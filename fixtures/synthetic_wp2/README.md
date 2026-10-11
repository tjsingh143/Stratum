# WP2 fixture suite: SYNTHETIC structural/statistical fixtures

**Everything in this directory is synthetic.** Each fixture is a small design built
from fixed, exactly representable patterns, to exercise one or more evidence checks.
The fixtures are not physical data, not fab data, and not semiconductor simulations.
They demonstrate software behavior only. No public dataset records routes, chambers
and treatment assignments together, so every check involving confounding or aliasing
is validated on synthetic fixtures only (brief Section 3.3).

| File | What it is |
|---|---|
| `<ID>/declaration_synthetic.yaml` | the WP1 declaration of the fixture |
| `<ID>/data_synthetic.csv` | its data table |
| `generate.py` | writes every fixture deterministically; `--check` verifies the files |
| `expectations.json` | the **preregistration registry**: one expected decision, code set, triggering conditions and rationale per fixture |
| `validate_registry.py` | checks the registry is complete and well formed; it does not judge statistical correctness |

## Preregistration (DECISIONS.md D-042, D-050)

The fixture expectations were preregistered before the evidence-check implementation
was run against them.

- `expectations.json` was written after the frozen rules D-042 to D-050 and before any
  evidence-check code existed. It was committed as the Stage-A freeze point.
- An expectation is never edited to match an implementation's output. A post-run
  change is appended to `corrections` with the previous expectation, the observed
  result, the reason, what was judged wrong, and a decision-record entry.
- After the freeze one rule was clarified (D-053, unit-unique nuisance factors). It
  changed ALIAS-05; its version-2 expectation is an appended `specification_clarification`
  correction, and `comparison.md` reports version-1 and current matches separately.
- A fixture matches only when the actual decision **and** the exact set of finding
  codes equal the preregistered ones (D-048).

```sh
.venv/bin/python fixtures/synthetic_wp2/generate.py --check
.venv/bin/python fixtures/synthetic_wp2/validate_registry.py
```

## Fixture groups

| Prefix | Checks |
|---|---|
| DECL, INT | WP1 refusal path; columns, labels, response values |
| HIER | unit identity and ownership |
| CONS | declaration-data consistency |
| REP | replication at the treatment application level |
| BAL | balance and missing units, from the data |
| MISS | T1/T2/T3 missing-data policy and exchangeability |
| CONF | confounding by exact estimability; partial-confounding metrics |
| ALIAS | grouping-partition aliasing |
| DIAG | Brown-Forsythe, SD ratio, studentized residuals, unavailable diagnostics |
| T3 | split-plot evidence |
| BLK | T2 with a declared block |
