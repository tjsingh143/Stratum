"""WP1: template matching and structured refusals.

Each test states the expected decision and the specific condition(s) expected to
fail, written from the template definitions (brief Section 5, DECISIONS.md D-035 to
D-039), not copied from the implementation's output.
"""
import unittest

import designs
from stratum.refusal import CATEGORIES
from stratum.templates import CONDITIONS, evaluate


class MatchCase(unittest.TestCase):
    def assertMatched(self, decl, template):
        res = evaluate(decl)
        self.assertEqual(res.decision, "matched", res.explain())
        self.assertEqual(res.matched_template, template)
        self.assertEqual(res.refusals, ())
        self.assertTrue(all(c.status == "pass" for c in res.conditions))
        return res

    def assertRefused(self, decl, failed, categories=None):
        """failed: the exact set of condition ids expected to fail."""
        res = evaluate(decl)
        self.assertEqual(res.decision, "refused")
        self.assertIsNone(res.matched_template)
        self.assertEqual(set(res.failed_conditions), set(failed), res.explain())
        if categories is not None:
            self.assertEqual(set(res.refusal_categories), set(categories))
        for r in res.refusals:
            self.assertIn(r.category, CATEGORIES)
            for text in (r.declared, r.requirement, r.reason):
                self.assertTrue(text and text.strip())
        return res


class ConditionsAreInspectable(unittest.TestCase):
    def test_condition_lists(self):
        self.assertEqual([c.id for c in CONDITIONS["T1"]], [
            "T1.no_treatment", "T1.no_comparisons", "T1.no_split_plot", "T1.no_blocking",
            "T1.three_level_chain", "T1.replicated_every_level"])
        self.assertEqual([c.id for c in CONDITIONS["T2"]], [
            "T2.one_treatment", "T2.applied_at_top_level", "T2.subsampling_depth",
            "T2.treatment_levels", "T2.treatment_applied_not_inherent", "T2.replicated",
            "T2.balanced_units", "T2.treatment_column_not_unit_id", "T2.no_split_plot",
            "T2.comparisons", "T2.supported_block"])
        self.assertEqual([c.id for c in CONDITIONS["T3"]], [
            "T3.split_plot_roles", "T3.two_level_hierarchy",
            "T3.whole_plot_factor_on_whole_plots", "T3.subplot_factor_on_subplots",
            "T3.whole_plot_factor_applied_not_inherent", "T3.whole_plot_replicated",
            "T3.whole_plot_balance", "T3.subplot_complete", "T3.factor_columns",
            "T3.subplot_not_exchangeable", "T3.no_blocking", "T3.comparisons"])
        for conds in CONDITIONS.values():
            for c in conds:
                self.assertIn(c.category, CATEGORIES)
                self.assertTrue(c.requirement)

    def test_match_reports_every_condition(self):
        res = evaluate(designs.t3())
        self.assertEqual([c.id for c in res.conditions], [c.id for c in CONDITIONS["T3"]])


