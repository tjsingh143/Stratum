# SASmixed Semiconductor (Littell et al. 1996, Data Set 2.2(b)): T3 split-plot.
# Whole-plot factor ET (etch time) on wafers; subplot factor position within wafer.
source("r/common.R")
d <- read.csv(file.path(DERIVED, "semiconductor.csv"))
stopifnot(nrow(d) == 48)
d$ET <- factor(d$ET)
d$position <- factor(d$position)
d$Grp <- factor(d$Grp)  # wafer identity = ET/Wafer; Wafer labels repeat across ET

## 1. Correct split-plot ANOVA: ET tested in the wafer stratum, position and
##    ET:position in the within-wafer stratum.
fit_split <- aov(resistance ~ ET * position + Error(Grp), data = d)
summary(fit_split)

## 2. Naive single-error ANOVA (treats all 48 readings as independent).
fit_naive <- aov(resistance ~ ET * position, data = d)
summary(fit_naive)

## 3. REML mixed model with lmerTest type III tests
fit_lmer <- lmer(resistance ~ ET * position + (1 | Grp), data = d, REML = TRUE)
summary(fit_lmer)
an_sat <- lmertest_anova(fit_lmer, "Satterthwaite")
an_kr <- lmertest_anova(fit_lmer, "Kenward-Roger")
an_sat
an_kr

## 4. nlme ML fit with SAS contrasts, to compare with the package transcript
##    SASmixed/inst/transcripts/Semiconductor.St (fm1Semi, S-PLUS 3.4 / nlme 3.0).
op <- options(contrasts = c("contr.SAS", "contr.poly"))
fit_lme_ml <- nlme::lme(resistance ~ ET * position, random = ~ 1 | Grp, data = d, method = "ML")
summary(fit_lme_ml)
options(op)

write_result(list(
  dataset = "SASmixed Semiconductor",
  design = list(a_et_levels = nlevels(d$ET), r_wafers_per_et = 3, b_positions = nlevels(d$position)),
  split_plot_aov_error_strata = aov_strata(fit_split),
  naive_aov = aov_table(fit_naive),
  lmer_reml = list(vc = lmer_vc(fit_lmer), singular = isSingular(fit_lmer),
                   reml_criterion = unname(REMLcrit(fit_lmer))),
  lmertest_type3_satterthwaite = an_sat,
  lmertest_type3_kenward_roger = an_kr,
  nlme_ml_contr_sas = list(vc = nlme_vc(fit_lme_ml), logLik = as.numeric(logLik(fit_lme_ml)),
                           AIC = AIC(fit_lme_ml), BIC = BIC(fit_lme_ml))
), "semiconductor.json")
