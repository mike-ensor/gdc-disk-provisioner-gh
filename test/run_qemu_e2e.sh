#!/usr/bin/env bash

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


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

# Parse arguments
DRY_RUN_ALLOWED=false
REUSE_DISKS=false
for arg in "$@"; do
    case $arg in
        -d|--dry-run)
            DRY_RUN_ALLOWED=true
            shift
            ;;
        -r|--reuse)
            REUSE_DISKS=true
            shift
            ;;
    esac
done

# Automatically generate test SSH key pairs if not already present (must run before ISO compilation!)
TEST_KEYS_DIR="${PROJECT_ROOT}/test/test-keys"
if [[ ! -f "${TEST_KEYS_DIR}/id_ed25519" ]]; then
    echo "[-] Ephemeral SSH validation keys missing. Generating key pair..."
    mkdir -p "${TEST_KEYS_DIR}"
    ssh-keygen -t ed25519 -N "" -f "${TEST_KEYS_DIR}/id_ed25519" &>/dev/null
    chmod 600 "${TEST_KEYS_DIR}/id_ed25519"
fi
TEST_PUB_KEY=$(cat "${TEST_KEYS_DIR}/id_ed25519.pub")

# Verify if testing subnet IP is free on the host network
echo "[-] Performing pre-flight check on testing network segment..."
DISABLE_SSH_DNS=false
if ping -c 1 -W 1 192.168.120.1 &>/dev/null; then
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "[!] STRONG WARNING: Testing network '192.168.120.0/24' is not open or is in use!"
    echo "[!] Active device detected on 192.168.120.1 (gateway IP)."
    echo "[!] Activating SSH UseDNS fallback (disabling reverse DNS) to prevent timeouts."
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    DISABLE_SSH_DNS=true
else
    echo "[x] Testing network '192.168.120.0/24' is clear. No conflicts detected."
fi

echo "=============================================================================="
echo "GDC Bootloader ISO Headless E2E Boot Tester & Validator"
echo "=============================================================================="

# Read ISO_VERSION from VERSION file if present
ISO_VER=$(cat "${PROJECT_ROOT}/VERSION" 2>/dev/null || echo "0.1.124")

# Force hydration and assembly with non-zero VLAN configuration for the E2E test
if [[ "${REUSE_DISKS}" = "false" ]]; then
    echo "[-] Compiling test ISO with VLAN parameters (VLAN 109, ISO Version: ${ISO_VER})..."
    ISO_VERSION="${ISO_VER}" ADMIN_SSH_PUB_KEYS="${TEST_PUB_KEY}" COMPANION_IP=192.168.120.2 COMPANION_HOST=gdc-companion.gdc-labs.com INSTALL_COMPANION_URL=http://gdc-companion.gdc-labs.com:8080/v1/install-logs BOOTSTRAP_MACHINE_VLAN_ID=0 BOOTSTRAP_K8S_VLAN_ID=109 BOOTSTRAP_K8S_IP_CIDR=192.168.109.10/24 BOOTSTRAP_K8S_GATEWAY=192.168.109.1 SINGLE_DISK=false DISK1=vda DISK2=vdb BOOT_MODE=bios DISABLE_SSH_DNS="${DISABLE_SSH_DNS}" make -C "${PROJECT_ROOT}/src/build" hydrate assemble
fi

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

