"""WP4: the Markdown report, rendered from a results.json document alone (D-076).

`render(doc)` takes the parsed results.json and returns the report text. It never sees the
analysis objects. Every number and every data-dependent text is read through `Src`, which
records the results.json path it came from. With `trace=True` each such value is wrapped
in \\x02 ... \\x03 so that a test can check that every traced value equals the value at its
path and that the static template text carries no data-dependent digit.

The plain-language explanation of each category comes from resources/explanations.yaml and
is inserted verbatim (D-075); a missing one is shown as pending. No explanation
wording lives in this module.
"""
from typing import Iterable, List, Optional

TRACE_OPEN, TRACE_CLOSE = "\x02", "\x03"


def fmt(v, sig: int = 4) -> str:
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, float):
        if v == 0:
            return "0"
        if abs(v) < 1e-4 or abs(v) >= 1e6:
            return "%.*e" % (sig - 1, v)
        return "%.*g" % (sig, v)
    return str(v)


def cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


class Src:
    """Read values from the results document by path, recording each one rendered."""

    def __init__(self, doc: dict, trace: bool = False):
        self.doc = doc
        self.trace = trace
        self.used: List[tuple] = []

    def get(self, *path, default=None):
        cur = self.doc
        for p in path:
            if isinstance(cur, dict):
                if p not in cur:
                    return default
                cur = cur[p]
            elif isinstance(cur, list):
                if not isinstance(p, int) or p >= len(cur):
                    return default
                cur = cur[p]
            else:
                return default
        return cur

    def _mark(self, path, value, s: str) -> str:
        if self.trace:
            self.used.append((tuple(path), value, s))
            return TRACE_OPEN + s + TRACE_CLOSE
        return s

    def num(self, *path, sig: int = 4) -> str:
        v = self.get(*path)
        return self._mark(path, v, fmt(v, sig))

    def key(self, path, k, in_cell: bool = True) -> str:
        """A dictionary key used as text (a stratum or level name)."""
        if self.trace:
            self.used.append((tuple(path) + ("<key>",), k, str(k)))
            s = cell(k) if in_cell else str(k)
            return TRACE_OPEN + s + TRACE_CLOSE
        return cell(k) if in_cell else str(k)

    def text(self, *path, in_cell: bool = False) -> str:
        v = self.get(*path)
        s = "-" if v is None else str(v)
        return self._mark(path, v, cell(s) if in_cell else s)


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------

def _explanation_lines(S: Src, path, indent="") -> List[str]:
    status = S.get(*path, "status")
    if status == "written":
        out = [indent + "- **Explanation:** " + S.text(*path, "text")]
        if S.get(*path, "same_as"):
            out[-1] += " _(shared with `" + S.text(*path, "same_as") + "`)_"
        return out
    return [indent + "- **Explanation:** _" + S.text(*path, "pending_label") + "_"]


def _finding_block(S: Src, base) -> List[str]:
    L = ["#### `" + S.text(*base, "code") + "` (" + S.text(*base, "severity") + ", stage "
         + S.text(*base, "stage") + ")", ""]
    L += _explanation_lines(S, base + ("explanation",))
    L.append("- **Technical detail:** " + S.text(*base, "message"))
    for j, _ in enumerate(S.get(*base, "wp1_refusals", default=[]) or []):
        rp = base + ("wp1_refusals", j)
        L.append("- WP1 refusal `" + S.text(*rp, "category") + "`"
                 + (" (" + S.text(*rp, "condition") + ")" if S.get(*rp, "condition") else ""))
        L += _explanation_lines(S, rp + ("explanation",), indent="  ")
        L.append("  - Declared: " + S.text(*rp, "declared"))
        L.append("  - Requirement: " + S.text(*rp, "requirement"))
        L.append("  - Why: " + S.text(*rp, "reason"))
        if S.get(*rp, "remedy"):
            L.append("  - To proceed: " + S.text(*rp, "remedy"))
    L.append("")
    return L


def _units_text(S: Src, base) -> str:
    per = S.get(*base, "independent_units", "per_level")
    if isinstance(per, dict):
        parts = [S.num(*base, "independent_units", "per_level", k) for k in per]
        names = [S.key(base + ("independent_units", "per_level"), k) for k in per]
        return ", ".join("%s: %s" % (n, p) for n, p in zip(names, parts)) + \
            " independent " + S.text(*base, "independent_units", "level") + " units per level"
    if S.get(*base, "independent_units", "total") is not None:
        return S.num(*base, "independent_units", "total") + " independent " + \
            S.text(*base, "independent_units", "level") + " units"
    return "-"


