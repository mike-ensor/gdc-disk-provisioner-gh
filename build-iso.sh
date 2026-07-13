#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader - Custom ISO Remastering & PXE Deploy Job
# ==============================================================================
# Triggers the custom GDC bootloader ISO build pipeline (either locally or 
# remotely via Google Cloud Build), verifies the upload, synchronizes with the
# on-premises Synology, and dynamically provisions the image inside Bootimus PXE.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Setup Exit and Failure trap for compiling local build reports
cleanup_and_report() {
    local exit_code=$?
    if [[ "${exit_code}" -eq 0 ]]; then
        echo "[-] ISO Job completed successfully. Compiling local build report..."
        python3 "${PROJECT_ROOT}/bin/generate_build_report.py" --local --status "SUCCESS" --iso-version "${ISO_VERSION:-1.0.0}" || true
    else
        echo "[!] ISO Job failed! Compiling local failure build report..." >&2
        python3 "${PROJECT_ROOT}/bin/generate_build_report.py" --local --status "FAILED" --iso-version "${ISO_VERSION:-1.0.0}" || true
    fi
}
trap cleanup_and_report EXIT

# ==============================================================================
# Step 1: Environment Initialization & Override Parsing
# ==============================================================================
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

# Load additional build variables and overrides (GDC override pattern)
BUILD_ENV="${PROJECT_ROOT}/src/build/build.env"
LOCAL_ENV="${PROJECT_ROOT}/src/build/local.env"

# Sourcing function that preserves existing terminal environment variables
source_env_safe() {
    local env_file="$1"
    if [[ -f "${env_file}" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            # Skip comments and empty lines
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue
            # Extract key and value
            if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                local key="${BASH_REMATCH[1]}"
                local val="${BASH_REMATCH[2]}"
                # Strip outer quotes
                val="${val#\"}" && val="${val%\"}"
                val="${val#\'}" && val="${val%\'}"
                # Set only if not already set in active shell environment
                if [[ -z "${!key:-}" ]]; then
                    export "${key}"="${val}"
                fi
            fi
        done < "${env_file}"
    fi
}

source_env_safe "${BUILD_ENV}"
source_env_safe "${LOCAL_ENV}"

# Clean up GCS prefix from bucket name
GCS_BUCKET_NAME=$(echo "${GCS_BUCKET:-gdc-disk-provisioner-isos}" | sed 's/^gs:\/\///')

echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] STEP 1: LOADING ACTIVE WORKSPACE ENVIRONMENT...\033[0m"
echo "=============================================================================="
echo "  GCP Project ID:   ${PROJECT_ID:-anthos-bare-metal-lab-1}"
echo "  GCP Region:       ${REGION:-us-west1}"
echo "  Builder Version:  ${BUILD_VERSION:-0.0.73}"
echo "  ISO Version:      ${ISO_VERSION}"
echo "  GCS Bucket:       gs://${GCS_BUCKET_NAME}"
echo "  ENABLE_GCS:       ${ENABLE_GCS:-false}"
echo "=============================================================================="

# ==============================================================================
# Step 2: Build ISO Pipeline (Local OR Remote)
# ==============================================================================
echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] STEP 2: REMASTERING AND COMPILING CUSTOM GDC ISO...\033[0m"
echo "=============================================================================="

if [[ "${ENABLE_GCS:-false}" == "true" ]]; then
    echo "[-] Remote pipeline detected (ENABLE_GCS=true). Submitting to Google Cloud Build..."
    # Trigger the Cloud Build remastering pipeline (auto-increments ISO_VERSION in .envrc)
    "${PROJECT_ROOT}/build.sh" --bucket "${GCS_BUCKET_NAME}"
else
    echo "[-] Local pipeline detected (ENABLE_GCS=false). Compiling synchronously on host..."
    
    # Auto-increment local version patch inside VERSION and .envrc to match build.sh behaviour
    if [[ "${ISO_VERSION}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        MAJOR="${BASH_REMATCH[1]}"
        MINOR="${BASH_REMATCH[2]}"
        PATCH="${BASH_REMATCH[3]}"
        NEW_PATCH=$((PATCH + 1))
        NEW_ISO_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
        echo "[-] Auto-incrementing local ISO_VERSION: ${ISO_VERSION} -> ${NEW_ISO_VERSION}"
        echo "${NEW_ISO_VERSION}" > "${PROJECT_ROOT}/VERSION"
        sed -i "s/export ISO_VERSION=.*/export ISO_VERSION=\"${NEW_ISO_VERSION}\"/g" "${ENVRC_FILE}"
        ISO_VERSION="${NEW_ISO_VERSION}"
    fi

    # Trigger local make targets
    make -C "${PROJECT_ROOT}/src/build" all \
        ISO_VERSION="${ISO_VERSION}" \
        GDC_DEBUG_MODE="${GDC_DEBUG_MODE:-false}" \
        ENABLE_GCS="false"
fi

# Reload .envrc to capture the newly incremented ISO_VERSION written by compile step
# shellcheck source=/dev/null
source "${ENVRC_FILE}"

if [[ "${GDC_DEBUG_MODE:-false}" == "true" ]]; then
    NEW_ISO_NAME="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}-debug.iso"
else
    NEW_ISO_NAME="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso"
fi

echo ""
echo -e "\033[91m\033[1m[!] CRITICAL WARNING: DO NOT REBOOT YOUR GDC TARGET NODES YET!\033[0m"
echo -e "\033[93mThe ISO is compiled but Bootimus PXE parameters are NOT yet registered and locked.\033[0m"
echo -e "\033[93mPlease wait for this script to complete Bootimus registration and print SUCCESS.\033[0m"
echo ""

# ==============================================================================
# Step 3 & 4: Wait for Synology, Ingest and Lock PXE Config
# ==============================================================================
echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] STEP 3 & 4: INGESTING, EXTRACTING, AND PROVISIONING ISO ON BOOTIMUS...\033[0m"
echo "=============================================================================="
echo "[-] Synology background sync polling is active. Triggering file ingestion..."

# Ingest, wait for Synology GCS-to-Local transfer, and perform kernel extraction
python3 "${PROJECT_ROOT}/src/build/bootimus.py" "${NEW_ISO_NAME}"

echo "=============================================================================="
echo -e "\033[93m\033[1m[ISO-JOB] SEALING BOOTIMUS NON-INTERACTIVE COMPLIANCE AUDIT...\033[0m"
echo "=============================================================================="
# Verify and lock all Bootimus boot parameters into non-interactive mode
python3 "${PROJECT_ROOT}/bin/check-bootimus-settings.py"

# ==============================================================================
# Step 5: Create final Bootimus Tree Readiness & Build Outputs Report
# ==============================================================================
echo "=============================================================================="
echo -e "\033[92m\033[1m[ISO-JOB] STEP 5: CREATING FINAL READINESS & AUDIT TREE REPORT...\033[0m"
echo "=============================================================================="

# Query and display final Bootimus PXE tree status to prove the newly compiled ISO is fully extracted and ready
python3 "${PROJECT_ROOT}/src/build/bootimus.py" --list

# Reports caching sync (handled by EXIT trap reporting generator automatically)
echo "=============================================================================="
echo -e "\033[92m\033[1m[x] ISO-JOB SUCCESS: GDC ISO compiled, GCS-synced, deployed, and verified on Bootimus!\033[0m"
echo "=============================================================================="
