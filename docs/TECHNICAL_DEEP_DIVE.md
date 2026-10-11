# Technical deep dive

## Declarations are contracts

`load_declaration()` uses a subclass of `yaml.SafeLoader` that rejects duplicate keys. `parse_declaration()` validates allowed and required fields, counts, labels, nesting, factor references and column collisions before creating immutable declaration objects. `templates.match()` evaluates the claimed template's condition set; it never searches for another template that happens to fit. A skipped prerequisite without a failed condition raises an internal error rather than returning a match.

`data.read_table()` checks unique nonempty headers and exact row widths. `parse_response()` accepts finite decimal syntax into `Fraction`. Empty/NA responses remain explicit missingness. Hierarchical IDs use parent-qualified tuples, so repeated wafer labels can be valid inside different lots while a globally scoped ID cannot silently move between parents.

`evidence.check_evidence()` records stage outcomes and findings. Early integrity failures stop dependent work. Later structural findings accumulate when the hierarchy remains meaningful. `analysis.analyze()` produces an unanalyzed result on refusal, then dispatches only a surviving T1/T2/T3 declaration.

## Exact geometry and error decomposition

`exact.rref()` performs rational elimination. `Design` caches geometry by design rows and column count, independently of response values. It selects independent columns, solves on a principal Gram submatrix and verifies a contrast against the full normal matrix. `Design.quad()` returns `None` for a non-estimable contrast. This same geometry supports projections, leverages and nuisance-adjusted precision ratios.

`nested_strata()` builds weighted squared deviations of hierarchical means. `_t2_unit_level()` separates treatment, optional block and unit residual, checking that sums of squares add exactly. `_t3()` separately decomposes the whole-plot and subplot strata and attaches the appropriate denominator to each term. The analysis checks decomposition identities directly rather than matching a known dataset's constants.

`component_groups()` merges strata with zero separating df. `variance_components()` preserves signed moments, truncated displays, interval availability and fit events; `reml_isotonic()` pools adjacent mean-square violations. An exact zero has an explicit unavailable-inference path. The numerical distribution routines operate after rational structural calculations, including log-space chi-square endpoints for tiny effective df.

## Planning retains identification limits

`allocation.model_from_strata()` represents component groups and their estimability. `classify()` / `bounds()` distinguish identified values, bounds over an unknown component split, lower bounds and wholly unestimable quantities. `plausible_components()` uses a local seeded random stream and returns immutable cached draws. Randomness here quantifies a planning convention; it is separate from simulation validation and has no validated coverage claim.

`reassign._one()` creates new planned units, rounds replication up to a multiple of nuisance levels, and randomizes a balanced layout within each level. `_verify_layout()` checks exact contrast geometry; `_precision()` uses within-cell unit variation. A proposed layout is not a repaired historical experiment or a predicted treatment effect.

## A result document controls the report

`results.build()` assembles schema `stratum-results/1`. It keeps decision, comparisons, findings, assumptions, diagnostics, analysis, allocation, reassignment and planning distinct. Refusal records include the failed condition, declared value, requirement, reason and possible remedy. CLI scientific refusal returns exit 0 with a result document; malformed input/operational errors return 1 and usage errors 2.

`report.Src` reads values by JSON path and can trace rendered numbers back to those paths. `report.render()` takes that document alone. This makes report re-rendering deterministic and testable without repeating the analysis. Strict JSON serialization uses `allow_nan=False`; numerical endpoint overflow is represented explicitly instead of emitting invalid JSON numbers.

`results.source_hash()` hashes sorted relative source paths and their SHA-256 values. Inputs are hashed as bytes. Committed reproducible outputs omit changing runtime metadata; ordinary CLI runs also record interpreter/dependency versions and Git state. These identify the calculation's inputs and source, without proving the experimental assumptions.

## Evidence around the engine

`reference/replay.py` starts from pinned source downloads, exports fresh CSVs in isolated R, and requires the complete generated R output set to match stored bytes. It does not seed computations with the existing derived CSVs. `validation/wp3_reproduce.py` compares the current engine to source-specific reference targets and frozen tolerances.

In the original release, the validation tooling read the compressed attempt ledgers, verified ledger hashes, recomputed cell metrics, checked equality with retained cell summaries and aggregated all outcomes, keeping unavailable intervals in denominators. It also regenerated the first seeded input in each cell and compared complete analysis fingerprints against retained records, a bounded regression check distinct from replaying all attempts. Those ledgers and scripts are not part of this repository; their results are summarized in [VALIDATION.md](../VALIDATION.md). The synthetic data generator, `validation/wp6_generate.py`, is included.

The [code samples](CODE_SAMPLES.md) are exact excerpts from the [source tree](../stratum/). [Reproducibility](../REPRODUCIBILITY.md) describes which checks can be repeated from this repository.
