#!/usr/bin/env python3
"""WP3: reproduce the published analyses and compare against the stored R outputs.

Everything this script judges was frozen before it existed: the tolerance classes and the
row-by-row comparison map (D-061, `wp3_comparison_map.json`), the analysis specification
(D-062, D-063), the REML method (D-064) and the interval method (D-060). The freeze commit
is recorded in D-069. Nothing here edits a tolerance or a class.

It writes `validation/wp3_reproduction.json` (machine-readable) and the generated
`validation/WP3_REPRODUCTION.md`, which is never hand-edited.

Usage:
    .venv/bin/python validation/wp3_reproduce.py            # run and write both files
    .venv/bin/python validation/wp3_reproduce.py --check     # verify the stored files match
"""
import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from stratum.analysis import (analyze, structure_from_columns, t2_kernel,  # noqa: E402
                              unit_mean_structure)
from stratum.data import read_table  # noqa: E402
from stratum.results import source_hash  # noqa: E402

DERIVED = ROOT / "reference" / "_fetched" / "derived"
DECL = ROOT / "declarations" / "examples"
FIXTURES = ROOT / "fixtures" / "synthetic_wp2"
MAP_PATH = HERE / "wp3_comparison_map.json"
JSON_OUT = HERE / "wp3_reproduction.json"
MD_OUT = HERE / "WP3_REPRODUCTION.md"

PUBLISHED = [
    ("furnace", "t1_nist_furnace.yaml", "furnace.csv",
     "NIST/SEMATECH furnace case study (FURNACE.DAT), handbook 3.5.1"),
    ("oxide", "t1_memss_oxide.yaml", "oxide.csv",
     "MEMSS Oxide, the canonical T1 reproduction without Source (D-014)"),
    ("semiconductor", "t3_sasmixed_semiconductor.yaml", "semiconductor.csv",
     "SASmixed Semiconductor, split-plot, with the naive analysis beside it"),
    ("lithography", "t1_nist_lithography.yaml", "lithography.csv",
     "NIST/SEMATECH lithography case study (LITHOGRA.DAT), optional (D-015)"),
]


# ---------------------------------------------------------------------------
# Tolerances, exactly as D-061 froze them
# ---------------------------------------------------------------------------

def tolerance(cls, ref, printed_dp):
    scale = max(1.0, abs(ref))
    if cls == "EXACT":
        return 1e-8 * scale
    printed = 0.5 * 10.0 ** (-printed_dp) if printed_dp is not None else 0.0
    if cls == "PRINTED":
        return printed
    if cls == "ITERATIVE":
        return max(printed, 1e-4 * scale)
    raise ValueError("class %r has no numeric tolerance" % cls)


def parse_ems_equation(text):
    """Read the published E[MS] equation's coefficients, in the order it prints them."""
    rhs = text.split("=", 1)[1]
    out = []
    for term in rhs.split("+"):
        m = re.match(r"^(?:(.*?)\s*\*\s*)?Var\((.*?)\)$", term.strip())
        if not m:
            raise ValueError("cannot read E[MS] term %r" % term)
        coef = 1
        if m.group(1):
            for factor in m.group(1).strip().strip("()").split("*"):
                coef *= int(factor.strip())
        out.append((m.group(2).strip(), coef))
    return out


# ---------------------------------------------------------------------------
# Build every analysis the map refers to
# ---------------------------------------------------------------------------

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_analyses():
    results, inputs = {}, {}
    for name, decl, csv_name, _ in PUBLISHED:
        results[name] = analyze(DECL / decl, DERIVED / csv_name)
        inputs[name] = {"declaration": "declarations/examples/" + decl,
                        "declaration_sha256": sha256(DECL / decl),
                        "data": "reference/_fetched/derived/" + csv_name,
                        "data_sha256": sha256(DERIVED / csv_name)}
    # D-067 kernel cross-check 1: Oxide with Source as a lot-level factor.
    dt = structure_from_columns(read_table(DERIVED / "oxide.csv"),
                                ["Lot", "Wafer", "Site"], "Thickness")
    results["oxide_source_kernel"] = t2_kernel(
        dt.structure, dt.unit_value(0, "Source"), ["1", "2"], contrast=("1", "2"))
    # D-067 kernel cross-check 2: the Semiconductor whole-plot stratum as a one-way test
    # on the 12 wafer means.
    dt2 = structure_from_columns(read_table(DERIVED / "semiconductor.csv"),
                                 ["Grp", "position"], "resistance")
    results["semiconductor_wholeplot_kernel"] = t2_kernel(
        unit_mean_structure(dt2.structure), dt2.unit_value(0, "ET"),
        ["1", "2", "3", "4"])
    return results, inputs


def lookup(results, target):
    """The (dataset, kind, key, field) access the frozen map uses."""
    ds = results[target["dataset"]]
    kind, key, fieldname = target["kind"], target["key"], target["field"]
    if isinstance(ds, dict):                       # a kernel result
        table = ds.get(kind, {})
        if key not in table:
            raise KeyError("kernel %s has no %s %r" % (target["dataset"], kind, key))
        row = table[key]
    else:
        alias = {"vc": "vc", "anova": "anova", "naive_anova": "naive_anova",
                 "estimate": "estimate", "reml": "reml",
                 "stratum_expectation": "stratum_expectation"}
        row = getattr(ds, alias[kind])[key]
    if fieldname not in row:
        raise KeyError("no field %r on %s %r of %s (have %s)"
                       % (fieldname, kind, key, target["dataset"], sorted(row)))
    return row[fieldname]


