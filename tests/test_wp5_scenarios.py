"""WP5 demonstration scenarios (DECISIONS.md D-086). All scenario data are SYNTHETIC."""
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCN = ROOT / "scenarios"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN = _load("scenario_run", SCN / "run.py")
GEN = _load("scenario_generate", SCN / "generate.py")
REG = json.loads((SCN / "expectations.json").read_text(encoding="utf-8"))


class Preregistration(unittest.TestCase):
    """The preregistered expectations carry no corrections, and the inputs regenerate."""

    def test_no_corrections_were_appended(self):
        self.assertEqual(REG["corrections"], [])

    def test_the_generator_never_imports_stratum(self):
        text = (SCN / "generate.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(from|import)\s+stratum", text, re.M))

    def test_generator_reproduces_the_inputs(self):
        for path, text in GEN.files().items():
            self.assertEqual(path.read_text(encoding="utf-8"), text, path)


class Results(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = {s["id"]: RUN.run(s) for s in REG["scenarios"]}

    def test_every_preregistered_assertion_matches(self):
        for sid, out in self.out.items():
            bad = [c for c in out["comparison"]["checks"] if c["status"] != "MATCH"]
            self.assertEqual(bad, [], sid)
            self.assertEqual(out["comparison"]["status"], "MATCH", sid)

    def test_assertion_counts(self):
        self.assertEqual({k: v["comparison"]["assertions"] for k, v in self.out.items()},
                         {"S1": 45, "S2": 39, "S3": 58})

    def test_stored_outputs_regenerate_byte_for_byte(self):
        for sid, out in self.out.items():
            for path, text in out["files"].items():
                self.assertEqual(path.read_text(encoding="utf-8"), text, path)

    def test_synthetic_everywhere(self):
        for sid, out in self.out.items():
            doc = json.loads(next(t for p, t in out["files"].items()
                                  if p.name == "results.json"))
            self.assertTrue(doc["synthetic"], sid)
            self.assertIn("SYNTHETIC", doc["data_label"])
            rep = next(t for p, t in out["files"].items() if p.name == "report.md")
            self.assertIn("**SYNTHETIC DATA.**", rep)
            wu = next(t for p, t in out["files"].items() if p.name == "WRITEUP.md")
            self.assertIn("(SYNTHETIC)", wu.splitlines()[0])

    def test_s1_report_explains_why_sites_cannot_help(self):
        rep = next(t for p, t in self.out["S1"]["files"].items() if p.name == "report.md")
        self.assertIn("More measurements below the 'run' level cannot restore", rep)
        self.assertIn("Measuring more wafers or sites does not help", rep)

    def test_writeups_fill_every_placeholder_from_the_documents(self):
        for s in REG["scenarios"]:
            d = ROOT / s["directory"]
            tmpl = (d / "writeup.md.in").read_text(encoding="utf-8")
            written = (d / "WRITEUP.md").read_text(encoding="utf-8")
            self.assertNotIn("{{", written)
            self.assertGreater(len(RUN.PLACEHOLDER.findall(tmpl)), 8, s["id"])
            static = RUN.PLACEHOLDER.sub("", tmpl)
            for pat in (r"2 sigma2\[run\] / r", r"D-\d{3}", r"\bT[123]\b", r"T2\.replicated",
                        r"\bS[123]\b", r"95%", r"sigma2\[\w+\]", r"108 measurements",
                        r"48 readings", r"offset of -4"):
                static = re.sub(pat, "", static)
            # Remaining static digits are only the design-describing constant "2" in the
            # floor formula; no result value is typed into a template.
            self.assertEqual(re.findall(r"\d", static), [], s["id"])


class SafeExpression(unittest.TestCase):
    def test_arithmetic_and_whitelisted_functions_only(self):
        self.assertAlmostEqual(RUN._expr("sqrt(2 * 4 * 15 / 60) - 1"), 0.41421356237, 9)
        for bad in ("__import__('os')", "open('x')", "(1).real", "[1][0]", "a"):
            with self.assertRaises(ValueError, msg=bad):
                RUN._expr(bad)


if __name__ == "__main__":
    unittest.main()
