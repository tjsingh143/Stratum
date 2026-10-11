"""WP2: every preregistered SYNTHETIC fixture against the checker (DECISIONS.md D-050,
D-051).
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "fixtures" / "synthetic_wp2"

spec = importlib.util.spec_from_file_location("wp2_run", HERE / "run_fixtures.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class FixturesMatchPreregistration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.refs = runner.run_all()

    def test_every_fixture_has_a_result(self):
        reg = json.loads((HERE / "expectations.json").read_text())
        self.assertEqual([r["id"] for r in self.rows], [f["id"] for f in reg["fixtures"]])

    def test_every_fixture_matches_its_current_expectation(self):
        for r in self.rows:
            with self.subTest(fixture=r["id"]):
                self.assertTrue(r["match"], r)

    def test_version_one_mismatches_are_exactly_the_documented_corrections(self):
        reg = json.loads((HERE / "expectations.json").read_text())
        documented = {c["fixture_id"] for c in reg["corrections"]}
        self.assertEqual({r["id"] for r in self.rows if not r["v1_match"]}, documented)
        self.assertEqual(documented, {"ALIAS-05"})          # D-053 only

    def test_reference_datasets_have_no_refusal(self):
        for r in self.refs:
            with self.subTest(dataset=r["id"]):
                self.assertTrue(r["ok"], r["status"])


if __name__ == "__main__":
    unittest.main()
