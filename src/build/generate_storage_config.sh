#!/usr/bin/env bash

# ==============================================================================
# GDC Dynamic Multi-Disk Partitioning & Sizing Script
# ==============================================================================
# Scans block devices, detects 1 vs 2 disk topologies, scales logical volumes
# dynamically to prevent disk exhaustion, and optimizes performance by splitting
# OS / etcd workloads from heavy SDS workloads when 2 disks are present.
# ==============================================================================

set -euo pipefail

# ==============================================================================
# Smart Logging, Diagnostics, and Error-Trapping Helpers
# ==============================================================================
log_goal() {
    local goal_desc="$1"
    echo "=============================================================================="
    echo "[GDC-INSTALL-GOAL] Starting Task: ${goal_desc}"
    echo "=============================================================================="
    logger -t gdc-provisioner "[GOAL] ${goal_desc}"
}

# shellcheck disable=SC2317
log_fail() {
    local fail_desc="$1"
    local error_msg="${2:-No extra context provided}"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "[GDC-INSTALL-FAIL] Critical Failure: ${fail_desc}" >&2
    echo "[GDC-INSTALL-FAIL] Diagnostic Details: ${error_msg}" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    logger -p user.err -t gdc-provisioner "[FAILURE] ${fail_desc} - Details: ${error_msg}"
}

# shellcheck disable=SC2317
failure_handler() {
    local last_line="$1"
    local last_code="$2"
    log_fail "The disk partitioning script crashed unexpectedly!" "Exit Code: ${last_code} on line ${last_line}"
}
trap 'failure_handler ${LINENO} $?' ERR

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-d" ]]; then
    DRY_RUN=true
fi

# ==============================================================================
# 1. Disk Detection & Sorting Heuristics
# ==============================================================================
log_goal "Scanning hardware block devices for GDC-compliant storage drives (>= 250 G)"

# Sort disks ascending by size so the smaller disk is always allocated to System
RAW_DISKS=$(lsblk -dno NAME,TYPE,SIZE | grep disk | cut -d' ' -f1)
DETECTED_DISKS=()

for disk in ${RAW_DISKS}; do
    # Skip loop and installer optical devices (sr0/cdrom)
    if [[ "${disk}" =~ ^loop || "${disk}" =~ ^sr ]]; then
        continue
    fi
    
    # Get sector size of block device
    if [[ -f "/sys/block/${disk}/size" ]]; then
        SECTORS=$(cat "/sys/block/${disk}/size")
        # 240 GB = 503316480 sectors (512-byte blocks)
        if [[ ${SECTORS} -ge 503316480 ]]; then
            DETECTED_DISKS+=("${disk}")
        fi
    fi
done

