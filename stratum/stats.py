"""WP2 diagnostics (DECISIONS.md D-044, D-049).

Diagnostics are warnings, never inference gates. Each one returns a plain dict:
    available  False when the data cannot support the calculation; then `reason`
               says why and nothing is computed (no value is manufactured);
    warn       True when the frozen threshold is crossed.
Every threshold is compared exactly in rational arithmetic, except the
Brown-Forsythe p-value. That p-value comes from the F survival function in
stratum.dist, which is verified against every F test stored in reference/r_outputs
(D-049); it is re-exported here under the names WP2 already used.

Conventions (D-044):
  - Brown-Forsythe: one-way ANOVA F on |y - group median|; warn at p < 0.05.
  - SD ratio: largest / smallest group SD (n - 1 denominator); warn at >= 2.0, a
    pragmatic v1 threshold, not a universal law. Zero denominator: infinite (or
    undefined when every SD is zero), with a warning.
  - Studentized residuals: externally studentized (deleted),
    t_i = r_i * sqrt((nu - 1) / (nu - r_i^2)), r_i internally studentized; warn at |t_i| > 3.
    Undefined (reported, never manufactured) when nu < 2, the leverage is 1, or the
    deleted residual variance is zero (D-055).
  - Normal quantiles: Blom positions (i - 3/8) / (n + 1/4) against the sorted
    internally studentized residuals. No test or cutoff is applied to them.
"""
import math
from fractions import Fraction
from statistics import NormalDist
from typing import List, Sequence

from .dist import betainc, f_sf  # noqa: F401  (published here since WP2)
from .exact import Design

Q = Fraction
BF_ALPHA = 0.05
SD_RATIO_WARN = 2          # compared as ratio^2 >= 4
STUDENTIZED_WARN = 3       # compared as t^2 > 9


# ---------------------------------------------------------------------------
# Small exact helpers
# ---------------------------------------------------------------------------

def mean(xs: Sequence[Fraction]) -> Fraction:
    return sum(xs, Q(0)) / len(xs)


def median(xs: Sequence[Fraction]) -> Fraction:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def variance(xs: Sequence[Fraction]) -> Fraction:
    m = mean(xs)
    return sum(((x - m) ** 2 for x in xs), Q(0)) / (len(xs) - 1)


def _unavailable(name, reason):
    return {"diagnostic": name, "available": False, "warn": False, "reason": reason}


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def brown_forsythe(groups: Sequence[Sequence[Fraction]], labels=None) -> dict:
    """Median-centered Brown-Forsythe test across groups of unit means."""
    name = "brown_forsythe"
    k, n = len(groups), sum(len(g) for g in groups)
    if k < 2:
        return _unavailable(name, "fewer than two treatment groups")
    if n - k < 1:
        return _unavailable(name, "no within-group degrees of freedom (N - t = %d)" % (n - k))
    z = [[abs(y - median(g)) for y in g] for g in groups]
    zbar = [mean(g) for g in z]
    grand = sum((sum(g) for g in z), Q(0)) / n
    ssb = sum((len(g) * (m - grand) ** 2 for g, m in zip(z, zbar)), Q(0))
    ssw = sum((sum(((v - m) ** 2 for v in g), Q(0)) for g, m in zip(z, zbar)), Q(0))
    if ssw == 0:
        return _unavailable(name, "the absolute deviations from the group medians have zero "
                                  "within-group sum of squares (as in a balanced design with "
                                  "exactly 2 units in every group), so the F statistic has a "
                                  "zero denominator")
    f = (ssb / (k - 1)) / (ssw / (n - k))
    p = f_sf(float(f), k - 1, n - k)
    return {"diagnostic": name, "available": True, "warn": p < BF_ALPHA, "F": float(f),
            "df": [k - 1, n - k], "p": p, "threshold": "p < %g" % BF_ALPHA,
            "groups": list(labels) if labels else None}


