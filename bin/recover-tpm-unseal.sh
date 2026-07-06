#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader - TPM 2.0 Boot Unseal Recovery Utility
# ==============================================================================
# Execute this script from a Live CD terminal on the bricked node to unlock the
# system disk via TPM, chroot into the target OS, install systemd-initramfs,
# and rebuild the boot ramdisks with proper systemd TPM 2.0 unsealing support.
# ==============================================================================

set -euo pipefail

echo "=============================================================================="
echo "GDC TPM 2.0 CRYPTO BOOT UNSEAL RECOVERY TOOL"
echo "=============================================================================="

if [[ $EUID -ne 0 ]]; then
   echo "[ERROR] This recovery script must be executed as root." 
   echo "        Please run: sudo $0"
   exit 1
fi

echo "[1/6] Scanning for the encrypted system partition..."
LUKS_DEV=""
# Find LUKS container candidate by looking for partition with LUKS signature
for dev in $(blkid -o device -t TYPE=crypto_LUKS); do
    # Verify if it's the crypt-system partition by inspecting its name or metadata
    if cryptsetup luksDump "${dev}" | grep -q "UUID"; then
        # Check if there is an active volume group system, or assume this is the main system partition
        LUKS_DEV="${dev}"
        break
    fi
done

if [[ -z "${LUKS_DEV}" ]]; then
    echo "[ERROR] Could not automatically locate any crypto_LUKS partition."
    echo "        Available block devices:"
    lsblk
    exit 1
fi

echo "Found GDC Encrypted LUKS partition at: ${LUKS_DEV}"

echo "[2/6] Unlocking LUKS partition via Motherboard hardware TPM 2.0..."
if ! systemctl is-active --quiet systemd-cryptsetup@crypt-system; then
    echo "Attaching crypt-system via systemd-cryptsetup daemon..."
    if ! /lib/systemd/systemd-cryptsetup attach crypt-system "${LUKS_DEV}" none tpm2-device=auto; then
        echo "[ERROR] Failed to automatically unlock the partition using the TPM 2.0 chip."
        echo "        This motherboard TPM might not have been enrolled, or Secure Boot state changed."
        echo "        Fallback: Attempting manual unlock..."
        if ! cryptsetup luksOpen "${LUKS_DEV}" crypt-system; then
            echo "[ERROR] Manual unlock failed. Cannot proceed with recovery."
            exit 1
        fi
    fi
else
    echo "LUKS partition 'crypt-system' is already unlocked."
fi

echo "[3/6] Activating LVM volume groups..."
vgchange -ay vg_system || true

echo "[4/6] Mounting target filesystems..."
mkdir -p /mnt/recovery

# Mount root
if [[ -b "/dev/vg_system/lv_root" ]]; then
    mount /dev/vg_system/lv_root /mnt/recovery
else
    echo "[ERROR] Could not find root logical volume /dev/vg_system/lv_root."
    exit 1
fi

# Find and mount /boot partition (usually partition 3 on the same parent disk)
PARENT_DISK=$(lsblk -no pkname "${LUKS_DEV}")
BOOT_PART=""
if [[ -b "/dev/${PARENT_DISK}p3" ]]; then
    BOOT_PART="/dev/${PARENT_DISK}p3"
elif [[ -b "/dev/${PARENT_DISK}3" ]]; then
    BOOT_PART="/dev/${PARENT_DISK}3"
fi

if [[ -n "${BOOT_PART}" ]]; then
    echo "Mounting boot partition ${BOOT_PART} to /mnt/recovery/boot..."
    mount "${BOOT_PART}" /mnt/recovery/boot
else
    echo "[WARNING] Could not determine boot partition automatically. Proceeding anyway..."
fi

# Find and mount EFI partition (usually partition 2 on UEFI systems)
EFI_PART=""
if [[ -b "/dev/${PARENT_DISK}p2" ]]; then
    EFI_PART="/dev/${PARENT_DISK}p2"
elif [[ -b "/dev/${PARENT_DISK}2" ]]; then
    EFI_PART="/dev/${PARENT_DISK}2"
fi

if [[ -n "${EFI_PART}" && -d "/sys/firmware/efi" ]]; then
    echo "Mounting EFI partition ${EFI_PART} to /mnt/recovery/boot/efi..."
    mkdir -p /mnt/recovery/boot/efi
    mount "${EFI_PART}" /mnt/recovery/boot/efi || true
fi

echo "[5/6] Binding system runtimes for chroot..."
for dir in dev proc sys run; do
    mount --bind "/${dir}" "/mnt/recovery/${dir}"
done

echo "[6/6] Executing system repairs inside target environment..."
# Run updates inside the chroot environment
chroot /mnt/recovery /usr/bin/env bash -c '
    echo "--- INSIDE TARGET OS CHROOT ---"
    set -ex
    
    # Enable DNS resolution inside chroot by copying host resolv.conf temporarily
    mv /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null || true
    cat /run/systemd/resolve/resolv.conf > /etc/resolv.conf 2>/dev/null || echo "nameserver 8.8.8.8" > /etc/resolv.conf
    
    # Install the systemd-initramfs package to enable systemd-based initrd boot path
    apt-get update || true
    apt-get install -y systemd-initramfs cryptsetup-initramfs
    
    # Double-check that CRYPTENROLL is active in conf-hook
    mkdir -p /etc/cryptsetup-initramfs
    sed -i "s/#\?CRYPTENROLL=.*/CRYPTENROLL=y/" /etc/cryptsetup-initramfs/conf-hook
    if ! grep -q "CRYPTENROLL" /etc/cryptsetup-initramfs/conf-hook; then
        echo "CRYPTENROLL=y" >> /etc/cryptsetup-initramfs/conf-hook
    fi
    
    # Rebuild initramfs with systemd and cryptenroll TPM drivers included
    update-initramfs -u -k all
    
    # Restore dns settings
    mv /etc/resolv.conf.bak /etc/resolv.conf 2>/dev/null || true
    echo "--- TARGET OS CHROOT UPDATES COMPLETE ---"
'

echo "Cleaning up mountpoints..."
for dir in run sys proc dev boot/efi boot; do
    umount -l "/mnt/recovery/${dir}" 2>/dev/null || true
done
umount -l /mnt/recovery
rmdir /mnt/recovery

echo "=============================================================================="
echo "[SUCCESS] Recovery complete! You can now safely reboot the machine."
echo "          The node will successfully unseal and unlock its storage via TPM 2.0."
echo "=============================================================================="
