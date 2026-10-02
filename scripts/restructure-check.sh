#!/usr/bin/env bash
# Restructure invariant gate: the app's semantic inputs are frozen.
#
# An architecture-scope refactor (/restructure) may change src/, tests/ and
# architecture/, but stories/ (story maps, features, formal models) and
# lexicon/ (ubiquitous language + derived relations) must stay byte-identical.
# This gate fails if anything under those paths is modified, staged, deleted or
# newly added relative to HEAD. It is the detection twin of the tool-boundary
# lock in .pi/extensions/process-gate.ts.
#
# The app is a separate repository (mounted at app/), so the check runs inside
# it. Set APP to an absolute path when the mount is external.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${APP:-app}"
if [[ "${APP}" = /* ]]; then
  APP_ROOT="${APP}"
else
  APP_ROOT="${ROOT}/${APP}"
fi

# Frozen paths, relative to the app repository root.
FROZEN=(stories lexicon)

if ! git -C "${APP_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "FAIL: ${APP_ROOT} is not a git work tree; cannot verify the restructure invariant" >&2
  exit 1
fi

# Tracked changes (staged or unstaged) against HEAD.
if ! git -C "${APP_ROOT}" diff --quiet HEAD -- "${FROZEN[@]}"; then
  echo "FAIL: frozen semantic inputs have changed:" >&2
  git -C "${APP_ROOT}" diff --name-status HEAD -- "${FROZEN[@]}" >&2
  exit 1
fi

# Untracked files (gitignore'd byproducts such as .DS_Store are excluded).
UNTRACKED="$(git -C "${APP_ROOT}" ls-files --others --exclude-standard -- "${FROZEN[@]}")"
if [[ -n "${UNTRACKED}" ]]; then
  echo "FAIL: new files under frozen semantic inputs:" >&2
  echo "${UNTRACKED}" >&2
  exit 1
fi

echo "PASS: stories and lexicon are unchanged in ${APP_ROOT} (restructure invariant holds)"
