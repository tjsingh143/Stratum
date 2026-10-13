"""Compare scenario replays without confusing numerical agreement with byte identity.

The numerical budget applies only to finite JSON floats. Structure, types, integer
counts, labels, decisions and provenance remain exact. Stored reports are checked
against their own results; a fresh report is checked against its fresh results.
No stored file or preregistered expectation is changed by these checks.
"""
import json
import math
from pathlib import Path
from typing import Callable, Dict, List

REL_TOL = 1e-12


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key %r" % key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError("non-finite JSON number %s" % value)


def parse(text: str):
    return json.loads(text, object_pairs_hook=_object, parse_constant=_constant)


def numerical_differences(expected, actual, path: str = "$", limit: int = 8) -> List[str]:
    """Return bounded diagnostics; there is no absolute-error allowance near zero."""
    differences = []

    def visit(a, b, where):
        if len(differences) >= limit:
            return
        if type(a) is not type(b):
            differences.append("%s: type changed" % where)
        elif isinstance(a, dict):
            if set(a) != set(b):
                differences.append("%s: object keys changed" % where)
                return
            for key in a:
                visit(a[key], b[key], where + "." + key)
        elif isinstance(a, list):
            if len(a) != len(b):
                differences.append("%s: list length changed" % where)
                return
            for i, (x, y) in enumerate(zip(a, b)):
                visit(x, y, "%s[%d]" % (where, i))
        elif isinstance(a, float):
            if not (math.isfinite(a) and math.isfinite(b)):
                differences.append("%s: non-finite float" % where)
            elif not math.isclose(a, b, rel_tol=REL_TOL, abs_tol=0.0):
                differences.append("%s: numerical drift exceeds %.0e relative" % (where, REL_TOL))
        elif a != b:
            differences.append("%s: value changed" % where)

    visit(expected, actual, path)
    return differences


def verify_outputs(files: Dict[Path, str], renderer: Callable, strict_bytes: bool = False) -> List[str]:
    """Read the golden files, verify every output, and never rewrite an artifact."""
    errors = []
    stored = {}
    fresh = {}
    texts = {}
    for path, text in files.items():
        try:
            old = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append("%s: cannot read stored output (%s)" % (path, exc))
            continue
        texts[path] = old
        if strict_bytes:
            if old.encode("utf-8") != text.encode("utf-8"):
                errors.append("%s: byte mismatch" % path)
        elif path.suffix == ".json":
            try:
                stored[path], fresh[path] = parse(old), parse(text)
                errors += ["%s: %s" % (path, detail) for detail in
                           numerical_differences(stored[path], fresh[path])]
            except (ValueError, TypeError) as exc:
                errors.append("%s: invalid JSON (%s)" % (path, exc))
        elif path.name != "report.md" and old != text:
            errors.append("%s: text mismatch" % path)

    if not strict_bytes:
        for path, text in files.items():
            if path.name != "report.md" or path not in texts:
                continue
            results = path.with_name("results.json")
            if results not in stored or results not in fresh:
                errors.append("%s: results.json is required for report verification" % path)
                continue
            if texts[path] != renderer(stored[results]):
                errors.append("%s: stored report does not render from stored results" % path)
            if text != renderer(fresh[results]):
                errors.append("%s: fresh report does not render from fresh results" % path)
    return errors
