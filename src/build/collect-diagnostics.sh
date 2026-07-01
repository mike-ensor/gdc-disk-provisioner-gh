#!/usr/bin/env bash
# ==============================================================================
# GDC Bare-Metal Hardware & Installation Diagnostics Collector (Enhanced)
# ==============================================================================
# Compiles a comprehensive diagnostic report in dual formats:
#   1. Human-Readable Report (/tmp/gdc-diagnostics/report.txt)
#   2. Machine-Parsable Report (/tmp/gdc-diagnostics/report.json)
# Gathers CPU, storage sector configurations, network links, VRF isolated tables,
# systemd service active statuses, port socket listening state, and installer logs.
# ==============================================================================
set -euo pipefail

OUT_DIR="/tmp/gdc-diagnostics"
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}/logs"

echo "=============================================================================="
echo "GDC BARE-METAL DIAGNOSTICS COLLECTOR"
echo "=============================================================================="
echo "[-] Initializing diagnostic outputs directory: ${OUT_DIR}"

# 1. Human-Readable Header
echo "=== GDC BARE-METAL DIAGNOSTICS REPORT ===" > "${OUT_DIR}/report.txt"
echo "Generated on: $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "${OUT_DIR}/report.txt"
echo "Host Kernel:  $(uname -r)" >> "${OUT_DIR}/report.txt"
echo "Hostname:     $(hostname)" >> "${OUT_DIR}/report.txt"
echo "=========================================" >> "${OUT_DIR}/report.txt"
echo "" >> "${OUT_DIR}/report.txt"

# 2. Hardware & CPU Info
echo "--- CPU & BOARD INFO ---" >> "${OUT_DIR}/report.txt"
lscpu >> "${OUT_DIR}/report.txt" 2>&1
echo "" >> "${OUT_DIR}/report.txt"

# 3. Block Storage Topology
echo "--- BLOCK STORAGE LAYOUT (lsblk) ---" >> "${OUT_DIR}/report.txt"
lsblk -o NAME,TYPE,SIZE,MODEL,FSTYPE,MOUNTPOINTS,PHY-SEC,LOG-SEC >> "${OUT_DIR}/report.txt" 2>&1
echo "" >> "${OUT_DIR}/report.txt"

echo "--- DISK SECTOR COUNTS ---" >> "${OUT_DIR}/report.txt"
for d in $(lsblk -dno NAME,TYPE | grep disk | awk '{print $1}'); do
  if [ -f "/sys/block/${d}/size" ]; then
    model_name=$(cat "/sys/block/${d}/device/model" 2>/dev/null || echo 'Unknown')
    echo "Device: /dev/${d} | Kernel size (sectors): $(cat "/sys/block/${d}/size") | Model: ${model_name}" >> "${OUT_DIR}/report.txt"
  fi
done
echo "" >> "${OUT_DIR}/report.txt"

# 4. Sourced and Generated Autoinstall Configurations
echo "--- AUTOINSTALL STORAGE PLANNED ---" >> "${OUT_DIR}/report.txt"
if [ -f /run/autoinstall-storage.yaml ]; then
  cat /run/autoinstall-storage.yaml >> "${OUT_DIR}/report.txt" 2>&1
  cp /run/autoinstall-storage.yaml "${OUT_DIR}/" 2>/dev/null || true
else
  echo "No /run/autoinstall-storage.yaml" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

if [ -f /autoinstall.yaml ]; then
  cp /autoinstall.yaml "${OUT_DIR}/" 2>/dev/null || true
fi
if [ -f /tmp/generate_storage_config.sh ]; then
  cp /tmp/generate_storage_config.sh "${OUT_DIR}/" 2>/dev/null || true
fi

# 5. Networking, VLAN, and VRF Isolation
echo "--- NETWORK IP ADDRESSES ---" >> "${OUT_DIR}/report.txt"
ip addr show >> "${OUT_DIR}/report.txt" 2>&1
echo "" >> "${OUT_DIR}/report.txt"

