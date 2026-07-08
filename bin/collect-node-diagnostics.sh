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

echo "--- INOTIFY KERNEL LIMITS ---" >> "${OUT_DIR}/report.txt"
echo "max_user_instances:                      $(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo "Unknown")" >> "${OUT_DIR}/report.txt"
echo "max_user_watches:                        $(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo "Unknown")" >> "${OUT_DIR}/report.txt"
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

echo "--- GDC ANSIBLE PROVISIONING RUN AUDITS ---" >> "${OUT_DIR}/report.txt"
if [ "${IS_PRIVILEGED}" = "true" ] || groups | grep -qE "systemd-journal|adm|sudo|root"; then
  # Count the number of provisioning attempts
  runs_started=$(journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c "Starting Ansible Pull" || true)
  runs_succeeded=$(journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c "SUCCESS: All Ready-Linux Post-Install" || true)
  
  # Default to 0 if empty
  runs_started="${runs_started:-0}"
  runs_succeeded="${runs_succeeded:-0}"
  
  # Get timestamps of first and last runs
  first_run_time=$(journalctl -u gdc-provision --no-pager -o short-iso 2>/dev/null | grep "Starting Ansible Pull" | head -n 1 | awk '{print $1}' || echo "N/A")
  last_run_time=$(journalctl -u gdc-provision --no-pager -o short-iso 2>/dev/null | grep "Starting Ansible Pull" | tail -n 1 | awk '{print $1}' || echo "N/A")
  
  echo "Total Ansible-Pull Provisioning Runs Started: ${runs_started}" >> "${OUT_DIR}/report.txt"
  echo "Total Ansible-Pull Provisioning Runs Succeeded: ${runs_succeeded}" >> "${OUT_DIR}/report.txt"
  echo "First Run Timestamp: ${first_run_time}" >> "${OUT_DIR}/report.txt"
  echo "Last Run Timestamp:  ${last_run_time}" >> "${OUT_DIR}/report.txt"
  
  # Determine current status of provisioning service
  if systemctl is-active --quiet gdc-provision 2>/dev/null; then
    sub_state=$(systemctl show gdc-provision --property=SubState 2>/dev/null | cut -d'=' -f2)
    if [ "${sub_state}" = "running" ]; then
      echo "Current Provisioning Status: IN_PROGRESS (Running)" >> "${OUT_DIR}/report.txt"
    else
      if journalctl -u gdc-provision -n 100 --no-pager 2>/dev/null | grep -q "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY"; then
        echo "Current Provisioning Status: COMPLETED (Success)" >> "${OUT_DIR}/report.txt"
      else
        echo "Current Provisioning Status: FAILED (Check logs)" >> "${OUT_DIR}/report.txt"
      fi
    fi
  else
    echo "Current Provisioning Status: INACTIVE (Not started/Failed)" >> "${OUT_DIR}/report.txt"
  fi
else
  echo "Skipped due to lack of permissions to query systemd-journal" >> "${OUT_DIR}/report.txt"
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
import socket

