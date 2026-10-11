"""WP4 results.json, the generated report, provenance and the explanation registry
(DECISIONS.md D-075, D-076, D-077). Fixture data are SYNTHETIC."""
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from stratum import __version__, explain
from stratum.cli import main as cli_main
from stratum.evidence import CODES
from stratum.refusal import CATEGORIES
from stratum.report import TRACE_CLOSE, TRACE_OPEN, Src, render, render_traced
from stratum.results import build, dumps, is_synthetic, source_hash

import wp4_helpers as H

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "fixtures" / "synthetic_wp2"
DERIVED = ROOT / "reference" / "_fetched" / "derived"
DECL = ROOT / "declarations" / "examples"
REPORTS = ROOT / "reports"


def fixture(fid):
    return FX / fid / "declaration_synthetic.yaml", FX / fid / "data_synthetic.csv"


_CACHE = {}


def doc_for(key):
    """Built once per test run and round-tripped through JSON, as a reader would see it."""
    if key not in _CACHE:
        if key in ("furnace", "semiconductor", "lithography", "oxide"):
            name = {"furnace": "t1_nist_furnace.yaml", "oxide": "t1_memss_oxide.yaml",
                    "semiconductor": "t3_sasmixed_semiconductor.yaml",
                    "lithography": "t1_nist_lithography.yaml"}[key]
            data = DERIVED / ("%s.csv" % key)
            if not data.is_file():
                raise unittest.SkipTest("needs the reference data in reference/_fetched/derived "
                                        "(see reference/README.md)")
            d = build(DECL / name, data, reproducible=True)
        else:
            d = build(*fixture(key), reproducible=True)
        _CACHE[key] = json.loads(dumps(d))
    return _CACHE[key]


ALLOWED_STATIC = [r"D-\d{3}", r"Section \d+(\.\d+)*", r"item \d", r"reading \d",
                  r"\bT[123]\b", r"\bS[0-8]\b", r"\bWP\d\b", r"SHA-256", r"95%",
                  r"^#+ \d+\.", r"x \d", r"includes 0", r"1/F_site"]


class Traceability(unittest.TestCase):
    """D-076: every number in the report is read from results.json."""

    KEYS = ("furnace", "semiconductor", "lithography", "REP-01", "BLK-01", "ALIAS-03",
            "MISS-01", "DIAG-02", "T3-01", "CONF-03", "CONF-05", "CONF-08", "REP-02",
            "DECL-01", "BAL-02", "MISS-16")

    def test_every_traced_value_matches_its_path(self):
        for key in self.KEYS:
            with self.subTest(key=key):
                doc = doc_for(key)
                text, used = render_traced(doc)
                fresh = Src(json.loads(dumps(doc)))
                self.assertGreater(len(used), 20, key)
                for path, value, shown in used:
                    if path and path[-1] == "<key>":
                        container = fresh.get(*path[:-1])
                        self.assertIn(value, container, (key, path))
                    else:
                        self.assertEqual(fresh.get(*path), value, (key, path))

    def test_static_text_has_no_data_dependent_digits(self):
        for key in self.KEYS:
            with self.subTest(key=key):
                text, _ = render_traced(doc_for(key))
                static = re.sub(re.escape(TRACE_OPEN) + ".*?" + re.escape(TRACE_CLOSE), "",
                                text, flags=re.S)
                for line in static.splitlines():
                    stripped = line
                    for pat in ALLOWED_STATIC:
                        stripped = re.sub(pat, "", stripped)
                    self.assertIsNone(re.search(r"\d", stripped),
                                      "%s: static digit in %r" % (key, line))

    def test_untraced_render_equals_traced_render_without_markers(self):
        for key in ("semiconductor", "CONF-03"):
            with self.subTest(key=key):
                doc = doc_for(key)
                text, _ = render_traced(doc)
                self.assertEqual(text.replace(TRACE_OPEN, "").replace(TRACE_CLOSE, ""),
                                 render(doc))


