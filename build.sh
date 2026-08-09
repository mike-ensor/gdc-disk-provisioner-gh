#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader - Google Cloud Build Trigger
# ==============================================================================
# Initiates the custom GDC ISO compilation pipeline in Google Cloud Build.
# Enforces that all critical environment variables are set before execution.
# ==============================================================================

set -euo pipefail

# Find script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"

# Load ISO_VERSION from the committed VERSION file as the source of truth
if [[ -f "${PROJECT_ROOT}/VERSION" ]]; then
    export ISO_VERSION=$(tr -d '[:space:]' < "${PROJECT_ROOT}/VERSION")
    echo "[-] Loaded ISO_VERSION from VERSION file: ${ISO_VERSION}"
fi

# ==========================================
# 1. Enforce Mandatory Environment Variables
# ==========================================
MISSING_VARS=0
for var in PROJECT_ID BUILD_VERSION REGION ISO_VERSION; do
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
    echo "  export ISO_VERSION=\"1.0.0\"" >&2
    exit 1
fi

ENV_FILE="${PROJECT_ROOT}/src/build/build.env"

# ==========================================
# 2. Auto-Increment ISO_VERSION Patch in VERSION and .envrc
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
else
    echo "[!] Warning: ISO_VERSION '${ISO_VERSION}' does not match semver format. Skipping auto-increment." >&2
fi

# ==========================================
# 3. Parse Defaults from build.env
# ==========================================
GCS_BUCKET_DEFAULT=""
SOURCE_ISO_DEFAULT="ubuntu-24.04-live-server-amd64.iso"

if [[ -f "${ENV_FILE}" ]]; then
    GCS_BUCKET_DEFAULT=$(grep "^GCS_BUCKET=" "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"'\')
    SOURCE_ISO_DEFAULT=$(grep "^SOURCE_ISO_FILENAME=" "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"'\')
fi

# Initialize runtime variables
GCS_BUCKET="${GCS_BUCKET_DEFAULT}"
SOURCE_ISO_FILENAME="${SOURCE_ISO_DEFAULT}"

# ==========================================
# 4. Help and Usage Menu
# ==========================================
show_help() {
    echo "GDC ISO Cloud Build Launcher"
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -b, --bucket VALUE       GCS Bucket Name (default: ${GCS_BUCKET_DEFAULT:-None})"
    echo "  -f, --filename VALUE     Blessed Source ISO Filename (default: ${SOURCE_ISO_DEFAULT})"
    echo "  -c, --customer-assets VAL Customer-supplied assets tarball URI (GCS or HTTPS)"
    echo "  -h, --help               Show this help menu"
    echo ""
    echo "Environment Variables (Enforced):"
    echo "  PROJECT_ID               Active GCP Project ID"
    echo "  BUILD_VERSION            Custom builder image tag (iso-builder:BUILD_VERSION)"
    echo "  REGION                   GCP Region for registry and metadata lookup"
    echo "  ISO_VERSION              Version tag for the custom GDC ISO"
    echo ""
    echo "Example:"
    echo "  export PROJECT_ID=\"my-project\" BUILD_VERSION=\"1.0.0\" REGION=\"us-central1\" ISO_VERSION=\"1.0.2\""
    echo "  $0 --bucket gdc-disk-provisioner-isos"
    exit 0
}

# ==========================================
# 5. Parse Command Line Arguments
# ==========================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--bucket)
            GCS_BUCKET="$2"
            shift 2
            ;;
        -f|--filename)
            SOURCE_ISO_FILENAME="$2"
            shift 2
            ;;
        -c|--customer-assets)
            CUSTOMER_ASSETS_URI="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo "[!] Error: Unknown argument '$1'" >&2
            exit 1
            ;;
    esac
done

# ==========================================
# 6. Apply Environment Overrides
# ==========================================
if [[ -n "${ISO_OUTPUT_BUCKET:-}" ]]; then
    echo "[-] Environment variable ISO_OUTPUT_BUCKET is set. Overriding target bucket to: ${ISO_OUTPUT_BUCKET}"
    GCS_BUCKET="${ISO_OUTPUT_BUCKET}"
fi

# Strip gs:// prefix from bucket name for clean Cloud Build substitution
GCS_BUCKET_NAME="${GCS_BUCKET#gs://}"
ISO_BLESSED_GCS_BUCKET_NAME="${ISO_BLESSED_GCS_BUCKET:-}"
ISO_BLESSED_GCS_BUCKET_NAME="${ISO_BLESSED_GCS_BUCKET_NAME#gs://}"

# ==========================================
# 7. Input Validations
# ==========================================
if [[ -z "${GCS_BUCKET_NAME}" ]]; then
    echo "[!] Error: GCS Bucket Name is required. Please set GCS_BUCKET in build.env or pass --bucket." >&2
    exit 1
fi

