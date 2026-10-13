# WP5 demonstration scenarios (SYNTHETIC)

Three end-to-end scenarios (PROJECT_BRIEF.md WP5; DECISIONS.md D-086, D-087). Every input
is synthetic and deliberately constructed by `generate.py`: it shows how Stratum behaves,
not how a real process varies.

| Scenario | Directory | What it shows |
|---|---|---|
| S1 | `S1-chamber-confounding/` | A recipe completely confounded with chamber: refused, with a crossed randomized reassignment and its expected precision |
| S2 | `S2-no-run-replication/` | One run per treatment level: refused, and the allocation analysis shows that only more runs lower the floor |
| S3 | `S3-split-plot/` | A correct split-plot with two error terms, beside the naive single-error analysis |

Each expected outcome was preregistered in `expectations.json` and committed before any
Stratum code ran on the inputs (D-086, freeze commit recorded in D-087).

```sh
.venv/bin/python scenarios/run.py S1             # one scenario (S1, S2 or S3)
.venv/bin/python scenarios/run.py --all --check  # portable verification and every assertion
.venv/bin/python scenarios/run.py --all --check --strict-bytes  # exact byte reproduction
python3 scenarios/generate.py --check            # verify the inputs
```

Each scenario directory holds its inputs, `output/results.json`, `output/report.md`
(rendered from results.json), `output/comparison.json` (every preregistered assertion with
its actual value) and `WRITEUP.md`, whose numbers are filled from those files.

Portable checks allow only finite JSON float differences within `1e-12` relative error,
with no absolute allowance near zero. Object structure, value types, integer counts,
decisions, provenance and write-ups remain exact. The stored report must render exactly
from its stored results, and the fresh report must render exactly from the fresh results;
tiny quantile differences can move a text-plot marker. `--strict-bytes` keeps the stronger
byte comparison available and never rewrites a stored file. Neither mode changes the
preregistered assertions or their tolerances.
