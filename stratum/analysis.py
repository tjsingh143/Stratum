"""WP3: analysis of the supported balanced designs (DECISIONS.md D-060 to D-068).

`analyze(declaration, data)` runs the WP1 match and the WP2 evidence checks and, when the
evidence decision is ANALYZE or WARN, produces the analysis PROJECT_BRIEF.md Section 5
specifies: an ANOVA table with expected mean squares, F tests against the correct error
term, effect estimates with intervals, variance components with labelled intervals, and
the REML cross-check. On REFUSE it produces no estimate of any kind (D-067).

Everything structural is computed in exact rational arithmetic from the response read as
an exact decimal (D-049). Floating point appears only in p-values, interval endpoints,
square roots and display.

The three templates share one implementation:

  * **Nested sums of squares.** For a level whose units each carry `m` observations,
    SS = m * sum over units of (unit mean - parent mean)^2, with df = (units) - (parents).
    Unit means are hierarchical (each unit's mean is the mean of its children's means),
    which equals the plain mean for balanced data and is what D-016 requires when sites
    are missing.
  * **Expected mean squares.** For a balanced design, E[MS of the stratum at level l] is
    the sum over levels j >= l of m_j * sigma^2_j, where m_j is the number of observations
    per level-j unit. Inverting that triangular system gives the method-of-moments
    estimates sigma^2_l = (MS_l - MS_{l+1}) / m_l, with the lowest component equal to its
    own mean square.
  * **Collapsed strata (D-054, D-062).** A level with one unit per parent gives its
    stratum 0 df and the same m as the level above, so adjacent components with equal m
    are merged into one combined component and no separate estimate of either is claimed.
  * **REML (D-064).** Closed form: the df-weighted pool-adjacent-violators fit of the
    stratum mean squares under lambda_0 >= lambda_1 >= ... > 0. Equal to the
    method-of-moments estimates whenever those are all nonnegative; otherwise the
    violating strata are pooled and that component's REML estimate is exactly 0.
  * **Intervals (D-060).** Satterthwaite for the components, exact where the component is
    a positive multiple of a single mean square, exact for every stratum's expected mean
    square, and t intervals for the fixed effects on the error stratum's df.
"""
import math
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .data import Table
from .declaration import Declaration
from .dist import chi2_log_quantile, chi2_quantile, f_sf, t_quantile, t_sf_two_sided
from .exact import Design
from .exact import det as exact_det
from .evidence import EvidenceResult, check_evidence, unit_means

Q = Fraction
ALPHA = 0.05                      # 95%, two-sided, per-comparison (D-060, D-062)
APPROX = "approximate (Satterthwaite)"
EXACT = "exact under the model for balanced data"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _mean(xs: Sequence[Fraction]) -> Fraction:
    return sum(xs, Q(0)) / len(xs)


def _f_num(x) -> Optional[float]:
    return None if x is None else float(x)


def _sq(x: Fraction) -> Fraction:
    return x * x


def _show(unit: Tuple[str, ...]) -> str:
    return "/".join(unit)


def _chi2_interval(point: float, nu: float) -> Tuple[float, float]:
    """[nu*point/chi2_{1-a/2}, nu*point/chi2_{a/2}], the scaled-chi-square interval."""
    return (nu * point / chi2_quantile(1.0 - ALPHA / 2.0, nu),
            nu * point / chi2_quantile(ALPHA / 2.0, nu))


# ---------------------------------------------------------------------------
# The structural input: unit identities and hierarchical means
# ---------------------------------------------------------------------------

@dataclass
class Structure:
    """What the analysis needs about a balanced design: the units at each level, each
    unit's parent, and each unit's hierarchical mean."""
    level_names: Tuple[str, ...]
    units: Tuple[Tuple, ...]                 # units[l]: ordered unit ids at level l
    parent: Tuple[Dict, ...]                 # parent[l][unit] -> unit at level l-1 (l >= 1)
    means: Tuple[Dict, ...]                  # means[l][unit] -> Fraction
    n_obs: int

    @property
    def depth(self) -> int:
        return len(self.level_names)

    @property
    def grand(self) -> Fraction:
        return _mean([self.means[0][u] for u in self.units[0]])

    def m(self, level: int) -> int:
        """Observations per unit at this level (balanced)."""
        n = len(self.units[level])
        if self.n_obs % n:
            raise ValueError("design is not balanced at level %r" % self.level_names[level])
        return self.n_obs // n

    def ancestor_of_bottom(self, level: int) -> Dict:
        """Each bottom-level unit's ancestor at `level`."""
        out = {u: u for u in self.units[self.depth - 1]}
        for lvl in range(self.depth - 1, level, -1):
            out = {u: self.parent[lvl][p] for u, p in out.items()}
        return out

    def balanced(self) -> bool:
        for lvl in range(1, self.depth):
            counts = {}
            for u, p in self.parent[lvl].items():
                counts[p] = counts.get(p, 0) + 1
            if len(set(counts.values())) != 1:
                return False
        return True


def structure_from_context(ctx) -> Structure:
    depth = len(ctx.decl.hierarchy)
    units, parents, means = [], [{}], []
    for lvl in range(depth):
        order = []
        for i in ctx.obs:
            if ctx.ids[i][lvl] not in order:
                order.append(ctx.ids[i][lvl])
        units.append(tuple(order))
        means.append(unit_means(ctx, lvl))
        if lvl:
            pmap = {}
            for i in ctx.obs:
                pmap.setdefault(ctx.ids[i][lvl], ctx.ids[i][lvl - 1])
            parents.append(pmap)
    return Structure(tuple(lv.name for lv in ctx.decl.hierarchy), tuple(units),
                     tuple(parents), tuple(means), len(ctx.obs))


@dataclass
class DirectTable:
    """A Structure built straight from a data table, with a way to read a column that is
    constant within a unit. Used only by the D-067 kernel cross-checks, which deliberately
    do not go through a declaration."""
    structure: Structure
    values: Dict
    columns: Tuple[Dict, ...]      # columns[l][unit] -> {column name: value}

    def unit_value(self, level: int, column: str) -> Dict:
        return {u: v[column] for u, v in self.columns[level].items()}


def structure_from_columns(table: Table, id_columns: Sequence[str],
                           response_column: str) -> DirectTable:
    """Build a Structure from a table's ID columns (parent-scoped identities) and response.
    Every row must carry a finite response; the kernel checks run on complete data."""
    from .data import parse_response
    depth = len(id_columns)
    units: List[List] = [[] for _ in range(depth)]
    seen: List[set] = [set() for _ in range(depth)]
    parents: List[Dict] = [{} for _ in range(depth)]
    columns: List[Dict] = [{} for _ in range(depth)]
    values: Dict = {}
    for row in table.rows:
        chain = tuple(row[c] for c in id_columns)
        for lvl in range(depth):
            uid = chain[: lvl + 1]
            if uid not in seen[lvl]:
                seen[lvl].add(uid)
                units[lvl].append(uid)
                columns[lvl][uid] = dict(row)
                if lvl:
                    parents[lvl][uid] = uid[:-1]
        v = parse_response(row[response_column])
        if v is None:
            raise ValueError("row %r has no finite response" % (chain,))
        values[chain] = v
    means: List[Dict] = [None] * depth
    means[depth - 1] = values
    for lvl in range(depth - 2, -1, -1):
        kids: Dict = {}
        for u in units[lvl + 1]:
            kids.setdefault(parents[lvl + 1][u], []).append(means[lvl + 1][u])
        means[lvl] = {u: _mean(kids[u]) for u in units[lvl]}
    st = Structure(tuple(id_columns), tuple(tuple(u) for u in units), tuple(parents),
                   tuple(means), len(values))
    return DirectTable(st, values, tuple(columns))


