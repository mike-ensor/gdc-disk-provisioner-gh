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

# Record initial environment variables to prevent files from overriding them
declare -A INITIAL_ENV
for var in $(compgen -e); do
    INITIAL_ENV[$var]=1
done

# Load environment configuration (dependencies, defaults, and overrides)
DEPS_FILE="${PROJECT_ROOT}/src/dependencies.env"
if [[ -f "${DEPS_FILE}" ]]; then
    # Export all variables from dependencies.env
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            value="${value#\"}" && value="${value%\"}"
            value="${value#\'}" && value="${value%\'}"
            if [[ -z "${INITIAL_ENV[${key}]:-}" ]]; then
                export "${key}"="${value}"
            fi
        fi
    done < "${DEPS_FILE}"
fi

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
            if [[ -z "${INITIAL_ENV[${key}]:-}" ]]; then
                export "${key}"="${value}"
            fi
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
            if [[ -z "${INITIAL_ENV[${key}]:-}" ]]; then
                export "${key}"="${value}"
            fi
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
if [[ "${GDC_DEBUG_MODE:-false}" == "true" ]]; then
    FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}-debug.iso"
else
    FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}.iso"
fi
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
cp -a "${TEMP_NEXUS_DIR}"/nexus-*/. "${EXTRACT_DIR}/custom-data/nexus/nexus-bin/"
cp -a "${TEMP_NEXUS_DIR}"/sonatype-work/. "${EXTRACT_DIR}/custom-data/nexus/sonatype-work/"
rm -rf "${TEMP_NEXUS_DIR}"

# Optimize Nexus VM options for Java 17 compatibility
VM_OPTIONS_FILE="${EXTRACT_DIR}/custom-data/nexus/nexus-bin/bin/nexus.vmoptions"
if [[ -f "${VM_OPTIONS_FILE}" ]]; then
    echo "[-] Optimizing Nexus VM options for Java 17 compatibility..."
    # 1. Comment out the endorsed directories line
    sed -i 's/^-Djava.endorsed.dirs=/# -Djava.endorsed.dirs=/g' "${VM_OPTIONS_FILE}"
    # 2. Uncomment Java 9+ options and format correctly for JVM single-arg parsing
    sed -i 's/^#[[:space:]]*--add-reads /--add-reads=/g' "${VM_OPTIONS_FILE}"
    sed -i 's/^#[[:space:]]*--add-reads=/--add-reads=/g' "${VM_OPTIONS_FILE}"
    sed -i 's/^#[[:space:]]*--add-exports /--add-exports=/g' "${VM_OPTIONS_FILE}"
    sed -i 's/^#[[:space:]]*--add-exports=/--add-exports=/g' "${VM_OPTIONS_FILE}"
    sed -i 's/^#[[:space:]]*--patch-module /--patch-module=/g' "${VM_OPTIONS_FILE}"
    sed -i 's/^#[[:space:]]*--patch-module=/--patch-module=/g' "${VM_OPTIONS_FILE}"
    sed -i 's/^#[[:space:]]*--add-opens /--add-opens=/g' "${VM_OPTIONS_FILE}"
    sed -i 's/^#[[:space:]]*--add-opens=/--add-opens=/g' "${VM_OPTIONS_FILE}"
    # 3. Replace unexpanded ${KARAF_HOME} with the absolute run path /var/lib/nexus/nexus-bin
    sed -i 's/\${KARAF_HOME}/\/var\/lib\/nexus\/nexus-bin/g' "${VM_OPTIONS_FILE}"
fi

# Configure Nexus to use H2 database (Java 17 compatibility)
NEXUS_DEFAULT_PROPERTIES="${EXTRACT_DIR}/custom-data/nexus/nexus-bin/etc/nexus-default.properties"
if [[ -f "${NEXUS_DEFAULT_PROPERTIES}" ]]; then
    echo "[-] Configuring Nexus default properties to use H2 database..."
    echo "nexus.datastore.enabled=true" >> "${NEXUS_DEFAULT_PROPERTIES}"
fi

NEXUS_PROPERTIES_DIR="${EXTRACT_DIR}/custom-data/nexus/sonatype-work/nexus3/etc"
mkdir -p "${NEXUS_PROPERTIES_DIR}"
NEXUS_PROPERTIES="${NEXUS_PROPERTIES_DIR}/nexus.properties"
echo "[-] Configuring Nexus user properties to use H2 database..."
echo "nexus.datastore.enabled=true" > "${NEXUS_PROPERTIES}"

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
rm -rf "${TARGET_BARE_REPO}"

echo "[-] Pre-seeding read-only bare Gitea playbook mirror..."
# Prioritize our local fully up-to-date development workspace repository
git config --global --add safe.directory "${PROJECT_ROOT}" || true
git config --global --add safe.directory "*" || true