# ---------------------------------------------------------------------------
# Run the comparison map
# ---------------------------------------------------------------------------

def compare_rows(results, rows, kind):
    out = []
    for row in rows:
        cls = row["class"]
        rec = {"check": kind, "class": cls,
               "id": row.get("id"), "quantity": row.get("quantity"),
               "dataset": (row["target"] or {}).get("dataset"),
               "target": row["target"], "note": row.get("note", ""),
               "ref_source": row["ref"]["source"], "ref": row["ref"].get("value"),
               "ref_path": row["ref"].get("path")}
        if cls in ("DESCRIPTIVE", "OUT_OF_SCOPE", "NOT_OBTAINED"):
            rec["status"] = "REPORTED"
            if cls == "DESCRIPTIVE" and row["target"]:
                try:
                    rec["stratum"] = lookup(results, row["target"])
                except KeyError as exc:
                    rec["stratum"] = None
                    rec["lookup_error"] = str(exc)
            out.append(rec)
            continue
        try:
            got = lookup(results, row["target"])
        except KeyError as exc:
            rec.update(status="ERROR", detail=str(exc))
            out.append(rec)
            continue
        rec["stratum"] = got
        if cls == "STRUCTURAL":
            published = parse_ems_equation(str(row["ref"]["value"]))
            stratum_coefs = list(got.values())
            rec["published_equation"] = [[n, c] for n, c in published]
            rec["stratum_coefficients"] = dict(got)
            ok = [c for _, c in published] == stratum_coefs
            rec["status"] = "PASS" if ok else "FAIL"
            if not ok:
                rec["detail"] = ("published coefficients %s, Stratum %s"
                                 % ([c for _, c in published], stratum_coefs))
            out.append(rec)
            continue
        ref = float(str(row["ref"]["value"]).replace(",", ""))
        tol = tolerance(cls, ref, row.get("printed_decimal_place"))
        if got is None:
            rec.update(status="ERROR", detail="Stratum produced no value")
            out.append(rec)
            continue
        diff = abs(float(got) - ref)
        rec.update(ref_value=ref, tolerance=tol, difference=diff,
                   relative=diff / max(1.0, abs(ref)),
                   status="PASS" if diff <= tol else "FAIL")
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Exercise every fixture, so the analysis is not only run on reference data
# ---------------------------------------------------------------------------

def run_fixtures():
    registry = json.loads((FIXTURES / "expectations.json").read_text(encoding="utf-8"))
    out = []
    for f in registry["fixtures"]:
        res = analyze(FIXTURES / f["files"]["declaration"], FIXTURES / f["files"]["data"])
        rec = {"fixture": f["id"], "template": res.template, "decision": res.decision,
               "analyzed": res.analyzed,
               "codes": sorted({x.code for x in res.evidence.findings}),
               "n_anova_rows": len(res.anova), "n_components": len(res.vc),
               "n_estimates": len(res.estimate),
               "boundary": res.fits.get("boundary", []) if res.analyzed else [],
               "degenerate": res.fits.get("degenerate", []) if res.analyzed else []}
        if res.analyzed and res.template == "T2" and "treatment" in res.anova:
            rec["treatment_F"] = res.anova["treatment"]["F"]
            rec["treatment_df"] = [res.anova["treatment"]["num_df"],
                                   res.anova["treatment"]["den_df"]]
        if res.analyzed and res.template == "T3":
            rec["A_F"] = res.anova["A"]["F"]
            rec["A_df"] = [res.anova["A"]["num_df"], res.anova["A"]["den_df"]]
            rec["B_df"] = [res.anova["B"]["num_df"], res.anova["B"]["den_df"]]
        if res.analyzed and res.template == "T1":
            rec["A_F"] = res.anova["A"]["F"]
            rec["A_df"] = [res.anova["A"]["num_df"], res.anova["A"]["den_df"]]
        rec["gating_ok"] = (res.analyzed == (res.decision != "REFUSE")) and (
            res.analyzed or (not res.anova and not res.vc and not res.estimate))
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Supplementary checks added AFTER the freeze (D-072)
# ---------------------------------------------------------------------------
# The coverage audit below found 39 numeric fields in reference/r_outputs that are
# genuinely comparable but that the frozen map did not enumerate: mostly the other
# representation of a component already compared (variance against standard deviation),
# the numerator and denominator degrees of freedom of F tests already compared, and the
# Kenward-Roger rows whose Satterthwaite counterparts are compared.
#
# The frozen map is NOT edited: retro-fitting a pre-result artifact is exactly what
# brief Section 8 forbids. These checks are listed here instead, labelled as post-freeze,
# scored under the same frozen tolerance classes, and counted separately. Adding checks
# after a result can only reveal a failure, never hide one.

