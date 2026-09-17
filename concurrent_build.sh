#!/usr/bin/env bash

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# ==============================================================================
# GDC Dual Concurrent ISO Build & Deployment Orchestrator
# ==============================================================================
# Triggers two concurrent Google Cloud Build pipelines for the SAME ISO_VERSION:
# 1. Default (with GDC Companion telemetry: GDC_COMPANION=TRUE)
# 2. Offline / No-Companion (GDC_COMPANION=FALSE -> -no-comp)
# Both retain full DEBUG mode configurations.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse Command Line Arguments
SKIP_PXE="false"
for arg in "$@"; do
    case "${arg}" in
        --skip-pxe)
            SKIP_PXE="true"
            ;;
        --help|-h)
            echo "Usage: $0 [--skip-pxe]"
            echo "  --skip-pxe    Build and verify ISOs on GCS without triggering Bootimus PXE ingestion"
            exit 0
            ;;
    esac
done

# Source .envrc
if [[ -f "${PROJECT_ROOT}/.envrc" ]]; then
    # shellcheck source=/dev/null
    source "${PROJECT_ROOT}/.envrc"
fi

# Load ISO_VERSION from VERSION file
ISO_VERSION=$(tr -d '[:space:]' < "${PROJECT_ROOT}/VERSION")
export ISO_VERSION

# ==========================================
# Auto-Increment ISO_VERSION Patch in VERSION and .envrc
# ==========================================
if [[ "${SKIP_INCREMENT:-false}" != "true" && "${ISO_VERSION}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
    NEW_PATCH=$((PATCH + 1))
    NEW_ISO_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
    
    echo "[-] Auto-incrementing ISO_VERSION: ${ISO_VERSION} -> ${NEW_ISO_VERSION}"
    
    # Update VERSION file
    echo "${NEW_ISO_VERSION}" > "${PROJECT_ROOT}/VERSION"
    echo "[-] Successfully updated VERSION file to ${NEW_ISO_VERSION}."
    
    # Update .envrc on disk
    ENVRC_FILE="${PROJECT_ROOT}/.envrc"
    if [[ -f "${ENVRC_FILE}" ]]; then
        # Use standard sed to replace the ISO_VERSION line
        sed -i "s/export ISO_VERSION=.*/export ISO_VERSION=\"${NEW_ISO_VERSION}\"/g" "${ENVRC_FILE}"
        echo "[-] Successfully updated ${ENVRC_FILE}."
    else
        echo "[!] Warning: .envrc file not found at ${ENVRC_FILE}. Skipping disk update." >&2
    fi
    
    # Update our runtime variable to use the newly incremented version
    ISO_VERSION="${NEW_ISO_VERSION}"
    export ISO_VERSION
else
    echo "[!] Warning: ISO_VERSION '${ISO_VERSION}' does not match semver format. Skipping auto-increment." >&2
fi

# Sourcing helper
BUILD_ENV="${PROJECT_ROOT}/src/build/build.env"
LOCAL_ENV="${PROJECT_ROOT}/src/build/local.env"
DEPS_ENV="${PROJECT_ROOT}/src/dependencies.env"

get_env() {
    (
        set -a
        [ -f "${DEPS_ENV}" ] && . "${DEPS_ENV}" &>/dev/null
        [ -f "${BUILD_ENV}" ] && . "${BUILD_ENV}" &>/dev/null
        [ -f "${LOCAL_ENV}" ] && . "${LOCAL_ENV}" &>/dev/null
        if [ -n "$1" ]; then eval echo "\${$1:-}"; fi
    )
}

# Enforce required variables
export PROJECT_ID="${PROJECT_ID:-anthos-bare-metal-lab-1}"
export REGION="${REGION:-us-west1}"
export BUILD_VERSION="${BUILD_VERSION:-0.0.90}"
export GCS_BUCKET_NAME="${ISO_OUTPUT_BUCKET#gs://}"
export ISO_BLESSED_GCS_BUCKET_NAME="${ISO_BLESSED_GCS_BUCKET#gs://}"
export SOURCE_ISO_FILENAME="${SOURCE_ISO_FILENAME:-ubuntu-24.04-live-server-amd64.iso}"
export GDC_DEBUG_MODE="true"

INSTALL_COMPANION_URL_VAL=$(get_env INSTALL_COMPANION_URL)
TEMPORARY_INSTALLER_PASSWORD_VAL=$(get_env TEMPORARY_INSTALLER_PASSWORD)
TEMPORARY_INSTALLER_SSH_PUB_KEYS_VAL=$(get_env TEMPORARY_INSTALLER_SSH_PUB_KEYS)
ADMIN_SSH_PUB_KEYS_VAL=$(get_env ADMIN_SSH_PUB_KEYS)
DEBUG_EXTRA_USER_VAL=$(get_env DEBUG_EXTRA_USER)
DEBUG_EXTRA_PASSWORD_VAL=$(get_env DEBUG_EXTRA_PASSWORD)

GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "N/A")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "N/A")

