# Data and references

Stratum uses published textbook and NIST/SEMATECH sources plus labeled synthetic fixtures and simulations. No proprietary or private fabrication dataset is present in this repository, and none of the work is physical fabrication testing.

## Published datasets

| Source | Verified structure | Role and interpretation boundary |
|---|---|---|
| NIST/SEMATECH furnace, `FURNACE.DAT` | 168 rows: 21 runs × 4 zones × 2 wafers | T1 reproduction of the handbook nested ANOVA. Zone positions repeat physically; the nested convention follows the reference. The file contains one response per wafer, despite source text discussing two sites. It does not state whether that response is an average. |
| MEMSS `Oxide` | 72 rows: 8 lots × 3 wafers × 3 sites | T1 without Source. Source is constant within lot, with four lots per level. A Source-fixed fit is a separate sensitivity comparison, not the canonical T1 model. Thickness units are not stated by the package. |
| SASmixed `Semiconductor` | 48 rows: 4 etch times × 3 wafers × 4 positions | T3; etch time has 3/8 test df, position 3/24, interaction 9/24. Positions are inherent locations. Resistance units and treatment randomization are not established by the package documentation. |
| NIST/SEMATECH lithography, `LITHOGRA.DAT` | 450 rows: 30 cassettes × 3 wafers × 5 sites | Optional T1 table reproduction, using raw width rather than the separate cleaned column. Fixed positions limit interpretation of a random site component. |

Published-reference results and persistent diagnostic warnings appear in the [WP3 reproduction](../validation/WP3_REPRODUCTION.md) and the [reference reports](../reports/INDEX.md). Source-level targets distinguish published text, package reproductions, retained R calculations and unavailable book values. O19, O20 and S06 remain unavailable; package transcripts are not represented as verified book pages.

## Fetching, checksums and redistribution

The [reference source manifest](../reference/manifest.json) retains source URLs, verified fallback URLs, normalization conventions, SHA-256 values and derived CSV hashes. `reference/fetch.py --offline` verifies cached sources. HTML sources are normalized to visible text according to the stored convention. `reference/replay.py` uses the pinned sources to regenerate CSVs and compare fresh R outputs to the retained files. Hash mismatches fail verification rather than updating the expected checksum.

Datasets are fetched by the reference tooling rather than redistributed in this repository. NIST's government-work statement does not settle the terms of externally contributed case-study data. MEMSS and SASmixed packages declare GPL (≥2), while separate terms for their book-origin data are not established. This uncertainty is retained; no blanket public-domain or dataset-redistribution claim is made. No repository-wide reuse license is granted or inferred. Provenance, citation and licensing details for each source are in [reference/README.md](../reference/README.md).

## Synthetic material

The 65 deterministic fixtures cover structural and diagnostic decisions. The three demonstration scenarios use explicitly synthetic data in arbitrary units. Their YAML and CSV inputs are in `scenarios/`, generated deterministically by `scenarios/generate.py`. The synthetic Monte Carlo study uses declared statistical models and frozen departures; its 418,000 attempts are not measurements from a physical process.

Chamber, route, confounding and aliasing behavior is checked with synthetic constructions; the published nested and split-plot references do not independently establish those checks. Synthetic results establish software and statistical behavior, not physical process realism, and the simulation's coverage estimates apply to the tested conditions, not to arbitrary manufacturing data.

## Citations and conventions

Sources as recorded by the project:

- NIST/SEMATECH, *e-Handbook of Statistical Methods*, DOI 10.18434/M32189. Furnace §§3.5.1.1/3.5.1.4; lithography §§6.6.1.1/6.6.1.3; split-plot §5.5 in the process-improvement chapter. Exact source URLs and checksums are in the manifest.
- Pinheiro, J. C. and Bates, D. M. (2000), *Mixed-Effects Models in S and S-PLUS*, Appendix A.20 and Oxide analyses. DOI 10.1007/b98882.
- Littell, R. C., Milliken, G. A., Stroup, W. W. and Wolfinger, R. D. (1996), *SAS System for Mixed Models*. Semiconductor Data Set 2.2(b); Oxide/Semi2 Data Set 4.4.
- MEMSS 0.9-4, DOI 10.32614/CRAN.package.MEMSS; SASmixed 1.0-5, DOI 10.32614/CRAN.package.SASmixed. Package-distributed data and example transcripts retain their source tier.
- Hurlbert (1984), pseudoreplication and experimental units, DOI 10.2307/1942661.
- Satterthwaite (1946), approximate variance-component inference, DOI 10.2307/3002019.
- Harville (1977), restricted-likelihood foundations, DOI 10.2307/2286796.
- Brown and Forsythe (1974), median-centered spread testing, DOI 10.1080/01621459.1974.10482955.
- Weerahandi (1993), generalized-pivotal inference, DOI 10.1080/01621459.1993.10476355. Stratum's pooling, allocation-ranking threshold and ranges remain project conventions.
- Bates et al. (2015), lme4, DOI 10.18637/jss.v067.i01; Kuznetsova et al. (2017), lmerTest, DOI 10.18637/jss.v082.i13. [Retained package versions](../reference/r_outputs/session.json).