def _estimate_table(S: Src, base) -> List[str]:
    L = ["| Contrast | Estimate | 95% interval | SE | df | Error term | Independent units "
         "| t | p |", "|---|---|---|---|---|---|---|---|---|"]
    for j, _ in enumerate(S.get(*base, "estimates", default=[])):
        e = base + ("estimates", j)
        approx = " _(approximate)_" if S.get(*e, "approximate") else ""
        L.append("| " + S.text(*e, "contrast", in_cell=True) + approx + " | "
                 + S.num(*e, "estimate") + " | " + S.num(*e, "lower") + " to "
                 + S.num(*e, "upper") + " | " + S.num(*e, "se") + " | " + S.num(*e, "df")
                 + " | " + S.text(*e, "error_term", in_cell=True) + " | "
                 + S.num(*e, "independent_units") + " | " + S.num(*e, "t") + " | "
                 + S.num(*e, "p", sig=3) + " |")
    return L


def _anova_table(S: Src, base, order: Iterable[str]) -> List[str]:
    L = ["| Source | df | SS | MS | E[MS] | Error term | F | p |",
         "|---|---|---|---|---|---|---|---|"]
    table = S.get(*base) or {}
    for key in order:
        if key not in table or not isinstance(table[key], dict):
            continue
        r = base + (key,)
        L.append("| " + S.text(*r, "source", in_cell=True) + " | " + S.num(*r, "df") + " | "
                 + S.num(*r, "ss", sig=6) + " | " + S.num(*r, "ms", sig=6) + " | "
                 + (S.text(*r, "ems", in_cell=True) if S.get(*r, "ems") else "-") + " | "
                 + (S.text(*r, "error_term", in_cell=True) if S.get(*r, "error_term") else "-")
                 + " | " + S.num(*r, "F") + " | " + S.num(*r, "p", sig=3) + " |")
    return L


ANOVA_ORDER = {"T1": ("A", "B", "residual", "total"),
               "T2": ("treatment", "block", "unit", "sub1", "sub2", "total"),
               "T3": ("A", "wholeplot_error", "B", "AB", "subplot_error", "total")}


def _qq_plot(S: Src, stratum: str) -> List[str]:
    """A fixed-size text plot of the stored normal-quantile pairs (D-044 reading 4)."""
    nq = S.get("diagnostics", stratum, "studentized_residuals", "normal_quantiles")
    disp = ("diagnostics_display", stratum)
    if not nq or S.get(*disp) is None:
        return []
    xs, ys = nq["theoretical"], nq["internally_studentized_sorted"]
    W, H = 41, 13
    lo = min(S.get(*disp, "x_min"), S.get(*disp, "y_min"))
    hi = max(S.get(*disp, "x_max"), S.get(*disp, "y_max"))
    span = (hi - lo) or 1.0
    grid = [[" "] * W for _ in range(H)]
    for c in range(W):                       # reference line y = x
        v = lo + span * c / (W - 1)
        r = int(round((hi - v) / span * (H - 1)))
        if 0 <= r < H:
            grid[r][c] = "."
    for x, y in zip(xs, ys):
        c = int(round((x - lo) / span * (W - 1)))
        r = int(round((hi - y) / span * (H - 1)))
        grid[r][c] = "o"
    rows = ["  |" + "".join(row) for row in grid]
    return (["Normal quantile plot (" + S.num(*disp, "n") + " points; horizontal: normal "
             "quantile, " + S.num(*disp, "x_min") + " to " + S.num(*disp, "x_max")
             + "; vertical: internally studentized residual, " + S.num(*disp, "y_min")
             + " to " + S.num(*disp, "y_max") + "; dots mark the line y = x):", "",
             "```"] + rows + ["  +" + "-" * W, "```", ""])


