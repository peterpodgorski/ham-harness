#!/usr/bin/env bash
# Runs inside the harness container (repository mounted at /workspace).
#
# Acceptance: the Cucumber scenarios run green on two axes.
#
#   * Layer  — the same `.feature` files are executed twice:
#       - handler pass (default): steps call the feature handlers/ports directly;
#       - TUI pass (`BDD_LAYER=tui`): every scenario tagged `@tui` is driven
#         through the real `UiState` key reducer, so it proves the behaviour is
#         reachable from the keyboard, not merely callable from the handler.
#       A tagged behaviour that has no TUI route (e.g. a missing screen) fails
#       the TUI pass — this is the enforcement the `@tui` marker exists for.
#   * Storage — each pass runs against the in-memory store and a real SQLite
#     database (`BDD_BACKEND=sqlite`), so the adapter + schema stack is
#     exercised too.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

cd ${APP}

echo "== handler pass (in-memory) =="
cargo test --test cucumber_bdd
echo "== handler pass (sqlite) =="
BDD_BACKEND=sqlite cargo test --test cucumber_bdd

# TUI pass. The runner runs only `@tui` scenarios and exits non-zero if it
# runs zero of them — a feature that claims TUI coverage must actually be
# exercised. A context with genuinely no TUI behaviours should not enable this
# gate (or should carry no `@tui` features); see the gate registry.
echo "== TUI pass (@tui, in-memory) =="
BDD_LAYER=tui cargo test --test cucumber_bdd
echo "== TUI pass (@tui, sqlite) =="
BDD_LAYER=tui BDD_BACKEND=sqlite cargo test --test cucumber_bdd
