#!/usr/bin/env bash

# ==============================================================================
# GDC Bootloader ISO Offline Packages Pre-seeding Utility
# ==============================================================================
# Resolves, downloads, and caches critical system dependencies (.deb files)
# completely offline. Synchronizes cached packages to the central GCS bucket
# to facilitate zero-network CI/CD compilation loops.
# ==============================================================================

set -euo pipefail

# Determine paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CACHE_DIR="${PROJECT_ROOT}/.cache/packages"

# Load build parameters
ENV_FILE="${SCRIPT_DIR}/build.env"
if [[ -f "${ENV_FILE}" ]]; then
    source "${ENV_FILE}"
fi

GCS_BUCKET="${GCS_BUCKET:-gs://gdc-disk-provisioner-isos}"
ENABLE_GCS="${ENABLE_GCS:-false}"
TEST_ONLY="${TEST_ONLY:-false}"

# Define the minimal set of dependencies to test and validate
# This limits GCS footprint and bandwidth during verification runs
TEST_PACKAGES=(
    "chrony"
    "socat"
    "net-tools"
    "arp-scan"
    "ansible"
    "git"
)

# Full production-grade offline dependency set
PROD_PACKAGES=(
    "conntrack"
    "ebtables"
    "ethtool"
    "iproute2"
    "iptables"
    "locales"
    "logrotate"
    "socat"
    "unzip"
    "chrony"
    "net-tools"
    "arp-scan"
    "libseccomp2"
    "auditd"
    "audispd-plugins"
    "ansible"
    "git"
)

# Choose package list based on execution profile
if [[ "${TEST_ONLY}" == "true" ]]; then
    echo "[-] Running in TEST mode. Restricting pre-seed download to minimal verification packages..."
    TARGET_PACKAGES=("${TEST_PACKAGES[@]}")
else
    echo "[-] Running in PRODUCTION mode. Pulling all baseline GDC system dependencies..."
    TARGET_PACKAGES=("${PROD_PACKAGES[@]}")
fi

echo "[-] Initializing package staging cache at: ${CACHE_DIR}"
mkdir -p "${CACHE_DIR}"
cd "${CACHE_DIR}"

# Update local package index to ensure correctNoble versions are resolved
echo "[-] Refreshing local APT package metadata index..."
sudo apt-get update -qq

# Download target packages recursively
echo "[-] Downloading package binaries (.debs)..."
for pkg in "${TARGET_PACKAGES[@]}"; do
    echo "  [-] Resolving and downloading: ${pkg}..."
    # Download the package itself
    apt-get download "${pkg}" 2>/dev/null || {
        echo "  [!] Warning: Failed to download ${pkg} via direct apt download. Trying dependency simulation..."
    }
    
    # Download dependencies recursively
    APT_DEPS=$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances "${pkg}" | grep "Depends:" | awk '{print $2}' | grep -v "<" | sort -u || true)
    if [[ -n "${APT_DEPS}" ]]; then
        for dep in ${APT_DEPS}; do
            # Skip packages that are already part of minimal/essential system configurations
            if [[ "${dep}" =~ ^(libc6|libgcc-s1|libstdc++6|zlib1g|dpkg|base-passwd|debianutils)$ ]]; then
                continue
            fi
            apt-get download "${dep}" 2>/dev/null || true
        done
    fi
done

# Synchronize downloaded debs back to the GCS Bucket if enabled
BUCKET_NAME=$(echo "${GCS_BUCKET}" | sed 's/^gs:\/\///')
if [[ "${ENABLE_GCS}" == "true" ]]; then
    if command -v gcloud &>/dev/null; then
        echo "[-] Uploading cached packages to GCS: gs://${BUCKET_NAME}/packages/ ..."
        gcloud storage cp *.deb "gs://${BUCKET_NAME}/packages/" --quiet
        echo "  [x] GCS package pre-seeding upload completed successfully."
    else
        echo "  [!] Warning: 'gcloud' CLI is missing. Skipping GCS cache sync."
    fi
fi

echo "=============================================================================="
echo "[+] Pre-seeding completed. Total packages cached: $(ls -1 *.deb 2>/dev/null | wc -l)"
echo "=============================================================================="
exit 0