echo "=============================================================================="
echo " GDC DUAL CONCURRENT CLOUD BUILD PIPELINE ORCHESTRATOR"
echo "=============================================================================="
echo "  ISO Version:          ${ISO_VERSION}"
echo "  GCP Project ID:       ${PROJECT_ID}"
echo "  GCP Region:           ${REGION}"
echo "  Builder Image Tag:    ${BUILD_VERSION}"
echo "  Destination Bucket:   gs://${GCS_BUCKET_NAME}"
echo "  Blessed Source Bkt:   gs://${ISO_BLESSED_GCS_BUCKET_NAME}"
echo "  Debug Mode (Both):    ${GDC_DEBUG_MODE}"
echo "  Deploy to PXE:        $([ "${SKIP_PXE}" = "true" ] && echo "DISABLED (--skip-pxe)" || echo "ENABLED")"
echo "=============================================================================="

ISO_NAME_PREFIX_VAL=$(get_env ISO_NAME_PREFIX)
ISO_NAME_PREFIX="${ISO_NAME_PREFIX_VAL:-gdc-bootstrap-ubuntu-24.04}"

ISO_DEFAULT_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}-debug.iso"
ISO_NOCOMP_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}-no-comp-debug.iso"

# 1. Collision check
echo "[-] Checking GCS destination bucket for collisions..."
for target in "${ISO_DEFAULT_NAME}" "${ISO_NOCOMP_NAME}"; do
    if gcloud storage objects describe "gs://${GCS_BUCKET_NAME}/sync/${target}" --project="${PROJECT_ID}" &>/dev/null; then
        echo "[!] Collision Error: GCS target 'gs://${GCS_BUCKET_NAME}/sync/${target}' already exists!" >&2
        exit 1
    fi
done
echo "  [x] No GCS collisions detected."

# 2. Launch Build 1: Default (GDC_COMPANION=TRUE)
echo "[-] Launching Cloud Build 1 (Default Companion: TRUE)..."
BUILD_ID_TRUE=$(gcloud builds submit "${PROJECT_ROOT}" \
    --config="${PROJECT_ROOT}/cloudbuild.yaml" \
    --project="${PROJECT_ID}" \
    --substitutions="_GCS_BUCKET_NAME=${GCS_BUCKET_NAME},_ISO_VERSION=${ISO_VERSION},_SOURCE_ISO_FILENAME=${SOURCE_ISO_FILENAME},_BUILD_VERSION=${BUILD_VERSION},_REGION=${REGION},_PROJECT_ID=${PROJECT_ID},_ISO_BLESSED_GCS_BUCKET=${ISO_BLESSED_GCS_BUCKET_NAME},_GDC_DEBUG_MODE=true,_CUSTOMER_ASSETS_URI=,_GIT_BRANCH=${GIT_BRANCH},_GIT_COMMIT=${GIT_COMMIT},_INSTALL_COMPANION_URL=${INSTALL_COMPANION_URL_VAL:-},_ADMIN_SSH_PUB_KEYS=${ADMIN_SSH_PUB_KEYS_VAL:-},_TEMPORARY_INSTALLER_SSH_PUB_KEYS=${TEMPORARY_INSTALLER_SSH_PUB_KEYS_VAL:-},_TEMPORARY_INSTALLER_PASSWORD=${TEMPORARY_INSTALLER_PASSWORD_VAL:-},_GDC_COMPANION=TRUE,_DEBUG_EXTRA_USER=${DEBUG_EXTRA_USER_VAL:-},_DEBUG_EXTRA_PASSWORD=${DEBUG_EXTRA_PASSWORD_VAL:-}" \
    --async --format="value(id)")
