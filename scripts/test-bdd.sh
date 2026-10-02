#!/usr/bin/env bash
# Runs inside the harness container (repository mounted at /workspace).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

cd ${APP}
cargo test --test cucumber_bdd
BDD_BACKEND=sqlite cargo test --test cucumber_bdd
