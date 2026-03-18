#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${HOME}/.local/bin"
TARGET="${INSTALL_DIR}/tower"
RUNTIME_TARGET="${INSTALL_DIR}/tower-run"

mkdir -p "${INSTALL_DIR}"

cat > "${TARGET}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${REPO_ROOT}/src\${PYTHONPATH:+:\${PYTHONPATH}}"
exec python3 -m control_tower.cli "\$@"
EOF

chmod +x "${TARGET}"

cat > "${RUNTIME_TARGET}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${REPO_ROOT}/src\${PYTHONPATH:+:\${PYTHONPATH}}"
exec python3 -m control_tower.runtime_cli "\$@"
EOF

chmod +x "${RUNTIME_TARGET}"

echo "Installed tower to ${TARGET}"
echo "Installed tower-run to ${RUNTIME_TARGET}"

case ":${PATH}:" in
  *":${INSTALL_DIR}:"*)
    ;;
  *)
    echo "Warning: ${INSTALL_DIR} is not on PATH"
    ;;
esac