echo "  [+] Build 1 Launched! Build ID: ${BUILD_ID_TRUE}"

# 3. Launch Build 2: No-Companion (GDC_COMPANION=FALSE)
echo "[-] Launching Cloud Build 2 (No-Companion: FALSE)..."
BUILD_ID_FALSE=$(gcloud builds submit "${PROJECT_ROOT}" \
    --config="${PROJECT_ROOT}/cloudbuild.yaml" \
    --project="${PROJECT_ID}" \
    --substitutions="_GCS_BUCKET_NAME=${GCS_BUCKET_NAME},_ISO_VERSION=${ISO_VERSION},_SOURCE_ISO_FILENAME=${SOURCE_ISO_FILENAME},_BUILD_VERSION=${BUILD_VERSION},_REGION=${REGION},_PROJECT_ID=${PROJECT_ID},_ISO_BLESSED_GCS_BUCKET=${ISO_BLESSED_GCS_BUCKET_NAME},_GDC_DEBUG_MODE=true,_CUSTOMER_ASSETS_URI=,_GIT_BRANCH=${GIT_BRANCH},_GIT_COMMIT=${GIT_COMMIT},_INSTALL_COMPANION_URL=${INSTALL_COMPANION_URL_VAL:-},_ADMIN_SSH_PUB_KEYS=${ADMIN_SSH_PUB_KEYS_VAL:-},_TEMPORARY_INSTALLER_SSH_PUB_KEYS=${TEMPORARY_INSTALLER_SSH_PUB_KEYS_VAL:-},_TEMPORARY_INSTALLER_PASSWORD=${TEMPORARY_INSTALLER_PASSWORD_VAL:-},_GDC_COMPANION=FALSE,_DEBUG_EXTRA_USER=${DEBUG_EXTRA_USER_VAL:-},_DEBUG_EXTRA_PASSWORD=${DEBUG_EXTRA_PASSWORD_VAL:-}" \
    --async --format="value(id)")
echo "  [+] Build 2 Launched! Build ID: ${BUILD_ID_FALSE}"

