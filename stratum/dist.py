"""Distribution and quantile functions (DECISIONS.md D-049, D-068).

Standard library only. WP2 needed one tail probability (the F survival function). WP3
needs chi-square and Student t quantiles for the variance-component and effect intervals,
so the incomplete gamma and beta functions and their inversions live here, and
stratum.stats imports the two names it already published.

Methods, all classical:
  - regularized incomplete beta I_x(a, b): the modified Lentz continued fraction
    (Press et al., *Numerical Recipes*, section 6.4);
  - regularized incomplete gamma P(a, x): the series for x < a + 1 and the continued
    fraction for x >= a + 1 (same source, section 6.2);
  - quantiles: the monotone tail function is inverted by bisection on a bracket found by
    doubling, to a relative width of 1e-15. No closed-form inverse is approximated.

The quantile functions are verified in tests/test_wp3_dist.py against exact closed forms
(chi-square on 1 and 2 df, Student t on 1 and 2 df, t^2 = F(1, nu)) and by round trip
against the tail functions, and the F survival function keeps its frozen 1e-8 agreement
with every F test stored in reference/r_outputs (D-049).
"""
import math
from functools import lru_cache
from statistics import NormalDist

_TINY = 1e-300
_EPS = 1e-16


# ---------------------------------------------------------------------------
# Incomplete beta, and the F distribution
# ---------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _TINY else _TINY)
    h = d
    for m in range(1, 100000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            return h
    raise ArithmeticError("incomplete beta continued fraction did not converge")


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def f_sf(f: float, d1: float, d2: float) -> float:
    """P(F > f) for F with (d1, d2) degrees of freedom."""
    if f <= 0.0:
        return 1.0
    if math.isinf(f):
        return 0.0
    return betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f))


def f_cdf(f: float, d1: float, d2: float) -> float:
    return 1.0 - f_sf(f, d1, d2)


# ---------------------------------------------------------------------------
# Incomplete gamma, and the chi-square distribution
# ---------------------------------------------------------------------------

def _gser(a: float, x: float) -> float:
    """P(a, x) by its series, for x < a + 1."""
    ap, total, delta = a, 1.0 / a, 1.0 / a
    for _ in range(100000):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            return total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    raise ArithmeticError("incomplete gamma series did not converge")


def _gcf(a: float, x: float) -> float:
    """Q(a, x) by its continued fraction, for x >= a + 1."""
    b, c = x + 1.0 - a, 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, 100000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = d if abs(d) > _TINY else _TINY
        c = b + an / c
        c = c if abs(c) > _TINY else _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            return h * math.exp(-x + a * math.log(x) - math.lgamma(a))
    raise ArithmeticError("incomplete gamma continued fraction did not converge")


def gammainc_p(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x)."""
    if x <= 0.0:
        return 0.0
    return _gser(a, x) if x < a + 1.0 else 1.0 - _gcf(a, x)


def gammainc_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) = 1 - P(a, x)."""
    if x <= 0.0:
        return 1.0
    return 1.0 - _gser(a, x) if x < a + 1.0 else _gcf(a, x)


def chi2_cdf(x: float, nu: float) -> float:
    return gammainc_p(nu / 2.0, x / 2.0)


def chi2_sf(x: float, nu: float) -> float:
    return gammainc_q(nu / 2.0, x / 2.0)


# ---------------------------------------------------------------------------
# Quantiles, by bisection on the monotone cumulative function
# ---------------------------------------------------------------------------

def _invert(cdf, p: float, start: float) -> float:
    """The x with cdf(x) = p, for a strictly increasing cdf on (0, inf)."""
    if not 0.0 < p < 1.0:
        raise ValueError("probability must be strictly between 0 and 1: %r" % p)
    lo, hi = 0.0, max(start, 1e-12)
    for _ in range(4000):                 # bracket upwards
        if cdf(hi) >= p:
            break
        lo, hi = hi, hi * 2.0
    else:
        raise ArithmeticError("could not bracket the quantile")
    for _ in range(1100):                 # includes the subnormal range
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi:
            break
        if cdf(mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-15 * lo:
            break
    return 0.5 * (lo + hi)


def _log_gamma_p_from_log_x(a: float, log_x: float) -> float:
    """Log P(a,x), evaluating the normalized gamma series without underflow."""
    x = math.exp(log_x) if log_x > -745 else 0.0
    if x >= a + 1:
        return math.log(gammainc_p(a, x))
    term = total = 1.0
    for i in range(1, 100000):
        term *= x / (a + i)
        total += term
        if abs(term) <= abs(total) * _EPS:
            return a * log_x - x - math.lgamma(a + 1) + math.log(total)
    raise ArithmeticError("log incomplete gamma series did not converge")


@lru_cache(maxsize=4096)
def chi2_log_quantile(p: float, nu: float) -> float:
    """Log of a chi-square quantile, including values below floating-point range."""
    if not 0 < p < 1 or not nu > 0:
        raise ValueError("probability must be inside (0,1) and df positive")
    if nu >= 0.5:
        return math.log(_invert(lambda x: chi2_cdf(x, nu), p, max(nu, 1.0)))
    a, target = nu / 2, math.log(p)
    # P(a,x) <= x**a/Gamma(a+1), so this is a lower bracket in log(x).
    lo = (target + math.lgamma(a + 1)) / a
    hi = math.log(max(nu, 1.0))
    while _log_gamma_p_from_log_x(a, hi) < target:
        hi += math.log(2)
    for _ in range(200):
        mid = (lo + hi) / 2
        if mid == lo or mid == hi:
            break
        if _log_gamma_p_from_log_x(a, mid) < target:
            lo = mid
        else:
            hi = mid
    return math.log(2) + (lo + hi) / 2


@lru_cache(maxsize=4096)
def chi2_quantile(p: float, nu: float) -> float:
    """The p-quantile of the chi-square distribution on nu degrees of freedom."""
    if nu >= 0.5:
        return _invert(lambda x: chi2_cdf(x, nu), p, max(nu, 1.0))
    return math.exp(chi2_log_quantile(p, nu))


@lru_cache(maxsize=4096)
def f_quantile(p: float, d1: float, d2: float) -> float:
    """The p-quantile of the F distribution on (d1, d2) degrees of freedom."""
    return _invert(lambda x: f_cdf(x, d1, d2), p, 1.0)


@lru_cache(maxsize=4096)
def t_quantile(p: float, nu: float) -> float:
    """The p-quantile of Student's t on nu degrees of freedom.

    Uses |T| = sqrt(F(1, nu)): P(|T| <= t) = P(F_{1,nu} <= t^2), so for p > 1/2 the
    p-quantile is sqrt of the (2p - 1)-quantile of F(1, nu). One inversion, and the
    identity is asserted in the tests."""
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_quantile(1.0 - p, nu)
    return math.sqrt(f_quantile(2.0 * p - 1.0, 1.0, nu))


def t_sf_two_sided(t: float, nu: float) -> float:
    """P(|T| > |t|) for Student's t on nu degrees of freedom."""
    return f_sf(float(t) * float(t), 1.0, nu)


def norm_quantile(p: float) -> float:
    return NormalDist().inv_cdf(p)
