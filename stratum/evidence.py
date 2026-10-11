"""WP2 evidence checks: can these data support the declared comparison?

`check_evidence(declaration, data)` takes a WP1 declaration and a data table and
returns an EvidenceResult with a decision (ANALYZE, WARN or REFUSE), every finding
with its reason, and the structured evidence behind it. It never reads the WP2
preregistration registry. It estimates nothing: there are no ANOVA tables,
variance components or effect estimates here (those are WP3).

Stages (DECISIONS.md D-048; each reports every finding it makes):
  S0  the declaration matches its claimed template (WP1)          stop on refusal
  S1  every declared column is present                            stop on refusal
  S2  labels present; responses missing or finite decimals        stop on refusal
  S3  unit identity: one parent per unit, no duplicate rows       stop on refusal
  S4  declared levels; constancy within units; T3 subplot layout  stop on refusal
  S5  balance, replication and missing data, from the data (D-043, D-047)
  S6  confounding by exact estimability (D-045)
  S7  aliasing by partition equivalence (D-046)
  S8  diagnostics (D-044), only if S0-S7 found no refusal

Decision: REFUSE if any refusal finding, else WARN if any warning, else ANALYZE.
Notes never change the decision; diagnostics never turn a refusal into ANALYZE.
"""
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from . import stats
from .data import Table, is_missing, parse_response, read_table
from .declaration import Declaration
from .exact import Design, cramers_v_squared, gram, proportional, quad
from .templates import MatchResult, evaluate, match

Q = Fraction
REFUSE, WARN, NOTE = "refuse", "warn", "note"

# The frozen vocabulary (D-048): code -> (severity, stage).
CODES = {
    "declaration_refused": (REFUSE, "S0"),
    "missing_column": (REFUSE, "S1"),
    "missing_label": (REFUSE, "S2"),
    "invalid_response": (REFUSE, "S2"),
    "multiple_parents": (REFUSE, "S3"),
    "duplicate_observation": (REFUSE, "S3"),
    "undeclared_level": (REFUSE, "S4"),
    "treatment_not_constant": (REFUSE, "S4"),
    "nuisance_not_constant": (REFUSE, "S4"),
    "subplot_structure": (REFUSE, "S4"),
    "count_exceeds_declaration": (REFUSE, "S5"),
    "missing_top_unit": (REFUSE, "S5"),
    "missing_intermediate_unit": (REFUSE, "S5"),
    "missing_observation": (REFUSE, "S5"),
    "missing_sites_not_exchangeable": (REFUSE, "S5"),
    "missing_subplot_cell": (REFUSE, "S5"),
    "subplot_level_absent_everywhere": (REFUSE, "S5"),
    "positional_labels_inconsistent": (REFUSE, "S5"),
    "insufficient_replication": (REFUSE, "S5"),
    "unbalanced_units": (REFUSE, "S5"),
    "block_imbalance": (REFUSE, "S5"),
    "complete_confounding": (REFUSE, "S6"),
    "partial_confounding": (REFUSE, "S6"),
    "aliased_components_required": (REFUSE, "S7"),
    "missing_sites_exception": (WARN, "S5"),
    "aliased_components": (WARN, "S7"),
    "nuisance_unit_unique": (WARN, "S6"),       # added post-freeze by D-053
    "brown_forsythe": (WARN, "S8"),
    "sd_ratio": (WARN, "S8"),
    "studentized_residual": (WARN, "S8"),
    "aliased_partition": (NOTE, "S7"),
    "diagnostic_unavailable": (NOTE, "S8"),
}

STAGES = (
    ("S0", "declaration matches the claimed template"),
    ("S1", "declared columns present"),
    ("S2", "labels and response values"),
    ("S3", "unit identity and ownership"),
    ("S4", "declaration-data consistency"),
    ("S5", "balance, replication and missing data"),
    ("S6", "confounding"),
    ("S7", "aliasing"),
    ("S8", "diagnostics"),
)
LME4 = "Designs outside v1 can be fitted in lme4 or lmerTest; Stratum does not analyze them."


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    details: dict = field(default_factory=dict, compare=False)

    def __post_init__(self):
        if self.code not in CODES:
            raise ValueError("unknown evidence code %r" % self.code)

    @property
    def severity(self) -> str:
        return CODES[self.code][0]

    @property
    def stage(self) -> str:
        return CODES[self.code][1]


@dataclass(frozen=True)
class StageOutcome:
    id: str
    title: str
    status: str                    # pass, fail, warn, not_evaluated
    reason: Optional[str] = None   # why a stage was not evaluated


@dataclass
class EvidenceResult:
    claimed_template: Optional[str]
    decision: str
    findings: Tuple[Finding, ...]
    stages: Tuple[StageOutcome, ...]
    evidence: dict
    match: Optional[MatchResult] = None
    # The parsed structure the stages ran on (unit identities, exact response values,
    # present units and children). WP3's analysis reads it so there is one source of
    # truth for the design the data actually contain. It is not part of to_dict().
    context: Optional[object] = None

    @property
    def categories(self) -> Tuple[str, ...]:
        return tuple(sorted({f.code for f in self.findings}))

    def by_severity(self, severity) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == severity)

    def to_dict(self) -> dict:
        return _jsonable({
            "claimed_template": self.claimed_template,
            "decision": self.decision,
            "categories": list(self.categories),
            "findings": [{"code": f.code, "severity": f.severity, "stage": f.stage,
                          "message": f.message, "details": f.details} for f in self.findings],
            "stages": [{"id": s.id, "title": s.title, "status": s.status, "reason": s.reason}
                       for s in self.stages],
            "evidence": self.evidence,
        })

    def explain(self) -> str:
        head = {"ANALYZE": "ANALYZE: the data support the declared comparison structurally.",
                "WARN": "WARN: analyzable, with the warnings below.",
                "REFUSE": "REFUSE: the data cannot support the declared comparison."}
        lines = ["%s (claimed %s)" % (head[self.decision], self.claimed_template or "?")]
        for sev, title in ((REFUSE, "Refusals"), (WARN, "Warnings"), (NOTE, "Notes")):
            items = self.by_severity(sev)
            if items:
                lines.append("%s:" % title)
                lines += ["  [%s] %s" % (f.code, f.message) for f in items]
        lines.append("Stages:")
        for s in self.stages:
            lines.append("  %s %-13s %s%s" % (s.id, s.status, s.title,
                                              " (%s)" % s.reason if s.reason else ""))
        return "\n".join(lines)


