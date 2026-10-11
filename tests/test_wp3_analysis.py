"""WP3: the analysis of supported designs (DECISIONS.md D-060 to D-068).

Three independent kinds of check, on small designs written here:
  * hand-worked sums of squares, mean squares, F statistics, components and standard
    errors, in exact fractions;
  * an independent exact least-squares projection of the same sums of squares, so the
    closed-form nested formulas are not only checked against themselves;
  * the structural claims the frozen decisions make (the collapsed-stratum merge, the
    blocked-T2 error term, REML equal to the moment estimates, the missing-site
    estimator, and gating on a refused design).

All data here are synthetic.
"""
import math
import unittest
from fractions import Fraction as Q

from stratum.analysis import (ALPHA, AnalysisResult, ComponentGroup, analyze,
                              component_groups, reml_isotonic, structure_from_columns,
                              t2_kernel, unit_mean_structure)
from stratum.data import read_table
from stratum.dist import t_quantile
from stratum.exact import Design


# ---------------------------------------------------------------------------
# Small declaration and data builders
# ---------------------------------------------------------------------------

def dec(v):
    """A CSV cell. Every value in these tests is a dyadic rational, so a float is exact."""
    if isinstance(v, Q):
        return repr(float(v))
    return str(v)


def table(header, rows):
    return read_table("inline", text="\n".join([",".join(header)] +
                                                [",".join(dec(c) for c in r) for r in rows])
                      + "\n")


T1_DECL = """
stratum_declaration: 1
claimed_template: T1
response: {column: y, units: null}
hierarchy:
  - {name: lot, id_column: lot, count: 2}
  - {name: wafer, id_column: wafer, nested_in: lot, count_per_parent: 2}
  - {name: site, id_column: site, nested_in: wafer, count_per_parent: 2}
treatments: []
nuisance_factors: []
comparisons: []
"""


def t2_decl(w=2, s=2, levels=("low", "high"), r=2, block=None, depth=3):
    hier = ["  - {name: run, id_column: run, count: %d}" % (len(levels) * r),
            "  - {name: wafer, id_column: wafer, nested_in: run, count_per_parent: %d, "
            "exchangeable: true}" % w]
    if depth == 3:
        hier.append("  - {name: site, id_column: site, nested_in: wafer, "
                    "count_per_parent: %d, exchangeable: true}" % s)
    nuis = "nuisance_factors: []"
    if block:
        nuis = ("nuisance_factors:\n  - {name: chamber, column: chamber, recorded_at: run, "
                "role: block, levels: [%s], crossed_with: temp}" % ", ".join(block))
    return """
stratum_declaration: 1
claimed_template: T2
response: {column: y, units: null}
hierarchy:
%s
treatments:
  - name: temp
    column: temp
    levels: [%s]
    applied_to: run
    replicates_per_level: %d
    assignment: {method: randomized}
%s
comparisons:
  - {id: cmp, kind: pairwise, factors: [temp], levels: [%s, %s]}
""" % ("\n".join(hier), ", ".join(levels), r, nuis, levels[1], levels[0])


T3_DECL = """
stratum_declaration: 1
claimed_template: T3
response: {column: y, units: null}
hierarchy:
  - {name: plot, id_column: plot, count: 4}
  - {name: pos, id_column: pos, nested_in: plot, count_per_parent: 2}
treatments:
  - name: A
    column: A
    levels: ["1", "2"]
    applied_to: plot
    replicates_per_level: 2
    assignment: {method: randomized}
  - name: B
    column: pos
    levels: ["1", "2"]
    applied_to: pos
    replicates_per_level: 4
    assignment: {method: inherent}
nuisance_factors: []
comparisons:
  - {id: a_cmp, kind: overall, factors: [A]}
  - {id: b_cmp, kind: overall, factors: [B]}
  - {id: ab_cmp, kind: interaction, factors: [A, B]}
split_plot: {whole_plot_factor: A, subplot_factor: B}
"""


# ---------------------------------------------------------------------------
# Independent exact least-squares projection of the same sums of squares
# ---------------------------------------------------------------------------

def projection_ss(values, groupings):
    """Cumulative Sum((P y)^2) for a chain of nested groupings, exactly, where each
    grouping is a list giving every observation's unit. Returns the successive
    differences, i.e. one sum of squares per stratum."""
    n = len(values)
    cum = []
    for grouping in groupings:
        cols = {g: i for i, g in enumerate(dict.fromkeys(grouping))}
        design = Design([(cols[g],) for g in grouping], len(cols))
        fit = design.fitted(values)
        cum.append(sum((f * f for f in fit), Q(0)))
    grand = sum(values, Q(0)) / n
    base = n * grand * grand
    out, prev = [], base
    for c in cum:
        out.append(c - prev)
        prev = c
    return out


def residual_ss(values, rows, ncols):
    """Sum of squared residuals of an exact least-squares fit of an indicator design."""
    design = Design(rows, ncols)
    fit = design.fitted(values)
    return sum(((v - f) ** 2 for v, f in zip(values, fit)), Q(0))


# ---------------------------------------------------------------------------
# T1
# ---------------------------------------------------------------------------

T1_VALUES = [10, 12, 14, 16, 20, 22, 24, 26]


def t1_table():
    rows = []
    k = 0
    for lot in (1, 2):
        for wafer in (1, 2):
            for site in (1, 2):
                rows.append([lot, wafer, site, T1_VALUES[k]])
                k += 1
    return table(["lot", "wafer", "site", "y"], rows)


