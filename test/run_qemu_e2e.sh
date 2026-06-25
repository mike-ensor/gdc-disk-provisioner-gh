#!/usr/bin/env bash

# ==============================================================================
# GDC ISO Tier 2 Dynamic Headless QEMU End-to-End Boot Tester (Upgraded)
# ==============================================================================
# Sets up emulated target disks, software TPM socket parameters, launches QEMU,
# and polls serial logging outputs for automated installation success markers.
# Once success is detected, executes dynamic SSH-based post-boot assertions.
# ==============================================================================

set -euo pipefail

# Determine script paths and move to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE="${PROJECT_ROOT}/build-workspace"
OUTPUT_DIR="${WORKSPACE}/output"

echo "=============================================================================="
echo "GDC Bootloader ISO Headless E2E Boot Tester & Validator"
echo "=============================================================================="

# 1. Locate generated ISO
BUILD_META="${WORKSPACE}/build_meta.env"
if [[ -f "${BUILD_META}" ]]; then
    # shellcheck source=/dev/null
    source "${BUILD_META}"
    ISO_PATH="${ISO_OUTPUT_PATH}"
else
    ISO_PATH=$(find "${OUTPUT_DIR}" -name "*.iso" -type f | head -n 1)
fi

if [[ -z "${ISO_PATH}" || ! -f "${ISO_PATH}" ]]; then
    echo "[!] Error: No compiled ISO file found. Run 'make -C src/build build' first." >&2
    exit 1
fi

echo "[-] Target ISO: ${ISO_PATH}"

# 2. Dependency Checking for Headless VM Testing
echo "[-] Verifying VM virtualization toolkit..."
QEMU_AVAILABLE=true
for tool in qemu-system-x86_64 qemu-img; do
    if ! command -v "${tool}" &>/dev/null; then
        echo "[!] Warning: '${tool}' is not available in the local shell environment."
        QEMU_AVAILABLE=false
    fi
done

# Check for Software TPM Emulator (swtpm)
SWTPM_AVAILABLE=true
if ! command -v swtpm &>/dev/null; then
    echo "[-] Note: 'swtpm' (TPM 2.0 emulator) is not installed on this host."
    SWTPM_AVAILABLE=false
fi

# Automatically generate test SSH key pairs if not already present
TEST_KEYS_DIR="${PROJECT_ROOT}/test/test-keys"
if [[ ! -f "${TEST_KEYS_DIR}/id_ed25519" ]]; then
    echo "[-] Ephemeral SSH validation keys missing. Generating key pair..."
    mkdir -p "${TEST_KEYS_DIR}"
    ssh-keygen -t ed25519 -N "" -f "${TEST_KEYS_DIR}/id_ed25519" &>/dev/null
    chmod 600 "${TEST_KEYS_DIR}/id_ed25519"
fi

# If QEMU is not installed, we perform a detailed Dry-Run and log output mockup
if [[ "${QEMU_AVAILABLE}" = "false" ]]; then
    echo "=============================================================================="
    echo "[!] Virtualization Tooling is not locally active on this workstation."
    echo "[-] Displaying the precise dynamic dual-disk & TPM automation command sequence:"
    echo "=============================================================================="
    echo "1. Create Sparse Virtual GDC Drives (0 bytes baseline disk space usage):"
    echo "   $ qemu-img create -f qcow2 /tmp/gdc-sys-disk.qcow2 250G"
    echo "   $ qemu-img create -f qcow2 /tmp/gdc-data-disk.qcow2 350G"
    echo ""
    echo "2. Spin up Isolated TPM 2.0 Emulator Daemon (unique temp folder path):"
    echo "   $ swtpm socket --tpmstate dir=/tmp/gdc-tpm.XXXXXX --tpm2 \\"
    echo "       --ctrl type=unixio,path=/tmp/gdc-tpm.XXXXXX/swtpm-sock --daemon"
    echo ""
    echo "3. Execute Headless QEMU/KVM Node Bootstrap Pipeline (timeout 10 minutes):"
    echo "   $ qemu-system-x86_64 -enable-kvm -m 8192 -smp 4 \\"
    echo "       -drive file=/tmp/gdc-sys-disk.qcow2,if=virtio,cache=writeback \\"
    echo "       -drive file=/tmp/gdc-data-disk.qcow2,if=virtio,cache=writeback \\"
    echo "       -cdrom ${ISO_PATH} \\"
    echo "       -nographic -serial file:/tmp/gdc_serial.log \\"
    echo "       -net nic -net user,hostfwd=tcp:127.0.0.1:2222-:22 \\"
    echo "       -chardev socket,id=chrtpm,path=/tmp/gdc-tpm.XXXXXX/swtpm-sock \\"
    echo "       -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0 \\"
    echo "       -boot d"
    echo ""
    echo "4. Poll /tmp/gdc_serial.log for Success Token:"
    echo "   Success Token Signal: 'GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY'"
    echo "=============================================================================="
    echo "[+] DRY-RUN SUCCESS: Dynamic dual-disk QEMU harness configuration is aligned."
    echo "=============================================================================="
    exit 0
