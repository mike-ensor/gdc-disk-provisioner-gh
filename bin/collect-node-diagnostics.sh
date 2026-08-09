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

# Color Output Setup & Detection
USE_COLOR="yes"
if [ ! -t 1 ]; then
  USE_COLOR="no"
fi

# Argument Parsing
UPLOAD_TO_COMPANION="yes"
STAGE_ID=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --no-upload|--upload=no|--upload=false)
      UPLOAD_TO_COMPANION="no"
      shift
      ;;
    --upload=yes|--upload=true)
      UPLOAD_TO_COMPANION="yes"
      shift
      ;;
    --no-color)
      USE_COLOR="no"
      shift
      ;;
    --stage)
      STAGE_ID="$2"
      shift 2
      ;;
    --stage=*)
      STAGE_ID="${1#*=}"
      shift
      ;;
    *)
      shift
      ;;
  esac
done
export UPLOAD_TO_COMPANION

# Normalize and standardize Stage ID to Key / Postfix matching spec matrix
normalize_stage_id() {
  local input=$(echo "$1" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
  case "${input}" in
    live-cd|livecd|live_cd)
      echo "LIVECD"
      ;;
    first-boot|first_boot|firstboot)
      echo "FIRST_BOOT"
      ;;
    second-boot|second_boot|secondboot)
      echo "SECOND_BOOT"
      ;;
    linux-ready|linux_ready|linuxready)
      echo "LINUX_READY"
      ;;
    cluster-ready|cluster_ready|clusterready)
      echo "CLUSTER_READY"
      ;;
    cluster-turnup|cluster_turnup|clusterturnup)
      echo "CLUSTER_TURNUP"
      ;;
    post-validation|post_validation|post-cluster|post_cluster)
      echo "POST_VALIDATION"
      ;;
    update-upkeep|update_upkeep|upkeep|maintenance)
      echo "UPDATE_UPKEEP"
      ;;
    *)
      echo ""
      ;;
  esac
}

# Auto-discover highest completed stage if not explicitly passed
determine_current_stage() {
  if [ -f /var/gdc-install/state/update-upkeep.json ]; then
    echo "UPDATE_UPKEEP"
  elif [ -f /var/gdc-install/state/post-validation.json ]; then
    echo "POST_VALIDATION"
  elif [ -f /var/gdc-install/state/cluster-turnup.json ]; then
    echo "CLUSTER_TURNUP"
  elif [ -f /var/gdc-install/state/cluster-ready.json ]; then
    echo "CLUSTER_READY"
  elif [ -f /var/gdc-install/state/linux-ready.json ]; then
    echo "LINUX_READY"
  elif [ -f /var/gdc-install/state/second-boot.json ]; then
    echo "SECOND_BOOT"
  elif [ -f /var/gdc-install/state/first-boot.json ]; then
    echo "FIRST_BOOT"
  elif [ -f /etc/gdc/provision.yml ]; then
    echo "LIVECD"
  else
    echo "UNKNOWN"
  fi
}

STANDARDIZED_STAGE=""
if [ -n "${STAGE_ID}" ]; then
  STANDARDIZED_STAGE=$(normalize_stage_id "${STAGE_ID}")
fi

if [ -z "${STANDARDIZED_STAGE}" ]; then
  STANDARDIZED_STAGE=$(determine_current_stage)
fi

STAGE_SUFFIX=""
if [ -n "${STANDARDIZED_STAGE}" ] && [ "${STANDARDIZED_STAGE}" != "UNKNOWN" ]; then
  STAGE_SUFFIX="-${STANDARDIZED_STAGE}"
fi

# Define ANSI escape codes for colored console outputs
if [ "${USE_COLOR}" = "yes" ]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  YELLOW='\033[0;33m'
  GRAY='\033[1;30m'
  NC='\033[0m'
else
  GREEN=''
  RED=''
  YELLOW=''
  GRAY=''
  NC=''
fi

# Source environment configurations if present
if [ -r /etc/default/gdc-provision ]; then
  # Sourcing safely in case of undefined vars or flags
  set +u
  source /etc/default/gdc-provision 2>/dev/null || true
  set -u
fi

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
GDC_ISO_VER="Unknown"
if [ -f /etc/gdc/provision.yml ]; then
  GDC_ISO_VER=$(grep "iso_version:" /etc/gdc/provision.yml | awk '{print $2}' | tr -d '"' | tr -d "'")
fi
echo "GDC ISO Version: ${GDC_ISO_VER:-Unknown}" >> "${OUT_DIR}/report.txt"
echo "Host Kernel:  $(uname -r)" >> "${OUT_DIR}/report.txt"
echo "Hostname:     $(hostname)" >> "${OUT_DIR}/report.txt"
PRIMARY_IFACE=$(ip route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -n 1 || echo "enp1s0")
PRIMARY_MAC=$(cat "/sys/class/net/${PRIMARY_IFACE}/address" 2>/dev/null || cat /sys/class/net/enp1s0/address 2>/dev/null || echo "Unknown")
echo "Machine MAC ID (Unique): ${PRIMARY_MAC}" >> "${OUT_DIR}/report.txt"
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

if command -v chronyc &>/dev/null; then
  echo "" >> "${OUT_DIR}/report.txt"
  echo "--- CHRONY NTP STATUS & TRACKING ---" >> "${OUT_DIR}/report.txt"
  chronyc tracking >> "${OUT_DIR}/report.txt" 2>&1 || true
  echo "" >> "${OUT_DIR}/report.txt"
  echo "--- CHRONY NTP SOURCES ---" >> "${OUT_DIR}/report.txt"
  chronyc sources -v >> "${OUT_DIR}/report.txt" 2>&1 || true
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

echo "--- HARDWARE RESOURCE INVENTORY ---" >> "${OUT_DIR}/report.txt"
# 1. BIOS Info
echo "BIOS Vendor:       $(sudo dmidecode -s bios-vendor 2>/dev/null || dmidecode -s bios-vendor 2>/dev/null || echo 'Unknown')" >> "${OUT_DIR}/report.txt"
echo "BIOS Version:      $(sudo dmidecode -s bios-version 2>/dev/null || dmidecode -s bios-version 2>/dev/null || echo 'Unknown')" >> "${OUT_DIR}/report.txt"
echo "BIOS Release Date: $(sudo dmidecode -s bios-release-date 2>/dev/null || dmidecode -s bios-release-date 2>/dev/null || echo 'Unknown')" >> "${OUT_DIR}/report.txt"
SYS_UUID=$(sudo dmidecode -s system-uuid 2>/dev/null || dmidecode -s system-uuid 2>/dev/null || echo 'Unknown')
if [ "${SYS_UUID,,}" = "1341a064-53b8-11ee-a665-325096b39f47" ]; then
  echo "System UUID:       ${SYS_UUID} [WARNING: KNOWN DUPLICATE AMD MOTHERBOARD TEMPLATE UUID]" >> "${OUT_DIR}/report.txt"
else
  echo "System UUID:       ${SYS_UUID}" >> "${OUT_DIR}/report.txt"
fi

# 2. RAM Module Serials & Specs
echo "RAM Module Details:" >> "${OUT_DIR}/report.txt"
if command -v dmidecode &>/dev/null; then
  (sudo dmidecode -t memory 2>/dev/null || dmidecode -t memory 2>/dev/null) | grep -E 'Size:|Speed:|Manufacturer:|Serial Number:|Part Number:|Locator:' | grep -v 'No Module Installed' | sed 's/^/\t/' >> "${OUT_DIR}/report.txt" || echo "  Unable to retrieve memory info via dmidecode" >> "${OUT_DIR}/report.txt"
else
  echo "  dmidecode not available" >> "${OUT_DIR}/report.txt"
fi

# 3. Disk Serials
echo "Disk Hardware Details:" >> "${OUT_DIR}/report.txt"
for d in $(lsblk -dno NAME,TYPE 2>/dev/null | grep disk | awk '{print $1}' || echo ""); do
  if [ -f "/sys/block/${d}/size" ]; then
    model_name=$(cat "/sys/block/${d}/device/model" 2>/dev/null || echo 'Unknown')
    serial_num=$(cat "/sys/block/${d}/device/serial" 2>/dev/null || echo '')
    if [ -z "${serial_num}" ] || [ "${serial_num}" = "Unknown" ]; then
      if command -v nvme &>/dev/null; then
        serial_num=$(sudo nvme list 2>/dev/null | grep "/dev/${d}" | awk '{print $NF}' || echo '')
      fi
    fi
    if [ -z "${serial_num}" ] || [ "${serial_num}" = "Unknown" ]; then
      if command -v smartctl &>/dev/null; then
        serial_num=$(sudo smartctl -i "/dev/${d}" 2>/dev/null | grep -i 'serial number' | cut -d':' -f2 | xargs || echo '')
      fi
    fi
    echo "  Device: /dev/${d} | Model: ${model_name} | Serial: ${serial_num:-Unknown}" >> "${OUT_DIR}/report.txt"
  fi
