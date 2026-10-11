"""WP4 allocation analysis (DECISIONS.md D-078, D-079, D-081). All designs are SYNTHETIC."""
import hashlib
import random
import statistics
import unittest
from fractions import Fraction as Q
from pathlib import Path

from stratum import allocation as al
from stratum.analysis import ComponentGroup, analyze, reml_isotonic

import wp4_helpers as H

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "fixtures" / "synthetic_wp2"


def fixture(fid):
    return FX / fid / "declaration_synthetic.yaml", FX / fid / "data_synthetic.csv"


def alloc_of(decl_path, data_path):
    res = analyze(decl_path, data_path)
    decl = res.evidence.match.declaration
    return res, al.allocation_for_analysis(res, decl)


def scen(comp, sid):
    return next(s for s in comp["scenarios"] if s["id"] == sid)


class TheFormula(unittest.TestCase):
    """V(r, w, s) = (2/r)(sigma2_R + sigma2_W/w + sigma2_S/(w s)), brief Section 5.5."""

    def model(self, comps=(Q(4), Q(2), Q(1)), m=(10, 5, 1)):
        # Build groups whose REML components are exactly `comps`: lambda_l = sum_j>=l m_j c_j.
        lam = [sum(mm * c for mm, c in zip(m[i:], comps[i:])) for i in range(3)]
        df = [6, 6, 48]
        strata = [(mm, d, l * d) for mm, d, l in zip(m, df, lam)]
        return al.model_from_strata(["unit", "sub1", "sub2"], ["run", "wafer", "site"],
                                    strata, "test")

    def test_hand_value(self):
        model = self.model()
        comps, _ = al.point_components(model)
        self.assertEqual(comps, [Q(4), Q(2), Q(1)])
        coefs = al._t2_coefs(3, [2, 5])
        lo, hi = al.bounds(model, coefs, comps)
        self.assertEqual(lo, hi)
        self.assertEqual(lo, Q(2, 3) * (Q(4) + Q(2, 2) + Q(1, 10)))      # = 3.4
        self.assertEqual(al.classify(model, coefs), "identified")

    def test_floor_is_two_sigma2_unit_over_r(self):
        model = self.model()
        comps, _ = al.point_components(model)
        lo, _ = al.bounds(model, al._t2_coefs(3, [al.INF, al.INF]), comps)
        self.assertEqual(lo, Q(2, 3) * 4)

    def test_only_more_units_lower_the_floor(self):
        model = self.model()
        comps, _ = al.point_components(model)
        floor = lambda r: al.bounds(model, al._t2_coefs(r, [al.INF, al.INF]), comps)[0]  # noqa
        self.assertLess(floor(4), floor(3))
        for w, s in ((2, 5), (3, 5), (2, 6), (50, 50)):
            self.assertGreater(al.bounds(model, al._t2_coefs(3, [w, s]), comps)[0], floor(3))

    def test_two_level_t2(self):
        coefs = al._t2_coefs(4, [3])
        self.assertEqual(coefs, [Q(1, 2), Q(1, 6)])


class PavaAgreesWithTheWp3Reml(unittest.TestCase):
    def test_float_and_exact_pava_match_reml_isotonic(self):
        rng = random.Random(5)
        for _ in range(300):
            k = rng.randint(1, 4)
            dfs = [rng.randint(1, 30) for _ in range(k)]
            ss = [Q(rng.randint(1, 900), rng.randint(1, 9)) for _ in range(k)]
            groups = [ComponentGroup(("g%d" % i,), 1, d, s, ("g",)) for i, (d, s)
                      in enumerate(zip(dfs, ss))]
            want = reml_isotonic(groups)
            self.assertEqual(al.pava_exact(dfs, ss), want)
            got = al.pava([float(d) for d in dfs], [float(s) for s in ss])
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, float(b), places=9)