# Sort disks ascending by size (using bash/sort)
if [[ ${#DETECTED_DISKS[@]} -gt 0 ]]; then
    # Sort them ascending by sector count
    # shellcheck disable=SC2207
    SORTED_DISKS=($(for d in "${DETECTED_DISKS[@]}"; do
        echo "$(cat "/sys/block/${d}/size") ${d}"
    done | sort -n | awk '{print $2}'))
else
    # Mock fallback for dev environments/containers without physical blocks
    SORTED_DISKS=("nvme0n1" "nvme1n1")
fi

NUM_DISKS=${#SORTED_DISKS[@]}
if [[ ${NUM_DISKS} -gt 2 ]]; then
    # Limit our topology scope to maximum 2 primary disks
    NUM_DISKS=2
fi

# ==============================================================================
# 2. Output Configurations Generator (YAML Generation)
# ==============================================================================
# Detect active boot mode (UEFI vs Legacy BIOS)
BOOT_MODE="bios"
if [[ -d "/sys/firmware/efi" ]]; then
    BOOT_MODE="uefi"
fi
echo "[-] Detected active system boot mode: ${BOOT_MODE}" >&2

# Write to a guaranteed writable path first, then print or copy to final target
TMP_YAML="/tmp/autoinstall-storage.yaml"
OUTPUT_FILE="/run/autoinstall-storage.yaml"

echo "[-] Scanning GDC Bare Metal Node Storage topology..." >&2
echo "[-] Detected ${#DETECTED_DISKS[@]} physical GDC-compliant block device(s)." >&2

# Locate storage templates directory
TEMPLATE_DIR="/cdrom/custom-data/storage"
if [[ ! -d "${TEMPLATE_DIR}" ]]; then
    # Local fallback for development/dry-run environments
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    TEMPLATE_DIR="${SCRIPT_DIR}/templates/storage"
fi

if [[ ! -d "${TEMPLATE_DIR}" ]]; then
    log_fail "Storage templates directory not found!" "Checked /cdrom/custom-data/storage and local templates/storage"
    exit 1
fi

# Select the appropriate template file based on boot mode and disk count
TOPOLOGY="single"
if [[ ${NUM_DISKS} -eq 2 ]]; then
    TOPOLOGY="dual"
fi

TEMPLATE_FILE="${TEMPLATE_DIR}/storage_config_${BOOT_MODE}_${TOPOLOGY}.yaml"

if [[ ! -f "${TEMPLATE_FILE}" ]]; then
    log_fail "Matching storage template file not found!" "File: ${TEMPLATE_FILE}"
    exit 1
fi

echo "[-] Loading storage template: ${TEMPLATE_FILE}..." >&2

# Read template, perform placeholder substitutions, and write to output stream
DISK_1="${SORTED_DISKS[0]:-vda}"
DISK_2="${SORTED_DISKS[1]:-vdb}"

# We format the output under the storage: key
echo "storage:" > "${TMP_YAML}"
sed -e "s/\${DISK_1}/${DISK_1}/g" -e "s/\${DISK_2}/${DISK_2}/g" "${TEMPLATE_FILE}" >> "${TMP_YAML}"

# Append standard formatting and mounting actions
cat <<EOF >> "${TMP_YAML}"
    
    # --- Formatting Actions ---
    - {type: format, id: fmt-root, volume: lv-root, fstype: ext4}
    - {type: format, id: fmt-var, volume: lv-var, fstype: ext4}
    - {type: format, id: fmt-varlog, volume: lv-varlog, fstype: ext4}
    - {type: format, id: fmt-metrics, volume: lv-metrics, fstype: ext4}
    - {type: format, id: fmt-containerd, volume: lv-containerd, fstype: xfs}
    - {type: format, id: fmt-etcd, volume: lv-etcd, fstype: ext4}
    - {type: format, id: fmt-etcd-events, volume: lv-etcd-events, fstype: ext4}
    - {type: format, id: fmt-gitea, volume: lv-gitea, fstype: ext4}
    - {type: format, id: fmt-nexus, volume: lv-nexus, fstype: ext4}
    - {type: format, id: fmt-localdisk, volume: lv-localdisk, fstype: xfs}
    - {type: format, id: fmt-sds, volume: lv-sds, fstype: xfs}

    # --- Mounting Actions ---
    - {type: mount, id: mnt-root, device: fmt-root, path: /}
    - {type: mount, id: mnt-var, device: fmt-var, path: /var, options: "defaults,noatime"}
    - {type: mount, id: mnt-varlog, device: fmt-varlog, path: /var/log, options: "defaults,noatime"}
    - {type: mount, id: mnt-metrics, device: fmt-metrics, path: /var/opt/buffered-metrics, options: "defaults,noatime"}
    - {type: mount, id: mnt-containerd, device: fmt-containerd, path: /var/lib/containerd, options: "defaults,noatime,prjquota"}
    - {type: mount, id: mnt-etcd, device: fmt-etcd, path: /var/lib/etcd, options: "noatime,nodiratime,commit=1"}
    - {type: mount, id: mnt-etcd-events, device: fmt-etcd-events, path: /var/lib/etcd-events, options: "noatime,nodiratime,commit=1"}
    - {type: mount, id: mnt-gitea, device: fmt-gitea, path: /var/lib/gitea, options: "defaults,noatime"}
    - {type: mount, id: mnt-nexus, device: fmt-nexus, path: /var/lib/nexus, options: "defaults,noatime"}
    - {type: mount, id: mnt-localdisk, device: fmt-localdisk, path: /customer/local-disk, options: "defaults,noatime,prjquota"}
    - {type: mount, id: mnt-sds, device: fmt-sds, path: /customer/sds, options: "defaults,noatime"}
    
    # --- Bootloader Action ---
    - {type: grub, id: grub-installer, device: disk-system}
EOF

if [[ "${DRY_RUN}" = "true" ]]; then
    cat "${TMP_YAML}"
    rm -f "${TMP_YAML}"
else
    mkdir -p "$(dirname "${OUTPUT_FILE}")"
    mv "${TMP_YAML}" "${OUTPUT_FILE}"
    echo "[-] Generated autoinstall storage configuration block in: ${OUTPUT_FILE}" >&2
fi

echo "==============================================================================" >&2
exit 0
