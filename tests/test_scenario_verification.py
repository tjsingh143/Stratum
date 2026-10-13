"""Portable replay guards must still detect scientific and presentation changes."""
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

from scenarios.verify import numerical_differences, parse, verify_outputs

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("verification_scenario_run", ROOT / "scenarios/run.py")
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)


class NumericalGuard(unittest.TestCase):
    def test_only_finite_float_roundoff_is_accepted(self):
        expected = {"p": 0.22504495350464732, "status": "ANALYZE", "counts": [4, 12]}
        actual = dict(expected, p=0.2250449535046472)
        self.assertEqual(numerical_differences(expected, actual), [])
        self.assertTrue(numerical_differences(expected, dict(expected, p=0.22505)))

    def test_metadata_decisions_structure_and_types_stay_exact(self):
        expected = {"source_sha256": "abc", "status": "REFUSE", "n": 3, "flag": True}
        for actual in ({**expected, "source_sha256": "def"},
                       {**expected, "status": "ANALYZE"},
                       {**expected, "n": 3.0}, {**expected, "flag": 1},
                       {**expected, "extra": None}, {"status": "REFUSE"}):
            with self.subTest(actual=actual):
                self.assertTrue(numerical_differences(expected, actual))
        self.assertTrue(numerical_differences([1, 2], [2, 1]))
        self.assertTrue(numerical_differences([1, 2], [1]))

    def test_no_absolute_error_budget_or_nonfinite_numbers(self):
        for a, b in ((0.0, 1e-300), (1e-30, 2e-30), (math.inf, math.inf),
                     (math.nan, math.nan), (1.0, math.inf)):
            with self.subTest(a=a, b=b):
                self.assertTrue(numerical_differences(a, b))

    def test_ambiguous_or_nonfinite_json_is_rejected(self):
        for text in ('{"p": 1, "p": 2}', '{"p": NaN}', '{"p": Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(text)


class ArtifactGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        registry = json.loads((ROOT / "scenarios/expectations.json").read_text())
        cls.output = RUN.run(next(s for s in registry["scenarios"] if s["id"] == "S3"))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.files = {}
        for source, fresh in self.output["files"].items():
            path = Path(self.temp.name) / source.name
            path.write_bytes(source.read_bytes())
            self.files[path] = fresh

    def path(self, name):
        return next(p for p in self.files if p.name == name)

    def test_real_stored_scenario_and_reports_verify_portably(self):
        self.assertEqual(verify_outputs(self.files, RUN.render), [])

    def test_stored_report_corruption_is_not_hidden_by_float_tolerance(self):
        path = self.path("report.md")
        path.write_text("incorrect result\n" + path.read_text(), encoding="utf-8")
        self.assertTrue(verify_outputs(self.files, RUN.render))

    def test_fresh_report_corruption_is_rejected(self):
        self.files[self.path("report.md")] += "incorrect interpretation\n"
        self.assertTrue(verify_outputs(self.files, RUN.render))

    def test_writeup_corruption_is_rejected(self):
        self.files[self.path("WRITEUP.md")] += "untraceable result\n"
        self.assertTrue(verify_outputs(self.files, RUN.render))

    def test_missing_stored_output_is_rejected(self):
        self.path("comparison.json").unlink()
        self.assertTrue(verify_outputs(self.files, RUN.render))

    def test_strict_bytes_detect_float_spelling_and_line_endings(self):
        path = Path(self.temp.name) / "sample.json"
        path.write_bytes(b'{"p": 0.22504495350464732}\n')
        files = {path: '{"p": 0.2250449535046472}\n'}
        self.assertEqual(verify_outputs(files, RUN.render), [])
        self.assertTrue(verify_outputs(files, RUN.render, strict_bytes=True))
        path.write_bytes(b'{"p": 1.0}\r\n')
        files = {path: '{"p": 1.0}\n'}
        self.assertEqual(verify_outputs(files, RUN.render), [])
        self.assertTrue(verify_outputs(files, RUN.render, strict_bytes=True))


if __name__ == "__main__":
    unittest.main()