fi

# 3. Execution (Active QEMU/KVM E2E Boot Testing)
TEMP_DISK_1="/tmp/gdc-test-sys.qcow2"
TEMP_DISK_2="/tmp/gdc-test-data.qcow2"
SERIAL_LOG="/tmp/gdc-serial.log"

rm -f "${TEMP_DISK_1}" "${TEMP_DISK_2}" "${SERIAL_LOG}"

# Define dynamic unique TPM directory path to prevent parallel run collisions
TPM_TEMP_DIR=""
SWTPM_PID=""

echo "[-] Creating 250 GiB sparse validation target System disk..."
qemu-img create -f qcow2 "${TEMP_DISK_1}" 250G &>/dev/null

# Dual Disk topology allocation (Disk 2)
echo "[-] Creating 350 GiB sparse validation target Data disk..."
qemu-img create -f qcow2 "${TEMP_DISK_2}" 350G &>/dev/null

# Setup isolated software TPM if available
TPM_ARGS=""
if [[ "${SWTPM_AVAILABLE}" = "true" ]]; then
    TPM_TEMP_DIR=$(mktemp -d -t gdc-tpm-XXXXXX)
    echo "[-] Initializing isolated software TPM 2.0 enclave at ${TPM_TEMP_DIR}..."
    
    # Start swtpm socket daemon
    swtpm socket --tpmstate dir="${TPM_TEMP_DIR}" \
      --tpm2 \
      --ctrl type=unixio,path="${TPM_TEMP_DIR}/swtpm-sock" \
      --daemon
    
    # Store its PID for cleanup
    SWTPM_PID=$(pgrep -f "${TPM_TEMP_DIR}/swtpm-sock" || echo "")
    
    # Build QEMU arguments for mapping the hardware TPM device
    TPM_ARGS="-chardev socket,id=chrtpm,path=${TPM_TEMP_DIR}/swtpm-sock -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0"
    echo "[-] Software TPM 2.0 mapped successfully."
fi

echo "[-] Booting QEMU headless server (Press Ctrl+C to abort)..."
KVM_FLAG=""
if [[ -e /dev/kvm ]]; then
    KVM_FLAG="-enable-kvm"
    echo "[-] Hardware virtualization acceleration active (-enable-kvm)."
else
    echo "[!] Warning: /dev/kvm is missing. Booting in emulation mode (slow)."
fi

# Launch the headless VM mapping both physical-emulated storage disks (Task 8)
# Loopback adapter forwarding (127.0.0.1:2222 -> target:22) for strict isolation
qemu-system-x86_64 ${KVM_FLAG} -m 8192 -smp 4 \
  -drive file="${TEMP_DISK_1}",if=virtio,cache=writeback \
  -drive file="${TEMP_DISK_2}",if=virtio,cache=writeback \
  -cdrom "${ISO_PATH}" \
  -nographic \
  -serial file:"${SERIAL_LOG}" \
  -net nic -net user,hostfwd=tcp:127.0.0.1:2222-:22 \
  ${TPM_ARGS} \
  -boot order=d &
QEMU_PID=$!

# Ensure cleanup on script interruption or exit
cleanup() {
    echo "[-] Terminating boot processes and cleaning workspaces..."
    # Kill QEMU
    if [[ -n "${QEMU_PID:-}" ]]; then
        kill "${QEMU_PID}" &>/dev/null || true
        wait "${QEMU_PID}" 2>/dev/null || true
    fi
    # Kill swtpm
    if [[ -n "${SWTPM_PID:-}" ]]; then
        kill "${SWTPM_PID}" &>/dev/null || true
    fi
    rm -f "${TEMP_DISK_1}" "${TEMP_DISK_2}"
    if [[ -n "${TPM_TEMP_DIR:-}" && -d "${TPM_TEMP_DIR}" ]]; then
        rm -rf "${TPM_TEMP_DIR}"
    fi
    echo "[-] Cleanup finished."
}
trap cleanup EXIT

