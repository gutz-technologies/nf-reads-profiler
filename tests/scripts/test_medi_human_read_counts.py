"""Validate downstream human counts and threshold/missingness semantics."""
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "medi_human_read_counts", Path(__file__).resolve().parents[2] / "bin/medi_human_read_counts.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TestHumanReadCounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for level in ("D", "G", "S"):
            (self.root / level).mkdir()
        self.output = self.root / "human.csv"

    def table(self, sample, records, level="S"):
        path = self.root / level / f"{level}_{sample}.b2"
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["name", "taxonomy_id", "taxonomy_lvl", "kraken_assigned_reads", "added_reads", "new_est_reads", "fraction_total_reads"])
            writer.writerows(records)

    def test_uses_assigned_count_once_per_sample(self):
        self.table("a_b", [["Homo sapiens", 9606, "S", 12, 8, 20, 0.5],
                           ["Other species", 123, "S", 20, 0, 20, 0.5]])
        self.table("a_b", [], level="G")
        rows = MODULE.collate(self.root, self.output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sample_id"], "a_b")
        self.assertEqual(rows[0]["kraken_assigned_human_read_ends"], 12)
        self.assertEqual(rows[0]["status"], "reported")

    def test_unreported_empty_and_missing_are_not_zero(self):
        self.table("unreported", [["Other species", 123, "S", 20, 0, 20, 1]])
        (self.root / "S/S_empty.b2").touch()
        (self.root / "D/D_missing.b2").touch()
        rows = {r["sample_id"]: r for r in MODULE.collate(self.root, self.output)}
        self.assertEqual(rows["unreported"]["status"], "human_taxon_not_reported")
        self.assertEqual(rows["empty"]["status"], "empty_species_table")
        self.assertEqual(rows["missing"]["status"], "missing_species_table")
        self.assertTrue(all(r["kraken_assigned_human_read_ends"] == "NA" for r in rows.values()))

    def test_invalid_or_duplicate_human_rows_fail_before_output(self):
        for value in ("NaN", "-1", "1.5", "bad"):
            self.table("bad", [["Homo sapiens", 9606, "S", value, 0, 0, 0]])
            with self.assertRaises(ValueError):
                MODULE.collate(self.root, self.output)
            self.assertFalse(self.output.exists())
        row = ["Homo sapiens", 9606, "S", 12, 0, 12, 1]
        self.table("bad", [row, row])
        with self.assertRaises(ValueError):
            MODULE.collate(self.root, self.output)


if __name__ == "__main__":
    unittest.main()
