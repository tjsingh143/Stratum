"""Stratum: design declaration, evidence checks, and narrow analysis of three
balanced wafer-level templates (PROJECT_BRIEF.md Sections 4 and 5).

WP1, the declaration layer:
  - stratum.declaration: YAML schema, parsing and structural validation;
  - stratum.templates:   explicit T1/T2/T3 matching and structured refusals.

WP2, the evidence checks (no estimation; that is WP3):
  - stratum.data:        CSV reading, missing-response tokens, exact decimal values;
  - stratum.exact:       exact rational rank, estimability and quadratic forms;
  - stratum.stats:       F distribution and the frozen diagnostics (D-044);
  - stratum.evidence:    check_evidence(declaration, data) -> ANALYZE / WARN / REFUSE.

WP3, the analysis (D-059 to D-068):
  - stratum.dist:        chi-square, t and F quantiles (standard library only);
  - stratum.analysis:    analyze(declaration, data) -> ANOVA, components, estimates.

WP4, explanation, allocation and reassignment (D-074 to D-081):
  - stratum.allocation:  the allocation analysis and its plausible values;
  - stratum.reassign:    the reassignment suggestion for confounded T2 designs;
  - stratum.explain:     the refusal/warning category registry and its plain-language texts;
  - stratum.results:     results.json, with input hashes and the code version;
  - stratum.report:      the Markdown report, rendered from results.json alone;
  - stratum.cli:         `python -m stratum ...`.
"""
__version__ = "1.0.0"