# ==========================================
# 8. Check for GCS Target Collision
# ==========================================
ISO_NAME_PREFIX="gdc-bootstrap-ubuntu-24.04"
TARGET_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}.iso"

echo "[-] Checking GCS destination bucket for filename collisions..."
if gcloud storage objects describe "gs://${GCS_BUCKET_NAME}/sync/${TARGET_ISO_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "[!] Collision Error: GCS target 'gs://${GCS_BUCKET_NAME}/sync/${TARGET_ISO_NAME}' already exists!" >&2
    echo "[!] Please increment your ISO_VERSION in .envrc or check GCS state." >&2
    exit 1
else
    echo "[-] No collision detected. Target filename '${TARGET_ISO_NAME}' is unique."
fi

# ==========================================
# 9. Launch Cloud Build
# ==========================================
echo "=============================================================================="
echo " LAUNCHING GDC ISO CLOUD BUILD PIPELINE"
echo "=============================================================================="
echo "  GCP Project ID:  ${PROJECT_ID}"
echo "  GCP Region:      ${REGION}"
echo "  Debug ISO:       ${GDC_DEBUG_MODE:-false}"
echo "  Builder Version: ${BUILD_VERSION}"
echo "  Target ISO Ver:  ${ISO_VERSION}"
echo "  Dest GCS Bucket: gs://${GCS_BUCKET_NAME}"
if [[ -n "${ISO_BLESSED_GCS_BUCKET_NAME}" ]]; then
echo "  Source GCS Bkt:  gs://${ISO_BLESSED_GCS_BUCKET_NAME}"
else
echo "  Source GCS Bkt:  gs://${GCS_BUCKET_NAME} (Fallback)"
fi
echo "  Source ISO Name: ${SOURCE_ISO_FILENAME}"
echo "=============================================================================="
echo "[-] Initiating gcloud builds submit..."

GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "N/A")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "N/A")

BUILD_ID=$(gcloud builds submit "${PROJECT_ROOT}" \
    --config="${PROJECT_ROOT}/cloudbuild.yaml" \
    --project="${PROJECT_ID}" \
    --substitutions="_GCS_BUCKET_NAME=${GCS_BUCKET_NAME},_ISO_VERSION=${ISO_VERSION},_SOURCE_ISO_FILENAME=${SOURCE_ISO_FILENAME},_BUILD_VERSION=${BUILD_VERSION},_REGION=${REGION},_PROJECT_ID=${PROJECT_ID},_ISO_BLESSED_GCS_BUCKET=${ISO_BLESSED_GCS_BUCKET_NAME},_GDC_DEBUG_MODE=${GDC_DEBUG_MODE:-false},_CUSTOMER_ASSETS_URI=${CUSTOMER_ASSETS_URI:-},_GIT_BRANCH=${GIT_BRANCH},_GIT_COMMIT=${GIT_COMMIT}" \
    --async --format="value(id)")

echo "[+] Cloud Build job created with ID: ${BUILD_ID}"
echo "[-] Polling build status until completion..."

# Wait loop to ensure the gcloud build is completed
for i in {1..80}; do
  b_status=$(gcloud builds describe "${BUILD_ID}" --project="${PROJECT_ID}" --format="value(status)")
  echo "[Cloud Build] Status: ${b_status} (Attempt ${i}/80)"
  if [[ "${b_status}" == "SUCCESS" ]]; then
    echo "[x] Cloud Build finished successfully."
    echo "[-] Downloading canonical build reports from GCS..."
    mkdir -p "${PROJECT_ROOT}/build-workspace/output"
    gcloud storage cp "gs://${GCS_BUCKET_NAME}/reports/build-reports/build-report-v${ISO_VERSION}.json" "${PROJECT_ROOT}/build-workspace/output/" || true
    gcloud storage cp "gs://${GCS_BUCKET_NAME}/reports/build-reports/build-report-v${ISO_VERSION}.md" "${PROJECT_ROOT}/build-workspace/output/" || true
    break
  elif [[ "${b_status}" == "FAILURE" || "${b_status}" == "TIMEOUT" || "${b_status}" == "CANCELLED" ]]; then
    echo "[!] Cloud Build failed with status: ${b_status}" >&2
    echo "[-] Automatically streaming failure logs..." >&2
    gcloud builds log "${BUILD_ID}" --project="${PROJECT_ID}" || true
    echo "[-] Generating local failure build report..." >&2
    python3 "${PROJECT_ROOT}/bin/generate_build_report.py" \
      --build-id "${BUILD_ID}" \
      --project-id "${PROJECT_ID}" \
      --gcs-bucket "gs://${GCS_BUCKET_NAME}" \
      --iso-version "${ISO_VERSION}" \
      --status "FAILED" \
      --output-dir "${PROJECT_ROOT}/build-workspace/output" || true
    echo "" >&2
    echo "[!] A localized failure report has been written to build-workspace/output/build-report-v${ISO_VERSION}.md" >&2
    exit 1
  fi
  sleep 15
done
