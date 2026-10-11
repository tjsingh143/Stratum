"""WP1: the example declarations match their template and do not misdescribe the data.

Declared columns and counts are cross-checked against reference/r_outputs/structure.json,
which WP0 generated from the files themselves (not from the brief). This is a test of
the examples' honesty, not a data check of the kind WP2 will implement.
"""
import json
import unittest
from pathlib import Path

from stratum.templates import evaluate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "declarations" / "examples"
STRUCTURE = json.loads((ROOT / "reference" / "r_outputs" / "structure.json").read_text())

EXPECTED = {
    "t1_nist_furnace.yaml": ("T1", "furnace"),
    "t1_memss_oxide.yaml": ("T1", "oxide"),
    "t1_nist_lithography.yaml": ("T1", "lithography"),
    "t2_illustrative_synthetic.yaml": ("T2", None),
    "t3_sasmixed_semiconductor.yaml": ("T3", "semiconductor"),
}


def result(name):
    return evaluate(EXAMPLES / name)


class ExamplesMatch(unittest.TestCase):
    def test_every_example_is_listed(self):
        self.assertEqual(sorted(p.name for p in EXAMPLES.glob("*.yaml")), sorted(EXPECTED))

    def test_each_matches_its_template(self):
        for name, (template, _) in EXPECTED.items():
            with self.subTest(example=name):
                res = result(name)
                self.assertEqual(res.matched_template, template, res.explain())

    def test_one_example_per_template(self):
        self.assertEqual({t for t, _ in EXPECTED.values()}, {"T1", "T2", "T3"})


class ExamplesAgreeWithReferenceFiles(unittest.TestCase):
    def check_columns(self, decl, dataset):
        cols = set(STRUCTURE[dataset]["columns"])
        used = {decl.response.column, *decl.id_columns,
                *(t.column for t in decl.treatments),
                *(f.column for f in decl.nuisance_factors)}
        self.assertLessEqual(used, cols)
        rows = 1
        for lv in decl.hierarchy:
            rows *= lv.count
        self.assertEqual(rows, STRUCTURE[dataset]["rows"])

    def test_furnace(self):
        d = result("t1_nist_furnace.yaml").declaration
        s = STRUCTURE["furnace"]
        self.check_columns(d, "furnace")
        self.assertEqual([lv.count for lv in d.hierarchy],
                         [len(s["runs"]), len(s["zones"]), len(s["wafers"])])
        # Zones are the same physical positions in every run (D-007).
        self.assertIs(d.level("zone").exchangeable, False)
        self.assertTrue(d.level("zone").exchangeable_declared)
        # Wafer exchangeability is not stated by the source: the default applies.
        self.assertFalse(d.level("wafer").exchangeable_declared)

    def test_oxide(self):
        d = result("t1_memss_oxide.yaml").declaration
        s = STRUCTURE["oxide"]
        self.check_columns(d, "oxide")
        self.assertEqual([lv.count for lv in d.hierarchy],
                         [len(s["lots"]), len(s["wafer_labels"]), len(s["sites"])])
        self.assertIsNone(d.response.units)
        # Source is recorded, not a treatment, and is constant within lot (D-014).
        self.assertEqual(d.treatments, ())
        (src,) = d.nuisance_factors
        self.assertEqual((src.column, src.role, src.recorded_at), ("Source", "recorded", "lot"))
        self.assertEqual(s["sources_per_lot"], 1)
        self.assertEqual(sorted(src.levels), sorted(s["sources"]))

    def test_lithography(self):
        d = result("t1_nist_lithography.yaml").declaration
        s = STRUCTURE["lithography"]
        self.check_columns(d, "lithography")
        self.assertEqual([lv.count for lv in d.hierarchy],
                         [s["cassettes"], len(s["wafers"]), len(s["sites"])])
        self.assertIs(d.level("site").exchangeable, False)
        self.assertTrue(d.level("site").exchangeable_declared)

    def test_semiconductor(self):
        d = result("t3_sasmixed_semiconductor.yaml").declaration
        s = STRUCTURE["semiconductor"]
        self.check_columns(d, "semiconductor")
        self.assertTrue(s["grp_equals_et_slash_wafer"])
        self.assertEqual(d.top.id_column, "Grp")
        self.assertEqual(d.top.count, s["grp_levels"])
        a = d.treatment(d.split_plot.whole_plot_factor)
        b = d.treatment(d.split_plot.subplot_factor)
        self.assertEqual(list(a.levels), s["et_levels"])
        self.assertEqual(list(b.levels), s["positions"])
        self.assertEqual(a.replicates_per_level, s["wafers_per_et"])
        self.assertEqual(s["obs_per_grp_position"], 1)
        # The declared structure gives the brief's Section 5.3 error df (8 and 24).
        n_a, r, n_b = len(a.levels), a.replicates_per_level, len(b.levels)
        self.assertEqual(n_a * (r - 1), 8)
        self.assertEqual(n_a * (r - 1) * (n_b - 1), 24)
        # Assignment of etch time is not stated in the documentation; not invented.
        self.assertEqual(a.assignment_method, "not_stated")
        self.assertEqual(b.assignment_method, "inherent")

    def test_t2_example_is_labeled_synthetic(self):
        path = EXAMPLES / "t2_illustrative_synthetic.yaml"
        self.assertIn("synthetic", path.name)
        d = result(path.name).declaration
        self.assertIn("synthetic", d.description.lower())
        self.assertIn("SYNTHETIC", path.read_text().splitlines()[0])


if __name__ == "__main__":
    unittest.main()
