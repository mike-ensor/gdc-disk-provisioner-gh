#!/usr/bin/env bash

# ==============================================================================
# GDC Bootloader ISO Build & Release Orchestrator
# ==============================================================================
# Triggers the complete sequential pipeline to compile both the container builder
# and the custom GDC bootloader ISO, then registers the image in Bootimus PXE.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================================================="
echo "GDC BOOTLOADER - ULTIMATE MASTER RELEASE ORCHESTRATOR"
echo "=============================================================================="

# 1. Trigger the Tooling Container Builder Job
"${PROJECT_ROOT}/build-builder.sh"

# 2. Trigger the Custom ISO Remastering & PXE Ingestion Job
"${PROJECT_ROOT}/build-iso.sh"

echo "=============================================================================="
echo -e "\033[92m\033[1m[x] SUCCESS: ALL PIPELINES AND PXE DEPLOYMENTS COMPLETED SUCCESSFULLY!\033[0m"
echo "=============================================================================="