def sd_ratio(groups: Sequence[Sequence[Fraction]], labels=None) -> dict:
    """Largest-to-smallest group SD of unit means."""
    name = "sd_ratio"
    labels = list(labels) if labels else [str(i) for i in range(len(groups))]
    usable = [(lab, g) for lab, g in zip(labels, groups) if len(g) >= 2]
    if len(usable) < 2:
        return _unavailable(name, "fewer than two treatment groups with an estimable SD")
    var = {lab: variance(g) for lab, g in usable}
    sds = {lab: math.sqrt(float(v)) for lab, v in var.items()}
    vmax, vmin = max(var.values()), min(var.values())
    out = {"diagnostic": name, "available": True, "sds": sds,
           "threshold": ">= %s (pragmatic v1 threshold, not a universal law)" % SD_RATIO_WARN}
    if vmin == 0:
        out.update(warn=True, ratio="infinite" if vmax > 0 else "undefined",
                   note="a group SD is exactly zero")
    else:
        out.update(warn=vmax / vmin >= SD_RATIO_WARN ** 2, ratio=math.sqrt(float(vmax / vmin)))
    return out


def blom_quantiles(n: int) -> List[float]:
    nd = NormalDist()
    return [nd.inv_cdf((i - 0.375) / (n + 0.25)) for i in range(1, n + 1)]


def studentized(y: Sequence[Fraction], design: Design, unit_labels=None, model="") -> dict:
    """Externally studentized residuals of y under a fixed-effects indicator design,
    plus the normal-quantile representation of the internally studentized residuals."""
    name = "studentized_residuals"
    n, nu = design.n, design.n - design.rank
    if nu < 2:
        return _unavailable(name, "residual df %d < 2: the deleted residual variance is "
                                  "undefined" % nu)
    fitted = design.fitted(y)
    e = [a - b for a, b in zip(y, fitted)]
    sse = sum((v * v for v in e), Q(0))
    if sse == 0:
        return _unavailable(name, "every residual is exactly zero")
    s2 = sse / nu
    lev = design.leverages()
    labels = list(unit_labels) if unit_labels else [str(i) for i in range(n)]
    units, warn, max_abs = [], False, 0.0
    internal, undefined = [], []
    for lab, ei, hi in zip(labels, e, lev):
        rec = {"unit": lab, "residual": float(ei), "leverage": float(hi)}
        if hi == 1:
            rec.update(internal=None, external=None,
                       note="leverage 1: the residual is identically 0 and the studentized "
                            "residual is undefined")
            undefined.append(lab)
            units.append(rec)
            continue
        r2 = ei * ei / (s2 * (1 - hi))
        sign = 1.0 if ei >= 0 else -1.0
        r = sign * math.sqrt(float(r2))
        internal.append(r)
        if nu - r2 > 0:
            t2 = r2 * (nu - 1) / (nu - r2)
            t = sign * math.sqrt(float(t2))
            flagged = t2 > STUDENTIZED_WARN ** 2
            warn = warn or flagged
            max_abs = max(max_abs, abs(t))
            rec.update(internal=r, external=t, flagged=flagged)
        else:
            # Deleting this unit leaves zero residual variance: the deleted variance is not
            # usable, so no number is manufactured (D-055).
            rec.update(internal=r, external=None,
                       note="deleted residual variance is zero: externally studentized "
                            "residual undefined")
            undefined.append(lab)
        units.append(rec)
    if len(undefined) == len(units):
        return _unavailable(name, "the externally studentized residual is undefined for every "
                                  "unit")
    quant = sorted(internal)
    return {"diagnostic": name, "available": True, "warn": warn, "model": model,
            "residual_df": nu, "max_abs_external": max_abs, "undefined_units": undefined,
            "threshold": "|externally studentized residual| > %d" % STUDENTIZED_WARN,
            "units": units,
            "normal_quantiles": {"positions": "Blom (i - 3/8) / (n + 1/4)",
                                 "theoretical": blom_quantiles(len(quant)),
                                 "internally_studentized_sorted": quant}}
