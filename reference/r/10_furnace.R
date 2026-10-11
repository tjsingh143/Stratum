# NIST/SEMATECH furnace case study (handbook 3.5.1): T1, run / zone-within-run / wafer.
source("r/common.R")
d <- read.csv(file.path(DERIVED, "furnace.csv"))
stopifnot(nrow(d) == 168)
d$run <- factor(d$run)
d$zone <- factor(d$zone)
a <- nlevels(d$run); b <- nlevels(d$zone); n <- 2

## 1. Nested ANOVA with Error strata, in the form used by NIST's ppc511.r
fit_aov <- aov(thickness ~ run + Error(run/zone), data = d)
summary(fit_aov)
strata <- aov_strata(fit_aov)
ms_run <- strata$ms[strata$term == "run"]
ms_loc <- strata$ms[strata$stratum == "Error: run:zone"]
ms_within <- strata$ms[strata$stratum == "Error: Within"]
df_run <- a - 1; df_loc <- a * (b - 1); df_within <- a * b * (n - 1)
stopifnot(strata$df[strata$term == "run"] == df_run)

# F tests as in the handbook: run against location(run), location against within.
f_run <- ms_run / ms_loc
f_loc <- ms_loc / ms_within
tests <- data.frame(
  term = c("run", "location(run)"), num_df = c(df_run, df_loc), den_df = c(df_loc, df_within),
  F = c(f_run, f_loc),
  p = c(pf(f_run, df_run, df_loc, lower.tail = FALSE), pf(f_loc, df_loc, df_within, lower.tail = FALSE))
)
tests

# Method-of-moments components from the balanced E[MS] (brief Section 5.1).
mom <- c(run = (ms_run - ms_loc) / (b * n), location = (ms_loc - ms_within) / n, within = ms_within)
mom

## 2. REML via lme4 (cross-check), with profile intervals for the SDs
fit_lmer <- lmer(thickness ~ 1 + (1 | run) + (1 | run:zone), data = d, REML = TRUE)
summary(fit_lmer)
ci <- profile_sd_ci(fit_lmer)
ci

## 3. REML via nlme, as in NIST's ppc511.r
fit_lme <- nlme::lme(thickness ~ 1, random = ~ 1 | run/zone, data = d, method = "REML")
nlme::VarCorr(fit_lme)

## 4. Supplementary structural check (not a published reference): zone labels
## 1-4 are the same physical furnace positions in every run, so zone could be a
## fixed crossed factor rather than a random nested one (DECISIONS.md D-007).
fit_zone_fixed <- aov(thickness ~ zone + Error(run/zone), data = d)
summary(fit_zone_fixed)

write_result(list(
  dataset = "NIST furnace (FURNACE.DAT)",
  design = list(a_runs = a, b_zones_per_run = b, n_wafers_per_zone = n),
  aov_error_strata = strata,
  f_tests_handbook_form = tests,
  mom_variance_components = as.list(mom),
  mom_sd = as.list(sqrt(mom)),
  mom_percent_of_total = as.list(100 * mom / sum(mom)),
  lmer_reml = list(vc = lmer_vc(fit_lmer), intercept = unname(fixef(fit_lmer)),
                   singular = isSingular(fit_lmer), profile_sd_ci = ci),
  nlme_reml = nlme_vc(fit_lme),
  supplementary_zone_fixed = aov_strata(fit_zone_fixed)
), "furnace.json")
