#!/usr/bin/env bash
# Runs inside the harness container (repository mounted at /workspace).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

(cd ${APP} && cargo build --bin derive)
CONTEXT="${PIPELINE_CONTEXT:-expense_tracking}"
python3 tools/lexicon/derive_check.py --context "${CONTEXT}" --derive-cmd ${APP}/target/debug/derive
