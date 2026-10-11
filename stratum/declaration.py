"""Declaration schema: parse a YAML design declaration and validate its structure.

The declaration describes the scientific design, not model syntax. The full shape,
with the meaning of every field, is documented in declarations/README.md. In short:

    stratum_declaration: 1
    claimed_template: T1 | T2 | T3
    description: <optional text>
    response:          {column, units}            # units may be null = not stated by the source
    hierarchy:         [top level, nested levels...]   # ordered, largest unit first
    treatments:        [...]                      # required; [] declares "no treatment"
    nuisance_factors:  [...]                      # required; [] declares "none recorded"
    comparisons:       [...]                      # required; [] for T1
    split_plot:        {whole_plot_factor, subplot_factor}   # T3 only

Validation here is template-independent: required fields, types, unknown fields,
duplicate keys, names that refer to undeclared things, and a hierarchy that is not
a single nesting chain. Whether the structure fits T1, T2 or T3 is decided in
stratum.templates. Every problem found is returned as a Refusal; nothing is
guessed, defaulted silently, or coerced, except the two documented defaults:
  - exchangeable: omitted -> False (not established as exchangeable; D-022, D-035)
  - id_scope:     omitted -> "parent" (labels identify a unit only within its parent; D-035)
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from .refusal import Refusal

SCHEMA_VERSION = 1
SUPPORTED_TEMPLATES = ("T1", "T2", "T3")
ASSIGNMENT_METHODS = ("randomized", "systematic", "inherent", "not_stated")
NUISANCE_ROLES = ("recorded", "block")
COMPARISON_KINDS = ("overall", "pairwise", "interaction")
ID_SCOPES = ("parent", "global")


# ---------------------------------------------------------------------------
# The parsed declaration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Response:
    column: str
    units: Optional[str]          # None: the source does not state units


@dataclass(frozen=True)
class Level:
    name: str
    id_column: str
    nested_in: Optional[str]      # None only for the top level
    count: int                    # top level: total units; nested level: units per parent
    id_scope: str                 # "global" for the top level; "parent" or "global" below
    exchangeable: Optional[bool]  # None for the top level; resolved True/False below it
    exchangeable_declared: bool   # False when the conservative default was applied

    @property
    def is_top(self) -> bool:
        return self.nested_in is None


@dataclass(frozen=True)
class Treatment:
    name: str
    column: str
    levels: Tuple[str, ...]
    applied_to: str               # a hierarchy level name: the experimental unit
    replicates_per_level: int     # number of applied_to units receiving each level, in total
    assignment_method: str
    assignment_description: Optional[str]


@dataclass(frozen=True)
class NuisanceFactor:
    name: str
    column: str
    recorded_at: str              # hierarchy level at which it is constant
    role: str                     # "recorded" or "block"
    levels: Optional[Tuple[str, ...]]
    crossed_with: Optional[str]   # block only: the treatment it is crossed with


@dataclass(frozen=True)
class Comparison:
    id: str
    kind: str
    factors: Tuple[str, ...]
    levels: Optional[Tuple[str, str]]   # pairwise only: (first, second), estimating first - second
    description: Optional[str]


@dataclass(frozen=True)
class SplitPlot:
    whole_plot_factor: str
    subplot_factor: str


@dataclass(frozen=True)
class Declaration:
    schema_version: int
    claimed_template: str         # as written; checked against SUPPORTED_TEMPLATES when matching
    description: Optional[str]
    response: Response
    hierarchy: Tuple[Level, ...]
    treatments: Tuple[Treatment, ...]
    nuisance_factors: Tuple[NuisanceFactor, ...]
    comparisons: Tuple[Comparison, ...]
    split_plot: Optional[SplitPlot]

    def level(self, name: str) -> Level:
        for lv in self.hierarchy:
            if lv.name == name:
                return lv
        raise KeyError(name)

    def level_index(self, name: str) -> int:
        return [lv.name for lv in self.hierarchy].index(name)

    def treatment(self, name: str) -> Treatment:
        for t in self.treatments:
            if t.name == name:
                return t
        raise KeyError(name)

    def total_units(self, level_name: str) -> int:
        """Number of units at a level in the declared balanced design."""
        n = 1
        for lv in self.hierarchy[: self.level_index(level_name) + 1]:
            n *= lv.count
        return n

    @property
    def top(self) -> Level:
        return self.hierarchy[0]

    @property
    def bottom(self) -> Level:
        return self.hierarchy[-1]

    @property
    def blocks(self) -> Tuple[NuisanceFactor, ...]:
        return tuple(f for f in self.nuisance_factors if f.role == "block")

    @property
    def id_columns(self) -> Tuple[str, ...]:
        return tuple(lv.id_column for lv in self.hierarchy)


@dataclass(frozen=True)
class ParseResult:
    declaration: Optional[Declaration]   # None whenever refusals is non-empty
    refusals: Tuple[Refusal, ...]

    @property
    def ok(self) -> bool:
        return not self.refusals


# ---------------------------------------------------------------------------
# YAML loading: safe loader that refuses duplicate keys instead of keeping the last
# ---------------------------------------------------------------------------

class _DuplicateKey(yaml.constructor.ConstructorError):
    pass


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping_no_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise _DuplicateKey(
                None, None, "duplicate key %r" % (key,), key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_duplicates)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_MISSING = object()


class _Errors:
    def __init__(self):
        self.items: List[Refusal] = []

    def add(self, category, path, declared, requirement, reason, remedy=None):
        self.items.append(Refusal(category=category, declared=declared,
                                  requirement=requirement, reason=reason,
                                  remedy=remedy, path=path))

    def schema(self, path, declared, requirement, reason="The declaration does not "
               "follow the schema, so Stratum cannot tell what design is meant.",
               remedy=None):
        self.add("schema", path, declared, requirement, reason,
                 remedy or "Correct the field; see declarations/README.md for the schema.")


def _show(value) -> str:
    if value is _MISSING:
        return "(field absent)"
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def _mapping(errs, value, path, allowed, required) -> Optional[Dict[str, Any]]:
    """Check that value is a mapping with only allowed keys and all required keys."""
    if not isinstance(value, dict):
        errs.schema(path, _show(value), "%s must be a mapping of fields" % path)
        return None
    ok = True
    for key in value:
        if key not in allowed:
            ok = False
            errs.schema("%s.%s" % (path, key), "unknown field %r" % (key,),
                        "only these fields are allowed at %s: %s" % (path, ", ".join(allowed)),
                        reason="Stratum rejects fields it does not understand rather than "
                               "ignoring them, because an ignored field could carry design "
                               "information the analysis would then silently miss.")
    for key in required:
        if key not in value:
            ok = False
            errs.schema("%s.%s" % (path, key), "(field absent)",
                        "field %r is required at %s" % (key, path),
                        reason="This information is part of the design declaration and is "
                               "never inferred.")
    return value if ok else None


def _text(errs, value, path, nullable=False) -> Tuple[bool, Optional[str]]:
    if value is None and nullable:
        return True, None
    if isinstance(value, str) and value.strip():
        return True, value
    errs.schema(path, _show(value), "%s must be a non-empty text value%s"
                % (path, " or null" if nullable else ""))
    return False, None


def _positive_int(errs, value, path) -> Tuple[bool, Optional[int]]:
    # bool is a subclass of int in Python; a YAML "yes" must not become a count of 1.
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return True, value
    errs.schema(path, _show(value), "%s must be a whole number of at least 1" % path,
                reason="Counts describe the balanced design: one whole number per level.",
                remedy="Give a single whole number. A list or range would describe an "
                       "unbalanced design, which v1 does not support.")
    return False, None


def _bool(errs, value, path) -> Tuple[bool, Optional[bool]]:
    if isinstance(value, bool):
        return True, value
    errs.schema(path, _show(value), "%s must be true or false" % path)
    return False, None


def _choice(errs, value, path, options) -> Tuple[bool, Optional[str]]:
    if isinstance(value, str) and value in options:
        return True, value
    errs.schema(path, _show(value), "%s must be exactly one of: %s" % (path, ", ".join(options)))
    return False, None


def _labels(errs, value, path, min_len=1) -> Tuple[bool, Optional[Tuple[str, ...]]]:
    """A list of factor level labels. Text or whole numbers only, normalised to text."""
    if not isinstance(value, list) or len(value) < min_len:
        errs.schema(path, _show(value), "%s must be a list of at least %d level label(s)"
                    % (path, min_len))
        return False, None
    out = []
    ok = True
    for i, item in enumerate(value):
        p = "%s[%d]" % (path, i)
        if isinstance(item, bool) or not isinstance(item, (str, int)) or \
                (isinstance(item, str) and not item.strip()):
            ok = False
            errs.schema(p, _show(item), "each level label must be text or a whole number",
                        reason="YAML reads some unquoted words as other types (no -> false, "
                               "1.0 -> a decimal). Stratum will not guess which label was meant.",
                        remedy="Quote the label, e.g. \"no\" or \"1.0\".")
            continue
        out.append(str(item))
    if ok and len(set(out)) != len(out):
        ok = False
        errs.schema(path, _show(value), "level labels must be distinct (compared as text)")
    return ok, tuple(out) if ok else None


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

_TOP_KEYS = ("stratum_declaration", "claimed_template", "description", "response",
             "hierarchy", "treatments", "nuisance_factors", "comparisons", "split_plot")
_TOP_REQUIRED = ("stratum_declaration", "claimed_template", "response", "hierarchy",
                 "treatments", "nuisance_factors", "comparisons")


def _parse_response(errs, raw):
    m = _mapping(errs, raw, "response", ("column", "units"), ("column", "units"))
    if m is None:
        return None
    ok1, column = _text(errs, m["column"], "response.column")
    ok2, units = _text(errs, m["units"], "response.units", nullable=True)
    return Response(column, units) if ok1 and ok2 else None


def _parse_hierarchy(errs, raw):
    if not isinstance(raw, list) or not raw:
        errs.schema("hierarchy", _show(raw),
                    "hierarchy must be a non-empty list of levels, largest unit first")
        return None
    levels = []
    ok = True
    for i, item in enumerate(raw):
        path = "hierarchy[%d]" % i
        if i == 0:
            m = _mapping(errs, item, path, ("name", "id_column", "count"),
                         ("name", "id_column", "count"))
            if m is None:
                ok = False
                if isinstance(item, dict) and ("nested_in" in item or "count_per_parent" in item
                                               or "exchangeable" in item or "id_scope" in item):
                    errs.add("hierarchy", path, _show(item),
                             "the first hierarchy level is the top level: it has a total "
                             "'count' and no nested_in, count_per_parent, exchangeable or id_scope",
                             "The hierarchy is ordered from the largest unit down. The top "
                             "level is not nested in anything, so it cannot carry nesting "
                             "fields.",
                             "List the largest unit (e.g. run or lot) first, with 'count'.")
                continue
            okn, name = _text(errs, m["name"], path + ".name")
            oki, idc = _text(errs, m["id_column"], path + ".id_column")
            okc, count = _positive_int(errs, m["count"], path + ".count")
            if okn and oki and okc:
                levels.append(Level(name, idc, None, count, "global", None, False))
            else:
                ok = False
        else:
            m = _mapping(errs, item, path,
                         ("name", "id_column", "nested_in", "count_per_parent",
                          "exchangeable", "id_scope"),
                         ("name", "id_column", "nested_in", "count_per_parent"))
            if m is None:
                ok = False
                continue
            okn, name = _text(errs, m["name"], path + ".name")
            oki, idc = _text(errs, m["id_column"], path + ".id_column")
            okp, parent = _text(errs, m["nested_in"], path + ".nested_in")
            okc, count = _positive_int(errs, m["count_per_parent"], path + ".count_per_parent")
            exch_declared = "exchangeable" in m
            oke, exch = (_bool(errs, m["exchangeable"], path + ".exchangeable")
                         if exch_declared else (True, False))
            oks, scope = (_choice(errs, m["id_scope"], path + ".id_scope", ID_SCOPES)
                          if "id_scope" in m else (True, "parent"))
            if okn and oki and okp and okc and oke and oks:
                levels.append(Level(name, idc, parent, count, scope, exch, exch_declared))
            else:
                ok = False
    if not ok:
        return None

    names = [lv.name for lv in levels]
    if len(set(names)) != len(names):
        errs.add("inconsistent_declaration", "hierarchy", "level names %s" % names,
                 "every hierarchy level has a distinct name",
                 "A repeated name makes treatment and nesting references ambiguous.")
        return None
    ids = [lv.id_column for lv in levels]
    if len(set(ids)) != len(ids):
        errs.add("inconsistent_declaration", "hierarchy", "id columns %s" % ids,
                 "every hierarchy level has its own ID column",
                 "Two levels sharing one ID column would be the same grouping, so their "
                 "variation could not be separated (they would be aliased).")
        return None

    # The hierarchy must be one nesting chain: each level nested in the level directly above.
    for i in range(1, len(levels)):
        lv = levels[i]
        path = "hierarchy[%d].nested_in" % i
        if lv.nested_in == levels[i - 1].name:
            continue
        ok = False
        if lv.nested_in not in names:
            errs.add("inconsistent_declaration", path, "nested_in: %r" % lv.nested_in,
                     "nested_in names a declared hierarchy level",
                     "Level %r is declared nested in a level that does not exist." % lv.name)
        elif lv.nested_in == lv.name:
            errs.add("hierarchy", path, "level %r nested in itself" % lv.name,
                     "each level is nested in the level directly above it",
                     "A level cannot be nested in itself.")
        else:
            errs.add("hierarchy", path,
                     "level %r is nested in %r, but the level listed directly above it is %r"
                     % (lv.name, lv.nested_in, levels[i - 1].name),
                     "the hierarchy is a single chain: each level is nested in the level "
                     "listed directly above it",
                     "Two levels nested side by side in the same parent, or a level nested "
                     "out of order, form a branching or crossed structure. v1 templates "
                     "are pure nesting chains; branching and crossed random structures need "
                     "a general mixed model, which Stratum deliberately is not.",
                     "If the levels really are a chain, list them in nesting order. "
                     "Otherwise this design is outside v1; fit it in lme4 or lmerTest.")
    return tuple(levels) if ok else None


def _parse_treatments(errs, raw, level_names):
    if not isinstance(raw, list):
        errs.schema("treatments", _show(raw),
                    "treatments must be a list; write [] to declare that there is no treatment")
        return None
    out = []
    ok = True
    for i, item in enumerate(raw):
        path = "treatments[%d]" % i
        keys = ("name", "column", "levels", "applied_to", "replicates_per_level", "assignment")
        m = _mapping(errs, item, path, keys, keys)
        if m is None:
            ok = False
            continue
        okn, name = _text(errs, m["name"], path + ".name")
        okc, column = _text(errs, m["column"], path + ".column")
        okl, levels = _labels(errs, m["levels"], path + ".levels")
        oka, applied = _text(errs, m["applied_to"], path + ".applied_to")
        okr, reps = _positive_int(errs, m["replicates_per_level"],
                                  path + ".replicates_per_level")
        am = _mapping(errs, m["assignment"], path + ".assignment",
                      ("method", "description"), ("method",))
        okm, method, desc = False, None, None
        if am is not None:
            okm, method = _choice(errs, am["method"], path + ".assignment.method",
                                  ASSIGNMENT_METHODS)
            if "description" in am:
                okd, desc = _text(errs, am["description"], path + ".assignment.description")
                okm = okm and okd
        if not (okn and okc and okl and oka and okr and okm):
            ok = False
            continue
        if level_names is not None and applied not in level_names:
            ok = False
            errs.add("inconsistent_declaration", path + ".applied_to", "applied_to: %r" % applied,
                     "applied_to names a declared hierarchy level (the experimental unit)",
                     "The treatment is declared as applied to a unit that is not in the "
                     "hierarchy, so its experimental unit is unknown.",
                     "Use one of the hierarchy level names: %s." % ", ".join(level_names))
            continue
        out.append(Treatment(name, column, levels, applied, reps, method, desc))
    return tuple(out) if ok else None


def _parse_nuisance(errs, raw, level_names):
    if not isinstance(raw, list):
        errs.schema("nuisance_factors", _show(raw),
                    "nuisance_factors must be a list; write [] if none was recorded")
        return None
    out = []
    ok = True
    for i, item in enumerate(raw):
        path = "nuisance_factors[%d]" % i
        m = _mapping(errs, item, path,
                     ("name", "column", "recorded_at", "role", "levels", "crossed_with"),
                     ("name", "column", "recorded_at", "role"))
        if m is None:
            ok = False
            continue
        okn, name = _text(errs, m["name"], path + ".name")
        okc, column = _text(errs, m["column"], path + ".column")
        oka, at = _text(errs, m["recorded_at"], path + ".recorded_at")
        okr, role = _choice(errs, m["role"], path + ".role", NUISANCE_ROLES)
        okl, levels = (_labels(errs, m["levels"], path + ".levels")
                       if "levels" in m else (True, None))
        okx, crossed = (_text(errs, m["crossed_with"], path + ".crossed_with")
                        if "crossed_with" in m else (True, None))
        if not (okn and okc and oka and okr and okl and okx):
            ok = False
            continue
        if role == "block" and (levels is None or crossed is None):
            ok = False
            errs.schema(path, _show(item),
                        "a nuisance factor with role 'block' must declare its levels and "
                        "the treatment it is crossed_with",
                        reason="A block is only supported as a balanced factor crossed with "
                               "the treatment; that cannot be checked without both.")
            continue
        if role == "recorded" and crossed is not None:
            ok = False
            errs.add("blocking", path + ".crossed_with", "role: recorded with crossed_with: %r"
                     % crossed,
                     "crossed_with is declared only for a role 'block' factor",
                     "A recorded nuisance factor is only checked for confounding; declaring "
                     "it crossed with a treatment would make it part of the design.",
                     "Use role: block if it is the one balanced block crossed with the T2 "
                     "treatment; otherwise remove crossed_with.")
            continue
        if level_names is not None and at not in level_names:
            ok = False
            errs.add("inconsistent_declaration", path + ".recorded_at", "recorded_at: %r" % at,
                     "recorded_at names a declared hierarchy level",
                     "The level at which this factor is constant must be a declared unit.",
                     "Use one of: %s." % ", ".join(level_names))
            continue
        out.append(NuisanceFactor(name, column, at, role, levels, crossed))
    return tuple(out) if ok else None


def _parse_comparisons(errs, raw, treatments):
    if not isinstance(raw, list):
        errs.schema("comparisons", _show(raw),
                    "comparisons must be a list; write [] when no comparison is intended (T1)")
        return None
    by_name = {t.name: t for t in treatments} if treatments is not None else None
    out = []
    ok = True
    for i, item in enumerate(raw):
        path = "comparisons[%d]" % i
        m = _mapping(errs, item, path, ("id", "kind", "factors", "levels", "description"),
                     ("id", "kind", "factors"))
        if m is None:
            ok = False
            continue
        oki, cid = _text(errs, m["id"], path + ".id")
        okk, kind = _choice(errs, m["kind"], path + ".kind", COMPARISON_KINDS)
        okf, factors = _labels(errs, m["factors"], path + ".factors")
        okd, desc = (_text(errs, m["description"], path + ".description")
                     if "description" in m else (True, None))
        if not (oki and okk and okf and okd):
            ok = False
            continue
        want = 2 if kind == "interaction" else 1
        if len(factors) != want:
            ok = False
            errs.schema(path + ".factors", _show(m["factors"]),
                        "a %s comparison names exactly %d factor(s)" % (kind, want))
            continue
        if by_name is not None:
            unknown = [f for f in factors if f not in by_name]
            if unknown:
                ok = False
                errs.add("comparison", path + ".factors", "factors: %s" % list(factors),
                         "every compared factor is a declared treatment",
                         "Intended comparisons are between treatment levels. %s is not a "
                         "declared treatment; nuisance factors are checked for confounding, "
                         "not compared." % ", ".join(repr(u) for u in unknown),
                         "Declare the factor under treatments, or remove the comparison.")
                continue
        pair = None
        if kind == "pairwise":
            okp, pair = _labels(errs, m.get("levels", _MISSING), path + ".levels", min_len=2)
            if not okp:
                ok = False
                continue
            if len(pair) != 2:
                ok = False
                errs.schema(path + ".levels", _show(m["levels"]),
                            "a pairwise comparison names exactly two distinct levels")
                continue
            if by_name is not None:
                bad = [lv for lv in pair if lv not in by_name[factors[0]].levels]
                if bad:
                    ok = False
                    errs.add("inconsistent_declaration", path + ".levels",
                             "levels: %s" % list(pair),
                             "pairwise levels are declared levels of %r" % factors[0],
                             "%s is not a level of %r." % (", ".join(repr(b) for b in bad),
                                                           factors[0]))
                    continue
        elif "levels" in m:
            ok = False
            errs.schema(path + ".levels", _show(m["levels"]),
                        "levels is given only for a pairwise comparison")
            continue
        out.append(Comparison(cid, kind, factors, pair, desc))
    if ok:
        ids = [c.id for c in out]
        if len(set(ids)) != len(ids):
            errs.schema("comparisons", "ids %s" % ids, "comparison ids are distinct")
            return None
    return tuple(out) if ok else None


def _parse_split_plot(errs, raw, treatment_names):
    keys = ("whole_plot_factor", "subplot_factor")
    m = _mapping(errs, raw, "split_plot", keys, keys)
    if m is None:
        return None
    oka, a = _text(errs, m["whole_plot_factor"], "split_plot.whole_plot_factor")
    okb, b = _text(errs, m["subplot_factor"], "split_plot.subplot_factor")
    if not (oka and okb):
        return None
    if a == b:
        errs.add("split_plot", "split_plot", "whole_plot_factor and subplot_factor are both %r" % a,
                 "the whole-plot and subplot factors are two different treatments",
                 "One factor cannot be applied both to whole plots and to subplots.")
        return None
    if treatment_names is not None:
        for key, name in (("whole_plot_factor", a), ("subplot_factor", b)):
            if name not in treatment_names:
                errs.add("inconsistent_declaration", "split_plot." + key, "%s: %r" % (key, name),
                         "split_plot names declared treatments",
                         "%r is not a declared treatment." % name)
                return None
    return SplitPlot(a, b)


def _check_columns(errs, decl_parts):
    """Each data column plays one role, with one exception handled by the templates:
    a T3 subplot factor may be the ID column of the subplot level (e.g. position)."""
    response, hierarchy, treatments, nuisance = decl_parts
    roles: Dict[str, List[str]] = {}

    def note(col, role):
        roles.setdefault(col, []).append(role)

    note(response.column, "response")
    for t in treatments:
        note(t.column, "treatment %r" % t.name)
    for f in nuisance:
        note(f.column, "nuisance factor %r" % f.name)
    clashes = {c: r for c, r in roles.items() if len(r) > 1}
    for lv in hierarchy:
        if lv.id_column == response.column:
            clashes.setdefault(lv.id_column, ["response"]).append("ID of level %r" % lv.name)
        for f in nuisance:
            if lv.id_column == f.column:
                clashes.setdefault(lv.id_column, []).extend(
                    ["nuisance factor %r" % f.name, "ID of level %r" % lv.name])
    for col, used in sorted(clashes.items()):
        errs.add("inconsistent_declaration", "columns", "column %r used as %s"
                 % (col, " and ".join(dict.fromkeys(used))),
                 "each data column has one role in the declaration",
                 "One column cannot be two different things; the declaration contradicts itself.")
    names = [t.name for t in treatments] + [f.name for f in nuisance]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        errs.add("inconsistent_declaration", "treatments/nuisance_factors",
                 "factor name(s) %s declared more than once" % dup,
                 "treatment and nuisance factor names are distinct",
                 "A name used twice makes comparisons and split-plot roles ambiguous.")
    return not clashes and not dup


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def parse_declaration(data: Any) -> ParseResult:
    """Validate an already-loaded YAML document (dict) and build a Declaration."""
    errs = _Errors()
    top = _mapping(errs, data, "declaration", _TOP_KEYS, _TOP_REQUIRED)
    if top is None:
        return ParseResult(None, tuple(errs.items))

    version = top["stratum_declaration"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        errs.schema("stratum_declaration", _show(version),
                    "stratum_declaration must be %d (the schema version)" % SCHEMA_VERSION)
    claimed = top["claimed_template"]
    if not isinstance(claimed, str):
        errs.schema("claimed_template", _show(claimed),
                    "claimed_template must be text: T1, T2 or T3")
    desc = None
    if "description" in top:
        _, desc = _text(errs, top["description"], "description")

    response = _parse_response(errs, top["response"])
    hierarchy = _parse_hierarchy(errs, top["hierarchy"])
    level_names = [lv.name for lv in hierarchy] if hierarchy is not None else None
    treatments = _parse_treatments(errs, top["treatments"], level_names)
    nuisance = _parse_nuisance(errs, top["nuisance_factors"], level_names)
    comparisons = _parse_comparisons(errs, top["comparisons"], treatments)

    split = None
    if "split_plot" in top:
        names = [t.name for t in treatments] if treatments is not None else None
        split = _parse_split_plot(errs, top["split_plot"], names)

    if treatments is not None and nuisance is not None:
        for f in nuisance:
            if f.crossed_with is not None and f.crossed_with not in [t.name for t in treatments]:
                errs.add("inconsistent_declaration",
                         "nuisance_factors(%s).crossed_with" % f.name,
                         "crossed_with: %r" % f.crossed_with,
                         "crossed_with names a declared treatment",
                         "The block is declared crossed with a treatment that does not exist.")

    if not errs.items and None not in (response, hierarchy, treatments, nuisance):
        _check_columns(errs, (response, hierarchy, treatments, nuisance))

    if errs.items:
        return ParseResult(None, tuple(errs.items))
    return ParseResult(Declaration(SCHEMA_VERSION, claimed, desc, response, hierarchy,
                                   treatments, nuisance, comparisons, split), ())


def load_declaration(source: Union[str, Path]) -> ParseResult:
    """Load YAML from a file path (Path) or from YAML text (str) and validate it."""
    text = Path(source).read_text(encoding="utf-8") if isinstance(source, Path) else source
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - _StrictLoader is a SafeLoader
    except yaml.YAMLError as exc:
        return ParseResult(None, (Refusal(
            category="yaml_syntax", declared=" ".join(str(exc).split()),
            requirement="the declaration is one valid YAML document with no duplicate keys",
            reason="Stratum cannot read the declaration. A duplicated key is refused rather "
                   "than letting the later value silently win.",
            remedy="Fix the YAML at the position shown."),))
    return parse_declaration(data)
