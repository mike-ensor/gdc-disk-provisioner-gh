---
name: gdc-kernel-hang-troubleshooting
description: Diagnose and bypass early-boot kernel hangs, black-screen freezes, or deadlocks on modern AMD/Zen CPU architectures. Use when serial logs end at `clocksource: Switched to clocksource tsc`.
---

# Skill: gdc-kernel-hang-troubleshooting

## Quick Start

1. Intercept the boot sequence at the GRUB menu (press `e`).
2. Append these parameters to the `linux` line:
   `tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp video=efifb:1280x1024`
3. Press `Ctrl+X` to boot.

## Workflows

### State 1: Signature Verification
Check the serial console or hypervisor/QEMU log (e.g. `build-workspace/qemu-live.log` or serial files):
*   **Signature:** Kernel logs stop completely after:
    `clocksource: Switched to clocksource tsc`
*   **Cause:** Zen 4/AMD firmware TPM (fTPM) ACPI interrupts or PSP deadlocks crash the kernel thread scheduler during early initialization.

### State 2: Permanent GRUB Mitigation
Once booted into the OS (via the temporary GRUB edit), make the parameters persistent:
1. Edit `/etc/default/grub`:
   `sudo nano /etc/default/grub`
2. Update the command-line defaults:
   `GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0,115200 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp video=efifb:1280x1024"`
3. Regenerate GRUB config and verify:
   ```bash
   sudo update-grub
   grep "modprobe.blacklist" /boot/grub/grub.cfg
   ```
