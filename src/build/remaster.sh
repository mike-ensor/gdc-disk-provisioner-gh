#!/usr/bin/env bash

# ==============================================================================
# GDC Bootloader ISO Remastering Engine (Stage-Gate Assembly)
# ==============================================================================
# Orchestrates Stage 3: Assemble-Artifact. Packages configurations,
# pre-seeds playbooks, injects pre-cached binaries, and compiles the bootable ISO.
# ==============================================================================

set -euo pipefail

# Determine script directory and move to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

# Load environment configuration (defaults and overrides)
ENV_FILE="${SCRIPT_DIR}/build.env"
if [[ -f "${ENV_FILE}" ]]; then
    # Export all variables from build.env
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            value="${value#\"}" && value="${value%\"}"
            value="${value#\'}" && value="${value%\'}"
            export "${key}"="${value}"
        fi
    done < "${ENV_FILE}"
fi

LOCAL_ENV_FILE="${SCRIPT_DIR}/local.env"
if [[ -f "${LOCAL_ENV_FILE}" ]]; then
    # Export overrides from local.env
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            value="${value#\"}" && value="${value%\"}"
            value="${value#\'}" && value="${value%\'}"
            export "${key}"="${value}"
        fi
    done < "${LOCAL_ENV_FILE}"
fi

AUTO_APPROVE=false
for arg in "$@"; do
    case $arg in
        -y|--y|--yes|--auto-approve)
            AUTO_APPROVE=true
            shift
            ;;
    esac
done

# Non-interactive confirmation checks
if [[ "${AUTO_APPROVE}" = "false" && -t 0 ]]; then
    read -rp "[-] Proceed with the GDC ISO compilation? [y/N]: " confirm
    case "${confirm}" in
        [yY][eE][sS]|[yY])
            echo "[-] Starting build process..."
            ;;
        *)
            echo "[!] Build aborted by user."
            exit 0
            ;;
    esac
fi

# Paths and Workspace Definitions
WORKSPACE="${PROJECT_ROOT}/build-workspace"
EXTRACT_DIR="${WORKSPACE}/custom-iso"
OUTPUT_DIR="${WORKSPACE}/output"
BIN_CACHE_DIR="${PROJECT_ROOT}/.cache/binaries"

# Output versioned filename
FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}.iso"
FINAL_ISO_PATH="${OUTPUT_DIR}/${FINAL_ISO_NAME}"

echo "=============================================================================="
echo "GDC ISO REMASTERING ASSEMBLY - COMPILING RELEASE CANDIDATE"
echo "=============================================================================="
echo "  - Output Name: ${FINAL_ISO_NAME}"
echo "  - Version:     ${ISO_VERSION}"
echo "=============================================================================="

# Ensure directories exist
mkdir -p "${EXTRACT_DIR}/custom-data/gitea"
mkdir -p "${EXTRACT_DIR}/custom-data/nexus"
mkdir -p "${EXTRACT_DIR}/custom-data/systemd"
mkdir -p "${EXTRACT_DIR}/custom-data/ansible/collections"
mkdir -p "${OUTPUT_DIR}"

# ==========================================
# 1. Install Pre-Cached Binaries
# ==========================================
echo "[-] Installing pre-verified standalone Gitea binary..."
cp "${BIN_CACHE_DIR}/${GITEA_BINARY_FILENAME}" "${EXTRACT_DIR}/custom-data/gitea/gitea"
chmod +x "${EXTRACT_DIR}/custom-data/gitea/gitea"

