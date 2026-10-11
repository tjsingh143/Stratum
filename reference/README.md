# Reference data and reference numbers (WP0)

This directory holds the published evidence Stratum is checked against: the published
datasets (fetched, never vendored), the published reference numbers, and the R
reference analyses run once in a pinned environment. All data are published
textbook and NIST/SEMATECH datasets. Nothing here is synthetic, and nothing here
comes from a fab.

## Regenerate and verify

```sh
python3 reference/replay.py         # fetch/verify, isolated pinned R replay, compare frozen outputs
python3 reference/verify.py         # all checks; prints documented differences and unobtained values
```

The original `r/run_reference.sh` writes R outputs directly; release users should use
`replay.py`, which preserves the stored comparison targets and rebuilds only the input
CSV cache. Repository-level checks: `python3 run_checks.py` from the repository root.

Requirements: Python 3.9+ (standard library only), Docker, and network access for
the first fetch. Files land in `reference/_fetched/`, which is git-ignored.

| File | What it is |
|---|---|
| `manifest.json` | pinned URLs (with verified fallbacks) and SHA-256 of every source and derived CSV |
| `fetch.py` | downloads and verifies the sources (DECISIONS.md D-003, D-004) |
| `r/Dockerfile`, `r/run_reference.sh` | pinned R 4.6.1 environment and runner (D-002) |
| `r/00_export.R` … `r/99_session.R` | export to CSV, the four reference analyses, session record |
| `r_outputs/*.Rout` | echoed transcripts (every command and its output) |
| `r_outputs/*.json` | the same results at full precision; `session.json` holds versions |
| `reference_numbers.csv` | every reference number, with its tier, exact source, and locator |
| `verify.py` | checks all of the above |

## Sources, citations, licenses, checksums

Retrieved 2026-09-30. SHA-256 is of the saved file. For HTML pages it is of the
page's visible text (D-004).

| Source | Citation | Redistribution status | Handling | SHA-256 |
|---|---|---|---|---|
| `FURNACE.DAT` | NIST/SEMATECH e-Handbook of Statistical Methods, §3.5.1 Furnace case study, https://www.itl.nist.gov/div898/handbook/ (DOI 10.18434/M32189), retrieved 2026-09-30. File header: "Data provided by Barry Hembre [sic] of AMD … Contact--Barry Hembree, AMD". | NIST's §105 statement covers works of NIST employees; these data were contributed by an outside company, so their status is **unclear** (D-003) | fetched; Wayback fallback verified | `e2725a7b153956077258a1af3c192f3bddf9322cac8ff10be6b1a6e17efe34cd` |
| `LITHOGRA.DAT` | same handbook, §6.6.1 Lithography case study. File header: "This file was recieved [sic] from Jack Prins of Sematech." | **unclear**, same reason | fetched; Wayback fallback verified | `777cd68453b8ff18b89d02f312259cdfdbd7980215b75687b156d248d7d0f1fc` |
| Handbook pages 3.5.1.1, 3.5.1.4, 6.6.1.1, 6.6.1.3; citation page | same handbook; citation form and DOI taken from its front page | handbook text by NIST/SEMATECH; not redistributed here | fetched as text | `2e9779c7…`, `e8998e5e…`, `7d12c570…`, `aeba9712…`, `2db05db6…` (full values in `manifest.json`) |
| `ppc511.r`, `pmc613.r` | NIST's published R code and printed output for the two case studies | as above | fetched | `9b8590c7…`, `60fe4a66…` |
| MEMSS 0.9-4 (`Oxide`) | Bates D, Maechler M, Bolker B, Walker S (2026). *MEMSS: Data Sets from Mixed-Effects Models in S*. R package version 0.9-4. doi:10.32614/CRAN.package.MEMSS. Data from Pinheiro JC, Bates DM (2000), *Mixed-Effects Models in S and S-PLUS*, Springer, Appendix A.20 (doi:10.1007/b98882), and Littell et al. (1996). | package GPL (≥ 2); terms for the book-origin data not stated separately: **unclear** | fetched from CRAN (Archive fallback) | `7b093f3c47e07bd8c99dbb9942cc29e5f078d4de02c55257f7fb3450921a1d65` |
| SASmixed 1.0-5 (`Semiconductor`, `Semi2`, transcripts) | Littell R, Milliken G, Stroup W, Wolfinger R, Bates D, Maechler M, Bolker B, Walker S (2026). *SASmixed: Data Sets from "SAS System for Mixed Models"*. R package version 1.0-5. doi:10.32614/CRAN.package.SASmixed. Data from Littell RC, Milliken GA, Stroup WW, Wolfinger RD (1996), *SAS System for Mixed Models*, SAS Institute: Data Set 2.2(b) and Data Set 4.4. | package GPL (≥ 2); book-origin data: **unclear** | fetched from CRAN (Archive fallback) | `ba71d2ef7f14b4cf6b6d499436622e66ebb76a2b98ea4842d5b33959fdffdb78` |
| rdrr.io rendering of the SASmixed `Semiconductor` help page | third-party rendering of the package example (lmer), page built 2019-05-01; https://rdrr.io/cran/SASmixed/man/Semiconductor.html, retrieved 2026-10-03 | third-party page; not redistributed | fetched as text; cross-check only (D-020) | `a3762b81…` |
| nlme 3.1-171 (saved re-run of the Pinheiro & Bates ch. 4 code) | Pinheiro J, Bates D, R Core Team (2026). *nlme: Linear and Nonlinear Mixed Effects Models*. R package version 3.1-171. | GPL (≥ 2) | fetched from CRAN | `481dc8277dd0e0f2717ffb36edfb08141621470de173894fb1153464383ba0d3` |

