#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0


# ==============================================================================
# GDC Forensics Inspector
# ==============================================================================
# Extracts forensics tarball and runs automated diagnostic checks.
# Usage: ./bin/inspect-forensics.sh <tarball.tar.gz>
# ==============================================================================

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <tarball.tar.gz>"
    exit 1
fi

TARBALL=$1
EXTRACT_DIR="./tmp/crash-analysis-$(date +%Y%m%d%H%M%S)"

echo "[-] Extracting ${TARBALL} to ${EXTRACT_DIR}..."
mkdir -p "${EXTRACT_DIR}"
tar -xzf "${TARBALL}" -C "${EXTRACT_DIR}"

# Find the forensic directory inside (it might have a variable timestamp name)
FORENSIC_ROOT=$(find "${EXTRACT_DIR}" -maxdepth 1 -mindepth 1 -type d | head -n 1)

echo "[-] Analyzing forensics in ${FORENSIC_ROOT}..."

# 1. Verify Boot Command Line
echo "=============================================================================="
echo " CHECK: Kernel Command Line (Boot Params)"
echo "=============================================================================="
cat "${FORENSIC_ROOT}/cmdline.txt"
echo -e "\n"
if grep -q "ds=nocloud;s=/cdrom/nocloud/" "${FORENSIC_ROOT}/cmdline.txt"; then
    echo "[x] Boot parameters look correct (offline seed)."
else
    echo "[!] WARNING: Boot parameters are likely wrong (missing or incorrect ds/s)."
fi

# 2. Check Subiquity for Schema Errors
echo -e "\n=============================================================================="
echo " CHECK: Subiquity Config Application Errors"
echo "=============================================================================="
SUBIQUITY_LOG="${FORENSIC_ROOT}/installer/subiquity-server-debug.log"
if [ -f "${SUBIQUITY_LOG}" ]; then
    grep -Ei "apply_autoinstall_config|error|exception|fail" "${SUBIQUITY_LOG}" | tail -n 20
else
    echo "[!] Installer log not found."
fi

# 3. Verify Configuration File Existence
echo -e "\n=============================================================================="
echo " CHECK: Injected Configuration Files"
echo "=============================================================================="
for f in autoinstall.yaml autoinstall-storage.yaml; do
    if [ -f "${FORENSIC_ROOT}/$f" ]; then
        echo "[x] Found ${f}"
    else
        echo "[!] Missing ${f} in forensics bundle."
    fi
done

echo -e "\n[x] Inspection complete."
