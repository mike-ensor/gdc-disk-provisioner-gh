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
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!================!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "[GDC-INSTALL-FAIL] Critical Failure: ${fail_desc}" >&2
    echo "[GDC-INSTALL-FAIL] Diagnostic Details: ${error_msg}" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!================!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
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
log_goal "Scanning hardware block devices for GDC-compliant storage drives (>= 250 GiB)"

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
# Write to a guaranteed writable path first, then print or copy to final target
TMP_YAML="/tmp/autoinstall-storage.yaml"
OUTPUT_FILE="/run/autoinstall-storage.yaml"

echo "[-] Scanning GDC Bare Metal Node Storage topology..." >&2
echo "[-] Detected ${#DETECTED_DISKS[@]} physical GDC-compliant block device(s)." >&2

# Open output configuration stream
exec 3> "${TMP_YAML}"

cat <<EOF >&3
# Generated dynamically by GDC GDC-SPEC-002-SEQ storage orchestrator
# Topology: ${NUM_DISKS} physical disk(s) detected
storage:
  layout:
    name: direct
  config:
EOF

if [[ ${NUM_DISKS} -eq 1 ]]; then
    # ==========================================================================
    # SINGLE DISK TOPOLOGY (250GB+ Single NVMe/SSD)
    # ==========================================================================
    # To prevent disk exhaustion, we scale down Gitea, Nexus, and Local-Disk
    # to guarantee they fit within a tight 250GB boundary.
    DISK_1="${SORTED_DISKS[0]}"
    log_goal "Activating SINGLE-DISK GDC LVM storage configuration on /dev/${DISK_1}"
    echo "[-] Activating SINGLE-DISK GDC Topology on /dev/${DISK_1}..." >&2

    cat <<EOF >&3
    - {type: disk, id: disk-system, path: /dev/${DISK_1}}
    - {type: partition, id: partition-efi, device: disk-system, size: 1GiB, flag: bios_grub}
    - {type: partition, id: partition-boot, device: disk-system, size: 2GiB}
    - {type: partition, id: partition-lvm, device: disk-system, size: -1}
    - {type: format, id: format-efi, volume: partition-efi, fstype: fat32}
    - {type: format, id: format-boot, volume: partition-boot, fstype: ext4}
    - {type: mount, id: mount-efi, volume: format-efi, path: /boot/efi}
    - {type: mount, id: mount-boot, volume: format-boot, path: /boot}
    - {type: dm_crypt, id: crypt-system, volume: partition-lvm, key: "temporary_bootstrap_key_to_be_enrolled_to_tpm"}
    - {type: lvm_volgroup, id: vg-system, name: vg_system, devices: [crypt-system]}
    
    # Scaled Logical Volumes for Single Disk (Total requested: ~210 GiB out of 232 GiB actual)
    - {type: lvm_partition, id: lv-root, volgroup: vg-system, name: lv_root, size: 15GiB}
    - {type: lvm_partition, id: lv-var, volgroup: vg-system, name: lv_var, size: 15GiB}
    - {type: lvm_partition, id: lv-varlog, volgroup: vg-system, name: lv_var_log, size: 15GiB}
    - {type: lvm_partition, id: lv-metrics, volgroup: vg-system, name: lv_var_opt_metrics, size: 10GiB}
    - {type: lvm_partition, id: lv-containerd, volgroup: vg-system, name: lv_containerd, size: 30GiB}
    - {type: lvm_partition, id: lv-etcd, volgroup: vg-system, name: lv_etcd, size: 20GiB}
    - {type: lvm_partition, id: lv-etcd-events, volgroup: vg-system, name: lv_etcd_events, size: 5GiB}
    - {type: lvm_partition, id: lv-gitea, volgroup: vg-system, name: lv_gitea, size: 15GiB}
    - {type: lvm_partition, id: lv-nexus, volgroup: vg-system, name: lv_nexus, size: 60GiB}
    - {type: lvm_partition, id: lv-localdisk, volgroup: vg-system, name: lv_local_disk, size: 25GiB}
    - {type: lvm_partition, id: lv-sds, volgroup: vg-system, name: lv_sds, size: -1} # Remainder for SDS
EOF

