#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader - Synology NAS GCS ISO Puller
# ==============================================================================
# This script is designed to run headlessly on a Synology NAS (e.g., via the 
# DSM Task Scheduler) to securely pull custom GDC bootstrap ISOs from a private
# Google Cloud Storage (GCS) bucket.
#
# It automatically:
#  1. Detects system CPU architecture.
#  2. Downloads/caches the official static rclone binary (no package installation needed!).
#  3. Uses environment-based rclone configuration with your GCP Service Account JSON key.
#  4. Performs an incremental, bandwidth-optimized delta sync of ISO files.
#  5. Maintains safety and avoids partial file boots on Bootimus / PXE servers.
# ==============================================================================

set -euo pipefail

# ==========================================
# 1. User Configurations
# ==========================================
# Local directory on Synology NAS where ISOs should be saved
LOCAL_ISO_DIR="/volume1/PXE/isos"

# Google Cloud Storage Bucket Name
GCS_BUCKET_NAME="gdc-disk-provisioner-isos"

# Path to the Google Cloud Service Account JSON Key file on the NAS
GCP_SA_KEY_PATH="/volume1/PXE/gcp-sa-key.json"

# Rclone version to use if download is required
RCLONE_VERSION="v1.66.0"

# ==========================================
# 2. Environmental Initialization
# ==========================================
echo "=============================================================================="
echo " GDC ISO SYNOLOGY PULL ENGINE"
echo "=============================================================================="
echo "  Local Path:       ${LOCAL_ISO_DIR}"
echo "  GCS Source:       gs://${GCS_BUCKET_NAME}"
echo "  Service Account:  ${GCP_SA_KEY_PATH}"
echo "=============================================================================="

# Ensure local directories exist
mkdir -p "${LOCAL_ISO_DIR}"

# Validate GCS credentials file
if [[ ! -f "${GCP_SA_KEY_PATH}" ]]; then
    echo "[!] Error: GCP Service Account Key file not found at: ${GCP_SA_KEY_PATH}" >&2
    echo "[!] Please upload your GCS service-account JSON key to the NAS and update the path." >&2
    exit 1
fi

# Create a secure temporary directory inside the local ISO folder for rclone
BIN_DIR="${LOCAL_ISO_DIR}/.rclone"
mkdir -p "${BIN_DIR}"
chmod 700 "${BIN_DIR}"

# ==========================================
# 3. Dynamic Rclone Acquisition
# ==========================================
RCLONE_BIN=""
if command -v rclone &>/dev/null; then
    RCLONE_BIN="$(command -v rclone)"
    echo "[-] Found system-wide rclone binary at: ${RCLONE_BIN}"
elif [[ -f "${BIN_DIR}/rclone" ]]; then
    RCLONE_BIN="${BIN_DIR}/rclone"
    echo "[-] Found cached rclone binary at: ${RCLONE_BIN}"
else
    echo "[-] rclone not found. Attempting automatic static installation..."
    
    # Detect CPU Architecture
    ARCH=$(uname -m)
    echo "[-] Detected hardware architecture: ${ARCH}"
    
    RCLONE_ZIP_NAME=""
    case "${ARCH}" in
        x86_64)
            RCLONE_ZIP_NAME="rclone-${RCLONE_VERSION}-linux-amd64.zip"
            ;;
        aarch64)
            RCLONE_ZIP_NAME="rclone-${RCLONE_VERSION}-linux-arm64.zip"
            ;;
        armv7l)
            RCLONE_ZIP_NAME="rclone-${RCLONE_VERSION}-linux-arm-v7.zip"
            ;;
        *)
            echo "[!] Error: Unsupported Synology hardware architecture: ${ARCH}" >&2
            exit 1
            ;;
    esac
    
    DOWNLOAD_URL="https://downloads.rclone.org/${RCLONE_VERSION}/${RCLONE_ZIP_NAME}"
    echo "[-] Downloading rclone from: ${DOWNLOAD_URL}"
    
    # Use standard curl to download to temp directory
    TEMP_ZIP="${BIN_DIR}/rclone.zip"
    curl -L -s -o "${TEMP_ZIP}" "${DOWNLOAD_URL}"
    
    # Extract zip file
    echo "[-] Extracting rclone zip package..."
    # Synology DSM has unzip installed by default
    unzip -q -o -j "${TEMP_ZIP}" "*/rclone" -d "${BIN_DIR}"
    rm -f "${TEMP_ZIP}"
    
    chmod +x "${BIN_DIR}/rclone"
    RCLONE_BIN="${BIN_DIR}/rclone"
    echo "[-] Static rclone compiled binary cached successfully at: ${RCLONE_BIN}"
fi

# ==========================================
# 4. GCS Execution via Environment Config
# ==========================================
echo "[-] Initializing GCS Remote Config & Pull Sync..."

# Export rclone parameters dynamically via environment variables.
# This avoids writing any plain-text config files to disk.
export RCLONE_CONFIG_GCS_REMOTE_TYPE="google cloud storage"
export RCLONE_CONFIG_GCS_REMOTE_SERVICE_ACCOUNT_FILE="${GCP_SA_KEY_PATH}"
export RCLONE_CONFIG_GCS_REMOTE_BUCKET_POLICY_ONLY="true"

# Sync parameters:
# --update: Skip files that are newer on the destination
# --copy-links: Follow symlinks
# --gcs-location: Force optimal API endpoint behaviors
# --inplace: Write directly to target files to save RAM space on Synology,
#            but using a temporary prefix or download staging folder is safer to prevent
#            PXE/Bootimus from booting off a partially-downloaded ISO.
# We will use rclone's native "--partial-suffix" option to ensure files are renamed 
# to their final .iso names only AFTER being 100% completely downloaded!
echo "[-] Executing rclone sync..."
"${RCLONE_BIN}" copy gcs_remote:"${GCS_BUCKET_NAME}" "${LOCAL_ISO_DIR}" \
  --include "*.iso" \
  --partial-suffix ".downloading" \
  --progress \
  --verbose

echo "[-] Sync complete. ISO files available in: ${LOCAL_ISO_DIR}"
ls -lh "${LOCAL_ISO_DIR}" | grep "\.iso$" || echo "[!] No ISO files found."
echo "=============================================================================="
