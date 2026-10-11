"""WP4: results.json, the single source of every number the report prints (D-076, D-077).

`build(declaration_path, data_path)` runs the WP1/WP2/WP3 pipeline unchanged, adds the
WP4 allocation analysis (D-078, D-079), the reassignment suggestion (D-080), the planning
pathway (D-081), the explanation texts (D-075, D-084) and the provenance (D-077), and returns
a JSON-serialisable document. The report renderer (stratum.report) reads only this
document.
"""
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from . import explain
from .allocation import allocation_for_analysis, allocation_for_planning, planning
from .analysis import analyze
from .evidence import _jsonable
from .reassign import suggestions

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
SCHEMA = "stratum-results/1"
REPRODUCIBLE_NOTE = ("omitted from committed reports so that they regenerate byte for byte: "
                     "a commit hash written into a committed file is always the parent of the "
                     "commit that contains it. source_sha256 identifies the code (D-077).")


# ---------------------------------------------------------------------------
# Provenance (D-077)
# ---------------------------------------------------------------------------

def _rel(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def file_record(path: Path) -> dict:
    data = Path(path).read_bytes()
    return {"path": _rel(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def source_hash() -> dict:
    files = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
    lines = ["%s %s" % (p.relative_to(ROOT).as_posix(),
                        hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
    return {"package": "stratum", "version": __version__,
            "source_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
            "source_files": len(files),
            "method": "SHA-256 over the sorted lines '<relative path> <file SHA-256>' of every "
                      "file in the stratum package (D-077)"}


def _git() -> Optional[dict]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
        return {"commit": commit, "dirty": bool(dirty)}
    except (OSError, subprocess.CalledProcessError):
        return None


def provenance(declaration: Path, data: Path, explanations: Path, reproducible: bool) -> dict:
    out = {"inputs": {"declaration": file_record(declaration), "data": file_record(data),
                      "explanations": file_record(explanations)},
           "code": source_hash()}
    if reproducible:
        out["git"] = None
        out["environment"] = None
        out["omitted"] = REPRODUCIBLE_NOTE
    else:
        try:
            import yaml
            yver = yaml.__version__
        except Exception:                                   # pragma: no cover
            yver = None
        out["git"] = _git()
        out["environment"] = {"python": platform.python_version(), "pyyaml": yver}
    return out


# ---------------------------------------------------------------------------
# Findings, caveats and explanations
# ---------------------------------------------------------------------------

def _finding_records(ev, entries) -> List[dict]:
    out = []
    for f in ev.findings:
        rec = {"code": f.code, "severity": f.severity, "stage": f.stage,
               "message": f.message, "details": f.details,
               "explanation": explain.lookup(entries, f.code)}
        if f.code == "declaration_refused":
            rec["wp1_refusals"] = []
            for r in (ev.match.refusals if ev.match is not None else ()):
                rec["wp1_refusals"].append({
                    "category": r.category, "condition": r.condition, "path": r.path,
                    "declared": r.declared, "requirement": r.requirement,
                    "reason": r.reason, "remedy": r.remedy,
                    "explanation": explain.lookup(entries, r.category)})
        out.append(rec)
    return out


def _caveats(res, decl, entries) -> List[dict]:
    out = []
    if not res.analyzed or decl is None:
        return out
    compared = []
    for comp in decl.comparisons:
        for name in comp.factors:
            if name not in compared:
                compared.append(name)
    for name in compared:
        t = decl.treatment(name)
        if t.assignment_method != "randomized":
            out.append({"code": "assignment_not_randomized", "severity": "caveat",
                        "message": "Factor %r: assignment.method is %r in the declaration%s. "
                                   "The tests and intervals are computed the same way for "
                                   "every assignment method; the caveat concerns attributing "
                                   "a difference to the factor (D-039)."
                                   % (t.name, t.assignment_method,
                                      " (%s)" % t.assignment_description.strip()
                                      if t.assignment_description else ""),
                        "details": {"factor": t.name, "method": t.assignment_method},
                        "explanation": explain.lookup(entries, "assignment_not_randomized")})
    for kind, code in (("boundary", "boundary_fit"), ("degenerate", "degenerate_fit")):
        items = res.fits.get(kind, [])
        if items:
            out.append({"code": code, "severity": "caveat",
                        "message": "; ".join("%s: %s" % (i.get("component", i.get("stratum")),
                                                         i.get("note", i.get("kind")))
                                             for i in items),
                        "details": {"items": items},
                        "explanation": explain.lookup(entries, code)})
    return out


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

def _test_row(row) -> Optional[dict]:
    if not row:
        return None
    return {"source": row["source"], "F": row["F"], "num_df": row["num_df"],
            "den_df": row["den_df"], "p": row["p"], "error_term": row["error_term"],
            "note": row.get("note", "")}


def _estimates_for(res, comp_id) -> List[dict]:
    out = []
    for key, e in res.estimate.items():
        if e.get("comparison") != comp_id:
            continue
        rec = dict(e)
        rec["key"] = key
        rec["half_width"] = e["t_critical"] * e["se"] if e["t_critical"] is not None else None
        rec["interval_includes_zero"] = (e["lower"] <= 0.0 <= e["upper"]) if e["lower"] is not None else None
        out.append(rec)
    return out


def _comparisons(res, decl, ev) -> List[dict]:
    if decl is None:
        return []
    repl = ev.evidence.get("replication", {}) if ev.evidence else {}
    refusals = [f for f in ev.findings if f.severity == "refuse"]
    out = []
    for comp in decl.comparisons:
        rec = {"id": comp.id, "kind": comp.kind, "factors": list(comp.factors),
               "levels": list(comp.levels) if comp.levels else None,
               "description": comp.description}
        if decl.claimed_template == "T3":
            a, b = decl.split_plot.whole_plot_factor, decl.split_plot.subplot_factor
            role = "AB" if comp.kind == "interaction" else ("A" if comp.factors[0] == a else "B")
            rec["role"] = {"A": "whole-plot factor", "B": "subplot factor",
                           "AB": "interaction"}[role]
            rec["experimental_unit"] = decl.top.name
            rec["units_note"] = ("%s is applied to whole %ss" % (a, decl.top.name)
                                 if role == "A" else
                                 "each %s contributes one independent within-%s comparison"
                                 % (decl.top.name, decl.top.name))
        else:
            role = "treatment"
            t = decl.treatment(comp.factors[0])
            rec["role"] = "treatment"
            rec["experimental_unit"] = t.applied_to
        if res.analyzed:
            approx = bool(res.design.get("missing_site_exception"))
            rec["status"] = "analyzed_approximate" if approx else "analyzed"
            key = {"treatment": "treatment", "A": "A", "B": "B", "AB": "AB"}[role]
            rec["test"] = _test_row(res.anova.get(key))
            rec["estimates"] = _estimates_for(res, comp.id)
            if role in ("treatment", "A"):
                rec["independent_units"] = {"per_level": res.design["replicates_per_level"],
                                            "level": rec["experimental_unit"]}
            else:
                rec["independent_units"] = {"total": res.design["whole_plots"],
                                            "level": rec["experimental_unit"]}
        else:
            rec["status"] = "refused"
            rec["test"] = None
            rec["estimates"] = []
            if repl:
                rec["independent_units"] = {"per_level": repl.get("present_per_level"),
                                            "level": repl.get("applied_to")}
            specific = [f.code for f in refusals if f.details.get("comparison") == comp.id]
            rec["refusal_codes"] = sorted({f.code for f in refusals})
            rec["specific_refusal_codes"] = sorted(set(specific))
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Assumptions and diagnostics
# ---------------------------------------------------------------------------

def _assumptions(res, ev, decl) -> List[dict]:
    tmpl = ev.claimed_template
    s5 = next((s.status for s in ev.stages if s.id == "S5"), "not_evaluated")
    s8 = next((s.status for s in ev.stages if s.id == "S8"), "not_evaluated")
    codes = {f.code for f in ev.findings}

    def diag_status(warn_codes, diagnostic_names):
        if s8 == "not_evaluated":
            return "not_evaluated"
        if codes & set(warn_codes):
            return "warn"
        diagnostics = ev.evidence.get("diagnostics", {})
        values = [v for group in diagnostics.values() if isinstance(group, dict)
                  for key, v in group.items() if key in diagnostic_names and isinstance(v, dict) and not v.get("not_applicable")]
        if not values or not any(v.get("available") for v in values):
            return "unavailable"
        if not all(v.get("available") and not v.get("undefined_units") for v in values):
            return "partly_unavailable; no warning triggered"
        return "no warning triggered; assumption not verified"
    out = [{"assumption": "balance at the experimental-unit level",
            "handling": "checked from the data; imbalance is refused (S5)",
            "status": s5}]
    if tmpl in ("T2", "T3"):
        out.append({"assumption": "equal variance across treatment levels",
                    "handling": "diagnosed: Brown-Forsythe test and largest-to-smallest SD "
                                "ratio of unit means; warnings only (D-044)",
                    "status": diag_status(("brown_forsythe", "sd_ratio"), ("brown_forsythe", "sd_ratio"))})
    out.append({"assumption": "normally distributed random effects and errors",
                "handling": "diagnosed: normal quantile plot and externally studentized "
                            "residuals beyond +-3; warnings only (D-044)",
                "status": diag_status(("studentized_residual",), ("studentized_residuals",))})
    out.append({"assumption": "independent experimental units",
                "handling": "not checkable from the data; it rests on how the units were "
                            "run and assigned (the declared assignment method)",
                "status": "not_checkable"})
    if tmpl == "T2" and decl is not None and decl.blocks:
        out.append({"assumption": "no treatment x block interaction",
                    "handling": "not tested; the additive error term contains any "
                                "interaction, which makes the treatment test conservative "
                                "(D-063)", "status": "not_checked"})
    if res.analyzed and res.design.get("missing_site_exception"):
        out.append({"assumption": "unit means of equal precision",
                    "handling": "violated by unequal site counts; the treatment test and "
                                "intervals are approximate (D-016, D-065)",
                    "status": "approximate"})
    return out


def _qq_display(diag: dict) -> dict:
    out = {}
    for stratum, res in (diag or {}).items():
        st = res.get("studentized_residuals", {}) if isinstance(res, dict) else {}
        nq = st.get("normal_quantiles")
        if not st.get("available") or not nq:
            continue
        xs, ys = nq["theoretical"], nq["internally_studentized_sorted"]
        out[stratum] = {"n": len(xs), "x_min": min(xs), "x_max": max(xs),
                        "y_min": min(ys), "y_max": max(ys)}
    return out


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary(doc) -> dict:
    comps = doc["comparisons"]
    fnd = doc["findings"]
    out = {"decision": doc["decision"]["evidence_decision"],
           "analyzed": doc["decision"]["analyzed"],
           "analyzed_comparisons": [c["id"] for c in comps if c["status"].startswith("analyzed")],
           "refused_comparisons": [c["id"] for c in comps if c["status"] == "refused"],
           "refusal_codes": sorted({f["code"] for f in fnd if f["severity"] == "refuse"}),
           "warning_codes": sorted({f["code"] for f in fnd if f["severity"] == "warn"}),
           "note_codes": sorted({f["code"] for f in fnd if f["severity"] == "note"}),
           "caveat_codes": sorted({c["code"] for c in doc["caveats"]})}
    steps = []
    for f in fnd:
        for r in f.get("wp1_refusals", []):
            if r.get("remedy"):
                steps.append({"kind": "wp1_remedy", "category": r["category"],
                              "text": r["remedy"]})
    if doc["reassignment"].get("status") == "produced":
        steps.append({"kind": "reassignment", "text": "A crossed, randomized reassignment is "
                                                      "proposed in the reassignment section."})
    for comp in doc["allocation"].get("comparisons", []):
        for key in ("robust_conclusion", "floor_statement"):
            if comp.get(key):
                steps.append({"kind": "allocation", "factor": comp["factor"],
                              "text": comp[key]})
    out["next_steps"] = steps
    pending = []
    for f in fnd + doc["caveats"]:
        for e in [f["explanation"]] + [r["explanation"] for r in f.get("wp1_refusals", [])]:
            if e["status"] == "pending" and e["category"] not in pending:
                pending.append(e["category"])
    out["pending_in_report"] = pending
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def is_synthetic(*paths: Path) -> bool:
    return any("synthetic" in Path(p).name.lower() for p in paths)


def build(declaration: Path, data: Path, *, explanations: Path = explain.DEFAULT_FILE,
          synthetic: Optional[bool] = None, data_label: Optional[str] = None,
          reproducible: bool = False) -> dict:
    declaration, data, explanations = Path(declaration), Path(data), Path(explanations)
    entries = explain.load(explanations)
    res = analyze(declaration, data)
    ev = res.evidence
    decl = ev.match.declaration if ev.match is not None else None
    synth = is_synthetic(declaration, data) if synthetic is None else synthetic
    prov = provenance(declaration, data, explanations, reproducible)

    plan = planning(ev, decl, data) if not res.analyzed else {"eligible": False,
                                                              "reason": "the design was "
                                                                        "analyzed"}
    if res.analyzed:
        allocation = allocation_for_analysis(res, decl)
    elif plan["eligible"]:
        allocation = allocation_for_planning(plan, decl)
    else:
        allocation = {"status": "not_applicable",
                      "reason": "the design was refused and is outside the planning pathway: "
                                "%s" % plan.get("reason", "")}
    reassignment = suggestions(ev, decl, prov["inputs"]["declaration"]["sha256"],
                               prov["inputs"]["data"]["sha256"], plan)

    analysis = res.to_dict()
    evidence = analysis.pop("evidence")
    if analysis.get("fits"):
        for kind in ("boundary", "degenerate", "failed"):
            analysis["fits"]["%s_count" % kind] = len(analysis["fits"].get(kind, []))
    doc = {
        "schema": SCHEMA,
        "generated_by": "stratum %s (stratum.results.build); never hand-edited" % __version__,
        "synthetic": synth,
        "data_label": data_label or ("labelled synthetic data; results show software "
                                     "behavior, not process realism (brief Section 3.3)"
                                     if synth else "user-supplied data"),
        "provenance": prov,
        "declaration": {"claimed_template": ev.claimed_template,
                        "description": decl.description if decl else None,
                        "response": {"column": decl.response.column,
                                     "units": decl.response.units} if decl else None,
                        "hierarchy": [{"name": lv.name, "count": lv.count,
                                       "per_parent": not lv.is_top,
                                       "exchangeable": lv.exchangeable,
                                       "exchangeable_declared": lv.exchangeable_declared}
                                      for lv in decl.hierarchy] if decl else [],
                        "treatments": [{"name": t.name, "levels": list(t.levels),
                                        "applied_to": t.applied_to,
                                        "replicates_per_level": t.replicates_per_level,
                                        "assignment": t.assignment_method}
                                       for t in decl.treatments] if decl else [],
                        "nuisance_factors": [{"name": f.name, "role": f.role,
                                              "recorded_at": f.recorded_at}
                                             for f in decl.nuisance_factors] if decl else []},
        "decision": {"evidence_decision": ev.decision, "analyzed": res.analyzed,
                     "template": res.template},
        "comparisons": _comparisons(res, decl, ev),
        "findings": _finding_records(ev, entries),
        "caveats": _caveats(res, decl, entries),
        "stages": evidence["stages"],
        "assumptions": _assumptions(res, ev, decl),
        "diagnostics": (ev.evidence or {}).get("diagnostics"),
        "diagnostics_display": _qq_display((ev.evidence or {}).get("diagnostics")),
        "evidence": evidence["evidence"],
        "analysis": analysis,
        "allocation": allocation,
        "reassignment": reassignment,
        "planning": {k: v for k, v in plan.items() if k != "evidence"},
        "explanations": dict(explain.coverage(entries),
                             file=prov["inputs"]["explanations"]["path"],
                             policy="D-075 (verbatim insertion, pending marked)"),
    }
    doc["summary"] = _summary(doc)
    return _jsonable(doc)


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=False, allow_nan=False, ensure_ascii=False) + "\n"
