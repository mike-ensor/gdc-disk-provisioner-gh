#!/usr/bin/env bash
# ==============================================================================
# GDC Bare-Metal Hardware & Installation Diagnostics Collector (Ultimate Edition)
# ==============================================================================
# Compiles a comprehensive diagnostic report in dual formats:
#   1. Human-Readable Report (/tmp/gdc-diagnostics/report.txt)
#   2. Machine-Parsable Report (/tmp/gdc-diagnostics/report.json)
# Gathers CPU, storage layouts, performance average load stats, active port sockets,
# systemd service active statuses, Netplan routing tables, and auth security.
# Supports unprivileged execution by checking permissions and guarding restricted tasks.
# ==============================================================================
set -euo pipefail

# Determine if the script is running with privileged access (root/EUID 0)
IS_PRIVILEGED=false
if [ "$(id -u)" -eq 0 ]; then
  IS_PRIVILEGED=true
fi

# Define dynamic working directory to prevent permission collisions on /tmp
OUT_DIR="/tmp/gdc-diagnostics"
if [ "${IS_PRIVILEGED}" = "false" ]; then
  OUT_DIR="/tmp/gdc-diagnostics-${USER:-unprivileged}"
fi

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}/logs"

# Print terminal initialization header
echo "GDC BARE-METAL DIAGNOSTICS COLLECTOR"
echo "[-] Initializing diagnostic outputs directory: ${OUT_DIR}"

# ------------------------------------------------------------------------------
# SECTION 1: REPORT.TXT HUMAN HEADER
# ------------------------------------------------------------------------------
echo "=== GDC BARE-METAL DIAGNOSTICS REPORT ===" > "${OUT_DIR}/report.txt"
echo "Generated on: $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "${OUT_DIR}/report.txt"
echo "Host Kernel:  $(uname -r)" >> "${OUT_DIR}/report.txt"
echo "Hostname:     $(hostname)" >> "${OUT_DIR}/report.txt"
echo "Privileged:   ${IS_PRIVILEGED}" >> "${OUT_DIR}/report.txt"
echo "=========================================" >> "${OUT_DIR}/report.txt"
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 2: SYSTEM IDENTITY & OS BASELINE
# ------------------------------------------------------------------------------
echo "--- SYSTEM IDENTITY & OS BASELINE ---" >> "${OUT_DIR}/report.txt"
if command -v hostnamectl &>/dev/null; then
  hostnamectl >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
else
  uname -a >> "${OUT_DIR}/report.txt" 2>&1
fi

echo "--- OS RELEASE ---" >> "${OUT_DIR}/report.txt"
if [ -r /etc/os-release ]; then
  cat /etc/os-release >> "${OUT_DIR}/report.txt"
else
  echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

echo "--- UPTIME & BOOT TIME ---" >> "${OUT_DIR}/report.txt"
uptime >> "${OUT_DIR}/report.txt" 2>&1
if command -v uptime &>/dev/null; then
  uptime -s >> "${OUT_DIR}/report.txt" 2>/dev/null || true
fi

echo "--- TIME & NTP STATUS ---" >> "${OUT_DIR}/report.txt"
if command -v timedatectl &>/dev/null; then
  timedatectl status >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
else
  date >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 3: HARDWARE & VIRTUALIZATION TOPOLOGY
# ------------------------------------------------------------------------------
echo "--- CPU & BOARD INFO ---" >> "${OUT_DIR}/report.txt"
lscpu >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- MEMORY ALLOCATION ---" >> "${OUT_DIR}/report.txt"
free -h >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- VIRTUALIZATION PROVIDER ---" >> "${OUT_DIR}/report.txt"
if command -v systemd-detect-virt &>/dev/null; then
  systemd-detect-virt >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
else
  echo "systemd-detect-virt not available" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 4: STORAGE & FILE SYSTEM HEALTH
