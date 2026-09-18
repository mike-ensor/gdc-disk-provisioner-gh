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
# GDC Bootloader - Kernel Upgrade Readiness Auditor
# ==============================================================================
# Verifies that dracut, GRUB, and cryptsetup settings on the target OS retain all
# mandatory GDC hardware blacklists, fTPM polling mode, and TPM unseal hooks before
# executing system package upgrades (e.g. apt-get update && apt-get upgrade -y).
# ==============================================================================

set -euo pipefail

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Kernel Upgrade Readiness Auditor for GDC nodes.
Verifies that Dracut, GRUB, and cryptsetup settings retain all mandatory
GDC hardware blacklists, fTPM polling mode, and TPM unseal hooks before
executing system package upgrades.

Options:
  -h, --help  Display this help message and exit
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage 0
            ;;
        *)
            echo "Error: Unknown option '$1'" >&2
            usage 1
            ;;
    esac
done

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
