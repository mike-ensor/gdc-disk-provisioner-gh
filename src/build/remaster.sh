#!/usr/bin/env bash

# ==============================================================================
# GDC Bootloader ISO Remastering Engine
# ==============================================================================
# Automatically handles download, non-root extraction, injection of configs,
# bootloader modification, and compilation of the customized bootable ISO.
# Includes variable review and interactive approval before building.
# ==============================================================================

set -euo pipefail

# Determine script directory and move to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

# Load environment configuration (only load if not already set in the environment)
ENV_FILE="${SCRIPT_DIR}/build.env"
if [[ -f "${ENV_FILE}" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            # Strip quotes if present
            value="${value#\"}"
            value="${value%\"}"
            value="${value#\'}"
            value="${value%\'}"
            # Export only if not already set in active shell
            if [[ -z "${!key:-}" ]]; then
                export "${key}"="${value}"
            fi
        fi
    done < "${ENV_FILE}"
else
    echo "[!] Error: Configuration file build.env not found in ${SCRIPT_DIR}" >&2
    exit 1
fi

# ==============================================================================
# 0. Interactive Variables Review & Confirmation
# ==============================================================================
AUTO_APPROVE=false

# Parse command line flags
for arg in "$@"; do
    case $arg in
        -y|--y|--yes|--auto-approve)
            AUTO_APPROVE=true
            shift
            ;;
        *)
            # Ignore other flags for the baseline script
            ;;
    esac
done

# Output the variables block
echo "=============================================================================="
echo " GDC ISO REMASTERING ENGINE - CONFIGURATION REVIEW"
echo "=============================================================================="
echo "  [Base OS Settings]"
echo "  - Blessed ISO Source URL:  ${SOURCE_ISO_URL}"
echo "  - Blessed ISO Filename:    ${SOURCE_ISO_FILENAME}"
echo ""
echo "  [Output ISO Tags & Settings]"
echo "  - Custom Version Tag:      ${ISO_VERSION}"
echo "  - Custom Name Prefix:      ${ISO_NAME_PREFIX}"
echo ""
echo "  [Publication Destinations]"
echo "  - GCS Bucket Deploy:       ${ENABLE_GCS} (${GCS_BUCKET:-N/A})"
echo "  - Local NFS Deploy:        ${ENABLE_NFS} (${NFS_DEPLOY_PATH:-N/A})"
echo "=============================================================================="

# Ask for user confirmation in interactive shells
if [[ "${AUTO_APPROVE}" = "false" ]]; then
    if [[ -t 0 ]]; then
        read -rp "[-] Proceed with the GDC ISO compilation? [y/N]: " confirm
        case "${confirm}" in
            [yY][eE][sS]|[yY])
                echo "[-] Confirmation received. Starting build process..."
                ;;
            *)
                echo "[!] Build aborted by user."
                exit 0
                ;;
        esac
    else
        echo "[-] Non-interactive terminal detected and --auto-approve not set."
        echo "[-] Automatically proceeding with the build..."
    fi
else
    echo "[-] Unattended execution (--auto-approve active). Proceeding..."
fi

# ==============================================================================
# Paths and Workspace Definitions
# ==============================================================================
WORKSPACE="${PROJECT_ROOT}/build-workspace"
EXTRACT_DIR="${WORKSPACE}/custom-iso"
OUTPUT_DIR="${WORKSPACE}/output"

# Centralized Local Caching Structure (Scoped by item space)
CACHE_ROOT="${PROJECT_ROOT}/.cache"
ISO_CACHE_DIR="${CACHE_ROOT}/isos"
BIN_CACHE_DIR="${CACHE_ROOT}/binaries"
BLOB_CACHE_DIR="${CACHE_ROOT}/blobs"

# Output versioned filename
BUILD_DATE=$(date +%Y%m%d-%H%M%S)
FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}-${BUILD_DATE}.iso"
FINAL_ISO_PATH="${OUTPUT_DIR}/${FINAL_ISO_NAME}"

# Setup clean directories
mkdir -p "${ISO_CACHE_DIR}" "${BIN_CACHE_DIR}" "${BLOB_CACHE_DIR}" "${EXTRACT_DIR}" "${OUTPUT_DIR}"

# ==============================================================================
# Dependency Checking
# ==============================================================================
echo "[-] Verifying system dependencies..."
for cmd in xorriso curl rsync; do
    if ! command -v "${cmd}" &>/dev/null; then
        echo "[!] Critical Error: Required tool '${cmd}' is not installed." >&2
        exit 1
    fi
done
echo "[-] Dependency check passed."