else
    # ==========================================================================
    # DUAL DISK TOPOLOGY (2x NVMe/SSD, e.g. Disk A [250G] and Disk B [500G])
    # ==========================================================================
    # Separation of Concerns:
    # - Disk 1 (Smaller) is dedicated to OS and active Kubernetes runtime etcd/CRI IOPS.
    # - Disk 2 (Larger) is dedicated to heavy storage blocks (/customer/local-disk and /customer/sds).
    DISK_1="${SORTED_DISKS[0]}"
    DISK_2="${SORTED_DISKS[1]}"
    log_goal "Activating DUAL-DISK GDC LVM performance configuration (System on /dev/${DISK_1}, Data on /dev/${DISK_2})"
    echo "[-] Activating DUAL-DISK GDC Performance Topology..." >&2
    echo "[-] System Drive (Disk 1):  /dev/${DISK_1}" >&2
    echo "[-] Data Drive (Disk 2):    /dev/${DISK_2}" >&2

    cat <<EOF >&3
    # --- Physical Drives ---
    - {type: disk, id: disk-system, path: /dev/${DISK_1}}
    - {type: disk, id: disk-data, path: /dev/${DISK_2}}
    
    # --- Disk 1 System Partitioning (EFI, Boot, and Core OS Services) ---
    - {type: partition, id: partition-efi, device: disk-system, size: 1GiB, flag: bios_grub}
    - {type: partition, id: partition-boot, device: disk-system, size: 2GiB}
    - {type: partition, id: partition-lvm-sys, device: disk-system, size: -1}
    - {type: format, id: format-efi, volume: partition-efi, fstype: fat32}
    - {type: format, id: format-boot, volume: partition-boot, fstype: ext4}
    - {type: mount, id: mount-efi, volume: format-efi, path: /boot/efi}
    - {type: mount, id: mount-boot, volume: format-boot, path: /boot}
    - {type: dm_crypt, id: crypt-system, volume: partition-lvm-sys, key: "temporary_bootstrap_key_to_be_enrolled_to_tpm"}
    - {type: lvm_volgroup, id: vg-system, name: vg_system, devices: [crypt-system]}

    # OS Logical Volumes on Disk 1 (Fits cleanly on 250G drive)
    - {type: lvm_partition, id: lv-root, volgroup: vg-system, name: lv_root, size: 20GiB}
    - {type: lvm_partition, id: lv-var, volgroup: vg-system, name: lv_var, size: 20GiB}
    - {type: lvm_partition, id: lv-varlog, volgroup: vg-system, name: lv_var_log, size: 15GiB}
    - {type: lvm_partition, id: lv-metrics, volgroup: vg-system, name: lv_var_opt_metrics, size: 10GiB}
    - {type: lvm_partition, id: lv-containerd, volgroup: vg-system, name: lv_containerd, size: 30GiB}
    - {type: lvm_partition, id: lv-etcd, volgroup: vg-system, name: lv_etcd, size: 20GiB}
    - {type: lvm_partition, id: lv-etcd-events, volgroup: vg-system, name: lv_etcd_events, size: 5GiB}
    - {type: lvm_partition, id: lv-gitea, volgroup: vg-system, name: lv_gitea, size: 20GiB}
    - {type: lvm_partition, id: lv-nexus, volgroup: vg-system, name: lv_nexus, size: -1} # Consumes remaining System disk for cache/bins (~100 GiB)

    # --- Disk 2 Data Partitioning (LUKS + Dedicated Data VG) ---
    - {type: partition, id: partition-lvm-data, device: disk-data, size: -1}
    - {type: dm_crypt, id: crypt-data, volume: partition-lvm-data, key: "temporary_bootstrap_key_to_be_enrolled_to_tpm"}
    - {type: lvm_volgroup, id: vg-data, name: vg_data, devices: [crypt-data]}
    
    # Data Logical Volumes on Disk 2
    - {type: lvm_partition, id: lv-localdisk, volgroup: vg-data, name: lv_local_disk, size: 100GiB}
    - {type: lvm_partition, id: lv-sds, volgroup: vg-data, name: lv_sds, size: -1} # Remainder of Disk 2 goes to SDS backend!
EOF
fi

# ==============================================================================
# 3. Formatting & Mounting Actions
# ==============================================================================
cat <<EOF >&3
    
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
EOF

if [[ ${NUM_DISKS} -eq 1 ]]; then
    cat <<EOF >&3
    - {type: format, id: fmt-localdisk, volume: lv-localdisk, fstype: xfs}
    - {type: format, id: fmt-sds, volume: lv-sds, fstype: xfs}
EOF
else
    cat <<EOF >&3
    - {type: format, id: fmt-localdisk, volume: lv-localdisk, fstype: xfs}
    - {type: format, id: fmt-sds, volume: lv-sds, fstype: xfs}
EOF
fi

cat <<EOF >&3

    # --- Mounting Actions ---
    - {type: mount, id: mnt-root, volume: fmt-root, path: /}
    - {type: mount, id: mnt-var, volume: fmt-var, path: /var, options: "defaults,noatime"}
    - {type: mount, id: mnt-varlog, volume: fmt-varlog, path: /var/log, options: "defaults,noatime"}
    - {type: mount, id: mnt-metrics, volume: fmt-metrics, path: /var/opt/buffered-metrics, options: "defaults,noatime"}
    - {type: mount, id: mnt-containerd, volume: fmt-containerd, path: /var/lib/containerd, options: "defaults,noatime,prjquota"}
    - {type: mount, id: mnt-etcd, volume: fmt-etcd, path: /var/lib/etcd, options: "noatime,nodiratime,commit=1"}
    - {type: mount, id: mnt-etcd-events, volume: fmt-etcd-events, path: /var/lib/etcd-events, options: "noatime,nodiratime,commit=1"}
    - {type: mount, id: mnt-gitea, volume: fmt-gitea, path: /var/lib/gitea, options: "defaults,noatime"}
    - {type: mount, id: mnt-nexus, volume: fmt-nexus, path: /var/lib/nexus, options: "defaults,noatime"}
    - {type: mount, id: mnt-localdisk, volume: fmt-localdisk, path: /customer/local-disk, options: "defaults,noatime,prjquota"}
    - {type: mount, id: mnt-sds, volume: fmt-sds, path: /customer/sds, options: "defaults,noatime"}
EOF

# Close streams
exec 3>&-

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