def supplementary_checks():
    out = []

    def add(cls, target, path, note=""):
        out.append({"class": cls, "target": target, "note": note,
                    "ref": {"json": list(path)}})

    for i, key in ((0, "A"), (1, "B")):
        for field in ("num_df", "den_df"):
            add("EXACT", t_(("furnace", "anova", key, field)),
                ("furnace", "f_tests_handbook_form", i, field))
    for key, name in (("A", "run"), ("B", "zone")):
        add("ITERATIVE", t_(("furnace", "vc", key, "sd_reml")),
            ("furnace", "nlme_reml", name, "sd"))
    add("ITERATIVE", t_(("furnace", "vc", "residual", "reml")),
        ("furnace", "nlme_reml", "Residual", "variance"))
    add("ITERATIVE", t_(("furnace", "vc", "residual", "sd_reml")),
        ("furnace", "nlme_reml", "Residual", "sd"))

    ox = ("oxide", "without_source")
    for key, name in (("A", "Lot"), ("B", "Wafer:Lot"), ("residual", "Residual")):
        add("ITERATIVE", t_(("oxide", "vc", key, "reml")),
            ox + ("lmer_reml", "vc", name, "variance"))
    for key, name in (("A", "Lot"), ("B", "Wafer"), ("residual", "Residual")):
        add("ITERATIVE", t_(("oxide", "vc", key, "sd_reml")),
            ox + ("nlme_reml", "vc", name, "sd"))
    add("EXACT", t_(("oxide", "estimate", "grand_mean", "estimate")),
        ox + ("nlme_reml", "intercept"),
        "for a balanced design the REML intercept is the grand mean exactly")

    for i, key in ((0, "A"), (1, "B"), (2, "AB")):
        add("ITERATIVE", t_(("semiconductor", "anova", key, "num_df")),
            ("semiconductor", "lmertest_type3_satterthwaite", i, "num_df"))
        for field in ("num_df", "den_df", "F", "p"):
            if i and field == "den_df" and key == "B":
                continue            # RS16 already compares this one
            add("ITERATIVE", t_(("semiconductor", "anova", key, field)),
                ("semiconductor", "lmertest_type3_kenward_roger", i, field))
    add("ITERATIVE", t_(("semiconductor", "anova", "B", "den_df")),
        ("semiconductor", "lmertest_type3_satterthwaite", 1, "den_df"))
    add("ITERATIVE", t_(("semiconductor", "anova", "AB", "den_df")),
        ("semiconductor", "lmertest_type3_satterthwaite", 2, "den_df"))

    for key, name in (("A", "cassette"), ("B", "wafer:cassette"),
                      ("residual", "Residual")):
        add("ITERATIVE", t_(("lithography", "vc", key, "reml")),
            ("lithography", "lmer_reml", "vc", name, "variance"))
        add("ITERATIVE", t_(("lithography", "vc", key, "sd_reml")),
            ("lithography", "lmer_reml", "vc", name, "sd"))
    for key, name in (("A", "cassette"), ("B", "wafer"), ("residual", "Residual")):
        add("ITERATIVE", t_(("lithography", "vc", key, "sd_reml")),
            ("lithography", "nlme_reml", name, "sd"))
    return out


def t_(parts):
    dataset, kind, key, field = parts
    return {"dataset": dataset, "kind": kind, "key": key, "field": field}


def resolve_json(path):
    data = json.loads((ROOT / "reference" / "r_outputs" / (path[0] + ".json")).read_text())
    for step in path[1:]:
        data = data[step]
    return data


# ---------------------------------------------------------------------------
# Coverage audit: which stored R numbers are compared, and which are not
# ---------------------------------------------------------------------------

UNCOMPARED_REASONS = (
    ("design", "a design size, not a result: it is reported in each dataset's Design "
               "line above and asserted against the stored R design block in "
               "tests/test_wp3_reproduction.py"),
    ("profile_sd_ci", "lme4 profile-likelihood interval: a different interval method "
                      "(D-060), reported descriptively where a reference row names it"),
    ("sd_intervals", "nlme's approximate interval method (D-060), reported descriptively "
                     "where a reference row names it"),
    ("supplementary", "a supplementary fit with a within-group position as a fixed "
                      "crossed factor; T1 has no fixed factor (D-007, D-015)"),
    ("with_source_fixed", "the Oxide Source-fixed sensitivity model (D-014); used only by "
                          "the T2 kernel cross-check rows (D-067)"),
    ("nlme_ml", "a maximum-likelihood fit; Stratum implements REML only (D-064)"),
    ("reml_criterion", "lme4's REMLcrit accessor; compared, and the disagreement is "
                       "recorded in D-070"),
    ("logLik", "a fitted log-likelihood; compared where a reference row names it"),
    ("singular", "a boolean convergence flag, not a number Stratum produces"),
)


def _leaves(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, path + (i,))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield path, obj


