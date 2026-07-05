#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader - Custom ISO Remastering & PXE Deploy Job
# ==============================================================================
# Triggers the Google Cloud Build remastering pipeline, compiles the custom GDC
# ISO, and dynamically deploys/provisions it inside the Bootimus PXE server.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENVRC_FILE="${PROJECT_ROOT}/.envrc"

if [[ ! -f "${ENVRC_FILE}" ]]; then
    echo "[!] Error: .envrc not found at ${ENVRC_FILE}" >&2
    exit 1
fi

# Load current environment configurations
# shellcheck source=/dev/null
source "${ENVRC_FILE}"

# Sync with VERSION file as the main source of truth
if [[ -f "${PROJECT_ROOT}/VERSION" ]]; then
    export ISO_VERSION=$(tr -d '[:space:]' < "${PROJECT_ROOT}/VERSION")
fi

echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] LOADING ACTIVE WORKSPACE ENVIRONMENT...\033[0m"
echo "=============================================================================="
echo "  GCP Project ID:  ${PROJECT_ID}"
echo "  GCP Region:      ${REGION}"
echo "  Builder Version: ${BUILD_VERSION}"
echo "  ISO Version:     ${ISO_VERSION}"
echo "=============================================================================="

echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] REMASTERING AND COMPILING THE NEW CUSTOM GDC ISO...\033[0m"
echo "=============================================================================="
# Trigger the Cloud Build ISO remastering pipeline (auto-increments ISO_VERSION in .envrc)
"${PROJECT_ROOT}/build.sh"

# Reload .envrc to capture the newly incremented ISO_VERSION written by build.sh
# shellcheck source=/dev/null
source "${ENVRC_FILE}"

if [[ "${GDC_DEBUG_MODE:-false}" == "true" ]]; then
    NEW_ISO_NAME="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}-debug.iso"
else
    NEW_ISO_NAME="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso"
fi

echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] LISTING ACTIVE BOOTIMUS IMAGES AND PXE GROUPS...\033[0m"
echo "=============================================================================="
# Query current Bootimus PXE database status
"${PROJECT_ROOT}/src/build/bootimus.py" --list

echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] INGESTING, EXTRACTING, AND PROVISIONING ISO ON PXE SERVER...\033[0m"
echo "=============================================================================="
# Ingest and apply custom PXE boot parameters to the newly compiled release image
"${PROJECT_ROOT}/src/build/bootimus.py" "${NEW_ISO_NAME}"

echo "=============================================================================="
echo -e "\033[92m\033[1m[x] ISO-JOB SUCCESS: GDC ISO compiled and dynamically deployed on PXE!\033[0m"
echo "=============================================================================="
