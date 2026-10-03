#!/usr/bin/env bash
# Escape-hatch / residual-risk gate.
#
# Every `system` declaration and every coverage/trace/vacuity exemption is a
# declared escape hatch from the traceability chain. This gate always enforces
# the *shape* (a `system` action may not also map to a step; a `system` mapping
# needs a closed `kind` and a non-empty `reason`; an exemption needs a non-empty
# reason) and reports every escape hatch as residual risk.
#
# Whether a *bare* `system: true` or an un-reasoned exemption is fatal is a
# per-context policy, set through the gate params:
#
#   PIPELINE_PARAM_REQUIRE_REASON    fail on `system: true` without a reason
#   PIPELINE_PARAM_STRICT_EXEMPTIONS fail on an exemption without a reason
#
# The JSON manifest is the residual-risk record a commit can cite:
#   python3 tools/lexicon/discipline.py --context <ctx> --json --out risk.json
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

CONTEXT="${PIPELINE_CONTEXT:-${CONTEXT:-}}"
if [[ -z "${CONTEXT}" ]]; then
  echo "FAIL: no bounded context; set CONTEXT (or PIPELINE_CONTEXT)" >&2
  exit 1
fi

ARGS=("--context" "${CONTEXT}" "--lexicon-dir" "${APP}/lexicon")
if [[ "${PIPELINE_PARAM_REQUIRE_REASON:-false}" == "true" ]]; then
  ARGS+=("--require-reason")
fi
if [[ "${PIPELINE_PARAM_STRICT_EXEMPTIONS:-false}" == "true" ]]; then
  ARGS+=("--strict-exemptions")
fi

python3 tools/lexicon/discipline.py "${ARGS[@]}"