class ReportContent(unittest.TestCase):
    def test_required_per_comparison_content(self):
        """Brief WP4: estimate and interval, df and error term, independent units."""
        doc = doc_for("REP-01")
        comp = doc["comparisons"][0]
        self.assertEqual(comp["status"], "analyzed")
        e = comp["estimates"][0]
        for k in ("estimate", "lower", "upper", "se", "df", "error_term", "independent_units"):
            self.assertIn(k, e)
        self.assertEqual(comp["test"]["error_term"], "units within treatment")
        self.assertEqual(comp["independent_units"]["level"], "run")
        text = render(doc)
        for heading in ("## 1. Summary", "### What the data support",
                        "### What the data do not support", "### What to do next",
                        "## 2. Comparisons", "## 3. Refusals, warnings, notes and caveats",
                        "## 4. Assumptions and diagnostics", "## 5. Allocation analysis",
                        "## 6. Reassignment suggestion", "## 7. Full analysis",
                        "## 8. Evidence checks", "## 9. Provenance"):
            self.assertIn(heading, text)
        self.assertIn("| Contrast | Estimate | 95% interval | SE | df | Error term "
                      "| Independent units |", text)

    def test_refused_design_reports_reasons_and_no_estimate(self):
        doc = doc_for("CONF-05")
        self.assertFalse(doc["decision"]["analyzed"])
        self.assertEqual(doc["comparisons"][0]["estimates"], [])
        self.assertEqual(doc["analysis"]["anova"], {})
        text = render(doc)
        self.assertIn("`partial_confounding`", text)
        self.assertIn("No estimate, test or interval is reported", text)
        f = next(x for x in doc["findings"] if x["code"] == "partial_confounding")
        self.assertIn("Cramer's V", f["message"])

    def test_wp1_refusal_shows_requirement_and_remedy(self):
        doc = doc_for("DECL-01")
        r = doc["findings"][0]["wp1_refusals"][0]
        self.assertEqual(r["category"], "replication")
        self.assertTrue(r["requirement"])
        text = render(doc)
        self.assertIn("WP1 refusal `replication` (T2.replicated)", text)
        self.assertIn("Run at least two 'run' units per treatment level", text)

    def test_t3_naive_analysis_side_by_side(self):
        text = render(doc_for("semiconductor"))
        self.assertIn("### Correct analysis and the naive single-error analysis, side by "
                      "side", text)
        self.assertIn("WRONG for this design", text)
        self.assertIn("| etch_time | whole plots within etch_time | (3, 8) |", text)

    def test_published_warnings_are_carried_forward(self):
        """D-056, D-067: the two published-data warnings appear in the reports."""
        self.assertIn("sd_ratio", doc_for("semiconductor")["summary"]["warning_codes"])
        self.assertIn("studentized_residual",
                      doc_for("lithography")["summary"]["warning_codes"])

    def test_missing_site_case_is_approximate_and_allocation_withheld(self):
        doc = doc_for("MISS-01")
        self.assertEqual(doc["comparisons"][0]["status"], "analyzed_approximate")
        self.assertTrue(doc["comparisons"][0]["estimates"][0]["approximate"])
        self.assertEqual(doc["allocation"]["status"], "withheld")
        self.assertIn("approximate", [a["status"] for a in doc["assumptions"]])

    def test_synthetic_labelling(self):
        self.assertTrue(doc_for("REP-01")["synthetic"])
        self.assertIn("SYNTHETIC DATA", render(doc_for("REP-01")))
        self.assertFalse(doc_for("furnace")["synthetic"])
        self.assertNotIn("SYNTHETIC DATA", render(doc_for("furnace")))
        self.assertTrue(is_synthetic(Path("a/x_synthetic.csv")))
        self.assertFalse(is_synthetic(Path("a/furnace.csv")))

    def test_assignment_caveat(self):
        doc = doc_for("semiconductor")
        cav = [c for c in doc["caveats"] if c["code"] == "assignment_not_randomized"]
        self.assertEqual({c["details"]["method"] for c in cav}, {"not_stated", "inherent"})
        self.assertEqual(doc["decision"]["evidence_decision"], "WARN")   # unchanged by caveats

    def test_assumption_status_follows_each_diagnostic(self):
        st = {a["assumption"]: a["status"] for a in doc_for("semiconductor")["assumptions"]}
        self.assertEqual(st["equal variance across treatment levels"], "warn")
        self.assertEqual(st["normally distributed random effects and errors"],
                         "no warning triggered; assumption not verified")

    def test_every_fixture_builds_serialises_and_renders(self):
        reg = json.loads((FX / "expectations.json").read_text())
        for f in reg["fixtures"]:
            doc = build(FX / f["files"]["declaration"], FX / f["files"]["data"],
                        reproducible=True)
            text = dumps(doc)                      # allow_nan=False: no NaN or infinity
            self.assertTrue(render(json.loads(text)).startswith("# Stratum report"), f["id"])
            self.assertEqual(doc["decision"]["analyzed"],
                             doc["decision"]["evidence_decision"] != "REFUSE", f["id"])
            if not doc["decision"]["analyzed"]:
                self.assertEqual(doc["analysis"]["anova"], {}, f["id"])
                self.assertTrue(all(c["estimates"] == [] for c in doc["comparisons"]), f["id"])