def unit_mean_structure(st: Structure, level: int = 0) -> Structure:
    """A one-level Structure whose observations are the unit means at `level`. Used by the
    Semiconductor whole-plot kernel check (D-067)."""
    return Structure((st.level_names[level],), (st.units[level],), ({},),
                     (st.means[level],), len(st.units[level]))


# ---------------------------------------------------------------------------
# Strata
# ---------------------------------------------------------------------------

@dataclass
class Stratum:
    key: str
    label: str
    df: int
    ss: Fraction
    m: Optional[int] = None            # random strata only: observations per unit
    random: bool = False
    error_key: Optional[str] = None    # the stratum this one is tested against
    ems: Optional[Dict[str, int]] = None
    note: str = ""

    @property
    def ms(self) -> Optional[Fraction]:
        return None if self.df == 0 else self.ss / self.df


def nested_strata(st: Structure) -> List[Stratum]:
    """One stratum per hierarchy level, from the hierarchical unit means."""
    out = []
    grand = st.grand
    for lvl in range(st.depth):
        m = st.m(lvl)
        if lvl == 0:
            ss = m * sum((_sq(st.means[0][u] - grand) for u in st.units[0]), Q(0))
            df = len(st.units[0]) - 1
        else:
            ss = m * sum((_sq(st.means[lvl][u] - st.means[lvl - 1][st.parent[lvl][u]])
                          for u in st.units[lvl]), Q(0))
            df = len(st.units[lvl]) - len(st.units[lvl - 1])
        out.append(Stratum(st.level_names[lvl], st.level_names[lvl], df, ss, m=m,
                           random=True))
    return out


def total_stratum(st: Structure, values: Dict) -> Stratum:
    grand = st.grand
    ss = sum((_sq(v - grand) for v in values.values()), Q(0))
    return Stratum("total", "total", st.n_obs - 1, ss)


def _group_means(keys: Sequence, value_of: Dict, group_of: Dict) -> Dict:
    groups: Dict[object, List[Fraction]] = {}
    for k in keys:
        groups.setdefault(group_of[k], []).append(value_of[k])
    return {g: _mean(v) for g, v in groups.items()}


# ---------------------------------------------------------------------------
# Variance components, REML and intervals
# ---------------------------------------------------------------------------

@dataclass
class ComponentGroup:
    keys: Tuple[str, ...]
    m: int
    df: int
    ss: Fraction
    labels: Tuple[str, ...]

    @property
    def ms(self) -> Fraction:
        return self.ss / self.df

    @property
    def key(self) -> str:
        return "+".join(self.keys)


def component_groups(random_strata: Sequence[Stratum]) -> List[ComponentGroup]:
    """Merge adjacent random strata that share an m, i.e. whose separating stratum has no
    degrees of freedom (D-054, D-062). The first stratum of a group is the one with
    nonzero df."""
    groups: List[ComponentGroup] = []
    for s in random_strata:
        if groups and groups[-1].m == s.m:
            g = groups[-1]
            if s.df:
                raise ValueError("merged stratum %r has %d df, expected 0" % (s.key, s.df))
            groups[-1] = ComponentGroup(g.keys + (s.key,), g.m, g.df, g.ss,
                                        g.labels + (s.label,))
            continue
        groups.append(ComponentGroup((s.key,), s.m, s.df, s.ss, (s.label,)))
    for g in groups:
        if g.df <= 0:
            raise ValueError("component group %r has %d degrees of freedom" % (g.key, g.df))
    if groups[-1].m != 1:
        raise ValueError("the lowest component group must have m = 1, got %d" % groups[-1].m)
    return groups


def reml_isotonic(groups: Sequence[ComponentGroup]) -> List[Fraction]:
    """Closed-form REML (D-064): the df-weighted pool-adjacent-violators fit of the mean
    squares under lambda_0 >= lambda_1 >= ... Returns one lambda per group."""
    blocks = [[int(g.df), Q(g.ss)] for g in groups]        # [df, ss] per block
    sizes = [1] * len(blocks)
    i = 0
    while i + 1 < len(blocks):
        lam_l = blocks[i][1] / blocks[i][0]
        lam_r = blocks[i + 1][1] / blocks[i + 1][0]
        if lam_l < lam_r:                                   # violates non-increasing: pool
            blocks[i] = [blocks[i][0] + blocks[i + 1][0], blocks[i][1] + blocks[i + 1][1]]
            sizes[i] += sizes[i + 1]
            del blocks[i + 1], sizes[i + 1]
            if i:
                i -= 1                                      # the pool may violate upstream
        else:
            i += 1
    out: List[Fraction] = []
    for (df, ss), size in zip(blocks, sizes):
        out.extend([ss / df] * size)
    return out


