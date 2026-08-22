#!/usr/bin/env python3
"""Join per-sample read counts with per-sample profile_taxa/profile_function
runtime, pulled from a Nextflow trace file.

Trace lives at <outdir>/<project>/reports/<ts>_trace.txt; readcounts at
<outdir>/<project>/<run>/readcount/<id>_readcount.txt (see README output
layout). Only COMPLETED trace rows are used; samples missing a given
process's time get an empty cell, not a dropped row.
"""

import argparse
import csv
import glob
import os
import re


def parse_time(t):
    if t.strip() == "-":
        return None
    total = 0.0
    for val, unit in re.findall(r"(\d+(?:\.\d+)?)([hms])", t):
        val = float(val)
        total += val * 3600 if unit == "h" else val * 60 if unit == "m" else val
    return total / 60


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", required=True, help="path to <ts>_trace.txt")
    ap.add_argument("--readcount-dir", required=True,
                     help="path to <outdir>/<project>/<run>/readcount/")
    ap.add_argument("--out", required=True, help="output TSV path")
    args = ap.parse_args()

    runtimes = {}
    with open(args.trace) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            m = re.match(r"(profile_taxa|profile_function) \((.+)\)$", row["name"])
            if not m or row["status"] != "COMPLETED":
                continue
            proc, sample = m.groups()
            mins = parse_time(row["realtime"])
            if mins is None:
                continue
            runtimes.setdefault(sample, {})[proc] = mins

    readcounts = {}
    for path in glob.glob(os.path.join(args.readcount_dir, "*_readcount.txt")):
        sample = os.path.basename(path).replace("_readcount.txt", "")
        with open(path) as f:
            readcounts[sample] = int(f.read().strip())

    with open(args.out, "w") as f:
        f.write("sample\treadcount\tprofile_taxa_min\tprofile_function_min\n")
        for sample in sorted(readcounts):
            rt = runtimes.get(sample, {})
            f.write(f"{sample}\t{readcounts[sample]}\t"
                    f"{rt.get('profile_taxa', '')}\t{rt.get('profile_function', '')}\n")

    print(f"rows: {len(readcounts)}")
    print(f"with profile_taxa time: {sum(1 for s in readcounts if 'profile_taxa' in runtimes.get(s, {}))}")
    print(f"with profile_function time: {sum(1 for s in readcounts if 'profile_function' in runtimes.get(s, {}))}")


if __name__ == "__main__":
    main()
