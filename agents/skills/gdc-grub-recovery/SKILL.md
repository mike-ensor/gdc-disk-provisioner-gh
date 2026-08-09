---
name: gdc-grub-recovery
description: Recover GDC nodes stuck in a `grub>` command-line shell or experiencing EFI boot sector corruption. Use when a node is stuck in the GRUB prompt and cannot load the kernel or grub.cfg automatically.
---

# Skill: gdc-grub-recovery

## Quick Start

Run these GRUB shell commands to manually point to the kernel and boot the node:
```grub
grub> set root=(hd0,gpt2)
grub> linux /vmlinuz-6.8.0-100-generic root=/dev/mapper/vg_system-lv_root console=ttyS0,115200 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp video=efifb:1280x1024
grub> initrd /initrd.img-6.8.0-100-generic
grub> boot
```

## Workflows

### State 1: Disk & Partition Exploration
If the node is stuck in a `grub>` shell:
1. List all detected storage devices and GPT partitions: `ls`
2. Locate the boot partition (usually `gpt2` or marked with `/boot` files):
   `ls (hd0,gpt2)/`
3. Verify if `/grub/grub.cfg` or `/boot/grub/grub.cfg` is readable.

### State 2: Manual Boot & Persistence Recovery
1. Set the GRUB root to the boot partition:
   `set root=(hd0,gpt2)`
2. If `grub.cfg` exists but wasn't loaded automatically, execute:
   `configfile /boot/grub/grub.cfg`
3. If missing or corrupt, load the kernel manually using the AMD platform safe parameters:
   ```grub
   linux /vmlinuz-xxx root=/dev/mapper/vg_system-lv_root console=tty1 console=ttyS0,115200 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp video=efifb:1280x1024
   initrd /initrd.img-xxx
   boot
   ```
4. Once booted into the target OS, persistently reinstall GRUB and regenerate config files:
   ```bash
   sudo grub-install /dev/nvme0n1
   sudo update-grub
   ```