def _diagnostics(S: Src) -> List[str]:
    diag = S.get("diagnostics")
    if not diag:
        return ["Diagnostics were not computed: " + (
            "the design was refused, and diagnosing a structure that cannot be analyzed "
            "would mean nothing (D-044 reading 5)."
            if S.get("decision", "evidence_decision") == "REFUSE" else "none applicable."), ""]
    L = []
    for stratum in diag:
        base = ("diagnostics", stratum)
        L += ["### " + S.key(("diagnostics",), stratum), ""]
        for name, title in (("brown_forsythe", "Brown-Forsythe (spread of unit means)"),
                            ("sd_ratio", "Largest-to-smallest SD of unit means"),
                            ("studentized_residuals", "Externally studentized residuals")):
            d = base + (name,)
            if S.get(*d) is None:
                continue
            if S.get(*d, "not_applicable"):
                L.append("- " + title + ": not applicable (" + S.text(*d, "reason") + ").")
                continue
            if not S.get(*d, "available"):
                L.append("- " + title + ": unavailable (" + S.text(*d, "reason") + ").")
                continue
            warn = " **(warning)**" if S.get(*d, "warn") else ""
            if name == "brown_forsythe":
                L.append("- " + title + ": F = " + S.num(*d, "F") + " on (" + S.num(*d, "df", 0)
                         + ", " + S.num(*d, "df", 1) + ") df, p = " + S.num(*d, "p", sig=3)
                         + "; warning at " + S.text(*d, "threshold") + "." + warn)
            elif name == "sd_ratio":
                L.append("- " + title + ": " + S.num(*d, "ratio") + "; warning at "
                         + S.text(*d, "threshold") + "." + warn)
            else:
                flagged = [u for u in S.get(*d, "units") or [] if u.get("flagged")]
                L.append("- " + title + " (model " + S.text(*d, "model") + ", residual df "
                         + S.num(*d, "residual_df") + "): largest |t| = "
                         + S.num(*d, "max_abs_external") + "; warning at "
                         + S.text(*d, "threshold") + "." + warn)
                for i, u in enumerate(S.get(*d, "units") or []):
                    if u.get("flagged"):
                        L.append("  - flagged: " + S.text(*d, "units", i, "unit") + ", t = "
                                 + S.num(*d, "units", i, "external"))
                del flagged
        L.append("")
        L += _qq_plot(S, stratum)
    return L


def _missing_sites(S: Src) -> List[str]:
    """D-021: each unit's surviving site counts, F_site and 1/F_site, with the exact label."""
    M = ("evidence", "missing_sites")
    if not S.get(*M, "exception_applies"):
        return []
    L = ["### Missing sites: count-only precision information (D-021)", "",
         S.text(*M, "label"), "",
         "| Unit | Surviving sites per " + S.text("declaration", "hierarchy", -2 + len(
             S.get("declaration", "hierarchy")), "name") + " (declared "
         + S.num(*M, "declared_per_wafer") + ") | F_site | 1/F_site |", "|---|---|---|---|"]
    for u in S.get(*M, "units"):
        b = M + ("units", u)
        counts = ", ".join(S.num(*b, "site_counts", k)
                           for k in range(len(S.get(*b, "site_counts"))))
        L.append("| " + S.key(M + ("units",), u) + " | " + counts + " | "
                 + S.text(*b, "F_site", "exact") + " | "
                 + S.text(*b, "precision_lower_bound", "exact") + " = "
                 + S.num(*b, "precision_lower_bound") + " |")
    return L + [""]


def _scenario_value(S: Src, sc) -> str:
    st = S.get(*sc, "status")
    if st == "identified":
        return S.num(*sc, "se")
    if st == "limited":
        return "between " + S.num(*sc, "se_lower") + " and " + S.num(*sc, "se_upper") + \
            " (limited)"
    if st == "lower_bound":
        return "at least " + S.num(*sc, "se_lower")
    return "not estimable"


def _scenario_range(S: Src, sc) -> str:
    if S.get(*sc, "plausible_se") is not None:
        return S.num(*sc, "plausible_se", "p2_5") + " to " + S.num(*sc, "plausible_se", "p97_5")
    if S.get(*sc, "plausible_se_lower") is not None:
        out = "lower bound " + S.num(*sc, "plausible_se_lower", "p2_5") + " to " + \
            S.num(*sc, "plausible_se_lower", "p97_5")
        if S.get(*sc, "plausible_se_upper") is not None:
            out += "; upper bound " + S.num(*sc, "plausible_se_upper", "p2_5") + " to " + \
                S.num(*sc, "plausible_se_upper", "p97_5")
        return out
    return "-"


