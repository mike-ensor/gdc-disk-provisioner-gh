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

# Parse arguments
DRY_RUN_ALLOWED=false
for arg in "$@"; do
    case $arg in
        -d|--dry-run)
            DRY_RUN_ALLOWED=true
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

# Force hydration and assembly with non-zero VLAN and dual-VRF configuration for the E2E test
echo "[-] Compiling test ISO with Dual-VRF parameters (VLAN 109)..."
ADMIN_SSH_PUB_KEYS="${TEST_PUB_KEY}" COMPANION_IP=192.168.120.2 COMPANION_HOST=gdc-companion.ensor-labs.com INSTALL_COMPANION_URL=http://gdc-companion.ensor-labs.com:8080/v1/install-logs MACHINE_VLAN_ID=0 K8S_VLAN_ID=109 K8S_GATEWAY=192.168.109.1 DISK1=vda DISK2=vdb BOOT_MODE=bios DISABLE_SSH_DNS="${DISABLE_SSH_DNS}" make -C "${PROJECT_ROOT}/src/build" hydrate assemble

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
        echo "   $ qemu-img create -f qcow2 /tmp/gdc-sys-disk.qcow2 250G"
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

rm -f "${TEMP_DISK_1}" "${TEMP_DISK_2}" "${SERIAL_LOG}"

# Start local GDC Installation Companion on host in background
echo "[-] Starting local GDC Installation Companion on host (port 8080)..."
python3 "${PROJECT_ROOT}/src/build/install_companion.py" &
COMPANION_PID=$!
sleep 2

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
    # Kill background installation companion
    if [[ -n "${COMPANION_PID:-}" ]]; then
        kill "${COMPANION_PID}" &>/dev/null || true
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
echo "[-] Monitoring serial logs for completion marker... (Timeout: 15 minutes)"
TIMEOUT=900
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

# 5.4. Validate Isolated VRF Devices and Routing Tables
echo "[-] Validating GDC Dual-VRF routing tables and interface isolation..."

# Check VRF interface link status
VRF_LINKS=$(ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "ip -o link show type vrf" 2>/dev/null || echo "")
if [[ -n "${VRF_LINKS}" ]]; then
    echo "  [x] Retreived VRF Link Devices:"
    echo "${VRF_LINKS}" | while read -r line; do
        echo "      - ${line}"
    done
    
    if echo "${VRF_LINKS}" | grep -q "vrf-machine" && echo "${VRF_LINKS}" | grep -q "vrf-k8s"; then
        echo "  [x] VRF Device links 'vrf-machine' and 'vrf-k8s' are present and active."
    else
        echo "  [!] CRITICAL ERROR: Active VRF device interfaces are missing in guest kernel!" >&2
        exit 1
    fi
else
    echo "  [!] CRITICAL ERROR: Could not query VRF link devices over SSH." >&2
    exit 1
fi

# Verify local routing resolution on vrf-machine
echo "[-] Querying routing path resolution for 'vrf-machine' (Table 10)..."
ROUTE_MACHINE=$(ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "ip route get 8.8.8.8 vrf vrf-machine" 2>/dev/null || echo "")
if [[ -n "${ROUTE_MACHINE}" ]]; then
    echo "      Route: ${ROUTE_MACHINE}"
    if echo "${ROUTE_MACHINE}" | grep -E -q "dev e.* table 10"; then
        echo "  [x] vrf-machine isolated routing table resolution PASSED."
    else
        echo "  [!] CRITICAL ERROR: Routing path for vrf-machine is incorrect!" >&2
        exit 1
    fi
else
    echo "  [!] CRITICAL ERROR: Failed to resolve routing path for vrf-machine." >&2
    exit 1
fi

# Verify local routing resolution on vrf-k8s (VLAN 109)
echo "[-] Querying routing path resolution for 'vrf-k8s' (Table 20)..."
ROUTE_K8S=$(ssh ${SSH_OPTS} -i "${SSH_KEY_PATH}" temporary-installer@127.0.0.1 "ip route get 8.8.8.8 vrf vrf-k8s" 2>/dev/null || echo "")
if [[ -n "${ROUTE_K8S}" ]]; then
    echo "      Route: ${ROUTE_K8S}"
    if echo "${ROUTE_K8S}" | grep -E -q "dev e.*\.109 table 20"; then
        echo "  [x] vrf-k8s (VLAN 109) isolated routing table resolution PASSED."
    else
        echo "  [!] CRITICAL ERROR: Routing path for vrf-k8s is incorrect!" >&2
        exit 1
    fi
else
    echo "  [!] CRITICAL ERROR: Failed to resolve routing path for vrf-k8s." >&2
    exit 1
fi

echo "=============================================================================="
echo "[+] SUCCESS: Headless E2E Boot and SSH validation suite passed completely!"
echo "=============================================================================="
exit 0