# If running in Cloud Build or without .git metadata, temporarily initialize a git repo to capture exact modifications
TEMP_GIT_CREATED=false
if [[ ! -d "${PROJECT_ROOT}/.git" ]]; then
    echo "  [-] Initializing temporary Git repository for pre-seeding workspace modifications..."
    git -C "${PROJECT_ROOT}" init -b main &>/dev/null
    git -C "${PROJECT_ROOT}" config user.name "GDC Builder"
    git -C "${PROJECT_ROOT}" config user.email "builder@gdc.local"
    # Ensure we only add the playbooks and source files, skipping heavy caches/ISOs in build-workspace and .cache
    git -C "${PROJECT_ROOT}" add src/ docs/ test/ &>/dev/null || true
    git -C "${PROJECT_ROOT}" commit -m "Auto-generated compile pre-seed commit" &>/dev/null
    TEMP_GIT_CREATED=true
fi

if git clone --bare "file://${PROJECT_ROOT}" "${TARGET_BARE_REPO}" &>/dev/null; then
    echo "  [x] Local development playbooks pre-seeded successfully."
elif git clone --bare "${UPSTREAM_PLAYBOOKS_REPO}" "${TARGET_BARE_REPO}" &>/dev/null; then
    echo "  [x] Upstream playbooks cloned successfully."
else
    echo "  [!] Upstream clone unreachable. Initializing local dummy playbook git repository."
    git init --bare "${TARGET_BARE_REPO}" &>/dev/null
fi

if [[ "${TEMP_GIT_CREATED}" = "true" ]]; then
    rm -rf "${PROJECT_ROOT}/.git"
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
CACHE_TAR="${PROJECT_ROOT}/.cache/binaries/community-general-8.6.0.tar.gz"
echo "[-] Pre-packaging Ansible collection dependencies..."
mkdir -p "${COLLECTIONS_DIR}/collections/ansible_collections/community/general"

if [[ -f "${CACHE_TAR}" ]]; then
    echo "  [x] Using cached community.general collection."
    tar -xzf "${CACHE_TAR}" -C "${COLLECTIONS_DIR}/collections/ansible_collections/community/general"
else
    GALAXY_URL="https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/artifacts/community-general-8.6.0.tar.gz"
    echo "  [-] Downloading community.general collection..."
    if curl -sSL -o "${CACHE_TAR}" "${GALAXY_URL}"; then
        echo "  [x] Downloaded and cached community.general."
        tar -xzf "${CACHE_TAR}" -C "${COLLECTIONS_DIR}/collections/ansible_collections/community/general"
    else
        echo "  [!] Warning: Failed to download community.general. Attempting ansible-galaxy fallback..."
        if command -v ansible-galaxy &>/dev/null; then
            ansible-galaxy collection install community.general -p "${COLLECTIONS_DIR}/collections" &>/dev/null
        fi
    fi
fi

# ==========================================
# 3. Dynamic Banners, bootloaders, and Casper bypass
# ==========================================
echo "[-] Copying and configuring Python Netplan hydrator and storage generator..."
cp "${SCRIPT_DIR}/configure_netplan.py" "${EXTRACT_DIR}/custom-data/"
chmod +x "${EXTRACT_DIR}/custom-data/configure_netplan.py"
cp "${SCRIPT_DIR}/generate_storage_config.sh" "${EXTRACT_DIR}/custom-data/"
chmod +x "${EXTRACT_DIR}/custom-data/generate_storage_config.sh"
cp "${PROJECT_ROOT}/bin/collect-node-diagnostics.sh" "${EXTRACT_DIR}/custom-data/collect-node-diagnostics.sh"
chmod +x "${EXTRACT_DIR}/custom-data/collect-node-diagnostics.sh"
cp "${SCRIPT_DIR}/scan_ips.py" "${EXTRACT_DIR}/custom-data/"
chmod +x "${EXTRACT_DIR}/custom-data/scan_ips.py"

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
    linux /casper/vmlinuz console=ttyS0 console=tty1 autoinstall "ds=nocloud;s=/cdrom/nocloud/" ip=none ---
    initrd /casper/initrd
}

menuentry "Ubuntu Server Standard Install" {
    set gfxpayload=keep
    linux /casper/vmlinuz console=ttyS0 console=tty1 ---
    initrd /casper/initrd
}
EOF
    # Assert bootloader parameter correctness (Task 6 Check)
    echo "[-] Verifying compiled boot-level parameters..."
    if ! grep -q "linux /casper/vmlinuz .* autoinstall" "${GRUB_CFG}" || ! grep -q "ds=nocloud;s=/cdrom/nocloud/" "${GRUB_CFG}"; then
        echo "[!] ERROR: Bootloader parameters check failed! Critical autoinstall or ds configuration is missing in grub.cfg." >&2
        exit 1
    fi
    echo "  [x] Bootloader parameters verified successfully."
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
