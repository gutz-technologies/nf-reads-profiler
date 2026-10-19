#!/usr/bin/env bash
# Local, read-only collation; see --help. No Docker, S3 writes, or profiling.
set -euo pipefail
exec python3 - "$@" <<'PY'
import argparse
import csv
import hashlib
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description="Collate KneadData read-end counts and measured post-trimming loss. Host-specific fractions remain NA without upstream filtering provenance; no microbial fraction is inferred.")
    p.add_argument("counts", type=Path, help="KneadData tab-delimited read count summary")
    p.add_argument("--cohort", required=True)
    p.add_argument("--reference", default="GRCh38_noalt_as", help="Exact decontaminated-stage reference label")
    p.add_argument("--samplesheet", type=Path, help="Optional pipeline CSV; all summary rows are retained and missing sheet samples appended")
    p.add_argument("--aliases", type=Path, help="Optional CSV with kneaddata_sample,sample columns; exact one-to-one mappings")
    p.add_argument("--output", type=Path, help="Output TSV (default stdout); refuses overwrite")
    a = p.parse_args()
    slots = ("pair1", "pair2", "orphan1", "orphan2")
    stages = {"raw": ["raw pair1", "raw pair2"],
              "trimmed": ["trimmed " + s for s in slots],
              "decontaminated": [f"decontaminated {a.reference} " + s for s in slots],
              "final": ["final " + s for s in slots]}
    count_columns = sum(stages.values(), [])
    digest = hashlib.sha256(a.counts.read_bytes()).hexdigest()
    with a.counts.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        expected = ["Sample"] + count_columns
        if reader.fieldnames != expected:
            raise ValueError("Unsupported count schema: expected exactly " + repr(expected))
        rows = list(reader)
    if not rows:
        raise ValueError("Empty count summary")

    aliases = {}
    if a.aliases:
        with a.aliases.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != ["kneaddata_sample", "sample"]:
                raise ValueError("Alias CSV needs kneaddata_sample,sample header")
            for row in reader:
                k, v = row["kneaddata_sample"], row["sample"]
                if not k or not v or k in aliases or v in aliases.values():
                    raise ValueError("Aliases must be nonempty and one-to-one")
                aliases[k] = v

    sheet = {}
    if a.samplesheet:
        with a.samplesheet.open(newline="") as f:
            reader = csv.DictReader(f)
            if not {"sample", "study_accession"}.issubset(reader.fieldnames or []):
                raise ValueError("Samplesheet needs sample and study_accession columns")
            for row in reader:
                key = row["sample"]
                if not key or key in sheet:
                    raise ValueError("Samplesheet sample IDs must be nonempty and unique")
                sheet[key] = row["study_accession"]

    results, seen, source_ids = [], set(), set()
    for line, row in enumerate(rows, 2):
        source = row["Sample"]
        if not source or source in source_ids or None in row or None in row.values():
            raise ValueError(f"Line {line}: duplicate/empty ID or malformed row")
        source_ids.add(source)
        sample = aliases.get(source, source.removesuffix("_R1_kneaddata"))
        if sample in seen:
            raise ValueError(f"Sample ID collision: {sample}")
        seen.add(sample)
        values, missing = {}, []
        for col in count_columns:
            token = row[col].strip()
            if token in ("", "NA"):
                values[col] = None
                missing.append(col)
                continue
            try:
                n = Decimal(token)
            except InvalidOperation:
                raise ValueError(f"Line {line}, {col}: invalid count {token!r}")
            if not n.is_finite() or n < 0 or n != n.to_integral_value():
                raise ValueError(f"Line {line}, {col}: count must be a finite nonnegative integer")
            values[col] = int(n)
        totals = {s: (sum(values[c] for c in cols) if all(values[c] is not None for c in cols) else None)
                  for s, cols in stages.items()}
        issues = []
        for s, cols in stages.items():
            x, y = (values[c] for c in cols[:2])
            if x is not None and y is not None and x != y:
                issues.append(s + "_unequal_pairs")
        for first, second in (("raw", "trimmed"), ("trimmed", "decontaminated"), ("decontaminated", "final")):
            x, y = totals[first], totals[second]
            if x is not None and y is not None and y > x:
                issues.append(second + "_exceeds_" + first)
        raw, trim, retained = (totals[s] for s in ("raw", "trimmed", "decontaminated"))
        removed = trim - retained if trim is not None and retained is not None and not issues else None
        frac_trim = removed / trim if removed is not None and trim else None
        # The raw denominator is usable only when the trimmed-to-raw relationship is known.
        frac_raw = removed / raw if removed is not None and raw and trim <= raw else None
        result = dict(cohort=a.cohort, sample=sample, kneaddata_sample=source,
                      study_accession=sheet.get(sample, "NA"),
                      coverage_status=("matched" if sample in sheet else "summary_only") if a.samplesheet else "not_checked",
                      measurement_status="invalid_counts" if issues else "missing_counts" if missing else "complete",
                      reference=a.reference, source_file=str(a.counts.resolve()), source_sha256=digest,
                      source_line=line, samplesheet=str(a.samplesheet.resolve()) if a.samplesheet else "NA",
                      id_match="explicit_alias" if source in aliases else "terminal_suffix_removed" if sample != source else "exact",
                      missing_columns=";".join(missing) or "NA", issues=";".join(issues) or "NA")
        result.update({c: values[c] for c in count_columns})
        result.update({s + "_read_ends": n for s, n in totals.items()})
        result.update(trimmed_to_decontaminated_removed_read_ends=removed,
                      trimmed_to_decontaminated_removed_fraction_of_trimmed=frac_trim,
                      trimmed_to_decontaminated_removed_fraction_of_raw=frac_raw,
                      host_attribution_status="unverified_intervening_filters_and_pair_policy",
                      host_reference_removed_fraction_of_trimmed=None,
                      host_reference_removed_fraction_of_raw=None)
        results.append(result)
    unused = set(aliases) - source_ids
    if unused:
        raise ValueError("Aliases absent from summary: " + repr(sorted(unused)))
    fields = list(results[0])
    for sample in sorted(set(sheet) - seen):
        result = {k: None for k in fields}
        result.update(cohort=a.cohort, sample=sample, study_accession=sheet[sample],
                      coverage_status="samplesheet_only", measurement_status="missing_summary",
                      reference=a.reference, source_file=str(a.counts.resolve()), source_sha256=digest,
                      samplesheet=str(a.samplesheet.resolve()))
        results.append(result)
    out = a.output.open("x", newline="") if a.output else sys.stdout
    try:
        writer = csv.DictWriter(out, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: "NA" if v is None else v for k, v in r.items()} for r in results)
    finally:
        if a.output:
            out.close()
    from collections import Counter
    print(f"{a.cohort}: coverage={dict(Counter(r['coverage_status'] for r in results))}; measurements={dict(Counter(r['measurement_status'] for r in results))}", file=sys.stderr)


try:
    main()
except (ValueError, OSError) as exc:
    sys.exit(f"ERROR: {exc}")
PY
