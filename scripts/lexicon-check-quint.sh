#!/usr/bin/env bash
# Quint <-> lexicon gate: shape of the formal models, then machine-checked
# verification. Models are discovered from the living-model layout
# (`${APP}/stories/*/formal/invariants.qnt`), one entry per story, so a new model
# cannot be silently omitted. The bounded context that owns each spec is
# resolved from the lexicon (`quint.specs`), so a spec follows the lexicon
# rather than one context hard-coded in this script. The reachability spec is the
# sibling `reachability.qnt` and may be absent. The pipeline runner pins a
# context via PIPELINE_CONTEXT; only specs owned by it run.
#
#   1. vocabulary conformance  — actions/invariants/witnesses owned by the lexicon
#   2. typecheck
#   3. exhaustive safety + deadlock via Apalache (bounded)
#   4. transition properties via TLC (full support for temporal properties)
#   5. reachability witnesses (simulation)
#   6. vacuity — every invariant falsifiable by a lexicon-declared corruption
#
# The verify/run commands are driven from the lexicon via `quint_check.py
# --emit`, so names cannot drift between the lexicon and this script.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

# NOTE: do not set JAVA_TOOL_OPTIONS=-XX:+UseParallelGC here. Quint's TLC
# backend first spawns the Apalache JVM (dist/src/tlc.js -> apalache.jar), which
# already selects a collector; an environment-level GC flag makes that JVM die
# with "Multiple garbage collectors selected", so the whole gate fails before
# TLC runs. TLC's "Please run the Java VM ... -XX:+UseParallelGC" line is a
# performance hint, not an error, and Quint spawns the TLC JVM internally
# (dist/src/tlc.js) with no hook to pass JVM arguments.

MAX_STEPS=20
MAX_SAMPLES=300

# One model per story, discovered from the living-model layout.
shopt -s nullglob
MODELS=(${APP}/stories/*/formal/invariants.qnt)
shopt -u nullglob
if [[ ${#MODELS[@]} -eq 0 ]]; then
  echo "FAIL: no ${APP}/stories/<story>/formal/invariants.qnt models found" >&2
  exit 1
fi

emit() {
  python3 tools/lexicon/quint_check.py --context "$1" --spec "$2" --emit "$3"
}

RAN=0
for MODEL in "${MODELS[@]}"; do
  # Ownership is a lexicon fact: resolve the context for this spec instead of
  # assuming the pipeline's context. An undeclared spec is a hard failure.
  CONTEXT="$(python3 tools/lexicon/quint_check.py --spec "${MODEL}" --print-context)"
  if [[ -n "${PIPELINE_CONTEXT:-}" && "${CONTEXT}" != "${PIPELINE_CONTEXT}" ]]; then
    continue
  fi
  RAN=$((RAN + 1))

  REACH="$(dirname "${MODEL}")/reachability.qnt"
  echo
  echo "==> ${MODEL} (context ${CONTEXT})"

  echo "--- vocabulary conformance"
  python3 tools/lexicon/quint_check.py --context "${CONTEXT}" --spec "${MODEL}"
  if [[ -f "${REACH}" ]]; then
    python3 tools/lexicon/quint_check.py --context "${CONTEXT}" --spec "${REACH}"
  fi

  echo "--- typecheck"
  quint typecheck "${MODEL}"
  if [[ -f "${REACH}" ]]; then
    quint typecheck "${REACH}"
  fi

  STATE_INVARIANTS="$(emit "${CONTEXT}" "${MODEL}" state)"
  TEMPORAL_PROPS="$(emit "${CONTEXT}" "${MODEL}" temporal)"

  if [[ -n "${STATE_INVARIANTS}" ]]; then
    echo "--- exhaustive safety + deadlock (Apalache, max ${MAX_STEPS} steps)"
    # shellcheck disable=SC2086
    quint verify "${MODEL}" --max-steps "${MAX_STEPS}" --invariants ${STATE_INVARIANTS}
  fi

  if [[ -n "${TEMPORAL_PROPS}" ]]; then
    echo "--- transition properties (TLC)"
    quint verify "${MODEL}" --backend tlc --temporal "$(echo "${TEMPORAL_PROPS}" | tr ' ' ',')"
  fi

  echo "--- vacuity"
  python3 tools/lexicon/quint_vacuity_check.py --context "${CONTEXT}" --spec "${MODEL}"

  if [[ -f "${REACH}" ]]; then
    WITNESSES="$(emit "${CONTEXT}" "${REACH}" witnesses)"
    if [[ -n "${WITNESSES}" ]]; then
      echo "--- reachability witnesses (simulation)"
      # shellcheck disable=SC2086
      quint run "${REACH}" --max-steps "${MAX_STEPS}" --max-samples "${MAX_SAMPLES}" \
        --witnesses ${WITNESSES}
    fi
  fi
done

if [[ ${RAN} -eq 0 ]]; then
  echo "FAIL: no Quint models owned by context ${PIPELINE_CONTEXT:-<all>}" >&2
  exit 1
fi

echo
echo "PASS: Quint models conform to the lexicon and verify."
