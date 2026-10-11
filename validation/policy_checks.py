#!/usr/bin/env python3
"""Independent checks of the statistical claims behind the frozen missing-site
policy (DECISIONS.md D-016, D-021, D-022). Standard library only; deterministic.

Check 1 (C-4). For a T2 experimental-unit mean formed as in D-016 (average the
surviving sites within each wafer, then weight the w wafers equally), with
nominal site count m0 and surviving counts m_j (1 <= m_j <= m0):
  a. the exact variance of the unit mean, computed as a' Sigma a from the full
     hierarchical covariance matrix (no closed form used), equals
     s2R + s2W/w + (s2S/w^2) * sum_j 1/m_j;
  b. its site-error part is F_site = (m0/w) * sum_j 1/m_j times the balanced one;
  c. 1/F_site <= Var_balanced / Var_missing <= 1 for any nonnegative components,
     with equality on the left when s2R = s2W = 0;
  d. a seeded Monte Carlo estimate agrees with the exact variance;
  e. the bound needs m_j <= m0: a counterexample with m_j > m0 is shown.

Check 2 (C-2). With fixed positional site effects, if the runs compared lose the
same NUMBER of sites but different site LABELS, the treatment contrast of unit
means is biased (not merely less precise); with exchangeable sites it is not;
and with the same labels missing in every run it is not.

Usage: python3 validation/policy_checks.py      (exit 1 on any failure)
"""
import random
import sys
from fractions import Fraction as Fr
from itertools import product

failures = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


# ---------- helpers: one run (experimental unit) with w wafers ----------

def observations(counts):
    """(wafer, site) index of every surviving reading in one run."""
    return [(j, k) for j, m in enumerate(counts) for k in range(m)]


def unit_mean_weights(counts):
    """Weights a with unit mean = a . y, under the D-016 hierarchical convention."""
    w = len(counts)
    return [Fr(1, w) * Fr(1, counts[j]) for j, _ in observations(counts)]


def covariance(counts, s2R, s2W, s2S):
    """Exact covariance matrix of the readings of one run under
    y = mu + R + W_j + S_jk, all independent."""
    obs = observations(counts)
    return [[s2R + (s2W if a[0] == b[0] else 0) + (s2S if a == b else 0) for b in obs] for a in obs]


def quad(a, sigma):
    return sum(a[i] * sigma[i][j] * a[j] for i in range(len(a)) for j in range(len(a)))


def exact_var(counts, s2R, s2W, s2S):
    return quad(unit_mean_weights(counts), covariance(counts, s2R, s2W, s2S))


def closed_form(counts, s2R, s2W, s2S):
    w = len(counts)
    return s2R + s2W / w + s2S / w**2 * sum(Fr(1, m) for m in counts)


def f_site(counts, m0):
    w = len(counts)
    return Fr(m0, w) * sum(Fr(1, m) for m in counts)


# ---------- check 1: C-4 derivation ----------

rng = random.Random(20261003)
comps = [(Fr(0), Fr(0), Fr(1)), (Fr(1), Fr(0), Fr(0)), (Fr(0), Fr(1), Fr(0)),
         (Fr(312557, 1000), Fr(225383, 1000), Fr(120893, 1000))]
comps += [tuple(Fr(rng.randint(0, 50), rng.randint(1, 9)) for _ in range(3)) for _ in range(12)]
configs = []
for w in (1, 2, 3, 4):
    for m0 in (1, 2, 5, 9):
        for counts in product(range(1, m0 + 1), repeat=w):
            configs.append((counts, m0))