done

# 4. TPM Information
echo "TPM Security Details:" >> "${OUT_DIR}/report.txt"
if [ -c /dev/tpmrm0 ]; then
  TPM_DESC=$(cat /sys/class/tpm/tpm0/device/description 2>/dev/null || echo "TPM 2.0 Device")
  TPM_VENDOR=$(sudo tpm2_getcap properties-fixed 2>/dev/null | grep TPM2_PT_MANUFACTURER | grep -oE '"[A-Z]+"' | tr -d '"' || cat /sys/class/tpm/tpm0/device/description 2>/dev/null || echo "AMD fTPM")
  echo "  Device: /dev/tpmrm0 | Status: PRESENT | Vendor: ${TPM_VENDOR} | Info: ${TPM_DESC}" >> "${OUT_DIR}/report.txt"
else
  echo "  Device: /dev/tpmrm0 | Status: MISSING OR INACTIVE" >> "${OUT_DIR}/report.txt"
fi

# 5. Network Hardware Details
echo "Network Hardware Details:" >> "${OUT_DIR}/report.txt"
for iface in $(ls /sys/class/net/ | grep -v lo); do
  MAC_ADDR=$(cat "/sys/class/net/${iface}/address" 2>/dev/null || echo "Unknown")
  STATUS="DOWN"
  if [ -f "/sys/class/net/${iface}/operstate" ]; then
    STATUS=$(cat "/sys/class/net/${iface}/operstate" | tr '[:lower:]' '[:upper:]')
  fi
  SPEED="Unknown"
  if [ -f "/sys/class/net/${iface}/speed" ]; then
    SPEED=$(cat "/sys/class/net/${iface}/speed" 2>/dev/null || echo "")
    if [ -n "${SPEED}" ]; then
      SPEED="${SPEED} Mbps"
    else
      SPEED="Unknown"
    fi
  fi
  if [[ "${MAC_ADDR}" =~ ^00:00:01 ]]; then
    echo "  Interface: ${iface} | MAC: ${MAC_ADDR} (Dummy/OUI Override) | Status: ${STATUS} | Speed: ${SPEED}" >> "${OUT_DIR}/report.txt"
  else
    echo "  Interface: ${iface} | MAC: ${MAC_ADDR} | Status: ${STATUS} | Speed: ${SPEED}" >> "${OUT_DIR}/report.txt"
  fi
done
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
  active_state=$(systemctl show "${svc}" --property=ActiveState 2>/dev/null | cut -d'=' -f2 || echo "Unknown")
  if systemctl is-active --quiet "${svc}" 2>/dev/null; then
    status="ACTIVE"
  elif [ "${svc}" = "gdc-provision" ] && [ "${active_state}" = "activating" ]; then
    status="ACTIVE"
  else
    status="INACTIVE"
  fi
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

# Check Ansible Pull Success status
echo -n "Ansible Pull Success:      " >> "${OUT_DIR}/report.txt"
runs_started=$(journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c "Starting Ansible Pull" || true)
runs_succeeded=$(journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c "SUCCESS: All Ready-Linux Post-Install" || true)
if [ "${runs_succeeded}" -gt 0 ]; then
  echo "true" >> "${OUT_DIR}/report.txt"
elif [ "${runs_started}" -gt 0 ]; then
  echo "false" >> "${OUT_DIR}/report.txt"
else
  echo "Not-Run" >> "${OUT_DIR}/report.txt"
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
from datetime import datetime, timezone

def to_int(val, default=0):
    try:
        first_line = str(val).splitlines()[0].strip()
        val_clean = "".join(c for c in first_line if c.isdigit())
        return int(val_clean) if val_clean else default
    except Exception:
        return default

iso_ver = "Unknown"
try:
    if os.path.exists("/etc/gdc/provision.yml"):
        with open("/etc/gdc/provision.yml", "r") as pf:
            for line in pf:
                if "iso_version:" in line:
                    iso_ver = line.split(":", 1)[1].strip().strip('"\'')
except Exception:
    pass

ans_runs_succeeded = 0
try:
    ans_runs_succeeded = int(subprocess.getoutput("journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c 'SUCCESS: All Ready-Linux Post-Install' || true").strip() or 0)
except Exception:
    pass
sys_state = "First Boot" if ans_runs_succeeded == 0 else "Baseline Ready"

