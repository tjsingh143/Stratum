# Record the exact R and package versions used for every stored reference output.
source("r/common.R")
pkgs <- c("lme4", "lmerTest", "pbkrtest", "nlme", "Matrix", "MEMSS", "SASmixed", "jsonlite")
versions <- vapply(pkgs, function(p) as.character(packageVersion(p)), "")
versions
sessionInfo()
write_result(list(
  r_version = R.version.string,
  platform = R.version$platform,
  packages = as.list(versions),
  cran_snapshot = Sys.getenv("CRAN_SNAPSHOT"),
  blas = extSoftVersion()[["BLAS"]],
  lapack = La_library()
), "session.json")