# ---------------------------------------------------------------------------
class T1Matching(MatchCase):
    def test_valid_t1(self):
        self.assertMatched(designs.t1(), "T1")

    def test_t1_with_recorded_nuisance(self):
        d = designs.t1()
        d["nuisance_factors"] = [{"name": "source", "column": "Source", "recorded_at": "lot",
                                  "role": "recorded", "levels": ["1", "2"]}]
        self.assertMatched(d, "T1")

    def test_t1_minimum_replication(self):
        d = designs.t1()
        d["hierarchy"][0]["count"] = 2
        d["hierarchy"][1]["count_per_parent"] = 2
        d["hierarchy"][2]["count_per_parent"] = 2
        self.assertMatched(d, "T1")

    def test_treatment_declared_for_t1(self):
        # Oxide-like: Source declared as a treatment under T1 (D-014 forbids this).
        d = designs.t1()
        d["treatments"] = [{"name": "source", "column": "Source", "levels": ["1", "2"],
                            "applied_to": "lot", "replicates_per_level": 3,
                            "assignment": {"method": "inherent"}}]
        res = self.assertRefused(d, {"T1.no_treatment"}, {"treatment_structure"})
        self.assertIn("T2", res.refusals[0].remedy)
        self.assertIn("nuisance_factors", res.refusals[0].remedy)

    def test_treatment_and_comparison_declared_for_t1(self):
        d = designs.t1()
        d["treatments"] = [{"name": "tool", "column": "tool", "levels": ["a", "b"],
                            "applied_to": "lot", "replicates_per_level": 3,
                            "assignment": {"method": "randomized"}}]
        d["comparisons"] = [{"id": "tools", "kind": "overall", "factors": ["tool"]}]
        self.assertRefused(d, {"T1.no_treatment", "T1.no_comparisons"})

    def test_two_level_hierarchy(self):
        d = designs.t1()
        d["hierarchy"] = d["hierarchy"][:2]
        self.assertRefused(d, {"T1.three_level_chain"}, {"hierarchy"})

    def test_four_level_hierarchy(self):
        d = designs.t1()
        d["hierarchy"].append({"name": "repeat", "id_column": "rep", "nested_in": "site",
                               "count_per_parent": 2})
        self.assertRefused(d, {"T1.three_level_chain"}, {"hierarchy"})

    def test_one_unit_per_parent_is_unidentified(self):
        for idx, key in ((1, "count_per_parent"), (2, "count_per_parent"), (0, "count")):
            with self.subTest(level=idx):
                d = designs.t1()
                d["hierarchy"][idx][key] = 1
                self.assertRefused(d, {"T1.replicated_every_level"}, {"replication"})

    def test_block_in_t1(self):
        # A block must be crossed with a declared treatment, so a T1 block always comes
        # with a treatment; both conditions fail.
        d = designs.t1()
        d["treatments"] = [{"name": "tool", "column": "tool", "levels": ["a", "b"],
                            "applied_to": "lot", "replicates_per_level": 3,
                            "assignment": {"method": "randomized"}}]
        d["nuisance_factors"] = [{"name": "day", "column": "day", "recorded_at": "lot",
                                  "role": "block", "levels": ["1", "2"],
                                  "crossed_with": "tool"}]
        self.assertRefused(d, {"T1.no_treatment", "T1.no_blocking"},
                           {"treatment_structure", "blocking"})

    def test_block_without_treatment_refused_before_matching(self):
        d = designs.t1()
        d["nuisance_factors"] = [{"name": "day", "column": "day", "recorded_at": "lot",
                                  "role": "block", "levels": ["1", "2"],
                                  "crossed_with": "x"}]
        res = evaluate(d)
        self.assertEqual(res.refusal_categories, ("inconsistent_declaration",))

    def test_split_plot_in_t1(self):
        d = designs.t3()
        d["claimed_template"] = "T1"
        self.assertRefused(d, {"T1.no_treatment", "T1.no_comparisons", "T1.no_split_plot",
                               "T1.three_level_chain"})

    def test_exchangeability_does_not_change_t1_match(self):
        for value in (True, False, None):
            with self.subTest(exchangeable=value):
                d = designs.t1()
                if value is not None:
                    d["hierarchy"][2]["exchangeable"] = value
                res = self.assertMatched(d, "T1")
                self.assertIs(res.declaration.bottom.exchangeable, bool(value))


