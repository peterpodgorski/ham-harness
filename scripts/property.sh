#!/usr/bin/env bash
# Property-based testing gate: run every property-test binary in the app.
# Context-aware by discovery, so a new property suite is picked up without
# editing the pipeline registry.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}/${APP}"

shopt -s nullglob
TESTS=(tests/property_tests*.rs)
shopt -u nullglob
if [[ ${#TESTS[@]} -eq 0 ]]; then
  echo "FAIL: no property_tests*.rs suites found" >&2
  exit 1
fi

ARGS=()
for f in "${TESTS[@]}"; do
  ARGS+=(--test "$(basename "${f}" .rs)")
done

echo "property suites: ${TESTS[*]}"
cargo test "${ARGS[@]}" -- --nocapture