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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Unified GDC Crash Cart, Emergency Recovery, & Subnet Diagnostics CLI.

Commands:
  snippet      Display the emergency root SSH activation block for remote console
  scan-subnet  Perform parallel ICMP and TCP probing to discover crashed nodes
  recover-tpm  Unlock LUKS via TPM, chroot into target OS, and rebuild initramfs

Run '$(basename "$0") <command> --help' for detailed options on any command.
EOF
    exit "${1:-0}"
}

# ==============================================================================
# SUBCOMMAND: snippet
# ==============================================================================
cmd_snippet() {
    local password="gdc-password-123"

    snippet_usage() {
        cat <<EOF
Usage: $(basename "$0") snippet [OPTIONS]

Outputs the emergency configuration commands to paste into a physical console
or BMC/KVM when an ISO does not boot fully or SSH is unreachable.

Options:
  --password <PASS>  Temporary root password (default: ${password})
  -h, --help         Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --password)
                password="$2"
                shift 2
                ;;
            -h|--help)
                snippet_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for snippet" >&2
                snippet_usage 1
                ;;
        esac
    done

    cat <<EOF
==============================================================================
GDC BOOTLOADER CRASH CART CONFIGURATION BLOCK
  -- Use this when the ISO does not boot fully BEFORE cloud-init starts --
==============================================================================
Copy and paste the following block directly into the remote root console to enable password-based SSH:

echo "root:${password}" | chpasswd
mkdir -p /etc/ssh/sshd_config.d
echo "PermitRootLogin yes" > /etc/ssh/sshd_config.d/99-root-ssh.conf
echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config.d/99-root-ssh.conf
systemctl restart ssh || systemctl restart sshd

==============================================================================
EOF
}

# ==============================================================================
# SUBCOMMAND: scan-subnet
# ==============================================================================
cmd_scan_subnet() {
    local scanner_py="${SCRIPT_DIR}/crash-cart-scan-subnet.py"
    if [[ ! -f "${scanner_py}" ]]; then
        echo "Error: Subnet scanner module '${scanner_py}' not found." >&2
        exit 1
    fi
    python3 "${scanner_py}" "$@"
}

