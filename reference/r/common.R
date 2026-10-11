# Shared helpers for the WP0 reference analyses. Sourced by each NN_*.R script.
# Runs inside the stratum-wp0-r image with /work = reference/.

.libPaths(c("/tmp/lib", .libPaths()))  # MEMSS, SASmixed installed here by run_reference.sh
suppressPackageStartupMessages({
  library(lme4)
  library(lmerTest)  # masks lme4::lmer so fits carry Satterthwaite/KR methods
  library(jsonlite)
})
# nlme is not attached (its VarCorr/lmList clash with lme4); it is called as nlme::.
options(width = 100, digits = 7, contrasts = c("contr.sum", "contr.poly"))

OUT <- "r_outputs"
DERIVED <- "_fetched/derived"

# Read a NIST Dataplot .DAT file: data start after the first all-dash line.
read_dat <- function(path, cols) {
  lines <- readLines(path, warn = FALSE)
  start <- which(grepl("^-+\\s*$", lines))[1]
  body <- lines[(start + 1):length(lines)]
  read.table(text = body[nzchar(trimws(body))], col.names = cols)
}

# One row per term per Error() stratum of an aov fit.
aov_strata <- function(fit) {
  s <- summary(fit)
  rows <- lapply(names(s), function(st) {
    tab <- s[[st]][[1]]
    data.frame(
      stratum = st, term = trimws(rownames(tab)), df = tab[["Df"]],
      ss = tab[["Sum Sq"]], ms = tab[["Mean Sq"]],
      F = if ("F value" %in% names(tab)) tab[["F value"]] else NA_real_,
      p = if ("Pr(>F)" %in% names(tab)) tab[["Pr(>F)"]] else NA_real_,
      row.names = NULL
    )
  })
  do.call(rbind, rows)
}

# Single-stratum aov fit as the same kind of table.
aov_table <- function(fit) {
  tab <- summary(fit)[[1]]
  data.frame(term = trimws(rownames(tab)), df = tab[["Df"]], ss = tab[["Sum Sq"]],
             ms = tab[["Mean Sq"]], F = tab[["F value"]], p = tab[["Pr(>F)"]],
             row.names = NULL)
}

# Variance components and SDs from an lme4 fit, as a named list.
lmer_vc <- function(fit) {
  vc <- as.data.frame(lme4::VarCorr(fit))
  setNames(lapply(seq_len(nrow(vc)), function(i) list(variance = vc$vcov[i], sd = vc$sdcor[i])),
           vc$grp)
}

# lmerTest type III table with the requested denominator-df method.
lmertest_anova <- function(fit, ddf) {
  a <- anova(fit, type = 3, ddf = ddf)
  data.frame(term = rownames(a), num_df = a[["NumDF"]], den_df = a[["DenDF"]],
             F = a[["F value"]], p = a[["Pr(>F)"]], row.names = NULL)
}

# Profile-likelihood intervals for the SD parameters of an lme4 fit.
profile_sd_ci <- function(fit) {
  ci <- suppressMessages(confint(fit, method = "profile", signames = FALSE, parm = "theta_"))
  data.frame(parameter = rownames(ci), lower = ci[, 1], upper = ci[, 2], row.names = NULL)
}

# Variance components of a random-intercept nlme fit at full precision, keyed by
# grouping level (nlme::VarCorr returns rounded character strings).
nlme_vc <- function(fit) {
  re <- fit$modelStruct$reStruct
  s2 <- fit$sigma^2
  out <- lapply(names(re), function(g) {
    v <- s2 * as.numeric(as.matrix(re[[g]]))
    list(variance = v, sd = sqrt(v))
  })
  names(out) <- names(re)
  out$Residual <- list(variance = s2, sd = fit$sigma)
  out
}

write_result <- function(x, name) {
  writeLines(toJSON(x, auto_unbox = TRUE, digits = NA, pretty = TRUE, na = "null"),
             file.path(OUT, name))
}