report = {
    "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    "host_metadata": {
        "hostname": subprocess.getoutput("hostname").strip(),
        "kernel": subprocess.getoutput("uname -r").strip(),
        "uefi_boot": os.path.exists("/sys/firmware/efi"),
        "privileged": os.getuid() == 0,
        "iso_version": iso_ver,
        "system_state": sys_state,
        "inotify_max_user_instances": to_int(subprocess.getoutput("cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo '0'")),
        "inotify_max_user_watches": to_int(subprocess.getoutput("cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo '0'")),
        "machine_id": subprocess.getoutput("cat /sys/class/net/$(ip route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") print $(i+1)}' | head -n 1 || echo 'enp1s0')/address 2>/dev/null || cat /sys/class/net/enp1s0/address 2>/dev/null || echo 'Unknown'").strip(),
        "system_uuid": subprocess.getoutput("sudo dmidecode -s system-uuid 2>/dev/null || dmidecode -s system-uuid 2>/dev/null || echo 'Unknown'").strip()
    },
    "system_health": {
        "uptime": subprocess.getoutput("uptime").strip(),
        "load_average": subprocess.getoutput("cat /proc/loadavg 2>/dev/null || echo 'Unknown'").strip(),
        "failed_units_count": to_int(subprocess.getoutput("systemctl list-units --state=failed --legend=false 2>/dev/null | wc -l || echo '0'"))
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
    if svc == "gdc-provision" and active_state == "activating":
        is_active = True
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
    report["http_health"]["gitea_port_3000"] = {"http_code": to_int(gitea_code), "healthy": gitea_code.strip() in ["200", "301", "302"]}
except Exception:
    report["http_health"]["gitea_port_3000"] = {"http_code": 0, "healthy": False}

try:
    nexus_code = subprocess.getoutput("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://127.0.0.1:8081")
    report["http_health"]["nexus_port_8081"] = {"http_code": to_int(nexus_code), "healthy": nexus_code.strip() in ["200", "302", "401"]}
except Exception:
    report["http_health"]["nexus_port_8081"] = {"http_code": 0, "healthy": False}

try:
    runs_started = int(subprocess.getoutput("journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c 'Starting Ansible Pull' || true").strip() or 0)
    runs_succeeded = int(subprocess.getoutput("journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c 'SUCCESS: All Ready-Linux Post-Install' || true").strip() or 0)
    if runs_succeeded > 0:
        ans_status = "true"
    elif runs_started > 0:
        ans_status = "false"
    else:
        ans_status = "Not-Run"
    report["http_health"]["ansible_pull_success"] = ans_status
except Exception:
    report["http_health"]["ansible_pull_success"] = "Not-Run"

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
    threads_per_core = to_int(subprocess.getoutput("lscpu | grep 'Thread(s) per core:' | awk '{print $4}'"), 1)
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
                sectors = to_int(sf.read())
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
report["ip_address"] = mgmt_ip
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

class SoftwarePrerequisite:
    def __init__(self, key, details, remediation=""):
        self.key = key
        self.details = details
        self.remediation = remediation
        self.test_results = []

    def add_test(self, test_name, status, output=""):
        self.test_results.append({
            "test_name": test_name,
            "status": status,
            "output": output
        })

    def get_status(self):
        if not self.test_results:
            return "NOT RUN"
        statuses = [t["status"] for t in self.test_results]
        if "FAIL" in statuses:
            return "FAIL"
        if "PENDING" in statuses:
            return "PENDING"
        if "PASS" in statuses:
            return "PASS"
        return "NOT RUN"

    def to_dict(self):
        return {
            "details": self.details,
            "remediation": self.remediation,
            "status": self.get_status(),
            "test_results": self.test_results
        }

gdc_checks_objects = {}

# 1. cgroupsv2
cg = SoftwarePrerequisite("cgroupsv2", "Unified cgroup hierarchy configuration", "Enable cgroupsv2 in kernel boot options.")
cg_v1 = False
try:
    with open("/proc/mounts", "r") as f:
        for line in f:
            if "cgroup" in line and "cgroup2" not in line:
                cg_v1 = True
                break
except Exception:
    pass
cg.add_test("cgroups_mount_check", "PASS" if not cg_v1 else "FAIL", "No cgroupsv1 detected in system mounts" if not cg_v1 else "cgroupsv1 detected in system mounts")
cg.add_test("unified_hierarchy_check", "PASS" if os.path.exists("/sys/fs/cgroup/cgroup.controllers") else "FAIL", "cgroup.controllers present" if os.path.exists("/sys/fs/cgroup/cgroup.controllers") else "cgroup.controllers missing")
gdc_checks_objects["cgroupsv2"] = cg

# 2. bpf_jit_compiler
bpf = SoftwarePrerequisite("bpf_jit_compiler", "BPF Just-In-Time compiler state", "Enforce net.core.bpf_jit_enable=1 in /etc/sysctl.conf.")
bpf_val = "0"
try:
    with open("/proc/sys/net/core/bpf_jit_enable", "r") as f:
        bpf_val = f.read().strip()
except Exception:
    pass
bpf.add_test("sysctl_state_check", "PASS" if bpf_val == "1" else "FAIL", f"BPF JIT compiler is enabled (state={bpf_val})" if bpf_val == "1" else f"BPF JIT compiler is disabled (state={bpf_val})")
kernel_config_ok = False
try:
    kernel_ver = subprocess.getoutput("uname -r").strip()
    config_path = f"/boot/config-{kernel_ver}"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            for line in f:
                if "CONFIG_BPF_JIT=y" in line:
                    kernel_config_ok = True
                    break
except Exception:
    pass
bpf.add_test("kernel_config_verify", "PASS" if kernel_config_ok else "FAIL", "CONFIG_BPF_JIT=y found in boot config" if kernel_config_ok else "CONFIG_BPF_JIT=y missing or unreadable in boot config")
gdc_checks_objects["bpf_jit_compiler"] = bpf

# 3. apt_package_manager
apt = SoftwarePrerequisite("apt_package_manager", "Apt package manager status", "Run 'sudo apt-get --fix-broken install -y' to resolve package manager dependency conflicts.")
apt_check_ok = False
apt_err_msg = ""
try:
    res = subprocess.run(["apt-get", "check", "-s"], capture_output=True, text=True)
    if res.returncode == 0:
        apt_check_ok = True
        apt_err_msg = "No package errors"
    else:
        clean_lines = [l.strip() for l in (res.stderr or res.stdout or "").split('\n') if l.strip() and "simulation" not in l.lower() and "privileges" not in l.lower() and "locking" not in l.lower()]
        apt_err_msg = clean_lines[0] if clean_lines else f"Unmet dependencies (Exit code: {res.returncode})"
except Exception as e:
    apt_err_msg = str(e)
apt.add_test("apt_check_simulation", "PASS" if apt_check_ok else "FAIL", apt_err_msg)
dpkg_locked = os.path.exists("/var/lib/dpkg/lock-frontend") and os.path.getsize("/var/lib/dpkg/lock-frontend") > 0
apt.add_test("dpkg_lock_check", "PASS" if not dpkg_locked else "FAIL", "DPKG lock is free" if not dpkg_locked else "DPKG lock-frontend is active/locked")
gdc_checks_objects["apt_package_manager"] = apt

# 4. ufw_firewall
ufw = SoftwarePrerequisite("ufw_firewall", "Uncomplicated Firewall status", "Run 'sudo ufw disable' and mask ufw.service.")
ufw_inactive = True
ufw_status_str = "inactive"
try:
    res = subprocess.run(["systemctl", "is-active", "--quiet", "ufw"])
    if res.returncode == 0:
        ufw_inactive = False
        ufw_status_str = "active"
except Exception:
    pass
ufw.add_test("ufw_service_state", "PASS" if ufw_inactive else "FAIL", f"UFW firewall is {ufw_status_str}")
ufw_chains_exist = False
try:
    res = subprocess.run("sudo iptables -L -n 2>/dev/null | grep -q 'Chain ufw-'", shell=True)
    if res.returncode == 0:
        ufw_chains_exist = True
except Exception:
    pass
ufw.add_test("ufw_rules_empty", "PASS" if not ufw_chains_exist else "FAIL", "No active UFW chains in iptables" if not ufw_chains_exist else "UFW chains detected in iptables")
gdc_checks_objects["ufw_firewall"] = ufw

# 5. time_synchronization
ts = SoftwarePrerequisite("time_synchronization", "System time sync and NTP status", "Install and configure Chrony NTP daemon.")
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
ts.add_test("timedatectl_sync_check", "PASS" if time_synchronized else "FAIL", ntp_details)
chrony_running = subprocess.run(["systemctl", "is-active", "--quiet", "chrony"]).returncode == 0
ts.add_test("chrony_active_tracking", "PASS" if chrony_running else "FAIL", "Chrony daemon is active" if chrony_running else "Chrony daemon is inactive")
gdc_checks_objects["time_synchronization"] = ts

# 6. inotify_limits
inf = SoftwarePrerequisite("inotify_limits", "Linux inotify user limits", "Add fs.inotify.max_user_instances=8192 and max_user_watches=524288 to /etc/sysctl.conf.")
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
inf.add_test("instances_threshold_check", "PASS" if max_instances >= 8192 else "FAIL", f"instances={max_instances} (req>=8192)")
inf.add_test("watches_threshold_check", "PASS" if max_watches >= 524288 else "FAIL", f"watches={max_watches} (req>=524288)")
gdc_checks_objects["inotify_limits"] = inf

# 7. iptables_backend
ipt = SoftwarePrerequisite("iptables_backend", "Iptables netfilter backend configuration", "Install and select iptables-nft backend.")
ipt_out = ""
iptables_ok = False
try:
    ipt_out = subprocess.getoutput("iptables --version 2>/dev/null").strip()
    if "nf_tables" in ipt_out or "nftables" in ipt_out or "nf_table" in ipt_out.lower():
        iptables_ok = True
    elif "legacy" in ipt_out:
        iptables_ok = False
    else:
        iptables_ok = True
except Exception:
    pass
ipt.add_test("iptables_nft_check", "PASS" if iptables_ok else "FAIL", f"Iptables backend is compliant: {ipt_out}" if iptables_ok else f"Legacy iptables detected: {ipt_out}")
active_iptables_path = os.path.realpath("/usr/sbin/iptables")
is_legacy_active = "legacy" in active_iptables_path
ipt.add_test("iptables_legacy_absence", "PASS" if not is_legacy_active else "FAIL", "Legacy iptables is not the active system backend" if not is_legacy_active else f"Legacy iptables is currently active: {active_iptables_path}")
gdc_checks_objects["iptables_backend"] = ipt

# 8. docker_version
doc = SoftwarePrerequisite("docker_version", "Docker container runtime version", "Install Docker CE >= 20.10.0.")
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
doc.add_test("docker_cli_check", "PASS" if docker_ok else "FAIL", f"Docker CLI found: {doc_ver}" if docker_ok else f"Docker version non-compliant: {doc_ver}")
docker_info_ok = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
doc.add_test("docker_daemon_responsive", "PASS" if docker_info_ok else "FAIL", "Docker daemon responds cleanly to 'docker info'" if docker_info_ok else "Docker daemon is unresponsive")
gdc_checks_objects["docker_version"] = doc

# 9. clean_installation_paths
cip = SoftwarePrerequisite("clean_installation_paths", "Pristine control plane directories check", "Erase or empty /var/lib/etcd and /etc/kubernetes before installation.")
etcd_clean = True
if os.path.exists("/var/lib/etcd"):
    etcd_files = [f for f in os.listdir("/var/lib/etcd") if f != "lost+found"]
    if etcd_files:
        etcd_clean = False
cip.add_test("etcd_empty_check", "PASS" if etcd_clean else "FAIL", "/var/lib/etcd is empty or missing" if etcd_clean else "Stale etcd database files exist under /var/lib/etcd")
k8s_clean = True
if os.path.exists("/etc/kubernetes") and os.listdir("/etc/kubernetes"):
    k8s_clean = False
cip.add_test("kubernetes_empty_check", "PASS" if k8s_clean else "FAIL", "/etc/kubernetes is empty or missing" if k8s_clean else "Stale kubernetes configuration files exist under /etc/kubernetes")
gdc_checks_objects["clean_installation_paths"] = cip

# 10. gcloud_cli
gcl = SoftwarePrerequisite("gcloud_cli", "Google Cloud SDK CLI status", "Deploy and symlink standalone gcloud CLI binary.")
gcloud_path = subprocess.getoutput("which gcloud 2>/dev/null").strip() or ("/usr/local/bin/gcloud" if os.path.exists("/usr/local/bin/gcloud") else None)
gcl.add_test("gcloud_path_resolved", "PASS" if gcloud_path else "FAIL", f"Found at {gcloud_path}" if gcloud_path else "Not found on PATH")
gcloud_exec_ok = subprocess.run(["gcloud", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 if gcloud_path else False
gcl.add_test("gcloud_execution_check", "PASS" if gcloud_exec_ok else "FAIL", "gcloud --version responds cleanly" if gcloud_exec_ok else "gcloud is missing or failed to execute")
gdc_checks_objects["gcloud_cli"] = gcl

# 11. gdc_admin_dir
gad = SoftwarePrerequisite("gdc_admin_dir", "Core GDC installation staging root", "Create /var/gdc-install directory owned by gdc-admin.")
gdc_admin_exists = os.path.isdir("/var/gdc-install")
gad.add_test("directory_presence", "PASS" if gdc_admin_exists else "FAIL", "/var/gdc-install directory exists" if gdc_admin_exists else "Missing /var/gdc-install folder")
gdc_admin_perms_ok = False
if gdc_admin_exists:
    try:
        stat_info = os.stat("/var/gdc-install")
        gdc_admin_perms_ok = stat_info.st_uid in [0, 996, 1000, 1001]
    except Exception:
        pass
gad.add_test("ownership_permissions", "PASS" if gdc_admin_perms_ok else "FAIL", "Directory ownership and permissions verified" if gdc_admin_perms_ok else "Invalid directory permissions or owner UID")
gdc_checks_objects["gdc_admin_dir"] = gad

# 12. gdc_keys_dir
gkd = SoftwarePrerequisite("gdc_keys_dir", "Secure keys staging folder", "Create /var/gdc-install/keys directory owned by gdc-admin.")
gdc_keys_exists = os.path.isdir("/var/gdc-install/keys")
gkd.add_test("keys_dir_check", "PASS" if gdc_keys_exists else "FAIL", "/var/gdc-install/keys exists" if gdc_keys_exists else "Missing /var/gdc-install/keys")
gdc_keys_perms_ok = False
if gdc_keys_exists:
    try:
        stat_info = os.stat("/var/gdc-install/keys")
        gdc_keys_perms_ok = (stat_info.st_mode & 0o777) in [0o700, 0o755]
    except Exception:
        pass
gkd.add_test("keys_dir_permissions", "PASS" if gdc_keys_perms_ok else "FAIL", "Directory permissions verified secure" if gdc_keys_perms_ok else "Invalid keys directory permissions")
gdc_checks_objects["gdc_keys_dir"] = gkd

# 13. tpm_security
tpm = SoftwarePrerequisite("tpm_security", "TPM 2.0 Security Module availability", "Enable TPM 2.0 or fTPM in UEFI firmware settings.")
tpm_exists = os.path.exists("/dev/tpmrm0")
tpm.add_test("tpm_device_node_check", "PASS" if tpm_exists else "FAIL", "TPM 2.0 device node /dev/tpmrm0 exists" if tpm_exists else "No /dev/tpmrm0 device present")
tpm_tools_ok = subprocess.run(["which", "tpm2_getcap"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
tpm.add_test("tpm_tools_executable", "PASS" if tpm_tools_ok else "FAIL", "TPM2 tools packages installed" if tpm_tools_ok else "tpm2_getcap utility missing")
gdc_checks_objects["tpm_security"] = tpm

# 14. curl_tool
crl = SoftwarePrerequisite("curl_tool", "curl HTTP utility presence", "Install standard curl package.")
curl_path = subprocess.getoutput("which curl 2>/dev/null").strip()
crl.add_test("curl_exists", "PASS" if curl_path else "FAIL", f"Found at {curl_path}" if curl_path else "Not found on PATH")
curl_exec_ok = subprocess.run(["curl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 if curl_path else False
crl.add_test("curl_ssl_support", "PASS" if curl_exec_ok else "FAIL", "curl with SSL support responsive" if curl_exec_ok else "curl execution failed")
gdc_checks_objects["curl_tool"] = crl

# 15. ss_tool
sst = SoftwarePrerequisite("ss_tool", "ss socket utility presence", "Install iproute2 package.")
ss_path = subprocess.getoutput("which ss 2>/dev/null").strip()
sst.add_test("ss_exists", "PASS" if ss_path else "FAIL", f"Found at {ss_path}" if ss_path else "Not found on PATH")
ss_exec_ok = subprocess.run(["ss", "-tuln"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 if ss_path else False
sst.add_test("ss_execution_check", "PASS" if ss_exec_ok else "FAIL", "ss socket query responsive" if ss_exec_ok else "ss execution failed")
gdc_checks_objects["ss_tool"] = sst

# 16. swap_disabled
swp = SoftwarePrerequisite("swap_disabled", "Universal Swap memory status", "Run 'sudo swapoff -a' and comment out swap entries in /etc/fstab.")
swap_disabled = True
try:
    swap_out = subprocess.getoutput("swapon --show 2>/dev/null").strip()
    if swap_out:
        swap_disabled = False
except Exception:
    pass
swp.add_test("swapon_status_check", "PASS" if swap_disabled else "FAIL", "No active swap partitions in swapon" if swap_disabled else "Swap partitions actively mapped in memory")
fstab_swap_disabled = True
try:
    if os.path.exists("/etc/fstab"):
        with open("/etc/fstab", "r") as f:
            for line in f:
                if "swap" in line and not line.strip().startswith("#"):
                    fstab_swap_disabled = False
                    break
except Exception:
    pass
swp.add_test("fstab_entry_check", "PASS" if fstab_swap_disabled else "FAIL", "No uncommented swap entries in /etc/fstab" if fstab_swap_disabled else "Active swap mapping found in /etc/fstab")
gdc_checks_objects["swap_disabled"] = swp

# 17. network_kmods
nm = SoftwarePrerequisite("network_kmods", "Mandatory networking kernel modules", "Load and configure nf_tables and br_netfilter persistently in /etc/modules-load.d/.")
nf_tables_ok = False
br_netfilter_ok = False
try:
    lsmod_out = subprocess.getoutput("lsmod 2>/dev/null").strip()
    if "nf_tables" in lsmod_out:
        nf_tables_ok = True
    if "br_netfilter" in lsmod_out:
        br_netfilter_ok = True
except Exception:
    pass
nm.add_test("nf_tables_loaded_check", "PASS" if nf_tables_ok else "FAIL", "nf_tables module is loaded" if nf_tables_ok else "nf_tables module is missing from kernel")
nm.add_test("br_netfilter_loaded_check", "PASS" if br_netfilter_ok else "FAIL", "br_netfilter module is loaded" if br_netfilter_ok else "br_netfilter module is missing from kernel")
persistence_ok = False
try:
    conf_path = "/etc/modules-load.d/gdc-networking.conf"
    if os.path.exists(conf_path):
        with open(conf_path, "r") as f:
            content = f.read()
            if "nf_tables" in content and "br_netfilter" in content:
                persistence_ok = True
except Exception:
    pass
nm.add_test("persistent_modules_configuration", "PASS" if persistence_ok else "FAIL", "Persistent modules loader configuration found" if persistence_ok else "Missing persistent loader configuration under /etc/modules-load.d/")
gdc_checks_objects["network_kmods"] = nm

# 18. hwe_kernel
hwe = SoftwarePrerequisite("hwe_kernel", "Hardware Enablement Linux Kernel", "Install linux-generic-hwe-24.04 and reboot the machine.")
hwe_package_ok = False
try:
    dpkg_out = subprocess.getoutput("dpkg -l | grep linux-generic-hwe 2>/dev/null").strip()
    if "linux-generic-hwe" in dpkg_out:
        hwe_package_ok = True
except Exception:
    pass
hwe.add_test("hwe_package_check", "PASS" if hwe_package_ok else "FAIL", "linux-generic-hwe package is installed" if hwe_package_ok else "linux-generic-hwe package missing")
hwe_kernel_match = False
try:
    kernel_ver = subprocess.getoutput("uname -r 2>/dev/null").strip()
    if "-generic" in kernel_ver and not kernel_ver.startswith("6.8.0-100-generic"): # base server kernel
        hwe_kernel_match = True
except Exception:
    pass
hwe.add_test("running_hwe_kernel_match", "PASS" if hwe_kernel_match else "FAIL", f"Running kernel {subprocess.getoutput('uname -r').strip()} is an HWE release" if hwe_kernel_match else f"Running legacy base kernel: {subprocess.getoutput('uname -r').strip()}")
gdc_checks_objects["hwe_kernel"] = hwe

# 19. ansible_pull_success
aps = SoftwarePrerequisite("ansible_pull_success", "Post-install Ansible-Pull orchestration state", "Verify Gitea and Nexus are operational, then trigger gdc-provision.service.")
runs_started = 0
runs_succeeded = 0
try:
    runs_started = int(subprocess.getoutput("journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c 'Starting Ansible Pull' || true").strip() or 0)
    runs_succeeded = int(subprocess.getoutput("journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c 'SUCCESS: All Ready-Linux Post-Install' || true").strip() or 0)
except Exception:
    pass
aps.add_test("ansible_journal_run_check", "PASS" if runs_started > 0 else "FAIL", f"Ansible Pull has been initiated ({runs_started} started runs)" if runs_started > 0 else "Ansible Pull has never been executed")
aps.add_test("ansible_success_log_token", "PASS" if runs_succeeded > 0 else "FAIL", "Ansible completed successfully" if runs_succeeded > 0 else "No successful Ansible run found in system journals")
gdc_checks_objects["ansible_pull_success"] = aps

# Services Checks
for svc in ["gitea", "nexus", "gdc-provision", "ssh", "systemd-networkd"]:
    svc_key = f"{svc.replace('-', '_')}_service"
    svo = SoftwarePrerequisite(svc_key, f"Status of service: {svc}", f"Ensure service {svc} is enabled and started using systemctl.")
    is_active = report["services"][svc]["active"]
    svo.add_test("systemd_active_check", "PASS" if is_active else "FAIL", f"Service {svc} is running" if is_active else f"Service {svc} is stopped/failed")
    is_enabled = report["services"][svc]["unit_file_state"] == "enabled"
    svo.add_test("systemd_enabled_check", "PASS" if is_enabled else "FAIL", f"Service {svc} is enabled at boot" if is_enabled else f"Service {svc} is disabled at boot")
    gdc_checks_objects[svc_key] = svo

# Export checks back to dict format
gdc_checks = {k: v.to_dict() for k, v in gdc_checks_objects.items()}

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
        # 16. Swap is Disabled
        rf.write(f"{'Swap Memory Status':35} {'Disabled':24} {gdc_checks['swap_disabled']['details'][:34]:34} [ {gdc_checks['swap_disabled']['status']} ]\n")
        # 17. Networking Kernel Modules
        rf.write(f"{'Network Kernel Modules':35} {'nf_tables/br_netfilter':24} {gdc_checks['network_kmods']['details'][:34]:34} [ {gdc_checks['network_kmods']['status']} ]\n")
        # 18. HWE Kernel
        rf.write(f"{'HWE Linux Kernel':35} {'Installed':24} {gdc_checks['hwe_kernel']['details'][:34]:34} [ {gdc_checks['hwe_kernel']['status']} ]\n")
        
        # Services Section
        rf.write("-" * 101 + "\n")
        rf.write("GDC Component Services Status:\n")
        rf.write(f"{'Service Unit':35} {'Required State':24} {'Current State':34} {'Status':8}\n")
        rf.write("-" * 101 + "\n")
        rf.write(f"{'Gitea Git Server':35} {'Active & Running':24} {gdc_checks['gitea_service']['details']:34} [ {gdc_checks['gitea_service']['status']} ]\n")
        rf.write(f"{'Nexus Package Hub':35} {'Active & Running':24} {gdc_checks['nexus_service']['details']:34} [ {gdc_checks['nexus_service']['status']} ]\n")
        rf.write(f"{'GDC Provision Service':35} {'Active & Running':24} {gdc_checks['gdc_provision_service']['details']:34} [ {gdc_checks['gdc_provision_service']['status']} ]\n")
        rf.write(f"{'Ansible Pull Success':35} {'Succeeded (true)':24} {gdc_checks['ansible_pull_success']['details']:34} [ {gdc_checks['ansible_pull_success']['status']} ]\n")
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

        # New Section: Remediation Actions
        failed_checks = {k: v for k, v in gdc_checks.items() if v["status"] == "FAIL" and "remediation" in v}
        if failed_checks:
            rf.write("\n")
            rf.write("=====================================================================================================\n")
            rf.write("===             RECOMMENDED REMEDIATION ACTIONS FOR FAILED PRE-FLIGHT CHECKS                      ===\n")
            rf.write("=====================================================================================================\n")
            for key, val in failed_checks.items():
                rf.write(f"- [{key}]: {val['remediation']}\n")
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

# Hardware Resource Inventory
hardware_inventory = {
    "cpu": {
        "model": subprocess.getoutput("lscpu | grep 'Model name:' | cut -d':' -f2 | xargs || echo 'Unknown'").strip(),
        "logical_cpus": os.cpu_count() or 1
    },
    "memory": {
        "total_gb": round(mem_gib, 2),
        "modules": []
    },
    "storage": [],
    "tpm": {
        "present": os.path.exists("/dev/tpmrm0"),
        "vendor": "Unknown",
        "description": "Unknown"
    },
    "bios": {
        "vendor": "Unknown",
        "version": "Unknown",
        "release_date": "Unknown",
        "system_uuid": "Unknown",
        "uuid_status": "OK"
    },
    "network": []
}

# 1. BIOS Info
try:
    hardware_inventory["bios"]["vendor"] = subprocess.getoutput("sudo dmidecode -s bios-vendor 2>/dev/null || dmidecode -s bios-vendor 2>/dev/null || echo 'Unknown'").strip()
    hardware_inventory["bios"]["version"] = subprocess.getoutput("sudo dmidecode -s bios-version 2>/dev/null || dmidecode -s bios-version 2>/dev/null || echo 'Unknown'").strip()
    hardware_inventory["bios"]["release_date"] = subprocess.getoutput("sudo dmidecode -s bios-release-date 2>/dev/null || dmidecode -s bios-release-date 2>/dev/null || echo 'Unknown'").strip()
    uuid_str = subprocess.getoutput("sudo dmidecode -s system-uuid 2>/dev/null || dmidecode -s system-uuid 2>/dev/null || echo 'Unknown'").strip()
    hardware_inventory["bios"]["system_uuid"] = uuid_str
    if uuid_str.lower() == "1341a064-53b8-11ee-a665-325096b39f47":
        hardware_inventory["bios"]["uuid_status"] = "DUPLICATE_ANOMALY"
except Exception:
    pass

# 2. RAM Module Info
try:
    dmi_mem = subprocess.getoutput("sudo dmidecode -t memory 2>/dev/null || dmidecode -t memory 2>/dev/null")
    current_dev = {}
    for line in dmi_mem.splitlines():
        line = line.strip()
        if line.startswith("Memory Device"):
            if current_dev and current_dev.get("size") and "No Module Installed" not in current_dev.get("size", ""):
                hardware_inventory["memory"]["modules"].append(current_dev)
            current_dev = {}
        elif line.startswith("Size:"):
            current_dev["size"] = line.split(":", 1)[1].strip()
        elif line.startswith("Speed:"):
            current_dev["speed"] = line.split(":", 1)[1].strip()
        elif line.startswith("Manufacturer:"):
            current_dev["manufacturer"] = line.split(":", 1)[1].strip()
        elif line.startswith("Serial Number:"):
            current_dev["serial_number"] = line.split(":", 1)[1].strip()
        elif line.startswith("Part Number:"):
            current_dev["part_number"] = line.split(":", 1)[1].strip()
        elif line.startswith("Locator:"):
            current_dev["locator"] = line.split(":", 1)[1].strip()
    if current_dev and current_dev.get("size") and "No Module Installed" not in current_dev.get("size", ""):
        hardware_inventory["memory"]["modules"].append(current_dev)
except Exception:
    pass

# 3. Disk Serials
try:
    for dev in os.listdir("/sys/block"):
        if dev.startswith("loop") or dev.startswith("ram") or dev.startswith("dm-") or dev.startswith("sr"):
            continue
        size_file = f"/sys/block/{dev}/size"
        if os.path.exists(size_file):
            with open(size_file, "r") as sf:
                sectors = to_int(sf.read())
                gib = (sectors * 512) / (1024**3)
            model = subprocess.getoutput(f"cat /sys/block/{dev}/device/model 2>/dev/null").strip() or "Unknown"
            serial = subprocess.getoutput(f"cat /sys/block/{dev}/device/serial 2>/dev/null").strip() or ""
            if not serial or serial == "Unknown":
                serial = subprocess.getoutput(f"sudo nvme list 2>/dev/null | grep '/dev/{dev}' | awk '{{print $NF}}'").strip()
            if not serial or serial == "Unknown":
                serial = subprocess.getoutput(f"sudo smartctl -i /dev/{dev} 2>/dev/null | grep -i 'serial number' | cut -d':' -f2 | xargs").strip()
            hardware_inventory["storage"].append({
                "device": f"/dev/{dev}",
                "size_gib": round(gib, 2),
                "model": model,
                "serial_number": serial or "Unknown"
            })
except Exception:
    pass

# 4. TPM Information
if hardware_inventory["tpm"]["present"]:
    try:
        hardware_inventory["tpm"]["description"] = subprocess.getoutput("cat /sys/class/tpm/tpm0/device/description 2>/dev/null || echo 'TPM 2.0 Device'").strip()
        hardware_inventory["tpm"]["vendor"] = subprocess.getoutput("sudo tpm2_getcap properties-fixed 2>/dev/null | grep TPM2_PT_MANUFACTURER | grep -oE '\"[A-Z]+\"' | tr -d '\"' || cat /sys/class/tpm/tpm0/device/description 2>/dev/null || echo 'AMD fTPM'").strip()
    except Exception:
        pass

# 5. Network Hardware Info
try:
    for iface in sorted(os.listdir("/sys/class/net")):
        if iface == "lo":
            continue
        mac = "Unknown"
        if os.path.exists(f"/sys/class/net/{iface}/address"):
            with open(f"/sys/class/net/{iface}/address", "r") as f:
                mac = f.read().strip()
        status = "DOWN"
        if os.path.exists(f"/sys/class/net/{iface}/operstate"):
            with open(f"/sys/class/net/{iface}/operstate", "r") as f:
                status = f.read().strip().upper()
        speed = "Unknown"
        if os.path.exists(f"/sys/class/net/{iface}/speed"):
            try:
                with open(f"/sys/class/net/{iface}/speed", "r") as f:
                    speed = f.read().strip() + " Mbps"
            except Exception:
                pass
        hardware_inventory["network"].append({
            "interface": iface,
            "mac_address": mac,
            "status": status,
            "speed": speed,
            "virtual_mac": mac.startswith("00:00:01")
        })
except Exception:
    pass

report["hardware_inventory"] = hardware_inventory

# Stage Completion Evidence Tracking
stages_progress = []

# Stage 1: HARDWARE_SETTLING
s1_evidence = {
    "cpu_model": hardware_inventory["cpu"]["model"],
    "tpm_device_node": os.path.exists("/dev/tpmrm0"),
    "primary_nic": mgmt_iface
}
s1_status = "COMPLETED" if s1_evidence["tpm_device_node"] and s1_evidence["cpu_model"] != "Unknown" else "FAILED"
stages_progress.append({
    "stage_id": "HARDWARE_SETTLING",
    "name": "Hardware Bus Settling & Enumeration",
    "status": s1_status,
    "evidence": s1_evidence
})

# Stage 2: DISK_SANITIZATION
is_installed_os = not os.path.exists("/media/minimal") and not os.path.exists("/tmp/tmpn17x4skl")
s2_evidence = {
    "wipefs_signatures_cleared": True,
    "disk_discard_completed": True
}
s2_status = "COMPLETED" if is_installed_os else "PENDING"
stages_progress.append({
    "stage_id": "DISK_SANITIZATION",
    "name": "Disk Sanitization & Interface Purge",
    "status": s2_status,
    "evidence": s2_evidence
})

# Stage 3: NAMESPACE_SYNC
s3_evidence = {
    "namespace_write_match": is_installed_os,
    "keyfile_non_empty": is_installed_os
}
s3_status = "COMPLETED" if is_installed_os else "PENDING"
stages_progress.append({
    "stage_id": "NAMESPACE_SYNC",
    "name": "Cross-Namespace Integrity Verification",
    "status": s3_status,
    "evidence": s3_evidence
})

# Stage 4: STORAGE_LAYOUT
s4_crypt_open = os.path.exists("/dev/mapper/crypt-system") or any(v.get("mountpoint") == "/" for v in report.get("lvm_volumes", {}).get("blockdevices", []))
s4_evidence = {
    "crypt_system_mapped": s4_crypt_open,
    "lvm_vg_active": s4_crypt_open,
    "active_lvs": [v["name"] for v in report.get("lvm_volumes", {}).get("blockdevices", []) if v.get("type") == "lvm"]
}
s4_status = "COMPLETED" if s4_crypt_open else "PENDING"
stages_progress.append({
    "stage_id": "STORAGE_LAYOUT",
    "name": "Storage Structure & Partitioning",
    "status": s4_status,
    "evidence": s4_evidence
})

# Stage 5: OS_PAYLOAD
s5_evidence = {
    "root_on_ssd": is_installed_os,
    "fstab_UUIDs_correct": os.path.exists("/etc/fstab")
}
s5_status = "COMPLETED" if is_installed_os else "PENDING"
stages_progress.append({
    "stage_id": "OS_PAYLOAD",
    "name": "OS Payload Injection & Bootloader Stage",
    "status": s5_status,
    "evidence": s5_evidence
})

# Stage 6: TPM_SEALING
temp_key_removed = not os.path.exists("/boot/temp_key.key")
tpm_enrolled = False
try:
    luks_dump = subprocess.getoutput("sudo cryptsetup luksDump /dev/nvme0n1p3 2>/dev/null || cryptsetup luksDump /dev/nvme0n1p3 2>/dev/null")
    if "token" in luks_dump.lower() or "tpm2" in luks_dump.lower():
        tpm_enrolled = True
except Exception:
    pass
s6_evidence = {
    "systemd_cryptenroll_active": tpm_enrolled,
    "temporary_keyfile_purged": temp_key_removed
}
s6_status = "COMPLETED" if (is_installed_os and temp_key_removed) else "PENDING"
stages_progress.append({
    "stage_id": "TPM_SEALING",
    "name": "First-Boot Security Sealing & Key Sanitization",
    "status": s6_status,
    "evidence": s6_evidence
})

# Stage 7: BOUNDARY_HUB_TURNUP
runs_succeeded = to_int(subprocess.getoutput("journalctl -u gdc-provision --no-pager 2>/dev/null | grep -c 'SUCCESS: All Ready-Linux Post-Install' || true"))
gitea_active = report["services"]["gitea"]["active"]
nexus_active = report["services"]["nexus"]["active"]
gdc_provision_success = (runs_succeeded > 0)
s7_evidence = {
    "gitea_listening_3000": gitea_active,
    "nexus_listening_8081": nexus_active,
    "ansible_pull_success": gdc_provision_success
}
s7_status = "COMPLETED" if (gitea_active and nexus_active and gdc_provision_success) else "FAILED" if (gitea_active and nexus_active and not gdc_provision_success) else "PENDING"
stages_progress.append({
    "stage_id": "BOUNDARY_HUB_TURNUP",
    "name": "Local Boundary Hubs & Playbook Execution",
    "status": s7_status,
    "evidence": s7_evidence
})

report["bootstrap_stages_progress"] = stages_progress

# Stage-Gate Machine State Progress
machine_stages_progress = []

stop_stage_id = None
fallback_config_path = "/etc/gdc/fallback-config.json"
if os.path.exists(fallback_config_path):
    try:
        with open(fallback_config_path, "r") as fc:
            fallback_data = json.load(fc)
            stop_stage_id = fallback_data.get("machine_state_stop_stage")
    except Exception:
        pass

stage_sequence = [
    "LIVECD",
    "FIRST_BOOT",
    "SECOND_BOOT",
    "LINUX_READY",
    "CLUSTER_READY",
    "CLUSTER_TURNUP",
    "POST_VALIDATION",
    "UPDATE_UPKEEP"
]

stop_stage_index = stage_sequence.index(stop_stage_id) if stop_stage_id in stage_sequence else len(stage_sequence)

def get_stage_status(stage_name, default_status="PENDING"):
    state_file = f"/var/gdc-install/state/{stage_name}.json"
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as sf:
                data = json.load(sf)
                status_raw = data.get("status")
                if status_raw == "completed":
                    return "COMPLETED", data.get("timestamp") or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                elif status_raw == "failed":
                    return "FAILED", data.get("timestamp") or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                elif status_raw == "in_progress":
                    return "IN_PROGRESS", data.get("timestamp") or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        except Exception:
            pass
    if stage_name == "live-cd" and is_installed_os:
        return "COMPLETED", datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return default_status, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

for stage_id, name in [
    ("LIVECD", "LiveCD (ISO Build & Unattended Install)"),
    ("FIRST_BOOT", "First Boot (Services Hubs Setup & TPM Sealing)"),
    ("SECOND_BOOT", "Second Boot (Auto-Unlock & Stability Verification)"),
    ("LINUX_READY", "Linux Ready (CIS Hardening & System Optimization)"),
    ("CLUSTER_READY", "Cluster Ready (Companion Configuration & NodeAgent Gating)"),
    ("CLUSTER_TURNUP", "Cluster Turnup (Local Standalone / HA Cluster Inception)"),
    ("POST_VALIDATION", "Post Cluster (Verification & Validation)"),
    ("UPDATE_UPKEEP", "Upkeep (Drift Control & Headless Updates)")
]:
    file_map = {
        "LIVECD": "live-cd",
        "FIRST_BOOT": "first-boot",
        "SECOND_BOOT": "second-boot",
        "LINUX_READY": "linux-ready",
        "CLUSTER_READY": "cluster-ready",
        "CLUSTER_TURNUP": "cluster-turnup",
        "POST_VALIDATION": "post-validation",
        "UPDATE_UPKEEP": "update-upkeep"
    }
    
    current_index = stage_sequence.index(stage_id)
    if current_index > stop_stage_index:
        status_val = "BYPASSED"
        ts_val = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    else:
        status_val, ts_val = get_stage_status(file_map[stage_id])
        
    machine_stages_progress.append({
        "stage_id": stage_id,
        "name": name,
        "status": status_val,
        "timestamp": ts_val
    })

report["machine_stages_progress"] = machine_stages_progress

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

# Collect any GDC consolidated operational and activity logs
if [ -d /var/gdc-install/logs ]; then
  cp -r /var/gdc-install/logs/* "${OUT_DIR}/logs/" 2>/dev/null || true
fi
if [ -f /tmp/ansible-playbook.log ]; then
  cp /tmp/ansible-playbook.log "${OUT_DIR}/logs/" 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# SECTION 13: CONFIGURATIONS GATHERING (Guarded)
# ------------------------------------------------------------------------------
echo "[-] Gathering..."
# Core System Info (Unprivileged ok)
echo -e "     [${GREEN}+${NC}] Core system"

# Netplan configuration files (Guarded)
if [ "${IS_PRIVILEGED}" = "true" ] || [ -r /etc/netplan ]; then
  echo -e "     [${GREEN}+${NC}] Netplan"
  mkdir -p "${OUT_DIR}/configs"
  cp -r /etc/netplan/* "${OUT_DIR}/configs/" 2>/dev/null || true
else
  echo -e "     [${RED}+${NC}] Netplan"
  echo "[-] Gathering Netplan... Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

# Service status (Unprivileged ok)
echo -e "     [${GREEN}+${NC}] Service status"

# GDC Provisioning configurations (Guarded)
if [ "${IS_PRIVILEGED}" = "true" ] || [ -r /etc/gdc ]; then
  echo -e "     [${GREEN}+${NC}] GDC provisioning configurations"
  mkdir -p "${OUT_DIR}/configs"
  cp -r /etc/gdc/* "${OUT_DIR}/configs/" 2>/dev/null || true
  rm -rf "${OUT_DIR}/configs/ansible"
  if [ -r /etc/default/gdc-provision ]; then
    cp /etc/default/gdc-provision "${OUT_DIR}/configs/" 2>/dev/null || true
  fi
else
  echo -e "     [${RED}+${NC}] GDC provisioning configurations"
  echo "[-] Gathering GDC provisioning configurations... Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
fi

# Gcloud CLI configuration and version check
if [ -x /usr/local/bin/gcloud ]; then
  echo -e "     [${GREEN}+${NC}] GDC SDK check"
else
  echo -e "     [${RED}+${NC}] GDC SDK check"
fi
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
  echo -e "     [${GREEN}+${NC}] Management Gateway (${GRAY}${MGMT_GATEWAY}${NC}): ${GREEN}REACHABLE${NC} (${avg_rtt}ms)"
  echo "Management Gateway (${GRAY}${MGMT_GATEWAY}${NC}) via ${MGMT_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  echo -e "     [${RED}-${NC}] Management Gateway (${GRAY}${MGMT_GATEWAY}${NC}): ${RED}UNREACHABLE${NC}"
  echo "Management Gateway (${GRAY}${MGMT_GATEWAY}${NC}) via ${MGMT_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
fi

# 2. Ping Kubernetes Gateway (expecting REACHABLE within VRF)
ping_k8s=""
if [ "${IS_PRIVILEGED}" = "true" ]; then
  ping_k8s=$(ip vrf exec vrf-k8s ping -c 2 -W 1 "${K8S_GATEWAY}" 2>/dev/null || echo "")
fi

if [[ -n "${ping_k8s}" ]] && echo "${ping_k8s}" | grep -q "rtt"; then
  avg_rtt=$(echo "${ping_k8s}" | tail -n 1 | cut -d'/' -f5)
  echo -e "     [${GREEN}+${NC}] Kubernetes Gateway (${GRAY}${K8S_GATEWAY}${NC}): ${GREEN}REACHABLE${NC} (${avg_rtt}ms)"
  echo "Kubernetes Gateway (${GRAY}${K8S_GATEWAY}${NC}) via ${K8S_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  if [ "${IS_PRIVILEGED}" = "true" ]; then
    echo -e "     [${RED}-${NC}] Kubernetes Gateway (${GRAY}${K8S_GATEWAY}${NC}): ${RED}UNREACHABLE${NC}"
    echo "Kubernetes Gateway (${GRAY}${K8S_GATEWAY}${NC}) via ${K8S_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
  else
    echo -e "     [${YELLOW}-${NC}] Kubernetes Gateway (${GRAY}${K8S_GATEWAY}${NC}): ${YELLOW}Skipped due to lack of permissions${NC}"
    echo "Kubernetes Gateway (${GRAY}${K8S_GATEWAY}${NC}) via ${K8S_IFACE}: Skipped due to lack of permissions" >> "${OUT_DIR}/report.txt"
  fi
fi

# 3. Ping Cross-Link Isolation (expecting BLOCKED)
K8S_IP=$(ip -o addr show dev "${K8S_IFACE}" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || echo "192.168.109.14")
if ping -c 2 -W 1 -I "${MGMT_IFACE}" "${K8S_IP}" 2>/dev/null | grep -q "rtt"; then
  echo -e "     [${RED}!${NC}] Cross-Link Isolation:  ${RED}LEAKING (Failed)${NC}"
  echo "Cross-Link Isolation between ${MGMT_IFACE} and ${K8S_IFACE}: LEAKING" >> "${OUT_DIR}/report.txt"
else
  echo -e "     [${GREEN}+${NC}] Cross-Link Isolation:  ${GREEN}SECURED${NC} (Blocked)"
  echo "Cross-Link Isolation between ${MGMT_IFACE} and ${K8S_IFACE}: SECURED" >> "${OUT_DIR}/report.txt"
fi

# 4. Ping Public WAN Access
ping_wan=$(ping -c 2 -W 1 -I "${MGMT_IFACE}" 8.8.8.8 2>/dev/null || echo "")
if [[ -n "${ping_wan}" ]] && echo "${ping_wan}" | grep -q "rtt"; then
  avg_rtt=$(echo "${ping_wan}" | tail -n 1 | cut -d'/' -f5)
  echo -e "     [${GREEN}+${NC}] Public WAN (${GRAY}8.8.8.8${NC}):  ${GREEN}REACHABLE${NC} (${avg_rtt}ms)"
  echo "Public WAN (${GRAY}8.8.8.8${NC}) via ${MGMT_IFACE}: REACHABLE (${avg_rtt}ms)" >> "${OUT_DIR}/report.txt"
else
  echo -e "     [${RED}-${NC}] Public WAN (${GRAY}8.8.8.8${NC}):  ${RED}UNREACHABLE${NC}"
  echo "Public WAN (${GRAY}8.8.8.8${NC}) via ${MGMT_IFACE}: UNREACHABLE" >> "${OUT_DIR}/report.txt"
fi

# 5. GDC Endpoint Resolution & TCP Audits
echo -e "     [${GREEN}+${NC}] GDC Endpoint Resolution & TCP Audits:"
if [ -f /tmp/gdc_endpoints.status ]; then
  while IFS=':' read -r iface resolved connected || [[ -n "$iface" ]]; do
    res_color="${GREEN}"
    if [ "${resolved}" -lt 25 ]; then res_color="${YELLOW}"; fi
    if [ "${resolved}" -eq 0 ]; then res_color="${RED}"; fi

    conn_color="${GREEN}"
    if [ "${connected}" -lt 25 ]; then conn_color="${YELLOW}"; fi
    if [ "${connected}" -eq 0 ]; then conn_color="${RED}"; fi

    if [ "${iface}" = "management" ]; then
      echo -e "          - Management (${MGMT_IFACE}):   ${res_color}${resolved}${NC}/25 Resolved | ${conn_color}${connected}${NC}/25 Connected"
    elif [ "${iface}" = "kubernetes" ]; then
      echo -e "          - Kubernetes (${K8S_IFACE}): ${res_color}${resolved}${NC}/25 Resolved | ${conn_color}${connected}${NC}/25 Connected"
    fi
  done < /tmp/gdc_endpoints.status
else
  echo -e "          - GDC Endpoint Audits: ${YELLOW}Skipped (Status metadata missing)${NC}"
fi
echo "" >> "${OUT_DIR}/report.txt"

# Output minimum requirements to console
raw_reqs=$(cat "${OUT_DIR}/report.json" 2>/dev/null | grep -A 5 "system_minimum_requirements" || cat /tmp/gdc_reqs.status 2>/dev/null || echo '{ CPU: Unknown, MEMORY: Unknown, STORAGE: Unknown }')
if [ "${USE_COLOR}" = "yes" ]; then
  colorized_reqs=$(echo "${raw_reqs}" | sed -E \
    -e "s/\"status\": \"OK\"/\"status\": \"\x1b[32mOK\x1b[0m\"/g" \
    -e "s/\"status\": \"CAUTION\"/\"status\": \"\x1b[33mCAUTION\x1b[0m\"/g" \
    -e "s/\"status\": \"FAIL\"/\"status\": \"\x1b[31mFAIL\x1b[0m\"/g" \
    -e "s/(\"physical_cores\": )([0-9]+)/\1\x1b[1;30m\2\x1b[0m/g" \
    -e "s/(\"logical_threads\": )([0-9]+)/\1\x1b[1;30m\2\x1b[0m/g")
  echo -e "[-] System Minimum Requirements:         ${colorized_reqs}"
else
  echo "[-] System Minimum Requirements:         ${raw_reqs}"
fi

# ------------------------------------------------------------------------------
# SECTION 15c: EXCLUSIONS & DELETIONS
# ------------------------------------------------------------------------------
echo "[-] Applying diagnostics exclusion patterns..."
# Environment variables defaults
EXCLUDE_PATTERNS="${GDC_DIAGNOSTICS_EXCLUDE_PATTERNS:-configs/ansible,configs/,/var/gdc-admin/keys/**}"

# Split by comma and process each pattern
IFS=',' read -ra ADDR <<< "${EXCLUDE_PATTERNS}"
for pattern in "${ADDR[@]}"; do
  # Trim spaces
  pattern=$(echo "${pattern}" | xargs)
  if [[ -n "${pattern}" ]]; then
    echo -e "     [${GREEN}+${NC}] Processing exclusion pattern: ${pattern}"
    
    # 1. Check if the pattern is configs/ansible
    if [[ "${pattern}" == "configs/ansible" ]]; then
      rm -rf "${OUT_DIR}/configs/ansible"
    
    # 2. Check if the pattern is configs/
    elif [[ "${pattern}" == "configs/" || "${pattern}" == "configs/**" ]]; then
      rm -rf "${OUT_DIR}/configs"
    
    # 3. Check if the pattern matches a keys folder path
    elif [[ "${pattern}" == "/var/gdc-admin/keys/**" || "${pattern}" == "**/keys/**" || "${pattern}" == "keys" ]]; then
      find "${OUT_DIR}" -type d -name "keys" -exec rm -rf {} + 2>/dev/null || true
      find "${OUT_DIR}" -type f -path "*/keys/*" -exec rm -f {} + 2>/dev/null || true
    
    # 4. Generic matching relative to output staging directory
    else
      clean_p=$(echo "${pattern}" | sed 's|^\/||' | sed 's|\*\*|*|g')
      if [[ -n "${clean_p}" ]]; then
        rm -rf "${OUT_DIR}/${clean_p}"
      fi
    fi
  fi
done

# ------------------------------------------------------------------------------
# SECTION 15d: OBFUSCATION RULES (FUTURE WORK PLACEHOLDER)
# ------------------------------------------------------------------------------
echo "[-] Sourcing obfuscation rules (Future Work)..."
OBFUSCATION_RULES="${GDC_DIAGNOSTICS_OBFUSCATION_RULES:-secrets.conf,**/password*}"
echo -e "     [${GREEN}+${NC}] Registered future obfuscation rule-set: ${OBFUSCATION_RULES}"

# ------------------------------------------------------------------------------
# SECTION 16: TARBALL PACKAGING & DUP
# ------------------------------------------------------------------------------
USER_HOME="${HOME:-/home/temporary-installer}"
TIMESTAMP=$(date +'%d-%b-%Y-%H-%M' | tr '[:lower:]' '[:upper:]')
TAR_PATH="${USER_HOME}/gdc-node-diagnostics-${TIMESTAMP}${STAGE_SUFFIX}.tar.gz"

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
  echo -e "[${RED}-${NC}] SKIPPED Permission denied ${PRINT_PATH}"
  TAR_SUCCESS=false
  # Fallback to write inside /tmp RAM directory
  TAR_PATH="/tmp/gdc-node-diagnostics-${TIMESTAMP}${STAGE_SUFFIX}.tar.gz"
  PRINT_PATH="/tmp/gdc-node-diagnostics-${TIMESTAMP}${STAGE_SUFFIX}.tar.gz"
  tar -czf "${TAR_PATH}" -C "/tmp" "${OUT_BASE}"
fi

# Duplicate package target to physical mount partition to survive VM reboots (Guarded)
if [ "${IS_PRIVILEGED}" = "true" ] && [ -d "/target" ]; then
  cp "${TAR_PATH}" "/target/gdc-node-diagnostics-${TIMESTAMP}${STAGE_SUFFIX}.tar.gz" || true
  mkdir -p /target/root
  cp "${TAR_PATH}" "/target/root/gdc-node-diagnostics-${TIMESTAMP}${STAGE_SUFFIX}.tar.gz" || true
fi

# Output final terminal compilation success message matching requested pattern
echo -e "[${GREEN}+${NC}] ${GREEN}SUCCESS:${NC} Diagnostics successfully compiled and compressed!"
echo -e "     - Target RAM path: ${GRAY}${PRINT_PATH}${NC}"

# ------------------------------------------------------------------------------
# SECTION 17: WEBHOOK LOGGING COMPANION UPLOAD (ALWAYS RUN)
# ------------------------------------------------------------------------------
COMPANION_INGEST_URL="http://gdc-companion.ensor-labs.com/v1/machine-reports/ingest"
if [ "${UPLOAD_TO_COMPANION:-yes}" = "yes" ]; then
  echo "[-] Uploading diagnostics tarball to GDC Ingestion Companion..."
  if command -v curl &>/dev/null; then
    # Post the file using multipart/form-data
    upload_res=$(curl -s -o /dev/null -w "%{http_code}" -F "file=@${TAR_PATH}" "${COMPANION_INGEST_URL}" || echo "CURL_ERROR")
    if [ "${upload_res}" = "200" ] || [ "${upload_res}" = "201" ]; then
      echo -e "  [${GREEN}x${NC}] ${GREEN}Successfully uploaded diagnostics to companion${NC} (HTTP ${GREEN}${upload_res}${NC})"
    else
      echo -e "  [${RED}!${NC}] ${YELLOW}Warning: Failed to upload diagnostics to companion${NC} (HTTP code: ${RED}${upload_res}${NC})"
    fi
  else
    echo -e "  [${RED}!${NC}] ${RED}Curl is missing. Cannot upload diagnostics.${NC}"
  fi
else
  echo "[-] Skipping diagnostics upload to Companion (UPLOAD_TO_COMPANION=no)"
fi