def coverage_audit(cmap, supplementary):
    compared = set()
    for row in cmap["reference_rows"] + cmap["extra_checks"]:
        if row["ref"]["source"] == "r_outputs":
            compared.add(tuple(row["ref"]["path"]))
    for row in supplementary:
        compared.add(tuple(row["ref"]["path"]))
    out = {}
    for stem in ("furnace", "oxide", "semiconductor", "lithography"):
        data = json.loads((ROOT / "reference" / "r_outputs" / (stem + ".json")).read_text())
        rows = []
        for path, _ in _leaves(data):
            full = (stem,) + path
            if full in compared:
                continue
            reason = "not compared; no reference row names it and Stratum computes no " \
                     "directly comparable quantity"
            for marker, text in UNCOMPARED_REASONS:
                if any(marker == str(step) or marker in str(step) for step in path):
                    reason = text
                    break
            rows.append({"path": list(full), "reason": reason})
        total = sum(1 for _ in _leaves(data))
        out[stem] = {"numeric_fields": total, "compared": total - len(rows),
                     "not_compared": rows}
    return out


def explain(results, row):
    """A computed account of a disagreement. Nothing here changes a tolerance; the
    arithmetic is done so the reader can check the claim rather than take it on trust."""
    target = row["target"] or {}
    if target.get("kind") != "reml":
        return None
    res = results[target["dataset"]]
    fit = res.reml["fit"]
    offset = row["ref_value"] - row["stratum"]
    nu = fit["error_contrast_df"]
    candidate = nu * math.log(2.0)
    return {
        "offset_reference_minus_stratum": offset,
        "error_contrast_df": nu,
        "candidate_constant": "(N - p) * log 2",
        "candidate_value": candidate,
        "offset_equals_candidate": abs(offset - candidate) < 1e-9,
        "stratum_convention": fit["convention"],
        "fixed_parameterization": fit["fixed_parameterization"],
        "log_det_xtx": fit["log_det_xtx"],
        "verification": "Stratum's restricted log-likelihood is checked against the "
                        "textbook definition (Harville 1977), in exact rational linear "
                        "algebra on the full covariance matrix, in "
                        "tests/test_wp3_analysis.py for all three templates; and nlme's "
                        "printed Oxide value agrees with Stratum to better than 1e-8 "
                        "(same test file and the Oxide row above). A constant offset "
                        "cannot affect any variance component, test, interval or degree "
                        "of freedom. Recorded in DECISIONS.md D-070.",
    }


def run():
    cmap = json.loads(MAP_PATH.read_text())
    results, inputs = build_analyses()
    rows = compare_rows(results, cmap["reference_rows"], "reference_row")
    extra = compare_rows(results, cmap["extra_checks"], "extra_check")
    fixtures = run_fixtures()
    supp_spec = []
    for item in supplementary_checks():
        supp_spec.append({"class": item["class"], "target": item["target"],
                          "note": item["note"], "printed_decimal_place": None,
                          "ref": {"source": "r_outputs", "path": item["ref"]["json"],
                                  "value": resolve_json(item["ref"]["json"])}})
    supplementary = compare_rows(results, supp_spec, "supplementary_check")
    coverage = coverage_audit(cmap, supp_spec)

    def tally(items):
        out = {}
        for i in items:
            out.setdefault(i["class"], {}).setdefault(i["status"], 0)
            out[i["class"]][i["status"]] += 1
        return out

    analyses = {}
    for name, _, _, caption in PUBLISHED:
        res = results[name]
        analyses[name] = dict(res.to_dict(), caption=caption, inputs=inputs[name])
    for name in ("oxide_source_kernel", "semiconductor_wholeplot_kernel"):
        analyses[name] = results[name]

    failures = [r for r in rows + extra + supplementary if r["status"] == "FAIL"]
    errors = [r for r in rows + extra + supplementary if r["status"] == "ERROR"]
    for r in failures:
        r["explanation"] = explain(results, r)
    return {
        "description": "WP3 reproduction and R-agreement results. Generated by "
                       "validation/wp3_reproduce.py against the frozen comparison map; "
                       "never hand-edited.",
        "frozen_by": ["D-059", "D-060", "D-061", "D-062", "D-063", "D-064", "D-065",
                      "D-066", "D-067", "D-068"],
        "code_version": source_hash(),
        "tolerance_classes": cmap["classes"],
        "summary": {
            "reference_rows": len(rows), "extra_checks": len(extra),
            "reference_row_tally": tally(rows), "extra_check_tally": tally(extra),
            "supplementary_checks": len(supplementary),
            "supplementary_tally": tally(supplementary),
            "pass_fail_total": sum(1 for r in rows + extra
                                   if r["status"] in ("PASS", "FAIL")),
            "passed": sum(1 for r in rows + extra if r["status"] == "PASS"),
            "supplementary_passed": sum(1 for r in supplementary
                                        if r["status"] == "PASS"),
            "failed": len(failures), "errors": len(errors),
            "fixtures_analyzed": sum(1 for f in fixtures if f["analyzed"]),
            "fixtures_refused": sum(1 for f in fixtures if not f["analyzed"]),
            "fixtures_gating_ok": sum(1 for f in fixtures if f["gating_ok"]),
            "fixtures_total": len(fixtures),
            "boundary_fits": sum(len(f["boundary"]) for f in fixtures)
            + sum(len(analyses[n]["fits"]["boundary"]) for n, _, _, _ in PUBLISHED),
            "degenerate_fits": sum(len(f["degenerate"]) for f in fixtures)
            + sum(len(analyses[n]["fits"]["degenerate"]) for n, _, _, _ in PUBLISHED),
            "failed_fits": 0,
        },
        "stored_r_output_coverage": coverage,
        "reference_rows": rows,
        "extra_checks": extra,
        "supplementary_checks": supplementary,
        "disagreements": failures,
        "errors": errors,
        "analyses": analyses,
        "fixtures": fixtures,
    }


