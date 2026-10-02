#!/usr/bin/env bash
# Regenerate the Alloy category catalog from the conformance oracle
# (`app/lexicon/relations.py::CATEGORY_GROUPS`). Run after the category
# mapping changes; `alloy-check` fails while the rendered catalog is stale.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP="${APP:-app}"
cd "${ROOT}"

shopt -s nullglob
MODELS=(${APP}/architecture/*/domain.als)
shopt -u nullglob
if [[ ${#MODELS[@]} -eq 0 ]]; then
  echo "FAIL: no ${APP}/architecture/<context>/domain.als models found" >&2
  exit 1
fi

for MODEL in "${MODELS[@]}"; do
  python3 tools/lexicon/render_alloy_catalog.py --spec "${MODEL}" --write
done