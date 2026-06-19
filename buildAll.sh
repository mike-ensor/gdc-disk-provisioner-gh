#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader - Ultimate Rapid Re-build & Deploy Orchestrator
# ==============================================================================
# Performs a complete build lifecycle execution in a single command:
#   1. Increments the builder container version (BUILD_VERSION) in .envrc.
#   2. Loads environment variables from .envrc.
#   3. Builds and pushes the new docker-builder image to GCP Artifact Registry.
#   4. Remasters and builds the custom bootable GDC ISO (build.sh).
#   5. Lists the Bootimus PXE tree to verify status.
#   6. Dynamically ingests, extracts, and provisions the newly built ISO in Bootimus.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENVRC_FILE="${PROJECT_ROOT}/.envrc"

echo "=============================================================================="
# Yellow ANSI Header for beautiful log separating
echo -e "\033[93m\033[1m[1/6] AUTO-INCREMENTING BUILDER CONTAINER VERSION IN .envrc...\033[0m"
echo "=============================================================================="

# 1. Parse and Auto-Increment BUILD_VERSION inside .envrc
if [[ -f "${ENVRC_FILE}" ]]; then
    # Load current variables to parse
    # shellcheck source=/dev/null
    source "${ENVRC_FILE}"
    
    if [[ "${BUILD_VERSION}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        MAJOR="${BASH_REMATCH[1]}"
        MINOR="${BASH_REMATCH[2]}"
        PATCH="${BASH_REMATCH[3]}"
        NEW_PATCH=$((PATCH + 1))
        NEW_BUILD_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
        
        echo "[-] Incrementing BUILD_VERSION in .envrc: ${BUILD_VERSION} -> ${NEW_BUILD_VERSION}"
        sed -i "s/export BUILD_VERSION=.*/export BUILD_VERSION=\"${NEW_BUILD_VERSION}\"/g" "${ENVRC_FILE}"
    else
        echo "[!] Warning: BUILD_VERSION '${BUILD_VERSION}' is not semver. Skipping increment."
    fi
else
    echo "[!] Error: .envrc not found at ${ENVRC_FILE}" >&2
    exit 1
fi

echo "=============================================================================="
echo -e "\033[93m\033[1m[2/6] LOADING RE-SOURCED ENVIRONMENT CONFIGURATIONS...\033[0m"
echo "=============================================================================="
# Reload the environment to grab the fresh builder version and other vars
# shellcheck source=/dev/null
source "${ENVRC_FILE}"

echo "  GCP Project ID:  ${PROJECT_ID}"
echo "  GCP Region:      ${REGION}"
echo "  Builder Version: ${BUILD_VERSION}"
echo "  ISO Version:     ${ISO_VERSION}"
echo "=============================================================================="

echo "=============================================================================="
echo -e "\033[93m\033[1m[3/6] RE-BUILDING AND REGISTERING CUSTOM ISO BUILDER CONTAINER...\033[0m"
echo "=============================================================================="
# Compile and push the new python3-capable container image to Artifact Registry
"${PROJECT_ROOT}/src/build/build.sh"

echo "=============================================================================="
echo -e "\033[93m\033[1m[4/6] REMASTERING AND COMPILING THE NEW CUSTOM GDC ISO...\033[0m"
echo "=============================================================================="
# Launch the cloud build to remaster and compile the ISO, incrementing ISO_VERSION in .envrc
"${PROJECT_ROOT}/build.sh"

# Reload .envrc again to capture the newly incremented ISO_VERSION written by build.sh
# shellcheck source=/dev/null
source "${ENVRC_FILE}"
NEW_ISO_NAME="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso"

echo "=============================================================================="
echo -e "\033[93m\033[1m[5/6] LISTING ACTIVE BOOTIMUS IMAGES AND GROUPS...\033[0m"
echo "=============================================================================="
# Query current Bootimus status
"${PROJECT_ROOT}/src/build/bootimus.py" --list

echo "=============================================================================="
echo -e "\033[93m\033[1m[6/6] INGESTING, EXTRACTING, AND PROVISIONING THE ISO ON PXE SERVER...\033[0m"
echo "=============================================================================="
# Trigger file scanner, wait for the new ISO to appear, extract, and apply parameters
"${PROJECT_ROOT}/src/build/bootimus.py" "${NEW_ISO_NAME}"

echo "=============================================================================="
echo -e "\033[92m\033[1m[x] SUCCESS: ALL PIPELINES AND PXE DEPLOYMENTS COMPLETED SUCCESSFULLY!\033[0m"
echo "=============================================================================="
