#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# GDC Bootloader - Kernel Upgrade Readiness Auditor
# ==============================================================================
# Verifies that dracut, GRUB, and cryptsetup settings on the target OS retain all
# mandatory GDC hardware blacklists, fTPM polling mode, and TPM unseal hooks before
# executing system package upgrades (e.g. apt-get update && apt-get upgrade -y).
# ==============================================================================

set -euo pipefail

ERRORS=0

echo "=================================================="
echo " GDC LINUX_READY KERNEL UPGRADE AUDIT"
echo "=================================================="

# Check 1: Persistent Dracut Configuration
if [ -f /etc/dracut.conf.d/gdc.conf ] && \
   grep -q 'omit_drivers+=.*pcie_mp2_amd' /etc/dracut.conf.d/gdc.conf && \
   grep -q 'add_dracutmodules+=.*tpm2-tss' /etc/dracut.conf.d/gdc.conf && \
   grep -q 'add_drivers+=.*tpm_tis_core' /etc/dracut.conf.d/gdc.conf && \
   grep -q 'hostonly="no"' /etc/dracut.conf.d/gdc.conf; then
    echo "[+] Check 1 PASSED: Dracut config (/etc/dracut.conf.d/gdc.conf) is correct."
else
    echo "[!] Check 1 FAILED: Dracut config (/etc/dracut.conf.d/gdc.conf) is missing or incomplete!"
    ERRORS=$((ERRORS + 1))
fi

# Check 2: GRUB Kernel Command Line
if grep -q 'tpm_tis.interrupts=0' /etc/default/grub && \
   grep -q 'modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp' /etc/default/grub; then
    echo "[+] Check 2 PASSED: GRUB defaults (/etc/default/grub) contain mandatory parameters."
else
    echo "[!] Check 2 FAILED: GRUB defaults (/etc/default/grub) missing mandatory parameters!"
    ERRORS=$((ERRORS + 1))
fi

# Check 3: Cryptsetup Initramfs Conf-Hook
if grep -q 'CRYPTENROLL=y' /etc/cryptsetup-initramfs/conf-hook 2>/dev/null; then
    echo "[+] Check 3 PASSED: Cryptsetup hook (/etc/cryptsetup-initramfs/conf-hook) has CRYPTENROLL=y."
else
    echo "[!] Check 3 FAILED: Cryptsetup hook (/etc/cryptsetup-initramfs/conf-hook) missing CRYPTENROLL=y!"
    ERRORS=$((ERRORS + 1))
fi

echo "=================================================="

if [ "$ERRORS" -eq 0 ]; then
    echo "[x] LINUX_READY SUCCESS: Node is verified ready for safe kernel upgrades."
    exit 0
else
    echo "[!] LINUX_READY FAILURE: $ERRORS check(s) failed! Do NOT run upgrade until fixed."
    exit 1
fi