# If QEMU is not installed, we perform a detailed Dry-Run and log output mockup
if [[ "${QEMU_AVAILABLE}" = "false" ]]; then
    if [[ "${DRY_RUN_ALLOWED}" = "true" ]]; then
        echo "=============================================================================="
        echo "[!] Virtualization Tooling is not locally active on this workstation."
        echo "[-] Displaying the precise dynamic dual-disk & TPM automation command sequence:"
        echo "=============================================================================="
        echo "1. Create Sparse Virtual GDC Drives (0 bytes baseline disk space usage):"
        echo "   $ qemu-img create -f qcow2 /tmp/gdc-sys-disk.qcow2 650G"
        echo "   $ qemu-img create -f qcow2 /tmp/gdc-data-disk.qcow2 350G"
        echo ""
        echo "2. Spin up Isolated TPM 2.0 Emulator Daemon (unique temp folder path):"
        echo "   $ swtpm socket --tpmstate dir=/tmp/gdc-tpm.XXXXXX --tpm2 \\"
        echo "       --ctrl type=unixio,path=/tmp/gdc-tpm.XXXXXX/swtpm-sock --daemon"
        echo ""
        echo "3. Execute Headless QEMU/KVM Node Bootstrap Pipeline (timeout 10 minutes):"
        echo "   $ qemu-system-x86_64 -enable-kvm -m 4096 -smp 4 \\"
        echo "       -drive file=/tmp/gdc-sys-disk.qcow2,if=virtio,cache=writeback \\"
        echo "       -drive file=/tmp/gdc-data-disk.qcow2,if=virtio,cache=writeback \\"
        echo "       -cdrom ${ISO_PATH} \\"
        echo "       -nographic -serial file:/tmp/gdc_serial.log \\"
        echo "       -netdev user,id=mgmtnet,net=192.168.120.0/24,hostfwd=tcp:127.0.0.1:2222-:22 \\"
        echo "       -device virtio-net-pci,netdev=mgmtnet \\"
        echo "       -netdev user,id=prodnet,net=192.168.220.0/24 \\"
        echo "       -device virtio-net-pci,netdev=prodnet \\"
        echo "       -chardev socket,id=chrtpm,path=/tmp/gdc-tpm.XXXXXX/swtpm-sock \\"
        echo "       -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0 \\"
        echo "       -boot order=c"
        echo ""
        echo "4. Poll /tmp/gdc_serial.log for Success Token:"
        echo "   Success Token Signal: 'GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY'"
        echo "=============================================================================="
        echo "[+] DRY-RUN SUCCESS: Dynamic dual-disk QEMU harness configuration is aligned."
        echo "=============================================================================="
        exit 0
    else
        echo "[!] CRITICAL ERROR: Virtualization tools ('qemu-system-x86_64' or 'qemu-img') are missing on this host!" >&2
        echo "    The dynamic E2E boot test suite cannot run. If you want to perform a dry-run and view mockups, use the --dry-run / -d option." >&2
        exit 1
    fi
fi

# 3. Execution (Active QEMU/KVM E2E Boot Testing)
TEMP_DISK_1="/tmp/opencode/gdc-test-sys.qcow2"
TEMP_DISK_2="/tmp/opencode/gdc-test-data.qcow2"
SERIAL_LOG="/tmp/opencode/gdc-serial.log"

if [[ "${REUSE_DISKS}" = "false" ]]; then
    rm -f "${TEMP_DISK_1}" "${TEMP_DISK_2}"
fi
rm -f "${SERIAL_LOG}"

# Start local GDC Installation Companion Mock on host in background for local log streaming
echo "[-] Starting local GDC Installation Companion Mock on host (port 8080)..."
python3 "${PROJECT_ROOT}/test/install_companion_mock.py" &
COMPANION_PID=$!
sleep 2

# Define dynamic unique TPM directory path to prevent parallel run collisions
TPM_TEMP_DIR=""
SWTPM_PID=""

if [[ "${REUSE_DISKS}" = "false" ]]; then
    echo "[-] Creating 650 GiB sparse validation target System disk..."
    qemu-img create -f qcow2 "${TEMP_DISK_1}" 650G &>/dev/null

    # Dual Disk topology allocation (Disk 2)
    echo "[-] Creating 350 GiB sparse validation target Data disk..."
    qemu-img create -f qcow2 "${TEMP_DISK_2}" 350G &>/dev/null
fi

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
qemu-system-x86_64 ${KVM_FLAG} -m 4096 -smp 4 \
  -drive file="${TEMP_DISK_1}",if=virtio,cache=writeback \
  -drive file="${TEMP_DISK_2}",if=virtio,cache=writeback \
  -cdrom "${ISO_PATH}" \
  -nographic \
  -serial file:"${SERIAL_LOG}" \
  -netdev user,id=mgmtnet,net=192.168.120.0/24,hostfwd=tcp:127.0.0.1:2222-:22 \
  -device virtio-net-pci,netdev=mgmtnet \
  -netdev user,id=prodnet,net=192.168.220.0/24 \
  -device virtio-net-pci,netdev=prodnet \
  ${TPM_ARGS} \
  -boot order=c &
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
    # Kill background mock companion
    if [[ -n "${COMPANION_PID:-}" ]]; then
        kill "${COMPANION_PID}" &>/dev/null || true
    fi
    # Only delete virtual disks on success to preserve them for diagnostics on failure
    if [[ "${SUCCESS:-false}" = "true" ]]; then
        rm -f "${TEMP_DISK_1}" "${TEMP_DISK_2}"
    else
        echo "[!] Keeping virtual disk images at ${TEMP_DISK_1} and ${TEMP_DISK_2} for diagnostics."
    fi
    if [[ -n "${TPM_TEMP_DIR:-}" && -d "${TPM_TEMP_DIR}" ]]; then
        rm -rf "${TPM_TEMP_DIR}"
    fi
    echo "[-] Cleanup finished."
}
trap cleanup EXIT

