#!/usr/bin/env bash

# ==============================================================================
# GDC Rapid-Feedback Local Playbook Sync & Run Tool
# ==============================================================================
# Syncs your local `src/ansible` folder directly to the target node over SSH
# and executes `ansible-playbook` on the target guest instantly.
# Works with both local QEMU sandboxes and remote physical nodes!
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Resolved target parameters (defaults to QEMU port forward; can be overridden via env)
TARGET_HOST="${GDC_TARGET_HOST:-127.0.0.1}"
SSH_PORT="${GDC_SSH_PORT:-2222}"
GDC_PASS="${GDC_PASSWORD:-}"

SSH_KEY_PATH="${PROJECT_ROOT}/test/test-keys/id_ed25519"
TARGET_USER="gdc-admin"

echo "=============================================================================="
echo "GDC Playbook Sync & Run Tool"
echo "=============================================================================="
echo "[-] Target Host:  ${TARGET_HOST}:${SSH_PORT}"

# 1. Preflight checks
if ! nc -z "${TARGET_HOST}" "${SSH_PORT}" &>/dev/null; then
    echo "[!] Error: No active SSH socket detected on ${TARGET_HOST}:${SSH_PORT}." >&2
    echo "    Make sure the target machine or QEMU test VM is booted and reachable!" >&2
    exit 1
fi

# Build SSH options
SSH_BASE_OPTS="-p ${SSH_PORT} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5"
if [[ -n "${GDC_PASS}" ]]; then
    if ! command -v sshpass &>/dev/null; then
        echo "[!] Error: 'sshpass' is required when GDC_PASSWORD is specified but is not installed." >&2
        exit 1
    fi
    SSH_CMD_PREFIX="sshpass -p ${GDC_PASS} ssh ${SSH_BASE_OPTS}"
    SCP_CMD_PREFIX="sshpass -p ${GDC_PASS} scp -P ${SSH_PORT} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
else
    if [[ ! -f "${SSH_KEY_PATH}" ]]; then
        echo "[!] Error: SSH key not found at ${SSH_KEY_PATH}." >&2
        exit 1
    fi
    SSH_CMD_PREFIX="ssh ${SSH_BASE_OPTS} -i ${SSH_KEY_PATH}"
    SCP_CMD_PREFIX="scp -P ${SSH_PORT} -i ${SSH_KEY_PATH} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
fi

# 2. Detect which user is active/authorized (gdc-admin or temporary-installer)
set +e
if ${SSH_CMD_PREFIX} gdc-admin@${TARGET_HOST} "echo '[x] Connected as gdc-admin'" &>/dev/null; then
    TARGET_USER="gdc-admin"
elif ${SSH_CMD_PREFIX} temporary-installer@${TARGET_HOST} "echo '[x] Connected as temporary-installer'" &>/dev/null; then
    TARGET_USER="temporary-installer"
else
    echo "[!] Error: Unable to authenticate via SSH using either gdc-admin or temporary-installer." >&2
    exit 1
fi
set -e

echo "[-] Active User:  ${TARGET_USER}"

# 3. Dynamic Re-Image Diagnostics & Advice
echo "[-] Running on-device state health checks..."
set +e
LUKS_KEY_EXISTS=$(${SSH_CMD_PREFIX} "${TARGET_USER}@${TARGET_HOST}" "sudo test -f /etc/keys/temp_key.key" &>/dev/null; echo $?)
GDC_ADMIN_EXISTS=$(${SSH_CMD_PREFIX} "${TARGET_USER}@${TARGET_HOST}" "sudo test -f /etc/sudoers.d/gdc-admin" &>/dev/null; echo $?)
SOURCES_DEACTIVATED=$(${SSH_CMD_PREFIX} "${TARGET_USER}@${TARGET_HOST}" "sudo test -f /etc/apt/sources.list.bak" &>/dev/null; echo $?)
set -e

REIMAGE_RECOMMENDED=false
REIMAGE_REASONS=()

if [[ ${LUKS_KEY_EXISTS} -ne 0 ]]; then
    REIMAGE_RECOMMENDED=true
    REIMAGE_REASONS+=("The temporary master-key passcode '/etc/keys/temp_key.key' is MISSING (indicates Stage 7 has run and successfully sealed LUKS keys to the TPM).")
fi
if [[ ${GDC_ADMIN_EXISTS} -eq 0 ]]; then
    REIMAGE_REASONS+=("The administrative account 'gdc-admin' has already been provisioned and configured on the node.")
fi
if [[ ${SOURCES_DEACTIVATED} -eq 0 ]]; then
    REIMAGE_REASONS+=("Standard public APT repositories have already been deactivated and locked exclusively to local loopback mirrors.")
fi

if [[ "${REIMAGE_RECOMMENDED}" = "true" ]]; then
    echo -e "\n=============================================================================="
    echo "💡 [DIAGNOSTIC ADVICE] RE-IMAGE OF THE NODE IS HIGHLY RECOMMENDED!"
    echo "------------------------------------------------------------------------------"
    echo "This device is already in a fully-provisioned, hardened 'Ready-Linux' state:"
    for reason in "${REIMAGE_REASONS[@]}"; do
        echo "   -> ${reason}"
    done
    echo ""
    echo "To test a clean first-boot deployment loop from a raw baseline OS state,"
    echo "it is highly beneficial to RE-IMAGE the device via PXE/Bootimus now."
    echo "=============================================================================="
    GDC_FORCE="${GDC_FORCE:-false}"
    if [[ "${GDC_FORCE}" = "true" ]]; then
        echo "[-] Bypassing re-image recommendation prompt (GDC_FORCE=true)..."
    else
        read -p "Do you still want to force push and execute on this active device? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "[-] Execution aborted by operator recommendation."
            exit 0
        fi
    fi
else
    echo "[x] Clean slate baseline state verified. No re-image required."
fi

# 4. Sync files over SSH
echo "[-] Syncing local 'src/ansible/' to guest /tmp/ansible/..."
${SSH_CMD_PREFIX} "${TARGET_USER}@${TARGET_HOST}" "rm -rf /tmp/ansible && mkdir -p /tmp/ansible"
${SCP_CMD_PREFIX} -r "${PROJECT_ROOT}/src/ansible/"* "${TARGET_USER}@${TARGET_HOST}:/tmp/ansible/"
echo "[x] Sync completed successfully."

# 5. Execute playbook locally inside VM with any additional parameters passed
echo "[-] Executing playbook on the guest..."
set +e
if [[ -n "${GDC_PASS}" ]]; then
    ${SSH_CMD_PREFIX} "${TARGET_USER}@${TARGET_HOST}" \
        "echo '${GDC_PASS}' | sudo -S ansible-playbook -i localhost, -c local --extra-vars 'ansible_become_password=${GDC_PASS}' /tmp/ansible/local.yml ${*:-}"
else
    ${SSH_CMD_PREFIX} "${TARGET_USER}@${TARGET_HOST}" \
        "sudo ansible-playbook -i localhost, -c local /tmp/ansible/local.yml ${*:-}"
fi
EXIT_CODE=$?
set -e

echo "=============================================================================="
if [[ ${EXIT_CODE} -eq 0 ]]; then
    echo "[+] SUCCESS: Playbook execution completed cleanly inside the target node!"
else
    echo "[!] FAILURE: Playbook failed with exit code: ${EXIT_CODE}" >&2
fi
echo "=============================================================================="
exit ${EXIT_CODE}