Software used for the R reference outputs, as cited by `citation()`:
- lme4: Bates D, Mächler M, Bolker B, Walker S (2015), *Journal of Statistical Software* 67(1), 1–48, doi:10.18637/jss.v067.i01.
- lmerTest: Kuznetsova A, Brockhoff PB, Christensen RHB (2017), *Journal of Statistical Software* 82(13), 1–26, doi:10.18637/jss.v082.i13.
- Versions are listed in `r_outputs/session.json`.

## Data dictionaries

Generated from the files (`r_outputs/structure.json`), not from the project specification. All four
datasets have no missing values and are fully balanced.

### NIST furnace (`FURNACE.DAT`, exported as `derived/furnace.csv`)
| Column | Meaning | Units | Levels / range |
|---|---|---|---|
| `run` | furnace run | — | 21 levels (1–21) |
| `zone` | furnace location (boat position in the tube) | — | 4 levels (1–4); the same physical positions in every run |
| `wafer` | wafer within zone | — | 2 levels (1–2), labels repeat in every run × zone |
| `thickness` | oxide film thickness | Å | 487–634, integers |

168 rows = 21 × 4 × 2, one reading per wafer. CRLF line endings, 25-line header.

### NIST lithography (`LITHOGRA.DAT`, exported as `derived/lithography.csv`)
| Column | Meaning | Units | Levels / range |
|---|---|---|---|
| `cassette` | cassette of wafers | — | 30 levels |
| `wafer` | wafer within cassette | — | 3 levels, labels repeat in every cassette |
| `site` | site on the wafer | — | 1 Top, 2 Left, 3 Center, 4 Right, 5 Bottom (fixed positions) |
| `width_raw` | line width (the handbook analyzes this one) | µm | — |
| `run_seq` | measurement sequence | — | 1–450, equal to row order |
| `width_cleaned` | "cleaned up" line width | µm | raw minus 0.002 to 0.9 |

450 rows = 30 × 3 × 5.

