#!/usr/bin/env bash
# Alloy <-> lexicon gate: the cross-feature structural domain model.
#
#   1. vocabulary conformance  — every sig/field/check/witness owned by the
#      lexicon, MBT conventions declared, no Int arithmetic in the model
#   2. structure gate          — `alloy exec` with `expect` annotations; the
#      CLI exit code is the result (`check … expect 0`, `run … expect 1`),
#      and the `run` witnesses are also the inhabitation check
#   3. vacuity gate            — every non-exempt check must be falsifiable by
#      a lexicon corruption injected into a copy of the model
#
# One entry per bounded context; the model is a living context artifact
# (`${APP}/architecture/<context>/domain.als`).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

ALLOY_JAR="${ALLOY_JAR:-/usr/local/lib/alloy/org.alloytools.alloy.dist.jar}"

# One model per bounded context, discovered from the living-model layout so a
# new context cannot be silently omitted. The pipeline runner pins the context
# via PIPELINE_CONTEXT.
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
  echo
  echo "==> ${MODEL}"

  echo "--- catalog is current (generated from the conformance oracle)"
  python3 tools/lexicon/render_alloy_catalog.py --spec "${MODEL}" --check

  echo "--- vocabulary conformance"
  python3 tools/lexicon/alloy_check.py --context "${CONTEXT}" --spec "${MODEL}"

  echo "--- structure gate (expect: invariants hold, witnesses reachable)"
  # Always direct the (receipt) output to a scratch dir so the gate never
  # leaves an Alloy byproduct in the working tree. The aarch64 native-solver
  # probe is a harmless fallback to SAT4J; filter the noise, keep the status.
  OUT="$(mktemp -d)"
  java -jar "${ALLOY_JAR}" exec -t none -o "${OUT}" -f "${MODEL}" \
      2> >(grep -v 'findPlatform unknown' >&2)
  rm -rf "${OUT}"

  echo "--- vacuity gate (every non-exempt check falsifiable)"
  python3 tools/lexicon/alloy_vacuity_check.py --context "${CONTEXT}" --spec "${MODEL}"
done

echo
echo "PASS: Alloy domain models conform to the lexicon and satisfy their invariants."