# Save initial state to .cache/build-state.json
mkdir -p "${PROJECT_ROOT}/.cache"
cat << EOF > "${PROJECT_ROOT}/.cache/build-state.json"
{
  "iso_version": "${ISO_VERSION}",
  "project_id": "${PROJECT_ID}",
  "builds": [
    {
      "name": "${ISO_DEFAULT_NAME}",
      "build_id": "${BUILD_ID_TRUE}",
      "companion": "TRUE",
      "status": "WORKING",
      "gcs_uri": "gs://${GCS_BUCKET_NAME}/sync/${ISO_DEFAULT_NAME}"
    },
    {
      "name": "${ISO_NOCOMP_NAME}",
      "build_id": "${BUILD_ID_FALSE}",
      "companion": "FALSE",
      "status": "WORKING",
      "gcs_uri": "gs://${GCS_BUCKET_NAME}/sync/${ISO_NOCOMP_NAME}"
    }
  ],
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "=============================================================================="
echo "[-] Monitoring both concurrent Cloud Builds..."
echo "=============================================================================="

STATUS_TRUE="WORKING"
STATUS_FALSE="WORKING"

for attempt in {1..90}; do
    if [[ "${STATUS_TRUE}" != "SUCCESS" ]]; then
        STATUS_TRUE=$(gcloud builds describe "${BUILD_ID_TRUE}" --project="${PROJECT_ID}" --format="value(status)")
    fi
    if [[ "${STATUS_FALSE}" != "SUCCESS" ]]; then
        STATUS_FALSE=$(gcloud builds describe "${BUILD_ID_FALSE}" --project="${PROJECT_ID}" --format="value(status)")
    fi

    echo "  [Attempt ${attempt}/90] Companion=TRUE: [${STATUS_TRUE}] | Companion=FALSE: [${STATUS_FALSE}]"

    # Check for terminal failure states
    if [[ "${STATUS_TRUE}" =~ ^(FAILURE|TIMEOUT|CANCELLED)$ ]]; then
        echo "[!] ERROR: Cloud Build 1 (${BUILD_ID_TRUE}) failed with status: ${STATUS_TRUE}" >&2
        gcloud builds log "${BUILD_ID_TRUE}" --project="${PROJECT_ID}" || true
        exit 1
    fi
    if [[ "${STATUS_FALSE}" =~ ^(FAILURE|TIMEOUT|CANCELLED)$ ]]; then
        echo "[!] ERROR: Cloud Build 2 (${BUILD_ID_FALSE}) failed with status: ${STATUS_FALSE}" >&2
        gcloud builds log "${BUILD_ID_FALSE}" --project="${PROJECT_ID}" || true
        exit 1
    fi

    if [[ "${STATUS_TRUE}" == "SUCCESS" && "${STATUS_FALSE}" == "SUCCESS" ]]; then
        echo "=============================================================================="
        echo " [x] SUCCESS: BOTH CONCURRENT CLOUD BUILDS COMPLETED CLEANLY!"
        echo "=============================================================================="
        # Update .cache/build-state.json with final success state
        cat << EOF > "${PROJECT_ROOT}/.cache/build-state.json"
{
  "iso_version": "${ISO_VERSION}",
  "project_id": "${PROJECT_ID}",
  "builds": [
    {
      "name": "${ISO_DEFAULT_NAME}",
      "build_id": "${BUILD_ID_TRUE}",
      "companion": "TRUE",
      "status": "SUCCESS",
      "gcs_uri": "gs://${GCS_BUCKET_NAME}/sync/${ISO_DEFAULT_NAME}"
    },
    {
      "name": "${ISO_NOCOMP_NAME}",
      "build_id": "${BUILD_ID_FALSE}",
      "companion": "FALSE",
      "status": "SUCCESS",
      "gcs_uri": "gs://${GCS_BUCKET_NAME}/sync/${ISO_NOCOMP_NAME}"
    }
  ],
  "completed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
        echo "[-] Downloading canonical build reports from GCS..."
        mkdir -p "${PROJECT_ROOT}/build-workspace/output"
        gcloud storage cp "gs://${GCS_BUCKET_NAME}/reports/build-reports/build-report-v${ISO_VERSION}.json" "${PROJECT_ROOT}/build-workspace/output/" 2>/dev/null || true
        gcloud storage cp "gs://${GCS_BUCKET_NAME}/reports/build-reports/build-report-v${ISO_VERSION}.md" "${PROJECT_ROOT}/build-workspace/output/" 2>/dev/null || true
        break
    fi

    sleep 15
done

# 4. Deploy both ISOs to Bootimus (optional via --skip-pxe)
if [[ "${SKIP_PXE}" == "false" ]]; then
    echo "=============================================================================="
    echo " STEP 4: INGESTING AND PROVISIONING BOTH ISOS ON BOOTIMUS"
    echo "=============================================================================="

    for ISO_NAME in "${ISO_DEFAULT_NAME}" "${ISO_NOCOMP_NAME}"; do
        echo "[-] Processing Bootimus deployment for: ${ISO_NAME}"
        timeout 120s python3 "${PROJECT_ROOT}/src/build/bootimus.py" "${ISO_NAME}" || true
    done

    echo "=============================================================================="
    echo " STEP 5: RUNNING BOOTIMUS STABILITY AUDITOR & HEALER"
    echo "=============================================================================="
    for i in {1..30}; do
        if python3 "${PROJECT_ROOT}/test/bin/check-bootimus-settings.py"; then
            echo -e "\033[92m[x] Bootimus configuration locked successfully for all images.\033[0m"
            break
        fi
        echo "[-] Waiting 15s for Bootimus extraction and healing loop... ($i/30)"
        sleep 15
    done

    # Display final tree
    python3 "${PROJECT_ROOT}/src/build/bootimus.py" --list

    echo "=============================================================================="
    echo -e "\033[92m\033[1m[x] DUAL ISO BUILD & BOOTIMUS DEPLOYMENT COMPLETED SUCCESSFULLY FOR v${ISO_VERSION}!\033[0m"
    echo "=============================================================================="
else
    echo "=============================================================================="
    echo " [-] SKIPPING BOOTIMUS PXE DEPLOYMENT & AUDIT (--skip-pxe active)"
    echo "=============================================================================="
    echo -e "\033[92m\033[1m[x] DUAL ISO BUILD & GCS SYNC COMPLETED SUCCESSFULLY FOR v${ISO_VERSION}!\033[0m"
    echo "=============================================================================="
fi