# ---------------------------------------------------------------------------
class T2Matching(MatchCase):
    def test_valid_t2(self):
        self.assertMatched(designs.t2(), "T2")

    def test_valid_t2_with_block(self):
        self.assertMatched(designs.t2_block(), "T2")

    def test_wafer_level_treatment_one_subsampling_level(self):
        d = designs.t2()
        d["hierarchy"] = [
            {"name": "wafer", "id_column": "wafer", "count": 6},
            {"name": "site", "id_column": "site", "nested_in": "wafer", "count_per_parent": 9},
        ]
        d["treatments"][0]["applied_to"] = "wafer"
        d["treatments"][0]["replicates_per_level"] = 3
        self.assertMatched(d, "T2")

    def test_single_wafer_and_site_per_unit_still_t2(self):
        # w = 1 and s = 1 are conforming T2 cells in the WP6 manifest (D-019).
        d = designs.t2()
        d["hierarchy"][1]["count_per_parent"] = 1
        d["hierarchy"][2]["count_per_parent"] = 1
        self.assertMatched(d, "T2")

    def test_missing_treatment(self):
        d = designs.t2()
        d["treatments"] = []
        d["comparisons"] = []
        res = self.assertRefused(d, {"T2.one_treatment"}, {"treatment_structure"})
        statuses = {c.id: c.status for c in res.conditions}
        self.assertEqual(statuses["T2.replicated"], "not_evaluated")
        self.assertEqual(statuses["T2.applied_at_top_level"], "not_evaluated")
        self.assertIn("T1", res.refusals[0].remedy)

    def test_two_treatments_factorial(self):
        d = designs.t2()
        d["treatments"].append({"name": "gas", "column": "gas", "levels": ["N2", "Ar"],
                                "applied_to": "run", "replicates_per_level": 4,
                                "assignment": {"method": "randomized"}})
        self.assertRefused(d, {"T2.one_treatment"}, {"treatment_structure"})

    def test_treatment_applied_to_nested_level(self):
        # Contradictory application level: treatment on wafers inside runs.
        d = designs.t2()
        d["treatments"][0]["applied_to"] = "wafer"
        d["treatments"][0]["replicates_per_level"] = 8
        res = self.assertRefused(d, {"T2.applied_at_top_level"}, {"application_level"})
        self.assertIn("run", res.refusals[0].reason)

    def test_treatment_applied_to_sites(self):
        d = designs.t2()
        d["treatments"][0]["applied_to"] = "site"
        self.assertRefused(d, {"T2.applied_at_top_level"})

    def test_unreplicated_runs_with_many_subsamples(self):
        # One run per level, 25 wafers x 9 sites each: pseudo-replication.
        d = designs.t2()
        d["hierarchy"][0]["count"] = 2
        d["hierarchy"][1]["count_per_parent"] = 25
        d["hierarchy"][2]["count_per_parent"] = 9
        d["treatments"][0]["replicates_per_level"] = 1
        res = self.assertRefused(d, {"T2.replicated"}, {"replication"})
        self.assertIn("zero error degrees of freedom", res.refusals[0].reason)

    def test_unbalanced_counts(self):
        d = designs.t2()
        d["hierarchy"][0]["count"] = 9
        self.assertRefused(d, {"T2.balanced_units"}, {"balance"})

    def test_one_treatment_level(self):
        d = designs.t2()
        d["treatments"][0]["levels"] = ["high"]
        d["treatments"][0]["replicates_per_level"] = 8
        d["comparisons"] = [{"id": "c", "kind": "overall", "factors": ["temp"]}]
        self.assertRefused(d, {"T2.treatment_levels"})

    def test_hierarchy_too_deep(self):
        d = designs.t2()
        d["hierarchy"].append({"name": "scan", "id_column": "scan", "nested_in": "site",
                               "count_per_parent": 2})
        self.assertRefused(d, {"T2.subsampling_depth"}, {"hierarchy"})

    def test_hierarchy_without_observation_level(self):
        d = designs.t2()
        d["hierarchy"] = d["hierarchy"][:1]
        self.assertRefused(d, {"T2.subsampling_depth"}, {"hierarchy"})

    def test_treatment_column_is_unit_id(self):
        d = designs.t2()
        d["treatments"][0]["column"] = "run"
        self.assertRefused(d, {"T2.treatment_column_not_unit_id"})

    def test_no_comparison(self):
        d = designs.t2()
        d["comparisons"] = []
        self.assertRefused(d, {"T2.comparisons"}, {"comparison"})

    def test_inherent_factor_as_t2_treatment(self):
        # Superficially T2: Oxide Source (an observed lot property, D-006/D-014) declared
        # as a lot-level treatment with 4 lots per level.
        d = designs.t1()
        d["claimed_template"] = "T2"
        d["hierarchy"][0]["count"] = 8
        d["treatments"] = [{"name": "source", "column": "Source", "levels": ["1", "2"],
                            "applied_to": "lot", "replicates_per_level": 4,
                            "assignment": {"method": "inherent"}}]
        d["comparisons"] = [{"id": "s", "kind": "overall", "factors": ["source"]}]
        self.assertRefused(d, {"T2.treatment_applied_not_inherent"}, {"assignment"})

    def test_assignment_methods_other_than_inherent_accepted(self):
        for method in ("randomized", "systematic", "not_stated"):
            with self.subTest(method=method):
                d = designs.t2()
                d["treatments"][0]["assignment"]["method"] = method
                self.assertMatched(d, "T2")

    def test_two_blocks(self):
        d = designs.t2_block()
        d["nuisance_factors"].append({"name": "day", "column": "day", "recorded_at": "run",
                                      "role": "block", "levels": ["1", "2"],
                                      "crossed_with": "temp"})
        self.assertRefused(d, {"T2.supported_block"}, {"blocking"})

    def test_block_at_subsampling_level(self):
        d = designs.t2_block()
        d["nuisance_factors"][0]["recorded_at"] = "wafer"
        self.assertRefused(d, {"T2.supported_block"}, {"blocking"})

    def test_block_unbalanced_crossing(self):
        # 4 runs per level cannot be split equally over 3 chambers.
        d = designs.t2_block()
        d["nuisance_factors"][0]["levels"] = ["A", "B", "C"]
        self.assertRefused(d, {"T2.supported_block"}, {"blocking"})

    def test_block_with_one_level(self):
        d = designs.t2_block()
        d["nuisance_factors"][0]["levels"] = ["A"]
        self.assertRefused(d, {"T2.supported_block"})

    def test_recorded_nuisance_any_level_ok(self):
        d = designs.t2_block()
        d["nuisance_factors"].append({"name": "tool", "column": "tool", "recorded_at": "site",
                                      "role": "recorded"})
        self.assertMatched(d, "T2")

    def test_split_plot_declared_under_t2(self):
        d = designs.t3()
        d["claimed_template"] = "T2"
        res = self.assertRefused(d, {"T2.one_treatment", "T2.no_split_plot"})
        self.assertIn("T3", " ".join(r.remedy for r in res.refusals))

    def test_exchangeability_is_recorded_not_gating(self):
        # D-037: complete balanced T2 matches whatever the site semantics; WP2 applies
        # the missing-site policy (D-016, D-021, D-022, D-028) using this field.
        for value in (True, False, None):
            with self.subTest(exchangeable=value):
                d = designs.t2()
                if value is not None:
                    d["hierarchy"][2]["exchangeable"] = value
                res = self.assertMatched(d, "T2")
                site = res.declaration.bottom
                self.assertIs(site.exchangeable, bool(value))
                self.assertEqual(site.exchangeable_declared, value is not None)