# ==============================================================================
# 1. Download "Blessed" Source ISO
# ==============================================================================
SOURCE_ISO="${ISO_CACHE_DIR}/${SOURCE_ISO_FILENAME}"
if [[ ! -f "${SOURCE_ISO}" ]]; then
    echo "[-] Source ISO not found locally. Downloading from official provider..."
    echo "[-] URL: ${SOURCE_ISO_URL}"
    curl -L -o "${SOURCE_ISO}" "${SOURCE_ISO_URL}"
    echo "[-] Download complete."
else
    echo "[-] Found cached source ISO at ${SOURCE_ISO}"
fi

# ==============================================================================
# 2. Extract Source ISO (Non-root)
# ==============================================================================
echo "[-] Extracting original ISO to workspace..."
# Clean extraction workspace first
rm -rf "${EXTRACT_DIR}"
mkdir -p "${EXTRACT_DIR}"

# Extract ISO contents utilizing xorriso's osirrox layer (no root/mount required!)
xorriso -osirrox on -indev "${SOURCE_ISO}" -extract / "${EXTRACT_DIR}" &>/dev/null
chmod -R +w "${EXTRACT_DIR}"
echo "[-] ISO extracted successfully."

# ==============================================================================
# 3. Inject Autoinstall & Config Layers
# ==============================================================================
echo "[-] Injecting custom configurations and bootloader adjustments..."

# Create NoCloud directory
mkdir -p "${EXTRACT_DIR}/nocloud"

# A. Inject Minimal Metadata
cat <<EOF > "${EXTRACT_DIR}/nocloud/meta-data"
instance-id: gdc-bootstrap-node-$(date +%s)
local-hostname: gdc-standalone-node
EOF

# B. Inject Autoinstall user-data
# Note: For this pipeline specimen, we stub a clean autoinstall block that satisfies GDC parameters
cat <<'EOF' > "${EXTRACT_DIR}/nocloud/user-data"
#cloud-config
autoinstall:
  version: 1
  identity:
    hostname: gdc-node-bootstrap
    username: temporary-installer
    password: "$6$rounds=4096$rounds_salt$placeholder_hash"
  locale: en_US.UTF-8
  keyboard: {layout: us}
  network:
    network:
      version: 2
      ethernets:
        all-en:
          match:
            name: "e*"
          dhcp4: true
  storage:
    layout:
      name: direct
EOF

# C. Inject Custom Services Directory (Hub and Spoke structures)
mkdir -p "${EXTRACT_DIR}/custom-data/gitea"
mkdir -p "${EXTRACT_DIR}/custom-data/nexus"
mkdir -p "${EXTRACT_DIR}/custom-data/systemd"

# Create placeholder binaries to establish the files/directory structure
echo "#!/bin/bash" > "${EXTRACT_DIR}/custom-data/gitea/gitea"
echo "echo 'Gitea Placeholder'" >> "${EXTRACT_DIR}/custom-data/gitea/gitea"
chmod +x "${EXTRACT_DIR}/custom-data/gitea/gitea"

echo "#!/bin/bash" > "${EXTRACT_DIR}/custom-data/nexus/nexus"
echo "echo 'Nexus Placeholder'" >> "${EXTRACT_DIR}/custom-data/nexus/nexus"
chmod +x "${EXTRACT_DIR}/custom-data/nexus/nexus"

# Clone the upstream playbook repository as a read-only mirror (cloned at ISO creation time)
GITEA_REPOS_DIR="${EXTRACT_DIR}/custom-data/gitea/repos"
mkdir -p "${GITEA_REPOS_DIR}"
TARGET_BARE_REPO="${GITEA_REPOS_DIR}/bootstrap-playbooks.git"

echo "[-] Cloning upstream GDC playbooks repository at ISO creation time..."
echo "[-] Repository Source: ${UPSTREAM_PLAYBOOKS_REPO}"

# Create a bare mirror repository
# (We handle fallback to local dummy initialization if upstream clone fails during development)
if git clone --bare "${UPSTREAM_PLAYBOOKS_REPO}" "${TARGET_BARE_REPO}" &>/dev/null; then
    echo "[-] Upstream repository cloned successfully."
else
    echo "[!] Warning: Could not clone upstream repository ${UPSTREAM_PLAYBOOKS_REPO}. Creating local dummy repository for build development."
    git init --bare "${TARGET_BARE_REPO}" &>/dev/null
fi