class AnalyzedDesigns(unittest.TestCase):
    def test_current_se_equals_the_analysis_se(self):
        """D-078: with no REML pooling, the allocation's current value is the comparison SE."""
        for fid in ("REP-01", "BLK-01", "CONF-01", "DIAG-01", "HIER-01", "CONS-01"):
            res, out = alloc_of(*fixture(fid))
            self.assertFalse(res.reml["fit"]["pooled"], fid)
            se = next(e["se"] for e in res.estimate.values() if e.get("comparison"))
            self.assertAlmostEqual(scen(out["comparisons"][0], "current")["se"], se, 12, fid)

    def test_t3_current_ses_equal_the_analysis_ses(self):
        res, out = alloc_of(*fixture("T3-01"))
        by = {c["factor"]: c for c in out["comparisons"]}
        a, b = res.labels["A"], res.labels["B"]
        est = res.estimate
        se_a = next(e["se"] for e in est.values() if e.get("factor") == a)
        se_b = next(e["se"] for e in est.values() if e.get("factor") == b)
        se_ab = next(e["se"] for e in est.values() if e.get("factor") == "%s x %s" % (a, b))
        self.assertAlmostEqual(scen(by[a], "current")["se"], se_a, 12)
        self.assertAlmostEqual(scen(by[b], "current")["se"], se_b, 12)
        self.assertAlmostEqual(scen(by["%s x %s" % (a, b)], "current")["se"], se_ab, 12)
        self.assertEqual([s["id"] for s in by[b]["scenarios"]], ["current", "add_unit"])
        self.assertEqual(scen(by[b], "add_unit")["error_df"], 4 * 3 * 3)   # a r' (b - 1)

    def test_scenarios_counts_and_df(self):
        res, out = alloc_of(*fixture("REP-01"))
        inner = res.internal
        t, r, (w, s) = inner["t"], inner["r"], inner["counts"]
        comp = out["comparisons"][0]
        self.assertEqual([x["id"] for x in comp["scenarios"]],
                         ["current", "add_unit", "add_wafer", "add_site", "floor"])
        self.assertEqual(scen(comp, "add_unit")["added_measurements"], t * w * s)
        self.assertEqual(scen(comp, "add_wafer")["added_measurements"], t * r * s)
        self.assertEqual(scen(comp, "add_site")["added_measurements"], t * r * w)
        self.assertEqual(scen(comp, "current")["error_df"], t * (r - 1))
        self.assertEqual(scen(comp, "add_unit")["error_df"], t * r)
        self.assertEqual(scen(comp, "add_unit")["design"]["run_per_level"], r + 1)
        self.assertEqual(scen(comp, "floor")["design"]["wafer_per_parent"], "unlimited")

    def test_blocked_design_reports_the_next_balanced_crossing(self):
        res, out = alloc_of(*fixture("BLK-01"))
        k, t, r = res.internal["k_observed"], res.internal["t"], res.internal["r"]
        comp = out["comparisons"][0]
        add = scen(comp, "add_unit")
        bal = scen(comp, "add_unit_balanced")
        self.assertEqual(add["balanced"], (r + 1) % k == 0)
        self.assertEqual(bal["design"]["run_per_level"], r + k)
        self.assertEqual(scen(comp, "current")["error_df"], t * r - t - k + 1)
        self.assertIn("within a block", out["block_note"])

    def test_t1_and_missing_sites_are_not_allocated(self):
        _, out = alloc_of(*fixture("BAL-01"))
        self.assertEqual(out["status"], "not_applicable")
        _, out = alloc_of(*fixture("MISS-01"))
        self.assertEqual(out["status"], "withheld")
        self.assertIn("D-016", out["reason"])


