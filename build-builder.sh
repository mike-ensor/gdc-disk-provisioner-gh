#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# GDC Bootloader - ISO Builder Container Compiler Job
# ==============================================================================
# Auto-increments the builder container version in .envrc, compiles the custom
# Python/Jinja2-capable build image, and pushes it to GCP Artifact Registry.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENVRC_FILE="${PROJECT_ROOT}/.envrc"

echo "=============================================================================="
echo -e "\033[93m\033[1m[BUILDER-JOB] AUTO-INCREMENTING BUILDER CONTAINER VERSION IN .envrc...\033[0m"
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
echo -e "\033[93m\033[1m[BUILDER-JOB] LOADING RE-SOURCED CONFIGURATIONS...\033[0m"
echo "=============================================================================="
# Reload the environment to grab the fresh builder version
# shellcheck source=/dev/null
source "${ENVRC_FILE}"

echo "  GCP Project ID:  ${PROJECT_ID}"
echo "  GCP Region:      ${REGION}"
echo "  Builder Version: ${BUILD_VERSION}"
echo "=============================================================================="

echo "=============================================================================="
echo -e "\033[93m\033[1m[BUILDER-JOB] COMPILING AND REGISTERING CUSTOM ISO BUILDER CONTAINER...\033[0m"
echo "=============================================================================="
# Compile and push the container image to Google Artifact Registry
"${PROJECT_ROOT}/src/build/build.sh"

echo "=============================================================================="
echo -e "\033[92m\033[1m[x] BUILDER-JOB SUCCESS: Custom compilation container is registered!\033[0m"
echo "=============================================================================="
