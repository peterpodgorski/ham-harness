#!/usr/bin/env bash
# Runs inside the harness container (repository mounted at /workspace).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

PLAN="${1:?usage: arch-class-diff.sh PLAN}"
CONTEXT="${PIPELINE_CONTEXT:-expense_tracking}"
python3 tools/arch/class_diff.py \
  --plan "${PLAN}" \
  --built "${APP}/architecture/${CONTEXT}/class-asbuilt.json"
