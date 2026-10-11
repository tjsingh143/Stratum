"""WP3: the frozen comparison map is complete, well formed, and matches its generator
(DECISIONS.md D-061).

These tests check form only. Whether Stratum agrees with a reference value is checked by
tests/test_wp3_reproduction.py, which runs the map.
"""
import csv
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
MAP_PATH = VALIDATION / "wp3_comparison_map.json"
REF_CSV = ROOT / "reference" / "reference_numbers.csv"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


builder = _load(VALIDATION / "build_wp3_map.py", "build_wp3_map")
MAP = json.loads(MAP_PATH.read_text())


class MapForm(unittest.TestCase):
    def test_matches_generator(self):
        built = json.dumps(builder.build(), indent=2, sort_keys=False) + "\n"
        self.assertEqual(MAP_PATH.read_text(), built,
                         "wp3_comparison_map.json differs from build_wp3_map.py")

    def test_covers_every_reference_row_exactly_once(self):
        with REF_CSV.open(newline="") as fh:
            ids = [r["id"] for r in csv.DictReader(fh)]
        self.assertEqual(len(ids), len(set(ids)))
        mapped = [r["id"] for r in MAP["reference_rows"]]
        self.assertEqual(sorted(ids), sorted(mapped))
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertEqual(MAP["rows"], len(ids))

    def test_classes_are_known_and_targets_consistent(self):
        for row in MAP["reference_rows"]:
            self.assertIn(row["class"], builder.CLASSES, row["id"])
            report_only = row["class"] in ("OUT_OF_SCOPE", "NOT_OBTAINED")
            self.assertEqual(row["target"] is None, report_only, row["id"])
            if report_only:
                self.assertTrue(row["note"], "%s needs a recorded reason" % row["id"])
            else:
                for field in ("dataset", "kind", "key", "field"):
                    self.assertIn(field, row["target"], row["id"])

    def test_pass_fail_rows_have_a_numeric_or_structural_reference(self):
        for row in MAP["reference_rows"]:
            if row["class"] not in builder.PASS_FAIL:
                continue
            value = row["ref"]["value"]
            if row["class"] == "STRUCTURAL":
                self.assertIsInstance(value, str, row["id"])
                continue
            if row["ref"]["source"] == "printed":
                self.assertIsNotNone(row["printed_decimal_place"], row["id"])
                float(str(value).replace(",", ""))
            else:
                self.assertIsInstance(value, (int, float), row["id"])

    def test_not_obtained_rows_are_the_three_recorded_ones(self):
        got = sorted(r["id"] for r in MAP["reference_rows"]
                     if r["class"] == "NOT_OBTAINED")
        self.assertEqual(got, ["O19", "O20", "S06"])
        for r in MAP["reference_rows"]:
            if r["class"] == "NOT_OBTAINED":
                self.assertEqual(r["printed_value"].strip(), "")

    def test_every_dataset_key_is_one_of_the_frozen_six(self):
        allowed = {"furnace", "oxide", "semiconductor", "lithography",
                   "oxide_source_kernel", "semiconductor_wholeplot_kernel"}
        for row in MAP["reference_rows"] + MAP["extra_checks"]:
            if row.get("target"):
                self.assertIn(row["target"]["dataset"], allowed)

    def test_kernel_rows_say_they_are_kernel_checks(self):
        for row in MAP["reference_rows"] + MAP["extra_checks"]:
            target = row.get("target")
            if target and target["dataset"].endswith("_kernel"):
                self.assertIn("kernel cross-check", row["note"],
                              "a kernel row must label itself (D-067): %r" % row)

    def test_out_of_scope_rows_cite_a_decision(self):
        for row in MAP["reference_rows"]:
            if row["class"] == "OUT_OF_SCOPE":
                self.assertRegex(row["note"], r"D-0\d\d|Section 5\.1")

    def test_extra_checks_are_full_precision_only(self):
        self.assertTrue(MAP["extra_checks"])
        for row in MAP["extra_checks"]:
            self.assertEqual(row["ref"]["source"], "r_outputs")
            self.assertIn(row["class"], ("EXACT", "ITERATIVE"))
            self.assertIsInstance(row["ref"]["value"], (int, float))


class DecimalPlace(unittest.TestCase):
    def test_known_cases(self):
        for text, want in [("571.659", 3), ("10,155", 0), ("3.85e-11", 13),
                           ("0.0000001", 7), ("20", 0), ("-10.1", 1),
                           ("1.393903e-07", 13), ("0.0500", 4)]:
            self.assertEqual(builder.decimal_place(text), want, text)

    def test_non_numeric_has_no_printed_precision(self):
        self.assertIsNone(builder.decimal_place("3072.11 = (4*2)*Var(Run) + ..."))
        self.assertIsNone(builder.decimal_place("  "))


if __name__ == "__main__":
    unittest.main()