def variance_components(groups: Sequence[ComponentGroup], n_fixed: int,
                        fixed_design=None) -> dict:
    """Method-of-moments and REML components, with intervals (D-060, D-064)."""
    ms = [g.ms for g in groups]
    lam = reml_isotonic(groups)
    last = len(groups) - 1
    comps: Dict[str, dict] = {}
    boundary: List[dict] = []
    for i, g in enumerate(groups):
        if i < last:
            mom = (ms[i] - ms[i + 1]) / g.m
            reml = (lam[i] - lam[i + 1]) / g.m
            nu_eff = None
            diff = float(ms[i] - ms[i + 1])
            denom = (float(ms[i]) ** 2 / groups[i].df
                     + float(ms[i + 1]) ** 2 / groups[i + 1].df)
            if denom > 0:
                nu_eff = diff * diff / denom
            exact = False
            ems_note = "(MS[%s] - MS[%s]) / %d" % (g.key, groups[i + 1].key, g.m)
            ems_show = "(MS[%s] - MS[%s]) / %d" % (" + ".join(g.labels),
                                                   " + ".join(groups[i + 1].labels), g.m)
        else:
            mom = ms[i]
            reml = lam[i]
            nu_eff = float(g.df)
            exact = True
            ems_note = "MS[%s]" % g.key
            ems_show = "MS[%s]" % " + ".join(g.labels)
        rec = {
            "component": g.key,
            "label": " + ".join(g.labels),
            "merged": len(g.keys) > 1,
            "coefficient": g.m,
            "estimator": ems_note,
            "estimator_display": ems_show,
            "mom": float(mom),
            "mom_exact": str(mom),
            "mom_truncated": float(max(mom, Q(0))),
            "negative": mom < 0,
            "sd_mom": math.sqrt(float(max(mom, Q(0)))),
            "reml": float(reml),
            "sd_reml": math.sqrt(float(reml)),
            "reml_equals_mom": mom >= 0,
            "interval_method": EXACT if exact else APPROX,
            "exact": exact,
        }
        if mom > 0 and nu_eff and nu_eff > 0:
            if nu_eff >= 0.5:
                lo, hi = _chi2_interval(float(mom), nu_eff)
                rec.update(interval_available=True, nu_eff=nu_eff,
                           interval_lower=max(lo, 0.0), interval_upper=hi,
                           truncated_at_zero=lo < 0.0,
                           sd_interval_lower=math.sqrt(max(lo, 0.0)),
                           sd_interval_upper=math.sqrt(hi))
            else:
                # The interval exists mathematically even if its endpoint cannot be
                # represented as a float. Keep logs for scoring and JSON-safe labels.
                log_scale = math.log(nu_eff) + math.log(float(mom))
                log_lo = log_scale - chi2_log_quantile(1 - ALPHA / 2, nu_eff)
                log_hi = log_scale - chi2_log_quantile(ALPHA / 2, nu_eff)
                def endpoint(log_value):
                    try:
                        return math.exp(log_value)
                    except OverflowError:
                        return "exceeds floating-point range"
                rec.update(interval_available=True, nu_eff=nu_eff,
                           interval_lower=endpoint(log_lo), interval_upper=endpoint(log_hi),
                           interval_log_lower=log_lo, interval_log_upper=log_hi,
                           truncated_at_zero=False,
                           sd_interval_lower=endpoint(log_lo / 2),
                           sd_interval_upper=endpoint(log_hi / 2),
                           numerical_note="Endpoints computed in log space (D-094); "
                                          "overflow labels are numerical limits, not missing intervals.")
        else:
            rec.update(interval_available=False, nu_eff=nu_eff,
                       interval_reason="the point estimate is %s, so the Satterthwaite "
                                       "scaled-chi-square interval is not usable; the "
                                       "estimate is reported as it is, truncated at zero, "
                                       "and the exact expected-mean-square intervals of the "
                                       "strata involved are reported instead (D-060)"
                                       % ("<= 0" if mom <= 0 else "unusable"))
        if rec["negative"]:
            boundary.append({"kind": "negative_moment_estimate", "component": g.key,
                             "estimate": float(mom),
                             "note": "reported as negative, then truncated at zero "
                                     "(brief Section 5.1)"})
        if reml == 0:
            boundary.append({"kind": "reml_on_boundary", "component": g.key,
                             "note": "the REML order constraint is active: the adjacent "
                                     "strata were pooled, so this component is exactly 0"
                                     if len(groups) > 1 and i < last else
                                     "the fitted residual variance is exactly 0; covariance is singular"})
        comps[g.key] = rec

    truncated = {k: v["mom_truncated"] for k, v in comps.items()}
    total = sum(truncated.values())
    for k, v in comps.items():
        v["percent_of_total"] = (100.0 * truncated[k] / total) if total > 0 else None

    pooled = []
    seen = []
    for i, g in enumerate(groups):
        if i and lam[i] == lam[i - 1]:
            if not seen or seen[-1][-1] != groups[i - 1].key:
                seen.append([groups[i - 1].key, g.key])
            else:
                seen[-1].append(g.key)
    pooled = [list(block) for block in seen]

    nu_total = sum(g.df for g in groups)
    # A zero fitted stratum variance is a singular covariance, not a finite
    # likelihood. Keep its boundary estimate and report the unavailable quantity.
    minus2 = None
    if all(l > 0 for l in lam):
        minus2 = sum(g.df * math.log(float(l)) for g, l in zip(groups, lam))
        minus2 += sum(float(g.ss) / float(l) for g, l in zip(groups, lam))
        minus2 += nu_total * math.log(2.0 * math.pi)
    log_det, param = None, None
    if fixed_design is not None:
        rows, ncols, param = fixed_design
        d = exact_det(Design(rows, ncols).xtx)
        if d > 0:
            log_det = math.log(float(d))
    reml_fit = {
        "method": "closed-form order-restricted (pool-adjacent-violators) REML for "
                  "balanced designs; no optimizer, so no convergence failure (D-064)",
        "lambda_hat": {g.key: float(l) for g, l in zip(groups, lam)},
        "mean_squares": {g.key: float(g.ms) for g in groups},
        "pooled": pooled,
        "boundary": bool(pooled),
        "error_contrast_df": nu_total,
        "n_fixed_parameters": n_fixed,
        "minus2_restricted_loglik_error_contrasts": minus2,
        "restricted_loglik_error_contrasts": None if minus2 is None else -0.5 * minus2,
        "log_det_xtx": log_det,
        "fixed_parameterization": param,
        "minus2_restricted_loglik": None if log_det is None or minus2 is None else minus2 + log_det,
        "restricted_loglik": None if log_det is None or minus2 is None else -0.5 * (minus2 + log_det),
        "convention": "-2 log L_R = (N - p) log(2 pi) + sum_k [ df_k log lambda_k "
                      "+ SS_k / lambda_k ] + log det(X'X), the standard restricted "
                      "log-likelihood (Harville 1977). The last term is an additive "
                      "constant that depends on how the fixed effects are parameterised, "
                      "so a REML log-likelihood is comparable only between fits that share "
                      "one. X here is the full-rank indicator parameterisation named in "
                      "`fixed_parameterization`. The form without that term is also "
                      "reported, and any offset against a package's printed value is "
                      "reported rather than absorbed (D-064).",
    }
    if minus2 is None:
        reml_fit["likelihood_unavailable_reason"] = (
            "A fitted stratum variance is zero: covariance is singular; no finite "
            "restricted log-likelihood is reported (D-103).")
    expectations = {}
    for g, l in zip(groups, lam):
        lo, hi = _chi2_interval(float(g.ms), float(g.df)) if g.ms > 0 else (None, None)
        expectations[g.key] = {
            "stratum": g.key, "label": " + ".join(g.labels), "df": g.df,
            "ms": float(g.ms), "lower": lo, "upper": hi, "exact": True,
            "interval_method": EXACT,
            "definition": "E[MS] = " + " + ".join(
                "%d*sigma2[%s]" % (gg.m, " + ".join(gg.labels))
                for gg in groups[groups.index(g):]),
        }
    return {"components": comps, "reml": reml_fit, "stratum_expectations": expectations,
            "boundary": boundary}


# ---------------------------------------------------------------------------
# Expected mean squares
# ---------------------------------------------------------------------------

def ems_coefficients(groups: Sequence[ComponentGroup], from_index: int) -> Dict[str, int]:
    """E[MS] of the stratum at or above group `from_index`: m_j on each component j >= it."""
    return {g.key: g.m for g in groups[from_index:]}


# ---------------------------------------------------------------------------
# Fixed-effect estimates
# ---------------------------------------------------------------------------

def _estimate(key, label, value, var, df, error_term, independent_units,
              approximate=False, is_contrast=False, extra=None):
    se = math.sqrt(float(var))
    tq = t_quantile(1.0 - ALPHA / 2.0, float(df))
    rec = {"estimate_of": label, "estimate": float(value), "se": se, "df": float(df),
           "error_term": error_term, "independent_units": independent_units,
           "lower": float(value) - tq * se, "upper": float(value) + tq * se,
           "t_critical": tq, "interval_method": APPROX if approximate else EXACT,
           "approximate": approximate}
    if se == 0:
        rec.update(lower=None, upper=None, t_critical=None, interval_available=False,
                   interval_reason="The error variance is zero; the estimate is descriptive "
                                   "and its inferential interval is unavailable (D-103).")
    if is_contrast:
        t = float(value) / se if se > 0 else None
        rec.update(t=t, p=t_sf_two_sided(t, float(df)) if t is not None else None)
    if extra:
        rec.update(extra)
    return key, rec


