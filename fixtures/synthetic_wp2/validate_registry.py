#!/usr/bin/env python3
"""Validate the WP2 preregistration registry (DECISIONS.md D-050).

This checks that `expectations.json` is complete and internally well formed:
every fixture has exactly one entry and vice versa; every entry has every
required field; codes come from the registry's own vocabulary; each expected
decision agrees with the severities of its expected codes (D-048); every check
area has passing and failing fixtures; every code is exercised; corrections are
append-only and fully documented.

It does NOT judge whether any expected decision is statistically correct, and it
never runs, imports or reads the evidence checker. Correctness is established
only by comparing preregistered expectations with the checker's actual output
after Stage B (D-050).

Usage: .venv/bin/python fixtures/synthetic_wp2/validate_registry.py
"""
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "expectations.json"

PROJECT_CLAIM = ("The fixture expectations were preregistered before the evidence-check "
                 "implementation was run against them.")
DECISIONS = ("ANALYZE", "WARN", "REFUSE")
SEVERITIES = ("refuse", "warn", "note")
STAGES = tuple("S%d" % i for i in range(9))
TOP_KEYS = {"registry", "schema_version", "created", "synthetic_label", "project_claim",
            "preregistration_statement", "governing_decisions", "decision_rule",
            "matching_rule", "check_areas", "vocabulary", "vocabulary_amendments", "fixtures",
            "reference_datasets", "corrections"}
FIXTURE_KEYS = {"id", "expectation_version", "purpose", "check_areas", "claimed_template",
                "synthetic", "data_label", "files", "expected_decision", "expected_categories",
                "triggering_conditions", "rationale", "preregistered"}
REFERENCE_KEYS = {"id", "synthetic", "data_label", "declaration", "data",
                  "expected_structural_outcome", "diagnostics", "rationale"}
CORRECTION_KEYS = {"fixture_id", "new_version", "date", "previous", "observed", "corrected",
                   "reason", "judged_wrong", "decisions_entry"}
JUDGED_WRONG = ("expectation", "implementation", "fixture_construction",
                "specification_ambiguity", "specification_clarification")
# A corrected expectation is recorded only when the expectation itself, or the specification it
# was derived from, was changed; an implementation or fixture fix keeps the expectation (D-050).
CORRECTS_EXPECTATION = ("expectation", "specification_clarification")
AMENDMENT_KEYS = {"code", "severity", "stage", "definition", "date", "decisions_entry"}
ID_RE = re.compile(r"^[A-Z0-9]+-\d{2}$")


def decision_for(codes, vocabulary):
    """The decision implied by a code set under the D-048 rule."""
    sev = {vocabulary[c]["severity"] for c in codes}
    if "refuse" in sev:
        return "REFUSE"
    if "warn" in sev:
        return "WARN"
    return "ANALYZE"


def effective_expectations(registry):
    """{fixture id: (version, decision, categories)} after applying corrections in order.
    Version-1 values come from the fixture entry; a correction supersedes them only
    through an appended, documented record (D-050)."""
    out = {f["id"]: (1, f["expected_decision"], tuple(sorted(f["expected_categories"])))
           for f in registry["fixtures"]}
    for c in registry["corrections"]:
        if c.get("judged_wrong") in CORRECTS_EXPECTATION and c.get("corrected"):
            out[c["fixture_id"]] = (c["new_version"], c["corrected"]["decision"],
                                    tuple(sorted(c["corrected"]["categories"])))
    return out


def _outcome(problems, where, value, vocabulary):
    if not isinstance(value, dict) or set(value) != {"decision", "categories"}:
        problems.append("%s must be {decision, categories}" % where)
        return
    if value["decision"] not in DECISIONS:
        problems.append("%s.decision %r is not one of %s" % (where, value["decision"], DECISIONS))
    cats = value["categories"]
    if not isinstance(cats, list) or any(c not in vocabulary for c in cats):
        problems.append("%s.categories must be a list of vocabulary codes" % where)