class T1Analysis(unittest.TestCase):
    def setUp(self):
        self.r = analyze(T1_DECL, t1_table())

    def test_hand_worked_anova(self):
        a = self.r.anova
        self.assertEqual((a["A"]["df"], a["B"]["df"], a["residual"]["df"],
                          a["total"]["df"]), (1, 2, 4, 7))
        self.assertEqual([a[k]["ss_exact"] for k in ("A", "B", "residual", "total")],
                         ["200", "32", "8", "240"])
        self.assertEqual([a[k]["ms"] for k in ("A", "B", "residual")], [200.0, 16.0, 2.0])
        self.assertAlmostEqual(a["A"]["F"], 12.5, 12)
        self.assertEqual((a["A"]["num_df"], a["A"]["den_df"]), (1, 2))
        self.assertAlmostEqual(a["B"]["F"], 8.0, 12)
        self.assertEqual((a["B"]["num_df"], a["B"]["den_df"]), (2, 4))
        self.assertEqual(a["A"]["error_term"], "wafer")
        self.assertEqual(a["B"]["error_term"], "site")

    def test_expected_mean_squares_follow_section_5_1(self):
        self.assertEqual(self.r.anova["A"]["ems_coefficients"],
                         {"A": 4, "B": 2, "residual": 1})
        self.assertEqual(self.r.anova["B"]["ems_coefficients"], {"B": 2, "residual": 1})
        self.assertEqual(self.r.anova["residual"]["ems_coefficients"], {"residual": 1})

    def test_hand_worked_components(self):
        vc = self.r.vc
        self.assertEqual([vc[k]["mom_exact"] for k in ("A", "B", "residual")],
                         ["46", "7", "2"])
        for k in ("A", "B", "residual"):
            self.assertEqual(vc[k]["reml"], vc[k]["mom"])
            self.assertTrue(vc[k]["reml_equals_mom"])
        self.assertAlmostEqual(sum(vc[k]["percent_of_total"] for k in vc), 100.0, 9)

    def test_lowest_component_interval_is_exact_chi_square(self):
        v = self.r.vc["residual"]
        self.assertTrue(v["exact"])
        self.assertEqual(v["nu_eff"], 4.0)
        from stratum.dist import chi2_quantile
        self.assertAlmostEqual(v["interval_lower"],
                               4 * 2.0 / chi2_quantile(0.975, 4), 12)
        self.assertAlmostEqual(v["interval_upper"],
                               4 * 2.0 / chi2_quantile(0.025, 4), 12)
        self.assertFalse(self.r.vc["A"]["exact"])
        self.assertFalse(self.r.vc["B"]["exact"])

    def test_satterthwaite_effective_df_of_a_difference(self):
        v = self.r.vc["A"]
        want = (200.0 - 16.0) ** 2 / (200.0 ** 2 / 1 + 16.0 ** 2 / 2)
        self.assertAlmostEqual(v["nu_eff"], want, 12)

    def test_sd_interval_is_the_square_root_of_the_variance_interval(self):
        for v in self.r.vc.values():
            if v["interval_available"]:
                self.assertAlmostEqual(v["sd_interval_lower"],
                                       math.sqrt(v["interval_lower"]), 12)
                self.assertAlmostEqual(v["sd_interval_upper"],
                                       math.sqrt(v["interval_upper"]), 12)

    def test_grand_mean_estimate_rests_on_the_top_level(self):
        e = self.r.estimate["grand_mean"]
        self.assertEqual(e["estimate"], 18.0)
        self.assertAlmostEqual(e["se"], math.sqrt(200.0 / 8), 12)
        self.assertEqual(e["df"], 1.0)
        self.assertEqual(e["independent_units"], 2)
        tq = t_quantile(1 - ALPHA / 2, 1.0)
        self.assertAlmostEqual(e["upper"] - e["estimate"], tq * e["se"], 10)

    def test_stratum_expectation_intervals_are_exact(self):
        for v in self.r.stratum_expectation.values():
            self.assertTrue(v["exact"])
            self.assertLess(v["lower"], v["ms"])
            self.assertGreater(v["upper"], v["ms"])

    def test_sums_of_squares_match_an_independent_projection(self):
        values = [Q(v) for v in T1_VALUES]
        lots = [1, 1, 1, 1, 2, 2, 2, 2]
        wafers = [(1, 1), (1, 1), (1, 2), (1, 2), (2, 1), (2, 1), (2, 2), (2, 2)]
        obs = list(range(8))
        got = projection_ss(values, [lots, wafers, obs])
        self.assertEqual([str(x) for x in got], ["200", "32", "8"])

    def test_no_boundary_or_failed_fits(self):
        self.assertEqual(self.r.fits["boundary"], [])
        self.assertEqual(self.r.fits["degenerate"], [])
        self.assertEqual(self.r.fits["failed"], [])


# ---------------------------------------------------------------------------
# T2
# ---------------------------------------------------------------------------

