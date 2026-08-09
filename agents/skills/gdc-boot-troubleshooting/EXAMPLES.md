# GDC Boot & LUKS Troubleshooting Examples

This file provides real-world examples of diagnosing and resolving common boot issues using the `gdc-boot-troubleshooting` skill.

---

## Example 1: AMD Zen 4 Platform fTPM/PSP Boot Hang

### 1.1 Symptoms
The console logs end abruptly at:
```text
1.646376] tsc: Refined TSC clocksource calibration: 3293.811 MHz
1.647311] clocksource: tsc: mask: OxfEEFFFFEEFFFFFFT max_cycles: Ox2f7a?58b259, max_idle ns: 440795268702 ns
1.648020] clocksource: Switched to clocksource tsc 
```
The node is completely unresponsive, SSH is offline, and no further output appears on the terminal.

### 1.2 Root Cause
A hardware conflict occurs with the AMD Cryptographic Coprocessor (`ccp`) and ACPI interrupts on Zen 4 platforms during the transition from the initramfs to the main target OS kernel.

### 1.3 Resolution Procedure

#### Option A: Interactive GRUB Edit (To Boot Once)
1.  Reboot the node and press **`e`** on the GRUB menu to edit the default boot entry.
2.  Locate the line starting with `linux`.
3.  Append the following parameters to the end of the line:
    ```text
    tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp
    ```
4.  Press **`Ctrl+X`** or **`F10`** to boot the node.
5.  Once booted, make the parameters persistent as shown in Section 1.4 below.

#### Option B: Chroot Rebuild (From Live CD)
If you cannot edit GRUB interactively, boot into the GDC Live CD and run:
```bash
# 1. Mount disk and bind mounts
sudo cryptsetup luksOpen /dev/nvme0n1p3 crypt-system
sudo vgchange -ay vg_system
sudo mkdir -p /mnt/recovery
sudo mount /dev/vg_system/lv_root /mnt/recovery
sudo mount /dev/nvme0n1p2 /mnt/recovery/boot
sudo mount /dev/nvme0n1p1 /mnt/recovery/boot/efi
for d in dev proc sys run; do sudo mount --bind /$d /mnt/recovery/$d; done

# 2. Enter chroot and patch GRUB config
sudo chroot /mnt/recovery /usr/bin/env bash -c '
    sed -i "s/GRUB_CMDLINE_LINUX_DEFAULT=\"[^\"]*/& tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp/" /etc/default/grub
    update-grub
'
```

### 1.4 Persistent Mitigation inside Target OS
Once logged in, verify and update `/etc/default/grub`:
```bash
sudo nano /etc/default/grub
# Ensure GRUB_CMDLINE_LINUX_DEFAULT contains:
# tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp

sudo update-grub
```
This ensures the node remains 100% immune to AMD hardware deadlocks on future restarts.
