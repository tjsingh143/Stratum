# NIST/SEMATECH lithography case study (handbook 6.6.1; optional in the brief):
# cassette / wafer / site, raw line width.
source("r/common.R")
d <- read.csv(file.path(DERIVED, "lithography.csv"))
stopifnot(nrow(d) == 450)
d$cassette <- factor(d$cassette)
d$wafer <- factor(d$wafer)  # labels 1-3 within each cassette
d$site <- factor(d$site)
a <- nlevels(d$cassette); b <- 3; n <- 5

## 1. Nested ANOVA with Error strata, site treated as replicate within wafer
##    (as in the handbook, 6.6.1.3)
fit_aov <- aov(width_raw ~ 1 + Error(cassette/wafer), data = d)
summary(fit_aov)
strata <- aov_strata(fit_aov)
ms <- setNames(strata$ms, c("cassette", "wafer", "site"))
mom <- c(cassette = unname(ms["cassette"] - ms["wafer"]) / (b * n),
         wafer = unname(ms["wafer"] - ms["site"]) / n,
         site = unname(ms["site"]))
mom

## 2. REML cross-checks
fit_lmer <- lmer(width_raw ~ 1 + (1 | cassette/wafer), data = d, REML = TRUE)
summary(fit_lmer)
fit_lme <- nlme::lme(width_raw ~ 1, random = ~ 1 | cassette/wafer, data = d, method = "REML")
nlme::VarCorr(fit_lme)

## 3. Supplementary structural check (not a published reference): sites 1-5 are
##    fixed positions (Top, Left, Center, Right, Bottom), so a systematic site
##    effect is folded into the "site" component above (DECISIONS.md D-007).
fit_site_fixed <- aov(width_raw ~ site + Error(cassette/wafer), data = d)
summary(fit_site_fixed)

write_result(list(
  dataset = "NIST lithography (LITHOGRA.DAT), raw width",
  design = list(a_cassettes = a, b_wafers_per_cassette = b, n_sites_per_wafer = n),
  aov_error_strata = strata,
  mom_variance_components = as.list(mom),
  lmer_reml = list(vc = lmer_vc(fit_lmer), singular = isSingular(fit_lmer)),
  nlme_reml = nlme_vc(fit_lme),
  supplementary_site_fixed = aov_strata(fit_site_fixed)
), "lithography.json")
