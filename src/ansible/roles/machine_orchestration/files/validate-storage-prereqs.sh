#!/usr/bin/env bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
set -eo pipefail

ENGINE_MODE="${1:-v2}" # Default to v2 if not supplied; pass "v1" or "v2"

MIN_INOTIFY_WATCHES="${MIN_INOTIFY_WATCHES:-524288}"
MIN_HUGEPAGES="${MIN_HUGEPAGES:-2048}"

echo "=== 1. Common: Checking iscsid Service ==="
if systemctl is-active --quiet iscsid; then
  echo "OK: iscsid is running"
else
  echo "FAIL: iscsid is inactive or missing"
  exit 1
fi

echo "=== 2. Common: Checking inotify Limits ==="
WATCHES=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo 0)
if [ "$WATCHES" -ge "$MIN_INOTIFY_WATCHES" ]; then
  echo "OK: fs.inotify.max_user_watches = $WATCHES"
else
  echo "FAIL: fs.inotify.max_user_watches ($WATCHES) < $MIN_INOTIFY_WATCHES"
  exit 1
fi

echo "=== 3. Common: Checking NVMe Schedulers ==="
NVME_FOUND=0
for dev in /sys/block/nvme*n1; do
  if [ -d "$dev" ]; then
    NVME_FOUND=1
    SCHED=$(cat "$dev/queue/scheduler" 2>/dev/null || true)
    echo "Device $(basename "$dev") scheduler: $SCHED"
  fi
done
if [ "$NVME_FOUND" -eq 0 ]; then
  echo "INFO: No NVMe block devices detected"
fi

echo "=== 4. Common: Checking Storage Directory ==="
if [ -d "/customer/sds" ]; then
  echo "OK: /customer/sds exists"
  df -h /customer/sds
else
  echo "FAIL: /customer/sds directory does not exist"
  exit 1
fi

echo "=== 5. Engine Verification ($ENGINE_MODE) ==="
HP=$(cat /proc/sys/vm/nr_hugepages 2>/dev/null || echo 0)

if [ "$ENGINE_MODE" = "v2" ]; then
  if [ "$HP" -ge "$MIN_HUGEPAGES" ]; then
    echo "OK: HugePages = $HP (>= $MIN_HUGEPAGES)"
  else
    echo "FAIL: HugePages ($HP) < $MIN_HUGEPAGES required for SPDK"
    exit 1
  fi

  REQUIRED_MODULES=("nvme_tcp" "uio" "uio_pci_generic" "vfio_pci")
  for mod in "${REQUIRED_MODULES[@]}"; do
    if [ -d "/sys/module/$mod" ] || lsmod | grep -q "^$mod "; then
      echo "OK: Module $mod is loaded"
    else
      echo "FAIL: Module $mod is not loaded"
      exit 1
    fi
  done
elif [ "$ENGINE_MODE" = "v1" ]; then
  if [ "$HP" -eq 0 ]; then
    echo "OK: HugePages disabled ($HP) for v1"
  else
    echo "WARN: HugePages is set to $HP; should be 0 for v1 to reclaim memory"
  fi
else
  echo "FAIL: Unknown ENGINE_MODE '$ENGINE_MODE'. Expected 'v1' or 'v2'."
  exit 1
fi
