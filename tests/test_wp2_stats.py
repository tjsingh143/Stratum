"""WP2: F distribution and diagnostics (DECISIONS.md D-044, D-049).

The F survival function is checked against every (F, df, p) triple stored in
reference/r_outputs to the tolerance fixed in D-049 before it was run (relative
error <= 1e-8), and against closed forms. Diagnostic values are hand-worked.
"""
import json
import math
import unittest
from fractions import Fraction as Q
from pathlib import Path

from stratum import stats
from stratum.exact import Design

ROOT = Path(__file__).resolve().parents[1]
REL_TOL = 1e-8          # D-049, fixed before any comparison was run


def r_f_tests():
    """(file, term, F, df1, df2, p) for every stored F test with a p-value."""
    def lists(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from lists(v)
        elif isinstance(o, list):
            if o and all(isinstance(x, dict) for x in o):
                yield o
            for v in o:
                yield from lists(v)
    out = []
    for path in sorted((ROOT / "reference" / "r_outputs").glob("*.json")):
        for rows in lists(json.loads(path.read_text())):
            resid = {r.get("stratum"): r["df"] for r in rows
                     if r.get("term") == "Residuals" and "df" in r}
            for r in rows:
                if r.get("F") is None or r.get("p") is None:
                    continue
                if "num_df" in r:
                    d1, d2 = r["num_df"], r["den_df"]
                else:
                    d1, d2 = r["df"], resid[r.get("stratum")]
                out.append((path.name, r["term"], r["F"], d1, d2, r["p"]))
    return out


class FDistribution(unittest.TestCase):
    def test_against_every_stored_r_f_test(self):
        tests = r_f_tests()
        self.assertGreaterEqual(len(tests), 19)
        for name, term, f, d1, d2, p in tests:
            with self.subTest(file=name, term=term, df=(d1, d2)):
                self.assertLessEqual(abs(stats.f_sf(f, d1, d2) - p) / p, REL_TOL)

    def test_closed_forms(self):
        # F(2, d2): P(F > f) = (1 + 2f/d2)^(-d2/2).
        for f, d2 in ((3.0, 10), (0.5, 4), (12.0, 7)):
            self.assertAlmostEqual(stats.f_sf(f, 2, d2), (1 + 2 * f / d2) ** (-d2 / 2), 13)
        # F(1, 1) = t(1)^2 (Cauchy): P(F > f) = 1 - (2/pi) atan(sqrt f).
        self.assertAlmostEqual(stats.f_sf(3.0, 1, 1), 1 - 2 / math.pi * math.atan(math.sqrt(3)), 13)
        self.assertEqual(stats.f_sf(0.0, 3, 5), 1.0)
        self.assertEqual(stats.f_sf(math.inf, 3, 5), 0.0)

    def test_incomplete_beta_identities(self):
        self.assertAlmostEqual(stats.betainc(1, 1, 0.3), 0.3, 14)
        self.assertAlmostEqual(stats.betainc(2.5, 4, 0.2) + stats.betainc(4, 2.5, 0.8), 1, 14)


def c(n, step=Q(1)):
    return [Q(2 * i - (n - 1), 2) * step for i in range(n)]


def one_way(groups):
    rows = [(0, 1 + g) for g, grp in enumerate(groups) for _ in grp]
    return [v for grp in groups for v in grp], Design(rows, 1 + len(groups))


class BrownForsythe(unittest.TestCase):
    def test_hand_value(self):
        # |dev| from medians: group 1 (2.5,1.5,.5,.5,1.5,2.5) mean 1.5, SS 4; group 2 x4:
        # mean 6, SS 64. SSB = 6*2*2.25^2 = 60.75, MSW = 68/10. F = 60.75/6.8 = 1215/136.
        res = stats.brown_forsythe([c(6), c(6, Q(4))])
        self.assertAlmostEqual(res["F"], 1215 / 136, 12)
        self.assertEqual(res["df"], [1, 10])
        self.assertTrue(res["warn"])
        self.assertAlmostEqual(res["p"], stats.f_sf(1215 / 136, 1, 10), 15)

    def test_identical_spread_gives_zero(self):
        res = stats.brown_forsythe([c(4), [v + 10 for v in c(4)]])
        self.assertEqual(res["F"], 0.0)
        self.assertEqual(res["p"], 1.0)
        self.assertFalse(res["warn"])

    def test_balanced_two_per_group_is_unavailable(self):
        # Each pair's two |deviations| from its median are equal: within SS = 0.
        res = stats.brown_forsythe([[Q(1), Q(3)], [Q(0), Q(10)]])
        self.assertFalse(res["available"])
        self.assertIn("zero denominator", res["reason"])

    def test_a_group_of_two_does_not_by_itself_make_it_unavailable(self):
        # D-055: availability follows the denominator. Groups (1, 3) and (0, 2, 7):
        # z = (1, 1) and (2, 0, 5); within SS = 0 + (1/9 + 49/9 + 64/9) = 38/3 > 0.
        # zbar = 1 and 7/3, grand 9/5: SSB = 2(4/5)^2 + 3(8/15)^2 = 32/15.
        # F = (32/15 / 1) / (38/3 / 3) = 48/95.
        res = stats.brown_forsythe([[Q(1), Q(3)], [Q(0), Q(2), Q(7)]])
        self.assertTrue(res["available"])
        self.assertEqual(res["df"], [1, 3])
        self.assertAlmostEqual(res["F"], 48 / 95, 14)

    def test_completely_degenerate_is_unavailable(self):
        res = stats.brown_forsythe([[Q(5)] * 3, [Q(5)] * 3])
        self.assertFalse(res["available"])
        res = stats.brown_forsythe([[Q(1)], [Q(2)]])          # N - t = 0
        self.assertFalse(res["available"])

    def test_one_group_unavailable(self):
        self.assertFalse(stats.brown_forsythe([c(5)])["available"])


class SdRatio(unittest.TestCase):
    def test_exact_threshold(self):
        self.assertTrue(stats.sd_ratio([c(4), c(4, Q(2))])["warn"])          # exactly 2: warn
        self.assertFalse(stats.sd_ratio([c(4), c(4, Q(199, 100))])["warn"])  # 1.99: no warn
        self.assertEqual(stats.sd_ratio([c(4), c(4, Q(4))])["ratio"], 4.0)
        self.assertFalse(stats.sd_ratio([c(4), c(4)])["warn"])

    def test_zero_sd(self):
        res = stats.sd_ratio([[Q(5)] * 4, c(4)])
        self.assertEqual(res["ratio"], "infinite")
        self.assertTrue(res["warn"])
        res = stats.sd_ratio([[Q(5)] * 3, [Q(7)] * 3])
        self.assertEqual(res["ratio"], "undefined")
        self.assertTrue(res["warn"])

    def test_needs_two_estimable_groups(self):
        self.assertFalse(stats.sd_ratio([c(4), [Q(1)]])["available"])


class Studentized(unittest.TestCase):
    def test_outlier_hand_value(self):
        # Two groups of 8, deviations (-0.5 x 7, 3.5): s^2 = 28/14 = 2, h = 1/8,
        # r^2 = 12.25 / (2 * 7/8) = 7, t^2 = 7 * 13 / (14 - 7) = 13.
        g = [Q(-1, 2)] * 7 + [Q(7, 2)]
        y, d = one_way([g, [v + 4 for v in g]])
        res = stats.studentized(y, d)
        self.assertAlmostEqual(res["max_abs_external"], math.sqrt(13), 12)
        self.assertTrue(res["warn"])
        self.assertEqual(res["residual_df"], 14)
        # the internal residual alone would be sqrt(7) = 2.65 and not flag (D-044 reading 2)
        self.assertAlmostEqual(max(abs(u["internal"]) for u in res["units"]), math.sqrt(7), 12)

    def test_threshold_is_strict(self):
        # (-0.5 x 5, 2.5) twice: s^2 = 15/10, h = 1/6, r^2 = 5, t^2 = 5 * 9 / 5 = 9 exactly.
        g = [Q(-1, 2)] * 5 + [Q(5, 2)]
        y, d = one_way([g, g])
        res = stats.studentized(y, d)
        self.assertAlmostEqual(res["max_abs_external"], 3.0, 12)
        self.assertFalse(res["warn"])

    def test_benign(self):
        y, d = one_way([c(5), c(5)])
        res = stats.studentized(y, d)       # t^2 = 2 * 7 / 6 = 7/3
        self.assertAlmostEqual(res["max_abs_external"], math.sqrt(7 / 3), 12)
        self.assertFalse(res["warn"])

    def test_unavailable(self):
        y, d = one_way([[Q(1)], [Q(2), Q(4)]])        # n 3 - rank 2 = 1 df
        self.assertFalse(stats.studentized(y, d)["available"])
        y, d = one_way([[Q(1)] * 3, [Q(2)] * 3])      # zero residuals
        self.assertFalse(stats.studentized(y, d)["available"])

    def test_zero_deleted_variance_is_undefined_not_infinite(self):
        # D-055. Groups (0, 0, 0) and (-1, 1): deleting either unit of the second group
        # leaves every residual zero, so its deleted variance is 0 (r^2 = nu = 3).
        y, d = one_way([[Q(0)] * 3, [Q(-1), Q(1)]])
        res = stats.studentized(y, d)
        self.assertTrue(res["available"])
        self.assertEqual(res["undefined_units"], ["3", "4"])
        self.assertFalse(res["warn"])
        self.assertTrue(all(u["external"] is None for u in res["units"][3:]))
        self.assertEqual([u["external"] for u in res["units"][:3]], [0.0] * 3)

    def test_normal_quantiles(self):
        q = stats.blom_quantiles(5)
        self.assertAlmostEqual(q[2], 0.0, 14)
        self.assertAlmostEqual(q[0], -q[4], 14)
        self.assertEqual(stats.blom_quantiles(1), [0.0])
        y, d = one_way([c(5), c(5)])
        nq = stats.studentized(y, d)["normal_quantiles"]
        self.assertEqual(len(nq["theoretical"]), 10)
        self.assertEqual(nq["internally_studentized_sorted"],
                         sorted(nq["internally_studentized_sorted"]))


if __name__ == "__main__":
    unittest.main()