def _contrast_specs(comp, levels, a_levels=None, b_levels=None):
    """(name, {level: coefficient}) per contrast, following D-045 reading 4 so that WP2
    and WP3 describe the same contrasts."""
    specs = []
    if comp.kind == "pairwise":
        hi, lo = comp.levels
        specs.append(("%s - %s" % (hi, lo), {hi: 1, lo: -1}))
    elif comp.kind == "overall":
        for lv in levels[1:]:
            specs.append(("%s - %s" % (lv, levels[0]), {lv: 1, levels[0]: -1}))
    else:
        for x in a_levels[1:]:
            for y in b_levels[1:]:
                specs.append(("(%s,%s)-(%s,%s)-(%s,%s)+(%s,%s)"
                              % (x, y, x, b_levels[0], a_levels[0], y,
                                 a_levels[0], b_levels[0]),
                              {(x, y): 1, (x, b_levels[0]): -1,
                               (a_levels[0], y): -1, (a_levels[0], b_levels[0]): 1}))
    return specs


# ---------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    template: Optional[str]
    decision: str                     # ANALYZE, WARN or REFUSE (carried from WP2)
    analyzed: bool
    evidence: EvidenceResult
    design: dict = field(default_factory=dict)
    anova: dict = field(default_factory=dict)
    naive_anova: dict = field(default_factory=dict)
    vc: dict = field(default_factory=dict)
    stratum_expectation: dict = field(default_factory=dict)
    estimate: dict = field(default_factory=dict)
    reml: dict = field(default_factory=dict)
    fits: dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    labels: dict = field(default_factory=dict)
    # Exact structural quantities the WP4 allocation reuses (the component groups with
    # their exact sums of squares). Not part of to_dict(), so WP3 outputs are unchanged.
    internal: dict = field(default_factory=dict, repr=False)

    def get(self, kind: str, key: str, fieldname: str):
        """The (kind, key, field) lookup the frozen WP3 comparison map uses (D-061)."""
        table = getattr(self, kind, None)
        if not isinstance(table, dict):
            raise KeyError("no such kind %r" % kind)
        if key not in table:
            raise KeyError("no %s %r (have %s)" % (kind, key, sorted(table)))
        row = table[key]
        if fieldname not in row:
            raise KeyError("no field %r on %s %r (have %s)"
                           % (fieldname, kind, key, sorted(row)))
        return row[fieldname]

    def to_dict(self) -> dict:
        return {
            "template": self.template, "decision": self.decision,
            "analyzed": self.analyzed, "design": self.design,
            "anova": self.anova, "naive_anova": self.naive_anova,
            "variance_components": self.vc,
            "stratum_expectations": self.stratum_expectation,
            "estimates": self.estimate, "reml": self.reml, "fits": self.fits,
            "notes": self.notes, "labels": self.labels,
            "evidence": self.evidence.to_dict(),
        }


def _fits(boundary, degenerate):
    return {
        "boundary": boundary,
        "degenerate": degenerate,
        "failed": [],
        "note": "Every step is closed form (exact rational ANOVA, closed-form REML, "
                "deterministic quantile functions), so no fit can fail to converge. An "
                "empty `failed` list means none occurred, not that none were looked for "
                "(D-066). A design the evidence checks refuse is not a failed fit: "
                "refusal is a successful outcome.",
    }


def _anova_row(s: Stratum, error: Optional[Stratum], groups=None, index=None):
    row = {"source": s.label, "key": s.key, "df": s.df,
           "ss": float(s.ss), "ss_exact": str(s.ss),
           "ms": _f_num(s.ms), "error_term": None, "F": None, "p": None,
           "num_df": None, "den_df": None, "note": s.note}
    if groups is not None and index is not None:
        row["ems_coefficients"] = ems_coefficients(groups, index)
        row["ems"] = " + ".join("%d*sigma2[%s]" % (g.m, " + ".join(g.labels))
                                for g in groups[index:])
        row["ems_by_key"] = " + ".join("%d*sigma2[%s]" % (v, k)
                                       for k, v in row["ems_coefficients"].items())
    if error is not None and s.ms is not None and error.ms is not None:
        row["error_term"] = error.label
        row["num_df"], row["den_df"] = s.df, error.df
        if error.ms == 0:
            row["note"] = (row["note"] + " " if row["note"] else "") + \
                "the error mean square is exactly 0, so no F statistic is defined"
        else:
            f = float(s.ms / error.ms)
            row["F"], row["p"] = f, f_sf(f, s.df, error.df)
    return row


def _rekey(strata: List[Stratum], keys: Sequence[str]) -> List[Stratum]:
    for s, k in zip(strata, keys):
        s.key = k
    return strata


def _group_index(groups: Sequence[ComponentGroup]) -> Dict[str, int]:
    return {k: i for i, g in enumerate(groups) for k in g.keys}


def _value_of(ctx, level_index: int, column: str) -> Dict:
    """Each unit's value of a column that is constant within the unit (verified by WP2)."""
    out = {}
    for i in ctx.obs:
        out.setdefault(ctx.ids[i][level_index], ctx.table.rows[i][column])
    return out


def _replicates(units, group_of, levels) -> Dict[str, int]:
    return {lv: sum(1 for u in units if group_of[u] == lv) for lv in levels}


def _satterthwaite(terms: Sequence[Tuple[float, float, float]]):
    """terms = (coefficient, mean square, df). Returns (point, nu_eff)."""
    point = sum(c * ms for c, ms, _ in terms)
    denom = sum((c * ms) ** 2 / df for c, ms, df in terms if df > 0)
    return point, (point * point / denom if denom > 0 else None)


# ---------------------------------------------------------------------------
# T1
# ---------------------------------------------------------------------------

def _t1(st: Structure, values: Dict, decl: Declaration, ev) -> AnalysisResult:
    strata = _rekey(nested_strata(st), ("A", "B", "residual"))
    groups = component_groups(strata)
    gi = _group_index(groups)
    vcres = variance_components(groups, n_fixed=1, fixed_design=(
        [(0,)] * st.n_obs, 1, "intercept only"))
    by = {s.key: s for s in strata}
    anova = {}
    for key, err in (("A", "B"), ("B", "residual"), ("residual", None)):
        s = by[key]
        anova[key] = _anova_row(s, by[err] if err else None, groups, gi[key])
    total = total_stratum(st, values)
    anova["total"] = _anova_row(total, None)
    if sum((by[k].ss for k in ("A", "B", "residual")), Q(0)) != total.ss:
        raise ArithmeticError("T1 sums of squares do not add to the total")
    anova["A"]["note"] = "tests sigma2[A] = 0 against the stratum below it"
    anova["B"]["note"] = "tests sigma2[B] = 0 against the residual stratum"

    ms_a = by["A"].ms
    est = {}
    key, rec = _estimate("grand_mean", "the overall mean of %s" % decl.response.column,
                         st.grand, ms_a / st.n_obs, by["A"].df, by["A"].label,
                         len(st.units[0]),
                         extra={"note": "Var(mean) = E[MS %s] / N, so the interval rests on "
                                        "the top-level units, not on the observations"
                                        % by["A"].label})
    est[key] = rec
    degenerate = [{"kind": "zero_error_mean_square", "stratum": k}
                  for k in ("B", "residual") if by[k].ms == 0]
    return AnalysisResult(
        "T1", ev.decision, True, ev,
        design={"levels": list(st.level_names),
                "units_per_level": [len(u) for u in st.units],
                "observations_per_unit": [st.m(l) for l in range(st.depth)],
                "n_observations": st.n_obs, "treatment": None},
        anova=anova, vc=vcres["components"],
        stratum_expectation=vcres["stratum_expectations"], estimate=est,
        reml={"fit": vcres["reml"]},
        fits=_fits(vcres["boundary"], degenerate),
        labels={"template": "T1: balanced nested variance components, no treatment",
                "levels": dict(zip(("A", "B", "residual"), st.level_names))},
        notes=["T1 has no treatment, so there is no treatment comparison. The two F tests "
               "test whether each variance component is zero.",
               "Variance-component intervals are Satterthwaite except where marked exact "
               "(D-060); every one is a per-component 95% interval, not a simultaneous band."])