def _jsonable(obj):
    if isinstance(obj, Fraction):
        return {"exact": str(obj), "value": float(obj)}
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = [_jsonable(v) for v in obj]
        return sorted(items, key=repr) if isinstance(obj, (set, frozenset)) else items
    if isinstance(obj, float) and obj != obj:
        return None
    if isinstance(obj, float) and obj in (float("inf"), float("-inf")):
        return "infinite" if obj > 0 else "-infinite"
    return obj


def _show(unit: Tuple[str, ...]) -> str:
    return "/".join(unit)


def _few(items, n=6):
    items = list(items)
    text = ", ".join(str(i) for i in items[:n])
    return text + (", ... (%d in all)" % len(items) if len(items) > n else "")


# ---------------------------------------------------------------------------
# The context shared by the stages
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, decl: Declaration, table: Table):
        self.decl = decl
        self.table = table
        self.findings: List[Finding] = []
        self.evidence: dict = {}
        self.depth = len(decl.hierarchy)

    def add(self, code, message, **details):
        self.findings.append(Finding(code, message, details))

    def refused(self) -> bool:
        return any(f.severity == REFUSE for f in self.findings)

    def identities(self, row) -> List[Tuple[str, ...]]:
        """Unit identity at each level: the label alone at the top and at id_scope
        global levels; the parent's identity plus the label at id_scope parent levels."""
        ids = []
        for i, lv in enumerate(self.decl.hierarchy):
            label = row[lv.id_column]
            ids.append((label,) if i == 0 or lv.id_scope == "global" else ids[i - 1] + (label,))
        return ids


# ---------------------------------------------------------------------------
# S1 - S4
# ---------------------------------------------------------------------------

def _s1_columns(ctx: _Ctx):
    d = ctx.decl
    wanted = [("response", d.response.column)]
    wanted += [("ID of level %r" % lv.name, lv.id_column) for lv in d.hierarchy]
    wanted += [("treatment %r" % t.name, t.column) for t in d.treatments]
    wanted += [("nuisance factor %r" % f.name, f.column) for f in d.nuisance_factors]
    have = set(ctx.table.columns)
    for role, col in wanted:
        if col not in have:
            ctx.add("missing_column",
                    "Column %r (%s) is declared but absent from the data, so that part of the "
                    "design cannot be checked." % (col, role), column=col, role=role)


def _label_columns(decl: Declaration):
    cols = [lv.id_column for lv in decl.hierarchy]
    cols += [t.column for t in decl.treatments]
    cols += [f.column for f in decl.nuisance_factors]
    return list(dict.fromkeys(cols))


def _s2_cells(ctx: _Ctx):
    d = ctx.decl
    blanks: Dict[str, List[int]] = {}
    bad: List[Tuple[int, str]] = []
    values: List[Optional[Fraction]] = []
    for i, row in enumerate(ctx.table.rows, start=2):        # line 1 is the header
        for col in _label_columns(d):
            if is_missing(row[col]):
                blanks.setdefault(col, []).append(i)
        cell = row[d.response.column]
        if is_missing(cell):
            values.append(None)
        else:
            v = parse_response(cell)
            if v is None:
                bad.append((i, cell))
            values.append(v)
    for col, lines in blanks.items():
        ctx.add("missing_label",
                "Column %r is empty or NA on CSV line(s) %s. Those rows cannot be placed in "
                "the design, and Stratum does not guess their labels." % (col, _few(lines)),
                column=col, lines=lines)
    if bad:
        ctx.add("invalid_response",
                "Response %r is not a number on CSV line(s) %s (e.g. %r). Only an empty cell "
                "or NA means missing; anything else must be a finite decimal number."
                % (d.response.column, _few(i for i, _ in bad), bad[0][1]),
                lines=[i for i, _ in bad], values=[v for _, v in bad][:10])
    ctx.values = values


def _s3_identity(ctx: _Ctx):
    d = ctx.decl
    ctx.ids = [ctx.identities(r) for r in ctx.table.rows]
    for lvl in range(1, ctx.depth):
        lv = d.hierarchy[lvl]
        if lv.id_scope != "global":
            continue
        parents: Dict[str, set] = {}
        for ids in ctx.ids:
            parents.setdefault(ids[lvl][0], set()).add(ids[lvl - 1])
        shared = {lab: ps for lab, ps in parents.items() if len(ps) > 1}
        for lab, ps in sorted(shared.items()):
            ctx.add("multiple_parents",
                    "%s %r (id_scope global) occurs under %d different %s units: %s. Each unit "
                    "must belong to exactly one parent." % (lv.name, lab, len(ps),
                                                            d.hierarchy[lvl - 1].name,
                                                            _few(sorted(_show(p) for p in ps))),
                    level=lv.name, label=lab, parents=sorted(_show(p) for p in ps))
    seen: Dict[Tuple[str, ...], List[int]] = {}
    for i, row in enumerate(ctx.table.rows, start=2):
        seen.setdefault(tuple(row[c] for c in d.id_columns), []).append(i)
    for key, lines in sorted(seen.items()):
        if len(lines) > 1:
            ctx.add("duplicate_observation",
                    "Rows on CSV lines %s carry the same identity %s (%s). Stratum does not "
                    "average or drop either one." % (_few(lines), "/".join(key),
                                                     " > ".join(d.id_columns)),
                    identity=list(key), lines=lines)


def _unit_values(ctx: _Ctx, level_index: int, column: str) -> Dict[Tuple[str, ...], set]:
    out: Dict[Tuple[str, ...], set] = {}
    for ids, row in zip(ctx.ids, ctx.table.rows):
        out.setdefault(ids[level_index], set()).add(row[column])
    return out


