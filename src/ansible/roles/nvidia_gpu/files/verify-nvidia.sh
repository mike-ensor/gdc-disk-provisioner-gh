#!/usr/bin/env bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
#
# verify-nvidia.sh: Validates NVIDIA GPU hardware detection, Nouveau suppression,
# open kernel driver installation, kernel modules (modprobe), device nodes,
# nvidia-smi communication, nvidia-persistenced service, and container runtime.
#
# Usage:
#   sudo /usr/local/bin/verify-nvidia.sh          # Human-readable stdout
#   sudo /usr/local/bin/verify-nvidia.sh --json   # Machine-readable JSON for statefiles
#   sudo /usr/local/bin/verify-nvidia.sh --quiet  # Silent exit-code check

set -uo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

JSON_MODE=false
QUIET_MODE=false

for arg in "$@"; do
  case "$arg" in
    --json)
      JSON_MODE=true
      ;;
    --quiet|-q)
      QUIET_MODE=true
      ;;
  esac
done

OVERALL_STATUS="PASS"
CHECKS=()
DETAILS=()
GPU_PRESENT=false
PCI_BUS="NONE"
GPU_NAME="NONE"
DRIVER_VERSION="NONE"
CUDA_VERSION="NONE"
NOUVEAU_SUPPRESSED=true
KERNEL_MODULES_LOADED=false
DEVICE_NODES_PRESENT=false
NVIDIA_SMI_OK=false
PERSISTENCED_ACTIVE=false
CONTAINER_TOOLKIT_OK=false

log_ok() {
  local check="$1"
  local msg="$2"
  DETAILS+=("OK: $msg")
  CHECKS+=("{\"name\": \"$check\", \"status\": \"PASS\", \"message\": \"$msg\"}")
  if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
    echo "  [+] OK: $msg"
  fi
}

log_fail() {
  local check="$1"
  local msg="$2"
  OVERALL_STATUS="FAIL"
  DETAILS+=("FAIL: $msg")
  CHECKS+=("{\"name\": \"$check\", \"status\": \"FAIL\", \"message\": \"$msg\"}")
  if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
    echo "  [!] FAIL: $msg" >&2
  fi
}

log_info() {
  local check="$1"
  local msg="$2"
  DETAILS+=("INFO: $msg")
  CHECKS+=("{\"name\": \"$check\", \"status\": \"SKIPPED\", \"message\": \"$msg\"}")
  if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
    echo "  [-] INFO: $msg"
  fi
}

is_module_loaded() {
  local mod="$1"
  lsmod 2>/dev/null | awk -v m="$mod" '$1 == m {found=1} END {exit !found}'
}

# --- 1. PCI Hardware Probe ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 1. PCI Hardware Probe ==="
fi

PCI_RAW=$(lspci -nn 2>/dev/null | grep -E '\[(0300|0302|0380)\]:.*10de:' || true)
if [ -z "$PCI_RAW" ]; then
  log_info "pci_detection" "No NVIDIA GPU detected on PCI bus (SKIPPED_NO_GPU)"
  if [ "$JSON_MODE" = true ]; then
    cat <<EOF
{
  "status": "SKIPPED_NO_GPU",
  "gpu_present": false,
  "pci_bus": "NONE",
  "gpu_name": "NONE",
  "driver_version": "NONE",
  "nouveau_suppressed": true,
  "kernel_modules_loaded": false,
  "device_nodes_present": false,
  "nvidia_smi_ok": false,
  "persistenced_active": false,
  "container_toolkit_ok": false,
  "message": "No NVIDIA display or compute controllers detected on PCI bus",
  "checks": [
    {"name": "pci_detection", "status": "SKIPPED", "message": "No NVIDIA GPU detected on PCI bus"}
  ],
  "details": ["INFO: No NVIDIA GPU detected on PCI bus (SKIPPED_NO_GPU)"]
}
EOF
    exit 0
  fi
  exit 0