def _allocation(S: Src) -> List[str]:
    A = ("allocation",)
    st = S.get(*A, "status")
    if st not in ("available", "planning"):
        return ["Allocation analysis: **" + S.text(*A, "status") + "**: " + S.text(*A, "reason"),
                ""]
    L = []
    if st == "planning":
        L += ["> " + S.text(*A, "planning_label"), ""]
        if S.get(*A, "unit_note"):
            L += [S.text(*A, "unit_note"), ""]
    L += ["Components used: " + S.text(*A, "components_method") + ".", "",
          "| Component | Estimate | df | Status |", "|---|---|---|---|"]
    for j, _ in enumerate(S.get(*A, "components")):
        c = A + ("components", j)
        L.append("| " + S.text(*c, "label", in_cell=True) + " | " + S.num(*c, "estimate")
                 + " | " + S.num(*c, "df") + " | "
                 + ("combined component (not separately identifiable)" if S.get(*c, "merged")
                    else ("estimated" if S.get(*c, "estimable") else "not estimable"))
                 + " |")
    L += ["", "Uncertainty: " + S.text(*A, "plausible_values", "method") + "; "
          + S.num(*A, "plausible_values", "draws") + " draws, fixed seed; "
          + S.text(*A, "plausible_values", "label") + ".", ""]
    if S.get(*A, "block_note"):
        L += [S.text(*A, "block_note"), ""]
    for i, _ in enumerate(S.get(*A, "comparisons")):
        C = A + ("comparisons", i)
        L += ["### Standard error of " + S.text(*C, "comparison_of"), "",
              "Formula: `" + S.text(*C, "formula") + "`", "",
              "| Design | Standard error | Plausible range (95%) | Adds | Added measurements "
              "| Error df | Status |", "|---|---|---|---|---|---|---|"]
        for j, _ in enumerate(S.get(*C, "scenarios")):
            sc = C + ("scenarios", j)
            label = S.text(*sc, "label", in_cell=True)
            if not S.get(*sc, "balanced"):
                label += " _(unbalanced)_"
            L.append("| " + label + " | " + _scenario_value(S, sc) + " | "
                     + _scenario_range(S, sc) + " | " + S.text(*sc, "added_units", in_cell=True)
                     + " | " + S.num(*sc, "added_measurements") + " | "
                     + S.num(*sc, "error_df") + " | " + S.text(*sc, "status") + " |")
        L.append("")
        seen_notes = []
        for j, _ in enumerate(S.get(*C, "scenarios")):
            sc = C + ("scenarios", j)
            if S.get(*sc, "note"):
                L.append("- " + S.text(*sc, "label") + ": " + S.text(*sc, "note"))
            note = S.get(*sc, "bounds_note")
            if note and S.get(*sc, "status") != "identified" and note not in seen_notes:
                seen_notes.append(note)
                L.append("- " + S.text(*sc, "status") + ": " + S.text(*sc, "bounds_note"))
        R = C + ("ranking",)
        if S.get(*R, "assessed"):
            ids = S.get(*R, "candidates")
            L.append("- Which single addition lowers the standard error most, as a share of "
                     "the " + S.num(*R, "draws") + " plausible values: "
                     + "; ".join(S.text(*R, "candidate_labels", c) + " "
                                 + S.num(*R, "shares_percent", c) + "%" for c in ids)
                     + ". A ranking is called robust at " + S.num(*R, "robust_threshold_wins")
                     + " wins.")
        else:
            L.append("- Ranking: " + S.text(*R, "reason") + ".")
        for key in ("robust_conclusion", "ranking_statement", "floor_statement"):
            if S.get(*C, key):
                L.append("- **" + S.text(*C, key) + "**")
        L.append("")
    L += [S.text(*A, "current_vs_analysis") if S.get(*A, "current_vs_analysis") else "",
          "", "Not implemented: " + S.text(*A, "not_implemented") + ".", ""]
    return L


