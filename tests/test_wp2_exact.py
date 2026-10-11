"""WP2: exact rational linear algebra (DECISIONS.md D-045, D-049).

Every expected value below is worked by hand from the definitions, not taken from
the implementation.
"""
import unittest
from fractions import Fraction as Q

from stratum.exact import (Design, chi_square, cramers_v_squared, proportional, rank,
                           rref, solve)


def design(units, eff_levels, nuis_levels=None):
    """units: list of (effect, nuisance-or-None). Columns: 1, effect, nuisance."""
    E = len(eff_levels)
    rows = []
    for e, n in units:
        r = [0, 1 + eff_levels.index(e)]
        if nuis_levels:
            r.append(1 + E + nuis_levels.index(n))
        rows.append(r)
    return Design(rows, 1 + E + (len(nuis_levels) if nuis_levels else 0))


def contrast(eff_levels, hi, lo, n_nuis=0):
    c = [Q(0)] * (1 + len(eff_levels) + n_nuis)
    c[1 + eff_levels.index(hi)], c[1 + eff_levels.index(lo)] = Q(1), Q(-1)
    return c


class RankAndSolve(unittest.TestCase):
    def test_rank(self):
        self.assertEqual(rank([[1, 1, 0], [1, 0, 1], [0, 1, -1]]), 2)   # row3 = row1 - row2
        self.assertEqual(rank([[1, 0], [0, 1]]), 2)
        self.assertEqual(rank([[0, 0], [0, 0]]), 0)
        self.assertEqual(rank([[2, 4], [1, 2]]), 1)

    def test_rref_exact(self):
        m, piv = rref([[2, 1], [4, 3]])
        self.assertEqual(piv, [0, 1])
        self.assertEqual(m, [[1, 0], [0, 1]])

    def test_solve(self):
        a = [[Q(2), Q(1)], [Q(4), Q(2)]]
        x = solve(a, [Q(3), Q(6)])                  # consistent, rank 1
        self.assertEqual(2 * x[0] + x[1], 3)
        self.assertIsNone(solve(a, [Q(3), Q(7)]))  # inconsistent
        self.assertEqual(solve([[Q(1), Q(0)], [Q(0), Q(4)]], [Q(1), Q(2)]), [1, Q(1, 2)])


class Estimability(unittest.TestCase):
    """Treatment contrast with a nuisance factor included (D-045)."""
    L = ["low", "high"]

    def test_identical_partition_not_estimable(self):
        # low only in chamber A, high only in B: low = A and high = B as columns.
        d = design([("low", "A")] * 2 + [("high", "B")] * 2, self.L, ["A", "B"])
        self.assertFalse(d.estimable(contrast(self.L, "high", "low", 2)))
        # columns 1, low, high, A, B with low = A, high = B and 1 = low + high: rank 2
        self.assertEqual(d.rank, 2)

    def test_nested_partition_not_estimable(self):
        # 'low' in chambers A, B; 'high' in C, D. Partitions differ, rank still decides.
        units = [("low", "A"), ("low", "B"), ("high", "C"), ("high", "D")] * 2
        d = design(units, self.L, ["A", "B", "C", "D"])
        self.assertFalse(d.estimable(contrast(self.L, "high", "low", 4)))

    def test_crossed_estimable_without_inflation(self):
        units = [("low", "A"), ("low", "B"), ("high", "A"), ("high", "B")]
        full = design(units, self.L, ["A", "B"])
        trt = design([(e, None) for e, _ in units], self.L)
        q_full = full.quad(contrast(self.L, "high", "low", 2))
        q_trt = trt.quad(contrast(self.L, "high", "low"))
        # One unit per cell: adjusted information sum_j n1j n2j / n.j = 1/2 + 1/2 = 1.
        self.assertEqual(q_full, 1)
        self.assertEqual(q_trt, Q(1, 2) + Q(1, 2))
        self.assertEqual(q_full / q_trt, 1)

    def test_partial_confounding_variance_ratio(self):
        # Table [[3, 1], [1, 3]]. Adjusted information = 3*1/4 + 1*3/4 = 3/2 -> Var 2/3;
        # treatment-only Var = 1/4 + 1/4 = 1/2. Ratio 4/3, SE inflation sqrt(4/3).
        units = [("low", "A")] * 3 + [("low", "B")] + [("high", "A")] + [("high", "B")] * 3
        full = design(units, self.L, ["A", "B"])
        trt = design([(e, None) for e, _ in units], self.L)
        q_full = full.quad(contrast(self.L, "high", "low", 2))
        q_trt = trt.quad(contrast(self.L, "high", "low"))
        self.assertEqual(q_full, Q(2, 3))
        self.assertEqual(q_trt, Q(1, 2))
        self.assertEqual(q_full / q_trt, Q(4, 3))

    def test_proportional_unequal_is_not_inflated(self):
        # Each level: 2 units on d1, 1 on d2 -> proportional -> ratio exactly 1.
        units = [("low", "d1")] * 2 + [("low", "d2")] + [("high", "d1")] * 2 + [("high", "d2")]
        full = design(units, self.L, ["d1", "d2"])
        trt = design([(e, None) for e, _ in units], self.L)
        self.assertEqual(full.quad(contrast(self.L, "high", "low", 2)) /
                         trt.quad(contrast(self.L, "high", "low")), 1)

    def test_generalized_inverse_form_is_invariant(self):
        # The same design with columns permuted gives the same quadratic form.
        units = [("low", "A")] * 3 + [("low", "B")] + [("high", "A")] + [("high", "B")] * 3
        d1 = design(units, ["low", "high"], ["A", "B"])
        d2 = design(units, ["high", "low"], ["B", "A"])
        self.assertEqual(d1.quad(contrast(["low", "high"], "high", "low", 2)),
                         d2.quad(contrast(["high", "low"], "high", "low", 2)))