fi

GPU_PRESENT=true
PCI_BUS=$(echo "$PCI_RAW" | head -n 1 | awk '{print $1}')
log_ok "pci_detection" "NVIDIA GPU controller detected on PCI bus: $PCI_BUS"

# --- 2. Nouveau Suppression ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 2. Nouveau Module Suppression ==="
fi

if is_module_loaded "nouveau"; then
  NOUVEAU_SUPPRESSED=false
  log_fail "nouveau_suppression" "Nouveau kernel module is currently loaded in memory"
else
  log_ok "nouveau_suppression" "Nouveau kernel module is suppressed (not loaded)"
fi

if [ -f "/etc/modprobe.d/blacklist-nouveau.conf" ] && grep -q "blacklist nouveau" /etc/modprobe.d/blacklist-nouveau.conf 2>/dev/null; then
  log_ok "nouveau_blacklist_conf" "Modprobe configuration /etc/modprobe.d/blacklist-nouveau.conf present"
else
  log_fail "nouveau_blacklist_conf" "Modprobe blacklist file /etc/modprobe.d/blacklist-nouveau.conf missing or incomplete"
fi

# --- 3. Debian Package Installation ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 3. Debian Package Installation ==="
fi

for pkg in "nvidia-driver-580-open" "nvidia-utils-580" "nvidia-container-toolkit"; do
  if dpkg -s "$pkg" 2>/dev/null | grep -q "Status: install ok installed"; then
    pkg_ver=$(dpkg -s "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    log_ok "pkg_$pkg" "Package $pkg is installed ($pkg_ver)"
  else
    log_fail "pkg_$pkg" "Package $pkg is NOT installed or broken"
  fi
done

# --- 4. Kernel Modules (modprobe & lsmod) ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 4. Kernel Modules (modprobe / lsmod) ==="
fi

# Attempt loading nvidia modules if not already loaded
if ! is_module_loaded "nvidia"; then
  modprobe nvidia 2>/dev/null || sudo modprobe nvidia 2>/dev/null || true
fi
if ! is_module_loaded "nvidia_uvm"; then
  modprobe nvidia_uvm 2>/dev/null || sudo modprobe nvidia_uvm 2>/dev/null || true
fi
if ! is_module_loaded "nvidia_modeset"; then
  modprobe nvidia_modeset 2>/dev/null || sudo modprobe nvidia_modeset 2>/dev/null || true
fi

MODULES_ALL_OK=true

if is_module_loaded "nvidia"; then
  log_ok "modprobe_nvidia" "Kernel module 'nvidia' is loaded"
else
  log_fail "modprobe_nvidia" "Kernel module 'nvidia' is NOT loaded"
  MODULES_ALL_OK=false
fi

if is_module_loaded "nvidia_uvm"; then
  log_ok "modprobe_nvidia_uvm" "Kernel module 'nvidia_uvm' is loaded"
else
  log_fail "modprobe_nvidia_uvm" "Kernel module 'nvidia_uvm' is NOT loaded"
  MODULES_ALL_OK=false
fi

if is_module_loaded "nvidia_modeset"; then
  log_ok "modprobe_nvidia_modeset" "Kernel module 'nvidia_modeset' is loaded"
else
  log_fail "modprobe_nvidia_modeset" "Kernel module 'nvidia_modeset' is NOT loaded"
  MODULES_ALL_OK=false
fi

KERNEL_MODULES_LOADED=$MODULES_ALL_OK

# --- 5. Device Nodes ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 5. Device Nodes ==="
fi

if [ -c "/dev/nvidia0" ] && [ -c "/dev/nvidiactl" ]; then
  DEVICE_NODES_PRESENT=true
  log_ok "device_nodes" "Device character nodes /dev/nvidia0 and /dev/nvidiactl exist"
else
  log_fail "device_nodes" "Device character nodes /dev/nvidia* are missing"
fi

# --- 6. nvidia-smi Query & Communication ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 6. nvidia-smi Communication ==="
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  SMI_OUTPUT=$(nvidia-smi 2>&1 || true)
  if echo "$SMI_OUTPUT" | grep -qi "couldn't communicate with the NVIDIA driver"; then
    log_fail "nvidia_smi" "nvidia-smi failed to communicate with NVIDIA kernel driver"
  elif [ -n "$SMI_OUTPUT" ] && ! echo "$SMI_OUTPUT" | grep -qi "failed"; then
    NVIDIA_SMI_OK=true
    SMI_QUERY=$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -n 1 || true)
    if [ -n "$SMI_QUERY" ]; then
      GPU_NAME=$(echo "$SMI_QUERY" | cut -d',' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      DRIVER_VERSION=$(echo "$SMI_QUERY" | cut -d',' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    fi
    log_ok "nvidia_smi" "nvidia-smi operational (GPU: $GPU_NAME, Driver: $DRIVER_VERSION)"
  else
    log_fail "nvidia_smi" "nvidia-smi command exited with error: $SMI_OUTPUT"
  fi
else
  log_fail "nvidia_smi" "nvidia-smi binary not found in PATH"
fi

# --- 7. nvidia-persistenced.service ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 7. nvidia-persistenced Daemon Service ==="
fi

if systemctl is-active --quiet nvidia-persistenced.service 2>/dev/null; then
  PERSISTENCED_ACTIVE=true
  log_ok "persistenced_service" "nvidia-persistenced.service is active and running"
else
  log_fail "persistenced_service" "nvidia-persistenced.service is not active"
fi

# --- 8. NVIDIA Container Toolkit ---
if [ "$JSON_MODE" = false ] && [ "$QUIET_MODE" = false ]; then
  echo "=== 8. NVIDIA Container Toolkit Runtime ==="
fi

if command -v nvidia-ctk >/dev/null 2>&1; then
  CTK_VERSION=$(nvidia-ctk --version 2>/dev/null | head -n 1 | awk '{print $NF}' || echo "unknown")
  CONTAINER_TOOLKIT_OK=true
  log_ok "container_toolkit" "nvidia-ctk operational (version $CTK_VERSION)"
else
  log_fail "container_toolkit" "nvidia-ctk binary missing or non-executable"
fi

# --- Output Formatting ---
if [ "$JSON_MODE" = true ]; then
  CHECKS_JSON=$(IFS=,; echo "${CHECKS[*]}")
  
  DETAILS_JSON="["
  FIRST=true
  for line in "${DETAILS[@]}"; do
    clean_line=$(echo "$line" | sed 's/"/\\"/g')
    if [ "$FIRST" = true ]; then
      DETAILS_JSON+="\"$clean_line\""
      FIRST=false
    else
      DETAILS_JSON+=", \"$clean_line\""
    fi
  done
  DETAILS_JSON+="]"

  cat <<EOF
{
  "status": "$OVERALL_STATUS",
  "gpu_present": $GPU_PRESENT,
  "pci_bus": "$PCI_BUS",
  "gpu_name": "$GPU_NAME",
  "driver_package": "nvidia-driver-580-open",
  "driver_version": "$DRIVER_VERSION",
  "nouveau_suppressed": $NOUVEAU_SUPPRESSED,
  "kernel_modules_loaded": $KERNEL_MODULES_LOADED,
  "device_nodes_present": $DEVICE_NODES_PRESENT,
  "nvidia_smi_ok": $NVIDIA_SMI_OK,
  "persistenced_active": $PERSISTENCED_ACTIVE,
  "container_toolkit_ok": $CONTAINER_TOOLKIT_OK,
  "checks": [
    $CHECKS_JSON
  ],
  "details": $DETAILS_JSON
}
EOF
fi

if [ "$OVERALL_STATUS" = "PASS" ]; then
  exit 0
else
  exit 1
fi