def _s4_consistency(ctx: _Ctx):
    d = ctx.decl
    for t in d.treatments:
        observed = {row[t.column] for row in ctx.table.rows}
        extra = sorted(observed - set(t.levels))
        if extra:
            ctx.add("undeclared_level",
                    "Treatment %r has value(s) %s in the data that are not declared levels %s."
                    % (t.name, extra, list(t.levels)), factor=t.name, values=extra)
    for f in d.nuisance_factors:
        if f.levels is None:
            continue
        extra = sorted({row[f.column] for row in ctx.table.rows} - set(f.levels))
        if extra:
            ctx.add("undeclared_level",
                    "Nuisance factor %r has value(s) %s that are not declared levels %s."
                    % (f.name, extra, list(f.levels)), factor=f.name, values=extra)
    for t in d.treatments:
        li = d.level_index(t.applied_to)
        varying = {u: v for u, v in _unit_values(ctx, li, t.column).items() if len(v) > 1}
        if varying:
            ctx.add("treatment_not_constant",
                    "Treatment %r was declared applied to whole %r units, but it takes more "
                    "than one value inside %d of them: %s. The treatment of such a unit is "
                    "undefined." % (t.name, t.applied_to, len(varying),
                                    _few("%s %s" % (_show(u), sorted(v))
                                         for u, v in sorted(varying.items()))),
                    factor=t.name, level=t.applied_to,
                    units={_show(u): sorted(v) for u, v in varying.items()})
    for f in d.nuisance_factors:
        li = d.level_index(f.recorded_at)
        varying = {u: v for u, v in _unit_values(ctx, li, f.column).items() if len(v) > 1}
        if varying:
            ctx.add("nuisance_not_constant",
                    "Nuisance factor %r was declared constant within %r units, but varies "
                    "inside %d of them: %s." % (f.name, f.recorded_at, len(varying),
                                                _few("%s %s" % (_show(u), sorted(v))
                                                     for u, v in sorted(varying.items()))),
                    factor=f.name, level=f.recorded_at,
                    units={_show(u): sorted(v) for u, v in varying.items()})
    if d.claimed_template == "T3":
        b = d.treatment(d.split_plot.subplot_factor)
        per_plot: Dict[Tuple[str, ...], Dict[str, int]] = {}
        for ids, row in zip(ctx.ids, ctx.table.rows):
            counts = per_plot.setdefault(ids[0], {})
            counts[row[b.column]] = counts.get(row[b.column], 0) + 1
        bad = {u: {lv: n for lv, n in c.items() if n > 1} for u, c in per_plot.items()}
        bad = {u: c for u, c in bad.items() if c}
        if bad:
            ctx.add("subplot_structure",
                    "Subplot factor %r should take each level once in every whole plot, but "
                    "repeats levels in %d whole plot(s): %s. The split-plot structure "
                    "declared is not present in the data." % (
                        b.name, len(bad), _few("%s %s" % (_show(u), c)
                                               for u, c in sorted(bad.items()))),
                    factor=b.name, whole_plots={_show(u): c for u, c in bad.items()})


# ---------------------------------------------------------------------------
# S5: balance, replication and missing data from the data
# ---------------------------------------------------------------------------

def _structure(ctx: _Ctx):
    """Present units (at least one observed response below them) and their children."""
    obs = [i for i, v in enumerate(ctx.values) if v is not None]
    ctx.obs = obs
    present = [set() for _ in range(ctx.depth)]
    children = [dict() for _ in range(ctx.depth)]
    for i in obs:
        ids = ctx.ids[i]
        for lvl in range(ctx.depth):
            present[lvl].add(ids[lvl])
            if lvl:
                children[lvl].setdefault(ids[lvl - 1], set()).add(ids[lvl])
    ctx.present, ctx.children = present, children
    order = []                                   # top units in first-appearance order
    for i in obs:
        if ctx.ids[i][0] not in order:
            order.append(ctx.ids[i][0])
    ctx.top_order = order


def _first_value(ctx: _Ctx, level_index: int, column: str) -> Dict[Tuple[str, ...], str]:
    out = {}
    for i in ctx.obs:
        out.setdefault(ctx.ids[i][level_index], ctx.table.rows[i][column])
    return out


def _s5_structure(ctx: _Ctx):
    d = ctx.decl
    _structure(ctx)
    n_rows, n_obs = len(ctx.table.rows), len(ctx.obs)
    ev = {"rows": n_rows, "observed_responses": n_obs, "missing_responses": n_rows - n_obs,
          "levels": []}
    ctx.evidence["structure"] = ev

    top = d.top
    n_top = len(ctx.present[0])
    ev["levels"].append({"level": top.name, "declared_total": top.count, "present": n_top})
    top_missing = n_top < top.count
    excess, short_mid, short_low = [], [], []
    if n_top > top.count:
        excess.append("%d %r units present, %d declared" % (n_top, top.name, top.count))
    if top_missing:
        ctx.add("missing_top_unit",
                "%d of %d declared %r units have data. A whole %s is missing, which v1 "
                "refuses rather than analyzing an unbalanced design. %s"
                % (n_top, top.count, top.name, top.name, LME4),
                level=top.name, declared=top.count, present=n_top)
    for lvl in range(1, ctx.depth):
        lv = d.hierarchy[lvl]
        counts = {p: len(ctx.children[lvl].get(p, ())) for p in ctx.present[lvl - 1]}
        ev["levels"].append({"level": lv.name, "declared_per_parent": lv.count,
                             "present_per_parent": sorted(set(counts.values()))})
        for p, c in sorted(counts.items()):
            if c > lv.count:
                excess.append("%s has %d %r units, %d declared" % (_show(p), c, lv.name, lv.count))
            elif c < lv.count:
                (short_low if lvl == ctx.depth - 1 else short_mid).append((p, c))
    if excess:
        ctx.add("count_exceeds_declaration",
                "The data have more units than the declaration states: %s. Declared counts "
                "are what the data are checked against; Stratum never rewrites them from the "
                "data." % _few(excess, 4), details=excess)
    if short_mid:
        mid = d.hierarchy[1]
        ctx.add("missing_intermediate_unit",
                "%d %r unit(s) have fewer %r units than declared (%d): %s. A wholly missing "
                "%s is unit-level imbalance; the missing-site exception does not cover it "
                "(D-016). %s" % (len(short_mid), top.name, mid.name, mid.count,
                                 _few("%s has %d" % (_show(p), c) for p, c in short_mid),
                                 mid.name, LME4),
                level=mid.name, units={_show(p): c for p, c in short_mid})

    template = d.claimed_template
    if short_low:
        _missing_lowest(ctx, short_low, bool(top_missing or short_mid or excess))
    if template in ("T1", "T2"):
        _label_balance(ctx)
    if template in ("T2", "T3"):
        _replication(ctx)
    if template == "T2" and d.blocks:
        _block_balance(ctx)


