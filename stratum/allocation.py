"""WP4: the allocation analysis (brief Section 5.5; DECISIONS.md D-078, D-079, D-081).

For a comparison of two treatment-level means with r units per level, the variance is a
sum of coefficient x variance component. For T2 with levels l = 0 (the experimental unit)
down to the lowest, and n_j units per parent below the unit,

    V(r', n'_1, ..., n'_{D-1}) = (2 / r') * sum_l sigma^2_l / (n'_1 * ... * n'_l),

which for D = 3 is exactly (2/r)(sigma^2_R + sigma^2_W / w + sigma^2_S / (w s)). The floor,
as every lower count grows, is 2 sigma^2_0 / r: only more experimental units lower it.

The components are the closed-form REML estimates of D-064. Every output is classified
(D-078):

  identified    every merged group enters with one coefficient, so a value is given;
  limited       a merged group (w = 1 or s = 1) enters with unequal coefficients, so only
                bounds over the unidentified split are implied, and no point value is given;
  lower_bound   a component is not estimable (r = 1), so only the estimable part is known;
  not_estimable nothing estimable enters, so no number is given.

Uncertainty is shown with plausible values of the stratum mean squares (D-079): for each
estimable stratum, lambda* = nu MS / U with U ~ chi-square(nu), converted to components
exactly as the point estimate is, on a fixed seed.
"""
import functools
import hashlib
import math
import random
import statistics
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

from .analysis import _group_means, _mean, _sq, _value_of, nested_strata, structure_from_context

Q = Fraction
INF = None                          # an unbounded count (the floor)
N_DRAWS = 20000                     # D-079
SEED_TEXT = "stratum-wp4-plausible-values-v1"
SEED = int(hashlib.sha256(SEED_TEXT.encode("utf-8")).hexdigest()[:16], 16)
ROBUST_WINS = 19000                 # 95% of N_DRAWS (D-079)
ROBUST_SENTENCE = "only additional %s lower the floor."   # brief Section 5.5, verbatim


def plural(name: str) -> str:
    return name if name.endswith("s") else name + "s"


def sig6(x: Optional[float]) -> Optional[float]:
    return None if x is None else float("%.6g" % x)


# ---------------------------------------------------------------------------
# The component model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelGroup:
    """One component group: adjacent levels merged because the stratum that would separate
    them has no degrees of freedom (D-054, D-062), or a single level."""
    levels: Tuple[int, ...]          # indices into ComponentModel.level_keys
    m: int                           # observations per unit at the group's top level
    df: int
    ss: Optional[Fraction]           # None when not estimable (0 df, D-081)

    @property
    def estimable(self) -> bool:
        return self.df > 0 and self.ss is not None

    @property
    def ms(self) -> Fraction:
        return self.ss / self.df


@dataclass(frozen=True)
class ComponentModel:
    level_keys: Tuple[str, ...]
    level_labels: Tuple[str, ...]
    groups: Tuple[ModelGroup, ...]
    basis: str

    def group_key(self, g: ModelGroup) -> str:
        return "+".join(self.level_keys[i] for i in g.levels)

    def group_label(self, g: ModelGroup) -> str:
        return " + ".join(self.level_labels[i] for i in g.levels)


def model_from_strata(keys, labels, strata, basis) -> ComponentModel:
    """strata: (m, df, ss) top to bottom, one per level. Adjacent levels with the same m are
    merged (the lower one has 0 df). A group with 0 df is not estimable; that can only be
    the top group (D-081, r = 1)."""
    groups: List[List] = []
    for i, (m, df, ss) in enumerate(strata):
        if groups and groups[-1][1] == m:
            if df:
                raise ValueError("merged level %r has %d df, expected 0" % (keys[i], df))
            groups[-1][0].append(i)
            continue
        groups.append([[i], m, df, ss])
    out = tuple(ModelGroup(tuple(lv), m, df, ss if df > 0 else None)
                for lv, m, df, ss in groups)
    for g in out[1:]:
        if not g.estimable:
            raise ValueError("only the top component group may be non-estimable")
    if not any(g.estimable for g in out):
        raise ValueError("no estimable component group")
    return ComponentModel(tuple(keys), tuple(labels), out, basis)


