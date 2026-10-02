#!/usr/bin/env bash
# Scenario <-> model gate: every non-`system` Quint action must be exercised by
# its story's Gherkin, and every scenario must replay as a valid model path.
#
# The join is per story: the model is discovered from the living-model layout,
# its owning context is resolved from the lexicon, and the story's `features/`
# directory supplies the scenarios (the lexicon may override with
# `coverage.features`). Gaps and stale exemptions fail; templates shared by
# several actions and used templates with no action are reported as notes;
# ambiguous steps in a trace are composed with `any { ... }` and resolved by
# `quint test`.
#
# Coverage is template-level: it catches an action whose whole template no
# scenario exercises, not an action that shares a used template with a sibling.
# Telling those apart needs argument binding (`quint_check.py` docs). Trace
# replay checks ordering, guards and state invariants, not concrete values.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

shopt -s nullglob
MODELS=(${APP}/stories/*/formal/invariants.qnt)
shopt -u nullglob
if [[ ${#MODELS[@]} -eq 0 ]]; then
  echo "FAIL: no ${APP}/stories/<story>/formal/invariants.qnt models found" >&2
  exit 1
fi

RAN=0
for MODEL in "${MODELS[@]}"; do
  # Ownership is a lexicon fact: resolve the context for this spec instead of
  # assuming the pipeline's context.
  CONTEXT="$(python3 tools/lexicon/quint_check.py --spec "${MODEL}" --print-context)"
  if [[ -n "${PIPELINE_CONTEXT:-}" && "${CONTEXT}" != "${PIPELINE_CONTEXT}" ]]; then
    continue
  fi
  RAN=$((RAN + 1))
  echo
  echo "==> ${MODEL} (context ${CONTEXT})"
  python3 tools/lexicon/quint_check.py --context "${CONTEXT}" --spec "${MODEL}" --coverage --trace
done

if [[ ${RAN} -eq 0 ]]; then
  echo "FAIL: no Quint models owned by context ${PIPELINE_CONTEXT:-<all>}" >&2
  exit 1
fi

echo
echo "PASS: every Quint action is exercised by its story's Gherkin."