def validate(registry, base=HERE):
    """Return a list of problems (empty when the registry is well formed)."""
    p = []
    if not isinstance(registry, dict):
        return ["registry is not a JSON object"]
    missing, extra = TOP_KEYS - set(registry), set(registry) - TOP_KEYS
    if missing or extra:
        p.append("top-level keys: missing %s, unexpected %s" % (sorted(missing), sorted(extra)))
        return p
    if registry["schema_version"] != 1:
        p.append("schema_version must be 1")
    if registry["project_claim"] != PROJECT_CLAIM:
        p.append("project_claim must be the D-042 wording exactly")
    statement = registry["preregistration_statement"]
    if not isinstance(statement, str) or "before" not in statement:
        p.append("preregistration_statement must state that expectations predate the checker")
    if "SYNTHETIC" not in registry["synthetic_label"]:
        p.append("synthetic_label must say SYNTHETIC")

    vocab = registry["vocabulary"]
    for code, v in vocab.items():
        if not re.match(r"^[a-z_]+$", code):
            p.append("vocabulary code %r is not snake_case" % code)
        if not isinstance(v, dict) or set(v) != {"severity", "stage", "definition"}:
            p.append("vocabulary[%s] must have severity, stage, definition" % code)
            continue
        if v["severity"] not in SEVERITIES:
            p.append("vocabulary[%s].severity %r invalid" % (code, v["severity"]))
        if v["stage"] not in STAGES:
            p.append("vocabulary[%s].stage %r invalid" % (code, v["stage"]))
        if not str(v["definition"]).strip():
            p.append("vocabulary[%s].definition empty" % code)
    if p:
        return p
    frozen_vocab = vocab
    vocab = dict(vocab)
    for i, a in enumerate(registry["vocabulary_amendments"]):
        where = "vocabulary_amendments[%d]" % i
        if not isinstance(a, dict) or set(a) != AMENDMENT_KEYS:
            p.append("%s: fields must be exactly %s" % (where, sorted(AMENDMENT_KEYS)))
            continue
        if a["code"] in vocab:
            p.append("%s: code %r already exists; frozen codes are never redefined"
                     % (where, a["code"]))
        if a["severity"] not in SEVERITIES or a["stage"] not in STAGES:
            p.append("%s: invalid severity or stage" % where)
        if not re.match(r"^D-\d{3}$", str(a["decisions_entry"])):
            p.append("%s: decisions_entry must name the DECISIONS.md entry" % where)
        vocab[a["code"]] = {"severity": a["severity"], "stage": a["stage"],
                            "definition": a["definition"]}
    areas = registry["check_areas"]

    seen = set()
    for i, f in enumerate(registry["fixtures"]):
        where = "fixtures[%d]" % i
        if not isinstance(f, dict) or set(f) != FIXTURE_KEYS:
            got = set(f) if isinstance(f, dict) else set()
            p.append("%s: fields missing %s, unexpected %s"
                     % (where, sorted(FIXTURE_KEYS - got), sorted(got - FIXTURE_KEYS)))
            continue
        fid = f["id"]
        where = "fixture %s" % fid
        if not isinstance(fid, str) or not ID_RE.match(fid):
            p.append("%s: id must look like ABC-01" % where)
        if fid in seen:
            p.append("%s: duplicate id" % where)
        seen.add(fid)
        if f["expectation_version"] != 1:
            p.append("%s: expectation_version of a fixture entry is always 1; later versions "
                     "are appended under corrections" % where)
        for key in ("purpose", "rationale", "data_label"):
            if not isinstance(f[key], str) or not f[key].strip():
                p.append("%s: %s must be non-empty text" % (where, key))
        if f["synthetic"] is not True or "SYNTHETIC" not in str(f["data_label"]):
            p.append("%s: must be labeled synthetic" % where)
        if f["preregistered"] != statement:
            p.append("%s: preregistered must be the registry's preregistration statement"
                     % where)
        if not (isinstance(f["check_areas"], list) and f["check_areas"]
                and all(a in areas for a in f["check_areas"])):
            p.append("%s: check_areas must be a non-empty list of declared areas" % where)
        conds = f["triggering_conditions"]
        if not (isinstance(conds, list) and conds and all(isinstance(c, str) and c.strip()
                                                          for c in conds)):
            p.append("%s: triggering_conditions must be a non-empty list of text" % where)
        if f["expected_decision"] not in DECISIONS:
            p.append("%s: expected_decision %r invalid" % (where, f["expected_decision"]))
        cats = f["expected_categories"]
        if not isinstance(cats, list) or len(set(cats)) != len(cats):
            p.append("%s: expected_categories must be a list without repeats" % where)
            continue
        unknown = [c for c in cats if c not in frozen_vocab]
        if unknown:
            p.append("%s: codes not in the vocabulary: %s" % (where, unknown))
            continue
        if f["expected_decision"] in DECISIONS and decision_for(cats, vocab) != f["expected_decision"]:
            p.append("%s: expected_decision %s disagrees with the severities of %s (implies %s)"
                     % (where, f["expected_decision"], cats, decision_for(cats, vocab)))

        files = f["files"]
        if not isinstance(files, dict) or set(files) != {"declaration", "data"}:
            p.append("%s: files must name declaration and data" % where)
            continue
        for kind, rel in files.items():
            if not (isinstance(rel, str) and rel.startswith(fid + "/") and "synthetic" in rel):
                p.append("%s: %s path must be <id>/...synthetic..." % (where, kind))
            elif not (base / rel).is_file():
                p.append("%s: %s file %s does not exist" % (where, kind, rel))
        decl_path = base / str(files.get("declaration"))
        if decl_path.is_file():
            text = decl_path.read_text(encoding="utf-8")
            if not text.startswith("# SYNTHETIC"):
                p.append("%s: declaration file does not start with the SYNTHETIC label" % where)
            try:
                d = yaml.safe_load(text)
            except yaml.YAMLError:
                d = None
            if not isinstance(d, dict):
                p.append("%s: declaration file is not a YAML mapping" % where)
            else:
                if d.get("claimed_template") != f["claimed_template"]:
                    p.append("%s: claimed_template %r differs from the declaration file's %r"
                             % (where, f["claimed_template"], d.get("claimed_template")))
                if "SYNTHETIC FIXTURE %s" % fid not in str(d.get("description", "")):
                    p.append("%s: declaration description lacks 'SYNTHETIC FIXTURE %s'"
                             % (where, fid))

    dirs = {q.name for q in base.iterdir() if q.is_dir() and ID_RE.match(q.name)}
    for name in sorted(dirs - seen):
        p.append("fixture directory %s has no registry entry" % name)
    for name in sorted(seen - dirs):
        p.append("registry entry %s has no fixture directory" % name)

    fixtures = [f for f in registry["fixtures"] if isinstance(f, dict) and set(f) == FIXTURE_KEYS]
    for area in areas:
        tagged = [f for f in fixtures if area in f["check_areas"]]
        if not any(f["expected_decision"] == "ANALYZE" for f in tagged):
            p.append("check area %r has no passing (ANALYZE) fixture" % area)
        if not any(f["expected_decision"] != "ANALYZE" for f in tagged):
            p.append("check area %r has no failing (WARN or REFUSE) fixture" % area)
    used = {c for f in fixtures for c in f["expected_categories"]}
    used |= {c for x in registry["corrections"] if isinstance(x, dict)
             and x.get("judged_wrong") in CORRECTS_EXPECTATION and isinstance(x.get("corrected"), dict)
             for c in x["corrected"].get("categories", [])}
    for code in sorted(set(vocab) - used):
        p.append("vocabulary code %r is exercised by no fixture" % code)

    for i, r in enumerate(registry["reference_datasets"]):
        where = "reference_datasets[%d]" % i
        if not isinstance(r, dict) or set(r) != REFERENCE_KEYS:
            p.append("%s: wrong fields" % where)
            continue
        if r["synthetic"] is not False:
            p.append("%s: published reference data are not synthetic" % where)
        if r["expected_structural_outcome"] != "no refusal-severity finding":
            p.append("%s: only the structural outcome is preregistered" % where)

    versions = {}
    for i, c in enumerate(registry["corrections"]):
        where = "corrections[%d]" % i
        if not isinstance(c, dict) or set(c) != CORRECTION_KEYS:
            p.append("%s: fields must be exactly %s" % (where, sorted(CORRECTION_KEYS)))
            continue
        if c["fixture_id"] not in seen:
            p.append("%s: unknown fixture %r" % (where, c["fixture_id"]))
            continue
        want = versions.get(c["fixture_id"], 1) + 1
        if c["new_version"] != want:
            p.append("%s: new_version must be %d (corrections are sequential)" % (where, want))
        versions[c["fixture_id"]] = c["new_version"]
        if c["judged_wrong"] not in JUDGED_WRONG:
            p.append("%s: judged_wrong must be one of %s" % (where, JUDGED_WRONG))
        if not re.match(r"^D-\d{3}$", str(c["decisions_entry"])):
            p.append("%s: decisions_entry must name the DECISIONS.md entry (D-NNN)" % where)
        if not str(c["reason"]).strip():
            p.append("%s: reason must be given" % where)
        _outcome(p, where + ".previous", c["previous"], vocab)
        _outcome(p, where + ".observed", c["observed"], vocab)
        if c["judged_wrong"] in CORRECTS_EXPECTATION:
            _outcome(p, where + ".corrected", c["corrected"], vocab)
            if isinstance(c["corrected"], dict) and \
                    isinstance(c["corrected"].get("categories"), list) and \
                    all(x in vocab for x in c["corrected"]["categories"]) and \
                    decision_for(c["corrected"]["categories"], vocab) != c["corrected"]["decision"]:
                p.append("%s.corrected: decision disagrees with code severities" % where)
        elif c["corrected"] is not None:
            p.append("%s: corrected must be null unless the expectation or its specification "
                     "changed" % where)
    return p


def main():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    problems = validate(registry)
    if problems:
        print("\n".join(problems))
        return 1
    n = len(registry["fixtures"])
    counts = {d: sum(f["expected_decision"] == d for f in registry["fixtures"]) for d in DECISIONS}
    print("registry well formed: %d fixtures (version-1: %s), %d frozen codes + %d amended, "
          "%d corrections; statistical correctness is not judged here"
          % (n, ", ".join("%d %s" % (counts[d], d) for d in DECISIONS),
             len(registry["vocabulary"]), len(registry["vocabulary_amendments"]),
             len(registry["corrections"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