echo "--- NETWORK LINKS ---" >> "${OUT_DIR}/report.txt"
ip link show >> "${OUT_DIR}/report.txt" 2>&1
echo "" >> "${OUT_DIR}/report.txt"

echo "--- VRF ROUTING TABLES ---" >> "${OUT_DIR}/report.txt"
ip route show table all >> "${OUT_DIR}/report.txt" 2>&1
echo "" >> "${OUT_DIR}/report.txt"

echo "--- NETPLAN STATUS ---" >> "${OUT_DIR}/report.txt"
if command -v netplan &>/dev/null; then
  netplan status --all >> "${OUT_DIR}/report.txt" 2>&1 || true
  netplan info >> "${OUT_DIR}/report.txt" 2>&1 || true
else
  echo "Netplan utility is not installed." >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# 6. systemd Service Auditing
echo "--- GDC SYSTEMD SERVICES STATUS ---" >> "${OUT_DIR}/report.txt"
for svc in gitea nexus gdc-provision ssh systemd-networkd; do
  if systemctl is-active --quiet "${svc}" 2>/dev/null; then
    status="ACTIVE"
  else
    status="INACTIVE"
  fi
  
  # Fetch properties via systemctl show safely
  active_state=$(systemctl show "${svc}" --property=ActiveState 2>/dev/null | cut -d'=' -f2 || echo "Unknown")
  load_state=$(systemctl show "${svc}" --property=LoadState 2>/dev/null | cut -d'=' -f2 || echo "Unknown")
  unit_state=$(systemctl show "${svc}" --property=UnitFileState 2>/dev/null | cut -d'=' -f2 || echo "Unknown")
  
  echo "Service: ${svc} | Status: ${status} | LoadState: ${load_state} | ActiveState: ${active_state} | UnitState: ${unit_state}" >> "${OUT_DIR}/report.txt"
done
echo "" >> "${OUT_DIR}/report.txt"

# 7. Listening Port Auditing
echo "--- GDC SYSTEM PORT LISTENING AUDIT ---" >> "${OUT_DIR}/report.txt"
if command -v ss &>/dev/null; then
  ss -ltun >> "${OUT_DIR}/report.txt" 2>&1 || true
else
  echo "ss utility is not available." >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# 8. GDC Local Service Hub HTTP Health Handshakes
echo "--- GDC SERVICE HTTP HEALTH CHECKS ---" >> "${OUT_DIR}/report.txt"
if command -v curl &>/dev/null; then
  # Check Gitea Port 3000
  echo -n "Gitea (Port 3000) Health: " >> "${OUT_DIR}/report.txt"
  if curl -s -I --connect-timeout 2 "http://127.0.0.1:3000" &> /dev/null; then
    echo "HEALTHY (Responsive)" >> "${OUT_DIR}/report.txt"
  else
    echo "UNHEALTHY (No response)" >> "${OUT_DIR}/report.txt"
  fi

  # Check Nexus Port 8081
  echo -n "Nexus (Port 8081) Health: " >> "${OUT_DIR}/report.txt"
  if curl -s -I --connect-timeout 2 "http://127.0.0.1:8081" &> /dev/null; then
    echo "HEALTHY (Responsive)" >> "${OUT_DIR}/report.txt"
  else
    echo "UNHEALTHY (No response)" >> "${OUT_DIR}/report.txt"
  fi
else
  echo "curl utility is not available." >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# 9. Hardware Security TPM 2.0 State
echo "--- TPM 2.0 HARDWARE SECURITY STATUS ---" >> "${OUT_DIR}/report.txt"
if [ -c /dev/tpmrm0 ]; then
  echo "TPM 2.0 Device (/dev/tpmrm0): PRESENT" >> "${OUT_DIR}/report.txt"
else
  echo "TPM 2.0 Device (/dev/tpmrm0): MISSING OR INACTIVE" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# 10. Parse and Compile Structured Machine Report (report.json)
echo "[-] Compiling structured machine-readable report.json..."
python3 - <<EOF > "${OUT_DIR}/report.json"
import json
import subprocess
import os

