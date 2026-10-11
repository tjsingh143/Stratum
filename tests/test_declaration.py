"""WP1: declaration parsing and template-independent validation."""
import unittest

import designs
from stratum.declaration import load_declaration, parse_declaration
from stratum.templates import evaluate


def categories(result):
    return {r.category for r in result.refusals}


def paths(result):
    return {r.path for r in result.refusals}


class ValidDeclarations(unittest.TestCase):
    def test_bases_parse(self):
        for base in (designs.t1, designs.t2, designs.t2_block, designs.t3):
            with self.subTest(base=base.__name__):
                self.assertTrue(parse_declaration(base()).ok)

    def test_parsed_fields(self):
        d = parse_declaration(designs.t2_block()).declaration
        self.assertEqual(d.claimed_template, "T2")
        self.assertEqual(d.response.column, "y")
        self.assertEqual([lv.name for lv in d.hierarchy], ["run", "wafer", "site"])
        self.assertEqual(d.top.count, 8)
        self.assertEqual(d.total_units("site"), 8 * 2 * 5)
        self.assertEqual(d.treatments[0].applied_to, "run")
        self.assertEqual(d.blocks[0].crossed_with, "temp")

    def test_units_may_be_declared_unstated(self):
        d = parse_declaration(designs.t3()).declaration
        self.assertIsNone(d.response.units)


class MissingRequiredFields(unittest.TestCase):
    def test_each_required_top_level_field(self):
        for key in ("stratum_declaration", "claimed_template", "response", "hierarchy",
                    "treatments", "nuisance_factors", "comparisons"):
            with self.subTest(key=key):
                d = designs.t1()
                del d[key]
                r = parse_declaration(d)
                self.assertFalse(r.ok)
                self.assertIn("declaration." + key, paths(r))
                self.assertEqual(categories(r), {"schema"})

    def test_response_units_key_is_required(self):
        # Units may be null (not stated by the source) but must be declared.
        d = designs.t1()
        del d["response"]["units"]
        r = parse_declaration(d)
        self.assertIn("response.units", paths(r))

    def test_treatment_fields_required(self):
        for key in ("name", "column", "levels", "applied_to", "replicates_per_level",
                    "assignment"):
            with self.subTest(key=key):
                d = designs.t2()
                del d["treatments"][0][key]
                r = parse_declaration(d)
                self.assertIn("treatments[0].%s" % key, paths(r))

    def test_assignment_method_required(self):
        d = designs.t2()
        d["treatments"][0]["assignment"] = {"description": "by hand"}
        self.assertIn("treatments[0].assignment.method", paths(parse_declaration(d)))

    def test_level_fields_required(self):
        d = designs.t1()
        del d["hierarchy"][1]["count_per_parent"]
        self.assertIn("hierarchy[1].count_per_parent", paths(parse_declaration(d)))
        d = designs.t1()
        del d["hierarchy"][2]["nested_in"]
        self.assertIn("hierarchy[2].nested_in", paths(parse_declaration(d)))

    def test_block_needs_levels_and_crossed_with(self):
        d = designs.t2_block()
        del d["nuisance_factors"][0]["crossed_with"]
        r = parse_declaration(d)
        self.assertFalse(r.ok)
        self.assertEqual(categories(r), {"schema"})

    def test_missing_field_is_refused_end_to_end(self):
        d = designs.t2()
        del d["treatments"][0]["applied_to"]
        res = evaluate(d)
        self.assertEqual(res.decision, "refused")
        self.assertIsNone(res.matched_template)
        self.assertEqual(res.conditions, ())


class UnknownAndMalformedFields(unittest.TestCase):
    def test_unknown_top_level_field(self):
        d = designs.t1()
        d["random_effects"] = ["(1|lot)"]
        r = parse_declaration(d)
        self.assertIn("declaration.random_effects", paths(r))

    def test_unknown_level_field(self):
        d = designs.t1()
        d["hierarchy"][1]["crossed_with"] = "lot"
        self.assertIn("hierarchy[1].crossed_with", paths(parse_declaration(d)))

    def test_count_must_be_single_whole_number(self):
        for bad in ([3, 4], "3", 0, 2.5, True):
            with self.subTest(bad=bad):
                d = designs.t1()
                d["hierarchy"][1]["count_per_parent"] = bad
                self.assertIn("hierarchy[1].count_per_parent", paths(parse_declaration(d)))

    def test_wrong_schema_version(self):
        d = designs.t1()
        d["stratum_declaration"] = 2
        self.assertIn("stratum_declaration", paths(parse_declaration(d)))

    def test_bad_enum_values(self):
        d = designs.t2()
        d["treatments"][0]["assignment"]["method"] = "random"
        self.assertIn("treatments[0].assignment.method", paths(parse_declaration(d)))
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "tool", "column": "tool", "recorded_at": "run",
                                  "role": "random_effect"}]
        self.assertIn("nuisance_factors[0].role", paths(parse_declaration(d)))

    def test_not_a_mapping(self):
        r = parse_declaration(["T1"])
        self.assertFalse(r.ok)
        self.assertEqual(categories(r), {"schema"})


