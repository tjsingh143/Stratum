"""WP4: the command-line interface (brief Sections 4 and 7; D-076).

    python -m stratum analyze <declaration.yaml> <data.csv> --out <dir> [--synthetic]
        writes <dir>/results.json and <dir>/report.md
    python -m stratum report <results.json> [--out report.md]
        renders a report from a results.json alone
    python -m stratum explanations [--check] [--guide]
        checks resources/explanations.yaml against the category registry (D-075), and
        writes or checks resources/EXPLANATIONS_GUIDE.md

The CLI adds nothing the library does not do.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

from . import explain, __version__
from .report import render
from .results import build, dumps

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "fixtures" / "synthetic_wp2" / "expectations.json"


def _analyze(args) -> int:
    doc = build(Path(args.declaration), Path(args.data),
                explanations=Path(args.explanations),
                synthetic=True if args.synthetic else None, data_label=args.data_label)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(dumps(doc), encoding="utf-8")
    (out / "report.md").write_text(render(doc), encoding="utf-8")
    print("decision %s; wrote %s and %s" % (doc["decision"]["evidence_decision"],
                                           out / "results.json", out / "report.md"))
    return 0


def _report(args) -> int:
    doc = json.loads(Path(args.results).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != "stratum-results/1":
        raise ValueError("expected a Stratum results.json with schema stratum-results/1")
    text = render(doc)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def fixture_occurrences() -> dict:
    """Categories occurring in each WP2 fixture under the current pipeline."""
    from .analysis import analyze
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    occ = {}
    base = REGISTRY.parent
    for f in reg["fixtures"]:
        res = analyze(base / f["files"]["declaration"], base / f["files"]["data"])
        ev = res.evidence
        decl = ev.match.declaration if ev.match is not None else None
        names = [x.code for x in ev.findings]
        for x in ev.findings:
            names += [r["category"] for r in x.details.get("wp1_refusals", [])]
        if res.analyzed and decl is not None:
            for comp in decl.comparisons:
                if any(decl.treatment(n).assignment_method != "randomized" for n in comp.factors):
                    names.append("assignment_not_randomized")
            if res.fits.get("boundary"):
                names.append("boundary_fit")
            if res.fits.get("degenerate"):
                names.append("degenerate_fit")
        for n in dict.fromkeys(names):
            occ.setdefault(n, []).append(f["id"])
    return occ


def _explanations(args) -> int:
    path = Path(args.file)
    try:
        entries = explain.load(path)
    except explain.ExplanationError as exc:
        print("FAIL %s" % exc)
        return 1
    cov = explain.coverage(entries)
    print("%s matches the registry: %d of %d required explanations written, %d of %d optional"
          % (path.name, cov["required_written"], cov["required"], cov["optional_written"],
             cov["optional"]))
    if args.guide or args.check:
        text = explain.guide_text(explain.wp2_definitions(REGISTRY), fixture_occurrences())
        if args.check:
            if not explain.GUIDE_FILE.exists() or \
                    explain.GUIDE_FILE.read_text(encoding="utf-8") != text:
                print("MISMATCH %s differs from the generator" % explain.GUIDE_FILE.name)
                return 1
            print("%s matches the generator" % explain.GUIDE_FILE.name)
        else:
            explain.GUIDE_FILE.write_text(text, encoding="utf-8")
            print("wrote %s" % explain.GUIDE_FILE)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m stratum", description="Check a declared T1/T2/T3 design and analyze only supported comparisons.",
        epilog="Workflow: analyze DECLARATION.yaml DATA.csv --out OUTPUT; report OUTPUT/results.json. "
               "A scientific REFUSE is a successful result (exit 0). Input/operational errors exit 1; "
               "usage errors exit 2. Examples and reference workflow: README.md; "
               "repository checks: python3 run_checks.py.")
    ap.add_argument("--version", action="version", version="Stratum " + __version__)
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze", help="declaration + data -> results.json and report.md")
    a.add_argument("declaration", help="design YAML; schema and examples: declarations/README.md")
    a.add_argument("data", help="UTF-8 CSV with unique headers; empty/NA responses mean missing")
    a.add_argument("--out", required=True, help="output directory")
    a.add_argument("--synthetic", action="store_true",
                   help="label the run synthetic (also automatic for *synthetic* file names)")
    a.add_argument("--data-label", default=None, help="how to describe the data source")
    a.add_argument("--explanations", default=str(explain.DEFAULT_FILE))
    a.set_defaults(fn=_analyze)
    r = sub.add_parser("report", help="render report.md from a results.json")
    r.add_argument("results")
    r.add_argument("--out", default=None)
    r.set_defaults(fn=_report)
    e = sub.add_parser("explanations", help="maintainer check of explanation coverage and generated guide")
    e.add_argument("--file", default=str(explain.DEFAULT_FILE))
    e.add_argument("--check", action="store_true", help="also check the guide is current")
    e.add_argument("--guide", action="store_true", help="write resources/EXPLANATIONS_GUIDE.md")
    e.set_defaults(fn=_explanations)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError, csv.Error, explain.ExplanationError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