class Identifiability(H.TempDirCase, unittest.TestCase):
    """D-054, D-078: w = 1 or s = 1 gives limited outputs, never an invented split."""

    def build(self, r, w, s):
        d, c = H.write(self.tmp, H.t2_declaration(r=r, w=w, s=s), H.t2_rows(r=r, w=w, s=s))
        return alloc_of(d, c)

    def test_one_wafer_per_run(self):
        res, out = self.build(3, 1, 4)
        comp = out["comparisons"][0]
        self.assertEqual(scen(comp, "current")["status"], "identified")
        self.assertEqual(scen(comp, "add_unit")["status"], "identified")
        self.assertEqual(scen(comp, "add_site")["status"], "identified")
        self.assertEqual(scen(comp, "add_wafer")["status"], "limited")
        self.assertEqual(scen(comp, "floor")["status"], "limited")
        self.assertIsNone(scen(comp, "add_wafer")["se"])
        merged = [c for c in out["components"] if c["merged"]]
        self.assertEqual(len(merged), 1)
        C = merged[0]["estimate"]
        site = next(c for c in out["components"] if not c["merged"])["estimate"]
        # Adding a wafer: (2/3)(sigma2_R + sigma2_W/2 + site/(2*4)); the split of C is
        # unknown, so the bounds are (2/3)(C/2 + site/8) and (2/3)(C + site/8).
        aw = scen(comp, "add_wafer")
        self.assertAlmostEqual(aw["se_lower"] ** 2, 2 / 3 * (C / 2 + site / 8), 10)
        self.assertAlmostEqual(aw["se_upper"] ** 2, 2 / 3 * (C + site / 8), 10)
        fl = scen(comp, "floor")
        self.assertEqual(fl["se_lower"], 0.0)
        self.assertAlmostEqual(fl["se_upper"] ** 2, 2 / 3 * C, 10)
        self.assertFalse(comp["ranking"]["assessed"])

    def test_one_site_per_wafer(self):
        res, out = self.build(3, 3, 1)
        comp = out["comparisons"][0]
        self.assertEqual(scen(comp, "floor")["status"], "identified")
        self.assertEqual(scen(comp, "add_wafer")["status"], "identified")
        self.assertEqual(scen(comp, "add_site")["status"], "limited")

    def test_one_wafer_and_one_site(self):
        res, out = self.build(3, 1, 1)
        comp = out["comparisons"][0]
        self.assertEqual(scen(comp, "current")["status"], "identified")
        self.assertEqual(scen(comp, "add_unit")["status"], "identified")
        for sid in ("add_wafer", "add_site", "floor"):
            self.assertEqual(scen(comp, sid)["status"], "limited", sid)
        se = next(e["se"] for e in res.estimate.values() if e.get("comparison"))
        self.assertAlmostEqual(scen(comp, "current")["se"], se, 12)


class PlausibleValues(unittest.TestCase):
    """D-079: fixed seed, fixed draw count, percentiles and the robustness rule."""

    def test_frozen_settings(self):
        self.assertEqual(al.N_DRAWS, 20000)
        self.assertEqual(al.ROBUST_WINS, 19000)
        self.assertEqual(al.SEED, int(hashlib.sha256(
            b"stratum-wp4-plausible-values-v1").hexdigest()[:16], 16))
        self.assertEqual(al.ROBUST_SENTENCE % "runs", "only additional runs lower the floor.")

    def test_draws_are_reproducible_and_follow_the_pivot(self):
        model = al.model_from_strata(["unit", "sub1"], ["run", "site"],
                                     [(4, 6, Q(60)), (1, 24, Q(24))], "test")
        a = al.plausible_components(model, n=50)
        b = al.plausible_components(model, n=50)
        self.assertEqual(a, b)
        # Reproduce the first draw by hand: lambda* = nu MS / (2 Gamma(nu/2)).
        rng = random.Random(al.SEED)
        l0 = 6 * 10.0 / (2 * rng.gammavariate(3.0, 1.0))
        l1 = 24 * 1.0 / (2 * rng.gammavariate(12.0, 1.0))
        lam = al.pava([6.0, 24.0], [6 * l0, 24 * l1])
        self.assertAlmostEqual(a[0][0], (lam[0] - lam[1]) / 4, 12)
        self.assertAlmostEqual(a[0][1], lam[1], 12)
        for d in a:
            self.assertGreaterEqual(d[0], 0.0)

    def test_percentiles(self):
        vals = [float(i) for i in range(1001)]
        q = statistics.quantiles(vals, n=40, method="inclusive")
        self.assertEqual(al._pct(vals), {"p2_5": al.sig6(q[0]), "p50": al.sig6(q[19]),
                                         "p97_5": al.sig6(q[38])})

    def test_robust_ranking_and_the_brief_sentence(self):
        _, out = alloc_of(*fixture("REP-01"))
        comp = out["comparisons"][0]
        rk = comp["ranking"]
        self.assertTrue(rk["assessed"])
        self.assertEqual(rk["draws"], 20000)
        self.assertEqual(sum(rk["wins"].values()) + rk["ties"], 20000)
        if rk["robust"]:
            self.assertGreaterEqual(rk["wins"][rk["best"]], 19000)
        if rk["robust"] and rk["best"] == "add_unit":
            self.assertEqual(comp["robust_conclusion"],
                             "Robust conclusion: only additional runs lower the floor.")
        self.assertIn("only additional runs lower it", comp["floor_statement"])

    def test_non_robust_ranking_is_said_plainly(self):
        """r = 5, w = 2: adding a run beats adding a wafer exactly when sigma2_W < 2
        sigma2_R. With sigma2_R = 1 and sigma2_W = 2 the point estimate sits on that line,
        so neither option can win 95% of plausible values."""
        # lambda_U = sigma2_W + 2 sigma2_R = 4 on t(r-1) = 8 df; lambda_W = 2 on 10 df.
        model = al.model_from_strata(["unit", "sub1"], ["run", "wafer"],
                                     [(2, 8, Q(32)), (1, 10, Q(20))], "test")
        spec = al.t2_specs(2, 5, [2], ["run", "wafer"], None, "temp")
        out = al.allocate(model, spec, "run", ["wafer"])
        comp = out["comparisons"][0]
        rk = comp["ranking"]
        self.assertTrue(rk["assessed"])
        self.assertFalse(rk["robust"])
        self.assertLess(max(rk["wins"].values()), 19000)
        self.assertIn("uncertain", comp["ranking_statement"])
        self.assertNotIn("robust_conclusion", comp)
        self.assertIn("only additional runs lower it", comp["floor_statement"])
        # At the point estimate the two options are exactly equal.
        self.assertAlmostEqual(scen(comp, "add_unit")["se"], scen(comp, "add_wafer")["se"], 12)


