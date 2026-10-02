#!/usr/bin/env bash
# Model-based testing against the Quint behavioural models: replay
# Quint-generated traces against the real app, one driver per story.
#
# Registration is by convention: a story with
# `${APP}/stories/<story>/formal/invariants.qnt` may register a driver at
# `${APP}/tests/mbt_<story>.rs` (dashes become underscores). The script
# discovers the models from the living-model layout, so a new behavioural model
# is picked up without editing this script and the driver list is never
# hard-coded. MBT is run only for stories that register a driver (it is enabled
# when the story warrants it). The pipeline runner pins a context via
# PIPELINE_CONTEXT; only specs owned by it run.
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
MISSING=()
for MODEL in "${MODELS[@]}"; do
  STORY="$(basename "$(dirname "$(dirname "${MODEL}")")")"
  DRIVER="${APP}/tests/mbt_${STORY//-/_}.rs"
  if [[ ! -f "${DRIVER}" ]]; then
    MISSING+=("${STORY}")
    continue
  fi

  # The context that owns the spec is a lexicon fact, resolved from the model
  # rather than assumed from the pipeline.
  CONTEXT="$(python3 tools/lexicon/quint_check.py --spec "${MODEL}" --print-context)"
  if [[ -n "${PIPELINE_CONTEXT:-}" && "${CONTEXT}" != "${PIPELINE_CONTEXT}" ]]; then
    continue
  fi

  RAN=$((RAN + 1))
  echo
  echo "==> ${STORY} (${DRIVER})"
  cargo test --manifest-path ${APP}/Cargo.toml --test "mbt_${STORY//-/_}" -- --nocapture
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo
  echo "note: no MBT driver registered for: ${MISSING[*]}"
fi

if [[ ${RAN} -eq 0 ]]; then
  echo "FAIL: no Quint MBT drivers found for context ${PIPELINE_CONTEXT:-<all>}" >&2
  exit 1
fi

echo
echo "PASS: Quint domain behaviour MBT passed for every registered story."