### MEMSS `Oxide` (exported as `derived/oxide.csv`)
| Column | Meaning | Units | Levels / range |
|---|---|---|---|
| `Source` | two-level source classification | — | 1, 2; **constant within lot**: lots 1–4 = 1, lots 5–8 = 2 |
| `Lot` | lot | — | 8 levels |
| `Wafer` | wafer within lot | — | 1–3, labels repeat in every lot (nest as Lot/Wafer) |
| `Site` | site on the wafer | — | 1–3 |
| `Thickness` | oxide layer thickness | not stated in the package documentation | 1980–2036 |

72 rows = 8 × 3 × 3. Identical to SASmixed `Semi2` and nlme `Oxide`.

### SASmixed `Semiconductor` (exported as `derived/semiconductor.csv`)
| Column | Meaning | Units | Levels / range |
|---|---|---|---|
| `resistance` | wafer resistance | not stated in the package documentation | 4.60–6.97 |
| `ET` | etch time (whole-plot factor, applied to wafers) | — | 4 levels (1–4) |
| `Wafer` | wafer within etch time | — | 1–3, labels repeat across ET |
| `position` | position on the wafer (subplot factor) | — | 4 levels |
| `Grp` | wafer identity, "ET/Wafer" | — | 12 levels (verified equal to `ET/Wafer`) |

48 rows = 4 ET × 3 wafers × 4 positions, one reading per position.

## Differences between the project specification (Section 3.1) and the files

Every count and level structure in the specification's Section 3.1 was confirmed against the files
(`verify.py`, "brief claim" checks). The files add or contradict the following:

1. **NIST data licensing.** "NIST/SEMATECH handbook data are U.S. government works" is not established. Both files name industry contributors (D-003).
2. **Oxide Source** is a lot-level factor (4 lots per level), not a factor that varies within lots (D-006).
3. **Oxide is also Littell Data Set 4.4**, p. 155, identical to SASmixed `Semi2`. The specification cites only Pinheiro & Bates and "Littell et al. 1996" in general.
4. **Furnace zone and lithography site** are fixed physical positions repeated across groups. The handbook analyzes them as nested random effects. For lithography the position effect is large (F = 262 on 4, 356 df), so its "site" component is mostly systematic (D-007).
5. **Furnace.** The text says two sites were measured per wafer; the file has one value per wafer. The specification already notes this. Whether the value is a site average is not stated anywhere.
6. **Lithography** has six columns, including a cleaned width and a sequence number. The specification does not mention them (D-011).
7. **Units.** Neither package documents units for Oxide thickness or Semiconductor resistance.
8. **NIST's own furnace outputs disagree** in the third decimal between the ANOVA page (225.38294) and NIST's R/REML printout (225.381). The lithography page gives the wafer component as both 0.0500 and 0.04997 (D-008).

## Reference numbers

`reference_numbers.csv` holds 136 rows. Each row carries:
- a **tier**, which says where the value comes from: 42 `published`, 28 `package`, 63 `r-run`, 3 `not-obtained`;
- a **role**, which says how it may be used: 74 `canonical`, 12 `sensitivity`, 23 `cross-check`, 20 `optional`, 4 `supplementary`, 3 `not-obtained`.

**Which values are reproduction targets (`canonical`).**
- *Furnace:* NIST's published ANOVA page.
- *Oxide:* the T1 nested fit **without** Source. The Source-fixed fit has role `sensitivity`: it answers a different question, a lot-level comparison on (1, 6) df, and Stratum T1 is not extended to support it (D-014).
- *Semiconductor:* the classical split-plot from this repository's R run, because no package source reproduces Littell's tests (D-013).
- *Lithography:* optional. It reproduces NIST's table only and is never evidence about random site variance (D-015).

**Package-tier values are not book values.** Where book pages were unavailable, the package-distributed reproductions are the v1 reference (decision D-013). They keep tier `package`, and every one is labeled as not verified against the book. The three book values that could not be obtained (O19, O20, S06) stay blank.

`verify.py` enforces all of this. It checks that every published and package value appears verbatim at its stated place in the checksummed source, and that the R outputs reproduce them at the precision each source prints. The three exceptions found are listed as documented differences (D-008).