def _reassignment(S: Src) -> List[str]:
    R = ("reassignment",)
    st = S.get(*R, "status")
    if st == "not_applicable":
        return ["Not applicable: " + S.text(*R, "reason") + ".", ""]
    if S.get(*R, "suggestions") is None:
        return ["Not produced: " + S.text(*R, "reason") + ".", ""]
    L = []
    if S.get(*R, "note"):
        L += [S.text(*R, "note"), ""]
    for i, _ in enumerate(S.get(*R, "suggestions")):
        G = R + ("suggestions", i)
        L += ["### Factor `" + S.text(*G, "factor") + "`", ""]
        if S.get(*G, "status") != "produced":
            L += ["Not produced: " + S.text(*G, "reason"), ""]
            continue
        L += ["A crossed, randomized assignment of **" + S.text(*G, "treatment") + "** to **"
              + S.text(*G, "factor") + "**: " + S.num(*G, "replicates_per_level")
              + " units per treatment level (declared: "
              + S.num(*G, "declared_replicates_per_level") + "; extra per level: "
              + S.num(*G, "extra_units_per_level") + "), " + S.num(*G, "units_per_cell")
              + " in every treatment x " + S.text(*G, "factor") + " cell, "
              + S.num(*G, "total_units") + " units in all, randomized within each "
              + S.text(*G, "factor") + " level (seed " + S.num(*G, "seed") + ").", "",
              S.text(*G, "plan_note"), "",
              "| Planned unit | " + S.text(*G, "factor") + " | Order within level | "
              + S.text(*G, "treatment") + " |", "|---|---|---|---|"]
        for j, _ in enumerate(S.get(*G, "plan")):
            p = G + ("plan", j)
            L.append("| " + S.text(*p, "planned_unit") + " | " + S.text(*p, "factor_level")
                     + " | " + S.num(*p, "slot") + " | " + S.text(*p, "treatment") + " |")
        E = G + ("estimates",)
        L += ["", "**What the revised design would estimate:** the contrasts "
              + ", ".join(S.text(*E, "contrasts", k) for k in range(len(S.get(*E, "contrasts"))))
              + ", adjusted for " + S.text(*G, "factor") + "; tested against "
              + S.text(*E, "error_term") + " on (" + S.num(*E, "num_df") + ", "
              + S.num(*E, "den_df") + ") df; " + S.text(*E, "block") + "; and "
              + S.text(*E, "unit_variation") + ".", "",
              "- Revised declaration matches the template: " + S.num(*G, "revised_match", "matched")
              + " (" + S.text(*G, "revised_match", "template") + ").",
              "- Exact estimability check on the planned layout (D-045): "
              + S.num(*G, "layout_check", "verified") + "; table proportional: "
              + S.num(*G, "layout_check", "proportional") + ".",
              "- Assumption: " + S.text(*G, "assumption") + "."]
        if S.get(*G, "removed_note"):
            L.append("- " + S.text(*G, "removed_note"))
        P = G + ("precision",)
        pst = S.get(*P, "status")
        if pst == "identified":
            L.append("- **Expected precision** (" + S.text(*P, "label") + "): standard error "
                     + S.num(*P, "se") + " (95% interval " + S.num(*P, "se_interval", 0) + " to "
                     + S.num(*P, "se_interval", 1) + ", " + S.text(*P, "se_interval_method")
                     + "); expected 95% half width " + S.num(*P, "expected_half_width")
                     + " on " + S.num(*P, "error_df") + " df.")
            L.append("  - From the fitted components: " + S.num(*P, "se_from_components")
                     + "; " + S.text(*P, "formula") + ".")
        elif pst == "lower_bound":
            L.append("- **Expected precision:** standard error at least "
                     + S.num(*P, "se_lower") + "; " + S.text(*P, "note"))
        else:
            L.append("- **Expected precision:** unavailable; " + S.text(*P, "reason") + ".")
        L.append("")
    return L


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _render(doc: dict, trace: bool):
    S = Src(doc, trace)
    tmpl = S.get("decision", "template") or S.get("declaration", "claimed_template")
    L = ["# Stratum report: " + S.text("provenance", "inputs", "declaration", "path"), ""]
    if S.get("synthetic"):
        L += ["> **SYNTHETIC DATA.** " + S.text("data_label"), ""]
    else:
        L += ["> Data: " + S.text("data_label"), ""]
    L += ["Generated from `results.json` by " + S.text("generated_by") + ". Do not edit this "
          "file; regenerate it.", "",
          "- Claimed template: **" + S.text("declaration", "claimed_template") + "**",
          "- Evidence decision: **" + S.text("decision", "evidence_decision") + "**",
          "- Analysis produced: **" + S.num("decision", "analyzed") + "**",
          "- Plain-language explanations available: **"
          + S.num("explanations", "required_written") + " of "
          + S.num("explanations", "required") + "** required categories; any pending one is "
          "marked where it occurs.", ""]
    if S.get("declaration", "description"):
        L += ["Declaration: " + S.text("declaration", "description"), ""]

    # 1. Summary
    L += ["## 1. Summary", "", "### What the data support", ""]
    supported = False
    for i, c in enumerate(S.get("comparisons", default=[])):
        if not c["status"].startswith("analyzed"):
            continue
        supported = True
        base = ("comparisons", i)
        t = base + ("test",)
        line = "- **" + S.text(*base, "id") + "**"
        if S.get(*t, "F") is not None:
            line += ": F = " + S.num(*t, "F") + " on (" + S.num(*t, "num_df") + ", " \
                + S.num(*t, "den_df") + ") df against " + S.text(*t, "error_term") \
                + ", p = " + S.num(*t, "p", sig=3)
        if c["status"] == "analyzed_approximate":
            line += " _(approximate)_"
        L.append(line + ".")
        for j, _ in enumerate(c.get("estimates", [])):
            e = base + ("estimates", j)
            L.append("  - " + S.text(*e, "contrast") + ": " + S.num(*e, "estimate")
                     + ", 95% interval " + S.num(*e, "lower") + " to " + S.num(*e, "upper")
                     + " (interval includes 0: " + S.num(*e, "interval_includes_zero") + ").")
    if tmpl == "T1" and S.get("decision", "analyzed"):
        supported = True
        L.append("- Variance components at each level, with intervals (Section 7). T1 has no "
                 "treatment comparison.")
    if not supported:
        L.append("- No comparison is supported. No estimate, test or interval is reported for "
                 "any declared comparison.")
    for code_key, what in (("warning_codes", "warnings"), ("caveat_codes", "report caveats")):
        codes = S.get("summary", code_key) or []
        if codes and S.get("decision", "analyzed"):
            L.append("- Analyzed with " + what + ": " + ", ".join(
                "`" + S.text("summary", code_key, k) + "`" for k in range(len(codes)))
                + " (Section 3).")
    L += ["", "### What the data do not support", ""]
    unsupported = False
    for i, c in enumerate(S.get("comparisons", default=[])):
        if c["status"] != "refused":
            continue
        unsupported = True
        base = ("comparisons", i)
        L.append("- **" + S.text(*base, "id") + "**: refused (" + ", ".join(
            "`" + S.text(*base, "refusal_codes", k) + "`"
            for k in range(len(c.get("refusal_codes", [])))) + ").")
    if not S.get("comparisons") and not S.get("decision", "analyzed"):
        unsupported = True
        L.append("- The design was refused (" + ", ".join(
            "`" + S.text("summary", "refusal_codes", k) + "`"
            for k in range(len(S.get("summary", "refusal_codes") or []))) + ").")
    if S.get("allocation", "status") in ("withheld",):
        unsupported = True
        L.append("- Allocation analysis: withheld (Section 5).")
    if not unsupported:
        L.append("- Nothing was refused.")
    L += ["", "### What to do next", ""]
    steps = S.get("summary", "next_steps") or []
    for k, _ in enumerate(steps):
        L.append("- " + S.text("summary", "next_steps", k, "text"))
    if S.get("summary", "warning_codes") or S.get("summary", "caveat_codes"):
        L.append("- Read the warnings and caveats in Section 3, and the assumptions in "
                 "Section 4, before relying on the result.")
    elif not steps:
        L.append("- No action is required by the checks. Read the assumptions in Section 4 "
                 "before relying on the result.")
    pend = S.get("summary", "pending_in_report") or []
    if pend:
        L.append("- Explanations still pending for categories in this report: " + ", ".join("`" + S.text("summary", "pending_in_report", k) + "`"
                                        for k in range(len(pend))) + ".")
    L.append("")

    # 2. Comparisons
    L += ["## 2. Comparisons", ""]
    if not S.get("comparisons"):
        L += ["No comparison is declared" + (" (T1 has no treatment)." if tmpl == "T1" else ".")
              , ""]
    for i, c in enumerate(S.get("comparisons", default=[])):
        base = ("comparisons", i)
        L += ["### " + S.text(*base, "id"), ""]
        L.append("- Kind: " + S.text(*base, "kind") + "; factor(s): " + ", ".join(
            S.text(*base, "factors", k) for k in range(len(c["factors"])))
            + ("; role: " + S.text(*base, "role") if S.get(*base, "role") else ""))
        if S.get(*base, "description"):
            L.append("- Description: " + S.text(*base, "description"))
        L.append("- Experimental unit: " + S.text(*base, "experimental_unit")
                 + "; independent units: " + _units_text(S, base))
        if S.get(*base, "units_note"):
            L.append("- " + S.text(*base, "units_note"))
        L.append("- Status: **" + S.text(*base, "status") + "**")
        t = base + ("test",)
        if S.get(*t) is not None:
            L.append("- Test: F = " + S.num(*t, "F") + " on (" + S.num(*t, "num_df") + ", "
                     + S.num(*t, "den_df") + ") df, error term: " + S.text(*t, "error_term")
                     + ", p = " + S.num(*t, "p", sig=3))
            if S.get(*t, "note"):
                L.append("  - " + S.text(*t, "note"))
        if c.get("estimates"):
            L += [""] + _estimate_table(S, base)
        if c["status"] == "refused":
            L.append("- Refused for: " + ", ".join(
                "`" + S.text(*base, "refusal_codes", k) + "`"
                for k in range(len(c.get("refusal_codes", [])))) + " (Section 3). No estimate, "
                "test or interval is reported.")
        L.append("")

    # 3. Findings
    L += ["## 3. Refusals, warnings, notes and caveats", ""]
    any_f = False
    for sev, title in (("refuse", "Refusals"), ("warn", "Warnings"), ("note", "Notes")):
        idx = [i for i, f in enumerate(S.get("findings", default=[])) if f["severity"] == sev]
        if not idx:
            continue
        any_f = True
        L += ["### " + title, ""]
        for i in idx:
            L += _finding_block(S, ("findings", i))
    if S.get("caveats"):
        any_f = True
        L += ["### Report caveats (they do not change the evidence decision)", ""]
        for i, _ in enumerate(S.get("caveats")):
            base = ("caveats", i)
            L += ["#### `" + S.text(*base, "code") + "` (caveat)", ""]
            L += _explanation_lines(S, base + ("explanation",))
            L += ["- **Technical detail:** " + S.text(*base, "message"), ""]
    if not any_f:
        L += ["None.", ""]

    # 4. Assumptions and diagnostics
    L += ["## 4. Assumptions and diagnostics", "",
          "| Assumption | How Stratum handles it | Status |", "|---|---|---|"]
    for i, _ in enumerate(S.get("assumptions", default=[])):
        a = ("assumptions", i)
        L.append("| " + S.text(*a, "assumption", in_cell=True) + " | "
                 + S.text(*a, "handling", in_cell=True) + " | " + S.text(*a, "status") + " |")
    L.append("")
    L += _missing_sites(S)
    L += _diagnostics(S)

    # 5. Allocation
    L += ["## 5. Allocation analysis", ""] + _allocation(S)

    # 6. Reassignment
    L += ["## 6. Reassignment suggestion", ""] + _reassignment(S)

    # 7. Full analysis
    L += ["## 7. Full analysis", ""]
    if not S.get("decision", "analyzed"):
        L += ["No analysis was produced: the evidence checks refused the design, and refusal "
              "is a successful outcome (brief Section 8).", ""]
    else:
        L += ["### ANOVA", ""] + _anova_table(S, ("analysis", "anova"),
                                              ANOVA_ORDER.get(tmpl, ())) + [""]
        if S.get("analysis", "naive_anova"):
            L += ["### Correct analysis and the naive single-error analysis, side by side", "",
                  "| Source | Correct: error term | Correct: df | Correct: F | Correct: p "
                  "| Naive: df | Naive: F | Naive: p |", "|---|---|---|---|---|---|---|---|"]
            for key in ("A", "B", "AB"):
                c, n = ("analysis", "anova", key), ("analysis", "naive_anova", key)
                if S.get(*c) is None:
                    continue
                L.append("| " + S.text(*c, "source", in_cell=True) + " | "
                         + S.text(*c, "error_term", in_cell=True) + " | (" + S.num(*c, "num_df")
                         + ", " + S.num(*c, "den_df") + ") | " + S.num(*c, "F") + " | "
                         + S.num(*c, "p", sig=3) + " | (" + S.num(*n, "num_df") + ", "
                         + S.num(*n, "den_df") + ") | " + S.num(*n, "F") + " | "
                         + S.num(*n, "p", sig=3) + " |")
            L += ["", "- " + S.text("analysis", "naive_anova", "A", "note"),
                  "- " + S.text("analysis", "naive_anova", "note"), ""]
        vc = S.get("analysis", "variance_components") or {}
        if vc:
            L += ["### Variance components", "",
                  "Upper-component Satterthwaite intervals are approximate. WP6 found severe "
                  "undercoverage for some upper components, including the T1 run component, "
                  "and errors in both directions for the middle component. These intervals "
                  "are not reliably calibrated across the validated grid. See VALIDATION.md "
                  "in the repository for measured coverage and availability (D-097, D-099).", "",
                  "| Component | Method of moments | REML | SD | 95% interval | Interval method "
                  "| % of total |", "|---|---|---|---|---|---|---|"]
            for k in vc:
                v = ("analysis", "variance_components", k)
                mom = S.num(*v, "mom") + (" (negative; truncated to 0)" if S.get(*v, "negative")
                                          else "")
                iv = (S.num(*v, "interval_lower") + " to " + S.num(*v, "interval_upper")
                      if S.get(*v, "interval_available") else "not available")
                L.append("| " + S.text(*v, "label", in_cell=True) + " | " + mom + " | "
                         + S.num(*v, "reml") + " | " + S.num(*v, "sd_mom") + " | " + iv + " | "
                         + S.text(*v, "interval_method", in_cell=True) + " | "
                         + S.num(*v, "percent_of_total") + " |")
            L.append("")
        se = S.get("analysis", "stratum_expectations") or {}
        if se:
            L += ["Exact 95% intervals for each stratum's expected mean square (D-060 item 3):",
                  "", "| Stratum | df | MS | 95% interval for E[MS] |", "|---|---|---|---|"]
            for k in se:
                v = ("analysis", "stratum_expectations", k)
                L.append("| " + S.text(*v, "label", in_cell=True) + " | " + S.num(*v, "df")
                         + " | " + S.num(*v, "ms", sig=6) + " | " + S.num(*v, "lower") + " to "
                         + S.num(*v, "upper") + " |")
            L.append("")
        if S.get("analysis", "reml", "fit"):
            f = ("analysis", "reml", "fit")
            L += ["REML cross-check: " + S.text(*f, "method") + ". Strata pooled: "
                  + (", ".join("+".join(b) for b in S.get(*f, "pooled"))
                     if S.get(*f, "pooled") else "none") + ".", ""]
        if S.get("analysis", "reml", "fit", "likelihood_unavailable_reason"):
            L += [S.text("analysis", "reml", "fit", "likelihood_unavailable_reason"), ""]
        if any(e.get("interval_available") is False for e in
               (S.get("analysis", "estimates") or {}).values()):
            L += ["Affected intervals and tests are unavailable because their error variance "
                  "is zero; retained point estimates are descriptive (D-103).", ""]
        fits = ("analysis", "fits")
        if S.get(*fits):
            L.append("Fits: " + S.num(*fits, "boundary_count") + " boundary, "
                     + S.num(*fits, "degenerate_count") + " degenerate, "
                     + S.num(*fits, "failed_count") + " failed. " + S.text(*fits, "note"))
            L.append("")
        for k, _ in enumerate(S.get("analysis", "notes") or []):
            L.append("- " + S.text("analysis", "notes", k))
        L.append("")

    # 8. Evidence stages
    L += ["## 8. Evidence checks", "", "| Stage | Check | Status | Note |", "|---|---|---|---|"]
    for i, _ in enumerate(S.get("stages", default=[])):
        s = ("stages", i)
        L.append("| " + S.text(*s, "id") + " | " + S.text(*s, "title", in_cell=True) + " | "
                 + S.text(*s, "status") + " | "
                 + (S.text(*s, "reason", in_cell=True) if S.get(*s, "reason") else "") + " |")
    if S.get("planning", "planning_only_findings"):
        L += ["", "Planning-only checks (D-081; they cannot change the decision):", ""]
        for i, _ in enumerate(S.get("planning", "planning_only_findings")):
            p = ("planning", "planning_only_findings", i)
            L.append("- `" + S.text(*p, "code") + "` (" + S.text(*p, "severity") + "): "
                     + S.text(*p, "message"))
    L.append("")

    # 9. Provenance
    P = ("provenance",)
    L += ["## 9. Provenance", "", "| Input | Path | SHA-256 | Bytes |", "|---|---|---|---|"]
    for k in ("declaration", "data", "explanations"):
        L.append("| " + k + " | `" + S.text(*P, "inputs", k, "path") + "` | `"
                 + S.text(*P, "inputs", k, "sha256") + "` | " + S.num(*P, "inputs", k, "bytes")
                 + " |")
    L += ["", "- Code: stratum " + S.text(*P, "code", "version") + ", source SHA-256 `"
          + S.text(*P, "code", "source_sha256") + "` over " + S.num(*P, "code", "source_files")
          + " files (" + S.text(*P, "code", "method") + ")."]
    if S.get(*P, "git") is not None:
        L.append("- Git commit `" + S.text(*P, "git", "commit") + "`, working tree dirty: "
                 + S.num(*P, "git", "dirty") + ".")
    if S.get(*P, "environment") is not None:
        L.append("- Python " + S.text(*P, "environment", "python") + ", PyYAML "
                 + S.text(*P, "environment", "pyyaml") + ".")
    if S.get(*P, "omitted"):
        L.append("- Git and environment: " + S.text(*P, "omitted"))
    L.append("")
    return "\n".join(L).rstrip() + "\n", S.used


def render(doc: dict) -> str:
    """The report text for a results.json document."""
    return _render(doc, False)[0]


def render_traced(doc: dict):
    """(text with every traced value wrapped in \\x02...\\x03, [(path, value, shown)])."""
    return _render(doc, True)
