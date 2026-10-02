#!/usr/bin/env bash
# Runs inside the harness container (repository mounted at /workspace).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

CONTEXT="${PIPELINE_CONTEXT:-expense_tracking}"

(cd tools/arch/extract-classes && cargo build --quiet)
tools/arch/extract-classes/target/debug/extract-classes --src "${APP}/src/${CONTEXT}" --context "${CONTEXT}" > "${APP}/architecture/${CONTEXT}/class-asbuilt.json"
python3 tools/arch/class_render.py --model "${APP}/architecture/${CONTEXT}/class-asbuilt.json" --out "${APP}/architecture/${CONTEXT}/class.md"
