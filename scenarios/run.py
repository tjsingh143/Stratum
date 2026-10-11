#!/usr/bin/env python3
"""WP5: run a demonstration scenario end to end with one command (DECISIONS.md D-086).

    .venv/bin/python scenarios/run.py S1          # or S2, S3, --all
    .venv/bin/python scenarios/run.py --all --check

For each scenario it runs the unchanged Stratum pipeline (stratum.results.build, then
stratum.report.render) on the SYNTHETIC inputs from scenarios/generate.py. It then
evaluates every assertion preregistered in scenarios/expectations.json, which was committed
before this runner existed. It writes into the scenario directory:

    output/results.json     the results document (D-076, D-077)
    output/report.md        the report, rendered from results.json alone
    output/comparison.json  every preregistered assertion with its actual value and status
    WRITEUP.md              the write-up; its numbers are filled from results.json and
                            comparison.json by the {{...}} placeholders in writeup.md.in

Nothing here edits an expectation. A failed assertion is reported and makes the command fail.
"""
import argparse
import ast
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from stratum.dist import chi2_quantile, t_quantile  # noqa: E402
from stratum.report import fmt, render  # noqa: E402
from stratum.results import build, dumps  # noqa: E402

EXPECTATIONS = HERE / "expectations.json"


def descriptive(scn: dict, decl_path: Path, data_path: Path, doc: dict) -> dict:
    """Raw treatment-level means of the response, from the data file. Descriptive only: this
    is not an estimate Stratum supports for a refused design."""
    import yaml
    decl = yaml.safe_load(decl_path.read_text(encoding="utf-8"))
    t = decl["treatments"][0]
    col, resp = t["column"], decl["response"]["column"]
    groups = defaultdict(list)
    with data_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            groups[row[col]].append(float(row[resp]))
    means = {lv: sum(groups[lv]) / len(groups[lv]) for lv in t["levels"]}
    out = {"label": "descriptive only: raw means of every measurement per level of %r, "
                    "computed from the data file by scenarios/run.py; not an estimate Stratum "
                    "supports, and it says nothing about uncertainty" % t["name"],
           "factor": t["name"], "means": means,
           "measurements_per_level": {lv: len(groups[lv]) for lv in t["levels"]}}
    comp = next((c for c in decl["comparisons"] if c["kind"] == "pairwise"), None)
    if comp:
        hi, lo = comp["levels"]
        out["raw_mean_difference"] = means[hi] - means[lo]
        out["difference_of"] = "%s - %s" % (hi, lo)
    return out


# ---------------------------------------------------------------------------
# Evaluating the preregistered assertions (ops defined in expectations.json)
# ---------------------------------------------------------------------------

MISSING = object()


def resolve(doc, path):
    cur = doc
    for p in path:
        if isinstance(p, dict):
            (k, v), = p.items()
            if not isinstance(cur, list):
                return MISSING
            cur = next((x for x in cur if isinstance(x, dict) and x.get(k) == v), MISSING)
        elif isinstance(cur, dict):
            cur = cur.get(p, MISSING)
        elif isinstance(cur, list) and isinstance(p, int) and p < len(cur):
            cur = cur[p]
        else:
            return MISSING
        if cur is MISSING:
            return MISSING
    return cur