def t2_rows(run_means, w=2, s=2, wafer_dev=Q(1), site_dev=Q(1, 2), levels=("low", "high"),
            block=None, depth=3):
    """Balanced synthetic T2 rows with exactly controlled unit, wafer and site deviations."""
    rows = []
    per = len(run_means) // len(levels)
    for idx, mean in enumerate(run_means):
        lv = levels[idx // per]
        run = "R%d" % (idx + 1)
        extra = [block[idx]] if block else []
        for j in range(w):
            wmean = mean + (wafer_dev if j % 2 else -wafer_dev)
            if depth == 2:
                rows.append([run, "%s-W%d" % (run, j + 1), lv] + extra + [wmean])
                continue
            for k in range(s):
                rows.append([run, "%s-W%d" % (run, j + 1), "S%d" % (k + 1), lv] + extra
                            + [wmean + (site_dev if k % 2 else -site_dev)])
    header = ["run", "wafer"] + (["site"] if depth == 3 else []) + ["temp"] \
        + (["chamber"] if block else []) + ["y"]
    return table(header, rows)


class T2Analysis(unittest.TestCase):
    def setUp(self):
        self.r = analyze(t2_decl(), t2_rows([Q(10), Q(14), Q(20), Q(24)]))

    def test_hand_worked_anova_and_the_correct_error_term(self):
        a = self.r.anova
        self.assertEqual([a[k]["ss_exact"] for k in ("treatment", "unit", "sub1", "sub2")],
                         ["400", "64", "16", "4"])
        self.assertEqual([a[k]["df"] for k in ("treatment", "unit", "sub1", "sub2")],
                         [1, 2, 4, 8])
        self.assertEqual(a["treatment"]["error_term"], "units within treatment")
        self.assertEqual((a["treatment"]["num_df"], a["treatment"]["den_df"]), (1, 2))
        self.assertAlmostEqual(a["treatment"]["F"], 400.0 / 32.0, 12)
        self.assertEqual(a["total"]["ss_exact"], "484")

    def test_hand_worked_components(self):
        self.assertEqual([self.r.vc[k]["mom_exact"] for k in ("unit", "sub1", "sub2")],
                         ["7", "7/4", "1/2"])

    def test_hand_worked_contrast(self):
        e = self.r.estimate["cmp: high - low"]
        self.assertEqual(e["estimate"], 10.0)
        self.assertAlmostEqual(e["se"], math.sqrt(2 * 32.0 / (2 * 4)), 12)
        self.assertEqual(e["df"], 2.0)
        self.assertEqual(e["independent_units"], 4)
        self.assertAlmostEqual(e["t"], 10.0 / math.sqrt(8.0), 12)

    def test_level_means(self):
        self.assertEqual(self.r.estimate["mean[low]"]["estimate"], 12.0)
        self.assertEqual(self.r.estimate["mean[high]"]["estimate"], 22.0)
        self.assertAlmostEqual(self.r.estimate["mean[low]"]["se"],
                               math.sqrt(32.0 / (2 * 4)), 12)

    def test_sums_of_squares_match_an_independent_projection(self):
        tbl = t2_rows([Q(10), Q(14), Q(20), Q(24)])
        values = [Q(row["y"]) for row in tbl.rows]
        runs = [row["run"] for row in tbl.rows]
        wafers = [row["wafer"] for row in tbl.rows]
        obs = list(range(len(values)))
        got = projection_ss(values, [runs, wafers, obs])
        self.assertEqual([str(x) for x in got], ["464", "16", "4"])   # run stratum = 400+64
        trt = [row["temp"] for row in tbl.rows]
        got_trt = projection_ss(values, [trt])
        self.assertEqual(str(got_trt[0]), "400")

    def test_the_unit_mean_one_way_test_is_the_same_test(self):
        """D-065: for balanced data the unit-mean analysis gives the identical F and df."""
        tbl = t2_rows([Q(10), Q(14), Q(20), Q(24)])
        dt = structure_from_columns(tbl, ["run", "wafer", "site"], "y")
        k = t2_kernel(unit_mean_structure(dt.structure), dt.unit_value(0, "temp"),
                      ["low", "high"], contrast=("high", "low"))
        self.assertAlmostEqual(k["anova"]["treatment"]["F"],
                               self.r.anova["treatment"]["F"], 12)
        self.assertEqual(k["anova"]["treatment"]["den_df"],
                         self.r.anova["treatment"]["den_df"])
        self.assertAlmostEqual(k["estimate"]["contrast"]["se"],
                               self.r.estimate["cmp: high - low"]["se"], 12)

    def test_depth_two_hierarchy(self):
        r = analyze(t2_decl(depth=2), t2_rows([Q(10), Q(14), Q(20), Q(24)], depth=2))
        self.assertEqual(sorted(r.vc), ["sub1", "unit"])
        self.assertNotIn("sub2", r.anova)
        self.assertEqual(r.anova["treatment"]["error_term"], "units within treatment")


class T2CollapsedStratum(unittest.TestCase):
    """D-054 and D-062: w = 1 merges the run and wafer components."""

    def setUp(self):
        self.r = analyze(t2_decl(w=1), t2_rows([Q(10), Q(14), Q(20), Q(24)], w=1))

    def test_the_components_are_merged_and_named(self):
        self.assertEqual(sorted(self.r.vc), ["sub2", "unit+sub1"])
        merged = self.r.vc["unit+sub1"]
        self.assertTrue(merged["merged"])
        self.assertEqual(merged["coefficient"], 2)
        self.assertIn("MS[unit+sub1] - MS[sub2]", merged["estimator"])

    def test_the_empty_stratum_is_omitted_and_the_test_still_works(self):
        self.assertEqual(self.r.design["collapsed_strata"], ["sub1"])
        self.assertNotIn("sub1", self.r.anova)
        self.assertEqual(self.r.anova["unit"]["error_term"], "site")
        self.assertEqual((self.r.anova["treatment"]["num_df"],
                          self.r.anova["treatment"]["den_df"]), (1, 2))

    def test_the_wp2_warning_is_carried_forward(self):
        self.assertEqual(self.r.decision, "WARN")
        self.assertIn("aliased_components",
                      {f.code for f in self.r.evidence.findings})
        self.assertTrue(any("not separately identifiable" in n for n in self.r.notes))


class T2Blocked(unittest.TestCase):
    """D-063: the additive unit-level model and its treatment error term."""

    def setUp(self):
        self.tbl = t2_rows([Q(10), Q(14), Q(20), Q(26)], w=2, depth=2,
                           wafer_dev=Q(1, 2), block=["A", "B", "A", "B"])
        self.r = analyze(t2_decl(w=2, depth=2, block=("A", "B")), self.tbl)

    def test_hand_worked_blocked_anova(self):
        a = self.r.anova
        self.assertEqual([a[k]["ss_exact"] for k in ("treatment", "block", "unit")],
                         ["242", "50", "2"])
        self.assertEqual([a[k]["df"] for k in ("treatment", "block", "unit")], [1, 1, 1])
        self.assertAlmostEqual(a["treatment"]["F"], 121.0, 12)
        self.assertEqual(a["treatment"]["error_term"],
                         "units within treatment and block")
        self.assertEqual((a["treatment"]["num_df"], a["treatment"]["den_df"]), (1, 1))

    def test_the_block_row_is_descriptive(self):
        self.assertIn("descriptive", self.r.anova["block"]["note"])
        self.assertNotIn("block", self.r.vc)

    def test_hand_worked_contrast_and_df(self):
        e = self.r.estimate["cmp: high - low"]
        self.assertEqual(e["estimate"], 11.0)
        self.assertAlmostEqual(e["se"], 1.0, 12)
        self.assertEqual(e["df"], 1.0)

    def test_matches_an_independent_exact_least_squares_fit(self):
        """The closed-form blocked decomposition against a generic exact fit of
        1 + treatment + block on the unit means."""
        means, trt, blk = {}, {}, {}
        for row in self.tbl.rows:
            means.setdefault(row["run"], []).append(Q(row["y"]))
            trt[row["run"]] = row["temp"]
            blk[row["run"]] = row["chamber"]
        units = list(means)
        y = [sum(means[u], Q(0)) / len(means[u]) for u in units]
        tcols = {lv: i for i, lv in enumerate(dict.fromkeys(trt[u] for u in units))}
        bcols = {lv: len(tcols) + i
                 for i, lv in enumerate(dict.fromkeys(blk[u] for u in units))}
        full = [(tcols[trt[u]], bcols[blk[u]]) for u in units]
        m = 2                                       # observations per unit
        self.assertEqual(residual_ss(y, full, len(tcols) + len(bcols)) * m,
                         Q(self.r.anova["unit"]["ss_exact"]))
        trt_only = [(tcols[trt[u]],) for u in units]
        self.assertEqual((residual_ss(y, trt_only, len(tcols))
                          - residual_ss(y, full, len(tcols) + len(bcols))) * m,
                         Q(self.r.anova["block"]["ss_exact"]))

    def test_the_treatment_contrast_is_free_of_block_effects(self):
        """D-063: because the crossing is balanced, adding a constant to every unit in one
        block changes no treatment estimate, standard error, F or df. That is why the test
        does not depend on blocks being fixed or random."""
        rows = []
        for row in self.tbl.rows:
            shifted = dict(row)
            if row["chamber"] == "B":
                shifted["y"] = Q(row["y"]) + 1000
            rows.append(shifted)
        shifted_tbl = table(list(self.tbl.columns),
                            [[r[c] for c in self.tbl.columns] for r in rows])
        r2 = analyze(t2_decl(w=2, depth=2, block=("A", "B")), shifted_tbl)
        for key in ("treatment", "unit"):
            self.assertEqual(r2.anova[key]["ss_exact"], self.r.anova[key]["ss_exact"])
        e1 = self.r.estimate["cmp: high - low"]
        e2 = r2.estimate["cmp: high - low"]
        for field in ("estimate", "se", "df", "t", "p", "lower", "upper"):
            self.assertAlmostEqual(e1[field], e2[field], 10, field)


class T2MissingSites(unittest.TestCase):
    """D-065: the narrow missing-site exception."""

    def setUp(self):
        tbl = t2_rows([Q(10), Q(14), Q(20), Q(24)])
        rows = [dict(r) for r in tbl.rows]
        rows[0]["y"] = ""                     # one site lost from run 1, wafer 1
        self.tbl = table(list(tbl.columns),
                         [[r[c] for c in tbl.columns] for r in rows])
        self.r = analyze(t2_decl(), self.tbl)

    def test_the_exception_applies_and_the_analysis_is_labelled_approximate(self):
        self.assertEqual(self.r.decision, "WARN")
        self.assertIn("missing_sites_exception",
                      {f.code for f in self.r.evidence.findings})
        self.assertTrue(self.r.design["missing_site_exception"])
        self.assertIn("approximate", self.r.anova["treatment"]["note"])
        self.assertTrue(self.r.estimate["cmp: high - low"]["approximate"])

    def test_components_reml_and_allocation_are_withheld_with_a_reason(self):
        self.assertEqual(self.r.vc, {})
        self.assertEqual(self.r.reml, {})
        self.assertEqual(self.r.stratum_expectation, {})
        text = " ".join(self.r.notes)
        for word in ("withheld", "variance-component", "allocation"):
            self.assertIn(word, text)

    def test_unit_means_are_hierarchical(self):
        """Run 1 keeps wafer 1 at full weight even though it lost a site (D-016)."""
        # Wafer 1 of run 1 is 10 - 1 = 9 and keeps only its second site, 9 + 1/2.
        # Wafer 2 of run 1 has mean 11. The run mean weights the two wafers equally.
        want = (Q(19, 2) + Q(11)) / 2
        self.assertAlmostEqual(self.r.estimate["mean[low]"]["estimate"],
                               float((want + Q(14)) / 2), 12)

    def test_the_degrees_of_freedom_are_still_the_unit_level_ones(self):
        self.assertEqual((self.r.anova["treatment"]["num_df"],
                          self.r.anova["treatment"]["den_df"]), (1, 2))


class T2Boundary(unittest.TestCase):
    """D-066: a negative moment estimate is reported, truncated, and recorded."""

    def setUp(self):
        # Wafer deviations large enough that MS[sub1] > MS[unit], so sigma2[unit] < 0.
        self.r = analyze(t2_decl(depth=2),
                         t2_rows([Q(10), Q(14), Q(20), Q(24)], depth=2, wafer_dev=Q(4)))

    def test_the_negative_estimate_is_reported_then_truncated(self):
        v = self.r.vc["unit"]
        self.assertTrue(v["negative"])
        self.assertLess(v["mom"], 0.0)
        self.assertEqual(v["mom_truncated"], 0.0)
        self.assertEqual(v["sd_mom"], 0.0)

    def test_no_satterthwaite_interval_is_manufactured(self):
        v = self.r.vc["unit"]
        self.assertFalse(v["interval_available"])
        self.assertIn("not usable", v["interval_reason"])
        self.assertNotIn("interval_lower", v)

    def test_reml_pools_and_sits_on_the_boundary(self):
        v = self.r.vc["unit"]
        self.assertEqual(v["reml"], 0.0)
        self.assertFalse(v["reml_equals_mom"])
        self.assertTrue(self.r.reml["fit"]["boundary"])
        self.assertEqual(self.r.reml["fit"]["pooled"], [["unit", "sub1"]])

    def test_the_boundary_fit_is_recorded(self):
        kinds = {b["kind"] for b in self.r.fits["boundary"]}
        self.assertEqual(kinds, {"negative_moment_estimate", "reml_on_boundary"})
        self.assertEqual(self.r.fits["failed"], [])

    def test_the_exact_expectation_intervals_are_still_reported(self):
        self.assertEqual(sorted(self.r.stratum_expectation), ["sub1", "unit"])
        for v in self.r.stratum_expectation.values():
            self.assertTrue(v["exact"])


# ---------------------------------------------------------------------------
# T3
# ---------------------------------------------------------------------------

T3_ROWS = [
    ("P1", "1", "1", Q(9)), ("P1", "2", "1", Q(11)),
    ("P2", "1", "1", Q(25, 2)), ("P2", "2", "1", Q(31, 2)),
    ("P3", "1", "2", Q(18)), ("P3", "2", "2", Q(22)),
    ("P4", "1", "2", Q(22)), ("P4", "2", "2", Q(26)),
]


def t3_table():
    return table(["plot", "pos", "A", "y"],
                 [[p, pos, a, y] for p, pos, a, y in T3_ROWS])


class T3Analysis(unittest.TestCase):
    def setUp(self):
        self.r = analyze(T3_DECL, t3_table())

    def test_hand_worked_anova_and_two_error_terms(self):
        a = self.r.anova
        self.assertEqual([a[k]["ss_exact"] for k in
                          ("A", "wholeplot_error", "B", "AB", "subplot_error", "total")],
                         ["200", "32", "169/8", "9/8", "1/4", "509/2"])
        self.assertEqual([a[k]["df"] for k in
                          ("A", "wholeplot_error", "B", "AB", "subplot_error")],
                         [1, 2, 1, 1, 2])
        self.assertEqual(a["A"]["error_term"], "whole plots within A")
        self.assertEqual(a["B"]["error_term"], "subplot error")
        self.assertEqual(a["AB"]["error_term"], "subplot error")
        self.assertAlmostEqual(a["A"]["F"], 12.5, 12)
        self.assertAlmostEqual(a["B"]["F"], 169.0, 12)
        self.assertAlmostEqual(a["AB"]["F"], 9.0, 12)

    def test_expected_mean_squares(self):
        self.assertEqual(self.r.anova["A"]["ems_coefficients"],
                         {"wholeplot": 2, "residual": 1})
        self.assertEqual(self.r.anova["B"]["ems_coefficients"], {"residual": 1})
        self.assertEqual(self.r.anova["subplot_error"]["ems_coefficients"],
                         {"residual": 1})

    def test_hand_worked_components(self):
        self.assertEqual(self.r.vc["wholeplot"]["mom_exact"], "127/16")
        self.assertEqual(self.r.vc["residual"]["mom_exact"], "1/8")

    def test_the_naive_analysis_is_reported_and_labelled_wrong(self):
        n = self.r.naive_anova
        self.assertEqual(n["residual"]["df"], 4)
        self.assertEqual(n["residual"]["ss_exact"], "129/4")
        self.assertAlmostEqual(n["A"]["F"], 200.0 / (129.0 / 16), 12)
        self.assertEqual(n["A"]["ss_exact"], self.r.anova["A"]["ss_exact"])
        self.assertIn("WRONG", n["A"]["note"])
        self.assertIn("residual df instead of", n["note"])

    def test_the_naive_residual_pools_the_two_error_strata(self):
        self.assertEqual(Q(self.r.naive_anova["residual"]["ss_exact"]),
                         Q(self.r.anova["wholeplot_error"]["ss_exact"])
                         + Q(self.r.anova["subplot_error"]["ss_exact"]))
        self.assertEqual(self.r.naive_anova["residual"]["df"],
                         self.r.anova["wholeplot_error"]["df"]
                         + self.r.anova["subplot_error"]["df"])

    def test_contrast_standard_errors_use_the_right_stratum(self):
        ms_g, ms_e = 16.0, 0.125
        a = self.r.estimate["a_cmp: 2 - 1"]
        self.assertAlmostEqual(a["estimate"], 10.0, 12)
        self.assertAlmostEqual(a["se"], math.sqrt(2 * ms_g / (2 * 2)), 12)
        self.assertEqual(a["df"], 2.0)
        b = self.r.estimate["b_cmp: 2 - 1"]
        self.assertAlmostEqual(b["se"], math.sqrt(2 * ms_e / 4), 12)
        self.assertEqual(b["df"], 2.0)
        self.assertEqual(b["error_term"], "subplot error")
        ab = [k for k in self.r.estimate if k.startswith("ab_cmp")][0]
        self.assertAlmostEqual(self.r.estimate[ab]["se"],
                               2 * math.sqrt(ms_e / 2), 12)

    def test_subplot_level_means_are_labelled_approximate(self):
        for lv in ("1", "2"):
            e = self.r.estimate["mean_B[%s]" % lv]
            self.assertTrue(e["approximate"])
            self.assertIn("Satterthwaite", e["note"])
        self.assertFalse(self.r.estimate["mean_A[1]"]["approximate"])

    def test_sums_of_squares_match_an_independent_projection(self):
        tbl = t3_table()
        values = [Q(row["y"]) for row in tbl.rows]
        plots = [row["plot"] for row in tbl.rows]
        got = projection_ss(values, [[row["A"] for row in tbl.rows], plots,
                                     list(range(8))])
        self.assertEqual(str(got[0]), "200")                 # A
        self.assertEqual(str(got[1]), "32")                  # whole-plot error
        cells = [(row["A"], row["pos"]) for row in tbl.rows]
        full = [(i,) for i in range(8)]
        # subplot error = residual of plot + cell, fitted exactly
        pcols = {p: i for i, p in enumerate(dict.fromkeys(plots))}
        ccols = {c: len(pcols) + i for i, c in enumerate(dict.fromkeys(cells))}
        rows = [(pcols[p], ccols[c]) for p, c in zip(plots, cells)]
        self.assertEqual(residual_ss(values, rows, len(pcols) + len(ccols)),
                         Q(self.r.anova["subplot_error"]["ss_exact"]))
        del full

    def test_degrees_of_freedom_for_the_sasmixed_shape(self):
        """a = 4, r = 3, b = 4 gives A on (3, 8) and B on (3, 24), as brief 5.3 states."""
        decl = T3_DECL.replace('count: 4', 'count: 12') \
            .replace('levels: ["1", "2"]\n    applied_to: plot',
                     'levels: ["1", "2", "3", "4"]\n    applied_to: plot') \
            .replace('replicates_per_level: 2', 'replicates_per_level: 3') \
            .replace('count_per_parent: 2', 'count_per_parent: 4') \
            .replace('levels: ["1", "2"]\n    applied_to: pos',
                     'levels: ["1", "2", "3", "4"]\n    applied_to: pos') \
            .replace('replicates_per_level: 4', 'replicates_per_level: 12')
        rows, n = [], 0
        for a in range(1, 5):
            for rep in range(3):
                plot = "P%d_%d" % (a, rep)
                for pos in range(1, 5):
                    n += 1
                    rows.append([plot, str(pos), str(a), str(n % 7 + a + 0.5 * pos)])
        r = analyze(decl, table(["plot", "pos", "A", "y"], rows))
        self.assertTrue(r.analyzed, r.notes)
        self.assertEqual((r.anova["A"]["num_df"], r.anova["A"]["den_df"]), (3, 8))
        self.assertEqual((r.anova["B"]["num_df"], r.anova["B"]["den_df"]), (3, 24))
        self.assertEqual((r.anova["AB"]["num_df"], r.anova["AB"]["den_df"]), (9, 24))
        self.assertEqual(r.naive_anova["residual"]["df"], 32)


# ---------------------------------------------------------------------------
# REML
# ---------------------------------------------------------------------------

def brute_force_isotonic(groups):
    """The order-restricted optimum by enumerating every contiguous partition, so the
    pool-adjacent-violators result is not checked against itself (D-064)."""
    n = len(groups)
    best, best_val = None, None
    for mask in range(1 << (n - 1)):
        blocks, start = [], 0
        for i in range(n - 1):
            if mask >> i & 1:
                blocks.append((start, i + 1))
                start = i + 1
        blocks.append((start, n))
        lam = []
        for lo, hi in blocks:
            df = sum(groups[i].df for i in range(lo, hi))
            ss = sum((groups[i].ss for i in range(lo, hi)), Q(0))
            lam.extend([ss / df] * (hi - lo))
        if any(lam[i] < lam[i + 1] for i in range(n - 1)):
            continue
        val = sum(float(g.df) * math.log(float(l)) + float(g.ss) / float(l)
                  for g, l in zip(groups, lam))
        if best_val is None or val < best_val - 1e-12:
            best, best_val = lam, val
    return best


class RemlClosedForm(unittest.TestCase):
    def groups(self, triples):
        return [ComponentGroup((("g%d" % i),), m, df, Q(ss), ("g%d" % i,))
                for i, (m, df, ss) in enumerate(triples)]

    def test_ordered_mean_squares_are_left_alone(self):
        g = self.groups([(4, 1, 200), (2, 2, 32), (1, 4, 8)])
        self.assertEqual(reml_isotonic(g), [Q(200), Q(16), Q(2)])

    def test_a_violation_is_pooled(self):
        g = self.groups([(2, 1, 2), (1, 4, 32)])
        self.assertEqual(reml_isotonic(g), [Q(34, 5), Q(34, 5)])

    def test_matches_brute_force_enumeration(self):
        cases = [
            [(4, 1, 200), (2, 2, 32), (1, 4, 8)],
            [(4, 1, 2), (2, 2, 32), (1, 4, 8)],
            [(4, 1, 2), (2, 2, 4), (1, 4, 400)],
            [(4, 3, 30), (2, 3, 30), (1, 3, 30)],
            [(8, 2, 10), (4, 5, 100), (2, 7, 20), (1, 9, 300)],
            [(8, 2, 1000), (4, 5, 100), (2, 7, 60), (1, 9, 9)],
        ]
        for triples in cases:
            g = self.groups(triples)
            self.assertEqual(reml_isotonic(g), brute_force_isotonic(g), triples)

    def test_pooling_never_breaks_the_ordering(self):
        g = self.groups([(8, 2, 10), (4, 5, 100), (2, 7, 20), (1, 9, 300)])
        lam = reml_isotonic(g)
        self.assertTrue(all(lam[i] >= lam[i + 1] for i in range(len(lam) - 1)))

    def test_merged_group_requires_zero_df(self):
        bad = [ComponentGroup(("a",), 2, 3, Q(6), ("a",)),
               ComponentGroup(("b",), 2, 3, Q(6), ("b",))]
        with self.assertRaises(ValueError):
            component_groups([_S("a", 2, 3, Q(6)), _S("b", 2, 3, Q(6))])
        del bad


class _S:
    """A minimal stand-in for Stratum in the component_groups guard test."""

    def __init__(self, key, m, df, ss):
        self.key, self.m, self.df, self.ss, self.label = key, m, df, ss, key

    @property
    def ms(self):
        return self.ss / self.df


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

class Gating(unittest.TestCase):
    """D-067: a refused design produces no estimate of any kind."""

    def test_refused_declaration_produces_nothing(self):
        """r = 1 is refused by WP1 itself: zero error degrees of freedom."""
        r = analyze(t2_decl(r=1), t2_rows([Q(10), Q(20)]))
        self.assertEqual(r.decision, "REFUSE")
        self.assertFalse(r.analyzed)
        self.assertEqual((r.anova, r.vc, r.estimate, r.reml, r.stratum_expectation),
                         ({}, {}, {}, {}, {}))
        self.assertTrue(any("refusal is a successful outcome" in n for n in r.notes))
        self.assertTrue(any("declaration_refused" in n for n in r.notes))

    def test_data_level_refusal_produces_nothing(self):
        """The declaration is fine, but the data give one run to a treatment level."""
        rows = t2_rows([Q(10), Q(14), Q(20), Q(24)])
        fixed = []
        for row in rows.rows:
            row = dict(row)
            if row["run"] == "R4":
                row["temp"] = "low"
            fixed.append([row[c] for c in rows.columns])
        r = analyze(t2_decl(), table(list(rows.columns), fixed))
        self.assertEqual(r.decision, "REFUSE")
        self.assertFalse(r.analyzed)
        self.assertEqual((r.anova, r.vc, r.estimate), ({}, {}, {}))
        self.assertTrue(any("insufficient_replication" in n for n in r.notes))

    def test_a_refused_declaration_produces_nothing(self):
        r = analyze("not: a declaration\n", t1_table())
        self.assertEqual(r.decision, "REFUSE")
        self.assertFalse(r.analyzed)
        self.assertEqual(r.anova, {})

    def test_warn_is_analyzed_and_carries_its_findings(self):
        r = analyze(t2_decl(w=1), t2_rows([Q(10), Q(14), Q(20), Q(24)], w=1))
        self.assertEqual(r.decision, "WARN")
        self.assertTrue(r.analyzed)
        self.assertTrue(r.evidence.by_severity("warn"))

    def test_result_lookup_matches_the_map_contract(self):
        r = analyze(T1_DECL, t1_table())
        self.assertEqual(r.get("anova", "A", "df"), 1)
        self.assertEqual(r.get("vc", "A", "mom"), 46.0)
        with self.assertRaises(KeyError):
            r.get("anova", "nope", "df")
        with self.assertRaises(KeyError):
            r.get("vc", "A", "nope")
        self.assertIsInstance(r, AnalysisResult)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# The restricted log-likelihood, checked against its textbook definition
# ---------------------------------------------------------------------------

def brute_restricted_loglik(y, x_rows, groupings, variances, sigma2):
    """-2 log L_R from the definition, in exact rational linear algebra:

        (n - p) log(2 pi) + log|V| + log|X'V^-1 X| + y'Py,   V = sigma2 I + sum var_g Z_g Z_g'

    (Harville 1977). This is independent of the stratum decomposition analysis.py uses,
    so it checks the closed form rather than restating it."""
    from stratum.exact import det, solve
    n, p = len(y), len(x_rows[0])
    V = [[Q(sigma2) if i == j else Q(0) for j in range(n)] for i in range(n)]
    for grouping, var in zip(groupings, variances):
        for i in range(n):
            for j in range(n):
                if grouping[i] == grouping[j]:
                    V[i][j] += Q(var)
    cols = [solve(V, [Q(row[k]) for row in x_rows]) for k in range(p)]
    vy = solve(V, [Q(v) for v in y])
    xtvx = [[sum((Q(x_rows[i][a]) * cols[b][i] for i in range(n)), Q(0))
             for b in range(p)] for a in range(p)]
    xtvy = [sum((Q(x_rows[i][a]) * vy[i] for i in range(n)), Q(0)) for a in range(p)]
    beta = solve(xtvx, xtvy)
    quad = sum((Q(y[i]) * vy[i] for i in range(n)), Q(0)) \
        - sum((xtvy[a] * beta[a] for a in range(p)), Q(0))
    return ((n - p) * math.log(2 * math.pi) + math.log(float(det(V)))
            + math.log(float(det(xtvx))) + float(quad))


class RestrictedLogLikelihood(unittest.TestCase):
    def test_t1_matches_the_definition(self):
        r = analyze(T1_DECL, t1_table())
        lots = [1, 1, 1, 1, 2, 2, 2, 2]
        wafers = [11, 11, 12, 12, 21, 21, 22, 22]
        want = brute_restricted_loglik(
            T1_VALUES, [[1]] * 8, [lots, wafers],
            [r.vc["A"]["reml"], r.vc["B"]["reml"]], r.vc["residual"]["reml"])
        self.assertAlmostEqual(r.reml["fit"]["minus2_restricted_loglik"], want, 9)

    def test_t3_matches_the_definition(self):
        r = analyze(T3_DECL, t3_table())
        tbl = t3_table()
        plots = [row["plot"] for row in tbl.rows]
        cells = sorted({(row["A"], row["pos"]) for row in tbl.rows})
        x_rows = [[1 if (row["A"], row["pos"]) == c else 0 for c in cells]
                  for row in tbl.rows]
        want = brute_restricted_loglik(
            [Q(row["y"]) for row in tbl.rows], x_rows, [plots],
            [r.vc["wholeplot"]["reml"]], r.vc["residual"]["reml"])
        self.assertAlmostEqual(r.reml["fit"]["minus2_restricted_loglik"], want, 9)

    def test_t2_matches_the_definition(self):
        decl, tbl = t2_decl(), t2_rows([Q(10), Q(14), Q(20), Q(24)])
        r = analyze(decl, tbl)
        runs = [row["run"] for row in tbl.rows]
        wafers = [row["wafer"] for row in tbl.rows]
        levels = sorted({row["temp"] for row in tbl.rows})
        x_rows = [[1 if row["temp"] == lv else 0 for lv in levels] for row in tbl.rows]
        want = brute_restricted_loglik(
            [Q(row["y"]) for row in tbl.rows], x_rows, [runs, wafers],
            [r.vc["unit"]["reml"], r.vc["sub1"]["reml"]], r.vc["sub2"]["reml"])
        self.assertAlmostEqual(r.reml["fit"]["minus2_restricted_loglik"], want, 9)

    def test_the_error_contrast_form_differs_by_the_fixed_effects_constant(self):
        r = analyze(T1_DECL, t1_table())
        fit = r.reml["fit"]
        self.assertAlmostEqual(fit["minus2_restricted_loglik"]
                               - fit["minus2_restricted_loglik_error_contrasts"],
                               fit["log_det_xtx"], 12)
        self.assertAlmostEqual(fit["log_det_xtx"], math.log(8.0), 12)   # X = 1, N = 8
        self.assertEqual(fit["fixed_parameterization"], "intercept only")

    def test_the_optimum_is_a_minimum_of_minus_two_log_likelihood(self):
        """Perturbing either component away from the REML estimate raises -2 log L_R."""
        r = analyze(T1_DECL, t1_table())
        lots = [1, 1, 1, 1, 2, 2, 2, 2]
        wafers = [11, 11, 12, 12, 21, 21, 22, 22]
        base = brute_restricted_loglik(
            T1_VALUES, [[1]] * 8, [lots, wafers],
            [r.vc["A"]["reml"], r.vc["B"]["reml"]], r.vc["residual"]["reml"])
        for which, factor in ((0, Q(9, 10)), (0, Q(11, 10)), (1, Q(4, 5)),
                              (1, Q(6, 5)), (2, Q(9, 10)), (2, Q(11, 10))):
            v = [Q(46), Q(7), Q(2)]
            v[which] = v[which] * factor
            self.assertGreater(brute_restricted_loglik(
                T1_VALUES, [[1]] * 8, [lots, wafers], v[:2], v[2]), base)


class ExactDeterminant(unittest.TestCase):
    """stratum.exact.det, added for the REML log-likelihood's fixed-effects constant."""

    def test_small_known_values(self):
        from stratum.exact import det
        self.assertEqual(det([[Q(2)]]), Q(2))
        self.assertEqual(det([[Q(1), Q(2)], [Q(3), Q(4)]]), Q(-2))
        self.assertEqual(det([[Q(1), Q(1)], [Q(1), Q(1)]]), Q(0))
        self.assertEqual(det([[Q(2), Q(0), Q(0)], [Q(0), Q(3), Q(0)],
                              [Q(0), Q(0), Q(5)]]), Q(30))

    def test_is_exact_on_fractions(self):
        from stratum.exact import det
        self.assertEqual(det([[Q(1, 3), Q(1, 7)], [Q(1, 5), Q(1, 11)]]),
                         Q(1, 33) - Q(1, 35))

    def test_row_swap_sign_and_singularity(self):
        from stratum.exact import det
        a = [[Q(0), Q(1)], [Q(1), Q(0)]]
        self.assertEqual(det(a), Q(-1))
        self.assertEqual(det([[Q(1), Q(2), Q(3)], [Q(2), Q(4), Q(6)],
                              [Q(1), Q(0), Q(1)]]), Q(0))

    def test_requires_a_square_matrix(self):
        from stratum.exact import det
        with self.assertRaises(ValueError):
            det([[Q(1), Q(2)]])

    def test_indicator_gram_determinant_is_the_product_of_cell_counts(self):
        from stratum.exact import det
        rows = [(0,), (0,), (0,), (1,), (1,)]
        self.assertEqual(det(Design(rows, 2).xtx), Q(6))