def _missing_lowest(ctx: _Ctx, short, higher_problem: bool):
    d = ctx.decl
    low = d.bottom
    parent = d.hierarchy[-2]
    template = d.claimed_template
    lost = sum(low.count - c for _, c in short)
    where = _few("%s has %d of %d" % (_show(p), c, low.count) for p, c in short)
    if template == "T1":
        ctx.add("missing_observation",
                "%d %r unit(s) have fewer %r observations than declared: %s. T1 needs the "
                "balanced design; v1 refuses missing observations rather than approximating. "
                "If the same %s labels are absent everywhere by design, declare that reduced "
                "design (D-016, D-043)." % (len(short), parent.name, low.name, where, low.name),
                parents={_show(p): c for p, c in short}, declared=low.count)
    elif template == "T2":
        if not low.exchangeable:
            how = "declared exchangeable: false" if low.exchangeable_declared else \
                "not declared exchangeable (the default is false)"
            ctx.add("missing_sites_not_exchangeable",
                    "%d %r observation(s) are missing (%s). The %r level is %s, so the "
                    "missing-site exception does not apply: missing fixed positions change "
                    "which positions a unit mean averages, not only its precision (D-022, "
                    "D-028). If the sites really are interchangeable random subsamples, the "
                    "declaration can say so." % (lost, low.name, where, low.name, how),
                    parents={_show(p): c for p, c in short}, declared=low.count,
                    exchangeable_declared=low.exchangeable_declared)
        elif higher_problem:
            ctx.evidence["missing_sites"] = {
                "lost": lost, "exception_applies": False,
                "reason": "a higher-level unit is missing or exceeds its declared count; the "
                          "exception needs every experimental and intermediate unit (D-016)"}
        else:
            _site_exception(ctx, short, lost)
    elif template == "T3":
        b = d.treatment(d.split_plot.subplot_factor)
        observed: Dict[Tuple[str, ...], set] = {}
        for i in ctx.obs:
            observed.setdefault(ctx.ids[i][0], set()).add(ctx.table.rows[i][b.column])
        missing = {u: frozenset(set(b.levels) - s) for u, s in observed.items()}
        sets = set(missing.values())
        if len(sets) == 1 and next(iter(sets)):
            gone = sorted(next(iter(sets)), key=list(b.levels).index)
            left = [lv for lv in b.levels if lv not in gone]
            more = ("A design with one subplot level is not a split-plot: B and A x B are "
                    "not estimable, and it is not reclassified as another template (D-021)."
                    if len(left) < 2 else
                    "If those levels were never run, declare the reduced T3 with levels %s "
                    "(D-016, D-043)." % left)
            ctx.add("subplot_level_absent_everywhere",
                    "Declared %r level(s) %s are absent from every whole plot; the declaration "
                    "lists them. %s" % (b.name, gone, more),
                    factor=b.name, absent=gone, remaining=left)
        else:
            cells = {_show(u): sorted(m, key=list(b.levels).index)
                     for u, m in missing.items() if m}
            ctx.add("missing_subplot_cell",
                    "%d whole plot(s) lack subplot cells: %s. In T3 each missing cell removes "
                    "part of the B and A x B comparisons; v1 refuses sporadic missing cells "
                    "(D-016). %s" % (len(cells), _few("%s lacks %s" % (u, m)
                                                      for u, m in sorted(cells.items())), LME4),
                    factor=b.name, missing=cells)


def _site_exception(ctx: _Ctx, short, lost):
    """D-016 / D-021: per experimental unit, the surviving site counts and F_site."""
    d = ctx.decl
    m0 = d.bottom.count
    units = {}
    for top in ctx.top_order:
        if ctx.depth == 3:
            wafers = sorted(ctx.children[1].get(top, ()))
            counts = [len(ctx.children[2].get(w, ())) for w in wafers]
        else:
            counts = [len(ctx.children[1].get(top, ()))]
        w = len(counts)
        f_site = Q(m0, w) * sum((Q(1, m) for m in counts), Q(0))
        units[_show(top)] = {"site_counts": counts, "F_site": f_site,
                             "precision_lower_bound": 1 / f_site}
    ctx.evidence["missing_sites"] = {
        "lost": lost, "exception_applies": True, "declared_per_wafer": m0, "units": units,
        "label": "1/F_site: count-only lower bound on this unit mean's precision relative to "
                 "the balanced design. Not an estimated total precision loss, and not a "
                 "substitute for variance-component inference (D-021)."}
    equal = len({u["F_site"] for u in units.values()}) == 1
    ctx.add("missing_sites_exception",
            "%d exchangeable %r observation(s) are missing (%s); every experimental unit and "
            "intermediate unit is present, so the narrow missing-site exception applies "
            "(D-016). The treatment comparison will use hierarchical unit means and is "
            "approximate rather than the exact balanced test: %s Variance components and the "
            "allocation analysis are not computed for this case."
            % (lost, d.bottom.name,
               _few("%s has %d of %d" % (_show(p), c, m0) for p, c in short),
               "every unit lost the same number, so the unit means share one F_site (%s)."
               % next(iter(units.values()))["F_site"] if equal else
               "unequal site counts give the unit means unequal precision."),
            lost=lost, equal_counts=equal)


def _label_balance(ctx: _Ctx):
    """D-043 reading 3: label balance for nonexchangeable parent-scoped levels."""
    d = ctx.decl
    for lvl in range(1, ctx.depth):
        lv = d.hierarchy[lvl]
        if lv.id_scope != "parent" or lv.exchangeable:
            continue
        kids = {p: ctx.children[lvl].get(p, set()) for p in ctx.present[lvl - 1]}
        if any(len(k) != lv.count for k in kids.values()):
            continue                      # counts are handled by the missing/excess checks
        sets = {frozenset(k[-1] for k in ks) for ks in kids.values()}
        if len(sets) > 1:
            shown = sorted(sorted(s) for s in sets)
            ctx.add("positional_labels_inconsistent",
                    "Level %r is not declared exchangeable, so its labels are fixed positions, "
                    "but different %r units carry different label sets (%d distinct, e.g. %s). "
                    "Matching counts are not enough when positions differ (D-022, D-043). If "
                    "the labels are arbitrary, declare exchangeable: true (or id_scope: global "
                    "for unit identifiers)." % (lv.name, d.hierarchy[lvl - 1].name, len(sets),
                                               _few(shown, 3)),
                    level=lv.name, label_sets=shown)


def _top_treatment(d: Declaration):
    if d.claimed_template == "T3":
        return d.treatment(d.split_plot.whole_plot_factor)
    return d.treatments[0]


def _replication(ctx: _Ctx):
    d = ctx.decl
    t = _top_treatment(d)
    value = _first_value(ctx, 0, t.column)
    r = {lv: sum(1 for u in ctx.present[0] if value[u] == lv) for lv in t.levels}
    ctx.evidence["replication"] = {"factor": t.name, "applied_to": t.applied_to,
                                   "declared_per_level": t.replicates_per_level,
                                   "present_per_level": r}
    if min(r.values()) < 2:
        low = {lv: n for lv, n in r.items() if n < 2}
        ctx.add("insufficient_replication",
                "%r was applied to %r units, and level(s) %s have fewer than 2 of them in the "
                "data. With r < 2 there is no variation among units treated alike, so the "
                "test has no error degrees of freedom. More %s cannot replace replicated %r "
                "units." % (t.name, t.applied_to, low,
                            " or ".join("%ss" % lv.name for lv in d.hierarchy[1:]) or "subunits",
                            t.applied_to), factor=t.name, present_per_level=r)
    if len(set(r.values())) > 1:
        ctx.add("unbalanced_units",
                "Present %r units per level of %r are %s, not equal. Unit-level imbalance is "
                "refused in v1 (brief Section 5.4). %s" % (t.applied_to, t.name, r, LME4),
                factor=t.name, present_per_level=r)


