#!/usr/bin/env bash

# ==============================================================================
# GDC Rapid-Feedback Local Playbook Sync & Run Tool
# ==============================================================================
# Syncs your local `src/ansible` folder directly to the active QEMU VM over SSH
# and executes `ansible-playbook` on the target guest instantly.
# This gives you a 3-second rapid development feedback loop!
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

SSH_KEY_PATH="${PROJECT_ROOT}/test/test-keys/id_ed25519"
SSH_PORT=2222
TARGET_HOST="127.0.0.1"

# Automatically find whether we should connect as gdc-admin or temporary-installer
TARGET_USER="gdc-admin"

echo "=============================================================================="
echo "GDC Playbook Sync & Run Tool"
echo "=============================================================================="

# 1. Preflight checks
if ! nc -z "${TARGET_HOST}" "${SSH_PORT}" &>/dev/null; then
    echo "[!] Error: No active SSH socket detected on localhost:${SSH_PORT}." >&2
    echo "    Make sure you have booted your QEMU test VM first!" >&2
    exit 1
fi

if [[ ! -f "${SSH_KEY_PATH}" ]]; then
    echo "[!] Error: SSH key not found at ${SSH_KEY_PATH}." >&2
    exit 1
fi

SSH_OPTS="-p ${SSH_PORT} -i ${SSH_KEY_PATH} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5"

# Detect which user is active/authorized (fallback to temporary-installer if gdc-admin is not yet created)
if ! ssh ${SSH_OPTS} gdc-admin@127.0.0.1 "echo '[x] Connected as gdc-admin'" &>/dev/null; then
    if ssh ${SSH_OPTS} temporary-installer@127.0.0.1 "echo '[x] Connected as temporary-installer'" &>/dev/null; then
        TARGET_USER="temporary-installer"
    else
        echo "[!] Error: Unable to authenticate via SSH key using either gdc-admin or temporary-installer." >&2
        exit 1
    fi
fi

echo "[-] Target User:  ${TARGET_USER}"
echo "[-] Syncing local 'src/ansible/' to guest /tmp/ansible/..."

# 2. Sync files over SSH
# Clean target destination directory first to ensure we don't carry deleted/dead files
ssh ${SSH_OPTS} "${TARGET_USER}@${TARGET_HOST}" "rm -rf /tmp/ansible && mkdir -p /tmp/ansible"

# Copy local src/ansible/ directory recursively
scp -r -P "${SSH_PORT}" -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "${PROJECT_ROOT}/src/ansible/"* "${TARGET_USER}@${TARGET_HOST}:/tmp/ansible/"

echo "[x] Sync completed successfully."
echo "[-] Executing playbook on the guest..."

# 3. Execute playbook locally inside VM with any additional parameters passed
set +e
ssh -t -p "${SSH_PORT}" -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 "${TARGET_USER}@${TARGET_HOST}" \
    "sudo ansible-playbook -i localhost, -c local /tmp/ansible/local.yml ${*:-}"
EXIT_CODE=$?
set -e

echo "=============================================================================="
if [[ ${EXIT_CODE} -eq 0 ]]; then
    echo "[+] SUCCESS: Playbook execution completed cleanly inside the VM!"
else
    echo "[!] FAILURE: Playbook failed with exit code: ${EXIT_CODE}" >&2
fi
echo "=============================================================================="
exit ${EXIT_CODE}
