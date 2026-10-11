# Stratum methods

Stratum implements three balanced normal models. Their exact treatment tests require independent random effects, normal errors and common variances at the relevant strata. A declaration identifies the experimental unit; observed replication is counted at that level. Diagnostics can expose departures, but cannot establish these assumptions.

## T1: nested variation without treatment

For `a` top groups, `b` subgroups per group and `n` observations per subgroup:

`y_ijk = μ + A_i + B_j(i) + ε_k(ij)`.

| Stratum | df | Expected mean square |
|---|---:|---|
| A | a−1 | σ²_ε + nσ²_B + bnσ²_A |
| B within A | a(b−1) | σ²_ε + nσ²_B |
| Observation error | ab(n−1) | σ²_ε |

Each sum of squares is the number of observations per unit multiplied by the squared departures of unit means from parent means. Orthogonal strata sum exactly to the total. Subtracting adjacent mean squares gives `(MS_A−MS_B)/(bn)` and `(MS_B−MS_ε)/n`; the lowest component is `MS_ε`. The grand mean's SE is `sqrt(MS_A/(abn))`, with `a−1` interval df. V1 requires exactly three levels and replication at each split.

## T2: treatment assigned to upper-level units

With `t` treatment levels, `r` units per level, `w` wafers per unit and `s` sites per wafer, the unit error mean square has expectation:

`λ_U = σ²_S + sσ²_W + wsσ²_R`.

Treatment is tested by `MS_treatment/MS_U`, with `(t−1, t(r−1))` df. A pairwise difference has `SE = sqrt(2 MS_U/(rws))`. Extra sites reduce the measurement term in an average; they cannot supply the missing error df when `r=1`.

T2 also permits just one subsampling level. Counts of one at a lower split collapse a stratum. The output names the combined component, such as `σ²_R+σ²_W`, instead of reporting an unidentified separation. Treatment inference can remain available with replicated upper units.

For one balanced block with `k` levels, the unit-mean model is intercept + treatment + fixed block. Every treatment×block cell has equal counts, and the error df are `tr−t−k+1`. Treatment is tested against that additive residual. One unit per cell is allowed by the additive assumption; arbitrary treatment×block interaction is not separately fitted. The limited interaction departure in validation does not establish general robustness to interaction. Block differences are descriptive.

## T3: two distinct error strata

For `a` levels of A, `r` whole plots per level and `b` B levels within every plot:

`y_ijk = μ + α_i + G_j(i) + β_k + (αβ)_ik + ε_ijk`.

| Term | Numerator df | Error mean square | Denominator df |
|---|---:|---|---:|
| A | a−1 | Whole plots within A, MS_G | a(r−1) |
| B | b−1 | Subplot error, MS_ε | a(r−1)(b−1) |
| A×B | (a−1)(b−1) | Subplot error, MS_ε | a(r−1)(b−1) |

Within-plot differences cancel the shared whole-plot effect. Thus `Var̂(A difference)=2MS_G/(rb)`, `Var̂(B difference)=2MS_ε/(ar)`, and a two-by-two interaction contrast has variance `4MS_ε/r`. Component estimates are `(MS_G−MS_ε)/b` and `MS_ε`.

The naive comparison uses a single **pooled** error, `(SS_G+SS_ε)/(a(r−1)b)`, for the same fixed A+B+A×B model. It is not a pure subplot-error test. Its output is labeled as an incorrect analysis of the declared split-plot.

## Intervals and exact arithmetic

Effect intervals are two-sided `estimate ± t_(0.975,ν) SE`, per comparison, without multiplicity adjustment. A single balanced error stratum gives exact inference under the model. B level means mix both strata and use approximate Satterthwaite df; B differences use the subplot stratum alone. T3 reports A/B means and requested contrasts, without a separate cell-mean interval table.

Finite decimal inputs become `fractions.Fraction`. Hierarchical means, sums of squares, projection geometry, rank and estimability use rational arithmetic. Distribution functions, roots, quantiles and displayed interval endpoints use floating point. This boundary avoids arbitrary rank tolerances while acknowledging numerical limits in probability calculations.

For a positive component estimate `q = Σ c_k MS_k`, the approximate interval uses:

`ν_eff = q² / Σ[(c_k MS_k)²/ν_k]`

`[ν_eff q / χ²_(0.975,ν_eff), ν_eff q / χ²_(0.025,ν_eff)]`.

A positive multiple of one random-stratum mean square has an exact chi-square interval. A difference of mean squares does not. Nonpositive moments are retained, also displayed truncated at zero, and receive no component interval. Component percentages use truncated moments. Very small effective df can yield endpoint overflow; logarithmic endpoints preserve scoring and the output marks the floating-point limit.

**Measured limitation:** T1 run-component coverage was 18,039/24,000 (75.1625%), ranging from 58.20% to 91.65% across conforming cells. All 12 run-component cells and nine wafer-component cells triggered formal alerts. Approximate upper-component intervals are not reliably calibrated nominal 95% intervals over this grid. Unavailable intervals count as noncoverage. [Validation details](VALIDATION.md).

## REML and degenerate fits

