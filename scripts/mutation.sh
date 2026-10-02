#!/usr/bin/env bash
# Mutation kill-rate gate. Runs `cargo-mutants` and compares the caught/total
# ratio against PIPELINE_PARAM_THRESHOLD (default 1.0). Off by default in every
# profile: it is slow and is only enabled where a context has asked for it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}/${APP}"

THRESHOLD="${PIPELINE_PARAM_THRESHOLD:-1.0}"

echo "mutation threshold: ${THRESHOLD}"
# cargo-mutants exits non-zero when mutants survive; the score below is the
# authoritative check, so do not abort on its exit code.
cargo mutants --no-times || true

python3 - "${THRESHOLD}" <<'PY'
import sys
from pathlib import Path

threshold = float(sys.argv[1])
out = Path("mutants.out")
if not out.is_dir():
    print(f"FAIL: cargo-mutants produced no {out}/ (baseline tests may have failed)")
    sys.exit(1)

def count(name: str) -> int:
    path = out / name
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())

caught = count("caught.txt")
missed = count("missed.txt")
timeout = count("timeout.txt")
total = caught + missed + timeout
score = caught / total if total else 0.0
print(f"mutation score: {score:.3f} ({caught} caught, {missed} missed, "
      f"{timeout} timeout of {total})")
if score < threshold:
    print(f"FAIL: mutation score {score:.3f} < threshold {threshold:.3f}")
    sys.exit(1)
print("PASS: mutation score meets threshold")
PY