class Provenance(H.TempDirCase, unittest.TestCase):
    def test_input_hashes_and_code_version(self):
        dp, cp = fixture("REP-01")
        doc = build(dp, cp)
        inp = doc["provenance"]["inputs"]
        self.assertEqual(inp["declaration"]["sha256"], hashlib.sha256(dp.read_bytes()).hexdigest())
        self.assertEqual(inp["data"]["sha256"], hashlib.sha256(cp.read_bytes()).hexdigest())
        self.assertEqual(inp["explanations"]["sha256"],
                         hashlib.sha256(explain.DEFAULT_FILE.read_bytes()).hexdigest())
        code = doc["provenance"]["code"]
        self.assertEqual(code["version"], __version__)
        files = sorted(p for p in (ROOT / "stratum").rglob("*.py")
                       if "__pycache__" not in p.parts)
        lines = ["%s %s" % (p.relative_to(ROOT).as_posix(),
                            hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
        self.assertEqual(code["source_sha256"],
                         hashlib.sha256("\n".join(lines).encode()).hexdigest())
        self.assertIsNotNone(doc["provenance"]["environment"])

    def test_reproducible_mode_omits_git_and_environment(self):
        doc = build(*fixture("REP-01"), reproducible=True)
        self.assertIsNone(doc["provenance"]["git"])
        self.assertIsNone(doc["provenance"]["environment"])
        self.assertIn("byte for byte", doc["provenance"]["omitted"])
        again = build(*fixture("REP-01"), reproducible=True)
        self.assertEqual(dumps(doc), dumps(again))

    def test_a_changed_input_changes_its_hash(self):
        dp, cp = H.write(self.tmp, H.t2_declaration(), H.t2_rows())
        a = build(dp, cp, reproducible=True)
        cp.write_text(cp.read_text().replace("100.", "101.", 1))
        b = build(dp, cp, reproducible=True)
        self.assertNotEqual(a["provenance"]["inputs"]["data"]["sha256"],
                            b["provenance"]["inputs"]["data"]["sha256"])
        self.assertEqual(a["provenance"]["code"], b["provenance"]["code"])


class Explanations(H.TempDirCase, unittest.TestCase):
    """D-075: the registry, the explanation file, verbatim insertion, pending labels."""

    def test_registry_covers_every_category(self):
        reg = explain.by_name()
        for c in CATEGORIES:
            self.assertEqual(reg[c].kind, "refusal")
        for code, (sev, _) in CODES.items():
            self.assertEqual(reg[code].kind, {"refuse": "refusal", "warn": "warning",
                                              "note": "note"}[sev])
        for c in ("assignment_not_randomized", "boundary_fit", "degenerate_fit"):
            self.assertEqual(reg[c].kind, "caveat")
        self.assertEqual(sum(1 for c in reg.values() if c.required), 47)
        self.assertEqual(sorted(c.name for c in reg.values() if not c.required),
                         ["aliased_partition", "diagnostic_unavailable"])

    def test_the_committed_file_matches_the_registry(self):
        entries = explain.load()
        self.assertEqual(set(entries), set(explain.by_name()))

    def test_scaffold_has_no_text(self):
        path = self.tmp / "e.yaml"
        path.write_text(explain.scaffold_text())
        cov = explain.coverage(explain.load(path))
        self.assertEqual((cov["required"], cov["required_written"]), (47, 0))

    def explanations_file(self, texts=None, same=None):
        raw = yaml.safe_load(explain.scaffold_text())
        for k, v in (texts or {}).items():
            raw["entries"][k]["text"] = v
        for k, v in (same or {}).items():
            raw["entries"][k]["same_as"] = v
        path = self.tmp / "explanations.yaml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
        return path

    def test_text_is_inserted_verbatim(self):
        text = "TEST TEXT: the two chambers were never compared within one level.\nSecond line."
        path = self.explanations_file({"complete_confounding": text})
        doc = json.loads(dumps(build(*fixture("CONF-03"), explanations=path,
                                     reproducible=True)))
        f = next(x for x in doc["findings"] if x["code"] == "complete_confounding")
        self.assertEqual(f["explanation"]["status"], "written")
        self.assertEqual(f["explanation"]["text"], text)
        rep = render(doc)
        self.assertIn("**Explanation:** " + text, rep)
        self.assertEqual(doc["explanations"]["required_written"], 1)
        self.assertNotIn("complete_confounding", doc["summary"]["pending_in_report"])

    def test_same_as_reuses_text(self):
        path = self.explanations_file({"insufficient_replication": "SHARED"},
                                {"replication": "insufficient_replication"})
        doc = json.loads(dumps(build(*fixture("DECL-01"), explanations=path,
                                     reproducible=True)))
        r = doc["findings"][0]["wp1_refusals"][0]["explanation"]
        self.assertEqual((r["status"], r["text"], r["same_as"]),
                         ("written", "SHARED", "insufficient_replication"))

    def test_pending_is_shown_as_pending(self):
        path = self.tmp / "scaffold.yaml"
        path.write_text(explain.scaffold_text())
        doc = json.loads(dumps(build(*fixture("CONF-03"), explanations=path,
                                     reproducible=True)))
        f = next(x for x in doc["findings"] if x["code"] == "complete_confounding")
        self.assertEqual(f["explanation"]["status"], "pending")
        self.assertIsNone(f["explanation"]["text"])
        self.assertIn("has not been written yet", render(doc))
        self.assertIn("complete_confounding", doc["summary"]["pending_in_report"])

    def test_the_committed_file_is_complete(self):
        """D-084: every category, required and optional, has its text."""
        cov = explain.coverage(explain.load())
        self.assertEqual((cov["required_written"], cov["required_pending"]), (47, []))
        self.assertEqual(cov["optional_written"], 2)

    def test_no_authorship_claim_in_reports(self):
        """No report labels the explanation texts with a personal authorship claim."""
        rep = render(doc_for("CONF-03"))
        self.assertNotIn("written by the author", rep)
        self.assertIn("**Explanation:** " + explain.load()["complete_confounding"]["text"], rep)

    def test_invalid_files_are_refused(self):
        raw = yaml.safe_load(explain.scaffold_text())
        bad = []
        r1 = json.loads(json.dumps(raw)); del r1["entries"]["schema"]; bad.append(r1)        # noqa
        r2 = json.loads(json.dumps(raw)); r2["entries"]["nope"] = {"kind": "refusal",       # noqa
                                                                    "text": None}
        bad.append(r2)
        r3 = json.loads(json.dumps(raw)); r3["entries"]["sd_ratio"]["kind"] = "refusal"     # noqa
        bad.append(r3)
        r4 = json.loads(json.dumps(raw)); r4["entries"]["sd_ratio"]["text"] = "  "          # noqa
        bad.append(r4)
        r5 = json.loads(json.dumps(raw)); r5["entries"]["sd_ratio"].update(                 # noqa
            text="x", same_as="brown_forsythe")
        bad.append(r5)
        r6 = json.loads(json.dumps(raw)); r6["format"] = "other"                            # noqa
        bad.append(r6)
        for i, r in enumerate(bad):
            path = self.tmp / ("bad%d.yaml" % i)
            path.write_text(yaml.safe_dump(r))
            with self.assertRaises(explain.ExplanationError, msg=str(i)):
                explain.load(path)
        dup = self.tmp / "dup.yaml"
        dup.write_text(explain.scaffold_text() + "  schema:\n    kind: refusal\n    text: null\n")
        with self.assertRaises(explain.ExplanationError):
            explain.load(dup)


class CommittedOutputs(unittest.TestCase):
    def test_each_committed_report_renders_from_its_results_json(self):
        n = 0
        for res in sorted(REPORTS.glob("*/*/results.json")):
            doc = json.loads(res.read_text(encoding="utf-8"))
            self.assertEqual(res.with_name("report.md").read_text(encoding="utf-8"),
                             render(doc), res)
            self.assertEqual(doc["schema"], "stratum-results/1")
            n += 1
        self.assertEqual(n, 18)

    def test_committed_reports_record_the_current_code(self):
        want = source_hash()["source_sha256"]
        for res in sorted(REPORTS.glob("*/*/results.json")):
            doc = json.loads(res.read_text(encoding="utf-8"))
            self.assertEqual(doc["provenance"]["code"]["source_sha256"], want, res)

    def test_wp3_reproduction_records_the_code_version(self):
        """D-077 applies to every run, including the WP3 reproduction output."""
        data = json.loads((ROOT / "validation" / "wp3_reproduction.json").read_text())
        self.assertEqual(data["code_version"], source_hash())
        for name in ("furnace", "oxide", "semiconductor", "lithography"):
            inp = data["analyses"][name]["inputs"]
            self.assertEqual(inp["declaration_sha256"], hashlib.sha256(
                (ROOT / inp["declaration"]).read_bytes()).hexdigest())

    def test_every_committed_report_uses_the_texts_verbatim(self):
        """Each finding's and caveat's explanation in every committed report is the file's
        text, verbatim, and nothing is pending."""
        entries = explain.load()
        seen = set()
        for res in sorted(REPORTS.glob("*/*/results.json")):
            doc = json.loads(res.read_text(encoding="utf-8"))
            rep = res.with_name("report.md").read_text(encoding="utf-8")
            self.assertEqual(doc["summary"]["pending_in_report"], [], res)
            items = doc["findings"] + doc["caveats"]
            exps = [i["explanation"] for i in items]
            for i in doc["findings"]:
                exps += [r["explanation"] for r in i.get("wp1_refusals", [])]
            for e in exps:
                self.assertEqual(e["status"], "written", (res, e["category"]))
                self.assertEqual(e["text"], explain.lookup(entries, e["category"])["text"])
                self.assertIn("**Explanation:** " + e["text"], rep)
                seen.add(e["category"])
        self.assertGreaterEqual(len(seen), 14)

    def test_synthetic_reports_live_under_synthetic_names(self):
        for res in sorted(REPORTS.glob("*/*/results.json")):
            doc = json.loads(res.read_text(encoding="utf-8"))
            self.assertEqual(doc["synthetic"], "synthetic" in res.parts[-3], res)


IN_GIT_CHECKOUT = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                                 capture_output=True).returncode == 0


class Cli(H.TempDirCase, unittest.TestCase):
    def test_analyze_then_report(self):
        dp, cp = fixture("REP-01")
        out = self.tmp / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(["analyze", str(dp), str(cp), "--out", str(out)]), 0)
        doc = json.loads((out / "results.json").read_text())
        self.assertEqual((out / "report.md").read_text(), render(doc))
        rep = self.tmp / "again.md"
        self.assertEqual(cli_main(["report", str(out / "results.json"), "--out", str(rep)]), 0)
        self.assertEqual(rep.read_text(), (out / "report.md").read_text())

    @unittest.skipUnless(IN_GIT_CHECKOUT, "not a Git checkout")
    def test_cli_records_git_provenance_in_a_checkout(self):
        dp, cp = fixture("REP-01")
        out = self.tmp / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(["analyze", str(dp), str(cp), "--out", str(out)]), 0)
        doc = json.loads((out / "results.json").read_text())
        self.assertIsNotNone(doc["provenance"]["git"])

    def test_module_entry_point(self):
        proc = subprocess.run([sys.executable, "-m", "stratum", "explanations"], cwd=ROOT,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("matches the registry", proc.stdout)


if __name__ == "__main__":
    unittest.main()
