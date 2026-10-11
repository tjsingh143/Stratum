"""WP4 reassignment suggestion (DECISIONS.md D-080, D-081). All designs are SYNTHETIC."""
import hashlib
import math
import unittest
from fractions import Fraction as Q
from pathlib import Path

from stratum import reassign as ra
from stratum.allocation import planning
from stratum.analysis import analyze
from stratum.declaration import load_declaration, parse_declaration
from stratum.dist import chi2_quantile, t_quantile
from stratum.evidence import EvidenceResult, Finding

import designs
import wp4_helpers as H

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "fixtures" / "synthetic_wp2"
CHAMBER = {"name": "chamber", "column": "chamber", "recorded_at": "run", "role": "recorded",
           "levels": ["A", "B"]}


def run(decl_path, data_path, dsha="d" * 64, csha="c" * 64):
    res = analyze(decl_path, data_path)
    decl = res.evidence.match.declaration if res.evidence.match else None
    plan = planning(res.evidence, decl, data_path)
    return res, ra.suggestions(res.evidence, decl, dsha, csha, plan)


def produced(out):
    return [s for s in out["suggestions"] if s["status"] == "produced"]


class ConfoundedFixture(unittest.TestCase):
    """CONF-03: every 'low' run in chamber A, every 'high' run in B; r = 4, k = 2."""

    @classmethod
    def setUpClass(cls):
        cls.dp = FX / "CONF-03" / "declaration_synthetic.yaml"
        cls.cp = FX / "CONF-03" / "data_synthetic.csv"
        cls.res, cls.out = run(cls.dp, cls.cp)
        cls.s = produced(cls.out)[0]

    def test_crossed_and_balanced(self):
        s = self.s
        self.assertEqual((s["replicates_per_level"], s["units_per_cell"], s["total_units"]),
                         (4, 2, 8))
        self.assertEqual(s["extra_units_per_level"], 0)
        cells = {}
        for p in s["plan"]:
            cells[(p["treatment"], p["factor_level"])] = cells.get(
                (p["treatment"], p["factor_level"]), 0) + 1
        self.assertEqual(cells, {(t, c): 2 for t in ("low", "high") for c in ("A", "B")})

    def test_seed_is_derived_from_the_inputs(self):
        want = int(hashlib.sha256(("stratum-wp4-reassignment-v1|%s|%s|chamber"
                                   % ("d" * 64, "c" * 64)).encode()).hexdigest()[:16], 16)
        self.assertEqual(self.s["seed"], want)
        _, again = run(self.dp, self.cp)
        self.assertEqual(produced(again)[0]["plan"], self.s["plan"])
        _, other = run(self.dp, self.cp, csha="e" * 64)
        self.assertNotEqual(produced(other)[0]["seed"], self.s["seed"])

    def test_the_revised_declaration_matches_t2_with_a_block(self):
        self.assertTrue(self.s["revised_match"]["matched"])
        self.assertEqual(self.s["revised_match"]["template"], "T2")
        rev = parse_declaration(self.s["revised_declaration"]).declaration
        self.assertEqual(rev.treatments[0].replicates_per_level, 4)
        self.assertEqual(rev.treatments[0].assignment_method, "randomized")
        self.assertEqual([(f.name, f.role, f.crossed_with) for f in rev.nuisance_factors],
                         [("chamber", "block", "temp")])

    def test_exact_estimability_on_the_planned_layout(self):
        lc = self.s["layout_check"]
        self.assertTrue(lc["verified"])
        self.assertTrue(lc["proportional"])
        self.assertEqual([c["variance_ratio"] for c in lc["contrasts"]], [1])

    def test_what_it_estimates(self):
        e = self.s["estimates"]
        self.assertEqual((e["num_df"], e["den_df"]), (1, 2 * 4 - 2 - 2 + 1))

    def test_expected_precision_by_hand(self):
        """lambda_U = pooled within-cell MS of the unit means x m, with an exact interval."""
        import csv
        with self.cp.open() as fh:
            rows = list(csv.DictReader(fh))
        m = 3 * 5
        units = {}
        for r in rows:
            units.setdefault(r["run"], {"cell": (r["temp"], r["chamber"]), "y": []})
            units[r["run"]]["y"].append(Q(r["y"]))
        means = {u: sum(v["y"], Q(0)) / len(v["y"]) for u, v in units.items()}
        cells = {}
        for u, v in units.items():
            cells.setdefault(v["cell"], []).append(means[u])
        cmean = {c: sum(v, Q(0)) / len(v) for c, v in cells.items()}
        ss = m * sum((means[u] - cmean[v["cell"]]) ** 2 for u, v in units.items())
        nu = len(units) - len(cells)
        ms = ss / nu
        p = self.s["precision"]
        self.assertEqual(p["status"], "identified")
        self.assertEqual(p["lambda_unit_df"], nu)
        self.assertAlmostEqual(p["lambda_unit"], float(ms), 12)
        se = math.sqrt(2 * float(ms) / (4 * m))
        self.assertAlmostEqual(p["se"], se, 12)
        lo = nu * float(ms) / chi2_quantile(0.975, nu)
        hi = nu * float(ms) / chi2_quantile(0.025, nu)
        self.assertAlmostEqual(p["se_interval"][0], math.sqrt(2 * lo / (4 * m)), 12)
        self.assertAlmostEqual(p["se_interval"][1], math.sqrt(2 * hi / (4 * m)), 12)
        self.assertAlmostEqual(p["expected_half_width"], t_quantile(0.975, 5) * se, 12)
        self.assertAlmostEqual(p["se_from_components"], se, 12)
        self.assertIn("not results", p["label"])

    def test_the_refused_comparison_still_has_no_estimate(self):
        self.assertFalse(self.res.analyzed)
        self.assertEqual((self.res.anova, self.res.vc, self.res.estimate), ({}, {}, {}))