def _block_balance(ctx: _Ctx):
    d = ctx.decl
    t, b = d.treatments[0], d.blocks[0]
    tv = _first_value(ctx, 0, t.column)
    bv = _first_value(ctx, 0, b.column)
    table = [[sum(1 for u in ctx.present[0] if tv[u] == tl and bv[u] == bl)
              for bl in b.levels] for tl in t.levels]
    ctx.evidence["block_table"] = {"rows": list(t.levels), "columns": list(b.levels),
                                   "counts": table}
    if len({n for row in table for n in row}) > 1:
        ctx.add("block_imbalance",
                "Block %r was declared crossed with %r so that every block runs every level "
                "equally often, but the data give %s (rows %s, columns %s)."
                % (b.name, t.name, table, list(t.levels), list(b.levels)),
                factor=b.name, counts=table)


# ---------------------------------------------------------------------------
# S6: confounding (D-045)
# ---------------------------------------------------------------------------

def _partition(ctx: _Ctx, key) -> frozenset:
    groups: Dict[object, List[int]] = {}
    for i in ctx.obs:
        groups.setdefault(key(i), []).append(i)
    return frozenset(frozenset(g) for g in groups.values())


def _level_partition(ctx: _Ctx, lvl: int) -> frozenset:
    return _partition(ctx, lambda i: ctx.ids[i][lvl])


def _nuisance_partition(ctx: _Ctx, f) -> frozenset:
    return _partition(ctx, lambda i: ctx.table.rows[i][f.column])


def _confined(ctx: _Ctx, f, lvl: int) -> bool:
    """True when every observed level of nuisance factor f lies inside one unit at lvl."""
    home: Dict[str, Tuple[str, ...]] = {}
    for i in ctx.obs:
        unit = ctx.ids[i][lvl]
        if home.setdefault(ctx.table.rows[i][f.column], unit) != unit:
            return False
    return True


def _unit_unique(ctx: _Ctx, f) -> bool:
    """D-053: a recorded factor each of whose levels lies inside a single top-level unit
    (e.g. a different day for every run). Such labels only rename units."""
    return f.role == "recorded" and len(ctx.present[0]) >= 2 and _confined(ctx, f, 0)


def _s6_confounding(ctx: _Ctx):
    d = ctx.decl
    records = []
    ctx.evidence["confounding"] = records
    ctx.unit_unique = [f.name for f in d.nuisance_factors if _unit_unique(ctx, f)]
    if d.claimed_template == "T1":
        ctx.evidence["confounding_note"] = "T1 has no treatment: confounding is not applicable."
    else:
        for comp in d.comparisons:
            for f in d.nuisance_factors:
                records.append(_confounding_pair(ctx, comp, f))
    for name in ctx.unit_unique:
        trends = [r["linear_trend"] for r in records
                  if r["nuisance"] == name and "linear_trend" in r]
        shown = [tr for tr in trends if tr.get("available")]
        extra = ""
        if shown:
            ratios = [c["variance_ratio"] for tr in shown for c in tr["contrasts"]
                      if c["estimable"]]
            if ratios:
                extra = (" Read as an ordered number, a linear trend in %r leaves the comparison "
                         "estimable; adjusting for it would multiply the contrast variance by "
                         "up to %s (evidence only, no threshold)." % (name, max(ratios)))
        ctx.add("nuisance_unit_unique",
                "Each level of %r occurs within a single %r unit (for example, a different day "
                "for every run). As a categorical factor, its effect cannot be separated from "
                "%s-to-%s variation with this design: one fixed indicator per unit would "
                "saturate the unit-level data and make every comparison of units "
                "non-estimable mechanically, which is not evidence of confounding. It is "
                "therefore not adjusted for, and not reported as confounding or aliasing "
                "(D-053). A drift or order concern needs an informative representation: levels "
                "shared by several units (a period or block), or an ordered numeric variable.%s"
                % (name, d.top.name, d.top.name, d.top.name, extra),
                factor=name, level=d.top.name, linear_trend=trends)


def _contrast_specs(comp, eff_obs, a=None, b=None):
    """(name, {effect level: coefficient}) for each contrast of a comparison (D-045)."""
    specs = []
    if comp.kind == "pairwise":
        hi, lo = comp.levels
        if hi in eff_obs and lo in eff_obs:
            specs.append(("%s - %s" % (hi, lo), {hi: 1, lo: -1}))
    elif comp.kind == "overall":
        for e in eff_obs[1:]:
            specs.append(("%s - %s" % (e, eff_obs[0]), {e: 1, eff_obs[0]: -1}))
    else:
        al = [x for x in a.levels if any(e[0] == x for e in eff_obs)]
        bl = [y for y in b.levels if any(e[1] == y for e in eff_obs)]
        for x in al[1:]:
            for y in bl[1:]:
                cells = {(x, y): 1, (x, bl[0]): -1, (al[0], y): -1, (al[0], bl[0]): 1}
                if all(c in eff_obs for c in cells):
                    specs.append(("(%s,%s)-(%s,%s)-(%s,%s)+(%s,%s)"
                                  % (x, y, x, bl[0], al[0], y, al[0], bl[0]), cells))
    return specs


def _linear_trend(ctx: _Ctx, comp, f, lx, keyf, effects, a=None, b=None) -> dict:
    """D-053 B: a unit-unique factor whose labels are numbers is evaluated as an ordered
    variable: the comparison with a linear trend in it, by exact estimability, with the
    variance ratio against the comparison alone. Evidence only."""
    d = ctx.decl
    if d.level_index(f.recorded_at) > lx:
        return {"available": False,
                "reason": "%r varies within the %r units" % (f.name, d.hierarchy[lx].name)}
    units: Dict[Tuple[str, ...], Tuple[object, str]] = {}
    for i in ctx.obs:
        row = ctx.table.rows[i]
        units.setdefault(ctx.ids[i][lx], (keyf(row), row[f.column]))
    x = {v: parse_response(v) for _, v in units.values()}
    if any(val is None for val in x.values()):
        return {"available": False,
                "reason": "the levels of %r are not all numbers, so no order can be read "
                          "from them" % f.name}
    eff_obs = [e for e in effects if any(k == e for k, _ in units.values())]
    rows = [[Q(1)] + [Q(int(k == e)) for e in eff_obs] + [x[v]] for k, v in units.values()]
    g_full, g_trt = gram(rows), gram([r[:-1] for r in rows])
    out = []
    for name, coef in _contrast_specs(comp, eff_obs, a, b):
        c = [Q(0)] + [Q(coef.get(e, 0)) for e in eff_obs]
        q_full, q_trt = quad(g_full, c + [Q(0)]), quad(g_trt, c)
        item = {"contrast": name, "estimable": q_full is not None}
        if q_full is not None:
            item.update(variance_ratio=q_full / q_trt,
                        se_inflation=float(q_full / q_trt) ** 0.5)
        out.append(item)
    return {"available": True, "model": "1 + %s + linear in %s" % (comp.factors[0], f.name),
            "rows_are": d.hierarchy[lx].name, "contrasts": out}


