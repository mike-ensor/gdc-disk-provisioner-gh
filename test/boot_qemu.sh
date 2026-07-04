#!/usr/bin/env bash

# ==============================================================================
# GDC Interactive QEMU VM Boot Tool (Speed Up Iteration)
# ==============================================================================
# Boots the fully-installed target VM in the background and keeps it alive
# so you can run rapid-feedback playbook runs over and over in seconds.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

TEMP_DISK_1="/tmp/opencode/gdc-test-sys.qcow2"
TEMP_DISK_2="/tmp/opencode/gdc-test-data.qcow2"
SERIAL_LOG="/tmp/opencode/gdc-serial.log"

echo "=============================================================================="
echo "GDC Interactive QEMU Bootloader"
echo "=============================================================================="

# Pre-flight check: is port 2222 already occupied?
if nc -z 127.0.0.1 2222 &>/dev/null; then
    echo "[!] Error: Port 2222 is already in use. Is QEMU already running?" >&2
    exit 1
fi

if [[ ! -f "${TEMP_DISK_1}" ]]; then
    echo "[!] Error: Virtual disk ${TEMP_DISK_1} not found." >&2
    echo "    Please run the full './test/run_qemu_e2e.sh' once first to install the OS!" >&2
    exit 1
fi

# Locate GDC ISO to pass as cdrom (optional but QEMU invocation expects it)
ISO_PATH=$(find "${PROJECT_ROOT}/build-workspace/output" -name "*.iso" -type f | head -n 1 || echo "")

# Setup Software TPM
SWTPM_AVAILABLE=false
TPM_ARGS=""
if command -v swtpm &>/dev/null; then
    SWTPM_AVAILABLE=true
    TPM_TEMP_DIR=$(mktemp -d -t gdc-tpm-XXXXXX)
    echo "[-] Initializing isolated software TPM 2.0 enclave at ${TPM_TEMP_DIR}..."
    swtpm socket --tpmstate dir="${TPM_TEMP_DIR}" \
      --tpm2 \
      --ctrl type=unixio,path="${TPM_TEMP_DIR}/swtpm-sock" \
      --daemon
    TPM_ARGS="-chardev socket,id=chrtpm,path=${TPM_TEMP_DIR}/swtpm-sock -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0"
fi

KVM_FLAG=""
if [[ -e /dev/kvm ]]; then
    KVM_FLAG="-enable-kvm"
fi

echo "[-] Booting QEMU VM in background..."
qemu-system-x86_64 ${KVM_FLAG} -m 4096 -smp 4 \
  -drive file="${TEMP_DISK_1}",if=virtio,cache=writeback \
  -drive file="${TEMP_DISK_2}",if=virtio,cache=writeback \
  ${ISO_PATH:+-cdrom "$ISO_PATH"} \
  -nographic \
  -serial file:"${SERIAL_LOG}" \
  -netdev user,id=mgmtnet,net=192.168.120.0/24,hostfwd=tcp:127.0.0.1:2222-:22 \
  -device virtio-net-pci,netdev=mgmtnet \
  -netdev user,id=prodnet,net=192.168.220.0/24 \
  -device virtio-net-pci,netdev=prodnet \
  ${TPM_ARGS} \
  -boot order=c &
QEMU_PID=$!

echo "[x] QEMU booted in background with PID: ${QEMU_PID}"
echo "[-] Waiting for SSH port 2222 to open..."

# Wait for SSH port forward to become active
for i in {1..30}; do
    if nc -z 127.0.0.1 2222 &>/dev/null; then
        echo "=============================================================================="
        echo "[+] VM booted and SSH port 2222 is active!"
        echo "[-] You can now run './test/sync_and_run_ansible.sh' to execute plays."
        echo "=============================================================================="
        exit 0
    fi
    sleep 3
done

echo "[!] Timeout waiting for SSH to start." >&2
exit 1
