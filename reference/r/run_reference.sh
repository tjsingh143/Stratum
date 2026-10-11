#!/usr/bin/env bash
# Regenerate every stored WP0 R reference output in reference/r_outputs/.
#   1. verify the fetched sources (reference/fetch.py --offline)
#   2. build the pinned R image (reference/r/Dockerfile)
#   3. install MEMSS and SASmixed from the checksum-verified tarballs
#   4. run each NN_*.R script; its echoed transcript goes to r_outputs/<name>.Rout
set -euo pipefail
REF="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE=stratum-wp0-r:1

python3 "$REF/fetch.py" --offline
docker build -q -t "$IMAGE" "$REF/r" >/dev/null
mkdir -p "$REF/r_outputs"

docker run --rm -v "$REF":/work -w /work "$IMAGE" bash -c '
  set -euo pipefail
  mkdir -p /tmp/lib
  R CMD INSTALL --no-test-load -l /tmp/lib \
    _fetched/cran/MEMSS_0.9-4.tar.gz _fetched/cran/SASmixed_1.0-5.tar.gz >/tmp/install.log 2>&1 \
    || { cat /tmp/install.log; exit 1; }
  for script in r/[0-9][0-9]_*.R; do
    name=$(basename "$script" .R); name=${name#[0-9][0-9]_}
    echo "running $script"
    Rscript --vanilla -e "source(\"$script\", echo = TRUE, max.deparse.length = Inf, spaced = TRUE)" \
      > "r_outputs/$name.Rout" 2>&1 || { tail -30 "r_outputs/$name.Rout"; exit 1; }
  done
'
echo "reference outputs written to $REF/r_outputs"