class YamlText(unittest.TestCase):
    T1_TEXT = """
stratum_declaration: 1
claimed_template: T1
response: {column: y, units: nm}
hierarchy:
  - {name: lot, id_column: lot, count: 4}
  - {name: wafer, id_column: wafer, nested_in: lot, count_per_parent: 2%s}
  - {name: site, id_column: site, nested_in: wafer, count_per_parent: 3%s}
treatments: []
nuisance_factors: []
comparisons: []
"""

    def test_duplicate_key_refused(self):
        text = self.T1_TEXT % ("", "") + "comparisons: []\n"
        r = load_declaration(text)
        self.assertEqual(categories(r), {"yaml_syntax"})
        self.assertIn("duplicate key", r.refusals[0].declared)

    def test_syntax_error_refused(self):
        r = load_declaration("claimed_template: [T1\n")
        self.assertEqual(categories(r), {"yaml_syntax"})

    def test_exchangeable_true_parsed(self):
        r = load_declaration(self.T1_TEXT % ("", ", exchangeable: true"))
        site = r.declaration.level("site")
        self.assertIs(site.exchangeable, True)
        self.assertTrue(site.exchangeable_declared)

    def test_nonexchangeable_declared_parsed(self):
        r = load_declaration(self.T1_TEXT % (", exchangeable: false", ", exchangeable: false"))
        for name in ("wafer", "site"):
            lv = r.declaration.level(name)
            self.assertIs(lv.exchangeable, False)
            self.assertTrue(lv.exchangeable_declared)

    def test_exchangeability_default_is_nonexchangeable(self):
        # D-022: if not declared exchangeable, sites are NOT established as exchangeable.
        r = load_declaration(self.T1_TEXT % ("", ""))
        for name in ("wafer", "site"):
            lv = r.declaration.level(name)
            self.assertIs(lv.exchangeable, False)
            self.assertFalse(lv.exchangeable_declared)
        self.assertIsNone(r.declaration.level("lot").exchangeable)

    def test_exchangeable_must_be_boolean(self):
        r = load_declaration(self.T1_TEXT % ("", ", exchangeable: maybe"))
        self.assertIn("hierarchy[2].exchangeable", paths(r))

    def test_exchangeable_not_allowed_on_top_level(self):
        d = designs.t1()
        d["hierarchy"][0]["exchangeable"] = True
        r = parse_declaration(d)
        self.assertIn("hierarchy[0].exchangeable", paths(r))
        self.assertIn("hierarchy", categories(r))

    def test_unquoted_yaml_boolean_label_refused(self):
        # YAML 1.1 reads an unquoted "no" as false; Stratum refuses rather than guessing.
        text = """
stratum_declaration: 1
claimed_template: T2
response: {column: y, units: nm}
hierarchy:
  - {name: run, id_column: run, count: 4}
  - {name: site, id_column: site, nested_in: run, count_per_parent: 3}
treatments:
  - {name: coat, column: coat, levels: [yes, no], applied_to: run,
     replicates_per_level: 2, assignment: {method: randomized}}
nuisance_factors: []
comparisons: [{id: c, kind: overall, factors: [coat]}]
"""
        r = load_declaration(text)
        self.assertIn("treatments[0].levels[0]", paths(r))

    def test_numeric_labels_normalised_to_text(self):
        d = designs.t3()
        d["treatments"][0]["levels"] = [1, 2, 3, 4]
        r = parse_declaration(d)
        self.assertEqual(r.declaration.treatments[0].levels, ("1", "2", "3", "4"))

    def test_labels_colliding_as_text_refused(self):
        d = designs.t3()
        d["treatments"][0]["levels"] = [1, "1", 2, 3]
        self.assertIn("treatments[0].levels", paths(parse_declaration(d)))


