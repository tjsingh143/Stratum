# Design declarations (WP1)

A declaration is a YAML file stating how an experiment was designed: what was
measured, how units nest, what was applied to which unit, and which supported
template the design is claimed to be. Stratum then checks that claim against the
template's structural conditions (`stratum/templates.py`). Anything that does not fit
exactly is refused with a reason. Nothing is reinterpreted as a different template.

Matching uses the declaration only. Whether a dataset actually has the declared
columns, counts and nesting is checked by the evidence stage implemented in WP2. **A matched declaration means
"the declared design is a supported structure", not "the data can be analyzed".**

```sh
.venv/bin/python -m unittest discover -s tests      # WP1 tests
```

```python
from pathlib import Path
from stratum.templates import evaluate
print(evaluate(Path("declarations/examples/t3_sasmixed_semiconductor.yaml")).explain())
```

## Schema (version 1)

Every field below is required unless marked optional. Unknown fields and duplicate
keys are refused.

```yaml
stratum_declaration: 1            # schema version
claimed_template: T1 | T2 | T3    # exactly as written; anything else is refused
description: <text>               # optional

response:
  column: <data column>
  units: <text> | null            # null = the source does not state units

hierarchy:                        # ordered, largest unit first; one nesting chain
  - name: <level name>            # top level
    id_column: <data column>      # labels unique across the whole dataset
    count: <whole number>         # total number of top-level units
  - name: <level name>            # each further level
    id_column: <data column>
    nested_in: <name of the level directly above>
    count_per_parent: <whole number>
    id_scope: parent | global     # optional, default parent (labels repeat across parents)
    exchangeable: true | false    # optional, default false (see below)

treatments:                       # [] declares "no treatment" (T1)
  - name: <factor name>
    column: <data column>
    levels: [<label>, ...]        # text or whole numbers; quote yes/no/1.0
    applied_to: <level name>      # the experimental unit of this treatment
    replicates_per_level: <whole number>   # applied_to units receiving each level, in total
    assignment:
      method: randomized | systematic | inherent | not_stated
      description: <text>         # optional

nuisance_factors:                 # [] declares "none recorded"
  - name: <factor name>
    column: <data column>
    recorded_at: <level name>     # level at which the factor is constant
    role: recorded | block
    levels: [<label>, ...]        # optional for recorded; required for block
    crossed_with: <treatment>     # block only

comparisons:                      # [] for T1
  - id: <unique id>
    kind: overall | pairwise | interaction
    factors: [<treatment>]        # two treatments for interaction
    levels: [<first>, <second>]   # pairwise only; estimates first - second
    description: <text>           # optional

split_plot:                       # T3 only
  whole_plot_factor: <treatment>
  subplot_factor: <treatment>
```

### Meaning of the less obvious fields

- **`exchangeable`** (D-022, D-037). `true` declares that the units at this level are
  interchangeable random subsamples with no fixed positional meaning. `false` declares
  fixed or meaningful positions. If omitted, the level is treated as **not established
  as exchangeable** (`false`), and the parsed declaration records that the default was
  applied. Exchangeability is never inferred from the data. For complete balanced
  data it does not change T1 or T2 matching. It decides the missing-site policy in WP2
  (D-016, D-021, D-022, D-028). A T3 subplot level cannot be exchangeable.
- **`id_scope`** (D-036). `parent`: a label identifies a unit only within its parent
  (Oxide wafers 1–3 repeat in every lot). `global`: labels are unique across parents.
- **`assignment.method`** (D-039). `inherent` means the levels are properties the units
  already had (a lot's source, a position on a wafer), not something applied. It is
  refused for the T2 treatment and the T3 whole-plot factor, and allowed for the T3
  subplot factor. `not_stated` is used when the source does not say how levels were
  assigned. Stratum does not guess.
- **Nuisance `role`**. `recorded` factors are listed so that WP2 can check them for
  confounding. They are not part of any model. `block` is the one balanced block
  crossed with a T2 treatment (brief Section 5.2).

## Template conditions

The exact conditions are the `T1_CONDITIONS`, `T2_CONDITIONS` and `T3_CONDITIONS`
tuples in `stratum/templates.py`. The reasoning behind each is in DECISIONS.md, D-038.

## Examples

| File | Template | Anchor |
|---|---|---|
| `examples/t1_nist_furnace.yaml` | T1 | NIST furnace, 21 × 4 × 2 |
| `examples/t1_memss_oxide.yaml` | T1 | MEMSS Oxide, 8 × 3 × 3, Source recorded (D-014) |
| `examples/t1_nist_lithography.yaml` | T1 | NIST lithography, optional reproduction only (D-015) |
| `examples/t2_illustrative_synthetic.yaml` | T2 | **synthetic illustration**; no dataset exists for it |
| `examples/t3_sasmixed_semiconductor.yaml` | T3 | SASmixed Semiconductor, 4 × 3 × 4 |

The reference examples' columns and counts are tested against
`reference/r_outputs/structure.json` (`tests/test_examples.py`). Where a source does
not state something (units, how etch time was assigned, whether sites are
interchangeable), the example says so rather than filling it in.