class PlanningPathway(H.TempDirCase, unittest.TestCase):
    """D-081: refused T2 designs get planning quantities only within the gate."""

    def plan_for(self, decl_path, data_path):
        res = analyze(decl_path, data_path)
        decl = res.evidence.match.declaration if res.evidence.match else None
        return res, decl, al.planning(res.evidence, decl, data_path)

    def test_unreplicated_data_give_lower_bounds_and_no_floor(self):
        res, decl, plan = self.plan_for(*fixture("REP-02"))
        self.assertFalse(res.analyzed)
        self.assertEqual(res.anova, {})                 # the WP3 gating is unchanged
        self.assertTrue(plan["eligible"])
        out = al.allocation_for_planning(plan, decl)
        self.assertEqual(out["status"], "planning")
        self.assertIn("not results", out["planning_label"])
        comp = out["comparisons"][0]
        for sid in ("current", "add_unit", "add_wafer", "add_site"):
            self.assertEqual(scen(comp, sid)["status"], "lower_bound", sid)
            self.assertIsNone(scen(comp, sid)["se_upper"])
        self.assertEqual(scen(comp, "floor")["status"], "not_estimable")
        self.assertIsNone(scen(comp, "floor")["se_lower"])
        self.assertFalse(comp["ranking"]["assessed"])
        self.assertIn("only additional runs lower it", comp["floor_statement"])
        self.assertEqual(out["unit_stratum_df"], 0)

    def test_declared_single_run_uses_planning_only_checks(self):
        res, decl, plan = self.plan_for(*fixture("DECL-01"))
        self.assertEqual(res.evidence.categories, ("declaration_refused",))
        self.assertTrue(plan["eligible"])
        self.assertEqual(plan["mode"], "planning_only_checks")
        self.assertIn("insufficient_replication",
                      {f["code"] for f in plan["planning_only_findings"]})
        self.assertEqual(res.decision, "REFUSE")          # the decision never changes

    def test_gate_refusals(self):
        cases = {"BAL-02": "outside the planning pathway",        # unbalanced_units
                 "BLK-03": "outside the planning pathway",        # block_imbalance
                 "T3-03": "T2 only",
                 "MISS-16": "T2 only",
                 "INT-01": "outside the planning pathway"}
        for fid, text in cases.items():
            _, _, plan = self.plan_for(*fixture(fid))
            self.assertFalse(plan["eligible"], fid)
            self.assertIn(text, plan["reason"], fid)

    def test_other_wp1_refusals_are_not_planned(self):
        d = H.t2_declaration(r=1, w=2, s=2)
        d["comparisons"] = []                              # a second WP1 failure
        dp, cp = H.write(self.tmp, d, H.t2_rows(r=1, w=2, s=2))
        _, _, plan = self.plan_for(dp, cp)
        self.assertFalse(plan["eligible"])
        self.assertIn("other than one unit per treatment level", plan["reason"])

    def test_complete_confounding_is_not_allocated(self):
        res, decl, plan = self.plan_for(*fixture("CONF-03"))
        self.assertTrue(plan["eligible"])
        out = al.allocation_for_planning(plan, decl)
        self.assertEqual(out["status"], "not_applicable")
        self.assertIn("reassignment", out["reason"])


if __name__ == "__main__":
    unittest.main()