# ---------------------------------------------------------------------------
class T3Matching(MatchCase):
    def test_valid_t3(self):
        self.assertMatched(designs.t3(), "T3")

    def test_minimal_t3(self):
        d = designs.t3()
        d["hierarchy"][0]["count"] = 4
        d["hierarchy"][1]["count_per_parent"] = 2
        d["treatments"][0].update(levels=["a", "b"], replicates_per_level=2)
        d["treatments"][1].update(levels=["p", "q"], replicates_per_level=4)
        self.assertMatched(d, "T3")

    def test_missing_split_plot_roles_not_converted(self):
        d = designs.t3()
        del d["split_plot"]
        res = self.assertRefused(d, {"T3.split_plot_roles"}, {"split_plot"})
        self.assertEqual(res.claimed_template, "T3")
        statuses = {c.id: c.status for c in res.conditions}
        self.assertEqual(statuses["T3.subplot_complete"], "not_evaluated")

    def test_t2_shaped_declaration_claimed_as_t3_not_converted(self):
        # A valid T2 structure, claimed as T3: refused, never matched as T2.
        d = designs.t2()
        d["claimed_template"] = "T3"
        res = self.assertRefused(d, {"T3.split_plot_roles", "T3.two_level_hierarchy"})
        self.assertIsNone(res.matched_template)

    def test_both_factors_on_whole_plots(self):
        # A factorial on wafers dressed as a split-plot.
        d = designs.t3()
        d["treatments"][1].update(applied_to="wafer", column="angle", replicates_per_level=3)
        res = self.assertRefused(d, {"T3.subplot_factor_on_subplots", "T3.subplot_complete"},
                                 {"application_level", "balance"})
        self.assertIn("not a split-plot", res.refusals[0].reason)

    def test_roles_swapped(self):
        d = designs.t3()
        d["split_plot"] = {"whole_plot_factor": "pos", "subplot_factor": "etch"}
        self.assertRefused(d, {"T3.whole_plot_factor_on_whole_plots",
                               "T3.subplot_factor_on_subplots",
                               "T3.whole_plot_factor_applied_not_inherent",
                               "T3.subplot_complete", "T3.factor_columns"})
        # Balance of A is not evaluated when A is not on the whole plots.

    def test_subsampling_inside_subplots(self):
        d = designs.t3()
        d["hierarchy"].append({"name": "scan", "id_column": "scan", "nested_in": "position",
                               "count_per_parent": 3})
        res = self.assertRefused(d, {"T3.two_level_hierarchy"}, {"hierarchy"})
        statuses = {c.id: c.status for c in res.conditions}
        self.assertEqual(statuses["T3.subplot_factor_on_subplots"], "not_evaluated")

    def test_unreplicated_whole_plots(self):
        d = designs.t3()
        d["hierarchy"][0]["count"] = 4
        d["treatments"][0]["replicates_per_level"] = 1
        d["treatments"][1]["replicates_per_level"] = 4
        self.assertRefused(d, {"T3.whole_plot_replicated"}, {"replication"})

    def test_single_subplot_level_refused_as_t3(self):
        # D-021 C-3: one B level -> B and AxB not estimable; refused, not reclassified.
        d = designs.t3()
        d["hierarchy"][1]["count_per_parent"] = 1
        d["treatments"][1]["levels"] = ["1"]
        d["comparisons"] = [{"id": "etch", "kind": "overall", "factors": ["etch"]}]
        res = self.assertRefused(d, {"T3.subplot_complete"}, {"balance"})
        self.assertIn("not reclassified", res.refusals[0].remedy)

    def test_incomplete_subplots(self):
        d = designs.t3()
        d["hierarchy"][1]["count_per_parent"] = 3
        self.assertRefused(d, {"T3.subplot_complete"})

    def test_subplot_replicates_inconsistent(self):
        d = designs.t3()
        d["treatments"][1]["replicates_per_level"] = 3
        self.assertRefused(d, {"T3.subplot_complete"})

    def test_whole_plot_counts_inconsistent(self):
        d = designs.t3()
        d["hierarchy"][0]["count"] = 10
        self.assertRefused(d, {"T3.whole_plot_balance", "T3.subplot_complete"}, {"balance"})

    def test_subplot_declared_exchangeable(self):
        d = designs.t3()
        d["hierarchy"][1]["exchangeable"] = True
        self.assertRefused(d, {"T3.subplot_not_exchangeable"}, {"exchangeability"})

    def test_subplot_declared_nonexchangeable_ok(self):
        d = designs.t3()
        d["hierarchy"][1]["exchangeable"] = False
        self.assertMatched(d, "T3")

    def test_three_treatments(self):
        d = designs.t3()
        d["treatments"].append({"name": "dose", "column": "dose", "levels": ["lo", "hi"],
                                "applied_to": "wafer", "replicates_per_level": 6,
                                "assignment": {"method": "randomized"}})
        self.assertRefused(d, {"T3.split_plot_roles"}, {"split_plot"})

    def test_block_in_t3(self):
        d = designs.t3()
        d["nuisance_factors"] = [{"name": "chamber", "column": "chamber",
                                  "recorded_at": "wafer", "role": "block",
                                  "levels": ["A", "B", "C"], "crossed_with": "etch"}]
        self.assertRefused(d, {"T3.no_blocking"}, {"blocking"})

    def test_whole_plot_factor_column_is_wafer_id(self):
        d = designs.t3()
        d["treatments"][0]["column"] = "wafer"
        self.assertRefused(d, {"T3.factor_columns"})

    def test_inherent_whole_plot_factor(self):
        d = designs.t3()
        d["treatments"][0]["assignment"]["method"] = "inherent"
        self.assertRefused(d, {"T3.whole_plot_factor_applied_not_inherent"}, {"assignment"})

    def test_no_comparison(self):
        d = designs.t3()
        d["comparisons"] = []
        self.assertRefused(d, {"T3.comparisons"}, {"comparison"})