# Configure Gitea's Git repository to be read-only (pull-only from upstream, no pushing)
# We enforce this by disabling push actions via a local pre-receive hook
mkdir -p "${TARGET_BARE_REPO}/hooks"
cat <<'EOF' > "${TARGET_BARE_REPO}/hooks/pre-receive"
#!/usr/bin/env bash
echo "[-] [GGD SECURITY ERROR] Direct pushing to Gitea's local bootstrap repository is strictly forbidden." >&2
echo "[-] This repository is READ-ONLY. It can only pull updates from the upstream origin." >&2
exit 1
EOF
chmod +x "${TARGET_BARE_REPO}/hooks/pre-receive"
echo "[-] Gitea read-only bare mirror repository pre-seeded successfully."

# ==============================================================================
# 4. Modify GRUB Boot Options
# ==============================================================================
GRUB_CFG="${EXTRACT_DIR}/boot/grub/grub.cfg"

if [[ -f "${GRUB_CFG}" ]]; then
    echo "[-] Overwriting GRUB config to enforce offline unattended autoinstall..."
    
    # Overwrite the grub config with our customized defaults
    cat <<'EOF' > "${GRUB_CFG}"
set timeout=5
set default=0

menuentry "Google Distributed Cloud (GDC) Automated Bootstrap" {
    set gfxpayload=keep
    linux /casper/vmlinuz quiet autoinstall ds=nocloud;s=/cdrom/nocloud/ ip=dhcp ---
    initrd /casper/initrd
}

menuentry "Ubuntu Server Standard Install" {
    set gfxpayload=keep
    linux /casper/vmlinuz quiet ---
    initrd /casper/initrd
}
EOF
else
    echo "[!] Warning: boot/grub/grub.cfg not found in extracted ISO. Skipping bootloader patch."
fi

# ==============================================================================
# 5. Compile & Repack Bootable ISO (using xorriso)
# ==============================================================================
echo "[-] Compiling bootable custom GDC ISO..."

# ==============================================================================
# 5. Compile & Repack Bootable ISO (using xorriso)
# ==============================================================================
echo "[-] Extracting embedded EFI system partition from original ISO dynamically..."
PART_INFO=$(xorriso -indev "${SOURCE_ISO}" -report_el_torito as_mkisofs 2>/dev/null | grep "\-append_partition 2")

if [[ -n "${PART_INFO}" ]]; then
    INTERVAL=$(echo "${PART_INFO}" | grep -o -E "[0-9]+d-[0-9]+d")
    START_SECTOR=$(echo "${INTERVAL}" | cut -d'-' -f1 | tr -d 'd')
    END_SECTOR=$(echo "${INTERVAL}" | cut -d'-' -f2 | tr -d 'd')
    COUNT=$((END_SECTOR - START_SECTOR + 1))
    
    echo "[-] Found EFI partition sectors: ${START_SECTOR} to ${END_SECTOR} (Count: ${COUNT})"
    mkdir -p "$(dirname "${EXTRACT_DIR}/boot/grub/efi.img")"
    dd if="${SOURCE_ISO}" of="${EXTRACT_DIR}/boot/grub/efi.img" bs=512 skip="${START_SECTOR}" count="${COUNT}" status=none
    echo "[-] EFI system partition extracted successfully."
else
    echo "[!] Warning: No appended EFI partition found in original ISO. Attempting fallback..."
fi

echo "[-] Compiling bootable custom GDC ISO..."

# Ubuntu 24.04 live ISO uses standard grub-efi booting
# We compile back referencing the extracted grub-boot records
XORRISO_LOG=$(mktemp)
if ! xorriso -as mkisofs -r -V "GDC-BOOTSTRAP" \
  -J -b boot/grub/i386-pc/eltorito.img -c boot.catalog \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -eltorito-alt-boot -e boot/grub/efi.img -no-emul-boot \
  -isohybrid-gpt-basdat \
  -o "${FINAL_ISO_PATH}" \
  "${EXTRACT_DIR}" >"${XORRISO_LOG}" 2>&1; then
    echo "[!] Error: xorriso compilation failed!" >&2
    cat "${XORRISO_LOG}" >&2
    rm -f "${XORRISO_LOG}"
    exit 5
fi
rm -f "${XORRISO_LOG}"

echo "[-] ISO generated successfully!"
echo "[-] Location: ${FINAL_ISO_PATH}"
echo "[-] Size: $(du -sh "${FINAL_ISO_PATH}" | cut -f1)"

# Export the generated ISO path for Makefile integration
echo "ISO_OUTPUT_PATH=${FINAL_ISO_PATH}" > "${WORKSPACE}/build_meta.env"
echo "ISO_OUTPUT_NAME=${FINAL_ISO_NAME}" >> "${WORKSPACE}/build_meta.env"