def _confounding_pair(ctx: _Ctx, comp, f) -> dict:
    d = ctx.decl
    a = b = None
    if comp.kind == "interaction":
        a, b = d.treatment(comp.factors[0]), d.treatment(comp.factors[1])
        lx = max(d.level_index(a.applied_to), d.level_index(b.applied_to))
        keyf = lambda row: (row[a.column], row[b.column])        # noqa: E731
        effects = [(x, y) for x in a.levels for y in b.levels]
        effect_name = "%s x %s" % (a.name, b.name)
    else:
        t = d.treatment(comp.factors[0])
        lx = d.level_index(t.applied_to)
        keyf = lambda row: row[t.column]                         # noqa: E731
        effects = list(t.levels)
        effect_name = t.name
    lf = d.level_index(f.recorded_at)
    lr = max(lx, lf)
    rec = {"comparison": comp.id, "effect": effect_name, "nuisance": f.name,
           "rows_are": d.hierarchy[lr].name}

    # A recorded label unique to a whole plot and constant within it also cancels
    # from every within-plot B/AB contrast. Counting A-by-B cells against plot IDs
    # would invent an imbalance from the split-plot structure itself (D-096).
    wholeplot_label = d.claimed_template == "T3" and lf == 0
    if f.name in ctx.unit_unique and (_confined(ctx, f, lx) or wholeplot_label):
        label_level = 0 if wholeplot_label else lx
        rec.update(status="unit_unique",
                   reason="each level of %r lies inside one %r unit, so as a category it only "
                          "renames units and is not entered in the estimability matrix "
                          "(D-053)" % (f.name, d.hierarchy[label_level].name))
        trend = _linear_trend(ctx, comp, f, lx, keyf, effects, a, b)
        rec["linear_trend"] = trend
        bad = [c["contrast"] for c in trend.get("contrasts", ()) if not c["estimable"]]
        if bad:
            rec["status"] = "complete"
            ctx.add("complete_confounding",
                    "Comparison %r is not estimable once a linear trend in %r is included: %s "
                    "cannot be separated from the trend (exact rank; D-053 C)."
                    % (comp.id, f.name, ", ".join(bad)),
                    comparison=comp.id, nuisance=f.name, nonestimable=bad, model="linear trend")
        return rec

    units: Dict[Tuple[str, ...], Tuple[object, str]] = {}
    for i in ctx.obs:
        row = ctx.table.rows[i]
        units.setdefault(ctx.ids[i][lr], (keyf(row), row[f.column]))
    eff_obs = [e for e in effects if any(k == e for k, _ in units.values())]
    nuis_order = list(f.levels) if f.levels else sorted({v for _, v in units.values()})
    nuis_obs = [v for v in nuis_order if any(n == v for _, n in units.values())]
    ei = {e: j for j, e in enumerate(eff_obs)}
    ni = {v: j for j, v in enumerate(nuis_obs)}
    E, M = len(eff_obs), len(nuis_obs)
    rows_full = [(0, 1 + ei[k], 1 + E + ni[v]) for k, v in units.values()]
    rows_trt = [(0, 1 + ei[k]) for k, _ in units.values()]
    full, trt = Design(rows_full, 1 + E + M), Design(rows_trt, 1 + E)
    table = [[sum(1 for k, v in units.values() if k == e and v == n) for n in nuis_obs]
             for e in eff_obs]
    v2 = cramers_v_squared(table)
    rec.update(levels=[_label(e) for e in eff_obs], nuisance_levels=nuis_obs, table=table,
               n_rows=len(units), proportional=proportional(table),
               cramers_v=None if v2 is None else float(v2) ** 0.5,
               cramers_v_squared=v2)

    contrasts = _contrast_specs(comp, eff_obs, a, b)
    out, nonestimable = [], []
    for name, coef in contrasts:
        c_trt = [Q(0)] * (1 + E)
        for e, w in coef.items():
            c_trt[1 + ei[e]] = Q(w)
        c_full = c_trt + [Q(0)] * M
        q_full, q_trt = full.quad(c_full), trt.quad(c_trt)
        item = {"contrast": name, "estimable": q_full is not None}
        if q_full is None:
            nonestimable.append(name)
        else:
            ratio = q_full / q_trt
            item.update(variance_ratio=ratio, se_inflation=float(ratio) ** 0.5,
                        var_with_nuisance_over_sigma2=q_full, var_treatment_only_over_sigma2=q_trt)
        out.append(item)
    rec["contrasts"] = out
    if not contrasts:
        rec.update(status="not_evaluable",
                   reason="a compared level has no data; the structural checks report it")
        return rec
    if nonestimable:
        rec["status"] = "complete"
        ctx.add("complete_confounding",
                "Comparison %r is not estimable once %r is included: %s cannot be separated "
                "from %r differences (design-matrix rank; table %s). The data contain no "
                "%s comparison made within a level of %r. More measurements below the %r "
                "level cannot restore that missing independent information. A crossed, "
                "randomized assignment of %s levels to %s levels is needed."
                % (comp.id, f.name, ", ".join(nonestimable), f.name, table, effect_name,
                   f.name, d.hierarchy[lx].name, effect_name, f.name),
                comparison=comp.id, nuisance=f.name, table=table,
                nonestimable=nonestimable)
    elif not rec["proportional"]:
        rec["status"] = "partial"
        worst = max(out, key=lambda x: x["variance_ratio"])
        ctx.add("partial_confounding",
                "Comparison %r is estimable but %r is unevenly spread over its levels "
                "(table %s; Cramer's V = %s, descriptive). Including %r inflates the "
                "variance of %s by %s (standard error x %.4f). v1 refuses unbalanced "
                "experimental-unit designs, so this partially confounded design is refused. %s"
                % (comp.id, f.name, table, "%.4f" % rec["cramers_v"] if v2 is not None else "n/a",
                   f.name, worst["contrast"], worst["variance_ratio"], worst["se_inflation"],
                   LME4),
                comparison=comp.id, nuisance=f.name, table=table,
                cramers_v=rec["cramers_v"], variance_ratio=worst["variance_ratio"],
                se_inflation=worst["se_inflation"])
    else:
        rec["status"] = "none"
    return rec


