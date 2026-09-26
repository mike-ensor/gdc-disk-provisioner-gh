#!/usr/bin/env bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
set -eo pipefail

echo "=== Checking HugePages ==="
HP=$(cat /proc/sys/vm/nr_hugepages 2>/dev/null || echo 0)
if [ "$HP" -ge 2048 ]; then
  echo "OK: HugePages = $HP (>= 2048)"
else
  echo "FAIL: HugePages ($HP) < 2048"
  exit 1
fi

echo "=== Checking Kernel Modules ==="
REQUIRED_MODULES=("nvme_tcp" "uio" "uio_pci_generic" "vfio_pci")
for mod in "${REQUIRED_MODULES[@]}"; do
  if [ -d "/sys/module/$mod" ] || lsmod | grep -q "^$mod "; then
    echo "OK: Module $mod is loaded"
  else
    echo "FAIL: Module $mod is not loaded"
    exit 1
  fi
done

echo "=== Checking Storage Directory ==="
if [ -d "/customer/sds" ]; then
  echo "OK: /customer/sds exists"
  df -h /customer/sds
else
  echo "FAIL: /customer/sds directory does not exist"
  exit 1
fi
