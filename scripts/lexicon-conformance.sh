#!/usr/bin/env bash
# Runs inside the harness container (repository mounted at /workspace).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

(cd ${APP} && cargo build --bin derive)
CONTEXT="${PIPELINE_CONTEXT:-${CONTEXT:-}}"
if [[ -z "${CONTEXT}" ]]; then
  echo "FAIL: no bounded context; set CONTEXT (or PIPELINE_CONTEXT)" >&2
  exit 1
fi
python3 tools/lexicon/derive_check.py --context "${CONTEXT}" --derive-cmd ${APP}/target/debug/derive
