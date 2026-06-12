#!/usr/bin/env bash

# ==============================================================================
# GDC Bootloader ISO Remastering Engine
# ==============================================================================
# Automatically handles download, non-root extraction, injection of configs,
# bootloader modification, and compilation of the customized bootable ISO.
# ==============================================================================

set -euo pipefail

# Determine script directory and move to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

# Load environment configuration
ENV_FILE="${SCRIPT_DIR}/build.env"
if [[ -f "${ENV_FILE}" ]]; then
    echo "[-] Loading build configuration from ${ENV_FILE}"
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
else
    echo "[!] Error: Configuration file build.env not found in ${SCRIPT_DIR}" >&2
    exit 1
fi

# ==============================================================================
# Paths and Workspace Definitions
# ==============================================================================
WORKSPACE="${PROJECT_ROOT}/build-workspace"
CACHE_DIR="${WORKSPACE}/cache"
EXTRACT_DIR="${WORKSPACE}/custom-iso"
OUTPUT_DIR="${WORKSPACE}/output"

# Output versioned filename
BUILD_DATE=$(date +%Y%m%d-%H%M%S)
FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}-${BUILD_DATE}.iso"
FINAL_ISO_PATH="${OUTPUT_DIR}/${FINAL_ISO_NAME}"

# Setup clean directories
mkdir -p "${CACHE_DIR}" "${EXTRACT_DIR}" "${OUTPUT_DIR}"

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
SOURCE_ISO="${CACHE_DIR}/${SOURCE_ISO_FILENAME}"
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

# Ubuntu 24.04 live ISO uses standard grub-efi booting
# We compile back referencing the extracted grub-boot records
xorriso -as mkisofs -r -V "GDC-BOOTSTRAP" \
  -J -b boot/grub/efi.img -c boot.catalog \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -elt-torito-alt-boot -e boot/grub/efi.img -no-emul-boot \
  -isohybrid-gpt-basdat \
  -o "${FINAL_ISO_PATH}" \
  "${EXTRACT_DIR}" &>/dev/null

echo "[-] ISO generated successfully!"
echo "[-] Location: ${FINAL_ISO_PATH}"
echo "[-] Size: $(du -sh "${FINAL_ISO_PATH}" | cut -f1)"

# Export the generated ISO path for Makefile integration
echo "ISO_OUTPUT_PATH=${FINAL_ISO_PATH}" > "${WORKSPACE}/build_meta.env"
echo "ISO_OUTPUT_NAME=${FINAL_ISO_NAME}" >> "${WORKSPACE}/build_meta.env"
