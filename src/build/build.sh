#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader - Re-build Custom ISO Builder Container
# ==============================================================================
# Builds and registers the 'iso-builder' container in Google Artifact Registry.
# Enforces that all critical environment variables are set before execution.
# ==============================================================================

set -euo pipefail

# ==========================================
# 1. Enforce Mandatory Environment Variables
# ==========================================
MISSING_VARS=0
for var in PROJECT_ID BUILD_VERSION REGION; do
    if [[ -z "${!var:-}" ]]; then
        echo "[!] Error: Mandatory environment variable '${var}' is not set." >&2
        MISSING_VARS=1
    fi
done

if [[ "${MISSING_VARS}" -eq 1 ]]; then
    echo "" >&2
    echo "Please set the required environment variables before running this script:" >&2
    echo "  export PROJECT_ID=\"your-gcp-project-id\"" >&2
    echo "  export BUILD_VERSION=\"1.0.0\"" >&2
    echo "  export REGION=\"us-central1\"" >&2
    exit 1
fi

# Find script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ==========================================
# 2. Verify or Create Google Artifact Registry (GAR)
# ==========================================
echo "[-] Checking for Artifact Registry 'gdc-build-images' in ${REGION}..."
if ! gcloud artifacts repositories describe gdc-build-images \
    --location="${REGION}" \
    --project="${PROJECT_ID}" &>/dev/null; then
    echo "[-] Repository 'gdc-build-images' not found. Creating it dynamically in ${REGION}..."
    gcloud artifacts repositories create gdc-build-images \
        --repository-format=docker \
        --location="${REGION}" \
        --description="GDC ISO compilation builder images" \
        --project="${PROJECT_ID}"
    echo "[-] Repository created successfully."
else
    echo "[-] Verified existing 'gdc-build-images' repository."
fi

# ==========================================
# 3. Launch Container Cloud Build
# ==========================================
TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/gdc-build-images/iso-builder:${BUILD_VERSION}"

echo "=============================================================================="
echo " COMPILING GDC ISO BUILDER CONTAINER"
echo "=============================================================================="
echo "  GCP Project ID:  ${PROJECT_ID}"
echo "  GCP Region:      ${REGION}"
echo "  Builder Tag:     ${TAG}"
echo "=============================================================================="
echo "[-] Initiating gcloud container builds..."

# Submit build to register in Google Artifact Registry
gcloud builds submit "${SCRIPT_DIR}" \
    --tag="${TAG}" \
    --project="${PROJECT_ID}"

echo "[-] Builder container compiled and registered successfully."