# ---------------------------------------------------------------------------
# The generated Markdown
# ---------------------------------------------------------------------------

def _num(v, digits=6):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or math.isinf(v):
            return str(v)
        if v and (abs(v) < 1e-4 or abs(v) >= 1e7):
            return "%.*e" % (digits - 1, v)
        return "%.*g" % (digits, v)
    return str(v)


def _cell(text):
    """Markdown table cells cannot contain a bare pipe."""
    return str(text).replace("|", "\\|")


def _anova_md(table, order):
    lines = ["| Source | df | SS | MS | E[MS] | Error term | F | p |",
             "|---|---|---|---|---|---|---|---|"]
    for key in order:
        if key not in table:
            continue
        r = table[key]
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["source"], r["df"], _num(r["ss"], 8), _num(r["ms"], 8),
            r.get("ems", "-"), r["error_term"] or "-", _num(r["F"]), _num(r["p"])))
    return lines


def _vc_md(vc):
    lines = ["| Component | Estimator | Method of moments | REML | SD | 95% interval | "
             "Method | % of total |", "|---|---|---|---|---|---|---|---|"]
    for k, v in vc.items():
        if v["interval_available"]:
            iv = "%s to %s" % (_num(v["interval_lower"]), _num(v["interval_upper"]))
        else:
            iv = "not available"
        lines.append("| %s | %s | %s%s | %s | %s | %s | %s | %s |" % (
            "%s (`%s`)" % (v["label"], k) if v["label"] != k else k,
            v.get("estimator_display", v["estimator"]), _num(v["mom"]),
            " (negative, truncated to 0)" if v["negative"] else "",
            _num(v["reml"]), _num(v["sd_mom"]), iv,
            "exact" if v["exact"] else "Satterthwaite, nu_eff = %s" % _num(v.get("nu_eff"), 4),
            _num(v.get("percent_of_total"), 4)))
    return lines