class Construction(H.TempDirCase, unittest.TestCase):
    def confounded(self, r, chambers):
        """chambers[level] -> list of chamber labels for that level's runs."""
        nz = dict(CHAMBER, levels=sorted({c for v in chambers.values() for c in v}))
        d = H.t2_declaration(r=r, w=2, s=2, nuisance=nz)
        rows = H.t2_rows(r=r, w=2, s=2, chamber_of=lambda lv, j: chambers[lv][j])
        return run(*H.write(self.tmp, d, rows))

    def test_r_not_divisible_by_k_rounds_up(self):
        _, out = self.confounded(3, {"low": ["A"] * 3, "high": ["B"] * 3})
        s = produced(out)[0]
        self.assertEqual((s["replicates_per_level"], s["extra_units_per_level"]), (4, 1))
        self.assertEqual(s["units_per_cell"], 2)
        self.assertTrue(s["revised_match"]["matched"])

    def test_unequal_cells_and_more_chambers_than_runs_per_cell(self):
        """'low' on A, A; 'high' on B, C. Chamber is not unit-unique (A holds two runs), so
        it enters the rank test and is completely confounded. Cells have 2, 1 and 1 runs:
        the pooled within-cell mean square is still exactly chi-square, on 4 - 3 = 1 df."""
        res, out = self.confounded(2, {"low": ["A", "A"], "high": ["B", "C"]})
        self.assertIn("complete_confounding", res.evidence.categories)
        s = produced(out)[0]
        self.assertEqual(s["factor_levels"], ["A", "B", "C"])
        self.assertEqual((s["replicates_per_level"], s["units_per_cell"]), (3, 1))
        self.assertEqual(s["estimates"]["den_df"], 2 * 3 - 2 - 3 + 1)
        self.assertTrue(s["layout_check"]["verified"])
        p = s["precision"]
        self.assertEqual(p["status"], "identified")
        self.assertEqual((p["lambda_unit_df"], p["unit_stratum"]["n_cells"]), (1, 3))

    def test_a_chamber_unique_to_each_run_is_not_confounding(self):
        """D-053: one chamber per run only renames the runs; nothing to reassign."""
        res, out = self.confounded(2, {"low": ["A", "B"], "high": ["C", "D"]})
        self.assertIn("nuisance_unit_unique", res.evidence.categories)
        self.assertEqual(out["status"], "not_applicable")

    def test_other_nuisance_factors_are_named_as_removed(self):
        day = {"name": "day", "column": "day", "recorded_at": "run", "role": "recorded"}
        d = H.t2_declaration(r=2, w=2, s=2, nuisance=CHAMBER)
        d["nuisance_factors"].append(day)
        rows = H.t2_rows(r=2, w=2, s=2, chamber_of=lambda lv, j: "A" if lv == "low" else "B",
                         extra=lambda lv, j: {"day": "d%d" % (j + 1)})
        _, out = run(*H.write(self.tmp, d, rows))
        s = produced(out)[0]
        self.assertEqual(s["removed_factors"], ["day"])
        self.assertEqual([f["name"] for f in s["revised_declaration"]["nuisance_factors"]],
                         ["chamber"])

    def test_factor_below_the_unit_is_not_reassigned(self):
        _, out = run(FX / "CONF-08" / "declaration_synthetic.yaml",
                     FX / "CONF-08" / "data_synthetic.csv")
        self.assertEqual(out["status"], "not_produced")
        self.assertIn("below the experimental unit", out["suggestions"][0]["reason"])

    def test_t3_is_not_reassigned(self):
        d = designs.t3()
        d["nuisance_factors"] = [{"name": "chamber", "column": "chamber",
                                  "recorded_at": "wafer", "role": "recorded"}]
        g = H.Lcg(3)
        rows = []
        for e in ("1", "2", "3", "4"):
            for j in range(3):
                for pos in ("1", "2", "3", "4"):
                    rows.append({"wafer": "W%s%d" % (e, j), "position": pos, "etch": e,
                                 "chamber": "C" + e, "y": "%.1f" % (50 + g(10) / 10.0)})
        res, out = run(*H.write(self.tmp, d, rows))
        self.assertIn("complete_confounding", res.evidence.categories)
        self.assertEqual(out["status"], "not_produced")
        self.assertIn("T2 assignments only", out["reason"])

    def test_trend_confounding_is_not_reassigned(self):
        decl = load_declaration(FX / "CONF-03" / "declaration_synthetic.yaml").declaration
        ev = EvidenceResult("T2", "REFUSE", (Finding("complete_confounding", "x", {
            "comparison": "high_vs_low", "nuisance": "chamber", "model": "linear trend"}),),
            (), {})
        out = ra.suggestions(ev, decl, "a", "b", None)
        self.assertEqual(out["suggestions"][0]["status"], "not_produced")
        self.assertIn("linear trend", out["suggestions"][0]["reason"])

    def test_nothing_to_reassign(self):
        _, out = run(FX / "REP-01" / "declaration_synthetic.yaml",
                     FX / "REP-01" / "data_synthetic.csv")
        self.assertEqual(out["status"], "not_applicable")

    def test_precision_unavailable_outside_the_planning_gate(self):
        _, out = run(FX / "BLK-03" / "declaration_synthetic.yaml",
                     FX / "BLK-03" / "data_synthetic.csv")
        s = produced(out)[0]
        self.assertEqual(s["precision"]["status"], "unavailable")
        self.assertIn("block_imbalance", s["precision"]["reason"])


class DeclarationRoundTrip(unittest.TestCase):
    def test_every_example_and_fixture_round_trips(self):
        paths = sorted((ROOT / "declarations" / "examples").glob("*.yaml")) + \
            sorted(FX.glob("*/declaration_synthetic.yaml"))
        n = 0
        for p in paths:
            parsed = load_declaration(p)
            if not parsed.ok:
                continue
            again = parse_declaration(ra.declaration_dict(parsed.declaration))
            self.assertTrue(again.ok, p)
            self.assertEqual(again.declaration, parsed.declaration, p)
            n += 1
        self.assertGreater(n, 60)


if __name__ == "__main__":
    unittest.main()