def model_from_analysis(internal: dict) -> ComponentModel:
    """The WP3 analysis's own component groups (all estimable)."""
    keys = list(internal["level_keys"])
    index = {k: i for i, k in enumerate(keys)}
    groups = tuple(ModelGroup(tuple(index[k] for k in g.keys), g.m, g.df, g.ss)
                   for g in internal["groups"])
    return ComponentModel(tuple(keys), tuple(internal["level_labels"]), groups,
                          "the WP3 analysis's stratum mean squares")


def pava(dfs: Sequence[float], ss: Sequence[float]) -> List[float]:
    """Df-weighted pool-adjacent-violators under lambda_0 >= lambda_1 >= ... (D-064), in
    floating point for the plausible-value draws. Identical in logic to
    analysis.reml_isotonic."""
    blocks = [[d, s] for d, s in zip(dfs, ss)]
    sizes = [1] * len(blocks)
    i = 0
    while i + 1 < len(blocks):
        if blocks[i][1] / blocks[i][0] < blocks[i + 1][1] / blocks[i + 1][0]:
            blocks[i] = [blocks[i][0] + blocks[i + 1][0], blocks[i][1] + blocks[i + 1][1]]
            sizes[i] += sizes[i + 1]
            del blocks[i + 1], sizes[i + 1]
            if i:
                i -= 1
        else:
            i += 1
    out: List[float] = []
    for (d, s), n in zip(blocks, sizes):
        out.extend([s / d] * n)
    return out


def pava_exact(dfs: Sequence[int], ss: Sequence[Fraction]) -> List[Fraction]:
    blocks = [[Q(d), Q(s)] for d, s in zip(dfs, ss)]
    sizes = [1] * len(blocks)
    i = 0
    while i + 1 < len(blocks):
        if blocks[i][1] / blocks[i][0] < blocks[i + 1][1] / blocks[i + 1][0]:
            blocks[i] = [blocks[i][0] + blocks[i + 1][0], blocks[i][1] + blocks[i + 1][1]]
            sizes[i] += sizes[i + 1]
            del blocks[i + 1], sizes[i + 1]
            if i:
                i -= 1
        else:
            i += 1
    out: List[Fraction] = []
    for (d, s), n in zip(blocks, sizes):
        out.extend([s / d] * n)
    return out


def _components(model: ComponentModel, lam: Sequence) -> List:
    """Group components from the estimable groups' lambdas (triangular inversion); None for
    a non-estimable group."""
    idx = [i for i, g in enumerate(model.groups) if g.estimable]
    out = [None] * len(model.groups)
    for j, i in enumerate(idx):
        if j + 1 < len(idx):
            out[i] = (lam[j] - lam[j + 1]) / model.groups[i].m
        else:
            out[i] = lam[j]
    return out


def point_components(model: ComponentModel) -> Tuple[List, List]:
    est = [g for g in model.groups if g.estimable]
    lam = pava_exact([g.df for g in est], [g.ss for g in est])
    return _components(model, lam), lam


# ---------------------------------------------------------------------------
# Evaluating a scenario: identified, limited, lower bound or not estimable
# ---------------------------------------------------------------------------

def classify(model: ComponentModel, coefs: Sequence[Fraction]) -> str:
    """The status depends only on the coefficient structure, never on the data."""
    unbounded = est_positive = limited = False
    for g in model.groups:
        cs = [coefs[i] for i in g.levels]
        if not g.estimable:
            unbounded = unbounded or max(cs) > 0
            continue
        est_positive = est_positive or max(cs) > 0
        limited = limited or min(cs) != max(cs)
    if unbounded:
        return "lower_bound" if est_positive else "not_estimable"
    return "limited" if limited else "identified"


def bounds(model: ComponentModel, coefs: Sequence, comps: Sequence):
    """(lower, upper) of the variance over the unidentified splits; upper None when a
    non-estimable component enters."""
    lo = hi = 0
    unbounded = False
    for g, c in zip(model.groups, comps):
        cs = [coefs[i] for i in g.levels]
        if c is None:
            unbounded = unbounded or max(cs) > 0
            continue
        lo += min(cs) * c
        hi += max(cs) * c
    return lo, (None if unbounded else hi)


