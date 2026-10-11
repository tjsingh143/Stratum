"""Template matching: does a valid declaration fit T1, T2 or T3 exactly?

Each template is an ordered tuple of named Conditions (T1_CONDITIONS, T2_CONDITIONS,
T3_CONDITIONS). Every condition states its requirement in words and has one check.
Matching evaluates every condition of the *claimed* template only, and matches when
none fails. A declaration is never re-tried against another template, so nothing is
silently coerced into the nearest supported structure (brief WP1, "Judged by").

A check returns:
  None      the condition holds;
  Fail(...) it does not, with what was declared, why, and what would be needed;
  SKIP      it cannot be evaluated because a prerequisite condition failed
            (for example "the treatment is replicated" when no treatment exists).

The template definitions follow PROJECT_BRIEF.md Section 5 and the WP1 decisions
D-035 to D-039 in DECISIONS.md.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple, Union

from .declaration import (SUPPORTED_TEMPLATES, Declaration, load_declaration,
                          parse_declaration)
from .refusal import Refusal


@dataclass(frozen=True)
class Fail:
    declared: str
    reason: str
    remedy: Optional[str] = None


SKIP = object()
LME4 = "Designs outside v1 can be fitted in lme4 or lmerTest; Stratum does not analyze them."


@dataclass(frozen=True)
class Condition:
    id: str
    category: str
    requirement: str
    check: Callable[[Declaration], object]


@dataclass(frozen=True)
class ConditionResult:
    id: str
    requirement: str
    status: str                  # "pass", "fail" or "not_evaluated"
    refusal: Optional[Refusal] = None


@dataclass(frozen=True)
class MatchResult:
    claimed_template: Optional[str]
    matched_template: Optional[str]          # set only when every condition passed
    declaration: Optional[Declaration]
    conditions: Tuple[ConditionResult, ...]  # empty when the declaration did not parse
    refusals: Tuple[Refusal, ...]

    @property
    def matched(self) -> bool:
        return self.matched_template is not None

    @property
    def decision(self) -> str:
        return "matched" if self.matched else "refused"

    @property
    def refusal_categories(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(r.category for r in self.refusals))

    @property
    def failed_conditions(self) -> Tuple[str, ...]:
        return tuple(c.id for c in self.conditions if c.status == "fail")

    def explain(self) -> str:
        if self.matched:
            lines = ["MATCHED %s. Every structural condition holds:" % self.matched_template]
            lines += ["  pass  %s: %s" % (c.id, c.requirement) for c in self.conditions]
            return "\n".join(lines)
        lines = ["REFUSED. The declaration (claimed %s) is not analyzed. Stratum does not "
                 "reinterpret it as a different template." % (self.claimed_template or "?")]
        for r in self.refusals:
            lines.append(r.explain())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _names(decl, attr="name", items=None):
    return [getattr(x, attr) for x in (items if items is not None else decl.treatments)]


def _only_treatment(decl):
    return decl.treatments[0] if len(decl.treatments) == 1 else None


def _split_factors(decl):
    """(A, B) treatments for a T3 declaration, or None if roles are not usable."""
    sp = decl.split_plot
    if sp is None or len(decl.treatments) != 2 or \
            set(_names(decl)) != {sp.whole_plot_factor, sp.subplot_factor}:
        return None
    return decl.treatment(sp.whole_plot_factor), decl.treatment(sp.subplot_factor)


def _no_split_plot(template):
    def check(decl):
        if decl.split_plot is None:
            return None
        return Fail("split_plot: whole_plot_factor %r, subplot_factor %r"
                    % (decl.split_plot.whole_plot_factor, decl.split_plot.subplot_factor),
                    "Split-plot roles describe a T3 design. Declaring them under %s is a "
                    "contradiction, and Stratum will not decide which part was meant." % template,
                    "If the design is a split-plot, claim T3. Otherwise remove split_plot.")
    return check


def _no_blocks(template):
    def check(decl):
        if not decl.blocks:
            return None
        return Fail("block factor(s) %s" % _names(decl, items=decl.blocks),
                    "%s has no blocking factor. The only supported block in v1 is one "
                    "balanced block crossed with a T2 treatment (brief Section 5.2)." % template,
                    "If the factor was only recorded, declare it with role: recorded so it "
                    "is checked for confounding. " + LME4)
    return check


def _hierarchy_text(decl):
    return " > ".join("%s(%d)" % (lv.name, lv.count) for lv in decl.hierarchy)


# ---------------------------------------------------------------------------
# T1: balanced nested variance components, no treatment (brief Section 5.1)
# ---------------------------------------------------------------------------

def _t1_no_treatment(decl):
    if not decl.treatments:
        return None
    t = decl.treatments[0]
    return Fail("treatment(s) %s; e.g. %r applied to %r" % (_names(decl), t.name, t.applied_to),
                "T1 has no treatment. It partitions variation among nested levels and "
                "tests no factor. Stratum does not extend T1 with a fixed factor (D-014).",
                "If the factor was assigned to replicated top-level units, claim T2. If it "
                "is an observed property recorded only to check for confounding, move it to "
                "nuisance_factors with role: recorded.")


def _t1_no_comparisons(decl):
    if not decl.comparisons:
        return None
    return Fail("comparisons %s" % _names(decl, "id", decl.comparisons),
                "T1 makes no comparison between treatment levels; its results are variance "
                "components only.",
                "Remove the comparisons, or claim T2 or T3 if a treatment was applied.")


def _t1_three_levels(decl):
    n = len(decl.hierarchy)
    if n == 3:
        return None
    if n < 3:
        why = ("v1 T1 is the nested model with two random levels above the observation "
               "(brief Section 5.1; e.g. run > zone > wafer, lot > wafer > site). A %d-level "
               "hierarchy is a simpler model that v1 does not define or validate." % n)
    else:
        why = ("v1 T1 is exactly three levels (two random levels above the observation). "
               "Deeper nesting has more variance components than the v1 T1 formulas and "
               "validation cover.")
    return Fail("%d-level hierarchy: %s" % (n, _hierarchy_text(decl)), why, LME4)


def _t1_replication(decl):
    problems = []
    if decl.top.count < 2:
        problems.append("top level %r has count %d" % (decl.top.name, decl.top.count))
    for lv in decl.hierarchy[1:]:
        if lv.count < 2:
            problems.append("%r has count_per_parent %d" % (lv.name, lv.count))
    if not problems:
        return None
    return Fail("; ".join(problems),
                "Every T1 variance component needs at least two units at its level. With one "
                "top-level unit there is no between-group variation to estimate. With one "
                "unit per parent, that level's variation and the variation of the level above "
                "it cannot be separated; they are aliased.",
                "Declare at least 2 units at every level. If a level truly has one unit per "
                "parent, the design cannot separate that component; no declaration fixes this.")


T1_CONDITIONS = (
    Condition("T1.no_treatment", "treatment_structure",
              "no treatment is declared", _t1_no_treatment),
    Condition("T1.no_comparisons", "comparison",
              "no intended comparison is declared", _t1_no_comparisons),
    Condition("T1.no_split_plot", "split_plot",
              "no split-plot roles are declared", _no_split_plot("T1")),
    Condition("T1.no_blocking", "blocking",
              "no nuisance factor has role block", _no_blocks("T1")),
    Condition("T1.three_level_chain", "hierarchy",
              "the hierarchy is a nesting chain of exactly three levels (top > middle > "
              "observation)", _t1_three_levels),
    Condition("T1.replicated_every_level", "replication",
              "top-level count >= 2 and count_per_parent >= 2 at both nested levels",
              _t1_replication),
)


# ---------------------------------------------------------------------------
# T2: one treatment on the top-level unit, balanced subsampling (brief Section 5.2)
# ---------------------------------------------------------------------------

def _t2_one_treatment(decl):
    n = len(decl.treatments)
    if n == 1:
        return None
    if n == 0:
        return Fail("treatments: [] (no treatment)",
                    "T2 tests one treatment against variation among the units it was applied "
                    "to. With no treatment there is nothing to test.",
                    "If the study only describes variation among nested levels, claim T1.")
    return Fail("%d treatments: %s" % (n, _names(decl)),
                "T2 has exactly one treatment. Two or more treatments on the same units form "
                "a factorial design that v1 does not support.",
                "If one factor was applied to whole units and another to subunits within "
                "them, that is a split-plot: claim T3. " + LME4)


def _t2_applied_at_top(decl):
    t = _only_treatment(decl)
    if t is None:
        return SKIP
    if t.applied_to == decl.top.name:
        return None
    above = [lv.name for lv in decl.hierarchy[: decl.level_index(t.applied_to)]]
    return Fail("treatment %r applied to %r, which is nested in %s; hierarchy %s"
                % (t.name, t.applied_to, " > ".join(above), _hierarchy_text(decl)),
                "In T2 the treatment's experimental unit is the top level of the hierarchy, "
                "and everything below it is subsampling. A treatment applied to %r inside "
                "%r makes %r a grouping above the experimental unit (a block or whole plot). "
                "That is a different design, with a different error term."
                % (t.applied_to, above[-1], above[-1]),
                "If the treatment was applied to whole %r units, set applied_to: %r. If "
                "another factor was applied to %r, the design may be a split-plot (T3). "
                % (decl.top.name, decl.top.name, above[-1]) + LME4)


def _t2_depth(decl):
    n = len(decl.hierarchy)
    if n in (2, 3):
        return None
    if n == 1:
        why = ("T2 has balanced subsampling below the experimental unit. A one-level "
               "hierarchy declares no observational level below the unit.")
        fix = ("Declare the measured unit below %r (count_per_parent may be 1 if each unit "
               "was measured once)." % decl.top.name)
    else:
        why = ("v1 T2 supports at most two subsampling levels below the experimental unit "
               "(e.g. wafers within run, sites within wafer; brief Sections 5.2 and 5.5).")
        fix = LME4
    return Fail("%d-level hierarchy: %s" % (n, _hierarchy_text(decl)), why, fix)


def _t2_levels(decl):
    t = _only_treatment(decl)
    if t is None:
        return SKIP
    if len(t.levels) >= 2:
        return None
    return Fail("treatment %r has levels %s" % (t.name, list(t.levels)),
                "A comparison needs at least two treatment levels.",
                "Declare every level that was applied.")


def _t2_replicated(decl):
    t = _only_treatment(decl)
    if t is None:
        return SKIP
    if t.replicates_per_level >= 2:
        return None
    sub = decl.hierarchy[1:]
    return Fail("treatment %r: replicates_per_level %d %r per level%s"
                % (t.name, t.replicates_per_level, t.applied_to,
                   (", with %s below each" % ", ".join("%d %r" % (lv.count, lv.name)
                                                     for lv in sub)) if sub else ""),
                "With one %r per treatment level there is no variation among units "
                "treated alike, so the treatment test has zero error degrees of freedom "
                "(brief Section 5.2). Subsamples measure within-unit variation only; more of "
                "them cannot replace replicated %r units." % (t.applied_to, t.applied_to),
                "Run at least two %r units per treatment level. No declaration change "
                "can make this design testable." % t.applied_to)


def _t2_balance(decl):
    t = _only_treatment(decl)
    if t is None or t.applied_to != decl.top.name:
        return SKIP
    need = len(t.levels) * t.replicates_per_level
    if need == decl.top.count:
        return None
    return Fail("%d levels x %d replicates = %d, but the top level %r has count %d"
                % (len(t.levels), t.replicates_per_level, need, decl.top.name, decl.top.count),
                "In balanced T2 every top-level unit receives exactly one treatment level and "
                "every level is applied to the same number of units. The declared counts "
                "contradict that.",
                "Correct the counts. If treatment levels really have different numbers of "
                "units, the design is unbalanced at the unit level, which v1 refuses "
                "(brief Section 5.4). " + LME4)


def _t2_column_not_id(decl):
    t = _only_treatment(decl)
    if t is None:
        return SKIP
    if t.column not in decl.id_columns:
        return None
    return Fail("treatment column %r is also the ID column of a hierarchy level" % t.column,
                "If treatment labels identify units, each unit is its own treatment level and "
                "there is no replication within a level.",
                "Give the treatment its own column.")


def _inherent_refusal(t, role):
    return Fail("%s %r has assignment method 'inherent' (%s)"
                % (role, t.name, t.assignment_description or "no description"),
                "'inherent' declares that the levels are properties the %r units already "
                "had, not something applied to them. Comparing such groups is an "
                "observational comparison between kinds of unit; it is not the applied-"
                "treatment design this template is defined for (D-006, D-014, D-039)."
                % t.applied_to,
                "If the factor was in fact applied to the units, declare the assignment "
                "method (randomized, systematic, or not_stated). If it is an observed "
                "property, declare it under nuisance_factors with role: recorded; it will be "
                "checked for confounding, not tested.")


def _t2_assigned(decl):
    t = _only_treatment(decl)
    if t is None:
        return SKIP
    return None if t.assignment_method != "inherent" else _inherent_refusal(t, "treatment")


def _t2_comparisons(decl):
    t = _only_treatment(decl)
    if t is None:
        return SKIP
    if not decl.comparisons:
        return Fail("comparisons: []",
                    "T2 exists to answer an intended comparison; none was declared.",
                    "Declare at least one comparison of %r (kind overall or pairwise)." % t.name)
    bad = [c.id for c in decl.comparisons if c.kind == "interaction"]
    if bad:
        return Fail("interaction comparison(s) %s" % bad,
                    "T2 has one treatment, so there is no interaction to estimate.",
                    "Remove the interaction, or claim T3 if a second factor was applied to "
                    "subunits.")
    return None


def _t2_block(decl):
    blocks = decl.blocks
    if not blocks:
        return None
    if len(blocks) > 1:
        return Fail("%d block factors: %s" % (len(blocks), _names(decl, items=blocks)),
                    "T2 allows at most one balanced blocking factor crossed with the "
                    "treatment (brief Section 5.2). More would make Stratum a general "
                    "mixed-model interface, which it deliberately is not.",
                    "Keep the one block the design was built around, and declare the others "
                    "with role: recorded so they are checked for confounding. " + LME4)
    b = blocks[0]
    t = _only_treatment(decl)
    problems = []
    if b.recorded_at != decl.top.name:
        problems.append("block %r is recorded at %r, not at the experimental unit %r"
                        % (b.name, b.recorded_at, decl.top.name))
    if t is not None and b.crossed_with != t.name:
        problems.append("block %r is crossed_with %r, not with the treatment %r"
                        % (b.name, b.crossed_with, t.name))
    if len(b.levels) < 2:
        problems.append("block %r has %d level" % (b.name, len(b.levels)))
    elif t is not None and t.replicates_per_level % len(b.levels) != 0:
        problems.append("%d replicates per treatment level cannot be split equally over %d "
                        "levels of %r" % (t.replicates_per_level, len(b.levels), b.name))
    if not problems:
        return None
    return Fail("; ".join(problems),
                "The supported block is constant within each experimental unit and crossed "
                "with the treatment so that every block level receives every treatment level "
                "equally often. Anything else is either not a block of the experimental units "
                "or an unbalanced crossing, which v1 does not analyze.",
                "Declare the block at %r, crossed_with the treatment, with a number of levels "
                "that divides the replicates per treatment level. If it was only recorded, "
                "use role: recorded." % decl.top.name)


T2_CONDITIONS = (
    Condition("T2.one_treatment", "treatment_structure",
              "exactly one treatment is declared", _t2_one_treatment),
    Condition("T2.applied_at_top_level", "application_level",
              "the treatment is applied to the top hierarchy level (the experimental unit)",
              _t2_applied_at_top),
    Condition("T2.subsampling_depth", "hierarchy",
              "the hierarchy is the experimental unit plus one or two subsampling levels",
              _t2_depth),
    Condition("T2.treatment_levels", "treatment_structure",
              "the treatment has at least two levels", _t2_levels),
    Condition("T2.treatment_applied_not_inherent", "assignment",
              "the treatment's assignment method is not 'inherent'", _t2_assigned),
    Condition("T2.replicated", "replication",
              "replicates_per_level >= 2 experimental units per treatment level", _t2_replicated),
    Condition("T2.balanced_units", "balance",
              "treatment levels x replicates_per_level = top-level count", _t2_balance),
    Condition("T2.treatment_column_not_unit_id", "inconsistent_declaration",
              "the treatment column is not a hierarchy ID column", _t2_column_not_id),
    Condition("T2.no_split_plot", "split_plot",
              "no split-plot roles are declared", _no_split_plot("T2")),
    Condition("T2.comparisons", "comparison",
              "at least one comparison of the treatment, none of kind interaction",
              _t2_comparisons),
    Condition("T2.supported_block", "blocking",
              "at most one block: recorded at the experimental unit, crossed with the "
              "treatment, >= 2 levels dividing replicates_per_level", _t2_block),
)


# ---------------------------------------------------------------------------
# T3: balanced split-plot (brief Section 5.3)
# ---------------------------------------------------------------------------

def _t3_roles(decl):
    sp = decl.split_plot
    if sp is None:
        return Fail("no split_plot section; treatments %s" % _names(decl),
                    "T3 needs an explicit whole-plot factor A and subplot factor B. Stratum "
                    "does not infer split-plot roles from application levels.",
                    "Add split_plot: {whole_plot_factor: <A>, subplot_factor: <B>}. If only "
                    "one factor was applied, the design is not a split-plot; Stratum will not "
                    "reinterpret it as T2. Claim T2 yourself if that is the design.")
    if len(decl.treatments) != 2:
        return Fail("%d treatment(s) %s with split_plot roles %r and %r"
                    % (len(decl.treatments), _names(decl), sp.whole_plot_factor,
                       sp.subplot_factor),
                    "T3 has exactly two treatments: the whole-plot factor and the subplot "
                    "factor. Additional factors are outside v1.",
                    LME4)
    return None


def _t3_two_levels(decl):
    n = len(decl.hierarchy)
    if n == 2:
        return None
    return Fail("%d-level hierarchy: %s" % (n, _hierarchy_text(decl)),
                "v1 T3 is the model of brief Section 5.3: whole plots, and one observed "
                "subplot unit per subplot level inside each whole plot. %s"
                % ("Subsampling inside subplot units adds a stratum that model does not "
                   "have." if n > 2 else "One level cannot hold both factors."),
                "Declare exactly two levels: the whole-plot unit and the subplot unit. "
                + LME4)


def _t3_whole_plot_level(decl):
    ab = _split_factors(decl)
    if ab is None:
        return SKIP
    a = ab[0]
    if a.applied_to == decl.top.name:
        return None
    return Fail("whole-plot factor %r applied to %r; top level is %r"
                % (a.name, a.applied_to, decl.top.name),
                "The whole-plot factor is applied to the whole-plot units, which are the top "
                "hierarchy level, and is judged against variation among them.",
                "Set applied_to: %r for %r, or correct the split_plot roles."
                % (decl.top.name, a.name))


def _t3_subplot_level(decl):
    ab = _split_factors(decl)
    if ab is None or len(decl.hierarchy) != 2:   # wrong depth: T3.two_level_hierarchy fails
        return SKIP
    b = ab[1]
    if b.applied_to == decl.bottom.name:
        return None
    return Fail("subplot factor %r applied to %r; the subplot level is %r"
                % (b.name, b.applied_to, decl.bottom.name),
                "The subplot factor varies inside each whole plot, applied to the subplot "
                "units. If both factors are applied to the same units, the design is a "
                "factorial on those units, not a split-plot, and the two error strata do "
                "not exist.",
                "Set applied_to: %r for %r if that is how it was applied. Stratum will not "
                "reclassify this declaration as T2 or any other template." %
                (decl.bottom.name, b.name))


def _t3_whole_plot_assigned(decl):
    ab = _split_factors(decl)
    if ab is None:
        return SKIP
    a = ab[0]
    return None if a.assignment_method != "inherent" else \
        _inherent_refusal(a, "whole-plot factor")


def _t3_whole_plot_replication(decl):
    ab = _split_factors(decl)
    if ab is None:
        return SKIP
    a = ab[0]
    problems = []
    if len(a.levels) < 2:
        problems.append("%r has %d level" % (a.name, len(a.levels)))
    if a.replicates_per_level < 2:
        problems.append("%r has replicates_per_level %d" % (a.name, a.replicates_per_level))
    if not problems:
        return None
    return Fail("; ".join(problems),
                "A is tested against variation among whole plots treated alike, on a(r - 1) "
                "df. It needs a >= 2 levels and r >= 2 whole plots per level; with r = 1 "
                "there are zero error df, and more subplot readings cannot replace whole "
                "plots.",
                "Use at least two whole plots per level of %r." % a.name)


def _t3_whole_plot_balance(decl):
    ab = _split_factors(decl)
    if ab is None or ab[0].applied_to != decl.top.name:
        return SKIP
    a = ab[0]
    need = len(a.levels) * a.replicates_per_level
    if need == decl.top.count:
        return None
    return Fail("%d levels of %r x %d replicates = %d, but %r has count %d"
                % (len(a.levels), a.name, a.replicates_per_level, need, decl.top.name,
                   decl.top.count),
                "In balanced T3 each whole plot receives one level of A and every level has "
                "the same number of whole plots. The counts contradict that.",
                "Correct the counts. Unequal whole plots per level is unit-level imbalance, "
                "which v1 refuses. " + LME4)


def _t3_subplot_structure(decl):
    ab = _split_factors(decl)
    if ab is None or len(decl.hierarchy) != 2:
        return SKIP
    b = ab[1]
    problems = []
    if len(b.levels) < 2:
        problems.append("%r has %d level" % (b.name, len(b.levels)))
    if decl.bottom.count != len(b.levels):
        problems.append("%r has count_per_parent %d but %r has %d levels"
                        % (decl.bottom.name, decl.bottom.count, b.name, len(b.levels)))
    if b.replicates_per_level != decl.top.count:
        problems.append("%r replicates_per_level %d, but each of the %d whole plots must "
                        "contain each level once (expected %d)"
                        % (b.name, b.replicates_per_level, decl.top.count, decl.top.count))
    if not problems:
        return None
    return Fail("; ".join(problems),
                "Balanced T3 has b >= 2 subplot levels and exactly one subplot unit per B "
                "level in every whole plot, so B and A x B are estimable within whole plots. "
                "With one B level they are not estimable at all (D-021, C-3).",
                "Declare one subplot unit per level of %r in each whole plot. A design with "
                "a single subplot level is refused as T3 and is not reclassified." % b.name)


def _t3_columns(decl):
    ab = _split_factors(decl)
    if ab is None:
        return SKIP
    a, b = ab
    problems = []
    if a.column in decl.id_columns:
        problems.append("whole-plot factor column %r is a hierarchy ID column" % a.column)
    if b.column == decl.top.id_column:
        problems.append("subplot factor column %r is the ID column of %r"
                        % (b.column, decl.top.name))
    if not problems:
        return None
    return Fail("; ".join(problems),
                "A whole-plot factor whose labels identify the whole plots has one whole plot "
                "per level, so no replication. The subplot factor may label the subplot "
                "units (e.g. position) but not the whole plots.",
                "Give the factor its own column.")


def _t3_subplot_not_exchangeable(decl):
    ab = _split_factors(decl)
    if ab is None:
        return SKIP
    if not decl.bottom.exchangeable:   # False, or None for a one-level hierarchy
        return None
    return Fail("subplot level %r declared exchangeable: true, while subplot factor %r "
                "is applied to it" % (decl.bottom.name, ab[1].name),
                "Exchangeable means interchangeable subsamples with no systematic meaning. "
                "T3 subplot units each carry a level of the subplot factor, so they are "
                "not exchangeable; the declaration contradicts itself.",
                "Remove exchangeable from the subplot level, or set it to false.")


def _t3_comparisons(decl):
    ab = _split_factors(decl)
    if ab is None:
        return SKIP
    if decl.comparisons:
        return None
    return Fail("comparisons: []",
                "T3 exists to answer comparisons of A, B or A x B; none was declared.",
                "Declare at least one comparison (overall, pairwise or interaction) of %r "
                "and/or %r." % (ab[0].name, ab[1].name))


T3_CONDITIONS = (
    Condition("T3.split_plot_roles", "split_plot",
              "split_plot names the whole-plot factor A and subplot factor B, and they are "
              "the only two treatments", _t3_roles),
    Condition("T3.two_level_hierarchy", "hierarchy",
              "the hierarchy is exactly whole-plot unit > subplot unit", _t3_two_levels),
    Condition("T3.whole_plot_factor_on_whole_plots", "application_level",
              "A is applied to the top level (whole-plot units)", _t3_whole_plot_level),
    Condition("T3.subplot_factor_on_subplots", "application_level",
              "B is applied to the bottom level (subplot units)", _t3_subplot_level),
    Condition("T3.whole_plot_factor_applied_not_inherent", "assignment",
              "A's assignment method is not 'inherent' (B may be inherent, e.g. position)",
              _t3_whole_plot_assigned),
    Condition("T3.whole_plot_replicated", "replication",
              "A has >= 2 levels and replicates_per_level >= 2 whole plots",
              _t3_whole_plot_replication),
    Condition("T3.whole_plot_balance", "balance",
              "A levels x A replicates_per_level = whole-plot count", _t3_whole_plot_balance),
    Condition("T3.subplot_complete", "balance",
              "B has >= 2 levels; subplot count_per_parent = B levels; B replicates_per_level "
              "= whole-plot count", _t3_subplot_structure),
    Condition("T3.factor_columns", "inconsistent_declaration",
              "A's column is not a hierarchy ID column; B's column is not the whole-plot "
              "ID column", 
              _t3_columns),
    Condition("T3.subplot_not_exchangeable", "exchangeability",
              "the subplot level is not declared exchangeable", _t3_subplot_not_exchangeable),
    Condition("T3.no_blocking", "blocking",
              "no nuisance factor has role block", _no_blocks("T3")),
    Condition("T3.comparisons", "comparison",
              "at least one comparison of A, B or A x B", _t3_comparisons),
)


CONDITIONS = {"T1": T1_CONDITIONS, "T2": T2_CONDITIONS, "T3": T3_CONDITIONS}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def match(decl: Declaration) -> MatchResult:
    """Evaluate the claimed template's conditions on a parsed declaration."""
    claimed = decl.claimed_template
    if claimed not in SUPPORTED_TEMPLATES:
        refusal = Refusal(
            category="unknown_template", declared="claimed_template: %r" % (claimed,),
            requirement="claimed_template is exactly one of T1, T2, T3",
            reason="Stratum v1 supports only three narrow templates. It does not guess "
                   "which one an unknown or differently spelled name means.",
            remedy="Claim T1 (nested variance components, no treatment), T2 (one treatment "
                   "on replicated top-level units with subsampling) or T3 (balanced "
                   "split-plot), whichever describes how the experiment was run. " + LME4)
        return MatchResult(claimed, None, decl, (), (refusal,))
    results = []
    for cond in CONDITIONS[claimed]:
        outcome = cond.check(decl)
        if outcome is None:
            results.append(ConditionResult(cond.id, cond.requirement, "pass"))
        elif outcome is SKIP:
            results.append(ConditionResult(cond.id, cond.requirement, "not_evaluated"))
        else:
            refusal = Refusal(category=cond.category, declared=outcome.declared,
                              requirement=cond.requirement, reason=outcome.reason,
                              remedy=outcome.remedy, condition=cond.id)
            results.append(ConditionResult(cond.id, cond.requirement, "fail", refusal))
    refusals = tuple(r.refusal for r in results if r.refusal is not None)
    # A check skips only when a prerequisite condition failed. A skip without any failure
    # would mean a condition was never evaluated on a matched declaration: fail closed.
    if not refusals and any(r.status != "pass" for r in results):
        raise RuntimeError("condition skipped without a failed prerequisite: %s"
                           % [r.id for r in results if r.status != "pass"])
    return MatchResult(claimed, None if refusals else claimed, decl, tuple(results), refusals)


def evaluate(source: Union[str, Path, dict]) -> MatchResult:
    """Parse and match in one step. source: a file Path, YAML text, or a loaded dict."""
    parsed = parse_declaration(source) if isinstance(source, dict) else load_declaration(source)
    if not parsed.ok:
        claimed = None
        if isinstance(source, dict) and isinstance(source.get("claimed_template"), str):
            claimed = source["claimed_template"]
        return MatchResult(claimed, None, None, (), parsed.refusals)
    return match(parsed.declaration)