# ---------------------------------------------------------------------------
# T2
# ---------------------------------------------------------------------------

def _t2_fixed_design(st: Structure, trt_of: Dict, trt_levels: Sequence[str],
                     blk_of=None, block=None):
    """The full-rank indicator parameterisation of T2's fixed effects, at the observation
    level: one column per treatment level, plus block indicators with the first observed
    block level dropped. Used only for the REML log-likelihood's additive constant
    (D-064)."""
    tops = st.ancestor_of_bottom(0)
    cols = {lv: j for j, lv in enumerate(trt_levels)}
    param = "cell means: one indicator per treatment level"
    if blk_of is None:
        rows = [(cols[trt_of[tops[u]]],) for u in st.units[-1]]
        return rows, len(cols), param
    seen = [lv for lv in block.levels if any(blk_of[t] == lv for t in st.units[0])]
    bcols = {lv: len(cols) + j - 1 for j, lv in enumerate(seen)}
    rows = []
    for u in st.units[-1]:
        top = tops[u]
        row = [cols[trt_of[top]]]
        if blk_of[top] != seen[0]:
            row.append(bcols[blk_of[top]])
        rows.append(tuple(row))
    return rows, len(cols) + len(seen) - 1, (
        param + ", plus block indicators with the first block level dropped")


def _t2_unit_level(unit_means: Dict, units: Sequence, trt_of: Dict, trt_levels: Sequence,
                   blk_of=None, blk_levels=None, scale: int = 1):
    """The unit-level decomposition: treatment, optional additive block, residual.
    `scale` is the number of observations per unit, so the sums of squares are on the
    observation scale (scale = 1 gives the unit-mean scale; the F statistic and df are the
    same either way)."""
    grand = _mean([unit_means[u] for u in units])
    tmean = _group_means(units, unit_means, trt_of)
    ss_t = scale * sum((_sq(tmean[trt_of[u]] - grand) for u in units), Q(0))
    t = len([lv for lv in trt_levels if lv in tmean])
    out = {"grand": grand, "treatment_means": tmean,
           "treatment": Stratum("treatment", "treatment", t - 1, ss_t)}
    if blk_of is None:
        ss_e = scale * sum((_sq(unit_means[u] - tmean[trt_of[u]]) for u in units), Q(0))
        out["unit"] = Stratum("unit", "units within treatment", len(units) - t, ss_e)
        out["block"] = None
    else:
        bmean = _group_means(units, unit_means, blk_of)
        k = len([lv for lv in blk_levels if lv in bmean])
        ss_b = scale * sum((_sq(bmean[blk_of[u]] - grand) for u in units), Q(0))
        ss_e = scale * sum((_sq(unit_means[u] - tmean[trt_of[u]] - bmean[blk_of[u]] + grand)
                            for u in units), Q(0))
        out["block"] = Stratum("block", "block", k - 1, ss_b)
        out["unit"] = Stratum("unit", "units within treatment and block",
                              len(units) - t - k + 1, ss_e)
        out["block_means"] = bmean
    ss_top = scale * sum((_sq(unit_means[u] - grand) for u in units), Q(0))
    parts = out["treatment"].ss + out["unit"].ss + (out["block"].ss if out["block"] else 0)
    if parts != ss_top:
        raise ArithmeticError("unit-level sums of squares do not add up")
    return out


def _t2_estimates(decl, split, ms_unit, df_unit, r_per_level, m_unit, error_label,
                  trt_levels, approximate=False):
    est = {}
    tmean = split["treatment_means"]
    for lv in trt_levels:
        if lv not in tmean:
            continue
        key, rec = _estimate("mean[%s]" % lv, "mean response at %s" % lv, tmean[lv],
                             ms_unit / (r_per_level[lv] * m_unit), df_unit, error_label,
                             r_per_level[lv], approximate=approximate)
        est[key] = rec
    t = decl.treatments[0]
    for comp in decl.comparisons:
        for name, coef in _contrast_specs(comp, [lv for lv in t.levels if lv in tmean]):
            value = sum(w * tmean[lv] for lv, w in coef.items())
            var = sum(Q(w * w, r_per_level[lv]) for lv, w in coef.items()) \
                * ms_unit / m_unit
            units = sum(r_per_level[lv] for lv in coef)
            key, rec = _estimate("%s: %s" % (comp.id, name), name, value, var, df_unit,
                                 error_label, units, approximate=approximate,
                                 is_contrast=True,
                                 extra={"comparison": comp.id, "contrast": name,
                                        "factor": t.name})
            est[key] = rec
    return est