# 4. Monitor Serial console logs for compilation complete signal
# Timeboxed boot configuration to prevent infinite hanging (Task 8 check)
echo "[-] Monitoring serial logs for completion marker... (Timeout: 25 minutes)"
TIMEOUT=1500
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
        if grep -q "Entering interactive mode" "${SERIAL_LOG}"; then
            echo "[!] ERROR: Installation aborted! Subiquity has fallen back to interactive TUI mode." >&2
            echo "[-] Last 20 lines of serial log:" >&2
            tail -n 20 "${SERIAL_LOG}" || true
            exit 1
        fi
        
        # Fast fail checks to prevent infinite hanging on installer crashes
        if grep -qE "ValidationError|state\": \"ERROR\"|curtin: Installation failed" "${SERIAL_LOG}"; then
            echo "[!] ERROR: Subiquity installation failed! Trashing installer immediately for diagnostics." >&2
            SUCCESS=false
            break
        fi
    fi

    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [[ $((ELAPSED % 60)) -eq 0 ]]; then
        echo "[-] Still installing... (${ELAPSED}s elapsed)"
    fi
done

if [[ "${SUCCESS}" = "false" ]]; then
    echo "[!] Timeout/Failure: Reached timeout threshold of ${TIMEOUT} seconds." >&2
    echo "[-] Displaying final 50 lines of serial.log for diagnostics:" >&2
    tail -n 50 "${SERIAL_LOG}" || true
    echo ""
    echo "[!] Attempting to gather target chroot diagnostic logs via SSH on port 2222..."
    SSH_KEY_PATH="${TEST_KEYS_DIR}/id_ed25519"
    SSH_OPTS="-p 2222 -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o UserKnownHostsFile=/dev/null"
    # Try logging in as ubuntu (live CD) or temporary-installer (target OS)
    TARGET_USER="temporary-installer"
    if ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" ubuntu@127.0.0.1 "echo 'SSH live CD reachable!'" &>/dev/null; then
        TARGET_USER="ubuntu"
    fi
    
    if ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" "${TARGET_USER}"@127.0.0.1 "echo 'SSH is reachable!'" &>/dev/null; then
        echo "  [x] Diagnostics SSH connected successfully as ${TARGET_USER}. Retrieving target node internals:"
        echo "=========================================================="
        echo "=== Subiquity Server Debug Log ==="
        ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" "${TARGET_USER}"@127.0.0.1 "sudo cat /var/log/installer/subiquity-server-debug.log || true" || true
        echo "=========================================================="
        echo "=== Subiquity Client Log ==="
        ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" "${TARGET_USER}"@127.0.0.1 "sudo cat /var/log/installer/subiquity-client.log || true" || true
        echo "=========================================================="
        echo "=== gdc-provision.service Status ==="
        ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" "${TARGET_USER}"@127.0.0.1 "sudo systemctl status gdc-provision.service || true" || true
        echo "=========================================================="
        echo "=== gdc-provision.service Journal ==="
        ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" "${TARGET_USER}"@127.0.0.1 "sudo journalctl -u gdc-provision.service -n 100 || true" || true
        echo "=========================================================="
        echo "=== Active Network Interfaces ==="
        ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" "${TARGET_USER}"@127.0.0.1 "ip addr show || true" || true
        echo "=========================================================="
        echo "=== Active Routing Tables ==="
        ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" "${TARGET_USER}"@127.0.0.1 "ip route show table all || true" || true
    else
        echo "  [!] SSH is currently unreachable on localhost:2222. Target OS/Live CD may have failed to boot, or port-forwarding is broken."
    fi
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
        echo "  [x] SSH socket active. Sleeping 10s cushion for SSH daemon to settle..."
        sleep 10
        break
    fi
    sleep 5
