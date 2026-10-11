# Validation material

| File | Contents |
|---|---|
| `wp3_reproduce.py` | Runs the four published-reference analyses and compares them with the frozen comparison map. Writes `wp3_reproduction.json` and `WP3_REPRODUCTION.md`; `--check` verifies both. Needs the reference data (see [reference/README.md](../reference/README.md)). |
| `build_wp3_map.py` | Builds the frozen comparison map from `reference/reference_numbers.csv`; `--check` verifies it |
| `wp3_comparison_map.json` | Tolerance class and comparison rule for every reference number and extra check |
| `wp3_reproduction.json`, [`WP3_REPRODUCTION.md`](WP3_REPRODUCTION.md) | Generated reproduction results: 198/199 frozen comparisons, 40/40 supplementary checks and the one retained disagreement |
| `policy_checks.py` | Independent, deterministic checks of the statistical claims behind the missing-site policy (standard library only) |
| `wp6_generate.py` | The synthetic data generator used by the validation study: a declaration and responses for a cell definition |
| `evidence/` | Selected, verified extracts of the validation study's results (below) |

## Evidence extracts

Each extract has a `source` block that gives the path and SHA-256 of the v1.0.0 file it was
taken from, and describes the selection. Values are copied unchanged. The only computed
values are `additional_accounting` in `validation_summary.json`, which sums named per-cell
counts as its `source.selection` states. The source files themselves (the full per-cell
summary, the investigation and history records and the release-gate record) and the attempt
ledgers behind them are not part of this repository, so these results are reported as
retained evidence rather than regenerated here.

| File | What to inspect |
|---|---|
| [`validation_summary.json`](evidence/validation_summary.json) | Totals, all 12 nominal families with their formal alerts and diagnostic flags, all 34 condition aggregates, focused groups, Monte Carlo SEs |
| [`t1_component_cells.json`](evidence/t1_component_cells.json) | The 12 conforming T1 cells: availability, negative estimates, bias, boundary counts and coverage |
| [`formal_alerts_and_corrections.json`](evidence/formal_alerts_and_corrections.json) | Each of the 21 formal alerts with its frozen band and observed count, and the two implementation corrections |
| [`interval_investigation.json`](evidence/interval_investigation.json) | 24 deterministic coverage calculations for the frozen interval method |
| [`validation_history.json`](evidence/validation_history.json) | Reconciliation of the corrected study with its first execution |
| [`original_release_gate.json`](evidence/original_release_gate.json) | Completion status and counts of the original release gate |

All validation data are SYNTHETIC: they show software behavior, not process realism.
Percentages in the documents are rounded for reading; the JSON keeps full precision, counts
and denominators. [VALIDATION.md](../VALIDATION.md) interprets these results, including
every adverse finding.
