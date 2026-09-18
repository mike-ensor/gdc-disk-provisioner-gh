---
name: gdc-luks-tpm-recovery
description: Recover and repair nodes blocked by LUKS decryption failures, failed motherboard TPM 2.0 unsealing, or snap-to-host key propagation race conditions. Use when nodes fail Curtin encryption or boot unsealing.
---

# Skill: gdc-luks-tpm-recovery

## Quick Start

1. Boot into the GDC Live CD/ISO.
2. Run the automated recovery script:
   `sudo ./bin/local/gdc-crash-cart.sh recover-tpm`
3. If it fails, open the container manually:
   `sudo cryptsetup luksOpen /dev/nvme0n1p3 crypt-system`

## Workflows

### State 1: Diagnosing Temporal Race Conditions (RCA-v0.1.76)
If Curtin fails with exit code 2 on `cryptsetup open` stating `No key available with this passphrase` (as summarized in the `luks-key-failures` RCA):
1. **Identify Root Cause:** Check if the LUKS formatting key was written to a private Snap namespace `/tmp/` or `/run/` instead of `/var/log/installer/`.
2. **Timing Jitter check:** Verify if physical factors like DRAM-less SSD HMB latency, virtual IPMI CD-ROM `sr0` SCSI settle delay, or CPU governor throttling allowed a 0-byte keyfile to format a volume which then failed to open with the propagated 45-byte key.
3. **Short-Term Resolution:** Pass the key inline using Curtin's process stream pipes.
4. **Long-Term Mitigation:** Route files strictly through `/var/log/installer/` (a zero-delay host-to-snap bind mount).

### State 2: Manual Chroot Repairs
If automated recovery is blocked, execute the manual chroot sequence:
```bash
# 1. Mount encrypted layout
sudo cryptsetup luksOpen /dev/nvme0n1p3 crypt-system
sudo vgchange -ay vg_system
sudo mount /dev/vg_system/lv_root /mnt/recovery
sudo mount /dev/nvme0n1p2 /mnt/recovery/boot
sudo mount /dev/nvme0n1p1 /mnt/recovery/boot/efi

# 2. Bind mounts & enter chroot
for d in dev proc sys run; do sudo mount --bind /$d /mnt/recovery/$d; done
sudo chroot /mnt/recovery

# 3. Inside chroot: Install cryptsetup and rebuild initramfs
apt-get update && apt-get install -y cryptsetup cryptsetup-initramfs
update-initramfs -u -k all
```