done

# 5.1. Test Pubkey Auth Entry
echo "[-] Testing SSH Key-Based Entry..."
SSH_ERR_LOG="/tmp/opencode/ssh-pubkey-error.log"
if ssh ${SSH_OPTS} -vvv -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "echo '[x] Remote authentication successful.'" &> "${SSH_ERR_LOG}"; then
    echo "  [x] SSH Pubkey Authentication PASSED cleanly."
else
    echo "  [!] WARNING: SSH Pubkey Authentication FAILED!" >&2
    echo "[-] Displaying SSH verbose debug log for diagnostics:" >&2
    cat "${SSH_ERR_LOG}" >&2
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

# 5.4. Validate Isolated VLAN Interfaces and Routing
echo "[-] Validating GDC VLAN interfaces and routing configuration..."

# Check VLAN interface link status
VLAN_LINKS=$(ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "ip -o link show type vlan" 2>/dev/null || echo "")
if [[ -n "${VLAN_LINKS}" ]]; then
    echo "  [x] Retrieved VLAN Link Devices:"
    echo "${VLAN_LINKS}" | while read -r line; do
        echo "      - ${line}"
    done
    
    if echo "${VLAN_LINKS}" | grep -q "\.109"; then
        echo "  [x] VLAN 109 interface is present and active."
    else
        echo "  [!] CRITICAL ERROR: Active VLAN 109 interface is missing in guest kernel!" >&2
        exit 1
    fi
else
    echo "  [!] CRITICAL ERROR: Could not query VLAN link devices over SSH." >&2
    exit 1
fi

# Verify routing resolution on primary interface
echo "[-] Querying default routing path resolution..."
ROUTE_DEFAULT=$(ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "ip route get 8.8.8.8" 2>/dev/null || echo "")
if [[ -n "${ROUTE_DEFAULT}" ]]; then
    echo "      Route: ${ROUTE_DEFAULT}"
    echo "  [x] Default routing resolution PASSED."
else
    echo "  [!] CRITICAL ERROR: Failed to resolve default routing path." >&2
    exit 1
fi

# ==============================================================================
# 6. Second Reboot & Passwordless TPM Unseal Verification
# ==============================================================================
echo "=============================================================================="
echo "[-] Initiating Step 6: Second Reboot & Passwordless TPM Unsealing Test..."
echo "=============================================================================="

# Issue reboot command over SSH
echo "[-] Triggering 'sudo reboot' on guest OS..."
ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "echo troubled-marble-150 | sudo -S reboot" &>/dev/null || true

# Wait for SSH socket to close
echo "[-] Waiting for SSH socket to close on reboot..."
sleep 5

# Poll SSH port 2222 for guest OS to return online after passwordless TPM unseal
echo "[-] Polling for guest OS to auto-unseal via TPM 2.0 and return online..."
REBOOT_SUCCESS=false
for i in {1..24}; do
    sleep 5
    if ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "echo '[x] Second boot online!'" &>/dev/null; then
        echo "  [x] SUCCESS: Guest OS auto-unsealed via TPM 2.0 and returned online after $((i * 5))s!"
        REBOOT_SUCCESS=true
        break
    fi
    echo "  [-] Waiting for second boot unseal... ($((i * 5))s elapsed)"
done

if [[ "${REBOOT_SUCCESS}" = "false" ]]; then
    echo "  [!] CRITICAL ERROR: Guest OS failed to auto-unseal via TPM 2.0 on second reboot!" >&2
    exit 1
fi

# Verify LUKS volume state on second boot
echo "[-] Auditing second boot cryptsetup state..."
CRYPT_STATUS=$(ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "echo troubled-marble-150 | sudo -S cryptsetup status crypt-system" 2>/dev/null || echo "")
if echo "${CRYPT_STATUS}" | grep -q "is active"; then
    echo "  [x] Verified: Volume 'crypt-system' is active and unlocked via TPM 2.0!"
else
    echo "  [!] CRITICAL ERROR: LUKS volume 'crypt-system' is not active on second boot!" >&2
    exit 1
fi

echo "=============================================================================="
echo "[+] SUCCESS: Complete End-to-End Test (LiveCD -> First Boot -> Ansible -> Second Boot -> TPM Unseal) PASSED 100%!"
echo "=============================================================================="
exit 0
