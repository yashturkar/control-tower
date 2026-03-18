#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${CONTROL_TOWER_REPO_URL:-https://github.com/yashturkar/control-tower.git}"
REPO_REF="${CONTROL_TOWER_REF:-main}"
INSTALL_BASE="${CONTROL_TOWER_INSTALL_ROOT:-${XDG_DATA_HOME:-${HOME}/.local/share}/control-tower}"
REPO_DIR="${INSTALL_BASE}/repo"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_cmd git
need_cmd python3

mkdir -p "${INSTALL_BASE}"

if [[ -d "${REPO_DIR}/.git" ]]; then
  git -C "${REPO_DIR}" fetch origin "${REPO_REF}" --depth=1
  git -C "${REPO_DIR}" checkout "${REPO_REF}"
  git -C "${REPO_DIR}" pull --ff-only origin "${REPO_REF}"
else
  rm -rf "${REPO_DIR}"
  git clone --depth=1 --branch "${REPO_REF}" "${REPO_URL}" "${REPO_DIR}"
fi

exec "${REPO_DIR}/scripts/install_tower.sh"