report = {
    "timestamp": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
    "host_metadata": {
        "hostname": subprocess.getoutput("hostname").strip(),
        "kernel": subprocess.getoutput("uname -r").strip(),
        "uefi_boot": os.path.exists("/sys/firmware/efi"),
        "privileged": os.getuid() == 0,
        "inotify_max_user_instances": int(subprocess.getoutput("cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo '0'").strip() or 0),
        "inotify_max_user_watches": int(subprocess.getoutput("cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo '0'").strip() or 0)
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

# 5. System Minimum Requirements Assessment
logical_cpus = os.cpu_count() or 1
physical_cores = logical_cpus
try:
    threads_per_core = int(subprocess.getoutput("lscpu | grep 'Thread(s) per core:' | awk '{print $4}'").strip() or 1)
    physical_cores = max(1, logical_cpus // threads_per_core)
except Exception:
    threads_per_core = 1

cpu_status = "FAIL"
if physical_cores >= 4:
    cpu_status = "OK"
elif physical_cores >= 2:
    cpu_status = "CAUTION"
else:
    cpu_status = "FAIL"

mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
mem_gib = mem_bytes / (1024**3)

mem_status = "FAIL"
if mem_gib >= 16.0:
    mem_status = "OK"
elif mem_gib >= 8.0:
    mem_status = "CAUTION"
else:
    mem_status = "FAIL"

disk_sizes = []
try:
    for dev in os.listdir("/sys/block"):
        if dev.startswith("loop") or dev.startswith("ram") or dev.startswith("dm-") or dev.startswith("sr"):
            continue
        size_file = f"/sys/block/{dev}/size"
        if os.path.exists(size_file):
            with open(size_file, "r") as sf:
                sectors = int(sf.read().strip())
                gib = (sectors * 512) / (1024**3)
                disk_sizes.append(gib)
except Exception:
    pass

disk_sizes.sort(reverse=True)

storage_status = "FAIL_MINIMUM"
total_space = sum(disk_sizes)
if total_space >= 256.0:
    storage_status = "OK"
elif total_space >= 128.0:
    storage_status = "CAUTION"
else:
    storage_status = "FAIL"

# Record statuses
report["system_minimum_requirements"] = {
    "cpu": {
        "status": cpu_status,
        "physical_cores": physical_cores,
        "logical_threads": logical_cpus,
        "hyperthreading_enabled": threads_per_core >= 2
    },
    "memory": {
        "status": mem_status,
        "total_gib": round(mem_gib, 2)
    },
    "storage": {
        "status": storage_status,
        "total_disks": len(disk_sizes),
        "disk_sizes_gib": [round(sz, 2) for sz in disk_sizes]
    },
    "overall_status": f"{{ CPU: {cpu_status}, MEMORY: {mem_status}, STORAGE: {storage_status} }}"
}

# Write results to temporary status file for bash to print to console
try:
    with open("/tmp/gdc_reqs.status", "w") as sf:
        sf.write(f"{{ CPU: {cpu_status}, MEMORY: {mem_status}, STORAGE: {storage_status} }}\n")
except Exception:
    pass

# Append results to report.txt
out_dir_path = "/tmp/gdc-diagnostics" if os.getuid() == 0 else f"/tmp/gdc-diagnostics-{subprocess.getoutput('whoami').strip()}"
try:
    with open(os.path.join(out_dir_path, "report.txt"), "a") as rf:
        rf.write("--- SYSTEM MINIMUM REQUIREMENTS CHECK ---\n")
        rf.write(f"CPU:                                     [{cpu_status}] ({physical_cores} physical cores, {logical_cpus} threads, HT={'enabled' if threads_per_core >= 2 else 'disabled'})\n")
        rf.write(f"Memory:                                  [{mem_status}] ({round(mem_gib, 2)} GiB total RAM)\n")
        
        storage_desc = f"{round(sum(disk_sizes), 2)} GiB total space across {len(disk_sizes)} disk(s)" if disk_sizes else "No disks detected"
        rf.write(f"Storage:                                 [{storage_status}] ({storage_desc})\n")
        rf.write(f"Overall Health Status:                   {{ CPU: {cpu_status}, MEMORY: {mem_status}, STORAGE: {storage_status} }}\n")
        rf.write("\n")
except Exception:
    pass

# GDC Endpoints Readiness Audit
domains = [
    "accounts.google.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "connectgateway.googleapis.com",
    "containerregistry.googleapis.com",
    "gkeconnect.googleapis.com",
    "gkehub.googleapis.com",
    "gkeonprem.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "gkeonprem.mtls.googleapis.com",
    "oauth2.googleapis.com",
    "securetoken.googleapis.com",
    "servicecontrol.googleapis.com",
    "serviceusage.googleapis.com",
    "stackdriver.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
    "www.googleapis.com",
    "gcr.io",
    "k8s.gcr.io",
    "logging.gdce.googleapis.com",
    "storage.gdce.googleapis.com"
]

report["gdc_endpoints_readiness"] = {}
endpoint_counts = {}

# Query the local IP addresses of the interfaces
mgmt_ip = subprocess.getoutput(f"ip -o -4 addr show dev {mgmt_iface} 2>/dev/null | awk '{{print $4}}' | cut -d'/' -f1 | head -n 1").strip() or "127.0.0.1"
k8s_ip = subprocess.getoutput(f"ip -o -4 addr show dev {k8s_iface} 2>/dev/null | awk '{{print $4}}' | cut -d'/' -f1 | head -n 1").strip() or "127.0.0.1"

# Prepare report.txt entries
try:
    with open(os.path.join(out_dir_path, "report.txt"), "a") as rf:
        rf.write("--- GDC ENDPOINTS READINESS AUDIT ---\n")
except Exception:
    pass

for name_lbl, ip_addr, dev_lbl in [("management", mgmt_ip, mgmt_iface), ("kubernetes", k8s_ip, k8s_iface)]:
    if not ip_addr or ip_addr == "127.0.0.1":
        continue
    
    report["gdc_endpoints_readiness"][name_lbl] = {}
    resolved_count = 0
    connected_count = 0
    
    try:
        with open(os.path.join(out_dir_path, "report.txt"), "a") as rf:
            rf.write(f"Interface: {dev_lbl} ({name_lbl.capitalize()} Network - IP: {ip_addr})\n")
    except Exception:
        pass
        
    for dom in domains:
        resolved_ip = None
        dns_status = "FAILED"
        tcp_status = "SKIPPED"
        
        # A. DNS Resolution Check
        try:
            resolved_ip = socket.gethostbyname(dom)
            dns_status = "RESOLVED"
            resolved_count += 1
        except Exception:
            pass
            
        # B. TCP Port 443 Check
        if resolved_ip:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                # BIND TO DEVICE IF ROOT & TESTING KUBERNETES INTERFACE FOR CORRECT VRF ROUTING
                if name_lbl == "kubernetes" and os.getuid() == 0:
                    try:
                        s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_BINDTODEVICE", 25), bytes(dev_lbl, "utf-8"))
                    except Exception:
                        pass
                s.bind((ip_addr, 0))
                s.connect((resolved_ip, 443))
                s.close()
                tcp_status = "CONNECTED"
                connected_count += 1
            except Exception:
                tcp_status = "FAILED"
                
        report["gdc_endpoints_readiness"][name_lbl][dom] = {
            "dns_resolved": dns_status == "RESOLVED",
            "resolved_ip": resolved_ip,
            "tcp_connected": tcp_status == "CONNECTED"
        }
        
        try:
            with open(os.path.join(out_dir_path, "report.txt"), "a") as rf:
                rf.write(f"  - {dom:40} DNS: {dns_status:8} ({resolved_ip or 'None':15}) | TCP: {tcp_status}\n")
        except Exception:
            pass
            
    try:
        with open(os.path.join(out_dir_path, "report.txt"), "a") as rf:
            rf.write(f"Summary: {resolved_count}/{len(domains)} Resolved | {connected_count}/{len(domains)} Connected\n\n")
    except Exception:
        pass
        
    endpoint_counts[name_lbl] = {"resolved": resolved_count, "connected": connected_count}

# Save counts to temporary endpoints status file for bash to read and print
try:
    with open("/tmp/gdc_endpoints.status", "w") as sf:
        sf.write(f"management:{endpoint_counts.get('management', {}).get('resolved', 0)}:{endpoint_counts.get('management', {}).get('connected', 0)}\n")
        sf.write(f"kubernetes:{endpoint_counts.get('kubernetes', {}).get('resolved', 0)}:{endpoint_counts.get('kubernetes', {}).get('connected', 0)}\n")
except Exception:
    pass

# ==============================================================================
# GDC SOFTWARE-ONLY BARE METAL OS PREREQUISITES AND STANDALONE PRE-FLIGHT AUDIT
# ==============================================================================

gdc_checks = {}

# 1. cgroupsv2 active (no cgroupsv1 detected)
cgroupsv1_detected = False
try:
    with open("/proc/mounts", "r") as f:
        for line in f:
            if "cgroup" in line and "cgroup2" not in line:
                cgroupsv1_detected = True
                break
except Exception:
    pass
gdc_checks["cgroupsv2"] = {
    "status": "FAIL" if cgroupsv1_detected else "PASS",
    "details": "cgroupsv1 detected in system mounts!" if cgroupsv1_detected else "Pure cgroupsv2 active"
}

# 2. BPF JIT compiler active
bpf_jit_enabled = False
bpf_val = "0"
try:
    with open("/proc/sys/net/core/bpf_jit_enable", "r") as f:
        bpf_val = f.read().strip()
        if bpf_val == "1":
            bpf_jit_enabled = True
except Exception:
    pass
if not bpf_jit_enabled:
    try:
        kernel_ver = subprocess.getoutput("uname -r").strip()
        config_path = f"/boot/config-{kernel_ver}"
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                for line in f:
                    if "CONFIG_BPF_JIT=y" in line:
                        bpf_jit_enabled = True
                        bpf_val = "y"
                        break
    except Exception:
        pass
gdc_checks["bpf_jit_compiler"] = {
    "status": "PASS" if bpf_jit_enabled else "FAIL",
    "details": f"BPF JIT compiler is enabled (state={bpf_val})" if bpf_jit_enabled else "BPF JIT compiler is disabled"
}

# 3. Apt package manager integrity
apt_check_ok = False
apt_err_msg = ""
try:
    res = subprocess.run(["apt-get", "check"], capture_output=True, text=True)
    if res.returncode == 0:
        apt_check_ok = True
        apt_err_msg = "No package errors"
    else:
        apt_err_msg = (res.stderr or res.stdout or "Error return code").strip().split('\n')[0]
except Exception as e:
    apt_err_msg = str(e)
gdc_checks["apt_package_manager"] = {
    "status": "PASS" if apt_check_ok else "FAIL",
    "details": apt_err_msg
}

# 4. UFW status (should be inactive)
ufw_inactive = True
ufw_status_str = "inactive"
try:
    res = subprocess.run(["ufw", "status"], capture_output=True, text=True)
    if "Status: active" in res.stdout or "active" in res.stdout.lower():
        ufw_inactive = False
        ufw_status_str = "active"
except Exception:
    pass
gdc_checks["ufw_firewall"] = {
    "status": "PASS" if ufw_inactive else "FAIL",
    "details": f"UFW firewall is {ufw_status_str}"
}

# 5. NTP / Time synchronization
time_synchronized = False
ntp_details = "Not synchronized"
try:
    out = subprocess.getoutput("timedatectl show --property=NTPSynchronized 2>/dev/null").strip()
    if "NTPSynchronized=yes" in out:
        time_synchronized = True
        ntp_details = "Synchronized (timedatectl yes)"
    else:
        status_out = subprocess.getoutput("timedatectl status 2>/dev/null")
        if "System clock synchronized: yes" in status_out or "synchronized: yes" in status_out.lower():
            time_synchronized = True
            ntp_details = "Synchronized (System clock synchronized: yes)"
except Exception:
    pass
gdc_checks["time_synchronization"] = {
    "status": "PASS" if time_synchronized else "FAIL",
    "details": ntp_details
}

# 6. Linux inotify limits
max_instances = 0
max_watches = 0
try:
    with open("/proc/sys/fs/inotify/max_user_instances", "r") as f:
        max_instances = int(f.read().strip())
except Exception:
    pass
try:
    with open("/proc/sys/fs/inotify/max_user_watches", "r") as f:
        max_watches = int(f.read().strip())
except Exception:
    pass
inotify_ok = (max_instances >= 8192) and (max_watches >= 524288)
gdc_checks["inotify_limits"] = {
    "status": "PASS" if inotify_ok else "FAIL",
    "details": f"instances={max_instances} (req>=8192), watches={max_watches} (req>=524288)"
}

# 7. Iptables backend (uses nf_tables)
ipt_out = ""
iptables_ok = False
try:
    ipt_out = subprocess.getoutput("iptables --version 2>/dev/null").strip()
    if "nf_tables" in ipt_out or "nftables" in ipt_out or "nf_table" in ipt_out.lower():
        iptables_ok = True
    elif "legacy" in ipt_out:
        iptables_ok = False
    else:
        iptables_ok = True  # Default ok if installed
except Exception:
    pass
gdc_checks["iptables_backend"] = {
    "status": "PASS" if iptables_ok else "FAIL",
    "details": f"Iptables backend is compliant: {ipt_out}" if iptables_ok else f"Legacy iptables detected! ({ipt_out})"
}

# 8. Docker Daemon version >= 20.10.0
docker_ok = False
doc_ver = "Unknown"
try:
    doc_ver = subprocess.getoutput("docker --version 2>/dev/null").strip()
    if "version" in doc_ver.lower():
        parts = doc_ver.lower().split("version")[-1].strip().split(",")
        ver_str = parts[0].strip().split(" ")[0].strip()
        ver_parts = [int(p) for p in ver_str.split(".") if p.isdigit()]
        if ver_parts and ver_parts[0] >= 20:
            if ver_parts[0] > 20 or (len(ver_parts) > 1 and ver_parts[1] >= 10):
                docker_ok = True
except Exception:
    pass
gdc_checks["docker_version"] = {
    "status": "PASS" if docker_ok else "FAIL",
    "details": f"Docker {doc_ver} matches required >= 20.10.0" if docker_ok else f"Docker version non-compliant: {doc_ver}"
}

# 9. Clean Installation Paths (/var/lib/etcd and /etc/kubernetes)
etcd_clean = True
k8s_clean = True
if os.path.exists("/var/lib/etcd"):
    etcd_files = [f for f in os.listdir("/var/lib/etcd") if f != "lost+found"]
    if etcd_files:
        etcd_clean = False
if os.path.exists("/etc/kubernetes") and os.listdir("/etc/kubernetes"):
    k8s_clean = False
paths_clean = etcd_clean and k8s_clean
gdc_checks["clean_installation_paths"] = {
    "status": "PASS" if paths_clean else "FAIL",
    "details": "Installation directories /var/lib/etcd and /etc/kubernetes are clean/empty" if paths_clean else f"Dirty directories! etcd_clean={etcd_clean}, k8s_clean={k8s_clean}"
}

# 10. gcloud CLI exists
gcloud_path = subprocess.getoutput("which gcloud 2>/dev/null").strip() or ("/usr/local/bin/gcloud" if os.path.exists("/usr/local/bin/gcloud") else None)
gdc_checks["gcloud_cli"] = {
    "status": "PASS" if gcloud_path else "FAIL",
    "details": f"Found at {gcloud_path}" if gcloud_path else "Not found on PATH"
}

# 11. /var/gdc-install directory exists
gdc_admin_exists = os.path.isdir("/var/gdc-install")
gdc_checks["gdc_admin_dir"] = {
    "status": "PASS" if gdc_admin_exists else "FAIL",
    "details": "Directory exists" if gdc_admin_exists else "Missing /var/gdc-install"
}

# 12. /var/gdc-install/keys directory exists
gdc_keys_exists = os.path.isdir("/var/gdc-install/keys")
gdc_checks["gdc_keys_dir"] = {
    "status": "PASS" if gdc_keys_exists else "FAIL",
    "details": "Directory exists" if gdc_keys_exists else "Missing keys directory"
}

# 13. TPM 2.0 Security Module
tpm_exists = os.path.exists("/dev/tpmrm0")
gdc_checks["tpm_security"] = {
    "status": "PASS" if tpm_exists else "FAIL",
    "details": "TPM 2.0 device present" if tpm_exists else "No /dev/tpmrm0"
}

# 14. curl tool exists
curl_path = subprocess.getoutput("which curl 2>/dev/null").strip()
gdc_checks["curl_tool"] = {
    "status": "PASS" if curl_path else "FAIL",
    "details": f"Found at {curl_path}" if curl_path else "Not found on PATH"
}

# 15. ss tool exists
ss_path = subprocess.getoutput("which ss 2>/dev/null").strip()
gdc_checks["ss_tool"] = {
    "status": "PASS" if ss_path else "FAIL",
    "details": f"Found at {ss_path}" if ss_path else "Not found on PATH"
}

# 16. Services Check - Gitea
gitea_active = report["services"]["gitea"]["active"]
gdc_checks["gitea_service"] = {
    "status": "PASS" if gitea_active else "FAIL",
    "details": "Active & Running" if gitea_active else "Inactive/Failed"
}

# 17. Services Check - Nexus
nexus_active = report["services"]["nexus"]["active"]
gdc_checks["nexus_service"] = {
    "status": "PASS" if nexus_active else "FAIL",
    "details": "Active & Running" if nexus_active else "Inactive/Failed"
}

# 18. Services Check - GDC Provision
gdc_provision_active = report["services"]["gdc-provision"]["active"]
gdc_checks["gdc_provision_service"] = {
    "status": "PASS" if gdc_provision_active else "FAIL",
    "details": "Active & Running" if gdc_provision_active else "Inactive/Failed"
}

# 19. Services Check - SSH
ssh_active = report["services"]["ssh"]["active"]
gdc_checks["ssh_service"] = {
    "status": "PASS" if ssh_active else "FAIL",
    "details": "Active & Running" if ssh_active else "Inactive/Failed"
}

# 20. Services Check - Systemd Networkd
networkd_active = report["services"]["systemd-networkd"]["active"]
gdc_checks["networkd_service"] = {
    "status": "PASS" if networkd_active else "FAIL",
    "details": "Active & Running" if networkd_active else "Inactive/Failed"
}

# 21. Storage Directories Space (Partition Groups)
dir_reqs = [
    ("/", 4 * 1024**3, "Root Directory"),
    ("/var/log", 12 * 1024**3, "Fluent-Bit Buffers"),
    ("/var/opt/buffered-metrics", 10016 * 1024**2, "Buffered Metrics"),
    ("/var/lib/containerd", 30 * 1024**3, "Containerd Storage"),
    ("/var/lib/kubelet", 500 * 1024**2, "Kubelet Storage"),
    ("/var/lib/etcd", 20 * 1024**3, "Etcd Database"),
    ("/var/lib/etcd-events", 5 * 1024**3, "Etcd Events")
]

partition_groups = {}
for path, req_bytes, desc in dir_reqs:
    cur_path = path
    while not os.path.exists(cur_path):
        parent = os.path.dirname(cur_path)
        if parent == cur_path:
            break
        cur_path = parent
    try:
        dev_id = os.stat(cur_path).st_dev
        st = os.statvfs(cur_path)
        free_bytes = st.f_bavail * st.f_frsize
    except Exception:
        dev_id = 0
        free_bytes = 0
    
    if dev_id not in partition_groups:
        partition_groups[dev_id] = {
            "free_bytes": free_bytes,
            "paths": [],
            "required_sum": 0,
            "actual_mount": cur_path
        }
    partition_groups[dev_id]["paths"].append((path, req_bytes, desc))
    partition_groups[dev_id]["required_sum"] += req_bytes

storage_partitions_ok = True
storage_partition_details = []
for dev_id, group in partition_groups.items():
    free_gib = group["free_bytes"] / (1024**3)
    req_gib = group["required_sum"] / (1024**3)
    status = "PASS" if group["free_bytes"] >= group["required_sum"] else "FAIL"
    if status == "FAIL":
        storage_partitions_ok = False
    paths_str = ", ".join([p[2] for p in group["paths"]])
    storage_partition_details.append({
        "mount": group["actual_mount"],
        "shared_by": paths_str,
        "free_gib": round(free_gib, 2),
        "required_gib": round(req_gib, 2),
        "status": status
    })

# Overwriting GDC OS Prerequisites check in the report
report["gdc_os_prerequisites"] = {
    "software_checks": gdc_checks,
    "storage_partitions": storage_partition_details,
    "overall_compliance": "PASS" if (all(c["status"] == "PASS" for c in gdc_checks.values()) and storage_partitions_ok) else "FAIL"
}

# APPEND THE COMPREHENSIVE TEXT TABLE TO THE BOTTOM OF REPORT.TXT
overall_prereq_status = report["gdc_os_prerequisites"]["overall_compliance"]
try:
    with open(os.path.join(out_dir_path, "report.txt"), "a") as rf:
        rf.write("\n")
        rf.write("=====================================================================================================\n")
        rf.write("===             GDC SOFTWARE-ONLY BARE METAL OS PREREQUISITES                                     ===\n")
        rf.write("=====================================================================================================\n")
        rf.write(f"{'Requirement':35} {'Target':24} {'Actual':34} {'Status':8}\n")
        rf.write("-" * 101 + "\n")
        
        # 1. cgroupsv2
        rf.write(f"{'cgroupsv2 Active':35} {'No cgroupsv1':24} {gdc_checks['cgroupsv2']['details']:34} [ {gdc_checks['cgroupsv2']['status']} ]\n")
        # 2. BPF JIT
        rf.write(f"{'BPF JIT Compiler':35} {'Enabled (1)':24} {('Active (' + bpf_val + ')'):34} [ {gdc_checks['bpf_jit_compiler']['status']} ]\n")
        # 3. Package manager
        rf.write(f"{'Apt Package Manager':35} {'Healthy':24} {gdc_checks['apt_package_manager']['details'][:34]:34} [ {gdc_checks['apt_package_manager']['status']} ]\n")
        # 4. UFW
        rf.write(f"{'UFW Firewall':35} {'Inactive':24} {gdc_checks['ufw_firewall']['details'][:34]:34} [ {gdc_checks['ufw_firewall']['status']} ]\n")
        # 5. Time sync
        rf.write(f"{'System Time Sync':35} {'Synchronized':24} {gdc_checks['time_synchronization']['details'][:34]:34} [ {gdc_checks['time_synchronization']['status']} ]\n")
        # 6. inotify
        rf.write(f"{'Linux inotify Limits':35} {'Inst>=8192':24} {('inst=' + str(max_instances)):34} [ {gdc_checks['inotify_limits']['status']} ]\n")
        rf.write(f"{'':35} {'Watch>=524288':24} {('watch=' + str(max_watches)):34} [ {gdc_checks['inotify_limits']['status']} ]\n")
        # 7. iptables
        rf.write(f"{'Iptables Backend':35} {'nf_tables':24} {('compliant' if iptables_ok else 'legacy'):34} [ {gdc_checks['iptables_backend']['status']} ]\n")
        # 8. docker
        rf.write(f"{'Docker Version':35} {'>= 20.10.0':24} {(doc_ver.split(' ')[-1] if ' ' in doc_ver else doc_ver)[:34]:34} [ {gdc_checks['docker_version']['status']} ]\n")
        # 9. Clean Installation paths
        rf.write(f"{'Clean Installation Paths':35} {'etcd & k8s empty':24} {('Clean' if paths_clean else 'Dirty'):34} [ {gdc_checks['clean_installation_paths']['status']} ]\n")
        
        # 10. gcloud SDK CLI
        rf.write(f"{'gcloud SDK CLI':35} {'Exists on PATH':24} {gdc_checks['gcloud_cli']['details'][:34]:34} [ {gdc_checks['gcloud_cli']['status']} ]\n")
        # 11. GDC Install Directory
        rf.write(f"{'GDC Install Directory':35} {'/var/gdc-install':24} {gdc_checks['gdc_admin_dir']['details'][:34]:34} [ {gdc_checks['gdc_admin_dir']['status']} ]\n")
        # 12. GDC Install Keys
        rf.write(f"{'GDC Install Keys':35} {'Keys folder':24} {gdc_checks['gdc_keys_dir']['details'][:34]:34} [ {gdc_checks['gdc_keys_dir']['status']} ]\n")
        # 13. curl Diagnostic Tool
        rf.write(f"{'curl Diagnostic Tool':35} {'Installed':24} {gdc_checks['curl_tool']['details'][:34]:34} [ {gdc_checks['curl_tool']['status']} ]\n")
        # 14. ss Socket Tool
        rf.write(f"{'ss Socket Tool':35} {'Installed':24} {gdc_checks['ss_tool']['details'][:34]:34} [ {gdc_checks['ss_tool']['status']} ]\n")
        # 15. TPM 2.0 Security Module
        rf.write(f"{'TPM 2.0 Security Device':35} {'/dev/tpmrm0 exists':24} {gdc_checks['tpm_security']['details'][:34]:34} [ {gdc_checks['tpm_security']['status']} ]\n")
        
        # Services Section
        rf.write("-" * 101 + "\n")
        rf.write("GDC Component Services Status:\n")
        rf.write(f"{'Service Unit':35} {'Required State':24} {'Current State':34} {'Status':8}\n")
        rf.write("-" * 101 + "\n")
        rf.write(f"{'Gitea Git Server':35} {'Active & Running':24} {gdc_checks['gitea_service']['details']:34} [ {gdc_checks['gitea_service']['status']} ]\n")
        rf.write(f"{'Nexus Package Hub':35} {'Active & Running':24} {gdc_checks['nexus_service']['details']:34} [ {gdc_checks['nexus_service']['status']} ]\n")
        rf.write(f"{'GDC Provision Service':35} {'Active & Running':24} {gdc_checks['gdc_provision_service']['details']:34} [ {gdc_checks['gdc_provision_service']['status']} ]\n")
        rf.write(f"{'SSH Terminal Server':35} {'Active & Running':24} {gdc_checks['ssh_service']['details']:34} [ {gdc_checks['ssh_service']['status']} ]\n")
        rf.write(f"{'Systemd Networkd':35} {'Active & Running':24} {gdc_checks['networkd_service']['details']:34} [ {gdc_checks['networkd_service']['status']} ]\n")
        
        # Partition space section
        rf.write("-" * 101 + "\n")
        rf.write("Storage Directories Free Space partitions:\n")
        rf.write(f"{'Mount Point':25} {'Free (GiB)':15} {'Required (GiB)':18} {'Status':10} {'Shared By Systems':32}\n")
        rf.write("-" * 101 + "\n")
        for p in storage_partition_details:
            rf.write(f"{p['mount']:25} {p['free_gib']:<15} {p['required_gib']:<18} [ {p['status']} ]     {p['shared_by'][:30]:32}\n")
        rf.write("-" * 101 + "\n")
        rf.write(f"OVERALL GDC PRE-FLIGHT COMPLIANCE STATUS: [ {overall_prereq_status} ]\n")
        rf.write("=====================================================================================================\n")

        # New Section: Disks & LVM Volumes Enumeration
        rf.write("\n")
        rf.write("=====================================================================================================\n")
        rf.write("===             GDC STORAGE: DISKS & LVM VOLUMES ENUMERATION                                      ===\n")
        rf.write("=====================================================================================================\n")
        lsblk_tree = subprocess.getoutput("lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT 2>/dev/null || lsblk")
        rf.write(lsblk_tree + "\n")
        rf.write("=====================================================================================================\n")

        # New Section: Networking Interface Details
        rf.write("\n")
        rf.write("=====================================================================================================\n")
        rf.write("===                     GDC NETWORKING INTERFACE DETAILS                                          ===\n")
        rf.write("=====================================================================================================\n")
        rf.write(f"{'Interface':25} {'IP Address':25} {'Link Status':15} {'Gateway':25}\n")
        rf.write("-" * 90 + "\n")
        
        # Active gateway discovery
        gateways = {}
        try:
            route_out = subprocess.getoutput("ip route show").strip().split('\n')
            for line in route_out:
                if "default via" in line:
                    parts = line.split()
                    dev = parts[parts.index("dev") + 1] if "dev" in parts else "unknown"
                    gw = parts[parts.index("via") + 1] if "via" in parts else "unknown"
                    gateways[dev] = gw
        except Exception:
            pass

        try:
            table20_out = subprocess.getoutput("ip route show table 20").strip().split('\n')
            for line in table20_out:
                if "default via" in line:
                    parts = line.split()
                    dev = parts[parts.index("dev") + 1] if "dev" in parts else "unknown"
                    gw = parts[parts.index("via") + 1] if "via" in parts else "unknown"
                    gateways[dev] = gw
        except Exception:
            pass

        try:
            for iface in sorted(os.listdir("/sys/class/net")):
                if iface == "lo":
                    continue
                ip = "None"
                try:
                    ip_out = subprocess.getoutput(f"ip -o -4 addr show dev {iface} 2>/dev/null")
                    if ip_out:
                        ip = ip_out.split()[3].split('/')[0]
                except Exception:
                    pass
                status = "DOWN"
                try:
                    with open(f"/sys/class/net/{iface}/operstate", "r") as f:
                        status = f.read().strip().upper()
                except Exception:
                    pass
                gw = gateways.get(iface, "None")
                rf.write(f"{iface:25} {ip:25} {status:15} {gw:25}\n")
        except Exception:
            pass
        rf.write("-" * 90 + "\n")
        
        # Egress summary
        mgmt_summary = f"{endpoint_counts.get('management', {}).get('connected', 0)}/25 Connected"
        k8s_summary = f"{endpoint_counts.get('kubernetes', {}).get('connected', 0)}/25 Connected"
        rf.write("Domain Access Efficacy (Google APIs):\n")
        rf.write(f"  - Management Network:     {mgmt_summary} domains accessed successfully\n")
        rf.write(f"  - Kubernetes VRF Network: {k8s_summary} domains accessed successfully\n")
        rf.write("=====================================================================================================\n")
except Exception as e:
    pass

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

# Gcloud CLI configuration and version check
echo "     [+] GDC SDK check"
echo "--- GDC GCLOUD CLI CHECK ---" >> "${OUT_DIR}/report.txt"
if [ -x /usr/local/bin/gcloud ]; then
  echo "gcloud CLI found at /usr/local/bin/gcloud" >> "${OUT_DIR}/report.txt"
  echo "gcloud Version Information:" >> "${OUT_DIR}/report.txt"
  /usr/local/bin/gcloud version >> "${OUT_DIR}/report.txt" 2>&1
  
  # Also write it to a dedicated file in logs to make it easy to find in the tarball
  /usr/local/bin/gcloud version > "${OUT_DIR}/logs/gcloud-version.txt" 2>&1
else
  echo "gcloud CLI is not present at /usr/local/bin/gcloud" >> "${OUT_DIR}/report.txt"
fi
echo "" >> "${OUT_DIR}/report.txt"

# ------------------------------------------------------------------------------
# SECTION 14: SYSTEMD JOURNALS EXTRACTION (Guarded)
# ------------------------------------------------------------------------------
echo "[-] Saving active systemd service journals..."
for svc in gdc-provision gitea nexus ssh systemd-networkd; do
  if [ "${IS_PRIVILEGED}" = "true" ] || groups | grep -qE "systemd-journal|adm|sudo|root"; then
    if [ "${svc}" = "gdc-provision" ]; then
      journalctl -u "${svc}" --no-pager -n 10000 > "${OUT_DIR}/logs/${svc}.log" 2>/dev/null || echo "Unable to query journal for ${svc}." > "${OUT_DIR}/logs/${svc}.log"
    else
      journalctl -u "${svc}" --no-pager -n 1000 > "${OUT_DIR}/logs/${svc}.log" 2>/dev/null || echo "Unable to query journal for ${svc}." > "${OUT_DIR}/logs/${svc}.log"
    fi
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
if [[ -n "${ping_mgmt}" ]] && echo "${ping_mgmt}" | grep -q "rtt"; then
  avg_rtt=$(echo "${ping_mgmt}" | tail -n 1 | cut -d'/' -f5)
  echo "     [+] Management Gateway (${MGMT_GATEWAY}): REACHABLE (${avg_rtt}ms)"
  echo "Management Gateway (${MGMT_GATEWAY}) via ${MGMT_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  echo "     [-] Management Gateway (${MGMT_GATEWAY}): UNREACHABLE"
  echo "Management Gateway (${MGMT_GATEWAY}) via ${MGMT_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
fi

# 2. Ping Kubernetes Gateway (expecting REACHABLE within VRF)
ping_k8s=""
if [ "${IS_PRIVILEGED}" = "true" ]; then
  ping_k8s=$(ip vrf exec vrf-k8s ping -c 2 -W 1 "${K8S_GATEWAY}" 2>/dev/null || echo "")
fi

if [[ -n "${ping_k8s}" ]] && echo "${ping_k8s}" | grep -q "rtt"; then
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
if ping -c 2 -W 1 -I "${MGMT_IFACE}" "${K8S_IP}" 2>/dev/null | grep -q "rtt"; then
  echo "     [!] Cross-Link Isolation:  LEAKING (Failed)"
  echo "Cross-Link Isolation between ${MGMT_IFACE} and ${K8S_IFACE}: LEAKING" >> "${OUT_DIR}/report.txt"
else
  echo "     [+] Cross-Link Isolation:  SECURED (Blocked)"
  echo "Cross-Link Isolation between ${MGMT_IFACE} and ${K8S_IFACE}: SECURED" >> "${OUT_DIR}/report.txt"
fi

# 4. Ping Public WAN Access
ping_wan=$(ping -c 2 -W 1 -I "${MGMT_IFACE}" 8.8.8.8 2>/dev/null || echo "")
if [[ -n "${ping_wan}" ]] && echo "${ping_wan}" | grep -q "rtt"; then
  avg_rtt=$(echo "${ping_wan}" | tail -n 1 | cut -d'/' -f5)
  echo "     [+] Public WAN (8.8.8.8):  REACHABLE (${avg_rtt}ms)"
  echo "Public WAN (8.8.8.8) via ${MGMT_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  echo "     [-] Public WAN (8.8.8.8):  UNREACHABLE"
  echo "Public WAN (8.8.8.8) via ${MGMT_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
fi

# 5. GDC Endpoint Resolution & TCP Audits
echo "     [+] GDC Endpoint Resolution & TCP Audits:"
if [ -f /tmp/gdc_endpoints.status ]; then
  while IFS=':' read -r iface resolved connected || [[ -n "$iface" ]]; do
    if [ "${iface}" = "management" ]; then
      echo "          - Management (${MGMT_IFACE}):   ${resolved}/25 Resolved | ${connected}/25 Connected"
    elif [ "${iface}" = "kubernetes" ]; then
      echo "          - Kubernetes (${K8S_IFACE}): ${resolved}/25 Resolved | ${connected}/25 Connected"
    fi
  done < /tmp/gdc_endpoints.status
else
  echo "          - GDC Endpoint Audits: Skipped (Status metadata missing)"
fi
echo "" >> "${OUT_DIR}/report.txt"

# Output minimum requirements to console
echo "[-] System Minimum Requirements:         $(cat /tmp/gdc_reqs.status 2>/dev/null || echo '{ CPU: Unknown, MEMORY: Unknown, STORAGE: Unknown }')"

# ------------------------------------------------------------------------------
# SECTION 16: TARBALL PACKAGING & DUP
# ------------------------------------------------------------------------------
USER_HOME="${HOME:-/home/temporary-installer}"
TIMESTAMP=$(date +'%d-%b-%Y-%H-%M' | tr '[:lower:]' '[:upper:]')
TAR_PATH="${USER_HOME}/gdc-node-diagnostics-${TIMESTAMP}.tar.gz"

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
  TAR_PATH="/tmp/gdc-node-diagnostics-${TIMESTAMP}.tar.gz"
  PRINT_PATH="/tmp/gdc-node-diagnostics-${TIMESTAMP}.tar.gz"
  tar -czf "${TAR_PATH}" -C "/tmp" "${OUT_BASE}"
fi

# Duplicate package target to physical mount partition to survive VM reboots (Guarded)
if [ "${IS_PRIVILEGED}" = "true" ] && [ -d "/target" ]; then
  cp "${TAR_PATH}" "/target/gdc-node-diagnostics-${TIMESTAMP}.tar.gz" || true
  mkdir -p /target/root
  cp "${TAR_PATH}" "/target/root/gdc-node-diagnostics-${TIMESTAMP}.tar.gz" || true
fi

# Output final terminal compilation success message matching requested pattern
echo "[+] SUCCESS: Diagnostics successfully compiled and compressed!"
echo "     - Target RAM path: ${PRINT_PATH}"

# ------------------------------------------------------------------------------
# SECTION 17: WEBHOOK LOGGING COMPANION UPLOAD (ALWAYS RUN)
# ------------------------------------------------------------------------------
COMPANION_INGEST_URL="http://gdc-companion.ensor-labs.com/v1/machine-reports/ingest"
echo "[-] Uploading diagnostics tarball to GDC Ingestion Companion..."
if command -v curl &>/dev/null; then
  # Post the file using multipart/form-data
  upload_res=$(curl -s -o /dev/null -w "%{http_code}" -F "file=@${TAR_PATH}" "${COMPANION_INGEST_URL}" || echo "CURL_ERROR")
  if [ "${upload_res}" = "200" ] || [ "${upload_res}" = "201" ]; then
    echo "  [x] Successfully uploaded diagnostics to companion (HTTP ${upload_res})"
  else
    echo "  [!] Warning: Failed to upload diagnostics to companion (HTTP code: ${upload_res})"
  fi
else
  echo "  [!] Curl is missing. Cannot upload diagnostics."
fi
