#!/usr/bin/env bash

# ==============================================================================
# GDC Installer Forensics Collector
# ==============================================================================
# Run this on the remote server to gather all logs necessary to debug
# why autoinstall failed and the installer fell back to interactive mode.
# ==============================================================================

set -euo pipefail

FORENSICS_DIR="/tmp/gdc-installer-forensics-$(date +%Y%m%d%H%M%S)"
mkdir -p "${FORENSICS_DIR}"

echo "[-] Gathering forensics in ${FORENSICS_DIR}..."

# 1. Installer Logs (The most critical source)
cp -r /var/log/installer "${FORENSICS_DIR}/" 2>/dev/null || echo "[-] No /var/log/installer found."

# 2. Cloud-init logs (To check datasource processing)
cp /var/log/cloud-init.log "${FORENSICS_DIR}/" 2>/dev/null || echo "[-] No cloud-init.log found."
cp /var/log/cloud-init-output.log "${FORENSICS_DIR}/" 2>/dev/null || echo "[-] No cloud-init-output.log found."

# 3. System information (Hardware detection/Partitioning status)
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE > "${FORENSICS_DIR}/lsblk.txt"
dmesg > "${FORENSICS_DIR}/dmesg.txt"
cat /proc/cmdline > "${FORENSICS_DIR}/cmdline.txt"

# 4. Check for our injected config
for f in /autoinstall.yaml /run/autoinstall-storage.yaml; do
    if [ -f "$f" ]; then
        cp "$f" "${FORENSICS_DIR}/"
    fi
done

# 5. Archive
tar -czf "${FORENSICS_DIR}.tar.gz" -C "/tmp" "$(basename "${FORENSICS_DIR}")"

echo "[x] Forensics gathered successfully: ${FORENSICS_DIR}.tar.gz"
echo "[-] Please copy this file off the server for analysis."
