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
    logger -t gdc-provisioner "[GOAL] ${goal_desc}" 2>/dev/null || true
}

# shellcheck disable=SC2317
log_fail() {
    local fail_desc="$1"
    local error_msg="${2:-No extra context provided}"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "[GDC-INSTALL-FAIL] Critical Failure: ${fail_desc}" >&2
    echo "[GDC-INSTALL-FAIL] Diagnostic Details: ${error_msg}" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    logger -p user.err -t gdc-provisioner "[FAILURE] ${fail_desc} - Details: ${error_msg}" 2>/dev/null || true
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
log_goal "Scanning hardware block devices for GDC-compliant storage drives (>= 560 GiB / 600 GB)"

# Detect active installer live media disks to prevent self-targeting/corruption
INSTALLER_DISKS=()
for mnt in /cdrom /isodevice /run/live/medium /run/initramfs/cdrom /run/initramfs/live /rofs; do
    if dev=$(findmnt -e -no SOURCE "${mnt}" 2>/dev/null) && [[ -n "${dev}" ]]; then
        clean_dev="${dev%%\[*}"
        real_dev=$(readlink -f "${clean_dev}" 2>/dev/null || echo "${clean_dev}")
        if [[ -b "${real_dev}" ]]; then
            if [[ "${real_dev}" =~ loop[0-9]+ ]]; then
                back_file=$(losetup -O BACK-FILE -n "${real_dev}" 2>/dev/null || true)
                clean_back_file="${back_file% (deleted)}"
                if [[ -n "${clean_back_file}" && -f "${clean_back_file}" ]]; then
                    loop_src=$(df --output=source "${clean_back_file}" 2>/dev/null | tail -n 1 || true)
                    if [[ -n "${loop_src}" && -b "${loop_src}" ]]; then
                        loop_pk=$(lsblk -no PKNAME "${loop_src}" 2>/dev/null | head -n 1 | tr -d '[:space:]' || true)
                        INSTALLER_DISKS+=("${loop_pk:-$(basename "${loop_src}")}")
                    fi
                fi
            else
                pkname=$(lsblk -no PKNAME "${real_dev}" 2>/dev/null | head -n 1 | tr -d '[:space:]' || true)
                INSTALLER_DISKS+=("${pkname:-$(basename "${real_dev}")}")
            fi
        fi
    fi
done

# Also detect all loop backing files across the system
while read -r back_file; do
    clean_back_file="${back_file% (deleted)}"
    if [[ -n "${clean_back_file}" && -f "${clean_back_file}" ]]; then
        loop_src=$(df --output=source "${clean_back_file}" 2>/dev/null | tail -n 1 || true)
        if [[ -n "${loop_src}" && -b "${loop_src}" ]]; then
            loop_pk=$(lsblk -no PKNAME "${loop_src}" 2>/dev/null | head -n 1 | tr -d '[:space:]' || true)
            INSTALLER_DISKS+=("${loop_pk:-$(basename "${loop_src}")}")
        fi
    fi
done < <(losetup -O BACK-FILE -n 2>/dev/null || true)

# Also detect block devices with GDC installer label or iso9660 filesystem
while read -r iso_dev; do
    if [[ -n "${iso_dev}" && -b "${iso_dev}" ]]; then
        real_dev=$(readlink -f "${iso_dev}" 2>/dev/null || echo "${iso_dev}")
        pkname=$(lsblk -no PKNAME "${real_dev}" 2>/dev/null | head -n 1 | tr -d '[:space:]')
        if [[ -n "${pkname}" ]]; then
            INSTALLER_DISKS+=("${pkname}")
        else
            INSTALLER_DISKS+=("$(basename "${real_dev}")")
        fi
    fi
done < <({ blkid -L "GDC-BOOTSTRAP" 2>/dev/null; ls -1 /dev/disk/by-label/GDC-BOOTSTRAP* 2>/dev/null; blkid -t TYPE=iso9660 -o device 2>/dev/null; } || true)

# Sort disks ascending by size so the smaller disk is always allocated to System
RAW_DISKS=$(lsblk -dno NAME,TYPE | awk '$2 == "disk" {print $1}')
DETECTED_DISKS=()

for disk in ${RAW_DISKS}; do
    # Skip loop, installer optical devices (sr0/cdrom), and ram devices
    if [[ "${disk}" =~ ^loop || "${disk}" =~ ^sr || "${disk}" =~ ^ram ]]; then
        continue
    fi

    # Skip active installer live media disk (e.g. boot USB drive or ISO backing device)
    is_installer=false
    for inst_d in "${INSTALLER_DISKS[@]}"; do
        if [[ "${disk}" == "${inst_d}" ]]; then
            echo "[-] Skipping installer live media disk: /dev/${disk}" >&2
            is_installer=true
            break
        fi
    done
    if [[ "${is_installer}" == "true" ]]; then
        continue
    fi

    # Skip USB transport devices (USB flash drives, external USB enclosures) and removable media
    TRAN=$(lsblk -dno TRAN "/dev/${disk}" 2>/dev/null || true)
    SYSPATH=$(readlink -f "/sys/block/${disk}" 2>/dev/null || true)
    IS_REMOVABLE="0"
    if [[ -f "/sys/block/${disk}/removable" ]]; then
        IS_REMOVABLE=$(cat "/sys/block/${disk}/removable" 2>/dev/null || echo "0")
    else
        IS_REMOVABLE=$(lsblk -dno RM "/dev/${disk}" 2>/dev/null | tr -d '[:space:]' || echo "0")
    fi
    IS_UDEV_USB="false"
    if udevadm info --query=property --name="/dev/${disk}" 2>/dev/null | grep -q -E '^(ID_BUS=usb|ID_USB_DRIVER=)'; then
        IS_UDEV_USB="true"
    fi

    if [[ "${TRAN}" == "usb" || "${SYSPATH}" =~ [uU][sS][bB] || "${IS_REMOVABLE}" == "1" || "${IS_UDEV_USB}" == "true" ]]; then
        echo "[-] Skipping USB storage device: /dev/${disk} (TRAN=${TRAN:-none}, RM=${IS_REMOVABLE})" >&2
        continue
    fi
    
    # Get sector size of block device
    if [[ -f "/sys/block/${disk}/size" ]]; then
        SECTORS=$(cat "/sys/block/${disk}/size")
        # 560 GiB = 1174405120 sectors (512-byte blocks) to guarantee 40GB root, 100GB logs, and 300GB+ Nexus
        if [[ ${SECTORS} -ge 1174405120 ]]; then
            DETECTED_DISKS+=("${disk}")
        else
            echo "[-] Skipping undersized disk: /dev/${disk} (${SECTORS} sectors < 1174405120)" >&2
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
    - {type: mount, id: mnt-localdisk, device: fmt-localdisk, path: /customer/local-disk, options: "defaults,noatime,nofail,prjquota"}
    - {type: mount, id: mnt-sds, device: fmt-sds, path: /customer/sds, options: "defaults,noatime,nofail"}
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
