"""WP3: the distribution and quantile functions (DECISIONS.md D-068).

Verified against exact closed forms and by round trip against the tail functions, never
against another implementation of the same approximation.
"""
import math
import unittest
from statistics import NormalDist

from stratum import dist

PROBS = (0.001, 0.025, 0.05, 0.1, 0.5, 0.9, 0.95, 0.975, 0.999)
DFS = (1, 2, 3, 4, 5, 8, 12, 24, 63, 84, 167, 360)


class ChiSquare(unittest.TestCase):
    def test_two_df_closed_form(self):
        # chi-square on 2 df is exponential with mean 2: cdf(x) = 1 - exp(-x/2).
        for p in PROBS:
            self.assertAlmostEqual(dist.chi2_quantile(p, 2), -2.0 * math.log1p(-p),
                                   delta=1e-10)

    def test_one_df_closed_form(self):
        nd = NormalDist()
        for p in PROBS:
            want = nd.inv_cdf((1.0 + p) / 2.0) ** 2
            self.assertAlmostEqual(dist.chi2_quantile(p, 1), want,
                                   delta=1e-9 * max(1.0, want))

    def test_cdf_round_trip(self):
        for nu in DFS:
            for p in PROBS:
                x = dist.chi2_quantile(p, nu)
                self.assertAlmostEqual(dist.chi2_cdf(x, nu), p, delta=1e-11)

    def test_sf_and_cdf_sum_to_one(self):
        for nu in DFS:
            for x in (0.5, 1.0, 5.0, 20.0, 100.0):
                self.assertAlmostEqual(dist.chi2_cdf(x, nu) + dist.chi2_sf(x, nu), 1.0,
                                       delta=1e-13)

    def test_fractional_df_is_supported(self):
        # Satterthwaite effective df are not whole numbers.
        for nu in (1.37, 2.5, 13.105261559783266, 37.9):
            for p in (0.025, 0.975):
                x = dist.chi2_quantile(p, nu)
                self.assertAlmostEqual(dist.chi2_cdf(x, nu), p, delta=1e-11)


class StudentT(unittest.TestCase):
    def test_one_df_is_cauchy(self):
        for p in (0.6, 0.75, 0.9, 0.95, 0.975, 0.995):
            self.assertAlmostEqual(dist.t_quantile(p, 1), math.tan(math.pi * (p - 0.5)),
                                   delta=1e-8)

    def test_two_df_closed_form(self):
        for p in (0.6, 0.75, 0.9, 0.95, 0.975, 0.995):
            a = 2.0 * p - 1.0
            self.assertAlmostEqual(dist.t_quantile(p, 2),
                                   a * math.sqrt(2.0 / (1.0 - a * a)), delta=1e-9)

    def test_symmetry_and_median(self):
        self.assertEqual(dist.t_quantile(0.5, 7), 0.0)
        for nu in DFS:
            self.assertAlmostEqual(dist.t_quantile(0.025, nu),
                                   -dist.t_quantile(0.975, nu), delta=1e-12)

    def test_two_sided_tail_round_trip(self):
        for nu in DFS:
            for p in (0.5, 0.1, 0.05, 0.01, 0.001):
                t = dist.t_quantile(1.0 - p / 2.0, nu)
                self.assertAlmostEqual(dist.t_sf_two_sided(t, nu), p, delta=1e-11)

    def test_large_df_approaches_the_normal(self):
        self.assertAlmostEqual(dist.t_quantile(0.975, 1e7), NormalDist().inv_cdf(0.975),
                               delta=1e-6)


class FDistribution(unittest.TestCase):
    def test_t_squared_is_f_on_one_df(self):
        for nu in DFS:
            t = dist.t_quantile(0.975, nu)
            self.assertAlmostEqual(t * t, dist.f_quantile(0.95, 1, nu),
                                   delta=1e-9 * max(1.0, t * t))

    def test_quantile_round_trip(self):
        for d1 in (1, 3, 9, 20, 63):
            for d2 in (2, 4, 8, 24, 84):
                for p in (0.05, 0.5, 0.95, 0.99):
                    f = dist.f_quantile(p, d1, d2)
                    self.assertAlmostEqual(dist.f_cdf(f, d1, d2), p, delta=1e-10)

    def test_reciprocal_relation(self):
        # F(d1, d2) upper p point is 1 / lower p point of F(d2, d1).
        for d1, d2 in ((3, 8), (9, 24), (20, 63)):
            self.assertAlmostEqual(dist.f_quantile(0.95, d1, d2),
                                   1.0 / dist.f_quantile(0.05, d2, d1), delta=1e-9)

    def test_known_closed_forms_are_unchanged_from_wp2(self):
        self.assertEqual(dist.f_sf(0.0, 3, 5), 1.0)
        self.assertEqual(dist.f_sf(math.inf, 3, 5), 0.0)
        self.assertAlmostEqual(dist.f_sf(3.0, 1, 1),
                               1 - 2 / math.pi * math.atan(math.sqrt(3)), 13)
        for d2 in (1, 4, 30):
            for f in (0.5, 2.0):
                self.assertAlmostEqual(dist.f_sf(f, 2, d2),
                                       (1 + 2 * f / d2) ** (-d2 / 2), 13)


class IncompleteGamma(unittest.TestCase):
    def test_exponential_closed_form(self):
        for x in (0.1, 1.0, 5.0, 20.0):
            self.assertAlmostEqual(dist.gammainc_p(1.0, x), 1.0 - math.exp(-x), 14)

    def test_p_plus_q_is_one(self):
        for a in (0.5, 1.0, 2.5, 10.0, 180.0):
            for x in (0.01, 1.0, 10.0, 200.0):
                self.assertAlmostEqual(dist.gammainc_p(a, x) + dist.gammainc_q(a, x),
                                       1.0, 13)

    def test_half_integer_matches_the_normal_tail(self):
        # P(1/2, x) = erf(sqrt(x)); chi-square on 1 df.
        for x in (0.25, 1.0, 4.0):
            self.assertAlmostEqual(dist.gammainc_p(0.5, x), math.erf(math.sqrt(x)), 13)


class Guards(unittest.TestCase):
    def test_probability_must_be_inside_the_unit_interval(self):
        for p in (0.0, 1.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                dist.chi2_quantile(p, 4)


if __name__ == "__main__":
    unittest.main()