def _fast_terms(model: ComponentModel, coefs: Sequence) -> List[Tuple[int, float, float, bool]]:
    """(group index, min coefficient, max coefficient, estimable) per group, in floats."""
    out = []
    for i, g in enumerate(model.groups):
        cs = [float(coefs[l]) for l in g.levels]
        out.append((i, min(cs), max(cs), g.estimable))
    return out


def _fast_bounds(terms, comps):
    lo = hi = 0.0
    unbounded = False
    for i, cmin, cmax, est in terms:
        c = comps[i]
        if c is None:
            unbounded = unbounded or cmax > 0
            continue
        lo += cmin * c
        hi += cmax * c
    return lo, (None if unbounded else hi)


# ---------------------------------------------------------------------------
# Plausible values (D-079)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=128)
def plausible_components(model: ComponentModel, n: int = N_DRAWS, seed: int = SEED):
    """n draws of the group components. Each estimable stratum: lambda* = nu MS / U,
    U ~ chi-square(nu) = 2 Gamma(nu/2, 1); then the same PAVA and inversion as the point
    estimate. A pure function of (model, n, seed), so it is cached; the result is a tuple
    and is never mutated."""
    est = [g for g in model.groups if g.estimable]
    dfs = [float(g.df) for g in est]
    ms = [float(g.ms) for g in est]
    rng = random.Random(seed)
    draws = []
    for _ in range(n):
        lam_star = [d * m / (2.0 * rng.gammavariate(d / 2.0, 1.0)) for d, m in zip(dfs, ms)]
        lam = pava(dfs, [d * l for d, l in zip(dfs, lam_star)])
        draws.append(tuple(_components(model, lam)))
    return tuple(draws)


def _pct(values: List[float]) -> Dict[str, float]:
    if len(values) < 2:
        v = values[0] if values else None
        return {"p2_5": sig6(v), "p50": sig6(v), "p97_5": sig6(v)}
    q = statistics.quantiles(values, n=40, method="inclusive")
    return {"p2_5": sig6(q[0]), "p50": sig6(q[19]), "p97_5": sig6(q[38])}


def _sqrt(v) -> Optional[float]:
    return None if v is None else math.sqrt(max(float(v), 0.0))


# ---------------------------------------------------------------------------
# One comparison's allocation table
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    id: str
    label: str
    design: dict
    coefs: List[Fraction]
    added_units: str
    added_measurements: int
    error_df: Optional[int]
    candidate: bool = False
    balanced: bool = True
    note: str = ""


def _evaluate(model, scenarios: List[Scenario], comps, draws) -> List[dict]:
    out = []
    for sc in scenarios:
        status = classify(model, sc.coefs)
        lo, hi = bounds(model, sc.coefs, comps)
        rec = {"id": sc.id, "label": sc.label, "design": sc.design,
               "added_units": sc.added_units, "added_measurements": sc.added_measurements,
               "error_df": sc.error_df, "balanced": sc.balanced, "status": status,
               "note": sc.note, "candidate": sc.candidate}
        if status == "identified":
            rec["se"] = _sqrt(lo)
            rec["variance"] = float(lo)
        elif status == "limited":
            rec.update(se=None, se_lower=_sqrt(lo), se_upper=_sqrt(hi),
                       bounds_note="identifiability bounds at the point estimate, not an "
                                   "interval estimate: the data identify only a combined "
                                   "component, and both of its parts are >= 0")
        elif status == "lower_bound":
            rec.update(se=None, se_lower=_sqrt(lo), se_upper=None,
                       bounds_note="lower bound only: a component that enters this "
                                   "variance is not estimable from these data, so no upper "
                                   "bound exists")
        else:
            rec.update(se=None, se_lower=None, se_upper=None,
                       bounds_note="not estimable: the only component that enters is not "
                                   "estimable from these data")
        if draws is not None and status != "not_estimable":
            los, his = [], []
            terms = _fast_terms(model, sc.coefs)
            for d in draws:
                a, b = _fast_bounds(terms, d)
                los.append(math.sqrt(max(a, 0.0)))
                if b is not None:
                    his.append(math.sqrt(max(b, 0.0)))
            if status == "identified":
                rec["plausible_se"] = _pct(los)
            else:
                rec["plausible_se_lower"] = _pct(los)
                if his:
                    rec["plausible_se_upper"] = _pct(his)
        out.append(rec)
    return out


