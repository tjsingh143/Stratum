# MEMSS Oxide (= SASmixed Semi2 = Littell et al. 1996 Data Set 4.4): lot / wafer / site.
# Source is constant within lot (lots 1-4 vs 5-8), so it can only enter as a
# lot-level factor. Both treatments are stored; which one Stratum reproduces was
# left open in DECISIONS.md D-006.
source("r/common.R")
d <- read.csv(file.path(DERIVED, "oxide.csv"))
stopifnot(nrow(d) == 72)
d$Source <- factor(d$Source)
d$Lot <- factor(d$Lot)
d$Wafer <- factor(d$Wafer)  # labels 1-3 within each lot; nesting via Lot/Wafer
a <- nlevels(d$Lot); b <- 3; n <- 3

## A. T1 without Source: three-level nested variance components
fit_aov <- aov(Thickness ~ 1 + Error(Lot/Wafer), data = d)
summary(fit_aov)
strata <- aov_strata(fit_aov)
ms <- setNames(strata$ms, c("lot", "wafer", "site"))
mom <- c(lot = unname(ms["lot"] - ms["wafer"]) / (b * n),
         wafer = unname(ms["wafer"] - ms["site"]) / n,
         site = unname(ms["site"]))
mom

fit_lmer <- lmer(Thickness ~ 1 + (1 | Lot/Wafer), data = d, REML = TRUE)
summary(fit_lmer)
ci <- profile_sd_ci(fit_lmer)
ci

# Pinheiro & Bates (2000) ch. 4 model, as in nlme's inst/scripts/ch04.R
fit_lme <- nlme::lme(Thickness ~ 1, random = ~ 1 | Lot/Wafer, data = d, method = "REML")
fit_lme
lme_int <- nlme::intervals(fit_lme, which = "var-cov")
lme_int

## B. Source as a fixed lot-level factor (Littell et al. 1996, Output 4.15 structure)
fit_aov_src <- aov(Thickness ~ Source + Error(Lot/Wafer), data = d)
summary(fit_aov_src)

fit_lmer_src <- lmer(Thickness ~ Source + (1 | Lot/Wafer), data = d, REML = TRUE)
summary(fit_lmer_src)
an_sat <- lmertest_anova(fit_lmer_src, "Satterthwaite")
an_kr <- lmertest_anova(fit_lmer_src, "Kenward-Roger")
an_sat
an_kr

# nlme REML with SAS-style contrasts, to compare with the package transcript
# SASmixed/inst/transcripts/Semi2.St (fm2RSemi2).
op <- options(contrasts = c("contr.SAS", "contr.poly"))
fit_lme_src <- nlme::lme(Thickness ~ Source, random = ~ 1 | Lot/Wafer, data = d, method = "REML")
summary(fit_lme_src)
lme_src_tt <- summary(fit_lme_src)$tTable
options(op)

write_result(list(
  dataset = "MEMSS Oxide",
  design = list(a_lots = a, b_wafers_per_lot = b, n_sites_per_wafer = n,
                source_levels = nlevels(d$Source), lots_per_source = 4),
  without_source = list(
    aov_error_strata = strata,
    mom_variance_components = as.list(mom),
    mom_sd = as.list(sqrt(mom)),
    lmer_reml = list(vc = lmer_vc(fit_lmer), intercept = unname(fixef(fit_lmer)),
                     singular = isSingular(fit_lmer), profile_sd_ci = ci),
    nlme_reml = list(vc = nlme_vc(fit_lme), intercept = unname(nlme::fixef(fit_lme)),
                     logLik = as.numeric(logLik(fit_lme)),
                     sd_intervals = list(
                       Lot = as.list(lme_int$reStruct$Lot[1, ]),
                       Wafer = as.list(lme_int$reStruct$Wafer[1, ]),
                       residual = as.list(lme_int$sigma)))
  ),
  with_source_fixed = list(
    aov_error_strata = aov_strata(fit_aov_src),
    lmer_reml = list(vc = lmer_vc(fit_lmer_src), fixef = as.list(fixef(fit_lmer_src)),
                     singular = isSingular(fit_lmer_src)),
    lmertest_type3_satterthwaite = an_sat,
    lmertest_type3_kenward_roger = an_kr,
    nlme_reml_contr_sas = list(vc = nlme_vc(fit_lme_src),
                               ttable = data.frame(term = rownames(lme_src_tt), lme_src_tt,
                                                   row.names = NULL, check.names = TRUE))
  )
), "oxide.json")