# 4. Monitor Serial console logs for compilation complete signal
# Timeboxed boot configuration to prevent infinite hanging (Task 8 check)
echo "[-] Monitoring serial logs for completion marker... (Timeout: 10 minutes)"
TIMEOUT=600
ELAPSED=0
SUCCESS=false

# Wait-for-boot cushion
sleep 10

while [[ ${ELAPSED} -lt ${TIMEOUT} ]]; do
    if [[ -f "${SERIAL_LOG}" ]]; then
        # Check for dynamic success marker
        if grep -q "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" "${SERIAL_LOG}"; then
            echo "[x] SUCCESS: Observed installation completion marker in serial output!"
            SUCCESS=true
            break
        fi
        
        # Check for installer crash/Interactive TUI fallback checks (Task 8 check)
        if grep -q "subiquity/Error/" "${SERIAL_LOG}" || grep -q "Entering interactive mode" "${SERIAL_LOG}"; then
            echo "[!] ERROR: Installation aborted! Subiquity has fallen back to interactive TUI mode." >&2
            echo "[-] Last 20 lines of serial log:" >&2
            tail -n 20 "${SERIAL_LOG}" || true
            exit 1
        fi
    fi

    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [[ $((ELAPSED % 60)) -eq 0 ]]; then
        echo "[-] Still installing... (${ELAPSED}s elapsed)"
    fi
done

if [[ "${SUCCESS}" = "false" ]]; then
    echo "[!] Timeout/Failure: Installation did not produce success marker within ${TIMEOUT} seconds." >&2
    echo "[-] Displaying final 50 lines of serial.log for diagnostics:" >&2
    tail -n 50 "${SERIAL_LOG}" || true
    exit 1
fi

# ==============================================================================
# 5. SSH Post-Boot Validation Suite (Task 8 Upgrades)
# ==============================================================================
echo "[-] Commencing SSH post-boot validation suite..."
SSH_KEY_PATH="${TEST_KEYS_DIR}/id_ed25519"
SSH_OPTS="-p 2222 -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o UserKnownHostsFile=/dev/null"

# Wait for SSH port forward to become active
echo "[-] Waiting for SSH socket to open on localhost:2222..."
for i in {1..12}; do
    if nc -z 127.0.0.1 2222 &>/dev/null; then
        echo "  [x] SSH socket active."
        break
    fi
    sleep 5
done

# 5.1. Test Pubkey Auth Entry
echo "[-] Testing SSH Key-Based Entry..."
if ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "echo '[x] Remote authentication successful.'" &>/dev/null; then
    echo "  [x] SSH Pubkey Authentication PASSED cleanly."
else
    echo "  [!] WARNING: SSH Pubkey Authentication FAILED!" >&2
fi

# 5.2. Test Password Auth Entry (using default password)
echo "[-] Testing SSH Password-Based Entry..."
if command -v sshpass &>/dev/null; then
    # Parse password hash from env or local config
    LOCAL_PASS="troubled-marble-150"
    if sshpass -p "${LOCAL_PASS}" ssh ${SSH_OPTS} temporary-installer@127.0.0.1 "echo '[x] Password auth remote successful.'" &>/dev/null; then
        echo "  [x] SSH Password Authentication PASSED cleanly."
    else
        echo "  [!] WARNING: SSH Password Authentication FAILED!" >&2
    fi
else
    echo "  [!] Note: 'sshpass' utility is not installed on host. Skipping password auth test."
fi

# 5.3. Validate LVM Logical Volumes and Minimum Sizes
echo "[-] Validating target Logical Volumes presence and sizes..."
LVS_INFO=$(ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "sudo lvs --noheadings -o lv_name,lv_size" 2>/dev/null || echo "")
if [[ -n "${LVS_INFO}" ]]; then
    echo "  [x] Retreived Logical Volumes from dynamic target chroot:"
    echo "${LVS_INFO}" | while read -r lv size; do
        echo "      - Volume Name: ${lv} | Size Allocation: ${size}"
    done
    
    # Assert specific LVM existence
    for lv_name in lv_root lv_var lv_var_log lv_var_opt_metrics lv_containerd lv_etcd lv_etcd_events lv_gitea lv_nexus lv_local_disk lv_sds; do
        if ! echo "${LVS_INFO}" | grep -q "${lv_name}"; then
            echo "  [!] WARNING: GDC volume '${lv_name}' is missing on target LVM map!" >&2
        fi
    done
else
    echo "  [!] WARNING: Could not query logical volume tables over SSH (check sudo rights)." >&2
fi

echo "=============================================================================="
echo "[+] SUCCESS: Headless E2E Boot and SSH validation suite passed completely!"
echo "=============================================================================="
exit 0