# ---------------------------------------------------------------------------
class UnknownTemplate(unittest.TestCase):
    def test_unknown_claims(self):
        for claim in ("T4", "t2", "T2 ", "split-plot", "general_mixed_model"):
            with self.subTest(claim=claim):
                d = designs.t2()
                d["claimed_template"] = claim
                res = evaluate(d)
                self.assertEqual(res.decision, "refused")
                self.assertEqual(res.refusal_categories, ("unknown_template",))
                self.assertEqual(res.conditions, ())

    def test_non_text_claim_is_schema_error(self):
        d = designs.t2()
        d["claimed_template"] = 2
        res = evaluate(d)
        self.assertEqual(res.refusal_categories, ("schema",))


class UnsupportedMixedOrCrossed(unittest.TestCase):
    """Arbitrary mixed or crossed structures cannot be declared into a template."""

    def test_crossed_random_factor_via_branching_hierarchy(self):
        # operator and wafer both nested in run (operator x wafer crossed within run).
        d = designs.t2()
        d["hierarchy"] = [
            {"name": "run", "id_column": "run", "count": 8},
            {"name": "wafer", "id_column": "wafer", "nested_in": "run", "count_per_parent": 2},
            {"name": "operator", "id_column": "operator", "nested_in": "run",
             "count_per_parent": 2},
        ]
        res = evaluate(d)
        self.assertEqual(res.decision, "refused")
        self.assertEqual(res.refusal_categories, ("hierarchy",))

    def test_random_effect_syntax_rejected(self):
        d = designs.t2()
        d["random_effects"] = "(1|run) + (1|run:wafer) + (1|tool)"
        res = evaluate(d)
        self.assertEqual(res.decision, "refused")
        self.assertEqual(res.refusal_categories, ("schema",))

    def test_nuisance_as_random_effect_rejected(self):
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "tool", "column": "tool", "recorded_at": "run",
                                  "role": "random"}]
        self.assertEqual(evaluate(d).refusal_categories, ("schema",))

    def test_crossed_with_on_hierarchy_level_rejected(self):
        d = designs.t1()
        d["hierarchy"][2]["crossed_with"] = "wafer"
        self.assertEqual(evaluate(d).decision, "refused")

    def test_two_crossed_blocks(self):
        d = designs.t2_block()
        d["nuisance_factors"].append({"name": "day", "column": "day", "recorded_at": "run",
                                      "role": "block", "levels": ["1", "2"],
                                      "crossed_with": "temp"})
        res = evaluate(d)
        self.assertEqual(res.failed_conditions, ("T2.supported_block",))


class RefusalText(unittest.TestCase):
    def test_explain_is_readable(self):
        d = designs.t2()
        d["treatments"][0]["replicates_per_level"] = 1
        d["hierarchy"][0]["count"] = 2
        text = evaluate(d).explain()
        self.assertTrue(text.startswith("REFUSED"))
        for part in ("Declared:", "Requirement:", "Why:", "To proceed:", "T2.replicated"):
            self.assertIn(part, text)

    def test_refusal_never_contains_statistics(self):
        # A refusal carries no estimate, p-value or F statistic.
        d = designs.t2()
        d["treatments"][0]["replicates_per_level"] = 1
        d["hierarchy"][0]["count"] = 2
        text = evaluate(d).explain().lower()
        for word in ("p-value", "p =", "estimate =", "f ="):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