The independent nonnegative component fit minimizes `Σ[ν_k log λ_k + SS_k/λ_k]` subject to descending expected mean squares. A pool-adjacent-violators algorithm joins adjacent violations with `λ = ΣSS/Σν`; triangular inversion recovers components. It is a closed-form balanced REML cross-check, rather than a general optimizer. Ordered mean squares give the moment solution; boundaries can pool strata.

This is another calculation on the same data, not a second experimental sample. Full-covariance tests and retained R outputs check it. The restricted log-likelihood is reported on error contrasts alone and with the `log det(X′X)` term, whose constant depends on how the fixed effects are coded. For Semiconductor, lme4's stored REML criterion differs from Stratum's value by the constant `(N−p) log 2 = 32 log 2`; that comparison stays recorded as failed, while the fitted components and tests agree within tolerance.

A zero fitted stratum variance makes covariance singular, so finite likelihood is unavailable. Zero error variance withholds the affected F/t/p values and inferential intervals while preserving descriptive estimates and fit events. No artificial positive variance is inserted.

## The missing-site exception

Only T2 may lose lowest-level observations explicitly declared exchangeable. Every top and intermediate unit must retain data; replication and block crossing must remain balanced; no observed count may exceed its declaration. Missing responses are empty or `NA`, with no imputation. Fixed-position sites are outside the exception, even if the same positions are absent everywhere.

Available sites are averaged within each wafer, then wafers are weighted equally within each upper unit. The treatment or additive-block analysis operates on those hierarchical means. Unequal counts imply unequal precision, so inference is approximate; response-independent missingness is required for the stated mean interpretation. Balanced component estimation, REML and allocation decomposition are withheld. There is no percentage-loss cutoff.

For nominal count `s` and surviving wafer counts `s_j`, `F_site=(s/w)Σ(1/s_j)`. Its reciprocal is a count-only lower bound on unit-mean precision relative to the balanced design, not an estimate of total precision loss. T1/T3 missing cells and missing higher units are refused under the current declaration.

## Confounding, aliasing and diagnostics

For each comparison and each recorded nuisance separately, Stratum forms effect+nuisance design geometry at the finer relevant level. A contrast `c` is estimable iff `rank(X′X)=rank([X′X | c])`. Non-estimability gives complete-confounding refusal. For estimable contrasts the ratio `c′(X′X)⁻c / c′(X₀′X₀)⁻c` measures variance inflation at a common residual scale. Contingency tables and Cramér's V describe association; V has no refusal threshold. Nonproportional partial crossing is refused as unbalanced.

A nuisance label unique to a unit is handled as a unit label, with a warning, rather than an extra identifiable random component. Numeric unit labels receive an exact linear-trend check. Whole-plot labels cancel from T3 B and interaction contrasts. Multiple nuisances are not checked jointly, and unrecorded or nonlinear drift can escape these checks.

Aliasing compares partitions rather than label spellings. Identical grouping partitions cannot yield separate components. T1 refuses the requested decomposition; T2 may retain the treatment test with combined components.

Diagnostics warn rather than gate: Brown–Forsythe `p<0.05`, largest/smallest group SD `≥2`, and absolute externally studentized residual `>3`. Normal quantile displays use Blom positions and internally studentized residuals, without a cutoff. Balanced `r=2` makes Brown–Forsythe unavailable. T1 checks top-group residuals only; T3 separates whole-plot and subplot residuals. Unavailable diagnostics and absence of warnings do not verify assumptions.

## Allocation and reassignment

For two run-level treatment means:

`Var(difference)=(2/r)(σ²_R+σ²_W/w+σ²_S/(ws))`.

The variance floor is `2σ²_R/r`. Only more runs lower this floor. Candidate additions compare one run per level, one wafer per run or one site per wafer; blocked T2 also shows the next addition that preserves complete crossing. A missing component yields bounds or unavailability, never a guessed point estimate. Costs and cost-optimal allocations are not implemented.

Allocation uncertainty uses 20,000 fixed-seed plausible stratum draws, `λ*=νMS/χ²_ν`, followed by pooling and inversion. Only fully identified candidate SEs are ranked; a 95% winning share is the stored ranking convention. These ranges are approximate, and their coverage was outside the simulation validation. In T3, an added subplot reading is a new B level and changes that factor; it is not a generic repeated reading at an existing position.

Eligible completely confounded categorical T2 assignments at the experimental-unit level receive `r′=k ceil(r/k)` new units per treatment, equally crossed over the nuisance levels. A deterministic, input-hash-seeded Fisher–Yates shuffle randomizes within each level. The new declaration and contrast geometry are checked. Existing observations are never relabeled, and other nuisances need recording and checking again.

Expected reassignment precision uses within-treatment×nuisance-cell variation, not the refused difference. It assumes additive effects and comparable future variation. Trends, partial confounding, T3 and below-unit nuisance factors do not receive this construction. With no estimable upper-unit variation, planning is limited to lower bounds; the floor's numerical value remains unknown.

Method references and source conventions are listed in [Data and references](docs/DATA_AND_REFERENCES.md); implementation excerpts appear in [Code samples](docs/CODE_SAMPLES.md).