def _label(e) -> str:
    return "(%s,%s)" % e if isinstance(e, tuple) else str(e)


# ---------------------------------------------------------------------------
# S7: aliasing (D-046)
# ---------------------------------------------------------------------------

def _s7_aliasing(ctx: _Ctx):
    d = ctx.decl
    template = d.claimed_template
    groupings = []        # (display name, component name or None, partition)
    for lvl, lv in enumerate(d.hierarchy):
        comp = "%r%s" % (lv.name, " (residual)" if lvl == ctx.depth - 1 else "")
        groupings.append(("level %r" % lv.name, comp, _level_partition(ctx, lvl)))
    excluded = []
    for f in d.nuisance_factors:
        if f.name in ctx.unit_unique:
            excluded.append(f.name)          # D-053: renames units; not a grouping step
            continue
        comp = "block %r" % f.name if template == "T2" and f.role == "block" else None
        groupings.append(("%s %r" % ("block" if f.role == "block" else "recorded factor",
                                     f.name), comp, _nuisance_partition(ctx, f)))
    pairs = []
    for i in range(len(groupings)):
        for j in range(i + 1, len(groupings)):
            (n1, c1, p1), (n2, c2, p2) = groupings[i], groupings[j]
            if p1 != p2:
                continue
            pairs.append([n1, n2])
            if c1 and c2 and template == "T1":
                ctx.add("aliased_components_required",
                        "%s and %s group the observations identically, so the %s and %s "
                        "variance components cannot be separated. Separate components are "
                        "exactly what T1 estimates, so this request cannot be met. Stratum "
                        "does not pretend to estimate two components from one partition."
                        % (n1, n2, c1, c2), pair=[n1, n2], unidentified=[c1, c2])
            elif c1 and c2:
                ctx.add("aliased_components",
                        "%s and %s group the observations identically, so the %s and %s "
                        "variance components cannot be separately estimated: only their "
                        "combined component is identifiable, and no separate estimate of "
                        "either is reported. Allocation outputs that need them separately are "
                        "unavailable or limited. The treatment comparison rests on replicated "
                        "independent %r units and does not need them separated (D-054)."
                        % (n1, n2, c1, c2, d.top.name),
                        pair=[n1, n2], unidentified=[c1, c2])
            else:
                ctx.add("aliased_partition",
                        "%s and %s group the observations identically (labels aside). Any "
                        "effect of one cannot be distinguished from the other." % (n1, n2),
                        pair=[n1, n2])
    ctx.evidence["aliasing"] = {"groupings": [n for n, _, _ in groupings], "aliased_pairs": pairs,
                                "excluded_unit_unique": excluded}


# ---------------------------------------------------------------------------
# S8: diagnostics (D-044)
# ---------------------------------------------------------------------------

def unit_means(ctx, level: int) -> Dict[Tuple[str, ...], Fraction]:
    """Hierarchical means: each unit's mean is the mean of its children's means."""
    means = {ctx.ids[i][-1]: ctx.values[i] for i in ctx.obs}
    for lvl in range(ctx.depth - 1, level, -1):
        means = {p: stats.mean([means[c] for c in sorted(ctx.children[lvl][p])])
                 for p in ctx.present[lvl - 1]}
    return means


def _diagnose(ctx: _Ctx, stratum, groups=None, labels=None, y=None, design=None,
              units=None, model=""):
    results = {}
    if groups is not None:
        results["brown_forsythe"] = stats.brown_forsythe(groups, labels)
        results["sd_ratio"] = stats.sd_ratio(groups, labels)
    else:
        results["brown_forsythe"] = {"available": False, "warn": False, "not_applicable": True,
                                     "reason": "no treatment groups in this stratum"}
        results["sd_ratio"] = dict(results["brown_forsythe"])
    results["studentized_residuals"] = stats.studentized(y, design, units, model)
    for name, res in results.items():
        if res.get("not_applicable"):
            continue
        if res["available"] and res.get("undefined_units"):
            ctx.add("diagnostic_unavailable",
                    "%s (%s): the externally studentized residual is undefined for %s (leverage "
                    "1 or zero deleted variance); no value was substituted."
                    % (name.replace("_", " "), stratum, _few(res["undefined_units"])),
                    diagnostic=name, stratum=stratum, units=res["undefined_units"])
        if not res["available"]:
            ctx.add("diagnostic_unavailable",
                    "%s (%s) could not be computed: %s. Nothing was substituted."
                    % (name.replace("_", " "), stratum, res["reason"]),
                    diagnostic=name, stratum=stratum)
        elif res["warn"]:
            if name == "brown_forsythe":
                ctx.add("brown_forsythe",
                        "%s: Brown-Forsythe F = %.4g on %s df, p = %.4g < 0.05. The spread of "
                        "unit means differs between treatment levels; the equal-variance "
                        "assumption is doubtful. Warning only." % (stratum, res["F"],
                                                                     res["df"], res["p"]),
                        stratum=stratum, F=res["F"], p=res["p"])
            elif name == "sd_ratio":
                ratio = res["ratio"]
                shown = ratio if isinstance(ratio, str) else "%.4g" % ratio
                ctx.add("sd_ratio",
                        "%s: largest-to-smallest SD of unit means = %s (warning at >= 2.0, a "
                        "pragmatic v1 threshold). Warning only." % (stratum, shown),
                        stratum=stratum, ratio=ratio, sds=res["sds"])
            else:
                flagged = [u["unit"] for u in res["units"] if u.get("flagged")]
                ctx.add("studentized_residual",
                        "%s: externally studentized residual beyond +-3 for %s (largest |t| = "
                        "%.4g). Possible outlier; check the record. Warning only."
                        % (stratum, _few(flagged), res["max_abs_external"]),
                        stratum=stratum, units=flagged, max_abs=res["max_abs_external"])
    return results


