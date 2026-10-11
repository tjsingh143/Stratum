# Pinned R environment for the WP0 reference analyses (DECISIONS.md D-002).
# R is used only to produce stored reference outputs; Stratum itself is Python.
#
# Base image pinned by digest (rocker/r-ver:4.6.1, multi-arch index digest).
FROM rocker/r-ver:4.6.1@sha256:4e6e6696ff54a86625c7f80046478e67014a2184e942b85eeff43db7b992d93e

# CRAN packages from a dated Posit Package Manager snapshot, so every rebuild
# resolves the same versions. MEMSS and SASmixed are NOT installed here: they
# are installed at run time from the checksum-verified tarballs fetched by
# reference/fetch.py, so the data provably come from the pinned sources.
ENV CRAN_SNAPSHOT=https://p3m.dev/cran/__linux__/noble/2026-09-29

RUN Rscript -e 'options(repos = c(CRAN = Sys.getenv("CRAN_SNAPSHOT"))); \
      install.packages(c("nlme", "lme4", "lmerTest", "pbkrtest", "jsonlite")); \
      for (p in c("nlme", "lme4", "lmerTest", "pbkrtest", "jsonlite")) \
        if (!requireNamespace(p, quietly = TRUE)) stop("failed to install ", p)'

WORKDIR /work