FUNCS = {"sqrt": math.sqrt, "chi2_quantile": chi2_quantile, "t_quantile": t_quantile}
BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
          ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def _expr(text):
    """Evaluate an `approx_expr` value: numbers, + - * /, unary minus and calls to the three
    whitelisted functions only. Anything else is refused."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
            return BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in FUNCS and not node.keywords:
            return FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("unsupported expression element in %r" % text)
    return ev(ast.parse(text, mode="eval"))


def check(doc, item) -> dict:
    op, value = item["op"], item["value"]
    actual = resolve(doc, item["path"])
    if op == "absent":
        ok = actual is MISSING or actual is None
    elif actual is MISSING:
        ok = False
    elif op == "eq":
        ok = actual == value
    elif op in ("approx", "approx_expr"):
        target = _expr(value) if op == "approx_expr" else value
        ok = isinstance(actual, (int, float)) and \
            abs(actual - target) <= 1e-9 * max(1.0, abs(target))
        if op == "approx_expr":
            item = dict(item, evaluated=target)
    elif op == "contains":
        ok = isinstance(actual, str) and value in actual
    elif op == "len":
        ok = hasattr(actual, "__len__") and len(actual) == value
    elif op == "field_set":
        ok = isinstance(actual, list) and \
            sorted({x.get(item["field"]) for x in actual}) == sorted(value)
    elif op == "lt":
        ok = isinstance(actual, (int, float)) and actual < value
    elif op == "gt":
        ok = isinstance(actual, (int, float)) and actual > value
    else:
        raise ValueError("unknown op %r" % op)
    shown = None if actual is MISSING else actual
    if op == "field_set" and isinstance(actual, list):
        shown = sorted({x.get(item["field"]) for x in actual})
    elif op == "len" and hasattr(actual, "__len__"):
        shown = len(actual)
    elif isinstance(shown, (dict, list)) and op not in ("eq",):
        shown = "<%s>" % type(shown).__name__
    return dict(item, actual=shown, status="MATCH" if ok else "MISMATCH")


# ---------------------------------------------------------------------------
# The write-up: {{path}} or {{path|digits}} placeholders, filled from the documents
# ---------------------------------------------------------------------------

PLACEHOLDER = re.compile(r"\{\{([^}|]+)(?:\|(\d+))?\}\}")


def _path(text):
    out = []
    for part in text.strip().split("."):
        if re.fullmatch(r"\d+", part):
            out.append(int(part))
        elif "=" in part:
            k, v = part.split("=", 1)
            out.append({k: v})
        else:
            out.append(part)
    return out


def fill(template: str, docs: dict) -> str:
    def sub(m):
        path = _path(m.group(1))
        value = resolve(docs, path)
        if value is MISSING:
            raise KeyError("write-up placeholder %r does not resolve" % m.group(1))
        return fmt(value, int(m.group(2)) if m.group(2) else 4)
    return PLACEHOLDER.sub(sub, template)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def run(scn: dict) -> dict:
    d = ROOT / scn["directory"]
    decl, data = d / "declaration_synthetic.yaml", d / "data_synthetic.csv"
    doc = json.loads(dumps(build(decl, data, synthetic=True, reproducible=True,
                                 data_label="SYNTHETIC demonstration scenario %s (%s); "
                                            "results show software behaviour, not process "
                                            "realism" % (scn["id"], scn["name"]))))
    desc = descriptive(scn, decl, data, doc)
    merged = dict(doc, descriptive=desc)
    checks = [check(merged, c) for c in scn["checks"]]
    comparison = {
        "scenario": scn["id"], "name": scn["name"], "synthetic": scn["synthetic"],
        "preregistered_in": "scenarios/expectations.json (D-086)",
        "assertions": len(checks),
        "matched": sum(1 for c in checks if c["status"] == "MATCH"),
        "status": "MATCH" if all(c["status"] == "MATCH" for c in checks) else "MISMATCH",
        "descriptive": desc, "checks": checks}
    files = {d / "output" / "results.json": dumps(doc),
             d / "output" / "report.md": render(doc),
             d / "output" / "comparison.json": json.dumps(comparison, indent=2,
                                                          ensure_ascii=False) + "\n"}
    tmpl = d / "writeup.md.in"
    if tmpl.exists():
        files[d / "WRITEUP.md"] = fill(tmpl.read_text(encoding="utf-8"),
                                       {"results": doc, "comparison": comparison,
                                        "descriptive": desc})
    return {"comparison": comparison, "files": files}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scenario", nargs="?", help="S1, S2 or S3")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="verify stored outputs match and every assertion holds")
    args = ap.parse_args()
    reg = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))
    chosen = [s for s in reg["scenarios"] if args.all or s["id"] == args.scenario]
    if not chosen:
        ap.error("name a scenario (S1, S2, S3) or pass --all")
    bad = 0
    for scn in chosen:
        out = run(scn)
        cmp_ = out["comparison"]
        for path, text in out["files"].items():
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    print("MISMATCH %s differs from the runner" % path.relative_to(ROOT))
                    bad = 1
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        print("%s %s: %s, %d of %d preregistered assertions match"
              % (scn["id"], scn["name"], cmp_["status"], cmp_["matched"], cmp_["assertions"]))
        for c in cmp_["checks"]:
            if c["status"] != "MATCH":
                print("  MISMATCH %s %s expected %r, actual %r"
                      % (c["path"], c["op"], c.get("evaluated", c["value"]), c["actual"]))
                bad = 1
    return bad


if __name__ == "__main__":
    sys.exit(main())