def _t2(st: Structure, values: Dict, decl: Declaration, ev, ctx) -> AnalysisResult:
    t = decl.treatments[0]
    block = decl.blocks[0] if decl.blocks else None
    units = st.units[0]
    trt_of = _value_of(ctx, 0, t.column)
    blk_of = _value_of(ctx, 0, block.column) if block else None
    trt_levels = [lv for lv in t.levels if any(trt_of[u] == lv for u in units)]
    r_per_level = _replicates(units, trt_of, trt_levels)
    missing_sites = any(f.code == "missing_sites_exception" for f in ev.findings)
    labels = {"template": "T2: one treatment on the top level, with balanced subsampling",
              "treatment": t.name, "applied_to": t.applied_to,
              "levels": dict(enumerate(st.level_names))}
    if block:
        labels["block"] = block.name

    if missing_sites:
        return _t2_missing_sites(st, decl, ev, ctx, units, trt_of, blk_of, trt_levels,
                                 r_per_level, block, labels)

    strata = _rekey(nested_strata(st), ["unit"] + ["sub%d" % i for i in range(1, st.depth)])
    m_unit = st.m(0)
    split = _t2_unit_level(st.means[0], units, trt_of, trt_levels,
                           blk_of, list(block.levels) if block else None, scale=m_unit)
    if split["unit"].df != strata[0].df - split["treatment"].df \
            - (split["block"].df if split["block"] else 0):
        raise ArithmeticError("unit-level degrees of freedom do not add up")
    random = [Stratum("unit", split["unit"].label, split["unit"].df, split["unit"].ss,
                      m=m_unit, random=True)] + strata[1:]
    groups = component_groups(random)
    gi = _group_index(groups)
    n_fixed = len(trt_levels) + (split["block"].df if split["block"] else 0)
    vcres = variance_components(groups, n_fixed=n_fixed,
                                fixed_design=_t2_fixed_design(st, trt_of, trt_levels,
                                                              blk_of, block))

    by = {s.key: s for s in random}
    unit_s, ms_unit = by["unit"], by["unit"].ms
    anova = {}
    anova["treatment"] = _anova_row(
        Stratum("treatment", t.name, split["treatment"].df, split["treatment"].ss),
        unit_s, groups, gi["unit"])
    anova["treatment"]["ems"] += (" + (%d * sum of squared %s effects) / %d"
                                  % (m_unit * min(r_per_level.values()), t.name,
                                     split["treatment"].df))
    anova["treatment"]["note"] = ("the treatment is tested against the variation among "
                                  "units treated alike (brief Section 5.2)")
    if split["block"]:
        anova["block"] = _anova_row(split["block"], unit_s, groups, gi["unit"])
        anova["block"]["note"] = ("descriptive only: the block was recorded, not "
                                  "randomised, so a block difference is not a causal "
                                  "comparison (D-063)")
    # A collapsed stratum (one unit per parent) has no degrees of freedom and no mean
    # square, so it is omitted from the table and the stratum above it is tested against
    # the next stratum that does have degrees of freedom (D-062).
    live = [s for s in random if s.df > 0]
    collapsed = [s.key for s in random if s.df == 0]
    for i, s in enumerate(live):
        anova[s.key] = _anova_row(s, live[i + 1] if i + 1 < len(live) else None,
                                  groups, gi[s.key])
    anova["unit"]["note"] = "the experimental-unit error stratum for the treatment test"
    total = total_stratum(st, values)
    anova["total"] = _anova_row(total, None)
    parts = split["treatment"].ss + split["unit"].ss + sum((s.ss for s in strata[1:]), Q(0))
    if split["block"]:
        parts += split["block"].ss
    if parts != total.ss:
        raise ArithmeticError("T2 sums of squares do not add to the total")

    est = _t2_estimates(decl, split, ms_unit, unit_s.df, r_per_level, m_unit,
                        unit_s.label, trt_levels)
    degenerate = [{"kind": "zero_error_mean_square", "stratum": s.key}
                  for s in live if s.ms == 0]
    notes = ["The treatment is judged against %d independent %s units per level; more "
             "lower-level measurements cannot replace them."
             % (min(r_per_level.values()), t.applied_to)]
    merged = [g for g in groups if len(g.keys) > 1]
    if merged:
        notes.append("Components %s are not separately identifiable, because a level has "
                     "one unit per parent; only their combined component is reported, and "
                     "the stratum that would have separated them (%s) has no degrees of "
                     "freedom and is omitted from the table (D-054, D-062)."
                     % (", ".join(g.key for g in merged), ", ".join(collapsed) or "none"))
    if block:
        notes.append("With a block in the model, sigma2[unit] is run-to-run variation "
                     "within a block, and the block is fixed (D-063). The additive error "
                     "term contains any treatment-by-block interaction, so the treatment "
                     "test is conservative if that interaction is real.")
    return AnalysisResult(
        "T2", ev.decision, True, ev,
        design={"levels": list(st.level_names),
                "units_per_level": [len(u) for u in st.units],
                "observations_per_unit": [st.m(l) for l in range(st.depth)],
                "n_observations": st.n_obs, "treatment": t.name,
                "treatment_levels": trt_levels, "replicates_per_level": r_per_level,
                "block": block.name if block else None,
                "block_levels": list(block.levels) if block else None,
                "collapsed_strata": collapsed},
        anova=anova, vc=vcres["components"],
        stratum_expectation=vcres["stratum_expectations"], estimate=est,
        reml={"fit": vcres["reml"]}, fits=_fits(vcres["boundary"], degenerate),
        labels=labels, notes=notes,
        internal={"groups": groups, "level_keys": [s.key for s in random],
                  "level_labels": [s.label for s in random],
                  "counts": [len(st.units[l]) // len(st.units[l - 1])
                             for l in range(1, st.depth)],
                  "t": len(trt_levels), "r": min(r_per_level.values()),
                  "k": len(block.levels) if block else None,
                  "k_observed": len(set(blk_of[u] for u in units)) if block else None,
                  "level_names": list(st.level_names)})


def _t2_missing_sites(st, decl, ev, ctx, units, trt_of, blk_of, trt_levels, r_per_level,
                      block, labels) -> AnalysisResult:
    """D-065: the narrow missing-site exception. Unit means only; no components, no
    expected-mean-square decomposition, no REML, no allocation."""
    t = decl.treatments[0]
    split = _t2_unit_level(st.means[0], units, trt_of, trt_levels,
                           blk_of, list(block.levels) if block else None, scale=1)
    unit_s = split["unit"]
    anova = {"treatment": _anova_row(
        Stratum("treatment", t.name, split["treatment"].df, split["treatment"].ss),
        unit_s)}
    anova["treatment"]["note"] = ("computed on experimental-unit means (D-016); "
                                  "approximate, because unequal site counts give the unit "
                                  "means unequal precision")
    if split["block"]:
        anova["block"] = _anova_row(split["block"], unit_s)
        anova["block"]["note"] = "descriptive only (D-063)"
    anova["unit"] = _anova_row(unit_s, None)
    anova["unit"]["note"] = "the experimental-unit error stratum, on the unit-mean scale"
    est = _t2_estimates(decl, split, unit_s.ms, unit_s.df, r_per_level, 1, unit_s.label,
                        trt_levels, approximate=True)
    withheld = {
        "variance_components": "withheld: D-016 forbids balanced expected-mean-square "
                               "variance-component inference on an unbalanced "
                               "missing-site case",
        "reml": "withheld: the closed-form REML of D-064 is valid only for balanced data",
        "allocation": "withheld: the allocation decomposition needs the variance "
                      "components (D-016); the report must say so",
    }
    return AnalysisResult(
        "T2", ev.decision, True, ev,
        design={"levels": list(st.level_names),
                "units_per_level": [len(u) for u in st.units],
                "n_observations": st.n_obs, "treatment": t.name,
                "treatment_levels": trt_levels, "replicates_per_level": r_per_level,
                "block": block.name if block else None,
                "missing_site_exception": True,
                "site_counts": ev.evidence.get("missing_sites", {})},
        anova=anova, estimate=est, reml={}, vc={},
        fits=_fits([], [{"kind": "zero_error_mean_square", "stratum": "unit"}]
                   if unit_s.ms == 0 else []),
        labels=dict(labels, template=labels["template"] + " (missing-site exception)"),
        notes=["The narrow missing-site exception applies (D-016, D-065). Experimental-unit "
               "means are formed hierarchically: sites are averaged within a wafer, then "
               "wafers are weighted equally within a unit.",
               "The treatment test, its standard errors and its intervals are APPROXIMATE: "
               "the exact balanced F test needs every unit mean to have the same variance, "
               "and unequal site counts break that.",
               withheld["variance_components"], withheld["reml"], withheld["allocation"]])


# ---------------------------------------------------------------------------
# T3
# ---------------------------------------------------------------------------

