#!/usr/bin/env bash
# ==============================================================================
# GDC Bare-Metal Hardware & Installation Diagnostics Collector (Test/Debug Variant)
# ==============================================================================
set -u

OUT_DIR="/tmp/gdc-diagnostics"
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}/logs"

echo "=== GDC BARE-METAL DIAGNOSTICS REPORT ===" > "${OUT_DIR}/report.txt"
echo "Generated on: $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "${OUT_DIR}/report.txt"
echo "=========================================" >> "${OUT_DIR}/report.txt"

# 1. Hardware & CPU Info
echo "--- CPU & BOARD INFO ---" >> "${OUT_DIR}/report.txt"
lscpu >> "${OUT_DIR}/report.txt" 2>&1

# 2. Block Storage Topology
echo "--- BLOCK STORAGE LAYOUT (lsblk) ---" >> "${OUT_DIR}/report.txt"
lsblk -o NAME,TYPE,SIZE,MODEL,FSTYPE,MOUNTPOINTS,PHY-SEC,LOG-SEC >> "${OUT_DIR}/report.txt" 2>&1
echo "--- DISK SECTOR COUNTS ---" >> "${OUT_DIR}/report.txt"
for d in $(lsblk -dno NAME,TYPE | grep disk | awk '{print $1}'); do
  if [ -f "/sys/block/${d}/size" ]; then
    echo "Device: /dev/${d} | Kernel size (sectors): $(cat /sys/block/${d}/size) | Model: $(cat /sys/block/${d}/device/model 2>/dev/null || echo 'Unknown')" >> "${OUT_DIR}/report.txt"
  fi
done

# 3. Sourced and Generated Autoinstall Configurations
echo "--- AUTOINSTALL STORAGE PLANNED ---" >> "${OUT_DIR}/report.txt"
cat /run/autoinstall-storage.yaml >> "${OUT_DIR}/report.txt" 2>&1 || echo "No /run/autoinstall-storage.yaml" >> "${OUT_DIR}/report.txt"
cp /run/autoinstall-storage.yaml "${OUT_DIR}/" 2>/dev/null || true
cp /autoinstall.yaml "${OUT_DIR}/" 2>/dev/null || true
cp /tmp/generate_storage_config.sh "${OUT_DIR}/" 2>/dev/null || true

# 4. Networking, VLAN, and VRF Isolation
echo "--- NETWORK IP ADDRESSES ---" >> "${OUT_DIR}/report.txt"
ip addr show >> "${OUT_DIR}/report.txt" 2>&1
echo "--- NETWORK LINKS ---" >> "${OUT_DIR}/report.txt"
ip link show >> "${OUT_DIR}/report.txt" 2>&1
echo "--- VRF ROUTING TABLES ---" >> "${OUT_DIR}/report.txt"
ip route show table all >> "${OUT_DIR}/report.txt" 2>&1
echo "--- NETPLAN STATUS ---" >> "${OUT_DIR}/report.txt"
netplan status --all >> "${OUT_DIR}/report.txt" 2>&1
netplan info >> "${OUT_DIR}/report.txt" 2>&1

# 5. Gather Logs
cp -r /var/log/installer/* "${OUT_DIR}/logs/" 2>/dev/null || true
cp /var/log/cloud-init* "${OUT_DIR}/logs/" 2>/dev/null || true

# 6. Kernel ring-buffer
dmesg > "${OUT_DIR}/dmesg.txt"

# 7. Compress the Package
TAR_PATH="/gdc-diagnostics.tar.gz"
tar -czf "${TAR_PATH}" -C "/tmp" gdc-diagnostics

echo "=============================================================================="
echo "[+] SUCCESS: Diagnostics successfully compiled and compressed!"
echo "    - Target RAM path:  ${TAR_PATH}"
# Write backup copies to any active physical target mounts to survive reboot
if [ -d "/target" ]; then
  cp "${TAR_PATH}" "/target/gdc-diagnostics.tar.gz" || true
  mkdir -p /target/root
  cp "${TAR_PATH}" "/target/root/gdc-diagnostics.tar.gz" || true
  echo "    - Target Disk path: /target/root/gdc-diagnostics.tar.gz"
fi
echo "=============================================================================="