def _ranking(model, scenarios: List[Scenario], records: List[dict], draws, unit_plural):
    cands = [(sc, rec) for sc, rec in zip(scenarios, records) if sc.candidate]
    result = {"candidates": [sc.id for sc, _ in cands],
              "candidate_labels": {sc.id: sc.label for sc, _ in cands},
              "draws": len(draws) if draws else 0,
              "robust_threshold_wins": ROBUST_WINS, "seed_text": SEED_TEXT}
    if len(cands) < 2:
        result.update(assessed=False, reason="fewer than two single additions to compare")
        return result
    bad = [rec["id"] for _, rec in cands if rec["status"] != "identified"]
    if bad:
        names = [rec["label"] for _, rec in cands if rec["status"] != "identified"]
        result.update(assessed=False,
                      reason="not assessed: %s %s not identified (limited or a lower bound), "
                             "so the order of the standard errors is not determined by the "
                             "data" % ("; ".join(names), "is" if len(names) == 1 else "are"))
        return result
    wins = {sc.id: 0 for sc, _ in cands}
    ties = 0
    fcs = [(_fast_terms(model, sc.coefs), sc.id) for sc, _ in cands]
    for d in draws:
        vals = [(_fast_bounds(t, d)[0], sid) for t, sid in fcs]
        vals.sort()
        if vals[0][0] == vals[1][0]:
            ties += 1
        else:
            wins[vals[0][1]] += 1
    best = max(wins, key=lambda k: wins[k])
    robust = wins[best] >= ROBUST_WINS
    labels = {sc.id: sc.label for sc, _ in cands}
    result.update(assessed=True, wins=wins, ties=ties,
                  shares={k: v / len(draws) for k, v in wins.items()},
                  shares_percent={k: 100.0 * v / len(draws) for k, v in wins.items()},
                  candidate_labels=labels,
                  best=best, best_label=labels[best], best_share=wins[best] / len(draws),
                  robust=robust)
    return result


def _conclusion(ranking, unit_name, lower_names, has_floor):
    unit_pl = plural(unit_name)
    lower = " or ".join(plural(n) for n in lower_names) or "lower-level units"
    out = {}
    if has_floor:
        out["floor_statement"] = ("No number of additional %s can bring the standard error "
                                  "below the floor; only additional %s lower it."
                                  % (lower, unit_pl))
    if ranking.get("assessed") and ranking.get("robust"):
        if ranking["best"] == "add_unit":
            out["robust_conclusion"] = "Robust conclusion: " + ROBUST_SENTENCE % unit_pl
        else:
            out["robust_conclusion"] = ("Robust conclusion: %s lowers the standard error "
                                        "most in at least 95%% of plausible values; the floor "
                                        "still moves only with more %s."
                                        % (ranking["best_label"], unit_pl))
    elif ranking.get("assessed"):
        out["ranking_statement"] = ("Which single addition lowers the standard error most is "
                                    "uncertain with these data: no option wins in 95% of "
                                    "plausible values.")
    return out


# ---------------------------------------------------------------------------
# T2 and T3 scenario builders
# ---------------------------------------------------------------------------

def _prod(xs) -> Optional[int]:
    p = 1
    for x in xs:
        if x is INF:
            return INF
        p *= x
    return p


def _t2_coefs(r: int, counts: Sequence) -> List[Fraction]:
    out = [Q(2, r)]
    for l in range(1, len(counts) + 1):
        p = _prod(counts[:l])
        out.append(Q(0) if p is INF else Q(2, r * p))
    return out


