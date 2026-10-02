#!/usr/bin/env bash
# Entry point for the deterministic per-context pipeline.
#
#   scripts/pipeline.sh check
#   scripts/pipeline.sh plan  --context expense_tracking
#   scripts/pipeline.sh run   --context expense_tracking
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

exec python3 tools/pipeline/pipeline.py "$@"