# ------------------------------------------------------------------------------
echo "--- BLOCK STORAGE LAYOUT (lsblk) ---" >> "${OUT_DIR}/report.txt"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,UUID >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- DISK SECTOR COUNTS ---" >> "${OUT_DIR}/report.txt"
for d in $(lsblk -dno NAME,TYPE 2>/dev/null | grep disk | awk '{print $1}' || echo ""); do
  if [ -f "/sys/block/${d}/size" ]; then
    model_name=$(cat "/sys/block/${d}/device/model" 2>/dev/null || echo 'Unknown')
    echo "Device: /dev/${d} | Kernel size (sectors): $(cat "/sys/block/${d}/size") | Model: ${model_name}" >> "${OUT_DIR}/report.txt"
  fi
done

echo "--- DISK SPACE UTILIZATION ---" >> "${OUT_DIR}/report.txt"
df -hT >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- INODE UTILIZATION ---" >> "${OUT_DIR}/report.txt"
df -i >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- MOUNT CONSTRAINTS (fstab) ---" >> "${OUT_DIR}/report.txt"
if [ -r /etc/fstab ]; then
  cat /etc/fstab >> "${OUT_DIR}/report.txt"
else
  echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

echo "--- ACTIVE SYSTEM MOUNTS ---" >> "${OUT_DIR}/report.txt"
mount -l >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- SOFTWARE RAID STATUS ---" >> "${OUT_DIR}/report.txt"
if [ -f /proc/mdstat ] && [ -r /proc/mdstat ]; then
  cat /proc/mdstat >> "${OUT_DIR}/report.txt"
else
  echo "No active software RAID (/proc/mdstat)" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 5: CURRENT RESOURCE snapshot
# ------------------------------------------------------------------------------
echo "--- CPU LOAD AVERAGE ---" >> "${OUT_DIR}/report.txt"
if [ -r /proc/loadavg ]; then
  cat /proc/loadavg >> "${OUT_DIR}/report.txt"
else
  echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

echo "--- TOP 15 RESOURCE CONSUMERS ---" >> "${OUT_DIR}/report.txt"
ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%cpu 2>/dev/null | head -n 16 >> "${OUT_DIR}/report.txt" || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- ZOMBIE PROCESSES ---" >> "${OUT_DIR}/report.txt"
ps axo stat,ppid,pid,comm 2>/dev/null | grep -w defunc >> "${OUT_DIR}/report.txt" || echo "No zombie processes detected." >> "${OUT_DIR}/report.txt"
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 6: NETWORKING CONFIGURATION & SOCKETS
# ------------------------------------------------------------------------------
echo "--- NETWORK IP ADDRESSES ---" >> "${OUT_DIR}/report.txt"
ip addr show >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- NETWORK LINKS ---" >> "${OUT_DIR}/report.txt"
ip link show >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- VRF ROUTING TABLES ---" >> "${OUT_DIR}/report.txt"
ip route show table all >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"

echo "--- ACTIVE LISTENING SOCKETS ---" >> "${OUT_DIR}/report.txt"
if command -v ss &>/dev/null; then
  if [ "${IS_PRIVILEGED}" = "true" ]; then
    ss -tulnp >> "${OUT_DIR}/report.txt" 2>&1
  else
    ss -tuln >> "${OUT_DIR}/report.txt" 2>&1
    echo "[-] ss process pid mapping: Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
  fi
else
  echo "ss utility is not available." >> "${OUT_DIR}/report.txt"
fi

echo "--- DNS SYSTEM RESOLV ---" >> "${OUT_DIR}/report.txt"
if [ -r /etc/resolv.conf ]; then
  cat /etc/resolv.conf >> "${OUT_DIR}/report.txt"
else
  echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

echo "--- DNS LOCAL HOSTNAME RESOLUTION ---" >> "${OUT_DIR}/report.txt"
if command -v getent &>/dev/null; then
  getent hosts localhost >> "${OUT_DIR}/report.txt" 2>&1 || true
else
  ping -c 1 -W 1 localhost >> "${OUT_DIR}/report.txt" 2>&1 || true
fi

echo "--- FIREWALL LIST RULES ---" >> "${OUT_DIR}/report.txt"
if [ "${IS_PRIVILEGED}" = "true" ]; then
  iptables -L -n -v >> "${OUT_DIR}/report.txt" 2>/dev/null || echo "iptables rule query failed" >> "${OUT_DIR}/report.txt"
else
  echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 7: SERVICES & DAEMONS