def _t3(st: Structure, values: Dict, decl: Declaration, ev, ctx) -> AnalysisResult:
    a_t = decl.treatment(decl.split_plot.whole_plot_factor)
    b_t = decl.treatment(decl.split_plot.subplot_factor)
    plots, subs = st.units[0], st.units[1]
    a_of = _value_of(ctx, 0, a_t.column)
    b_of = _value_of(ctx, 1, b_t.column)
    a_levels = [lv for lv in a_t.levels if any(a_of[u] == lv for u in plots)]
    b_levels = [lv for lv in b_t.levels if any(b_of[u] == lv for u in subs)]
    a, b, n_plots = len(a_levels), len(b_levels), len(plots)
    r_per_level = _replicates(plots, a_of, a_levels)
    grand = st.grand
    strata = nested_strata(st)

    # Whole-plot stratum: A and the whole-plot error.
    split = _t2_unit_level(st.means[0], plots, a_of, a_levels, scale=st.m(0))
    a_row = Stratum("A", a_t.name, split["treatment"].df, split["treatment"].ss)
    wp_err = Stratum("wholeplot", "whole plots within %s" % a_t.name, split["unit"].df,
                     split["unit"].ss, m=st.m(0), random=True)

    # Subplot stratum: B, A x B, and the subplot error.
    amean = split["treatment_means"]
    bmean = _group_means(subs, st.means[1], b_of)
    cell_of = {u: (a_of[st.parent[1][u]], b_of[u]) for u in subs}
    cmean = _group_means(subs, st.means[1], cell_of)
    ss_b = sum((_sq(bmean[b_of[u]] - grand) for u in subs), Q(0))
    ss_ab = sum((_sq(cmean[cell_of[u]] - amean[cell_of[u][0]] - bmean[b_of[u]] + grand)
                 for u in subs), Q(0))
    ss_e = sum((_sq(st.means[1][u] - st.means[0][st.parent[1][u]] - cmean[cell_of[u]]
                    + amean[cell_of[u][0]]) for u in subs), Q(0))
    if ss_b + ss_ab + ss_e != strata[1].ss:
        raise ArithmeticError("T3 subplot sums of squares do not add up")
    b_row = Stratum("B", b_t.name, b - 1, ss_b)
    ab_row = Stratum("AB", "%s x %s" % (a_t.name, b_t.name), (a - 1) * (b - 1), ss_ab)
    sp_err = Stratum("residual", "subplot error",
                     strata[1].df - b_row.df - ab_row.df, ss_e, m=1, random=True)

    random = [wp_err, sp_err]
    groups = component_groups(random)
    gi = _group_index(groups)
    cell_cols = {c: j for j, c in enumerate(sorted({cell_of[u] for u in subs}))}
    vcres = variance_components(groups, n_fixed=a * b, fixed_design=(
        [(cell_cols[cell_of[u]],) for u in subs], len(cell_cols),
        "cell means: one indicator per whole-plot x subplot cell"))
    ms_g, ms_e = wp_err.ms, sp_err.ms

    anova = {}
    for row, err, idx, key in ((a_row, wp_err, gi["wholeplot"], "A"),
                               (wp_err, sp_err, gi["wholeplot"], "wholeplot_error"),
                               (b_row, sp_err, gi["residual"], "B"),
                               (ab_row, sp_err, gi["residual"], "AB"),
                               (sp_err, None, gi["residual"], "subplot_error")):
        anova[key] = _anova_row(row, err, groups, idx)
        anova[key]["key"] = key
    r_min = min(r_per_level.values())
    anova["A"]["ems"] += (" + (%d * sum of squared %s effects) / %d"
                          % (r_min * st.m(0), a_t.name, a_row.df))
    anova["B"]["ems"] += (" + (%d * sum of squared %s effects) / %d"
                          % (n_plots, b_t.name, b_row.df))
    anova["AB"]["ems"] += (" + (%d * sum of squared %s x %s effects) / %d"
                           % (r_min, a_t.name, b_t.name, ab_row.df))
    anova["A"]["note"] = ("the whole-plot factor is tested against whole-plot error on "
                          "(%d, %d) df (brief Section 5.3)" % (a_row.df, wp_err.df))
    anova["B"]["note"] = "the subplot factor is tested against subplot error"
    anova["AB"]["note"] = "the interaction lives in the subplot stratum"
    anova["wholeplot_error"]["note"] = ("the error term for %s; it also tests "
                                        "sigma2[whole plot] = 0" % a_t.name)
    total = total_stratum(st, values)
    anova["total"] = _anova_row(total, None)
    if a_row.ss + wp_err.ss + ss_b + ss_ab + ss_e != total.ss:
        raise ArithmeticError("T3 sums of squares do not add to the total")

    # The naive single-error analysis the brief requires beside the correct one.
    naive_res = Stratum("residual", "residual (single error term)",
                        wp_err.df + sp_err.df, wp_err.ss + sp_err.ss)
    naive = {}
    for row, key in ((a_row, "A"), (b_row, "B"), (ab_row, "AB")):
        naive[key] = _anova_row(row, naive_res)
        naive[key]["key"] = key
    naive["residual"] = _anova_row(naive_res, None)
    naive["residual"]["key"] = "residual"
    naive["A"]["note"] = ("WRONG for this design: it tests a factor applied to whole plots "
                          "against subplot error, treating the %d readings on one %s as "
                          "independent replicates of %s" % (b, st.level_names[0], a_t.name))
    naive["note"] = ("Reported only for contrast (brief Section 5.3). Pooling the two error "
                     "strata gives %d residual df instead of %d, so %s is judged against "
                     "within-%s variation it was never applied to."
                     % (naive_res.df, wp_err.df, a_t.name, st.level_names[0]))

    # Estimates.
    est = {}
    for lv in a_levels:
        key, rec = _estimate("mean_A[%s]" % lv, "mean response at %s %s" % (a_t.name, lv),
                             amean[lv], ms_g / (r_per_level[lv] * st.m(0)), wp_err.df,
                             wp_err.label, r_per_level[lv])
        est[key] = rec
    sat_b = _satterthwaite([(1.0 / (b * n_plots), float(ms_g), wp_err.df),
                            ((b - 1.0) / (b * n_plots), float(ms_e), sp_err.df)])
    for lv in b_levels:
        key, rec = _estimate("mean_B[%s]" % lv, "mean response at %s %s" % (b_t.name, lv),
                             bmean[lv], Q(0), sat_b[1] or sp_err.df,
                             "both strata (whole plot and subplot)",
                             n_plots, approximate=True)
        rec["se"] = math.sqrt(sat_b[0])
        tq = t_quantile(1.0 - ALPHA / 2.0, rec["df"]) if rec["se"] > 0 else None
        # This mean uses both strata; _estimate received a placeholder variance.
        if rec["se"] > 0:
            rec.pop("interval_available", None)
            rec.pop("interval_reason", None)
        rec.update(t_critical=tq, lower=rec["estimate"] - tq * rec["se"] if tq else None,
                   upper=rec["estimate"] + tq * rec["se"] if tq else None,
                   note="the standard error of a subplot-level mean needs both mean "
                        "squares, so its df is Satterthwaite-approximated; the %s "
                        "contrasts below use the subplot stratum alone and are exact"
                        % b_t.name)
        est[key] = rec
    for comp in decl.comparisons:
        factors = list(comp.factors)
        if comp.kind == "interaction":
            specs = _contrast_specs(comp, None, a_levels, b_levels)
            for name, coef in specs:
                per_a: Dict[str, int] = {}
                for (i, k), w in coef.items():
                    per_a[i] = per_a.get(i, 0) + w
                if any(v != 0 for v in per_a.values()):
                    raise ArithmeticError("interaction contrast is not within whole plots")
                value = sum(w * cmean[c] for c, w in coef.items())
                var = sum(Q(w * w, r_per_level[c[0]]) for c, w in coef.items()) * ms_e
                involved = sorted({i for i, _ in coef})
                key, rec = _estimate("%s: %s" % (comp.id, name), name, value, var,
                                     sp_err.df, sp_err.label,
                                     sum(r_per_level[i] for i in involved),
                                     is_contrast=True,
                                     extra={"comparison": comp.id, "contrast": name,
                                            "factor": "%s x %s" % (a_t.name, b_t.name),
                                            "units_note": "each whole plot contributes one "
                                                          "independent within-plot "
                                                          "comparison"})
                est[key] = rec
        elif factors[0] == a_t.name:
            for name, coef in _contrast_specs(comp, a_levels):
                value = sum(w * amean[lv] for lv, w in coef.items())
                var = sum(Q(w * w, r_per_level[lv] * st.m(0))
                          for lv, w in coef.items()) * ms_g
                key, rec = _estimate("%s: %s" % (comp.id, name), name, value, var,
                                     wp_err.df, wp_err.label,
                                     sum(r_per_level[lv] for lv in coef),
                                     is_contrast=True,
                                     extra={"comparison": comp.id, "contrast": name,
                                            "factor": a_t.name})
                est[key] = rec
        else:
            for name, coef in _contrast_specs(comp, b_levels):
                value = sum(w * bmean[lv] for lv, w in coef.items())
                var = sum(Q(w * w, n_plots) for lv, w in coef.items()) * ms_e
                key, rec = _estimate("%s: %s" % (comp.id, name), name, value, var,
                                     sp_err.df, sp_err.label, n_plots,
                                     is_contrast=True,
                                     extra={"comparison": comp.id, "contrast": name,
                                            "factor": b_t.name,
                                            "units_note": "each whole plot contributes one "
                                                          "independent within-plot "
                                                          "comparison"})
                est[key] = rec

    degenerate = [{"kind": "zero_error_mean_square", "stratum": k}
                  for k, s in (("wholeplot_error", wp_err), ("subplot_error", sp_err))
                  if s.ms == 0]
    return AnalysisResult(
        "T3", ev.decision, True, ev,
        design={"levels": list(st.level_names), "whole_plot_factor": a_t.name,
                "subplot_factor": b_t.name, "a": a, "b": b,
                "whole_plots": n_plots, "replicates_per_level": r_per_level,
                "n_observations": st.n_obs, "a_levels": a_levels, "b_levels": b_levels},
        anova=anova, naive_anova=naive, vc=vcres["components"],
        stratum_expectation=vcres["stratum_expectations"], estimate=est,
        reml={"fit": vcres["reml"]}, fits=_fits(vcres["boundary"], degenerate),
        internal={"groups": groups, "level_keys": ["wholeplot", "residual"],
                  "level_labels": [wp_err.label, sp_err.label],
                  "a": a, "b": b, "r": r_min, "level_names": list(st.level_names)},
        labels={"template": "T3: balanced split-plot",
                "A": a_t.name, "B": b_t.name,
                "whole_plot_level": st.level_names[0], "subplot_level": st.level_names[1]},
        notes=["%s is applied to whole %ss, so the only replication it has is the %d "
               "%ss per level: it is tested on (%d, %d) df against whole-plot error, and "
               "the denominator df count a(r - 1) = %d x (%d - 1) = %d."
               % (a_t.name, st.level_names[0], r_min, st.level_names[0], a_row.df,
                  wp_err.df, a, r_min, wp_err.df),
               "%s and %s x %s vary inside a whole plot, so every whole plot contributes "
               "its own comparison: they are tested against subplot error on "
               "a(r - 1)(b - 1) = %d x (%d - 1) x (%d - 1) = %d df."
               % (b_t.name, a_t.name, b_t.name, a, r_min, b, sp_err.df),
               "That is why the two factors have different denominator degrees of freedom "
               "even though they come from the same %d readings: they are replicated at "
               "different levels of the design." % st.n_obs,
               "The naive single-error analysis is reported beside the correct one and is "
               "labelled wrong for this design (brief Section 5.3)."])


