#!/usr/bin/env python3
"""Report downstream, filtered Kraken-assigned human counts from Bracken inputs.

Absent taxid 9606 rows are not evidence of zero: Bracken thresholds taxa before
writing .b2 files. No original-library denominator is available here.
"""
import argparse
import csv
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path


def collate(bracken_dir, output):
    samples = set()
    for level in ("D", "G", "S"):
        for path in (bracken_dir / level).glob("*.b2"):
            if not path.name.startswith(level + "_"):
                raise ValueError(f"Unexpected Bracken filename: {path}")
            sample = path.name[len(level) + 1:-3]
            if not sample:
                raise ValueError(f"Empty sample ID: {path}")
            samples.add(sample)
    if not samples:
        raise ValueError(f"No D/G/S Bracken .b2 files in {bracken_dir}")

    rows = []
    for sample in sorted(samples):
        path = bracken_dir / "S" / f"S_{sample}.b2"
        count = "NA"
        status = "missing_species_table"
        if path.exists():
            status = "empty_species_table"
            if path.stat().st_size:
                status = "human_taxon_not_reported"
                with path.open(newline="") as handle:
                    reader = csv.DictReader(handle, delimiter="\t")
                    required = {"taxonomy_id", "taxonomy_lvl", "kraken_assigned_reads"}
                    if not required.issubset(reader.fieldnames or []):
                        raise ValueError(f"Missing Bracken columns: {path}")
                    for row in reader:
                        if row["taxonomy_id"] != "9606":
                            continue
                        if status == "reported":
                            raise ValueError(f"Duplicate human taxon row: {path}")
                        if row["taxonomy_lvl"] != "S":
                            raise ValueError(f"Human row is not species-level: {path}")
                        try:
                            number = Decimal(row["kraken_assigned_reads"])
                        except (InvalidOperation, TypeError):
                            raise ValueError(f"Invalid human count: {path}")
                        if not number.is_finite() or number < 0 or number != number.to_integral_value():
                            raise ValueError(f"Human count must be a nonnegative integer: {path}")
                        count, status = int(number), "reported"
        rows.append(dict(sample_id=sample, taxonomy_id=9606,
                         kraken_assigned_human_read_ends=count, status=status,
                         source_species_table=str(path.relative_to(bracken_dir)) if path.exists() else "NA"))

    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bracken_dir", type=Path, help="Directory containing D/, G/, S/ .b2 files")
    parser.add_argument("output", type=Path, help="Per-sample human read-count CSV")
    args = parser.parse_args()
    rows = collate(args.bracken_dir, args.output)
    total = sum(r["kraken_assigned_human_read_ends"] for r in rows if r["status"] == "reported")
    print(f"[collate_medi] filtered Kraken-assigned human read ends={total}; "
          f"sample statuses={dict(Counter(r['status'] for r in rows))}")


if __name__ == "__main__":
    main()
