"""The structured refusal shared by declaration validation and template matching.

A refusal says what was declared, which requirement it failed, why Stratum does
not support that, and (when one exists) what different declaration or design
would be needed. It never contains a statistical conclusion.

These messages are diagnostic text written for WP1. The plain-language
explanation for each refusal category that the WP4 report uses verbatim lives in
resources/explanations.yaml (D-075), not here.
"""
from dataclasses import dataclass
from typing import Optional

# Every category a refusal may carry. Tests assert against these strings.
CATEGORIES = (
    "yaml_syntax",            # the file is not parseable YAML, or has duplicate keys
    "schema",                 # missing, unknown, or wrongly typed field
    "inconsistent_declaration",  # a name refers to something not declared, or two parts contradict
    "unknown_template",       # claimed_template is not exactly T1, T2 or T3
    "hierarchy",              # unit hierarchy shape outside the claimed template
    "treatment_structure",    # wrong number or kind of treatments for the template
    "application_level",      # a treatment is applied at a level the template does not support
    "assignment",             # an observed (inherent) property declared as an applied treatment
    "replication",            # too few units at a level for the template's inference
    "balance",                # declared counts do not form the balanced template structure
    "blocking",               # nuisance blocking outside the one supported T2 form
    "split_plot",             # split-plot roles missing, malformed, or declared outside T3
    "exchangeability",        # subsampling semantics contradict the template
    "comparison",             # intended comparisons do not fit the template
)


@dataclass(frozen=True)
class Refusal:
    category: str
    declared: str          # what the declaration says, quoted back
    requirement: str       # the requirement that failed
    reason: str            # why Stratum does not support it
    remedy: Optional[str] = None   # what would make it analyzable, when known
    condition: Optional[str] = None  # template condition id, e.g. "T2.replicated"
    path: Optional[str] = None       # location in the YAML, e.g. "hierarchy[1].nested_in"

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError("unknown refusal category: %r" % self.category)

    def explain(self) -> str:
        head = "[%s]" % self.category
        if self.condition:
            head += " %s" % self.condition
        if self.path:
            head += " at %s" % self.path
        lines = [
            head,
            "  Declared:    " + self.declared,
            "  Requirement: " + self.requirement,
            "  Why:         " + self.reason,
        ]
        if self.remedy:
            lines.append("  To proceed:  " + self.remedy)
        return "\n".join(lines)