# ==============================================================================
# SUBCOMMAND: recover-tpm
# ==============================================================================
cmd_recover_tpm() {
    tpm_usage() {
        cat <<EOF
Usage: sudo $(basename "$0") recover-tpm

Unlocks the encrypted system disk via Motherboard TPM 2.0, chroots into the
target OS, configures initramfs cryptsetup hooks, and rebuilds boot ramdisks.
Must be executed as root from a Live CD recovery environment on the target node.

Options:
  -h, --help  Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                tpm_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for recover-tpm" >&2
                tpm_usage 1
                ;;
        esac
    done

    if [[ $EUID -ne 0 ]]; then
        echo "[ERROR] This recovery command must be executed as root." >&2
        echo "        Please run: sudo $(basename "$0") recover-tpm" >&2
        exit 1
    fi

    echo "=============================================================================="
    echo "GDC TPM 2.0 CRYPTO BOOT UNSEAL RECOVERY TOOL"
    echo "=============================================================================="

    echo "[1/6] Scanning for the encrypted system partition..."
    local luks_dev=""
    for dev in $(blkid -o device -t TYPE=crypto_LUKS); do
        if cryptsetup luksDump "${dev}" 2>/dev/null | grep -q "UUID"; then
            luks_dev="${dev}"
            break
        fi
    done

    if [[ -z "${luks_dev}" ]]; then
        echo "[ERROR] Could not automatically locate any crypto_LUKS partition." >&2
        echo "        Available block devices:" >&2
        lsblk
        exit 1
    fi
    echo "Found GDC Encrypted LUKS partition at: ${luks_dev}"

    echo "[2/6] Unlocking LUKS partition via Motherboard hardware TPM 2.0..."
    if ! systemctl is-active --quiet systemd-cryptsetup@crypt-system; then
        echo "Attaching crypt-system via systemd-cryptsetup daemon..."
        if ! /lib/systemd/systemd-cryptsetup attach crypt-system "${luks_dev}" none tpm2-device=auto 2>/dev/null; then
            echo "[ERROR] Failed to automatically unlock partition using TPM 2.0 chip." >&2
            echo "        Attempting manual cryptsetup unlock..." >&2
            if ! cryptsetup luksOpen "${luks_dev}" crypt-system; then
                echo "[ERROR] Manual unlock failed. Cannot proceed with recovery." >&2
                exit 1
            fi
        fi
    else
        echo "LUKS partition 'crypt-system' is already unlocked."
    fi

    echo "[3/6] Activating LVM volume groups..."
    vgchange -ay vg_system || true

    cleanup_mounts() {
        echo "Cleaning up mountpoints..."
        for dir in run sys proc dev boot/efi boot; do
            umount -l "/mnt/recovery/${dir}" 2>/dev/null || true
        done
        umount -l /mnt/recovery 2>/dev/null || true
        rmdir /mnt/recovery 2>/dev/null || true
    }
    trap cleanup_mounts EXIT

    echo "[4/6] Mounting target filesystems..."
    mkdir -p /mnt/recovery

    if [[ -b "/dev/vg_system/lv_root" ]]; then
        mount /dev/vg_system/lv_root /mnt/recovery
    else
        echo "[ERROR] Could not find root logical volume /dev/vg_system/lv_root." >&2
        exit 1
    fi

    local parent_disk
    parent_disk=$(lsblk -no pkname "${luks_dev}")
    local boot_part=""
    if [[ -b "/dev/${parent_disk}p3" ]]; then
        boot_part="/dev/${parent_disk}p3"
    elif [[ -b "/dev/${parent_disk}3" ]]; then
        boot_part="/dev/${parent_disk}3"
    fi

    if [[ -n "${boot_part}" ]]; then
        echo "Mounting boot partition ${boot_part} to /mnt/recovery/boot..."
        mount "${boot_part}" /mnt/recovery/boot
    else
        echo "[WARNING] Could not determine boot partition automatically. Proceeding anyway..."
    fi

    local efi_part=""
    if [[ -b "/dev/${parent_disk}p2" ]]; then
        efi_part="/dev/${parent_disk}p2"
    elif [[ -b "/dev/${parent_disk}2" ]]; then
        efi_part="/dev/${parent_disk}2"
    fi

    if [[ -n "${efi_part}" && -d "/sys/firmware/efi" ]]; then
        echo "Mounting EFI partition ${efi_part} to /mnt/recovery/boot/efi..."
        mkdir -p /mnt/recovery/boot/efi
        mount "${efi_part}" /mnt/recovery/boot/efi || true
    fi

    echo "[5/6] Binding system runtimes for chroot..."
    for dir in dev proc sys run; do
        mount --bind "/${dir}" "/mnt/recovery/${dir}"
    done

    echo "[6/6] Executing system repairs inside target environment..."
    chroot /mnt/recovery /usr/bin/env bash -c '
        echo "--- INSIDE TARGET OS CHROOT ---"
        set -ex
        mv /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null || true
        cat /run/systemd/resolve/resolv.conf > /etc/resolv.conf 2>/dev/null || echo "nameserver 8.8.8.8" > /etc/resolv.conf
        apt-get update || true
        apt-get install -y cryptsetup cryptsetup-initramfs
        update-initramfs -u -k all
        mv /etc/resolv.conf.bak /etc/resolv.conf 2>/dev/null || true
        echo "--- TARGET OS CHROOT UPDATES COMPLETE ---"
    '

    echo "=============================================================================="
    echo "[SUCCESS] Recovery complete! You can now safely reboot the machine."
    echo "          The node will successfully unseal and unlock its storage via TPM 2.0."
    echo "=============================================================================="
}

# ==============================================================================
# MAIN ROUTING
# ==============================================================================
if [[ $# -eq 0 ]]; then
    usage 1
fi

COMMAND="$1"
shift

case "${COMMAND}" in
    snippet)
        cmd_snippet "$@"
        ;;
    scan-subnet)
        cmd_scan_subnet "$@"
        ;;
    recover-tpm)
        cmd_recover_tpm "$@"
        ;;
    -h|--help|help)
        usage 0
        ;;
    *)
        echo "Error: Unknown command '${COMMAND}'" >&2
        usage 1
        ;;
esac