# ------------------------------------------------------------------------------
echo "--- SYSTEMD FAILED UNITS ---" >> "${OUT_DIR}/report.txt"
if command -v systemctl &>/dev/null; then
  systemctl --failed >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

echo "--- GDC SYSTEMD SERVICES STATUS ---" >> "${OUT_DIR}/report.txt"
for svc in gitea nexus gdc-provision ssh systemd-networkd; do
  if systemctl is-active --quiet "${svc}" 2>/dev/null; then
    status="ACTIVE"
  else
    status="INACTIVE"
  fi
  active_state=$(systemctl show "${svc}" --property=ActiveState 2>/dev/null | cut -d'=' -f2 || echo "Unknown")
  load_state=$(systemctl show "${svc}" --property=LoadState 2>/dev/null | cut -d'=' -f2 || echo "Unknown")
  unit_state=$(systemctl show "${svc}" --property=UnitFileState 2>/dev/null | cut -d'=' -f2 || echo "Unknown")
  echo "Service: ${svc} | Status: ${status} | LoadState: ${load_state} | ActiveState: ${active_state} | UnitState: ${unit_state}" >> "${OUT_DIR}/report.txt"
done

echo "--- GDC SERVICES BOOT STRAP ENABLED ---" >> "${OUT_DIR}/report.txt"
if command -v systemctl &>/dev/null; then
  systemctl list-unit-files --state=enabled >> "${OUT_DIR}/report.txt" 2>&1 || echo "Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 8: GDC LOCAL SERVICE HUB HEALTH CHECKS
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# SECTION 9: HARDWARE SECURITY (TPM 2.0)
# ------------------------------------------------------------------------------
echo "--- TPM 2.0 HARDWARE SECURITY STATUS ---" >> "${OUT_DIR}/report.txt"
if [ -c /dev/tpmrm0 ]; then
  echo "TPM 2.0 Device (/dev/tpmrm0): PRESENT" >> "${OUT_DIR}/report.txt"
else
  echo "TPM 2.0 Device (/dev/tpmrm0): MISSING OR INACTIVE" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 10: AUTOINSTALL CONFIGS & SOURCE FILES
# ------------------------------------------------------------------------------
echo "--- AUTOINSTALL CONFIGURATION BLOCKS ---" >> "${OUT_DIR}/report.txt"
if [ -f /autoinstall.yaml ] && [ -r /autoinstall.yaml ]; then
  cp /autoinstall.yaml "${OUT_DIR}/" 2>/dev/null || true
fi
if [ -f /tmp/generate_storage_config.sh ] && [ -r /tmp/generate_storage_config.sh ]; then
  cp /tmp/generate_storage_config.sh "${OUT_DIR}/" 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# SECTION 11: PROGRAMMATIC JSON COMPILATION
# ------------------------------------------------------------------------------
echo "[-] Compiling structured machine-readable report.json..."
python3 - <<'EOF' > "${OUT_DIR}/report.json"
import json
import subprocess
import os

