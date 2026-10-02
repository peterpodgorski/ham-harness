#!/usr/bin/env bash
# Model-based testing against the Alloy domain models: replay Alloy-generated
# traces against the real app, one driver per bounded context.
#
# Registration is by convention: a context with `${APP}/architecture/<context>/domain.als`
# must have a driver at `${APP}/tests/mbt_<context>.rs`. The script discovers
# the contexts, so a new domain model cannot be silently left without MBT.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

export ALLOY_JAR="${ALLOY_JAR:-/usr/local/lib/alloy/org.alloytools.alloy.dist.jar}"

if [[ -n "${PIPELINE_CONTEXT:-}" ]]; then
  MODELS=("${APP}/architecture/${PIPELINE_CONTEXT}/domain.als")
else
  shopt -s nullglob
  MODELS=(${APP}/architecture/*/domain.als)
  shopt -u nullglob
fi
if [[ ${#MODELS[@]} -eq 0 ]]; then
  echo "FAIL: no ${APP}/architecture/<context>/domain.als models found" >&2
  exit 1
fi

for MODEL in "${MODELS[@]}"; do
  CONTEXT="$(basename "$(dirname "${MODEL}")")"
  DRIVER="${APP}/tests/mbt_${CONTEXT}.rs"
  if [[ ! -f "${DRIVER}" ]]; then
    echo "FAIL: ${MODEL} has no MBT driver at ${DRIVER}" >&2
    exit 1
  fi
  echo
  echo "==> ${CONTEXT} (${DRIVER})"
  cargo test --manifest-path ${APP}/Cargo.toml --test "mbt_${CONTEXT}" -- --nocapture
done

echo
echo "PASS: Alloy domain MBT passed for every context."