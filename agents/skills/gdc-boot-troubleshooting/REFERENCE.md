# GDC Boot & LUKS Troubleshooting Reference Guide

This guide compiles advanced troubleshooting workflows, manual command lines, and recovery procedures for systems stuck at bootup, in a GRUB shell, or failing to decrypt/unseal storage via hardware TPM 2.0.

---

## 1. Advanced GRUB Shell Commands

When a node drops into a `grub>` command prompt, it means the GRUB bootloader successfully executed from the EFI System Partition (ESP), but it could not read the subsequent filesystem configuration (e.g. `grub.cfg`) to load the kernel and initramfs.

### 1.1 Disk & Partition Map Discovery
```grub
grub> ls
(hd0) (hd0,gpt1) (hd0,gpt2) (hd0,gpt3)
```
*   `gpt1`: Usually the EFI System Partition (FAT32).
*   `gpt2`: Boot partition `/boot` (Ext4).
*   `gpt3`: Encrypted GDC system partition (LUKS).

### 1.2 Inspect Partition Contents
Search for the kernel image (`vmlinuz`) and system configuration:
```grub
grub> ls (hd0,gpt2)/
config-6.8.0-100-generic vmlinuz-6.8.0-100-generic initrd.img-6.8.0-100-generic grub/
```

If `/boot/grub/grub.cfg` exists, you can boot directly:
```grub
grub> set root=(hd0,gpt2)
grub> configfile /boot/grub/grub.cfg
```

### 1.3 Manual Linux Booting Command-line
If GRUB cannot parse `grub.cfg`, run these manual loading commands:
```grub
grub> set root=(hd0,gpt2)
grub> linux /vmlinuz-6.8.0-100-generic root=/dev/mapper/vg_system-lv_root console=tty1 console=ttyS0,115200 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp video=efifb:1280x1024
grub> initrd /initrd.img-6.8.0-100-generic
grub> boot
```

---

## 2. Live CD Chroot Recovery Runbook

If the target OS fails to boot due to broken initramfs, missing cryptsetup packages, or failed TPM unsealing, you must boot the machine using the GDC Live CD/ISO and perform a chroot repair.

### 2.1 Automated Recovery Utility
Run the built-in GDC recovery utility to auto-mount, decrypt, and rebuild target initramfs:
```bash
sudo ./bin/local/gdc-crash-cart.sh recover-tpm
```

### 2.2 Manual Recovery Step-by-Step
If the automated script fails, execute these commands from the Live CD shell:

#### Step 1: Open the LUKS Partition
Locate and open the encrypted block device:
```bash
# Locate crypto partitions
sudo blkid -t TYPE=crypto_LUKS

# Manually open the container
sudo cryptsetup luksOpen /dev/nvme0n1p3 crypt-system
```

#### Step 2: Activate Volume Groups & Mount Root
```bash
sudo vgchange -ay vg_system
sudo mkdir -p /mnt/recovery
sudo mount /dev/vg_system/lv_root /mnt/recovery
```

#### Step 3: Mount Boot & EFI Partitions
```bash
# Mount /boot (usually p2)
sudo mount /dev/nvme0n1p2 /mnt/recovery/boot

# Mount EFI ESP (usually p1)
sudo mount /dev/nvme0n1p1 /mnt/recovery/boot/efi
```

#### Step 4: Bind Mount Runtime Virtual Filesystems
```bash
for dir in dev proc sys run; do
    sudo mount --bind "/${dir}" "/mnt/recovery/${dir}"
done
```

#### Step 5: Chroot and Rebuild Initramfs
Enter the target OS namespace and run the rebuild:
```bash
sudo chroot /mnt/recovery /usr/bin/env bash -c '
    set -ex
    # Ensure package repositories / local caches are available
    apt-get update || true
    
    # Ensure correct encryption packages are installed
    apt-get install -y cryptsetup cryptsetup-initramfs
    
    # Update initramfs for all kernels
    update-initramfs -u -k all
'
```

#### Step 6: Clean Up and Reboot
```bash
sudo umount -l /mnt/recovery/boot/efi || true
sudo umount -l /mnt/recovery/boot || true
for dir in run sys proc dev; do
    sudo umount -l "/mnt/recovery/${dir}" || true
done
sudo umount -l /mnt/recovery
sudo vgchange -an vg_system
sudo cryptsetup luksClose crypt-system
sudo reboot
```

---

## 3. TPM 2.0 Unsealing & Kernel Blacklists

### 3.1 Resolving Zen 4 / AMD Platform Boot Locks
Many modern AMD CPU architectures feature integrated firmware TPM (fTPM) and Cryptographic Coprocessor (CCP) security subsystems that fail on early-stage Linux kernel interrupts. This results in completely silent black-screen freezes at boot.

*   **Symptoms:** Node hangs after partition enumeration, or logs end abruptly after `clocksource: Switched to clocksource tsc`.
*   **Fix:** Ensure the following arguments exist in `/etc/default/grub` under `GRUB_CMDLINE_LINUX_DEFAULT`:
    *   `tpm_tis.interrupts=0` – Bypasses buggy hardware ACPI interrupt lines, forcing safe polling mode.
    *   `modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp` – Disables the AMD PSP / Cryptographic Coprocessor driver, preventing concurrent bus write locks.

To update persistently:
```bash
# Inside chroot or target OS:
sudo nano /etc/default/grub
# Adjust GRUB_CMDLINE_LINUX_DEFAULT
sudo update-grub
```

### 3.2 Verifying TPM 2.0 Device Status
Once booted, verify the TPM chip state:
```bash
# Check if TPM device exists
ls -l /dev/tpm*

# Test systemd tpm2 unseal tool capability
systemd-cryptenroll --tpm2-device=list
```
