"""WP3: the published reproduction and the comparison against the stored R outputs.

These tests run the frozen comparison map (D-061) and assert the published numbers
PROJECT_BRIEF.md names directly, so a regression in the analysis cannot pass by also
changing the generated report. They need the fetched reference data in
reference/_fetched/derived/ (`python3 reference/fetch.py`); without it they are skipped.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "reference" / "_fetched" / "derived"
JSON_OUT = ROOT / "validation" / "wp3_reproduction.json"
MD_OUT = ROOT / "validation" / "WP3_REPRODUCTION.md"
HAVE_DATA = all((DERIVED / name).exists() for name in
                ("furnace.csv", "oxide.csv", "semiconductor.csv", "lithography.csv"))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load(ROOT / "validation" / "wp3_reproduce.py", "wp3_reproduce")


@unittest.skipUnless(HAVE_DATA, "run python3 reference/fetch.py first")
class Tolerances(unittest.TestCase):
    def test_classes_are_exactly_as_frozen(self):
        self.assertAlmostEqual(runner.tolerance("EXACT", 3072.11, 2), 1e-8 * 3072.11, 15)
        self.assertAlmostEqual(runner.tolerance("EXACT", 0.001, 6), 1e-8, 15)
        self.assertAlmostEqual(runner.tolerance("PRINTED", 571.659, 3), 0.0005, 15)
        self.assertAlmostEqual(runner.tolerance("PRINTED", 3.85e-11, 13), 0.5e-13, 25)
        # ITERATIVE is never tighter than PRINTED.
        self.assertAlmostEqual(runner.tolerance("ITERATIVE", 225.381, 3), 1e-4 * 225.381, 15)
        self.assertAlmostEqual(runner.tolerance("ITERATIVE", 11.4, 1), 0.05, 15)
        for ref, dp in ((225.381, 3), (11.4, 1), (0.04997, 5), (1.9415, 4)):
            self.assertGreaterEqual(runner.tolerance("ITERATIVE", ref, dp),
                                    runner.tolerance("PRINTED", ref, dp))

    def test_structural_class_has_no_numeric_tolerance(self):
        with self.assertRaises(ValueError):
            runner.tolerance("STRUCTURAL", 1.0, 2)

    def test_published_ems_equation_is_read_not_assumed(self):
        got = runner.parse_ems_equation(
            "3072.11 = (4*2)*Var(Run) + 2*Var(Furnace Location) + Var(Within)")
        self.assertEqual(got, [("Run", 8), ("Furnace Location", 2), ("Within", 1)])


@unittest.skipUnless(HAVE_DATA, "run python3 reference/fetch.py first")
class Reproduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = runner.run()

    def test_generated_outputs_match_the_generator(self):
        text = json.dumps(self.data, indent=2, sort_keys=False, allow_nan=False) + "\n"
        self.assertTrue(JSON_OUT.exists(), "run validation/wp3_reproduce.py")
        self.assertEqual(JSON_OUT.read_text(), text,
                         "wp3_reproduction.json is stale; rerun the generator")
        self.assertTrue(MD_OUT.exists())
        self.assertEqual(MD_OUT.read_text(), runner.markdown(self.data),
                         "WP3_REPRODUCTION.md is stale; rerun the generator")

    def test_no_lookup_errors(self):
        self.assertEqual(self.data["errors"], [])

    def test_every_reference_row_was_classified_and_acted_on(self):
        rows = self.data["reference_rows"]
        self.assertEqual(len(rows), 136)
        for r in rows:
            self.assertIn(r["status"], ("PASS", "FAIL", "REPORTED"), r["id"])

    def test_the_only_disagreement_is_the_recorded_lme4_constant(self):
        """Any new disagreement must be investigated and recorded, never tuned away."""
        got = []
        for r in self.data["disagreements"]:
            t = r["target"]
            got.append((r.get("id"), t["dataset"], t["kind"], t["key"], t["field"]))
        self.assertEqual(got, [(None, "semiconductor", "reml", "fit",
                                "minus2_restricted_loglik")],
                         "unexpected disagreement(s): %s" % got)

    def test_pass_counts(self):
        s = self.data["summary"]
        self.assertEqual(s["pass_fail_total"], s["passed"] + s["failed"])
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["passed"], s["pass_fail_total"] - 1)

    def test_published_furnace_table_is_reproduced(self):
        """brief Section 3.2, to reporting precision."""
        a = self.data["analyses"]["furnace"]
        anova = a["anova"]
        self.assertEqual([anova[k]["df"] for k in ("A", "B", "residual", "total")],
                         [20, 63, 84, 167])
        self.assertAlmostEqual(anova["A"]["ms"], 3072.11, 2)
        self.assertAlmostEqual(anova["B"]["ms"], 571.659, 3)
        self.assertAlmostEqual(anova["residual"]["ms"], 120.893, 3)
        self.assertAlmostEqual(anova["A"]["F"], 5.37404, 5)
        self.assertAlmostEqual(anova["B"]["F"], 4.72864, 5)
        vc = a["variance_components"]
        self.assertAlmostEqual(vc["A"]["mom"], 312.55694, 5)
        self.assertAlmostEqual(vc["B"]["mom"], 225.38294, 5)
        self.assertAlmostEqual(vc["residual"]["mom"], 120.89286, 5)
        self.assertEqual(anova["A"]["ems_coefficients"], {"A": 8, "B": 2, "residual": 1})

    def test_published_oxide_components(self):
        vc = self.data["analyses"]["oxide"]["variance_components"]
        self.assertAlmostEqual(vc["A"]["sd_mom"], 11.398, 3)
        self.assertAlmostEqual(vc["B"]["sd_mom"], 5.9888, 4)
        self.assertAlmostEqual(vc["residual"]["sd_mom"], 3.5453, 4)

    def test_semiconductor_degrees_of_freedom_are_the_brief_s_numbers(self):
        """brief Section 5.3: etch time on 3 and 8 df, position on 3 and 24,
        the interaction on 9 and 24; the naive analysis on 32."""
        a = self.data["analyses"]["semiconductor"]
        self.assertEqual((a["anova"]["A"]["num_df"], a["anova"]["A"]["den_df"]), (3, 8))
        self.assertEqual((a["anova"]["B"]["num_df"], a["anova"]["B"]["den_df"]), (3, 24))
        self.assertEqual((a["anova"]["AB"]["num_df"], a["anova"]["AB"]["den_df"]), (9, 24))
        self.assertEqual(a["naive_anova"]["residual"]["df"], 32)
        self.assertAlmostEqual(a["anova"]["A"]["F"], 1.9415, 4)
        self.assertAlmostEqual(a["anova"]["B"]["F"], 3.3855, 4)
        self.assertAlmostEqual(a["anova"]["AB"]["F"], 0.8092, 4)
        self.assertAlmostEqual(a["naive_anova"]["A"]["F"], 4.7819, 4)
        self.assertAlmostEqual(a["naive_anova"]["A"]["p"], 0.0073, 4)
        self.assertIn("WRONG", a["naive_anova"]["A"]["note"])

    def test_published_lithography_table(self):
        a = self.data["analyses"]["lithography"]
        self.assertEqual([a["anova"][k]["df"] for k in ("A", "B", "residual")],
                         [29, 60, 360])
        self.assertAlmostEqual(a["anova"]["A"]["ms"], 4.3932, 4)
        self.assertAlmostEqual(a["variance_components"]["B"]["mom"], 0.04997, 5)

    def test_published_warnings_are_carried_forward(self):
        """D-056: the lithography and Semiconductor warnings must appear."""
        decisions = {name: self.data["analyses"][name]["decision"]
                     for name in ("furnace", "oxide", "semiconductor", "lithography")}
        self.assertEqual(decisions, {"furnace": "ANALYZE", "oxide": "ANALYZE",
                                     "semiconductor": "WARN", "lithography": "WARN"})
        codes = {name: sorted({f["code"] for f in
                               self.data["analyses"][name]["evidence"]["findings"]})
                 for name in decisions}
        self.assertEqual(codes["lithography"], ["studentized_residual"])
        self.assertEqual(codes["semiconductor"], ["sd_ratio"])

    def test_reml_equals_the_moment_estimates_on_every_published_dataset(self):
        for name in ("furnace", "oxide", "semiconductor", "lithography"):
            a = self.data["analyses"][name]
            for key, v in a["variance_components"].items():
                self.assertTrue(v["reml_equals_mom"], (name, key))
                self.assertAlmostEqual(v["reml"], v["mom"], 10, (name, key))
            self.assertFalse(a["reml"]["fit"]["boundary"], name)
            self.assertEqual(a["reml"]["fit"]["pooled"], [], name)

    def test_oxide_restricted_loglikelihood_matches_nlme(self):
        a = self.data["analyses"]["oxide"]
        nlme = json.loads((ROOT / "reference" / "r_outputs" / "oxide.json").read_text())
        self.assertAlmostEqual(a["reml"]["fit"]["restricted_loglik"],
                               nlme["without_source"]["nlme_reml"]["logLik"], 8)

    def test_kernel_checks_reproduce_r(self):
        k1 = self.data["analyses"]["oxide_source_kernel"]
        self.assertAlmostEqual(k1["anova"]["treatment"]["F"], 1.52612275940338, 10)
        self.assertEqual((k1["anova"]["treatment"]["num_df"],
                          k1["anova"]["treatment"]["den_df"]), (1, 6))
        self.assertAlmostEqual(k1["estimate"]["contrast"]["estimate"],
                               -10.0833333333333, 10)
        self.assertAlmostEqual(k1["estimate"]["contrast"]["se"], 8.16224000727281, 5)
        k2 = self.data["analyses"]["semiconductor_wholeplot_kernel"]
        self.assertAlmostEqual(k2["anova"]["treatment"]["F"], 1.94154199272946, 10)
        self.assertEqual(k2["anova"]["treatment"]["den_df"], 8)

    def test_kernel_checks_are_labelled_as_kernel_checks_only(self):
        for name in ("oxide_source_kernel", "semiconductor_wholeplot_kernel"):
            k = self.data["analyses"][name]
            self.assertIn("not an analysis of this dataset as a T2 experiment",
                          k["kernel_label"])
            self.assertIn("D-014", k["kernel_label"])

    def test_every_fixture_is_gated_correctly(self):
        self.assertEqual(len(self.data["fixtures"]), 65)
        for f in self.data["fixtures"]:
            self.assertTrue(f["gating_ok"], f["fixture"])
        self.assertEqual(sum(1 for f in self.data["fixtures"] if f["analyzed"]), 26)

    def test_every_template_is_exercised_by_the_fixtures(self):
        templates = {f["template"] for f in self.data["fixtures"] if f["analyzed"]}
        self.assertEqual(templates, {"T1", "T2", "T3"})
        merged = [f for f in self.data["fixtures"]
                  if f["analyzed"] and "aliased_components" in f["codes"]]
        self.assertTrue(merged, "no fixture exercises the collapsed-stratum merge")
        missing = [f for f in self.data["fixtures"]
                   if "missing_sites_exception" in f["codes"]]
        self.assertTrue(missing, "no fixture exercises the missing-site exception")
        for f in missing:
            self.assertEqual(f["n_components"], 0)

    def test_supplementary_checks_all_pass_and_use_the_frozen_classes(self):
        """D-072: added after the freeze, scored under the same classes, counted apart."""
        sup = self.data["supplementary_checks"]
        self.assertEqual(len(sup), 40)
        self.assertEqual(self.data["summary"]["supplementary_passed"], len(sup))
        for r in sup:
            self.assertEqual(r["status"], "PASS", r["target"])
            self.assertIn(r["class"], ("EXACT", "ITERATIVE"))
            self.assertEqual(r["check"], "supplementary_check")
        self.assertNotIn(len(sup), (self.data["summary"]["pass_fail_total"],))

    def test_the_frozen_map_was_not_edited(self):
        """The committed map must still reproduce from its generator (D-072)."""
        import importlib.util as iu
        spec = iu.spec_from_file_location("bm", ROOT / "validation" / "build_wp3_map.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        stored = (ROOT / "validation" / "wp3_comparison_map.json").read_text()
        self.assertEqual(stored,
                         json.dumps(mod.build(), indent=2, sort_keys=False) + "\n")

    def test_every_stored_r_number_is_compared_or_has_a_recorded_reason(self):
        for stem, c in self.data["stored_r_output_coverage"].items():
            self.assertEqual(c["compared"] + len(c["not_compared"]), c["numeric_fields"],
                             stem)
            for row in c["not_compared"]:
                self.assertFalse(row["reason"].startswith("not compared;"),
                                 "%s has no recorded reason: %s" % (stem, row["path"]))

    def test_design_sizes_match_the_stored_r_design_blocks(self):
        want = {
            "furnace": ([21, 84, 168], ["a_runs", "b_zones_per_run",
                                        "n_wafers_per_zone"], [21, 4, 2]),
            "oxide": ([8, 24, 72], ["a_lots", "b_wafers_per_lot",
                                    "n_sites_per_wafer"], [8, 3, 3]),
            "lithography": ([30, 90, 450], ["a_cassettes", "b_wafers_per_cassette",
                                            "n_sites_per_wafer"], [30, 3, 5]),
        }
        for name, (units, keys, counts) in want.items():
            stored = json.loads((ROOT / "reference" / "r_outputs"
                                 / (name + ".json")).read_text())["design"]
            self.assertEqual([stored[k] for k in keys], counts, name)
            got = self.data["analyses"][name]["design"]
            self.assertEqual(got["units_per_level"], units, name)
            self.assertEqual(got["units_per_level"][0], counts[0], name)
            self.assertEqual(got["observations_per_unit"],
                             [counts[1] * counts[2], counts[2], 1], name)
        semi = json.loads((ROOT / "reference" / "r_outputs"
                           / "semiconductor.json").read_text())["design"]
        got = self.data["analyses"]["semiconductor"]["design"]
        self.assertEqual((semi["a_et_levels"], semi["r_wafers_per_et"],
                          semi["b_positions"]), (4, 3, 4))
        self.assertEqual((got["a"], got["b"], got["whole_plots"]), (4, 4, 12))
        self.assertEqual(set(got["replicates_per_level"].values()), {3})

    def test_fits_are_counted_including_zeros(self):
        s = self.data["summary"]
        for key in ("boundary_fits", "degenerate_fits", "failed_fits"):
            self.assertIsInstance(s[key], int)
        self.assertEqual(s["failed_fits"], 0)
        for name in ("furnace", "oxide", "semiconductor", "lithography"):
            self.assertEqual(self.data["analyses"][name]["fits"]["failed"], [])


if __name__ == "__main__":
    unittest.main()
