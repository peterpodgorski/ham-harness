#!/usr/bin/env bash
# Verification attestation: bind the code to the spec it was checked against.
#
#   scripts/attest.sh emit  --context <ctx> [--out attestations/<ctx>.json]
#   scripts/attest.sh emit  --context <ctx> --format trailer
#   scripts/attest.sh check --context <ctx> --attestation <path>
#
# `emit` records the semantic-input digest, the resolved gate set and the
# deepest machine-checked layer. `check` fails if any of them drifted. The
# trailer form is what a commit can cite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

python3 tools/verify/attest.py "$@"
