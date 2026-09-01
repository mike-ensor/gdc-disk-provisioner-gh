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

# Source .envrc
if [[ -f "${PROJECT_ROOT}/.envrc" ]]; then
    # shellcheck source=/dev/null
    source "${PROJECT_ROOT}/.envrc"
fi

# Load ISO_VERSION from VERSION file
export ISO_VERSION=$(tr -d '[:space:]' < "${PROJECT_ROOT}/VERSION")

# Sourcing helper
BUILD_ENV="${PROJECT_ROOT}/src/build/build.env"
LOCAL_ENV="${PROJECT_ROOT}/src/build/local.env"

get_env() {
    (
        set -a
        [ -f src/dependencies.env ] && . src/dependencies.env &>/dev/null
        [ -f src/build/build.env ] && . src/build/build.env &>/dev/null
        [ -f src/build/local.env ] && . src/build/local.env &>/dev/null
        if [ -n "$1" ]; then eval echo "\${$1:-}"; fi
    )
}

# Enforce required variables
export PROJECT_ID="${PROJECT_ID:-anthos-bare-metal-lab-1}"
export REGION="${REGION:-us-west1}"
export BUILD_VERSION="${BUILD_VERSION:-0.0.89}"
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
echo "=============================================================================="

ISO_DEFAULT_NAME="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}-debug.iso"
ISO_NOCOMP_NAME="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}-no-comp-debug.iso"

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
        break
    fi

    sleep 15
done

# 4. Deploy both ISOs to Bootimus
echo "=============================================================================="
echo " STEP 4: INGESTING AND PROVISIONING BOTH ISOS ON BOOTIMUS"
echo "=============================================================================="

for ISO_NAME in "${ISO_DEFAULT_NAME}" "${ISO_NOCOMP_NAME}"; do
    echo "[-] Processing Bootimus deployment for: ${ISO_NAME}"
    python3 "${PROJECT_ROOT}/src/build/bootimus.py" "${ISO_NAME}" || true
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