def t2_scenarios(t: int, r: int, counts: Sequence[int], level_names: Sequence[str],
                 k: Optional[int]) -> List[Scenario]:
    """level_names[0] is the experimental unit; counts[j-1] units per parent at level j."""
    m = _prod(counts)
    blocked = k is not None and k > 1

    def edf(rr):
        return t * rr - t - k + 1 if blocked else t * (rr - 1)

    def design(rr, cc):
        d = {"%s_per_level" % level_names[0]: rr}
        for name, c in zip(level_names[1:], cc):
            d["%s_per_parent" % name] = "unlimited" if c is INF else c
        return d

    unit = level_names[0]
    out = [Scenario("current", "current design", design(r, counts), _t2_coefs(r, counts),
                    "none", 0, edf(r))]
    out.append(Scenario("add_unit", "one more %s per treatment level" % unit,
                        design(r + 1, counts), _t2_coefs(r + 1, counts),
                        "%d %s (one per treatment level)" % (t, plural(unit)), t * m,
                        edf(r + 1), candidate=True, balanced=not blocked or (r + 1) % k == 0,
                        note=("this breaks the balanced crossing with the block unless r + 1 "
                              "is a multiple of the number of block levels"
                              if blocked and (r + 1) % k else "")))
    if blocked:
        out.append(Scenario("add_unit_balanced",
                            "%d more %s per treatment level (one per block level, the next "
                            "balanced crossing)" % (k, plural(unit)),
                            design(r + k, counts), _t2_coefs(r + k, counts),
                            "%d %s" % (t * k, plural(unit)), t * k * m, edf(r + k)))
    for j in range(1, len(counts) + 1):
        cc = list(counts)
        cc[j - 1] += 1
        parents = t * r * _prod(counts[:j - 1])
        name, parent = level_names[j], level_names[j - 1]
        out.append(Scenario("add_%s" % name, "one more %s per %s" % (name, parent),
                            design(r, cc), _t2_coefs(r, cc),
                            "%d %s (one per %s)" % (parents, plural(name), parent),
                            t * r * m // counts[j - 1], edf(r), candidate=True))
    floor = [INF] * len(counts)
    out.append(Scenario("floor", "the floor: unlimited %s" % " and ".join(
        plural(n) for n in level_names[1:]), design(r, floor), _t2_coefs(r, floor),
        "unlimited", 0, edf(r),
        note="2 sigma^2[%s] / r: the limit as every lower count grows" % unit))
    return out


def t3_scenarios(a: int, b: int, r: int, level_names: Sequence[str], factor: str):
    wp, sp = level_names
    if factor == "A":
        def coefs(rr, bb):
            return [Q(2, rr), Q(0) if bb is INF else Q(2, rr * bb)]

        def design(rr, bb):
            return {"%s_per_level" % wp: rr,
                    "%s_per_%s" % (sp, wp): "unlimited" if bb is INF else bb}

        return [
            Scenario("current", "current design", design(r, b), coefs(r, b), "none", 0,
                     a * (r - 1)),
            Scenario("add_unit", "one more %s per whole-plot level" % wp, design(r + 1, b),
                     coefs(r + 1, b), "%d %s" % (a, plural(wp)), a * b, a * r,
                     candidate=True),
            Scenario("add_%s" % sp, "one more %s reading per %s" % (sp, wp),
                     design(r, b + 1), coefs(r, b + 1), "%d readings" % (a * r), a * r,
                     a * (r - 1), candidate=True,
                     note="a new reading per whole plot is a new level of the subplot "
                          "factor, which changes the subplot factor itself; it is shown "
                          "only to make the floor visible (D-078)"),
            Scenario("floor", "the floor: unlimited %s readings per %s" % (sp, wp),
                     design(r, INF), coefs(r, INF), "unlimited", 0, a * (r - 1),
                     note="2 sigma^2[whole plot] / r"),
        ]
    mult = 2 if factor == "B" else 4
    denom = a if factor == "B" else 1

    def coefs_b(rr):
        return [Q(0), Q(mult, denom * rr)]

    def design_b(rr):
        return {"%s_per_level" % wp: rr}

    return [
        Scenario("current", "current design", design_b(r), coefs_b(r), "none", 0,
                 a * (r - 1) * (b - 1)),
        Scenario("add_unit", "one more %s per whole-plot level" % wp, design_b(r + 1),
                 coefs_b(r + 1), "%d %s" % (a, plural(wp)), a * b, a * r * (b - 1),
                 candidate=True,
                 note="the number of subplot levels does not enter this variance"),
    ]


# ---------------------------------------------------------------------------
# Assembling an allocation section
# ---------------------------------------------------------------------------

def _components_record(model: ComponentModel, comps, lam):
    rows = []
    est = [g for g in model.groups if g.estimable]
    for g, c in zip(model.groups, comps):
        rec = {"component": model.group_key(g), "label": model.group_label(g),
               "levels": [model.level_keys[i] for i in g.levels],
               "merged": len(g.levels) > 1, "df": g.df, "estimable": g.estimable}
        if g.estimable:
            rec.update(estimate=float(c), estimate_exact=str(c), ms=float(g.ms),
                       lambda_hat=float(lam[est.index(g)]))
        else:
            rec.update(estimate=None,
                       reason="the stratum has 0 degrees of freedom (one unit per "
                              "treatment level), so this component is not estimable")
        rows.append(rec)
    return rows


def allocate(model: ComponentModel, specs: Sequence[dict], unit_name: str,
             lower_names: Sequence[str]) -> dict:
    comps, lam = point_components(model)
    draws = plausible_components(model)
    comparisons = []
    for spec in specs:
        scen = spec["scenarios"]
        records = _evaluate(model, scen, comps, draws)
        ranking = _ranking(model, scen, records, draws, plural(unit_name))
        has_floor = any(sc.id == "floor" for sc in scen)
        rec = {"comparison_of": spec["comparison_of"], "factor": spec["factor"],
               "formula": spec["formula"], "scenarios": records, "ranking": ranking}
        rec.update(_conclusion(ranking, spec.get("unit_name", unit_name),
                               spec.get("lower_names", lower_names), has_floor))
        comparisons.append(rec)
    return {"status": "available", "basis": model.basis,
            "components": _components_record(model, comps, lam),
            "components_method": "closed-form REML (D-064); equal to the method-of-moments "
                                 "estimates whenever those are all >= 0 (D-078)",
            "plausible_values": {"method": "generalized pivotal quantities: lambda* = nu MS "
                                           "/ U, U ~ chi-square(nu), then the same pooling and "
                                           "inversion as the point estimate (Weerahandi "
                                           "1993; D-079)",
                                 "draws": N_DRAWS, "seed_text": SEED_TEXT, "seed": SEED,
                                 "percentiles": "2.5, 50, 97.5 (statistics.quantiles, n = 40, "
                                                "inclusive)",
                                 "label": "approximate; not validated in the WP6 grid"},
            "comparisons": comparisons,
            "not_implemented": "cost-weighted versions and cost-optimal subsample sizes "
                               "(optional in brief Section 5.5; D-078)"}


def _not(status, reason):
    return {"status": status, "reason": reason}


def t2_specs(t, r, counts, level_names, k, treatment):
    unit = level_names[0]
    names = level_names[1:]
    terms = ["sigma2[%s]" % unit]
    for l in range(1, len(level_names)):
        prod = " * ".join("n_%s" % n for n in names[:l])
        terms.append("sigma2[%s] / %s" % (level_names[l], prod if l == 1 else "(%s)" % prod))
    formula = "(2 / r) * (%s); r = %s per treatment level%s" % (
        " + ".join(terms), plural(unit), "".join(
            ", n_%s = %s per %s" % (level_names[l], plural(level_names[l]), level_names[l - 1])
            for l in range(1, len(level_names))))
    return [{"comparison_of": "the difference between two %s level means" % treatment,
             "factor": treatment, "formula": formula,
             "scenarios": t2_scenarios(t, r, counts, level_names, k)}]


def allocation_for_analysis(res, decl) -> dict:
    """D-078 for an analyzed design."""
    if res.template == "T1":
        return _not("not_applicable", "T1 has no treatment comparison, so there is no "
                                      "allocation analysis (brief Section 5.5 covers T2 and "
                                      "T3).")
    if res.template == "T2" and res.design.get("missing_site_exception"):
        return _not("withheld", "withheld for the missing-site exception: the allocation "
                                "decomposition needs balanced variance components, which "
                                "D-016 forbids for an unbalanced missing-site case (D-065, "
                                "D-078).")
    inner = res.internal
    model = model_from_analysis(inner)
    if res.template == "T2":
        names = inner["level_names"]
        specs = t2_specs(inner["t"], inner["r"], inner["counts"], names,
                         inner["k_observed"], res.design["treatment"])
        out = allocate(model, specs, names[0], names[1:])
        if inner["k_observed"]:
            out["block_note"] = ("With a block, sigma2[%s] is run-to-run variation within a "
                                 "block (D-063)." % names[0])
    else:
        names = inner["level_names"]
        a_name, b_name = res.labels["A"], res.labels["B"]
        factors = []
        for comp in decl.comparisons:
            if comp.kind == "interaction":
                factors.append("AB")
            elif comp.factors[0] == a_name:
                factors.append("A")
            else:
                factors.append("B")
        specs = []
        for f in ("A", "B", "AB"):
            if f not in factors:
                continue
            what = {"A": "the difference between two %s level means" % a_name,
                    "B": "the difference between two %s level means" % b_name,
                    "AB": "a 2 x 2 %s x %s interaction contrast" % (a_name, b_name)}[f]
            formula = {"A": "(2 / r) * (sigma2[whole plot] + sigma2[subplot] / b)",
                       "B": "2 * sigma2[subplot] / (a * r)",
                       "AB": "4 * sigma2[subplot] / r"}[f]
            specs.append({"comparison_of": what, "factor": {"A": a_name, "B": b_name,
                                                            "AB": "%s x %s" % (a_name, b_name)}[f],
                          "formula": formula,
                          "scenarios": t3_scenarios(inner["a"], inner["b"], inner["r"],
                                                    names, f),
                          "unit_name": names[0], "lower_names": ["%s reading" % names[1]]})
        out = allocate(model, specs, names[0], ["%s reading" % names[1]])
    reml_pooled = bool(res.reml.get("fit", {}).get("pooled"))
    out["current_vs_analysis"] = (
        "REML pooled strata (a boundary fit), so the allocation's current standard error, "
        "which uses the fitted components, differs from the comparison's reported standard "
        "error, which uses the error mean square directly." if reml_pooled else
        "REML pooled nothing, so the allocation's current standard error equals the "
        "comparison's reported standard error exactly (D-078).")
    return out


# ---------------------------------------------------------------------------
# The planning pathway on refused T2 designs (D-081)
# ---------------------------------------------------------------------------

PLANNING_CODES = {"insufficient_replication", "missing_top_unit", "complete_confounding"}


def _codes_ok(codes) -> Tuple[bool, str]:
    if not codes <= PLANNING_CODES:
        return False, ("refusal reasons %s are outside the planning pathway, which allows only "
                       "%s (D-081)" % (sorted(codes - PLANNING_CODES), sorted(PLANNING_CODES)))
    if "missing_top_unit" in codes and "insufficient_replication" not in codes:
        return False, ("units are missing without leaving fewer than two per level; the "
                       "planning pathway allows a missing unit only in the unreplicated case "
                       "(D-081)")
    return True, "the refusal reasons are within the planning pathway (D-081)"


def planning(ev, decl, data) -> dict:
    """D-081: decide whether planning quantities may be computed for a refused design, and
    return the evidence to plan from. `decl` is the parsed declaration (also available when
    WP1 refused it); `data` is the table or path, needed for a planning-only run."""
    from .evidence import planning_evidence
    out = {"eligible": False, "mode": None, "evidence": None, "planning_only_findings": []}
    if ev.decision != "REFUSE":
        out["reason"] = "the design was not refused"
        return out
    if decl is None or decl.claimed_template != "T2":
        out["reason"] = "the planning pathway covers T2 only (D-081)"
        return out
    codes = {f.code for f in ev.by_severity("refuse")}
    source, mode = ev, "evidence"
    if codes == {"declaration_refused"}:
        failed = set(ev.match.failed_conditions) if ev.match else set()
        if failed != {"T2.replicated"}:
            out["reason"] = ("the declaration was refused for reasons other than one unit per "
                             "treatment level, so its data were not checked (D-081)")
            return out
        source, mode = planning_evidence(decl, data), "planning_only_checks"
        out["planning_only_findings"] = [
            {"code": f.code, "severity": f.severity, "stage": f.stage, "message": f.message}
            for f in source.findings]
        codes = {f.code for f in source.by_severity("refuse")}
    ok, reason = _codes_ok(codes)
    if not ok:
        out["reason"] = reason
        return out
    ok, why = balanced_structure(source, decl)
    if not ok:
        out["reason"] = "the present data are not balanced: %s (D-081)" % why
        return out
    out.update(eligible=True, mode=mode, evidence=source, codes=sorted(codes), reason=reason)
    return out


def balanced_structure(ev, decl) -> Tuple[bool, str]:
    ctx = ev.context
    if ctx is None:
        return False, "the evidence checks stopped before the data structure was established"
    if any(f.code == "missing_sites_exception" for f in ev.findings):
        return False, "sites are missing, so the data below the units are not balanced"
    if any(f.severity == "refuse" and f.code not in PLANNING_CODES for f in ev.findings):
        return False, "the planning-only checks found other refusal reasons"
    st = structure_from_context(ctx)
    if not st.balanced():
        return False, "units at some level have unequal numbers of children"
    t = decl.treatments[0]
    trt_of = _value_of(ctx, 0, t.column)
    per = {}
    for u in st.units[0]:
        per[trt_of[u]] = per.get(trt_of[u], 0) + 1
    if len(set(per.values())) != 1 or len(per) < 2:
        return False, "present units per treatment level are not equal"
    return True, "balanced"


def planning_model(ctx, decl, factor=None) -> Tuple[ComponentModel, dict]:
    """The unit stratum within treatment (or within treatment x factor cells, D-080) and the
    ordinary nested strata below it."""
    st = structure_from_context(ctx)
    t = decl.treatments[0]
    units = st.units[0]
    trt_of = _value_of(ctx, 0, t.column)
    if factor is not None:
        fac_of = _value_of(ctx, 0, factor.column)
        cell_of = {u: (trt_of[u], fac_of[u]) for u in units}
    else:
        cell_of = dict(trt_of)
    m = st.m(0)
    cmean = _group_means(units, st.means[0], cell_of)
    ss_u = m * sum((_sq(st.means[0][u] - cmean[cell_of[u]]) for u in units), Q(0))
    df_u = len(units) - len(cmean)
    lower = nested_strata(st)[1:]
    keys = ["unit"] + ["sub%d" % i for i in range(1, st.depth)]
    unit_pl = plural(st.level_names[0])
    label_u = ("%s within treatment x %s cells" % (unit_pl, factor.name) if factor is not None
               else "%s within treatment" % unit_pl)
    labels = [label_u] + [s.label for s in lower]
    strata = [(m, df_u, ss_u)] + [(s.m, s.df, s.ss) for s in lower]
    model = model_from_strata(keys, labels, strata,
                              "planning quantities from the strata that do not involve the "
                              "refused comparison (D-081)")
    per = {}
    for u in units:
        per[trt_of[u]] = per.get(trt_of[u], 0) + 1
    info = {"t": len(per), "r": min(per.values()), "m": m,
            "counts": [len(st.units[l]) // len(st.units[l - 1]) for l in range(1, st.depth)],
            "level_names": list(st.level_names), "unit_df": df_u,
            "unit_ms": None if df_u == 0 else ss_u / df_u, "n_cells": len(cmean),
            "n_units": len(units)}
    return model, info


def allocation_for_planning(plan: dict, decl) -> dict:
    """D-078 on a refused T2 design that passed the D-081 gate."""
    codes = set(plan["codes"])
    if "complete_confounding" in codes:
        return _not("not_applicable", "the comparison is not estimable (complete "
                                      "confounding), so no allocation of it exists; the "
                                      "reassignment suggestion gives the precision of a "
                                      "design that removes the confounding (D-078, D-080).")
    model, info = planning_model(plan["evidence"].context, decl)
    names = info["level_names"]
    specs = t2_specs(info["t"], info["r"], info["counts"], names, None,
                     decl.treatments[0].name)
    out = allocate(model, specs, names[0], names[1:])
    out["status"] = "planning"
    out["planning_label"] = ("planning quantities, not results: the design was refused, and "
                             "no estimate, test or interval of the comparison is produced "
                             "(D-081)")
    out["unit_stratum_df"] = info["unit_df"]
    if info["unit_df"] == 0:
        out["unit_note"] = ("With %d %s per treatment level there is no variation among %s "
                            "treated alike, so sigma2[%s] is not estimable: every standard "
                            "error below is a lower bound, and the floor is not estimable. "
                            "With 2 %s per level it becomes estimable."
                            % (info["r"], plural(names[0]) if info["r"] != 1 else names[0],
                               plural(names[0]), names[0], plural(names[0])))
    return out
