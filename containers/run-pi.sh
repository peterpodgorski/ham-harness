#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Local configuration lives in a gitignored .env at the harness root (e.g.
# PI_APP, PI_IMAGE). Load it so the caller does not have to export each time.
ENV_FILE="${PI_ENV_FILE:-${SCRIPT_DIR}/../.env}"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

IMAGE="${PI_IMAGE:-harness-pi:latest}"

# ── Build on demand ──────────────────────────────────────────────────────────

rebuild_image() {
  echo "==> Building pi agent image..." >&2
  podman build -t "${IMAGE}" -f "${SCRIPT_DIR}/Containerfile.pi" "${SCRIPT_DIR}/.."
}

if [[ "${1:-}" == "--build" ]]; then
  shift
  rebuild_image
elif ! podman image exists "${IMAGE}"; then
  echo "Image ${IMAGE} not found — building..." >&2
  rebuild_image
fi

# ── Config isolation ─────────────────────────────────────────────────────────

WORKSPACE="${PI_WORKSPACE:-$(pwd)}"
WORKSPACE="$(realpath "${WORKSPACE}")"

# The app repository is external, so its path is configuration, not an
# assertion. Set PI_APP to the app repository root; there is no default.
APP_REPO="${PI_APP:-}"
if [[ -z "${APP_REPO}" ]]; then
  echo "PI_APP is not set; point it at the app repository (export PI_APP=/path/to/app)." >&2
  exit 1
fi
APP_REPO="$(realpath "${APP_REPO}")"
if [[ ! -f "${APP_REPO}/Cargo.toml" ]]; then
  echo "App repository not found: ${APP_REPO}" >&2
  exit 1
fi

# alloy-connect is a separate (local) repository, mounted at
# /workspace/alloy-connect. The app's Cargo.toml refers to it as
# ../alloy-connect/alloy-connect, which resolves the same way on macOS.
ALLOY_REPO="${ALLOY_REPO:-}"
if [[ -z "${ALLOY_REPO}" ]]; then
  echo "ALLOY_REPO is not set; point it at the alloy-connect repository (export ALLOY_REPO=/path/to/alloy-connect)." >&2
  exit 1
fi
ALLOY_REPO="$(realpath "${ALLOY_REPO}")"
if [[ ! -f "${ALLOY_REPO}/Cargo.toml" ]]; then
  echo "alloy-connect repository not found: ${ALLOY_REPO}" >&2
  exit 1
fi

# Per-session config isolation. Multiple pi containers running in different
# terminals must not share one ~/.pi — concurrent writes to auth, sessions,
# settings, or installed packages can corrupt each other. Each session name gets
# its own directory and persists its login independently.
#
# Host-path bind mount (not a named volume) so that --userns=keep-id correctly
# maps the host user to container uid=1000 (pi). Named volumes are owned by
# container root (uid=0), which keep-id maps to a sub-uid the pi user cannot
# write to.
PI_SESSION="${PI_SESSION:-default}"
PI_DATA_DIR="${PI_DATA_DIR:-${HOME}/.local/share/pi-code-data/${PI_SESSION}}"
mkdir -p "${PI_DATA_DIR}"

# ── Run ──────────────────────────────────────────────────────────────────────

# Shared read-only mounts from the host's ~/.pi that are not session-specific.
EXTRA_VOLUMES=()
HOST_MODELS="${HOME}/.pi/agent/models.json"
if [[ -f "${HOST_MODELS}" ]]; then
  EXTRA_VOLUMES+=(--volume "${HOST_MODELS}:/home/pi/.pi/agent/models.json:ro")
fi

exec podman run \
    --rm -it \
    --userns=keep-id:uid=1000,gid=1000 \
    --volume "${WORKSPACE}:/workspace:rw" \
    --volume "${APP_REPO}:/workspace/app:rw" \
    --volume "${ALLOY_REPO}:/workspace/alloy-connect:ro" \
    --volume "${PI_DATA_DIR}:/home/pi/.pi:rw" \
    "${EXTRA_VOLUMES[@]+"${EXTRA_VOLUMES[@]}"}" \
    --workdir /workspace \
    --env "TERM=${TERM:-xterm-256color}" \
    --env "COLORTERM=${COLORTERM:-truecolor}" \
    --env "CONTEXT=${CONTEXT:-}" \
    "${IMAGE}" \
    "$@"