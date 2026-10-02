#!/usr/bin/env bash
# As-built check gate: regenerate the class model deterministically from the
# context's code and fail if it differs from the committed rendering. This is
# the automated half of the /explain as-built gate; the plan-vs-built review
# remains a human decision.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

CONTEXT="${PIPELINE_CONTEXT:-expense_tracking}"
COMMITTED="${APP}/architecture/${CONTEXT}/class.md"
if [[ ! -f "${COMMITTED}" ]]; then
  echo "FAIL: ${COMMITTED} does not exist (as-built model is missing)" >&2
  exit 1
fi

(cd tools/arch/extract-classes && cargo build --quiet)
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

tools/arch/extract-classes/target/debug/extract-classes \
  --src "${APP}/src/${CONTEXT}" --context "${CONTEXT}" > "${TMP}/class-asbuilt.json"
python3 tools/arch/class_render.py --model "${TMP}/class-asbuilt.json" --out "${TMP}/class.md"

if ! diff -u "${COMMITTED}" "${TMP}/class.md"; then
  echo "FAIL: ${CONTEXT} as-built class model is stale; run scripts/arch-class.sh" >&2
  exit 1
fi
echo "PASS: ${CONTEXT} as-built class model is current"