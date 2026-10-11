"""Deterministic numerical regression checks; no synthetic WP6 outcomes."""
import json
import math
import unittest
from fractions import Fraction as Q
from stratum.dist import chi2_cdf, chi2_log_quantile, chi2_quantile
from stratum.analysis import ComponentGroup, variance_components

class SmallQuantiles(unittest.TestCase):
    def test_small_df_round_trip(self):
        for nu in (.4, .2, .1, .05):
            for p in (.025, .5, .975):
                self.assertAlmostEqual(chi2_cdf(chi2_quantile(p, nu), nu), p, delta=1e-12)

    def test_independent_small_x_integral_bounds(self):
        # Integrating e^-x between e^-x0 and 1 bounds P(a,x0) between
        # e^-x0*x0**a/Gamma(a+1) and x0**a/Gamma(a+1).
        for nu in (.2, .1, .01, .001):
            a = nu / 2
            lx = chi2_log_quantile(.025, nu) - math.log(2)
            upper = a*lx - math.lgamma(a+1)
            lower = upper - math.exp(lx)
            self.assertLessEqual(lower - 2e-14, math.log(.025))
            self.assertGreaterEqual(upper + 2e-14, math.log(.025))

    def test_tiny_component_keeps_interval_and_json_safe_endpoints(self):
        groups = [ComponentGroup(('A',), 2, 1, Q(10001, 10000), ('A',)),
                  ComponentGroup(('e',), 1, 2, Q(2), ('e',))]
        v = variance_components(groups, 1)['components']['A']
        self.assertTrue(v['interval_available'])
        self.assertEqual(v['interval_upper'], 'exceeds floating-point range')
        self.assertGreater(v['interval_log_upper'], 709)
        self.assertGreater(v['interval_log_lower'], math.log(v['mom']))
        json.dumps(v, allow_nan=False)

if __name__ == '__main__':
    unittest.main()
