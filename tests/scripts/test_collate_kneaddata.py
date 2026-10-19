"""Exercise measured read-end loss, missingness, ID joins, and rejection paths."""
import csv
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "collate_kneaddata.sh"
SLOTS = ["pair1", "pair2", "orphan1", "orphan2"]
HEADER = ["Sample", "raw pair1", "raw pair2"] + [
    f"{stage} {slot}" for stage in ("trimmed", "decontaminated GRCh38_noalt_as", "final") for slot in SLOTS
]


class TestKneaddata(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_rows(self, rows, *args):
        path = self.root / "counts.tsv"
        with path.open("w", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(HEADER)
            w.writerows(rows)
        return subprocess.run(["bash", str(SCRIPT), str(path), "--cohort", "test", *map(str, args)], text=True, capture_output=True)

    def row(self, sample="a_R1_kneaddata"):
        # 200 raw ends, 180 trimmed, 170 retained. Orphans INCREASE as pairs break.
        return [sample, 100, 100, 80, 80, 15, 5, 70, 70, 25, 5, 70, 70, 25, 5]

    def parse(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return list(csv.DictReader(io.StringIO(proc.stdout), delimiter="\t"))

    def test_read_ends_and_denominators(self):
        r = self.parse(self.run_rows([self.row()]))[0]
        self.assertEqual(r["trimmed_to_decontaminated_removed_read_ends"], "10")
        self.assertAlmostEqual(float(r["trimmed_to_decontaminated_removed_fraction_of_trimmed"]), 10 / 180)
        self.assertAlmostEqual(float(r["trimmed_to_decontaminated_removed_fraction_of_raw"]), 0.05)
        self.assertEqual(r["host_reference_removed_fraction_of_trimmed"], "NA")

    def test_missing_is_not_zero_and_zero_denominators(self):
        missing = self.row("missing")
        missing[5] = "NA"
        zero = ["zero"] + [0] * 14
        rs = self.parse(self.run_rows([missing, zero]))
        self.assertEqual(rs[0]["trimmed_read_ends"], "NA")
        self.assertEqual(rs[0]["trimmed_to_decontaminated_removed_read_ends"], "NA")
        self.assertEqual(rs[1]["trimmed_to_decontaminated_removed_read_ends"], "0")
        self.assertEqual(rs[1]["trimmed_to_decontaminated_removed_fraction_of_trimmed"], "NA")

    def test_explicit_alias_and_outer_coverage(self):
        sheet = self.root / "sheet.csv"
        sheet.write_text("sample,study_accession\na,visit1\nabsent,visit2\n")
        aliases = self.root / "aliases.csv"
        aliases.write_text("kneaddata_sample,sample\na_CP05949_R1_kneaddata,a\n")
        rs = self.parse(self.run_rows([self.row("a_CP05949_R1_kneaddata"), self.row("extra")], "--samplesheet", sheet, "--aliases", aliases))
        self.assertEqual([r["coverage_status"] for r in rs], ["matched", "summary_only", "samplesheet_only"])
        self.assertEqual(rs[0]["id_match"], "explicit_alias")
        self.assertEqual(rs[2]["measurement_status"], "missing_summary")
        self.assertEqual(rs[2]["raw_read_ends"], "NA")

    def test_invalid_counts_and_duplicate_ids(self):
        row = self.row()
        row[1] = "NaN"
        self.assertNotEqual(self.run_rows([row]).returncode, 0)
        self.assertNotEqual(self.run_rows([self.row(), self.row()]).returncode, 0)
        row = self.row()
        row[7:11] = [100, 100, 25, 5]
        r = self.parse(self.run_rows([row]))[0]
        self.assertEqual(r["measurement_status"], "invalid_counts")
        self.assertEqual(r["trimmed_to_decontaminated_removed_read_ends"], "NA")

    def test_refuses_overwrite(self):
        dest = self.root / "out.tsv"
        dest.write_text("keep me")
        self.assertNotEqual(self.run_rows([self.row()], "--output", dest).returncode, 0)
        self.assertEqual(dest.read_text(), "keep me")


if __name__ == "__main__":
    unittest.main()