configs = configs[:: max(1, len(configs) // 200)]  # deterministic thinning, ~200 configurations

ok_a = ok_b = ok_c = ok_eq = True
for counts, m0 in configs:
    w = len(counts)
    for s2R, s2W, s2S in comps:
        v_miss = exact_var(counts, s2R, s2W, s2S)
        ok_a &= v_miss == closed_form(counts, s2R, s2W, s2S)
        if s2S > 0:
            site_part_miss = exact_var(counts, 0, 0, s2S)
            site_part_bal = exact_var((m0,) * w, 0, 0, s2S)
            ok_b &= site_part_miss / site_part_bal == f_site(counts, m0)
        v_bal = exact_var((m0,) * w, s2R, s2W, s2S)
        if v_miss > 0:
            ratio = v_bal / v_miss
            ok_c &= 1 / f_site(counts, m0) <= ratio <= 1
            if s2R == 0 and s2W == 0:
                ok_eq &= ratio == 1 / f_site(counts, m0)
check(f"1a exact a'Sigma.a equals the closed form ({len(configs)} count patterns x {len(comps)} component sets)", ok_a)
check("1b site-error part inflates by exactly F_site = (m0/w) sum 1/m_j", ok_b)
check("1c 1/F_site <= precision ratio (balanced/missing) <= 1 for every case", ok_c)
check("1c bound is attained when only the site component is nonzero", ok_eq)

# 1d: seeded Monte Carlo of one configuration, independent of all algebra above
counts, m0, (s2R, s2W, s2S) = (5, 2, 1, 4), 5, (4.0, 2.0, 9.0)
mc = random.Random(1)
n = 200_000
vals = []
for _ in range(n):
    r = mc.gauss(0, s2R ** 0.5)
    wafer_means = []
    for m in counts:
        wj = mc.gauss(0, s2W ** 0.5)
        wafer_means.append(sum(r + wj + mc.gauss(0, s2S ** 0.5) for _ in range(m)) / m)
    vals.append(sum(wafer_means) / len(wafer_means))
mean = sum(vals) / n
var_hat = sum((v - mean) ** 2 for v in vals) / (n - 1)
exact = float(closed_form(counts, Fr(4), Fr(2), Fr(9)))
se = exact * (2 / (n - 1)) ** 0.5  # SE of a sample variance under normality
check("1d Monte Carlo variance agrees with the exact variance (within 4 MC SE)",
      abs(var_hat - exact) <= 4 * se, f"MC {var_hat:.4f} vs exact {exact:.4f}, SE {se:.4f}")

# 1e: the precondition m_j <= m0 matters
counts_extra, m0_small = (7, 5), 5
F = f_site(counts_extra, m0_small)
ratio = exact_var((m0_small,) * 2, 1, 0, 1) / exact_var(counts_extra, 1, 0, 1)
check("1e with a wafer above nominal (m_j > m0), F_site < 1 and 1/F_site is NOT a lower bound",
      F < 1 and not (1 / F <= ratio), f"F_site = {F}, 1/F_site = {float(1/F):.4f}, ratio = {float(ratio):.4f}")

# ---------- check 2: C-2 exchangeable vs positional sites ----------
# Treatment contrast between one run at level 1 and one run at level 2, true
# treatment difference tau. Bias = E[contrast of unit means] - tau.

positions = [Fr(3), Fr(-1), Fr(0), Fr(1), Fr(-3)]  # fixed position effects, sum zero
zeros = [Fr(0)] * 5
tau = Fr(10)


def expected_unit_mean(kept, effects, shift=Fr(0)):
    return shift + sum(sum(effects[k] for k in wafer) / len(wafer) for wafer in kept) / len(kept)


def contrast_bias(kept_1, kept_2, effects):
    return expected_unit_mean(kept_1, effects, tau) - expected_unit_mean(kept_2, effects) - tau


lost_4 = [[0, 1, 2, 3], [0, 1, 2, 3]]  # each wafer lost position 4
lost_0 = [[1, 2, 3, 4], [1, 2, 3, 4]]  # each wafer lost position 0: same COUNTS, different labels
b = contrast_bias(lost_4, lost_0, positions)
check("2a positional sites, equal counts but different labels: the treatment contrast is biased",
      b != 0, f"bias = {b} in units of the position effects")
check("2b exchangeable sites (no positional effect), same patterns: no bias",
      contrast_bias(lost_4, lost_0, zeros) == 0)
check("2c positional sites, the SAME labels missing in both runs: no bias",
      contrast_bias(lost_4, lost_4, positions) == 0)

print(f"\n{'all policy checks passed' if not failures else str(len(failures)) + ' FAILED'}")
sys.exit(1 if failures else 0)
