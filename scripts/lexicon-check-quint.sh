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

# TLC (and the Apalache JVM) want a throughput-oriented garbage collector;
# without it the JVM prints "Please run the Java VM ... -XX:+UseParallelGC" and
# checks with a stop-the-world collector. Quint spawns the JVMs, so the option
# rides in through the environment, and both the direct `verify` and the
# vacuity subprocess inherit it. Preserve anything the caller/container set.
if [[ -n "${JAVA_TOOL_OPTIONS:-}" ]]; then
  export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS} -XX:+UseParallelGC"
else
  export JAVA_TOOL_OPTIONS="-XX:+UseParallelGC"
fi

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