echo "[-] Extracting Java JRE 17 headless runtime..."
rm -rf "${EXTRACT_DIR}/custom-data/nexus/jre"
mkdir -p "${EXTRACT_DIR}/custom-data/nexus/jre"
TEMP_JRE_DIR=$(mktemp -d)
tar -xzf "${BIN_CACHE_DIR}/${JRE_PACKAGE_FILENAME}" -C "${TEMP_JRE_DIR}"
cp -r "${TEMP_JRE_DIR}"/*/* "${EXTRACT_DIR}/custom-data/nexus/jre/"
rm -rf "${TEMP_JRE_DIR}"

echo "[-] Extracting Sonatype Nexus Distribution..."
rm -rf "${EXTRACT_DIR}/custom-data/nexus/nexus-bin"
rm -rf "${EXTRACT_DIR}/custom-data/nexus/sonatype-work"
mkdir -p "${EXTRACT_DIR}/custom-data/nexus/nexus-bin"
mkdir -p "${EXTRACT_DIR}/custom-data/nexus/sonatype-work"
TEMP_NEXUS_DIR=$(mktemp -d)
tar -xzf "${BIN_CACHE_DIR}/${NEXUS_PACKAGE_FILENAME}" -C "${TEMP_NEXUS_DIR}"
cp -r "${TEMP_NEXUS_DIR}"/nexus-*/* "${EXTRACT_DIR}/custom-data/nexus/nexus-bin/"
cp -r "${TEMP_NEXUS_DIR}"/sonatype-work/* "${EXTRACT_DIR}/custom-data/nexus/sonatype-work/"
rm -rf "${TEMP_NEXUS_DIR}"

echo "[-] Writing local JVM environment config for Sonatype Nexus..."
cat <<'EOF' > "${EXTRACT_DIR}/custom-data/nexus/nexus-bin/bin/nexus.rc"
run_as_user="root"
INSTALL4J_JAVA_HOME_OVERRIDE="/var/lib/nexus/jre"
EOF

# ==========================================
# 2. Pre-Seed Ansible & Playbook Repositories
# ==========================================
GITEA_REPOS_DIR="${EXTRACT_DIR}/custom-data/gitea/repos/gdc"
mkdir -p "${GITEA_REPOS_DIR}"
TARGET_BARE_REPO="${GITEA_REPOS_DIR}/bootstrap-playbooks.git"

echo "[-] Pre-seeding read-only bare Gitea playbook mirror..."
if git clone --bare "${UPSTREAM_PLAYBOOKS_REPO}" "${TARGET_BARE_REPO}" &>/dev/null; then
    echo "  [x] Upstream playbooks cloned successfully."
else
    echo "  [!] Upstream clone unreachable. Initializing local dummy playbook git repository."
    git init --bare "${TARGET_BARE_REPO}" &>/dev/null
fi

# Set Git pre-receive blocking hook for Read-Only assurance
mkdir -p "${TARGET_BARE_REPO}/hooks"
cat <<'EOF' > "${TARGET_BARE_REPO}/hooks/pre-receive"
#!/usr/bin/env bash
echo "[!] [GGD SECURITY ERROR] Direct pushing to Gitea's local bootstrap repository is strictly forbidden." >&2
echo "[-] This repository is READ-ONLY. It can only pull updates from the upstream origin." >&2
exit 1
EOF
chmod +x "${TARGET_BARE_REPO}/hooks/pre-receive"

# Package offline Ansible collections
COLLECTIONS_DIR="${EXTRACT_DIR}/custom-data/ansible"
echo "[-] Pre-packaging Ansible collection dependencies..."
if command -v ansible-galaxy &>/dev/null; then
    ansible-galaxy collection install community.general -p "${COLLECTIONS_DIR}/collections" &>/dev/null
else
    # Fallback direct download
    GALAXY_URL="https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/artifacts/community-general-8.6.0.tar.gz"
    TEMP_TAR="/tmp/community-general.tar.gz"
    mkdir -p "${COLLECTIONS_DIR}/collections/ansible_collections/community/general"
    if curl -sSL -o "${TEMP_TAR}" "${GALAXY_URL}"; then
        tar -xzf "${TEMP_TAR}" -C "${COLLECTIONS_DIR}/collections/ansible_collections/community/general"
        rm -f "${TEMP_TAR}"
    fi
fi

# ==========================================
# 3. Dynamic Banners, bootloaders, and Casper bypass
# ==========================================
echo "[-] Generating dynamic Message of the Day (MOTD) banner..."
"${SCRIPT_DIR}/generate_banner.py" "${EXTRACT_DIR}/custom-data/boot-banner.txt" "${ISO_VERSION}"

# Patch GRUB boot loader config
GRUB_CFG="${EXTRACT_DIR}/boot/grub/grub.cfg"
if [[ -f "${GRUB_CFG}" ]]; then
    echo "[-] Overwriting GRUB configuration to enforce unattended bootstrap..."
    cat <<'EOF' > "${GRUB_CFG}"
set timeout=5
set default=0

menuentry "Google Distributed Cloud (GDC) Automated Bootstrap" {
    set gfxpayload=keep
    linux /casper/vmlinuz quiet autoinstall "ds=nocloud;s=/cdrom/nocloud/" ip=none ---
    initrd /casper/initrd
}

menuentry "Ubuntu Server Standard Install" {
    set gfxpayload=keep
    linux /casper/vmlinuz quiet ---
    initrd /casper/initrd
}
EOF
fi

# Bypass Casper verification check to avoid drop-to-shells
if [[ -f "${EXTRACT_DIR}/md5sum.txt" ]]; then
    echo "[-] Removing md5sum.txt to bypass Casper media integrity checks..."
    rm -f "${EXTRACT_DIR}/md5sum.txt"
fi

# ==========================================
# 4. Compile and Repack Bootable ISO (using xorriso)
# ==========================================
echo "[-] Extracting system EFI partition dynamically..."
PART_INFO=$(xorriso -indev "${SOURCE_ISO_URL}" -report_el_torito as_mkisofs 2>/dev/null | grep "\-append_partition 2" || true)

if [[ -n "${PART_INFO}" ]]; then
    INTERVAL=$(echo "${PART_INFO}" | grep -o -E "[0-9]+d-[0-9]+d")
    START_SECTOR=$(echo "${INTERVAL}" | cut -d'-' -f1 | tr -d 'd')
    END_SECTOR=$(echo "${INTERVAL}" | cut -d'-' -f2 | tr -d 'd')
    COUNT=$((END_SECTOR - START_SECTOR + 1))
    
    mkdir -p "$(dirname "${EXTRACT_DIR}/boot/grub/efi.img")"
    dd if="${SOURCE_ISO_URL}" of="${EXTRACT_DIR}/boot/grub/efi.img" bs=512 skip="${START_SECTOR}" count="${COUNT}" status=none
    echo "  [x] Extracted system EFI boot segment."
else
    # Local fallback search
    ISO_CACHE_FILE="${PROJECT_ROOT}/.cache/isos/${SOURCE_ISO_FILENAME}"
    if [[ -f "${ISO_CACHE_FILE}" ]]; then
        PART_INFO=$(xorriso -indev "${ISO_CACHE_FILE}" -report_el_torito as_mkisofs 2>/dev/null | grep "\-append_partition 2" || true)
        if [[ -n "${PART_INFO}" ]]; then
            INTERVAL=$(echo "${PART_INFO}" | grep -o -E "[0-9]+d-[0-9]+d")
            START_SECTOR=$(echo "${INTERVAL}" | cut -d'-' -f1 | tr -d 'd')
            END_SECTOR=$(echo "${INTERVAL}" | cut -d'-' -f2 | tr -d 'd')
            COUNT=$((END_SECTOR - START_SECTOR + 1))
            mkdir -p "$(dirname "${EXTRACT_DIR}/boot/grub/efi.img")"
            dd if="${ISO_CACHE_FILE}" of="${EXTRACT_DIR}/boot/grub/efi.img" bs=512 skip="${START_SECTOR}" count="${COUNT}" status=none
            echo "  [x] Extracted system EFI boot segment from cache."
        fi
    fi
fi

echo "[-] Packaging ISO workspace via xorriso..."
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
    exit 1
fi
rm -f "${XORRISO_LOG}"

echo "[+] ISO compilation successfully compiled!"
echo "[+] Size: $(du -sh "${FINAL_ISO_PATH}" | cut -f1)"

# Generate variables manifest metadata for the build stages
echo "ISO_OUTPUT_PATH=${FINAL_ISO_PATH}" > "${WORKSPACE}/build_meta.env"
echo "ISO_OUTPUT_NAME=${FINAL_ISO_NAME}" >> "${WORKSPACE}/build_meta.env"

echo "=============================================================================="
exit 0
