"""WP2 Stage A: the synthetic fixtures regenerate exactly, and the preregistration
registry is complete and well formed (DECISIONS.md D-050).

These tests never import or run the evidence checker. They check form, not whether
any expected decision is statistically correct.
"""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic_wp2"


def _load(name):
    spec = importlib.util.spec_from_file_location("wp2_" + name, FIXTURES / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


generate = _load("generate")
validator = _load("validate_registry")
REGISTRY = json.loads((FIXTURES / "expectations.json").read_text(encoding="utf-8"))


class FixtureGeneration(unittest.TestCase):
    def test_files_match_generator(self):
        self.assertEqual(generate.main(["--check"]), 0)

    def test_generator_is_deterministic(self):
        a = [(f.id, f.decl_text(), f.data_text()) for f in generate.build()]
        b = [(f.id, f.decl_text(), f.data_text()) for f in generate.build()]
        self.assertEqual(a, b)

    def test_generator_holds_no_expectations(self):
        text = (FIXTURES / "generate.py").read_text(encoding="utf-8")
        for word in ("expected_decision", "expected_categories", "ANALYZE", "REFUSE",
                     "expectations.json\"", "import stratum", "from stratum"):
            self.assertNotIn(word, text)

    def test_every_fixture_is_labeled_synthetic(self):
        for d in sorted(p for p in FIXTURES.iterdir() if p.is_dir() and "-" in p.name):
            with self.subTest(fixture=d.name):
                self.assertEqual(sorted(x.name for x in d.iterdir()),
                                 ["data_synthetic.csv", "declaration_synthetic.yaml"])
                head = (d / "declaration_synthetic.yaml").read_text(encoding="utf-8")
                self.assertTrue(head.startswith("# SYNTHETIC"))
                self.assertIn("SYNTHETIC FIXTURE %s" % d.name, head)

    def test_values_are_exact_decimals(self):
        from fractions import Fraction
        self.assertEqual(generate.fmt(Fraction(201, 2)), "100.5")
        self.assertEqual(generate.fmt(Fraction(-3, 20)), "-0.15")
        self.assertEqual(generate.fmt(Fraction(7)), "7")
        self.assertEqual(generate.centered(4, Fraction(1)),
                         [Fraction(-3, 2), Fraction(-1, 2), Fraction(1, 2), Fraction(3, 2)])
        with self.assertRaises(ValueError):
            generate.fmt(Fraction(1, 3))


class RegistryIsWellFormed(unittest.TestCase):
    def problems(self, reg):
        return validator.validate(reg, FIXTURES)

    def test_registry_valid(self):
        self.assertEqual(self.problems(REGISTRY), [])

    def test_counts_and_vocabulary_size(self):
        self.assertEqual(len(REGISTRY["fixtures"]), 65)
        self.assertEqual(len(REGISTRY["vocabulary"]), 31)   # D-048, frozen
        # Post-freeze, appended only: one code (D-053) and one specification correction.
        self.assertEqual([a["code"] for a in REGISTRY["vocabulary_amendments"]],
                         ["nuisance_unit_unique"])
        self.assertEqual([(c["fixture_id"], c["judged_wrong"], c["decisions_entry"])
                          for c in REGISTRY["corrections"]],
                         [("ALIAS-05", "specification_clarification", "D-053")])
        self.assertEqual(validator.effective_expectations(REGISTRY)["ALIAS-05"],
                         (2, "WARN", ("nuisance_unit_unique",)))

    def test_no_checker_output_recorded(self):
        text = json.dumps(REGISTRY)
        for word in ("actual_decision", "actual_categories", "observed_decision"):
            self.assertNotIn(word, text)

    def test_required_fixture_cases_present(self):
        # Cases the WP2 instructions and D-022/D-028 name explicitly.
        ids = {f["id"] for f in REGISTRY["fixtures"]}
        for fid in ("HIER-01", "HIER-02", "HIER-03", "HIER-04", "CONS-01", "CONS-02",
                    "CONS-03", "CONS-04", "REP-01", "REP-02", "BAL-01", "BAL-02", "BAL-03",
                    "BAL-04", "BAL-05", "MISS-01", "MISS-02", "MISS-03", "MISS-04", "MISS-05",
                    "MISS-06", "MISS-07", "MISS-08", "MISS-10", "MISS-12", "MISS-13", "MISS-15",
                    "CONF-01", "CONF-02", "CONF-03", "CONF-05", "CONF-06", "ALIAS-01",
                    "ALIAS-02", "ALIAS-03", "ALIAS-04", "DIAG-01", "DIAG-02", "DIAG-03",
                    "DIAG-04", "T3-01", "T3-02", "T3-03", "BLK-01", "BLK-02", "BLK-03"):
            self.assertIn(fid, ids)

    def test_validator_catches_planted_errors(self):
        def broken(mutate):
            reg = copy.deepcopy(REGISTRY)
            mutate(reg)
            return self.problems(reg)

        def fx(reg, fid):
            return next(f for f in reg["fixtures"] if f["id"] == fid)

        cases = {
            "missing field": lambda r: fx(r, "CONF-05").pop("rationale"),
            "unknown code": lambda r: fx(r, "CONF-05").update(expected_categories=["weird"]),
            "decision vs severity": lambda r: fx(r, "DIAG-02").update(expected_decision="REFUSE"),
            "note-only marked WARN": lambda r: fx(r, "DIAG-04").update(expected_decision="WARN"),
            "duplicate id": lambda r: r["fixtures"].append(copy.deepcopy(fx(r, "BAL-01"))),
            "template mismatch": lambda r: fx(r, "T3-01").update(claimed_template="T2"),
            "entry removed": lambda r: r["fixtures"].remove(fx(r, "MISS-19")),
            "statement altered": lambda r: fx(r, "BAL-01").update(preregistered="later"),
            "not synthetic": lambda r: fx(r, "BAL-01").update(synthetic=False),
            "version edited": lambda r: fx(r, "BAL-01").update(expectation_version=2),
            "claim altered": lambda r: r.update(project_claim="Written by hand."),
            "uncovered code": lambda r: [f.update(expected_categories=[
                c for c in f["expected_categories"] if c != "sd_ratio"])
                for f in r["fixtures"]],
            "bad correction": lambda r: r["corrections"].append({"fixture_id": "BAL-01"}),
            "redefined code": lambda r: r["vocabulary_amendments"].append(
                dict(r["vocabulary_amendments"][0], code="sd_ratio")),
            "v1 uses amended code": lambda r: fx(r, "BAL-01").update(
                expected_decision="WARN", expected_categories=["nuisance_unit_unique"]),
            "clarification without corrected": lambda r: r["corrections"][0].update(
                corrected=None),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.assertNotEqual(broken(mutate), [])

    def test_correction_record_shape(self):
        reg = copy.deepcopy(REGISTRY)
        reg["corrections"].append({
            "fixture_id": "BAL-01", "new_version": 2, "date": "2026-10-04",
            "previous": {"decision": "ANALYZE", "categories": []},
            "observed": {"decision": "WARN", "categories": ["sd_ratio"]},
            "corrected": {"decision": "WARN", "categories": ["sd_ratio"]},
            "reason": "planted test record", "judged_wrong": "expectation",
            "decisions_entry": "D-999"})
        self.assertEqual(self.problems(reg), [])
        eff = validator.effective_expectations(reg)
        self.assertEqual(eff["BAL-01"], (2, "WARN", ("sd_ratio",)))
        # The version-1 entry itself is untouched by a correction.
        self.assertEqual(next(f for f in reg["fixtures"] if f["id"] == "BAL-01")
                         ["expected_decision"], "ANALYZE")
        reg["corrections"][0]["new_version"] = 3
        self.assertNotEqual(self.problems(reg), [])


if __name__ == "__main__":
    unittest.main()