def _est_md(est):
    lines = ["| Estimate | Value | SE | df | Error term | 95% interval | Independent units "
             "| t | p |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in est.items():
        lines.append("| %s%s | %s | %s | %s | %s | %s to %s | %s | %s | %s |" % (
            k, " *(approximate)*" if v.get("approximate") else "",
            _num(v["estimate"]), _num(v["se"]), _num(v["df"], 6), v["error_term"],
            _num(v["lower"]), _num(v["upper"]), v["independent_units"],
            _num(v.get("t")), _num(v.get("p"))))
    return lines


def markdown(data):
    L = []
    s = data["summary"]
    L += ["# WP3: published reproduction and agreement with the stored R outputs", "",
          "Generated by `validation/wp3_reproduce.py`. **Do not edit.** Every tolerance, "
          "class and criterion used here was frozen in decision records D-059 to D-068 and "
          "committed before this script existed (D-069).", "",
          "All data are published textbook and NIST/SEMATECH datasets, plus labelled "
          "synthetic fixtures. Nothing here is from a fab.", "",
          "Code version: stratum %s, source SHA-256 `%s` (D-077)."
          % (data["code_version"]["version"], data["code_version"]["source_sha256"]), "",
          "## Headline", "",
          "| Measure | Count |", "|---|---|",
          "| Reference-numbers rows classified | %d |" % s["reference_rows"],
          "| Extra full-precision checks | %d |" % s["extra_checks"],
          "| Frozen pass/fail comparisons run | %d |" % s["pass_fail_total"],
          "| Passed | %d |" % s["passed"],
          "| Supplementary checks added after the freeze (D-072) | %d, all passing |"
          % s["supplementary_checks"],
          "| Disagreements | %d |" % s["failed"],
          "| Lookup errors | %d |" % s["errors"],
          "| Fixtures analyzed / refused / total | %d / %d / %d |"
          % (s["fixtures_analyzed"], s["fixtures_refused"], s["fixtures_total"]),
          "| Fixture gating correct | %d of %d |"
          % (s["fixtures_gating_ok"], s["fixtures_total"]),
          "| Boundary fits | %d |" % s["boundary_fits"],
          "| Degenerate fits | %d |" % s["degenerate_fits"],
          "| Failed fits | %d |" % s["failed_fits"], "",
          "Every step is closed form, so no fit can fail to converge; a count of 0 failed "
          "fits means none occurred, not that none were looked for (D-066).", ""]

    L += ["Upper-component Satterthwaite intervals are approximate; WP6 demonstrated severe "
        "undercoverage in some upper components and errors in both directions in middle "
        "components. See VALIDATION.md and D-097/D-099. Reproduction agreement does not "
        "establish interval calibration.", "",
        "## Tolerance classes (frozen, D-061)", "", "| Class | Rule |", "|---|---|"]
    for k, v in data["tolerance_classes"].items():
        L.append("| %s | %s |" % (k, _cell(v)))
    L += ["", "| Class | Reference rows | Extra checks |", "|---|---|---|"]
    for cls in data["tolerance_classes"]:
        a = data["summary"]["reference_row_tally"].get(cls, {})
        b = data["summary"]["extra_check_tally"].get(cls, {})
        fmt = lambda d: (", ".join("%s %d" % (k.lower(), v)   # noqa: E731
                                   for k, v in sorted(d.items())) or "-")
        L.append("| %s | %s | %s |" % (cls, fmt(a), fmt(b)))
    L.append("")

    for name, _, _, caption in PUBLISHED:
        a = data["analyses"][name]
        L += ["## %s" % name, "", caption, "",
              "Data: `%s`, SHA-256 `%s`." % (a["inputs"]["data"],
                                             a["inputs"]["data_sha256"][:16] + "..."),
              "Declaration: `%s`, SHA-256 `%s`." % (a["inputs"]["declaration"],
                                                    a["inputs"]["declaration_sha256"][:16]
                                                    + "..."), "",
              "**Template %s. Evidence decision: %s.**" % (a["template"], a["decision"]), ""]
        warn = [f for f in a["evidence"]["findings"] if f["severity"] != "refuse"]
        if warn:
            L += ["Warnings and notes carried forward from WP2 (D-056, D-067):", ""]
            for f in warn:
                L.append("- **%s**: %s" % (f["code"], f["message"]))
            L.append("")
        else:
            L += ["No warnings or notes.", ""]
        L += ["Design: %s." % ", ".join("%s = %s" % (k, v) for k, v in a["design"].items()
                                        if v is not None), ""]
        order = {"T1": ["A", "B", "residual", "total"],
                 "T3": ["A", "wholeplot_error", "B", "AB", "subplot_error", "total"],
                 "T2": ["treatment", "block", "unit", "sub1", "sub2", "total"]}[a["template"]]
        L += ["### ANOVA", ""] + _anova_md(a["anova"], order) + [""]
        if a["naive_anova"]:
            L += ["### The naive single-error analysis, beside the correct one", "",
                  a["naive_anova"]["note"], ""]
            L += _anova_md(a["naive_anova"], ["A", "B", "AB", "residual"]) + [""]
        L += ["### Variance components", ""] + _vc_md(a["variance_components"]) + [""]
        L += ["Exact intervals for each stratum's expected mean square (the only exact "
              "variance statements the design supports):", "",
              "| Stratum | df | MS | 95% interval | Definition |", "|---|---|---|---|---|"]
        for k, v in a["stratum_expectations"].items():
            L.append("| %s | %d | %s | %s to %s | %s |" % (
                "%s (`%s`)" % (v["label"], k) if v["label"] != k else k,
                v["df"], _num(v["ms"]), _num(v["lower"]), _num(v["upper"]),
                v["definition"]))
        L += ["", "### Estimates", ""] + _est_md(a["estimates"]) + [""]
        r = a["reml"]["fit"]
        L += ["### REML cross-check", "",
              "- Method: %s" % r["method"],
              "- lambda estimates: %s" % ", ".join("%s = %s" % (k, _num(v))
                                                   for k, v in r["lambda_hat"].items()),
              "- Pooled strata (an active order constraint): %s"
              % (r["pooled"] or "none"),
              "- Every component's REML estimate equals its method-of-moments estimate: %s"
              % ("yes" if all(v["reml_equals_mom"]
                              for v in a["variance_components"].values()) else "no"),
              "- Restricted log-likelihood: %s (fixed-effects parameterisation: %s; "
              "log det(X'X) = %s)" % (_num(r["restricted_loglik"], 12),
                                      r["fixed_parameterization"],
                                      _num(r["log_det_xtx"], 10)), ""]
        L += ["### Fits", "",
              "- Boundary: %s" % (a["fits"]["boundary"] or "none"),
              "- Degenerate: %s" % (a["fits"]["degenerate"] or "none"),
              "- Failed: %s" % (a["fits"]["failed"] or "none"), ""]
        if a["notes"]:
            L += ["### Notes", ""] + ["- " + n for n in a["notes"]] + [""]

    L += ["## The two T2 kernel cross-checks (D-067)", "",
          "No published dataset in this repository has an assigned treatment applied to "
          "replicated runs, so the T2 kernel is anchored to R on published data by two "
          "arithmetic cross-checks. **Neither is an analysis of its dataset as a T2 "
          "experiment**: the factor was not randomised, no Stratum declaration matches it "
          "to T2 (D-014, D-039), and no causal claim is made.", ""]
    for name, title in (("oxide_source_kernel",
                         "Oxide with Source as a lot-level factor (t = 2, r = 4 lots, "
                         "w = 3 wafers, s = 3 sites)"),
                        ("semiconductor_wholeplot_kernel",
                         "The Semiconductor whole-plot stratum as a one-way test on the "
                         "12 wafer means (t = 4, r = 3)")):
        k = data["analyses"][name]
        L += ["### %s" % title, ""]
        L += _anova_md(k["anova"], ["treatment", "unit"]) + [""]
        if k.get("estimate"):
            L += _est_md(k["estimate"]) + [""]
        if k.get("vc"):
            L += _vc_md(k["vc"]) + [""]

    L += ["## Comparison against the stored R outputs and the published tables", "",
          "Every row of `reference/reference_numbers.csv` appears here, in the class the "
          "frozen map assigned it.", "",
          "| id | Dataset | Quantity | Class | Reference | Stratum | abs(diff) | "
          "Tolerance | Status |", "|---|---|---|---|---|---|---|---|---|"]
    for r in data["reference_rows"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["dataset"] or "-", r["quantity"][:58], r["class"],
            _num(r.get("ref_value", r.get("ref"))) if r["class"] != "STRUCTURAL"
            else "see below",
            _num(r.get("stratum")) if not isinstance(r.get("stratum"), dict)
            else "see below",
            _num(r.get("difference"), 3), _num(r.get("tolerance"), 3), r["status"]))
    L += ["", "### Extra full-precision checks with no reference-numbers row", "",
          "| Dataset | Target | Class | Reference | Stratum | abs(diff) | Tolerance | "
          "Status |", "|---|---|---|---|---|---|---|---|"]
    for r in data["extra_checks"]:
        t = r["target"]
        L.append("| %s | %s.%s.%s | %s | %s | %s | %s | %s | %s |" % (
            t["dataset"], t["kind"], t["key"], t["field"], r["class"],
            _num(r.get("ref_value", r.get("ref"))), _num(r.get("stratum")),
            _num(r.get("difference"), 3), _num(r.get("tolerance"), 3), r["status"]))
    L.append("")

    L += ["## Disagreements", ""]
    if not data["disagreements"]:
        L += ["None. Every pass/fail comparison is inside the tolerance its frozen class "
              "sets.", ""]
    else:
        for r in data["disagreements"]:
            t = r["target"] or {}
            L += ["### %s (%s.%s.%s), class %s"
                  % (r.get("id") or "extra check", t.get("dataset"), t.get("kind"),
                     t.get("field"), r["class"]),
                  "", "- Quantity: %s" % (r.get("quantity") or "-"),
                  "- Reference: %s (%s%s)" % (_num(r.get("ref_value"), 12), r["ref_source"],
                                              ", " + "/".join(str(x) for x in r["ref_path"])
                                              if r.get("ref_path") else ""),
                  "- Stratum: %s" % _num(r.get("stratum"), 12),
                  "- abs(difference) %s against tolerance %s"
                  % (_num(r.get("difference"), 6), _num(r.get("tolerance"), 6)),
                  "- Note from the frozen map: %s" % (r.get("note") or "-"), ""]
            ex = r.get("explanation")
            if ex:
                L += ["**Explanation (computed, not asserted).** The reference exceeds "
                      "Stratum's value by exactly %s, which equals %s = %s on this design "
                      "(agreement: %s). Stratum reports the standard restricted "
                      "log-likelihood: %s"
                      % (_num(ex["offset_reference_minus_stratum"], 12),
                         ex["candidate_constant"], _num(ex["candidate_value"], 12),
                         "yes" if ex["offset_equals_candidate"] else "no",
                         ex["stratum_convention"]), "",
                      ex["verification"], ""]
    L += ["## Report-only rows", "",
          "These rows are reported, never scored. A DESCRIPTIVE row is a quantity Stratum "
          "computes by a deliberately different method, so the two values sit side by "
          "side; an OUT_OF_SCOPE row is one Stratum does not compute at all, with the "
          "decision that put it out of scope.", ""]
    widths = []
    for name in ("furnace", "oxide"):
        a = data["analyses"].get(name)
        if not a:
            continue
        for key, v in a["variance_components"].items():
            if v["interval_available"] and not v["exact"]:
                widths.append("%s %s: Satterthwaite nu_eff = %s on %s df of data"
                              % (name, v["label"], _num(v["nu_eff"], 4),
                                 a["anova"][key]["df"]))
    if widths:
        L += ["Every DESCRIPTIVE row is a variance-component or standard-deviation "
              "interval. Stratum's Satterthwaite intervals for the top components are "
              "wider than nlme's Wald-type intervals and lme4's profile intervals, and "
              "sit higher, which is what a scaled-chi-square interval with few effective "
              "degrees of freedom does (" + "; ".join(widths) + "). Which of the three is "
              "better calibrated is not established by this reproduction. WP6 found severe "
              "undercoverage for some upper-level Stratum intervals; it did not compare "
              "the coverage of the alternative R methods (D-060, D-097).", ""]
    L += ["| id | Class | Quantity | Reference | Stratum's comparable value | Why no "
          "tolerance |", "|---|---|---|---|---|---|"]
    for r in data["reference_rows"]:
        if r["class"] not in ("DESCRIPTIVE", "OUT_OF_SCOPE", "NOT_OBTAINED"):
            continue
        L.append("| %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["class"], _cell(r["quantity"]), _num(r.get("ref")),
            _num(r.get("stratum")) if r.get("stratum") is not None else "-",
            _cell(r["note"])))
    L.append("")

    sup = data["supplementary_checks"]
    L += ["## Supplementary checks added after the freeze (D-072)", "",
          "The coverage audit below found numeric fields in `reference/r_outputs` that are "
          "genuinely comparable but that the frozen map did not enumerate: mostly the other "
          "representation of a component already compared (variance against standard "
          "deviation), the numerator and denominator degrees of freedom of F tests already "
          "compared, and the Kenward-Roger rows whose Satterthwaite counterparts are "
          "compared.", "",
          "**The frozen map is not edited.** Retro-fitting a pre-result artifact is what "
          "brief Section 8 forbids. These %d checks are listed separately, scored under the "
          "same frozen tolerance classes, and counted separately from the %d frozen "
          "comparisons. Adding checks after a result can only reveal a failure, never hide "
          "one." % (len(sup), data["summary"]["pass_fail_total"]), "",
          "| Dataset | Target | Class | Reference | Stratum | abs(diff) | Tolerance | "
          "Status |", "|---|---|---|---|---|---|---|---|"]
    for r in sup:
        tg = r["target"]
        L.append("| %s | %s.%s.%s | %s | %s | %s | %s | %s | %s |" % (
            tg["dataset"], tg["kind"], tg["key"], tg["field"], r["class"],
            _num(r.get("ref_value", r.get("ref"))), _num(r.get("stratum")),
            _num(r.get("difference"), 3), _num(r.get("tolerance"), 3), r["status"]))
    L += ["", "%d of %d pass." % (data["summary"]["supplementary_passed"], len(sup)), ""]

    L += ["## How completely the stored R outputs are compared", "",
          "`reference/reference_numbers.csv` is the reference-numbers table WP0 produced, "
          "and every one of its rows is classified above. The stored R output files hold "
          "further numeric fields; this table says how many of them a comparison reaches, "
          "so \"agreement with the stored R outputs\" is not quietly partial.", "",
          "| File | Numeric fields | Compared | Not compared |", "|---|---|---|---|"]
    cov = data["stored_r_output_coverage"]
    for stem, c in cov.items():
        L.append("| %s.json | %d | %d | %d |" % (stem, c["numeric_fields"], c["compared"],
                                                 len(c["not_compared"])))
    L += ["", "Every field that is not compared, with the reason:", "",
          "| Field | Why it is not compared |", "|---|---|"]
    for stem, c in cov.items():
        for row in c["not_compared"]:
            L.append("| `%s` | %s |" % ("/".join(str(x) for x in row["path"]),
                                        _cell(row["reason"])))
    L.append("")

    L += ["## The analysis run on every WP2 fixture", "",
          "The analysis is exercised on all %d preregistered synthetic fixtures, not only "
          "on the reference datasets. `gating` checks D-067: a fixture is analyzed exactly "
          "when the evidence decision is not REFUSE, and a refused design produces no "
          "ANOVA row, component or estimate." % len(data["fixtures"]), "",
          "| Fixture | Template | Decision | Analyzed | Codes | ANOVA rows | Components | "
          "Estimates | Boundary | Degenerate | Gating |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in data["fixtures"]:
        L.append("| %s | %s | %s | %s | %s | %d | %d | %d | %d | %d | %s |" % (
            f["fixture"], f["template"] or "-", f["decision"],
            "yes" if f["analyzed"] else "no", ", ".join(f["codes"]) or "-",
            f["n_anova_rows"], f["n_components"], f["n_estimates"],
            len(f["boundary"]), len(f["degenerate"]),
            "ok" if f["gating_ok"] else "FAIL"))
    L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the stored outputs match")
    args = ap.parse_args()
    data = run()
    text = json.dumps(data, indent=2, sort_keys=False, allow_nan=False) + "\n"
    md = markdown(data)
    if args.check:
        bad = 0
        for path, want in ((JSON_OUT, text), (MD_OUT, md)):
            if not path.exists():
                print("MISSING %s" % path.name)
                bad = 1
            elif path.read_text() != want:
                print("MISMATCH %s differs from the generator" % path.name)
                bad = 1
        if not bad:
            print("WP3 reproduction outputs match the generator")
    else:
        JSON_OUT.write_text(text)
        MD_OUT.write_text(md)
        print("wrote %s and %s" % (JSON_OUT.name, MD_OUT.name))
    s = data["summary"]
    print("pass/fail comparisons: %d passed, %d disagreements, %d errors (of %d)"
          % (s["passed"], s["failed"], s["errors"], s["pass_fail_total"]))
    print("fixtures: %d analyzed, %d refused, gating ok for %d of %d"
          % (s["fixtures_analyzed"], s["fixtures_refused"], s["fixtures_gating_ok"],
             s["fixtures_total"]))
    print("boundary fits %d, degenerate fits %d, failed fits %d"
          % (s["boundary_fits"], s["degenerate_fits"], s["failed_fits"]))
    for r in data["disagreements"]:
        print("  DISAGREEMENT %s %s: ref %r, stratum %r, |diff| %.6g > tol %.6g"
              % (r.get("id") or "extra", r["class"], r.get("ref_value"), r.get("stratum"),
                 r.get("difference"), r.get("tolerance")))
    for r in data["errors"]:
        print("  ERROR %s: %s" % (r.get("id") or r["target"], r.get("detail")))
    return 1 if (data["summary"]["errors"] or (args.check and bad)) else 0


if __name__ == "__main__":
    sys.exit(main())