class LeverageAndFit(unittest.TestCase):
    def test_one_way_leverage_and_fit(self):
        d = design([("a", None)] * 4 + [("b", None)] * 2, ["a", "b"])
        self.assertEqual(d.leverages(), [Q(1, 4)] * 4 + [Q(1, 2)] * 2)
        self.assertEqual(sum(d.leverages()), d.rank)          # trace(H) = rank
        y = [Q(1), Q(2), Q(3), Q(6), Q(10), Q(20)]
        self.assertEqual(d.fitted(y), [Q(3)] * 4 + [Q(15)] * 2)  # group means

    def test_additive_two_way_leverage(self):
        # Balanced 2 x 2 additive, 2 units per cell: h = 1/n_trt + 1/n_blk - 1/n = 3/8.
        units = [("low", "A"), ("low", "A"), ("low", "B"), ("low", "B"),
                 ("high", "A"), ("high", "A"), ("high", "B"), ("high", "B")]
        d = design(units, ["low", "high"], ["A", "B"])
        self.assertEqual(set(d.leverages()), {Q(3, 8)})


class ContingencyMeasures(unittest.TestCase):
    def test_proportional(self):
        self.assertTrue(proportional([[2, 1], [2, 1]]))
        self.assertTrue(proportional([[2, 2], [2, 2]]))
        self.assertFalse(proportional([[3, 1], [1, 3]]))
        self.assertFalse(proportional([[4, 0], [0, 4]]))

    def test_chi_square_and_cramers_v(self):
        # [[3,1],[1,3]]: E = 2 everywhere; chi2 = 4 * 1/2 = 2; V^2 = 2 / (8 * 1) = 1/4.
        self.assertEqual(chi_square([[3, 1], [1, 3]]), 2)
        self.assertEqual(cramers_v_squared([[3, 1], [1, 3]]), Q(1, 4))
        self.assertEqual(cramers_v_squared([[4, 0], [0, 4]]), 1)
        self.assertEqual(cramers_v_squared([[2, 2], [2, 2]]), 0)
        # 3 x 2: [[2,0],[0,2],[1,1]], E = 1 per cell, chi2 = 4, V^2 = 4 / (6 * 1) = 2/3.
        self.assertEqual(cramers_v_squared([[2, 0], [0, 2], [1, 1]]), Q(2, 3))

    def test_cramers_v_undefined_for_one_level(self):
        self.assertIsNone(cramers_v_squared([[4, 4]]))
        self.assertIsNone(cramers_v_squared([[3], [5]]))
        # an all-zero column (declared but unobserved level) is dropped first
        self.assertEqual(cramers_v_squared([[3, 1, 0], [1, 3, 0]]), Q(1, 4))


if __name__ == "__main__":
    unittest.main()
