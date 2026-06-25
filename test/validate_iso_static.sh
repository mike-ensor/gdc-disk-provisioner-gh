#!/usr/bin/env bash

# ==============================================================================
# GDC ISO Tier 1 Static Structural Validator
# ==============================================================================
# Inspects compiled ISO filesystems, extracts configs, and checks schemas
# entirely without root mounts or system VM overhead.
# ==============================================================================

set -euo pipefail

# Determine paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE="${PROJECT_ROOT}/build-workspace"
OUTPUT_DIR="${WORKSPACE}/output"

echo "=============================================================================="
echo "GDC Bootloader ISO Static Validation Suite (Tier 1)"
echo "=============================================================================="

# 1. Locate generated ISO
BUILD_META="${WORKSPACE}/build_meta.env"
if [[ -f "${BUILD_META}" ]]; then
    # shellcheck source=/dev/null
    source "${BUILD_META}"
    ISO_PATH="${ISO_OUTPUT_PATH}"
else
    # Fallback search if no meta exists
    ISO_PATH=$(find "${OUTPUT_DIR}" -name "*.iso" -type f | head -n 1)
fi

if [[ -z "${ISO_PATH}" || ! -f "${ISO_PATH}" ]]; then
    echo "[!] Error: No compiled ISO file found. Run 'make -C src/build build' first." >&2
    exit 1
fi

echo "[-] Target ISO: ${ISO_PATH}"
echo "[-] Size: $(du -sh "${ISO_PATH}" | cut -f1)"

# 2. Dependency Checking
echo "[-] Checking static validation requirements..."
if ! command -v xorriso &>/dev/null; then
    echo "[!] Error: 'xorriso' is required but not installed." >&2
    exit 1
fi

# 2.5. Verify Host Cached Binaries Integrity (CI/CD Assertions)
echo "[-] Verifying local cached binaries on host..."
# Source dependencies file first to load binary names and hashes
DEPS_ENV="${PROJECT_ROOT}/src/dependencies.env"
if [[ -f "${DEPS_ENV}" ]]; then
    # shellcheck source=/dev/null
    source "${DEPS_ENV}"
fi

# Source the build.env file to load standard variables
BUILD_ENV="${PROJECT_ROOT}/src/build/build.env"
if [[ -f "${BUILD_ENV}" ]]; then
    # shellcheck source=/dev/null
    source "${BUILD_ENV}"
else
    echo "[!] Error: build.env not found at ${BUILD_ENV}" >&2
    exit 1
fi

CACHE_DIR="${PROJECT_ROOT}/.cache/binaries"

verify_host_cache() {
    local filename="$1"
    local expected_sha="$2"
    local file_path="${CACHE_DIR}/${filename}"

    if [[ ! -f "${file_path}" ]]; then
        echo "[ ] CACHED BINARY MISSING ON HOST: ${filename} (Path: ${file_path})" >&2
        return 1
    fi

    local actual_sha
    actual_sha=$(sha256sum "${file_path}" | cut -d' ' -f1)
    if [[ "${actual_sha}" != "${expected_sha}" ]]; then
        echo "[ ] CRYPTOGRAPHIC HASH MISMATCH ON HOST: ${filename}!" >&2
        echo "    Expected: ${expected_sha}" >&2
        echo "    Actual:   ${actual_sha}" >&2
        return 1
    fi
    echo "[x] Verified host cached binary: ${filename} (Cryptographically valid)"
    return 0
}

HOST_CACHE_SUCCESS=true
verify_host_cache "${GITEA_BINARY_FILENAME}" "${GITEA_BINARY_SHA256}" || HOST_CACHE_SUCCESS=false
verify_host_cache "${NEXUS_PACKAGE_FILENAME}" "${NEXUS_PACKAGE_SHA256}" || HOST_CACHE_SUCCESS=false
verify_host_cache "${JRE_PACKAGE_FILENAME}" "${JRE_PACKAGE_SHA256}" || HOST_CACHE_SUCCESS=false

if [[ "${HOST_CACHE_SUCCESS}" = "false" ]]; then
    echo "[!] Error: Host cached binaries validation failed. Ensure 'make -C src/build build' has run." >&2
    exit 1
fi

# 3. File Inventory Checks (via xorriso non-root find)
echo "[-] Scanning ISO structural layout..."
CRITICAL_FILES=(
    "/nocloud/user-data"
    "/nocloud/meta-data"
    "/custom-data/gitea/gitea"
    "/custom-data/nexus/nexus-bin/bin/nexus"
    "/boot/grub/grub.cfg"
)

FAILED_CHECKS=0
for target_file in "${CRITICAL_FILES[@]}"; do
    # Run xorriso find query to assert existence
    if xorriso -indev "${ISO_PATH}" -find "${target_file}" &>/dev/null; then
        echo "[x] Found critical path: ${target_file}"
    else
        echo "[ ] CRITICAL PATH MISSING: ${target_file}" >&2
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
    fi
done

if [[ ${FAILED_CHECKS} -gt 0 ]]; then
    echo "[!] Error: File inventory check failed. ISO is missing structural paths." >&2
    exit 1
fi
echo "[-] Layout verification completed successfully."

# 4. Extract & Validate cloud-init User-Data Schema
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "${TEMP_DIR}"' EXIT

echo "[-] Extracting cloud-init config block..."
xorriso -osirrox on -indev "${ISO_PATH}" -extract /nocloud/user-data "${TEMP_DIR}/user-data" &>/dev/null

if [[ ! -f "${TEMP_DIR}/user-data" ]]; then
    echo "[!] Error: Failed to extract cloud-init user-data from ISO." >&2
    exit 1
fi

echo "[-] Validating cloud-init schema..."
if command -v cloud-init &>/dev/null; then
    if cloud-init schema --config-file "${TEMP_DIR}/user-data" &>/dev/null; then
        echo "[x] cloud-init schema checks passed."
    else
        echo "[!] CRITICAL ERROR: Autoinstall config contains syntax errors!" >&2
        cloud-init schema --config-file "${TEMP_DIR}/user-data" || true
        exit 1
    fi
else
    echo "[!] Warning: 'cloud-init' utility is not installed locally."
    echo "[!] Mock-validating YAML syntax of autoinstall configurations instead..."
    if command -v python3 &>/dev/null; then
        python3 -c "import yaml; yaml.safe_load(open('${TEMP_DIR}/user-data'))"
        echo "[x] YAML configuration syntax checks passed (Mock schema success)."
    else
        echo "[!] Warning: No YAML checkers available. Skipping syntax assertion."
    fi
fi

echo "=============================================================================="
echo "[+] SUCCESS: ISO passes all Tier 1 structural validation checks!"
echo "=============================================================================="
exit 0