report = {
    "timestamp": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
    "host_metadata": {
        "hostname": subprocess.getoutput("hostname").strip(),
        "kernel": subprocess.getoutput("uname -r").strip(),
        "uefi_boot": os.path.exists("/sys/firmware/efi"),
        "privileged": os.getuid() == 0
    },
    "system_health": {
        "uptime": subprocess.getoutput("uptime").strip(),
        "load_average": subprocess.getoutput("cat /proc/loadavg 2>/dev/null || echo 'Unknown'").strip(),
        "failed_units_count": int(subprocess.getoutput("systemctl list-units --state=failed --legend=false 2>/dev/null | wc -l || echo '0'").strip().split('\n')[0] or 0)
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

# Network connectivity checks
mgmt_iface = subprocess.getoutput("ip route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") print $(i+1)}' | head -n 1").strip() or "enp1s0"
k8s_iface = subprocess.getoutput("ip link show master vrf-k8s 2>/dev/null | grep -E '^[0-9]+: ' | awk '{print $2}' | cut -d':' -f1 | cut -d'@' -f1 | head -n 1").strip() or "enp1s0.109"
mgmt_gateway = subprocess.getoutput("ip route show default | grep 'via' | awk '{print $3}' | head -n 1").strip() or "192.168.9.1"
k8s_gateway = subprocess.getoutput("ip route show table 20 default 2>/dev/null | grep 'via' | awk '{print $3}' | head -n 1").strip() or "192.168.109.1"
k8s_ip = subprocess.getoutput(f"ip -o addr show dev {k8s_iface} 2>/dev/null | grep -oE '[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+' | head -n 1").strip() or "192.168.109.14"

report["network_connectivity"] = {}

# 1. Management Gateway
ping_mgmt = subprocess.run(f"ping -c 2 -W 1 -I {mgmt_iface} {mgmt_gateway}", shell=True, capture_output=True, text=True)
if ping_mgmt.returncode == 0:
    try:
        rtt = ping_mgmt.stdout.strip().split("\n")[-1].split("/")[-3]
        report["network_connectivity"]["management_gateway"] = {"reachable": True, "avg_rtt_ms": float(rtt)}
    except Exception:
        report["network_connectivity"]["management_gateway"] = {"reachable": True}
else:
    report["network_connectivity"]["management_gateway"] = {"reachable": False}

# 2. Kubernetes Gateway
if os.getuid() == 0:
    ping_k8s = subprocess.run(f"ip vrf exec vrf-k8s ping -c 2 -W 1 {k8s_gateway}", shell=True, capture_output=True, text=True)
    if ping_k8s.returncode == 0:
        try:
            rtt = ping_k8s.stdout.strip().split("\n")[-1].split("/")[-3]
            report["network_connectivity"]["kubernetes_gateway"] = {"reachable": True, "avg_rtt_ms": float(rtt)}
        except Exception:
            report["network_connectivity"]["kubernetes_gateway"] = {"reachable": True}
    else:
        report["network_connectivity"]["kubernetes_gateway"] = {"reachable": False}
else:
    report["network_connectivity"]["kubernetes_gateway"] = {"reachable": None, "skipped_reason": "Skipped due to lack of permissions"}

# 3. Cross-Link Isolation
ping_isolated = subprocess.run(f"ping -c 2 -W 1 -I {mgmt_iface} {k8s_ip}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
report["network_connectivity"]["cross_link_isolated"] = {"secured": ping_isolated.returncode != 0}

# 4. Public WAN Access
ping_wan = subprocess.run(f"ping -c 2 -W 1 -I {mgmt_iface} 8.8.8.8", shell=True, capture_output=True, text=True)
if ping_wan.returncode == 0:
    try:
        rtt = ping_wan.stdout.strip().split("\n")[-1].split("/")[-3]
        report["network_connectivity"]["public_wan_dns"] = {"reachable": True, "avg_rtt_ms": float(rtt)}
    except Exception:
        report["network_connectivity"]["public_wan_dns"] = {"reachable": True}
else:
    report["network_connectivity"]["public_wan_dns"] = {"reachable": False}

print(json.dumps(report, indent=2))
EOF

# ------------------------------------------------------------------------------
# SECTION 12: LOG GATHERING (Guarded)
# ------------------------------------------------------------------------------
echo "[-] Collecting installer log buffers..."
if [ "${IS_PRIVILEGED}" = "true" ]; then
  if [ -d /var/log/installer ]; then
    cp -r /var/log/installer/* "${OUT_DIR}/logs/" 2>/dev/null || true
  fi
  cp /var/log/cloud-init* "${OUT_DIR}/logs/" 2>/dev/null || true
else
  echo "[-] Collecting installer log buffers... Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

# ------------------------------------------------------------------------------
# SECTION 13: CONFIGURATIONS GATHERING (Guarded)
# ------------------------------------------------------------------------------
echo "[-] Gathering..."
# Core System Info (Unprivileged ok)
echo "     [+] Core system"

# Netplan configuration files (Guarded)
if [ "${IS_PRIVILEGED}" = "true" ] || [ -r /etc/netplan ]; then
  echo "     [+] Netplan"
  mkdir -p "${OUT_DIR}/configs"
  cp -r /etc/netplan/* "${OUT_DIR}/configs/" 2>/dev/null || true
else
  echo "[-] Gathering Netplan... Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

# Service status (Unprivileged ok)
echo "     [+] Service status"

# GDC Provisioning configurations (Guarded)
if [ "${IS_PRIVILEGED}" = "true" ] || [ -r /etc/gdc ]; then
  echo "     [+] GDC provisioning configurations"
  mkdir -p "${OUT_DIR}/configs"
  cp -r /etc/gdc/* "${OUT_DIR}/configs/" 2>/dev/null || true
  if [ -r /etc/default/gdc-provision ]; then
    cp /etc/default/gdc-provision "${OUT_DIR}/configs/" 2>/dev/null || true
  fi
else
  echo "[-] Gathering GDC provisioning configurations... Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

# ------------------------------------------------------------------------------
# SECTION 14: SYSTEMD JOURNALS EXTRACTION (Guarded)
# ------------------------------------------------------------------------------
echo "[-] Saving active systemd service journals..."
for svc in gdc-provision gitea nexus ssh systemd-networkd; do
  if [ "${IS_PRIVILEGED}" = "true" ] || groups | grep -qE "systemd-journal|adm|sudo|root"; then
    journalctl -u "${svc}" --no-pager -n 1000 > "${OUT_DIR}/logs/${svc}.log" 2>/dev/null || echo "Unable to query journal for ${svc}." > "${OUT_DIR}/logs/${svc}.log"
  else
    echo "Service journal: ${svc} | Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
  fi
done

# ------------------------------------------------------------------------------
# SECTION 15: KERNEL RING-BUFFER DMESG (Guarded)
# ------------------------------------------------------------------------------
echo "[-] Saving kernel ring-buffer (dmesg)..."
if [ "${IS_PRIVILEGED}" = "true" ]; then
  dmesg > "${OUT_DIR}/dmesg.txt" 2>/dev/null || echo "Unable to read dmesg without root privileges." > "${OUT_DIR}/dmesg.txt"
else
  echo "Kernel logs (dmesg): Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
  echo "Unable to read dmesg without root privileges." > "${OUT_DIR}/dmesg.txt"
fi

# ------------------------------------------------------------------------------
# SECTION 15b: NETWORK CONNECTIVITY CHECK (Enenumerated)
# ------------------------------------------------------------------------------
echo "[-] Network Connectivity Check..."
echo "--- NETWORK CONNECTIVITY CHECK ---" >> "${OUT_DIR}/report.txt"

# Dynamic interface discovery
MGMT_IFACE=$(ip route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -n 1 || echo "enp1s0")
K8S_IFACE=$(ip link show master vrf-k8s 2>/dev/null | grep -E '^[0-9]+: ' | awk '{print $2}' | cut -d':' -f1 | cut -d'@' -f1 | head -n 1 || echo "enp1s0.109")

# Dynamic gateway discovery
MGMT_GATEWAY=$(ip route show default 2>/dev/null | grep 'via' | awk '{print $3}' | head -n 1 || echo "192.168.9.1")
K8S_GATEWAY=$(ip route show table 20 default 2>/dev/null | grep 'via' | awk '{print $3}' | head -n 1 || echo "192.168.109.1")

# 1. Ping Management Gateway
ping_mgmt=$(ping -c 2 -W 1 -I "${MGMT_IFACE}" "${MGMT_GATEWAY}" 2>/dev/null || echo "")
if [[ -n "${ping_mgmt}" ]]; then
  avg_rtt=$(echo "${ping_mgmt}" | tail -n 1 | cut -d'/' -f5)
  echo "     [+] Management Gateway (${MGMT_GATEWAY}): REACHABLE (${avg_rtt}ms)"
  echo "Management Gateway (${MGMT_GATEWAY}) via ${MGMT_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  echo "     [-] Management Gateway (${MGMT_GATEWAY}): UNREACHABLE"
  echo "Management Gateway (${MGMT_GATEWAY}) via ${MGMT_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
fi

# 2. Ping Kubernetes Gateway
ping_k8s=""
if [ "${IS_PRIVILEGED}" = "true" ]; then
  ping_k8s=$(ip vrf exec vrf-k8s ping -c 2 -W 1 "${K8S_GATEWAY}" 2>/dev/null || echo "")
fi

if [[ -n "${ping_k8s}" ]]; then
  avg_rtt=$(echo "${ping_k8s}" | tail -n 1 | cut -d'/' -f5)
  echo "     [+] Kubernetes Gateway (${K8S_GATEWAY}): REACHABLE (${avg_rtt}ms)"
  echo "Kubernetes Gateway (${K8S_GATEWAY}) via ${K8S_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  if [ "${IS_PRIVILEGED}" = "true" ]; then
    echo "     [-] Kubernetes Gateway (${K8S_GATEWAY}): UNREACHABLE"
    echo "Kubernetes Gateway (${K8S_GATEWAY}) via ${K8S_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
  else
    echo "     [-] Kubernetes Gateway (${K8S_GATEWAY}): Skipped due to lack of permissions"
    echo "Kubernetes Gateway (${K8S_GATEWAY}) via ${K8S_IFACE}: Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
  fi
fi

# 3. Ping Cross-Link Isolation (expecting BLOCKED)
K8S_IP=$(ip -o addr show dev "${K8S_IFACE}" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || echo "192.168.109.14")
if ping -c 2 -W 1 -I "${MGMT_IFACE}" "${K8S_IP}" &>/dev/null; then
  echo "     [!] Cross-Link Isolation:  LEAKING (Failed)"
  echo "Cross-Link Isolation between ${MGMT_IFACE} and ${K8S_IFACE}: LEAKING" >> "${OUT_DIR}/report.txt"
else
  echo "     [+] Cross-Link Isolation:  SECURED (Blocked)"
  echo "Cross-Link Isolation between ${MGMT_IFACE} and ${K8S_IFACE}: SECURED" >> "${OUT_DIR}/report.txt"
fi

# 4. Ping Public WAN Access
ping_wan=$(ping -c 2 -W 1 -I "${MGMT_IFACE}" 8.8.8.8 2>/dev/null || echo "")
if [[ -n "${ping_wan}" ]]; then
  avg_rtt=$(echo "${ping_wan}" | tail -n 1 | cut -d'/' -f5)
  echo "     [+] Public WAN (8.8.8.8):  REACHABLE (${avg_rtt}ms)"
  echo "Public WAN (8.8.8.8) via ${MGMT_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  echo "     [-] Public WAN (8.8.8.8):  UNREACHABLE"
  echo "Public WAN (8.8.8.8) via ${MGMT_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 16: TARBALL PACKAGING & DUP
# ------------------------------------------------------------------------------
USER_HOME="${HOME:-/home/temporary-installer}"
TAR_PATH="${USER_HOME}/gdc-diagnostics.tar.gz"

# Format display path replacing local $HOME with '~'
PRINT_PATH="${TAR_PATH}"
if [[ "${TAR_PATH}" == "${USER_HOME}"* ]]; then
  PRINT_PATH="~${TAR_PATH#${USER_HOME}}"
fi

echo "[-] Creating tarball package at ${PRINT_PATH}..."

OUT_BASE=$(basename "${OUT_DIR}")
TAR_SUCCESS=true
if tar -czf "${TAR_PATH}" -C "/tmp" "${OUT_BASE}" 2>/dev/null; then
  :
else
  echo "[-] SKIPPED Permission denied ${PRINT_PATH}"
  TAR_SUCCESS=false
  # Fallback to write inside /tmp RAM directory
  TAR_PATH="/tmp/gdc-diagnostics.tar.gz"
  PRINT_PATH="/tmp/gdc-diagnostics.tar.gz"
  tar -czf "${TAR_PATH}" -C "/tmp" "${OUT_BASE}"
fi

# Duplicate package target to physical mount partition to survive VM reboots (Guarded)
if [ "${IS_PRIVILEGED}" = "true" ] && [ -d "/target" ]; then
  cp "${TAR_PATH}" "/target/gdc-diagnostics.tar.gz" || true
  mkdir -p /target/root
  cp "${TAR_PATH}" "/target/root/gdc-diagnostics.tar.gz" || true
fi

# Output final terminal compilation success message matching requested pattern
echo "[+] SUCCESS: Diagnostics successfully compiled and compressed!"
echo "     - Target RAM path: ${PRINT_PATH}"