def _s8_diagnostics(ctx: _Ctx):
    d = ctx.decl
    template = d.claimed_template
    out = {}
    ctx.evidence["diagnostics"] = out
    top_means = unit_means(ctx, 0)
    units = ctx.top_order
    y = [top_means[u] for u in units]
    names = [_show(u) for u in units]
    if template == "T1":
        out["top_units"] = _diagnose(ctx, "%s means" % d.top.name, y=y,
                                     design=Design([(0,) for _ in units], 1), units=names,
                                     model="intercept only")
        return
    t = _top_treatment(d)
    tv = _first_value(ctx, 0, t.column)
    levels = [lv for lv in t.levels if any(tv[u] == lv for u in units)]
    groups = [[top_means[u] for u in units if tv[u] == lv] for lv in levels]
    col = {lv: 1 + j for j, lv in enumerate(levels)}
    rows = [[0, col[tv[u]]] for u in units]
    ncol, model = 1 + len(levels), "%s" % t.name
    if template == "T2" and d.blocks:
        b = d.blocks[0]
        bv = _first_value(ctx, 0, b.column)
        blv = [lv for lv in b.levels if any(bv[u] == lv for u in units)]
        for r, u in zip(rows, units):
            r.append(ncol + blv.index(bv[u]))
        ncol += len(blv)
        model += " + %s (additive; provisional until WP3, D-044)" % b.name
    stratum = "%s means" % d.top.name
    out[d.top.name] = _diagnose(ctx, stratum, groups, levels, y, Design(rows, ncol), names,
                                model)
    if template == "T3":
        b = d.treatment(d.split_plot.subplot_factor)
        a = t
        plots = {u: j for j, u in enumerate(units)}
        cells: Dict[Tuple[str, str], int] = {}
        srows, sy, slabels = [], [], []
        nb = len(b.levels)
        for i in ctx.obs:
            row = ctx.table.rows[i]
            cell = (row[a.column], row[b.column])
            cells.setdefault(cell, len(cells))
            srows.append((plots[ctx.ids[i][0]], len(units) + b.levels.index(row[b.column]),
                          len(units) + nb + cells[cell]))
            sy.append(ctx.values[i])
            slabels.append(_show(ctx.ids[i][-1]))
        out[d.bottom.name] = _diagnose(
            ctx, "%s residuals" % d.bottom.name, y=sy,
            design=Design(srows, len(units) + nb + len(cells)), units=slabels,
            model="%s + %s + %s x %s (subplot stratum)" % (d.top.name, b.name, a.name, b.name))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _decision(findings: Sequence[Finding]) -> str:
    severities = {f.severity for f in findings}
    if REFUSE in severities:
        return "REFUSE"
    if WARN in severities:
        return "WARN"
    return "ANALYZE"


def check_evidence(declaration: Union[Path, str, dict, Declaration],
                   data: Union[Path, str, Table]) -> EvidenceResult:
    """Run the WP2 evidence checks. declaration: a YAML path, YAML text, a loaded dict,
    or a parsed Declaration. data: a CSV path or a Table."""
    m = match(declaration) if isinstance(declaration, Declaration) else evaluate(declaration)
    stages: List[StageOutcome] = []
    titles = dict(STAGES)

    def skipped_from(start, reason):
        for sid, title in STAGES[int(start[1]):]:
            stages.append(StageOutcome(sid, title, "not_evaluated", reason))

    if not m.matched:
        f = Finding("declaration_refused",
                    "The declaration does not fit claimed template %s, so its data are not "
                    "checked. WP1 refusals: %s" % (m.claimed_template or "?", "; ".join(
                        "[%s] %s" % (r.condition or r.category, r.reason) for r in m.refusals)),
                    {"wp1_refusals": [{"category": r.category, "condition": r.condition,
                                       "declared": r.declared, "reason": r.reason,
                                       "remedy": r.remedy} for r in m.refusals]})
        stages.append(StageOutcome("S0", titles["S0"], "fail"))
        skipped_from("S1", "the declaration was refused at S0")
        return EvidenceResult(m.claimed_template, "REFUSE", (f,), tuple(stages), {}, m)

    stages.append(StageOutcome("S0", titles["S0"], "pass"))
    table = data if isinstance(data, Table) else read_table(Path(data))
    ctx = _Ctx(m.declaration, table)

    def run(sid, fn, stop=True):
        before = len(ctx.findings)
        fn(ctx)
        new = ctx.findings[before:]
        sev = {f.severity for f in new}
        status = "fail" if REFUSE in sev else "warn" if WARN in sev else "pass"
        stages.append(StageOutcome(sid, titles[sid], status))
        return not (stop and status == "fail")

    for sid, fn in (("S1", _s1_columns), ("S2", _s2_cells), ("S3", _s3_identity),
                    ("S4", _s4_consistency)):
        if not run(sid, fn):
            next_id = "S%d" % (int(sid[1]) + 1)
            skipped_from(next_id, "stage %s found a refusal that leaves the structure "
                                  "undefined" % sid)
            return EvidenceResult(m.claimed_template, _decision(ctx.findings),
                                  tuple(ctx.findings), tuple(stages), ctx.evidence, m)
    run("S5", _s5_structure, stop=False)
    run("S6", _s6_confounding, stop=False)
    run("S7", _s7_aliasing, stop=False)
    if ctx.refused():
        stages.append(StageOutcome("S8", titles["S8"], "not_evaluated",
                                   "a refusal was found; diagnostics are not computed for a "
                                   "structure that cannot be analyzed"))
    else:
        run("S8", _s8_diagnostics, stop=False)
    return EvidenceResult(m.claimed_template, _decision(ctx.findings), tuple(ctx.findings),
                          tuple(stages), ctx.evidence, m, ctx)


def planning_evidence(decl: Declaration, data: Union[Path, str, Table]) -> EvidenceResult:
    """D-081: run stages S1-S7 on a declaration that WP1 refused only because it declares
    one unit per treatment level (condition T2.replicated).

    The findings feed the WP4 planning pathway only. They never change the decision of the
    run, which stays REFUSE at S0; check_evidence() is not affected. S8 (diagnostics) is not
    run, because no analysis follows."""
    table = data if isinstance(data, Table) else read_table(Path(data))
    ctx = _Ctx(decl, table)
    titles = dict(STAGES)
    stages: List[StageOutcome] = [StageOutcome("S0", titles["S0"], "fail",
                                               "planning-only run: WP1 refused T2.replicated")]
    for sid, fn in (("S1", _s1_columns), ("S2", _s2_cells), ("S3", _s3_identity),
                    ("S4", _s4_consistency), ("S5", _s5_structure), ("S6", _s6_confounding),
                    ("S7", _s7_aliasing)):
        before = len(ctx.findings)
        fn(ctx)
        sev = {f.severity for f in ctx.findings[before:]}
        stages.append(StageOutcome(sid, titles[sid],
                                   "fail" if REFUSE in sev else "warn" if WARN in sev else "pass"))
        if sid in ("S1", "S2", "S3", "S4") and REFUSE in sev:
            return EvidenceResult(decl.claimed_template, "REFUSE", tuple(ctx.findings),
                                  tuple(stages), ctx.evidence, None, None)
    stages.append(StageOutcome("S8", titles["S8"], "not_evaluated",
                               "planning-only run: no analysis follows"))
    return EvidenceResult(decl.claimed_template, _decision(ctx.findings), tuple(ctx.findings),
                          tuple(stages), ctx.evidence, None, ctx)
