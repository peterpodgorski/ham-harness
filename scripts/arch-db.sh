#!/usr/bin/env bash
# Runs inside the harness container (repository mounted at /workspace).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

CONTEXT="${PIPELINE_CONTEXT:-expense_tracking}"

python3 tools/arch/extract_schema.py --src "${APP}/src/${CONTEXT}/adapters/sqlite_store.rs" --context "${CONTEXT}" > "${APP}/architecture/${CONTEXT}/database-asbuilt.json"
python3 tools/arch/schema_render.py --model "${APP}/architecture/${CONTEXT}/database-asbuilt.json" --out "${APP}/architecture/${CONTEXT}/database.md"
