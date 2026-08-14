#!/usr/bin/env python3
"""Build an nf-reads-profiler samplesheet from GEMMA stage-1 preprocessed output.

GEMMA arrives as multiple FASTQ lane-pairs per sample; `preprocess_gemma.nf`
(stage 1) merges each sample's lanes into one R1/R2 pair per sample and
uploads to:

    s3://gutz-nf-reads-profilers-workdir/preprocessed/gemma/<batch>/<sample>_R1.fastq.gz
    s3://gutz-nf-reads-profilers-workdir/preprocessed/gemma/<batch>/<sample>_R2.fastq.gz

where <batch> is "under8g" or "over8g" (see infra/gemma-onboarding-plan.md and
s3://gutz-nf-reads-profilers-runs/playbooks/gemma.md).

This script builds the stage-2 samplesheet FROM THE OBJECTS STAGE 1 ACTUALLY
WROTE (via `aws s3 ls --recursive` on the batch prefix) -- not from the
source manifest -- so a partial/interrupted stage-1 run can never produce a
samplesheet pointing at FASTQ pairs that don't exist yet.

Output columns match assets/schema_input.json: sample,fastq_1,fastq_2,study_accession
(study_accession is set to the batch name).

Usage:
    python bin/build_gemma_samplesheet.py --batch under8g --out gemma-under8g.csv
    python bin/build_gemma_samplesheet.py --batch over8g --out gemma-over8g.csv

This only reads S3 and writes a local CSV -- it never uploads. Review the CSV,
then a human operator copies it to
s3://gutz-nf-reads-profilers-runs/samplesheets/ before launching main.nf.
"""

import argparse
import csv
import re
import subprocess
import sys

BUCKET = "gutz-nf-reads-profilers-workdir"
PREFIX_TMPL = "preprocessed/gemma/{batch}/"

# <sample>_R1.fastq.gz / <sample>_R2.fastq.gz -- sample itself may contain
# underscores (e.g. GMA_018_l3), so anchor on the trailing _R{1,2}.fastq.gz.
NAME_RE = re.compile(r"^(?P<sample>.+)_R(?P<read>[12])\.fastq\.gz$")


def list_batch_objects(batch):
    """Return list of (key, size_bytes) under the batch's preprocessed prefix."""
    prefix = PREFIX_TMPL.format(batch=batch)
    s3_prefix = f"s3://{BUCKET}/{prefix}"
    proc = subprocess.run(
        ["aws", "s3", "ls", "--recursive", s3_prefix],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # Verified behavior: `aws s3 ls --recursive` on a prefix with ZERO
        # matching objects exits 1 with empty stdout AND empty stderr -- that
        # is the "batch not started yet" case, not an error. A real error
        # (bad creds, bad bucket, network) exits nonzero WITH stderr output.
        if not proc.stdout.strip() and not proc.stderr.strip():
            return []
        sys.stderr.write(f"ERROR: aws s3 ls failed (exit {proc.returncode}):\n{proc.stderr}\n")
        sys.exit(1)

    objects = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: "2026-08-14 12:00:00     123456 preprocessed/gemma/<batch>/<key>"
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        _date, _time, size, key = parts
        objects.append((key, int(size)))
    return objects


def pair_samples(objects, batch):
    """Group objects into {sample: {'1': key, '2': key}}; warn on stray files."""
    pairs = {}
    unmatched = []
    for key, size in objects:
        filename = key.rsplit("/", 1)[-1]
        m = NAME_RE.match(filename)
        if not m:
            unmatched.append(key)
            continue
        sample = m.group("sample")
        read = m.group("read")
        pairs.setdefault(sample, {})[read] = (key, size)

    return pairs, unmatched


def build_rows(pairs, batch):
    """Return (rows, missing_mate) where rows are complete R1+R2 samples."""
    rows = []
    missing_mate = []
    for sample in sorted(pairs):
        mates = pairs[sample]
        has_r1 = "1" in mates
        has_r2 = "2" in mates
        if has_r1 and has_r2:
            r1_key, _ = mates["1"]
            r2_key, _ = mates["2"]
            rows.append({
                "sample": sample,
                "fastq_1": f"s3://{BUCKET}/{r1_key}",
                "fastq_2": f"s3://{BUCKET}/{r2_key}",
                "study_accession": batch,
            })
        else:
            missing = "R2" if has_r1 else "R1"
            missing_mate.append((sample, missing))
    return rows, missing_mate


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", required=True, choices=["under8g", "over8g"],
                     help="GEMMA batch to build a samplesheet for")
    ap.add_argument("--out", required=True,
                     help="local path to write the samplesheet CSV")
    args = ap.parse_args()

    s3_prefix = f"s3://{BUCKET}/{PREFIX_TMPL.format(batch=args.batch)}"
    print(f"Listing {s3_prefix} ...")
    objects = list_batch_objects(args.batch)

    if not objects:
        print(f"No objects found under {s3_prefix}")
        print("Stage 1 (preprocess_gemma.nf) for this batch has not produced "
              "any output yet -- nothing to build. Not writing a samplesheet.")
        sys.exit(0)

    pairs, unmatched = pair_samples(objects, args.batch)
    rows, missing_mate = build_rows(pairs, args.batch)

    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sample", "fastq_1", "fastq_2", "study_accession"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {args.out}: {len(rows)} samples ({args.batch})")

    if missing_mate:
        print(f"WARNING: {len(missing_mate)} sample(s) missing a mate (excluded from sheet):")
        for sample, missing in missing_mate:
            print(f"  {sample}: missing {missing}")

    if unmatched:
        print(f"WARNING: {len(unmatched)} object(s) under the prefix did not match "
              f"the <sample>_R[12].fastq.gz naming pattern (ignored):")
        for key in unmatched:
            print(f"  {key}")

    if not rows:
        print("WARNING: 0 complete pairs found -- samplesheet has a header only.")


if __name__ == "__main__":
    main()
