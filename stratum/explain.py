"""WP4: the refusal and warning categories, and their plain-language explanations.

The plain-language explanation of each refusal and warning category lives in
`resources/explanations.yaml` (DECISIONS.md D-075). This module holds no explanation
text. It holds:

  * the registry of categories (D-075 item 2): every WP1 refusal category, every WP2
    evidence code of severity refuse or warn, the three WP4 report caveats, and the two
    WP2 note codes as optional entries;
  * the loader for `resources/explanations.yaml`, whose `text` fields the report uses
    verbatim (a `null` text is reported as pending);
  * the generator of `resources/EXPLANATIONS_GUIDE.md`: technical facts and questions per
    category, never draft wording.
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .declaration import _StrictLoader
from .evidence import CODES
from .refusal import CATEGORIES as WP1_CATEGORIES

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "resources" / "explanations.yaml"
GUIDE_FILE = ROOT / "resources" / "EXPLANATIONS_GUIDE.md"
FORMAT = "stratum-explanations/1"
PENDING = ("pending: the plain-language explanation of this category has not been written "
           "yet (resources/explanations.yaml; D-075)")


@dataclass(frozen=True)
class Category:
    name: str
    kind: str            # refusal, warning, caveat, note
    source: str          # "WP1 refusal category", "WP2 evidence code", "WP4 report caveat"
    required: bool
    decisions: Tuple[str, ...]
    fact: Optional[str] = None   # technical fact for WP1 and WP4 categories (WP2: registry)


# Technical facts (constraints an explanation must be consistent with, not wording). WP2
# codes take theirs from the frozen vocabulary in fixtures/synthetic_wp2/expectations.json.
WP1_FACTS = {
    "yaml_syntax": "The declaration file is not parseable YAML, or repeats a key.",
    "schema": "A required field is missing, a field is unknown, or a value has the wrong type.",
    "inconsistent_declaration": "A name refers to something not declared, or two parts of "
                                "the declaration contradict each other.",
    "unknown_template": "claimed_template is not exactly T1, T2 or T3; Stratum does not guess "
                        "which template was meant.",
    "hierarchy": "The unit hierarchy's shape (number of levels, counts per parent) is outside "
                 "the claimed template.",
    "treatment_structure": "The number or kind of treatments does not fit the claimed template.",
    "application_level": "A treatment is applied at a level of the hierarchy the template does "
                         "not support (e.g. a T2 treatment on a nested level).",
    "assignment": "An observed (inherent) property is declared as an applied treatment where "
                  "the template needs an assigned one (D-039).",
    "replication": "Too few units at a level for the template's inference; with one unit per "
                   "treatment level the test has zero error degrees of freedom, and lower-level "
                   "measurements cannot replace units (brief Section 5.2).",
    "balance": "The declared counts do not form the balanced structure the template requires.",
    "blocking": "A block outside the one supported form: one balanced block crossed with a T2 "
                "treatment at the experimental unit.",
    "split_plot": "Split-plot roles are missing, malformed, or declared outside T3; a T3 with "
                  "one subplot level is refused as T3 and not remapped (D-021).",
    "exchangeability": "Subsampling semantics contradict the template: a T3 subplot level "
                       "cannot be exchangeable, because each subplot unit carries a level of "
                       "the subplot factor (D-037).",
    "comparison": "The intended comparisons do not fit the template (e.g. none declared, or an "
                  "interaction in T2).",
}
CAVEAT_FACTS = {
    "assignment_not_randomized": "A compared factor's assignment is declared systematic, "
                                 "not_stated or inherent. The F test and intervals are computed "
                                 "the same way; what differs is whether a difference can be "
                                 "attributed to the factor itself. Does not change the evidence "
                                 "decision (D-039, D-075).",
    "boundary_fit": "A method-of-moments variance component is negative (reported as negative, "
                    "then truncated at 0), or a REML component is exactly 0 because adjacent "
                    "strata were pooled (brief Section 5.1; D-064, D-066).",
    "degenerate_fit": "An error mean square is exactly 0, so an F statistic with it as "
                      "denominator is not defined (D-066).",
}
WP2_DECISIONS = {
    "S0": ("D-038", "D-048"), "S1": ("D-048",), "S2": ("D-043", "D-048"),
    "S3": ("D-036", "D-048"), "S4": ("D-047", "D-048"),
    "S5": ("D-016", "D-021", "D-022", "D-028", "D-043", "D-047"),
    "S6": ("D-045", "D-053"), "S7": ("D-046", "D-054"), "S8": ("D-044", "D-055"),
}


def registry() -> List[Category]:
    out = [Category(c, "refusal", "WP1 refusal category", True, ("D-035", "D-036", "D-037",
                                                                  "D-038", "D-039"),
                    WP1_FACTS[c]) for c in WP1_CATEGORIES]
    kind = {"refuse": "refusal", "warn": "warning", "note": "note"}
    for code, (sev, stage) in CODES.items():
        out.append(Category(code, kind[sev], "WP2 evidence code", sev != "note",
                            WP2_DECISIONS[stage]))
    for c, fact in CAVEAT_FACTS.items():
        dec = ("D-039", "D-075") if c == "assignment_not_randomized" else ("D-066", "D-075")
        out.append(Category(c, "caveat", "WP4 report caveat", True, dec, fact))
    names = [c.name for c in out]
    if len(names) != len(set(names)):
        raise ValueError("duplicate category names in the registry")
    return out


def by_name() -> Dict[str, Category]:
    return {c.name: c for c in registry()}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ExplanationError(ValueError):
    pass


def load(path: Path = DEFAULT_FILE) -> Dict[str, dict]:
    """The file's entries, validated against the registry. Raises ExplanationError on any
    disagreement; never fills a missing text."""
    path = Path(path)
    try:
        # _StrictLoader is yaml.SafeLoader plus duplicate-key refusal (D-035): safe.
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise ExplanationError("%s is not valid YAML: %s" % (path, exc))
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ExplanationError("%s: expected `format: %s`" % (path, FORMAT))
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        raise ExplanationError("%s: `entries` must be a mapping of category -> entry" % path)
    reg = by_name()
    problems = []
    missing = sorted(set(reg) - set(entries))
    extra = sorted(set(entries) - set(reg))
    if missing:
        problems.append("categories missing from the file: %s" % ", ".join(missing))
    if extra:
        problems.append("entries that are not registry categories: %s" % ", ".join(extra))
    for name, e in entries.items():
        if name not in reg:
            continue
        if not isinstance(e, dict) or set(e) - {"kind", "text", "same_as"}:
            problems.append("%s: an entry has only kind, text and same_as" % name)
            continue
        if e.get("kind") != reg[name].kind:
            problems.append("%s: kind %r, the registry says %r" % (name, e.get("kind"),
                                                                    reg[name].kind))
        text, same = e.get("text"), e.get("same_as")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            problems.append("%s: text must be null or non-empty text" % name)
        if same is not None:
            if text is not None:
                problems.append("%s: give either text or same_as, not both" % name)
            if same not in entries or entries.get(same, {}).get("same_as"):
                problems.append("%s: same_as must name an entry that has its own text field"
                                % name)
    if problems:
        raise ExplanationError("%s disagrees with the category registry: %s"
                               % (path, "; ".join(problems)))
    return entries


def lookup(entries: Dict[str, dict], name: str) -> dict:
    reg = by_name()
    cat = reg.get(name)
    if cat is None:
        raise KeyError("no category %r in the registry" % name)
    e = entries.get(name, {})
    text, via = e.get("text"), None
    if e.get("same_as"):
        via = e["same_as"]
        text = entries[via].get("text")
    if text is not None:
        return {"category": name, "kind": cat.kind, "status": "written",
                "text": text, "same_as": via}
    return {"category": name, "kind": cat.kind,
            "status": "pending" if cat.required else "optional_pending",
            "text": None, "same_as": via, "pending_label": PENDING}


def coverage(entries: Dict[str, dict]) -> dict:
    reg = registry()
    req = [c for c in reg if c.required]
    written = [c.name for c in req if lookup(entries, c.name)["status"] == "written"]
    opt = [c for c in reg if not c.required]
    return {"required": len(req), "required_written": len(written),
            "required_pending": [c.name for c in req if c.name not in written],
            "optional": len(opt),
            "optional_written": sum(1 for c in opt
                                    if lookup(entries, c.name)["status"] == "written")}


# ---------------------------------------------------------------------------
# The scaffold and the guide (generated; no explanation wording)
# ---------------------------------------------------------------------------

SCAFFOLD_HEADER = """\
# Plain-language explanations of the refusal and warning categories.
#
# Used by the WP4 report; DECISIONS.md D-075 describes how they are used.
#
# The report inserts each `text` verbatim, unchanged, wherever the category occurs, beside
# the technical detail. A `null` text is shown as pending. `same_as: <category>` reuses
# another entry's text. Technical facts per category: resources/EXPLANATIONS_GUIDE.md.
# Check this file with:  .venv/bin/python -m stratum explanations --check
"""


def scaffold_text() -> str:
    lines = [SCAFFOLD_HEADER, "format: %s" % FORMAT, "entries:"]
    current = None
    for c in registry():
        section = "%s (%s%s)" % (c.source, c.kind, "" if c.required else ", optional")
        if section != current:
            lines.append("  # --- %s ---" % section)
            current = section
        lines.append("  %s:" % c.name)
        lines.append("    kind: %s" % c.kind)
        lines.append("    text: null")
    return "\n".join(lines) + "\n"


QUESTIONS = (
    "What happened, in words a reader with no statistics training understands?",
    "What can, and what cannot, be concluded from the experiment because of it?",
    "What can the experimenter do next?",
)


def guide_text(wp2_definitions: Dict[str, str], occurrences: Dict[str, List[str]]) -> str:
    L = ["# Guide to writing the plain-language explanations", "",
         "Generated by `python -m stratum explanations --guide`. **Do not edit.** It lists, for "
         "each category in `resources/explanations.yaml`, the technical facts an explanation "
         "must be consistent with, the decisions that govern it, and the WP2 synthetic fixtures "
         "in which it occurs. The explanations themselves are in `resources/explanations.yaml` "
         "(D-075).", "",
         "Each explanation should answer the same three questions:", ""]
    L += ["%d. %s" % (i, q) for i, q in enumerate(QUESTIONS, start=1)]
    L += ["", "The report always prints the technical detail beside the explanation, so the "
              "explanation does not need to repeat numbers.", ""]
    current = None
    for c in registry():
        section = "%s: %s" % (c.source, c.kind + ("" if c.required else " (optional)"))
        if section != current:
            L += ["## %s" % section, ""]
            current = section
        fact = c.fact if c.fact is not None else wp2_definitions.get(c.name, "")
        L += ["### `%s`" % c.name, "",
              "- **Technical fact:** %s" % fact,
              "- **Governing decisions:** %s" % ", ".join(c.decisions),
              "- **Occurs in fixtures:** %s" % (", ".join(occurrences.get(c.name, []))
                                                 or "none (exercised by unit tests only)"),
              ""]
    return "\n".join(L).rstrip() + "\n"


def wp2_definitions(registry_path: Path) -> Dict[str, str]:
    reg = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    out = {k: v["definition"] for k, v in reg["vocabulary"].items()}
    for amend in reg.get("vocabulary_amendments", []):
        out[amend["code"]] = amend["definition"]
    return out