class InvalidHierarchy(unittest.TestCase):
    def test_nested_in_unknown_level(self):
        d = designs.t1()
        d["hierarchy"][2]["nested_in"] = "chip"
        r = parse_declaration(d)
        self.assertEqual(categories(r), {"inconsistent_declaration"})

    def test_branching_nesting_refused(self):
        # wafer and site both nested directly in lot: not a chain.
        d = designs.t1()
        d["hierarchy"][2]["nested_in"] = "lot"
        r = parse_declaration(d)
        self.assertEqual(categories(r), {"hierarchy"})
        self.assertIn("hierarchy[2].nested_in", paths(r))

    def test_out_of_order_refused(self):
        d = designs.t1()
        d["hierarchy"][1]["nested_in"] = "site"
        self.assertIn("hierarchy", categories(parse_declaration(d)))

    def test_self_nesting_refused(self):
        d = designs.t1()
        d["hierarchy"][1]["nested_in"] = "wafer"
        self.assertIn("hierarchy", categories(parse_declaration(d)))

    def test_top_level_with_nesting_fields_refused(self):
        d = designs.t1()
        d["hierarchy"][0]["nested_in"] = "fab"
        r = parse_declaration(d)
        self.assertIn("hierarchy", categories(r))

    def test_duplicate_level_names(self):
        d = designs.t1()
        d["hierarchy"][2]["name"] = "wafer"
        d["hierarchy"][2]["nested_in"] = "wafer"
        self.assertIn("inconsistent_declaration", categories(parse_declaration(d)))

    def test_shared_id_column_refused(self):
        d = designs.t1()
        d["hierarchy"][2]["id_column"] = "wafer"
        r = parse_declaration(d)
        self.assertEqual(categories(r), {"inconsistent_declaration"})

    def test_empty_hierarchy(self):
        d = designs.t1()
        d["hierarchy"] = []
        self.assertIn("hierarchy", paths(parse_declaration(d)))

    def test_id_scope_default_and_values(self):
        d = parse_declaration(designs.t1()).declaration
        self.assertEqual(d.level("lot").id_scope, "global")
        self.assertEqual(d.level("wafer").id_scope, "parent")
        bad = designs.t1()
        bad["hierarchy"][1]["id_scope"] = "unique"
        self.assertIn("hierarchy[1].id_scope", paths(parse_declaration(bad)))


class CrossReferences(unittest.TestCase):
    def test_treatment_applied_to_undeclared_level(self):
        d = designs.t2()
        d["treatments"][0]["applied_to"] = "lot"
        r = parse_declaration(d)
        self.assertEqual(categories(r), {"inconsistent_declaration"})
        self.assertIn("treatments[0].applied_to", paths(r))

    def test_nuisance_recorded_at_undeclared_level(self):
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "tool", "column": "tool", "recorded_at": "lot",
                                  "role": "recorded"}]
        self.assertIn("inconsistent_declaration", categories(parse_declaration(d)))

    def test_comparison_of_undeclared_factor(self):
        d = designs.t2()
        d["comparisons"][0]["factors"] = ["pressure"]
        self.assertIn("comparison", categories(parse_declaration(d)))

    def test_comparison_of_nuisance_factor_refused(self):
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "day", "column": "day", "recorded_at": "run",
                                  "role": "recorded"}]
        d["comparisons"] = [{"id": "days", "kind": "overall", "factors": ["day"]}]
        self.assertIn("comparison", categories(parse_declaration(d)))

    def test_pairwise_level_not_declared(self):
        d = designs.t2()
        d["comparisons"][0]["levels"] = ["high", "medium"]
        self.assertIn("inconsistent_declaration", categories(parse_declaration(d)))

    def test_pairwise_needs_exactly_two_levels(self):
        d = designs.t2()
        d["comparisons"][0]["levels"] = ["high"]
        self.assertIn("comparisons[0].levels", paths(parse_declaration(d)))
        d = designs.t2()
        del d["comparisons"][0]["levels"]
        self.assertIn("comparisons[0].levels", paths(parse_declaration(d)))

    def test_levels_only_for_pairwise(self):
        d = designs.t2()
        d["comparisons"][0]["kind"] = "overall"
        self.assertIn("comparisons[0].levels", paths(parse_declaration(d)))

    def test_interaction_needs_two_factors(self):
        d = designs.t3()
        d["comparisons"][2]["factors"] = ["etch"]
        self.assertIn("comparisons[2].factors", paths(parse_declaration(d)))

    def test_split_plot_names_undeclared_treatment(self):
        d = designs.t3()
        d["split_plot"]["subplot_factor"] = "angle"
        self.assertIn("inconsistent_declaration", categories(parse_declaration(d)))

    def test_split_plot_same_factor_twice(self):
        d = designs.t3()
        d["split_plot"]["subplot_factor"] = "etch"
        self.assertIn("split_plot", categories(parse_declaration(d)))

    def test_block_crossed_with_undeclared_treatment(self):
        d = designs.t2_block()
        d["nuisance_factors"][0]["crossed_with"] = "pressure"
        self.assertIn("inconsistent_declaration", categories(parse_declaration(d)))

    def test_recorded_factor_with_crossed_with(self):
        d = designs.t2_block()
        d["nuisance_factors"][0]["role"] = "recorded"
        self.assertIn("blocking", categories(parse_declaration(d)))

    def test_column_with_two_roles(self):
        d = designs.t2()
        d["response"]["column"] = "temp"
        r = parse_declaration(d)
        self.assertEqual(categories(r), {"inconsistent_declaration"})
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "day", "column": "run", "recorded_at": "run",
                                  "role": "recorded"}]
        self.assertIn("inconsistent_declaration", categories(parse_declaration(d)))

    def test_factor_name_used_twice(self):
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "temp", "column": "temp_log", "recorded_at": "run",
                                  "role": "recorded"}]
        self.assertIn("inconsistent_declaration", categories(parse_declaration(d)))


if __name__ == "__main__":
    unittest.main()