report = {
    "timestamp": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
    "host_metadata": {
        "hostname": subprocess.getoutput("hostname").strip(),
        "kernel": subprocess.getoutput("uname -r").strip(),
        "uefi_boot": os.path.exists("/sys/firmware/efi")
    },
    "services": {},
    "ports": {},
    "tpm_status": {
        "device_present": os.path.exists("/dev/tpmrm0")
    },
    "lvm_volumes": {},
    "http_health": {}
}

# Auditing services
for svc in ["gitea", "nexus", "gdc-provision", "ssh", "systemd-networkd"]:
    is_active = subprocess.run(["systemctl", "is-active", "--quiet", svc]).returncode == 0
    load_state = subprocess.getoutput(f"systemctl show {svc} --property=LoadState").split("=")[-1].strip()
    active_state = subprocess.getoutput(f"systemctl show {svc} --property=ActiveState").split("=")[-1].strip()
    unit_state = subprocess.getoutput(f"systemctl show {svc} --property=UnitFileState").split("=")[-1].strip()
    report["services"][svc] = {
        "active": is_active,
        "load_state": load_state,
        "active_state": active_state,
        "unit_file_state": unit_state
    }

# Auditing active socket ports
for port in [3000, 8081, 5001, 5002]:
    listening = subprocess.run(f"ss -ltn | grep -q ':{port} '", shell=True).returncode == 0
    report["ports"][str(port)] = {"listening": listening}

# HTTP health verification handshakes
try:
    gitea_code = subprocess.getoutput("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://127.0.0.1:3000")
    report["http_health"]["gitea_port_3000"] = {"http_code": int(gitea_code) if gitea_code.isdigit() else 0, "healthy": gitea_code in ["200", "301", "302"]}
except Exception:
    report["http_health"]["gitea_port_3000"] = {"healthy": False}

try:
    nexus_code = subprocess.getoutput("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://127.0.0.1:8081")
    report["http_health"]["nexus_port_8081"] = {"http_code": int(nexus_code) if nexus_code.isdigit() else 0, "healthy": nexus_code in ["200", "302", "401"]}
except Exception:
    report["http_health"]["nexus_port_8081"] = {"healthy": False}

# Storage status auditing (parse lsblk json)
try:
    lsblk_json = subprocess.getoutput("lsblk --json -o NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS")
    report["lvm_volumes"] = json.loads(lsblk_json)
except Exception:
    report["lvm_volumes"] = {"error": "Failed to parse lsblk output to JSON"}

print(json.dumps(report, indent=2))
EOF

# 11. Gather Installer Logs
echo "[-] Collecting installer log buffers..."
cp -r /var/log/installer/* "${OUT_DIR}/logs/" 2>/dev/null || true
cp /var/log/cloud-init* "${OUT_DIR}/logs/" 2>/dev/null || true

# 12. Gather Kernel Logs (dmesg)
echo "[-] Saving kernel ring-buffer (dmesg)..."
dmesg > "${OUT_DIR}/dmesg.txt" 2>/dev/null || echo "Unable to read dmesg without root privileges." > "${OUT_DIR}/dmesg.txt"

# 13. Compress and Package the Artifact
TAR_PATH="/gdc-diagnostics.tar.gz"
echo "[-] Creating tarball package at ${TAR_PATH}..."
tar -czf "${TAR_PATH}" -C "/tmp" gdc-diagnostics

echo "=============================================================================="
echo "[+] SUCCESS: Diagnostics successfully compiled and compressed!"
echo "    - Target RAM path:  ${TAR_PATH}"

# Duplicate package target to physical mount partition to survive VM reboots
if [ -d "/target" ]; then
  cp "${TAR_PATH}" "/target/gdc-diagnostics.tar.gz" || true
  mkdir -p /target/root
  cp "${TAR_PATH}" "/target/root/gdc-diagnostics.tar.gz" || true
  echo "    - Target Disk path: /target/root/gdc-diagnostics.tar.gz"
fi
echo "=============================================================================="