# ---------------------------------------------------------------------------
# The T2 kernel cross-checks (D-067)
# ---------------------------------------------------------------------------

KERNEL_LABEL = ("Arithmetic cross-check of the T2 kernel only (DECISIONS.md D-067). This is "
                "not an analysis of this dataset as a T2 experiment: the factor was not "
                "randomised, no Stratum declaration matches it to T2 (D-014, D-039), and no "
                "causal claim is made.")


def t2_kernel(st: Structure, trt_of: Dict, trt_levels: Sequence[str],
              contrast: Optional[Tuple[str, str]] = None) -> dict:
    """Run the T2 kernel on a structure built directly rather than from a declaration.

    With `st.depth == 1` this is the unit-mean one-way treatment test; with a deeper
    hierarchy it is the full stratified analysis. Used for the two R-anchored cross-checks
    frozen in D-067."""
    units = st.units[0]
    r_per_level = _replicates(units, trt_of, trt_levels)
    scale = st.m(0) if st.depth > 1 else 1
    split = _t2_unit_level(st.means[0], units, trt_of, trt_levels, scale=scale)
    unit_s = split["unit"]
    out = {"kernel_label": KERNEL_LABEL, "anova": {}, "estimate": {}, "vc": {},
           "reml": {}, "replicates_per_level": r_per_level}
    trt = Stratum("treatment", "treatment", split["treatment"].df, split["treatment"].ss)
    out["anova"]["treatment"] = _anova_row(trt, unit_s)
    out["anova"]["treatment"]["note"] = KERNEL_LABEL
    out["anova"]["unit"] = _anova_row(unit_s, None)
    if st.depth > 1:
        strata = _rekey(nested_strata(st),
                        ["unit"] + ["sub%d" % i for i in range(1, st.depth)])
        random = [Stratum("unit", unit_s.label, unit_s.df, unit_s.ss, m=scale,
                          random=True)] + strata[1:]
        groups = component_groups(random)
        vcres = variance_components(groups, n_fixed=len(trt_levels),
                                    fixed_design=_t2_fixed_design(st, trt_of, trt_levels))
        out["vc"] = vcres["components"]
        out["reml"] = {"fit": vcres["reml"]}
    if contrast:
        hi, lo = contrast
        tmean = split["treatment_means"]
        value = tmean[hi] - tmean[lo]
        var = (Q(1, r_per_level[hi]) + Q(1, r_per_level[lo])) * unit_s.ms / scale
        key, rec = _estimate("contrast", "%s - %s" % (hi, lo), value, var, unit_s.df,
                             unit_s.label, r_per_level[hi] + r_per_level[lo],
                             is_contrast=True, extra={"note": KERNEL_LABEL})
        out["estimate"]["contrast"] = rec
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def analyze(declaration: Union[Path, str, dict, Declaration],
            data: Union[Path, str, Table]) -> AnalysisResult:
    """Match the declaration, run the evidence checks, and analyze when they allow it."""
    ev = check_evidence(declaration, data)
    if ev.decision == "REFUSE" or ev.context is None or ev.match is None \
            or ev.match.declaration is None:
        return AnalysisResult(
            ev.claimed_template, ev.decision, False, ev,
            notes=["No analysis was produced. The evidence checks refused this design, and "
                   "refusal is a successful outcome (brief Section 8): Stratum does not "
                   "estimate anything a declared design cannot support.",
                   "Reasons: " + "; ".join("[%s] %s" % (f.code, f.message)
                                           for f in ev.by_severity("refuse"))])
    ctx, decl = ev.context, ev.match.declaration
    st = structure_from_context(ctx)
    values = {ctx.ids[i][-1]: ctx.values[i] for i in ctx.obs}
    if decl.claimed_template == "T1":
        return _t1(st, values, decl, ev)
    if decl.claimed_template == "T2":
        return _t2(st, values, decl, ev, ctx)
    if decl.claimed_template == "T3":
        return _t3(st, values, decl, ev, ctx)
    raise ValueError("unsupported template %r reached the analysis" % decl.claimed_template)
