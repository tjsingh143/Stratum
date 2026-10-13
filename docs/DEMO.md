# Three synthetic cases in a few minutes

Run these from the repository root. Each scenario's inputs are `declaration_synthetic.yaml` and `data_synthetic.csv` in its directory under `scenarios/`. The scenario commands rewrite the stored demonstration outputs; regeneration is deterministic, so an unmodified checkout regenerates them unchanged.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m stratum --version
```

All three cases are synthetic, in arbitrary units, and show software behavior rather than physical testing. The values quoted below are from the stored scenario results; the scenario checker (142 assertions) passed when run on this repository before publication.

## 1. Chamber confounding: a difference is not an identified effect

```sh
.venv/bin/python scenarios/run.py S1
```

Open `scenarios/S1-chamber-confounding/output/report.md`. There are three runs per recipe, three wafers per run and five sites per wafer. Raw means are 100 and 96: a descriptive modified-minus-standard difference of −4. All standard runs use chamber A; all modified runs use chamber B. The treatment contrast cannot be separated from chamber, so the decision is **REFUSE**, with no supported treatment estimate or interval.

Inspect the reassignment section. It proposes eight **new** runs: four per recipe, two per recipe×chamber cell, randomized within chamber. The revised blocked design has five error df. Its conditional planning SE is 0.7071067811865476, with range [0.4236511055153344, 2.031910674973518] and expected interval half-width 1.8176758475733998. These use within-cell variation and additive/comparable-future-variation assumptions. They do not estimate the refused recipe effect or repair existing runs. [Results](../scenarios/S1-chamber-confounding/output/results.json); [assertions and descriptive means](../scenarios/S1-chamber-confounding/output/comparison.json); [write-up](../scenarios/S1-chamber-confounding/WRITEUP.md).

## 2. Many measurements, no run replication

```sh
.venv/bin/python scenarios/run.py S2
```

Open `scenarios/S2-no-run-replication/output/report.md`. The two runs each contain six wafers × nine sites: 108 measurements, but only one run per treatment. Raw means differ by +3, without an inferential treatment conclusion. The decision is **REFUSE** because the run-level error has zero df.

Inspect allocation. The current SE is only bounded below by 0.21602468994692867; there is no estimated upper bound or total SE. The run-variance floor is **not estimable**. Adding wafers or sites cannot create independent runs. An additional run per level would provide replication, but its future precision cannot be fully quantified from this dataset. [Results](../scenarios/S2-no-run-replication/output/results.json); [assertions](../scenarios/S2-no-run-replication/output/comparison.json); [write-up](../scenarios/S2-no-run-replication/WRITEUP.md).

## 3. A valid split-plot: the denominator changes the conclusion

```sh
.venv/bin/python scenarios/run.py S3
```

Open `scenarios/S3-split-plot/output/report.md`. Four etch settings × three wafers × four positions yield 48 readings. The declared structure is analyzed with two error strata.

| Test | Correct F | Correct df | Correct p |
|---|---:|---:|---:|
| Whole-plot A | 1.8 | 3, 8 | 0.22504495350464732 |
| Subplot B | 8.0 | 3, 24 | 0.0007215102454105524 |
| A×B | 0.3333333333333333 | 9, 24 | 0.9548765456346505 |

The naive pooled-error A test reports F=6.744730679156909 on 3,32 df and p=0.0011821138348475674. Pooling the errors changes the apparent evidence for A. The position factor is inherent rather than randomized, and the report retains that interpretation caveat. [Results](../scenarios/S3-split-plot/output/results.json); [assertions](../scenarios/S3-split-plot/output/comparison.json); [write-up](../scenarios/S3-split-plot/WRITEUP.md).

## Check the stored demonstrations

```sh
python3 scenarios/generate.py --check
.venv/bin/python scenarios/run.py --all --check
```

The current `--check` mode verifies numerical scenario agreement with a `1e-12`
relative allowance for finite JSON floats, no absolute allowance, and exact
structure, counts, decisions, labels and provenance. Each report must render from
its own results. Add `--strict-bytes` to `--check` to require literal replay; the
recorded cross-platform S3 byte difference remains visible in that mode. All 142
preregistered statistical assertions run in either mode.


For an ordinary direct CLI call on the same synthetic S3 inputs:

```sh
.venv/bin/python -m stratum analyze scenarios/S3-split-plot/declaration_synthetic.yaml \
    scenarios/S3-split-plot/data_synthetic.csv --synthetic --out output/S3
.venv/bin/python -m stratum report output/S3/results.json \
    --out output/S3/report-rerendered.md
```

Both commands exit 0. When run on this repository before publication, the direct call matched the stored S3 result in every section except the data label and runtime provenance, and the re-rendered report was byte-identical to the one `analyze` wrote.
