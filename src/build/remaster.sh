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

# Consolidated function to load key-value configurations safely
load_env_file() {
    local filepath="$1"
    if [[ -f "${filepath}" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue
            if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                local key="${BASH_REMATCH[1]}"
                local value="${BASH_REMATCH[2]}"
                value="${value#\"}" && value="${value%\"}"
                value="${value#\'}" && value="${value%\'}"
                if [[ -z "${INITIAL_ENV[${key}]:-}" ]]; then
                    export "${key}"="${value}"
                fi
            fi
        done < "${filepath}"
    fi
}

# Load environment configuration (dependencies, defaults, and overrides)
load_env_file "${PROJECT_ROOT}/src/dependencies.env"
load_env_file "${SCRIPT_DIR}/build.env"

ISO_ENVIRONMENT="${ISO_ENVIRONMENT:-local}"
load_env_file "${SCRIPT_DIR}/${ISO_ENVIRONMENT}.env"

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
COMPANION_SUFFIX=""
if [[ "${GDC_COMPANION:-TRUE}" =~ ^([fF][aA][lL][sS][eE]|0|[nN][oO])$ ]]; then
    COMPANION_SUFFIX="-no-comp"
fi

if [[ "${GDC_DEBUG_MODE:-false}" == "true" ]]; then
    FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}${COMPANION_SUFFIX}-debug.iso"
else
    FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}${COMPANION_SUFFIX}.iso"
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
mkdir -p "${EXTRACT_DIR}/custom-data/tools"
mkdir -p "${EXTRACT_DIR}/custom-data/packages"
mkdir -p "${EXTRACT_DIR}/custom-data/security"
mkdir -p "${OUTPUT_DIR}"

# ==========================================
# 1. Install Pre-Cached Binaries
# ==========================================
echo "[-] Installing pre-verified standalone Gitea binary..."
cp "${BIN_CACHE_DIR}/${GITEA_BINARY_FILENAME}" "${EXTRACT_DIR}/custom-data/gitea/gitea"
chmod +x "${EXTRACT_DIR}/custom-data/gitea/gitea"

echo "[-] Copying pre-verified Google Cloud SDK tarball..."
cp "${BIN_CACHE_DIR}/${GCLOUD_SDK_FILENAME}" "${EXTRACT_DIR}/custom-data/tools/google-cloud-cli-linux-x86_64.tar.gz"

echo "[-] Staging CIS Hardening and Assessment Archive..."
if [[ -f "${BIN_CACHE_DIR}/${CIS_TARBALL_FILENAME}" ]]; then
    cp "${BIN_CACHE_DIR}/${CIS_TARBALL_FILENAME}" "${EXTRACT_DIR}/custom-data/security/${CIS_TARBALL_FILENAME}"
else
    echo "  [!] ERROR: CIS tarball not found in cache! Ensure it is synced from GCS first." >&2
    exit 1
fi

echo "[-] Fetching bmctl and nodeagentd version ${BOOTSTRAP_BMCTL_VERSION}..."
mkdir -p "${EXTRACT_DIR}/custom-data/tools/bmctl"
mkdir -p "${EXTRACT_DIR}/custom-data/tools/node-agent"
if [[ -f "${BIN_CACHE_DIR}/bmctl" ]]; then
    echo "  [x] Using cached bmctl binary."
    cp "${BIN_CACHE_DIR}/bmctl" "${EXTRACT_DIR}/custom-data/tools/bmctl/bmctl"
elif ! gcloud storage cp "gs://anthos-baremetal-release/bmctl/${BOOTSTRAP_BMCTL_VERSION}/linux-amd64/bmctl" "${EXTRACT_DIR}/custom-data/tools/bmctl/bmctl" --project="${PROJECT_ID}"; then
    echo "[!] Failed to download bmctl from GCS. Attempting public HTTPS fallback..."
    curl -L "https://storage.googleapis.com/anthos-baremetal-release/bmctl/${BOOTSTRAP_BMCTL_VERSION}/linux-amd64/bmctl" -o "${EXTRACT_DIR}/custom-data/tools/bmctl/bmctl"
fi
if [[ -f "${BIN_CACHE_DIR}/nodeagentd" ]]; then
    echo "  [x] Using cached nodeagentd binary."
    cp "${BIN_CACHE_DIR}/nodeagentd" "${EXTRACT_DIR}/custom-data/tools/node-agent/nodeagentd"
elif ! gcloud storage cp "gs://anthos-baremetal-release/bmctl/${BOOTSTRAP_BMCTL_VERSION}/linux-amd64/nodeagentd" "${EXTRACT_DIR}/custom-data/tools/node-agent/nodeagentd" --project="${PROJECT_ID}"; then
    echo "[!] Failed to download nodeagentd from GCS. Attempting public HTTPS fallback..."
    curl -L "https://storage.googleapis.com/anthos-baremetal-release/bmctl/${BOOTSTRAP_BMCTL_VERSION}/linux-amd64/nodeagentd" -o "${EXTRACT_DIR}/custom-data/tools/node-agent/nodeagentd"
fi
chmod +x "${EXTRACT_DIR}/custom-data/tools/bmctl/bmctl"
chmod +x "${EXTRACT_DIR}/custom-data/tools/node-agent/nodeagentd"

echo "[-] Copying authentication utilities (always included)..."
mkdir -p "${EXTRACT_DIR}/custom-data/auth"
if [[ -f "${PROJECT_ROOT}/bin/auth/gcp-authentication.sh" ]]; then
    cp "${PROJECT_ROOT}/bin/auth/gcp-authentication.sh" "${EXTRACT_DIR}/custom-data/auth/gcp-authentication.sh"
    chmod +x "${EXTRACT_DIR}/custom-data/auth/gcp-authentication.sh"
fi

if [ "${GDC_DEBUG_MODE}" = "true" ]; then
    echo "[-] Copying cluster operation scripts (DEBUG mode enabled)..."
    mkdir -p "${EXTRACT_DIR}/custom-data/cluster"
    if [[ -f "${PROJECT_ROOT}/bin/cluster/create_cluster.sh" ]]; then
        cp "${PROJECT_ROOT}/bin/cluster/create_cluster.sh" "${EXTRACT_DIR}/custom-data/cluster/create_cluster.sh"
        chmod +x "${EXTRACT_DIR}/custom-data/cluster/create_cluster.sh"
    fi
    if [[ -f "${PROJECT_ROOT}/bin/cluster/verify-upgrade-readiness.sh" ]]; then
        cp "${PROJECT_ROOT}/bin/cluster/verify-upgrade-readiness.sh" "${EXTRACT_DIR}/custom-data/cluster/verify-upgrade-readiness.sh"
        chmod +x "${EXTRACT_DIR}/custom-data/cluster/verify-upgrade-readiness.sh"
    fi
fi

echo "[-] Copying pre-verified Smallstep CLI package..."
cp "${BIN_CACHE_DIR}/${STEP_CLI_FILENAME}" "${EXTRACT_DIR}/custom-data/packages/"

echo "[-] Extracting and staging Helm CLI binary..."
mkdir -p "${EXTRACT_DIR}/custom-data/tools/helm"
if [[ -f "${BIN_CACHE_DIR}/${HELM_PACKAGE_FILENAME}" ]]; then
    TEMP_HELM_DIR=$(mktemp -d)
    tar -xzf "${BIN_CACHE_DIR}/${HELM_PACKAGE_FILENAME}" -C "${TEMP_HELM_DIR}"
    cp "${TEMP_HELM_DIR}/linux-amd64/helm" "${EXTRACT_DIR}/custom-data/tools/helm/helm"
    chmod +x "${EXTRACT_DIR}/custom-data/tools/helm/helm"
    rm -rf "${TEMP_HELM_DIR}"
    echo "  [x] Helm CLI staged successfully at /custom-data/tools/helm/helm."
else
    echo "  [!] WARNING: Helm package not found in cache! Run 'make deps' first." >&2
fi

echo "[-] Extracting and staging Kubestr CLI binary..."
mkdir -p "${EXTRACT_DIR}/custom-data/tools/kubestr"
if [[ -f "${BIN_CACHE_DIR}/${KUBESTR_PACKAGE_FILENAME}" ]]; then
    TEMP_KUBESTR_DIR=$(mktemp -d)
    tar -xzf "${BIN_CACHE_DIR}/${KUBESTR_PACKAGE_FILENAME}" -C "${TEMP_KUBESTR_DIR}"
    cp "${TEMP_KUBESTR_DIR}/kubestr" "${EXTRACT_DIR}/custom-data/tools/kubestr/kubestr"
    chmod +x "${EXTRACT_DIR}/custom-data/tools/kubestr/kubestr"
    rm -rf "${TEMP_KUBESTR_DIR}"
    echo "  [x] Kubestr CLI staged successfully at /custom-data/tools/kubestr/kubestr."
else
    echo "  [!] WARNING: Kubestr package not found in cache! Run 'make deps' first." >&2
fi

echo "[-] Extracting and staging Oras CLI binary..."
mkdir -p "${EXTRACT_DIR}/custom-data/tools/oras"
if [[ -f "${BIN_CACHE_DIR}/${ORAS_PACKAGE_FILENAME}" ]]; then
    TEMP_ORAS_DIR=$(mktemp -d)
    tar -xzf "${BIN_CACHE_DIR}/${ORAS_PACKAGE_FILENAME}" -C "${TEMP_ORAS_DIR}"
    cp "${TEMP_ORAS_DIR}/oras" "${EXTRACT_DIR}/custom-data/tools/oras/oras"
    chmod +x "${EXTRACT_DIR}/custom-data/tools/oras/oras"
    rm -rf "${TEMP_ORAS_DIR}"
    echo "  [x] Oras CLI staged successfully at /custom-data/tools/oras/oras."
else
    echo "  [!] WARNING: Oras package not found in cache! Run 'make deps' first." >&2
fi

echo "[-] Copying pre-seeded offline Debian packages..."
mkdir -p "${EXTRACT_DIR}/custom-data/packages"
if ls "${PROJECT_ROOT}/.cache/packages"/*.deb &>/dev/null; then
    cp "${PROJECT_ROOT}/.cache/packages"/*.deb "${EXTRACT_DIR}/custom-data/packages/"
fi

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

# Detect if Nexus distribution bundles its own JDK 21 runtime (Nexus 3.78+)
BUNDLED_JDK_DIR=$(find "${EXTRACT_DIR}/custom-data/nexus/nexus-bin/jdk" -mindepth 2 -maxdepth 2 -type d -name "jdk-21*" 2>/dev/null | head -n 1)
if [[ -n "${BUNDLED_JDK_DIR}" && -d "${BUNDLED_JDK_DIR}" ]]; then
    echo "[-] Configuring bundled Java 21 runtime for Sonatype Nexus..."
    rm -rf "${EXTRACT_DIR}/custom-data/nexus/jre"
    JDK_REL_PATH=$(realpath --relative-to="${EXTRACT_DIR}/custom-data/nexus" "${BUNDLED_JDK_DIR}")
    ln -sfn "${JDK_REL_PATH}" "${EXTRACT_DIR}/custom-data/nexus/jre"
    echo "  [x] Symlinked /custom-data/nexus/jre -> ${JDK_REL_PATH}"
fi

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
echo "[-] Configuring Nexus user properties to use H2 database and bypass onboarding..."
cat <<'EOF' > "${NEXUS_PROPERTIES}"
nexus.datastore.enabled=true
nexus.onboarding.enabled=false
EOF

echo "[-] Writing local JVM environment config for Sonatype Nexus..."
cat <<'EOF' > "${EXTRACT_DIR}/custom-data/nexus/nexus-bin/bin/nexus.rc"
run_as_user="root"
INSTALL4J_JAVA_HOME_OVERRIDE="/var/lib/nexus/jre"
EOF

# ==========================================
# 2. Inject Mock GDC Companion Data (If configured)
# ==========================================
if [[ -n "${MOCK_GDC_COMPANION_DATA:-}" ]]; then
    MOCK_SOURCE_FILE="${PROJECT_ROOT}/custom-data/machine-info-mock-${MOCK_GDC_COMPANION_DATA}.json"
    MOCK_CRT="${PROJECT_ROOT}/custom-data/mock-client.crt"
    MOCK_KEY="${PROJECT_ROOT}/custom-data/mock-client.key"
    
    echo "[-] Development Override: MOCK_GDC_COMPANION_DATA is set to '${MOCK_GDC_COMPANION_DATA}'"
    
    if [[ ! -f "${MOCK_SOURCE_FILE}" ]]; then
        echo "[!] [ERROR] Mock companion data file not found: ${MOCK_SOURCE_FILE}"
        echo "[!] Continuing with standard mTLS/Companion build..."
    else
        echo "[-] Injecting mock configuration from ${MOCK_SOURCE_FILE} to bypass Companion API..."
        mkdir -p "${EXTRACT_DIR}/custom-data/gdc"
        cp "${MOCK_SOURCE_FILE}" "${EXTRACT_DIR}/custom-data/gdc/machine-info-mock.json"
        
        # Also inject mock certificates if they exist
        if [[ -f "${MOCK_CRT}" ]] && [[ -f "${MOCK_KEY}" ]]; then
            echo "[-] Found mock client certificates. Injecting..."
            cp "${MOCK_CRT}" "${EXTRACT_DIR}/custom-data/gdc/mock-client.crt"
            cp "${MOCK_KEY}" "${EXTRACT_DIR}/custom-data/gdc/mock-client.key"
        fi
        
        # Add early-command to copy it from custom-data to the target filesystem before Ansible runs
        cat << 'EARLY_EOF' > "${EXTRACT_DIR}/custom-data/gdc/inject-mock.sh"
#!/bin/bash
mkdir -p /target/etc/gdc
cp /cdrom/custom-data/gdc/machine-info-mock.json /target/etc/gdc/machine-info-mock.json
if [ -f /cdrom/custom-data/gdc/mock-client.crt ]; then
    cp /cdrom/custom-data/gdc/mock-client.crt /target/etc/gdc/mock-client.crt
    cp /cdrom/custom-data/gdc/mock-client.key /target/etc/gdc/mock-client.key
fi
EARLY_EOF
        chmod +x "${EXTRACT_DIR}/custom-data/gdc/inject-mock.sh"
    fi
fi

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

# Clean-room playbook repository assembly (GDC-SPEC-001 / Source Sanitization)
TEMP_STAGING_DIR=$(mktemp -d)

# Determine destination folder inside the staging directory based on ANSIBLE_PLAYBOOK_HOME
TARGET_COPY_DIR="${TEMP_STAGING_DIR}"
if [[ -n "${ANSIBLE_PLAYBOOK_HOME:-}" && "${ANSIBLE_PLAYBOOK_HOME}" != "/" ]]; then
    TARGET_COPY_DIR="${TEMP_STAGING_DIR}/${ANSIBLE_PLAYBOOK_HOME}"
    mkdir -p "${TARGET_COPY_DIR}"
fi

# Copy ONLY the contents of src/ansible/ into the target directory
cp -r "${PROJECT_ROOT}/src/ansible"/* "${TARGET_COPY_DIR}/"
if [[ -f "${PROJECT_ROOT}/src/ansible/.gitignore" ]]; then
    cp "${PROJECT_ROOT}/src/ansible/.gitignore" "${TARGET_COPY_DIR}/.gitignore"
fi

# Clean-room sanitization: purge any compiled Python bytecode and cache dirs
find "${TARGET_COPY_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${TARGET_COPY_DIR}" -name "*.py[cod]" -delete 2>/dev/null || true
find "${TARGET_COPY_DIR}" -name '*$py.class' -delete 2>/dev/null || true
find "${TARGET_COPY_DIR}" -name "*.retry" -delete 2>/dev/null || true

# [HOTFIX] Inject the rendered all.yml global vars from the hydrator,
# replacing the checked-in all.yml.j2 so ansible-pull has actual variables
if [[ -f "${EXTRACT_DIR}/custom-data/ansible/vars/all.yml" ]]; then
    mkdir -p "${TARGET_COPY_DIR}/vars"
    cp "${EXTRACT_DIR}/custom-data/ansible/vars/all.yml" "${TARGET_COPY_DIR}/vars/all.yml"
    rm -f "${TARGET_COPY_DIR}/vars/all.yml.j2"
fi

# Initialize a fresh, clean git repository inside the staging directory
git -C "${TEMP_STAGING_DIR}" init -b main &>/dev/null
git -C "${TEMP_STAGING_DIR}" config user.name "${GDC_RELEASE_USER_NAME:-GDC Release Builder}"
git -C "${TEMP_STAGING_DIR}" config user.email "${GDC_RELEASE_USER_EMAIL:-gdc-release@google.com}"
git -C "${TEMP_STAGING_DIR}" add . &>/dev/null
git -C "${TEMP_STAGING_DIR}" commit -m "GDC Ansible Playbook Release v${ISO_VERSION}" &>/dev/null

# Clone this sanitized single-commit staging repository as a bare repo
if git clone --bare "file://${TEMP_STAGING_DIR}" "${TARGET_BARE_REPO}" &>/dev/null; then
    echo "  [x] GDC Playbooks pre-seeded, sanitized, and compiled cleanly (single-commit release)."
else
    echo "  [!] Failed to pre-seed playbooks locally. Initializing local dummy playbook git repository."
    git init --bare "${TARGET_BARE_REPO}" &>/dev/null
fi
rm -rf "${TEMP_STAGING_DIR}"

# Set Git pre-receive blocking hook for Read-Only assurance
mkdir -p "${TARGET_BARE_REPO}/hooks"
cat <<'EOF' > "${TARGET_BARE_REPO}/hooks/pre-receive"
#!/usr/bin/env bash
echo "[!] [GGD SECURITY ERROR] Direct pushing to Gitea's local bootstrap repository is strictly forbidden." >&2
echo "[-] This repository is READ-ONLY. It can only pull updates from the upstream origin." >&2
exit 1
EOF
chmod +x "${TARGET_BARE_REPO}/hooks/pre-receive"


echo "[-] Pre-seeding Secondary Ansible Playbook Repository (system-desired-state)..."
SECONDARY_REPOS_DIR="${EXTRACT_DIR}/custom-data/gitea/repos/gdc"
SECONDARY_BARE_REPO="${SECONDARY_REPOS_DIR}/system-desired-state.git"

mkdir -p "${SECONDARY_BARE_REPO}"

if [[ -n "${UPSTREAM_DESIRED_STATE_REPO:-}" ]]; then
    echo "  [-] Cloning upstream desired state repository: ${UPSTREAM_DESIRED_STATE_REPO}"
    TEMP_SECONDARY_DIR=$(mktemp -d)
    
    if git clone --depth 1 "${UPSTREAM_DESIRED_STATE_REPO}" "${TEMP_SECONDARY_DIR}" &>/dev/null; then
        git -C "${SECONDARY_BARE_REPO}" init --bare --initial-branch=main &>/dev/null
        git -C "${TEMP_SECONDARY_DIR}" push "${SECONDARY_BARE_REPO}" HEAD:main &>/dev/null
        echo "  [x] Successfully packaged upstream desired state playbooks."
    else
        echo "  [!] Failed to clone upstream repo. Initializing empty bare repository."
        git init --bare "${SECONDARY_BARE_REPO}" &>/dev/null
    fi
    rm -rf "${TEMP_SECONDARY_DIR}"
else
    echo "  [-] No upstream specified. Initializing clean bare repository with no-op skeleton."
    git init --bare -b main "${SECONDARY_BARE_REPO}" &>/dev/null
    
    # Create a mock local.yml so ansible-pull completes successfully
    TEMP_MOCK_DIR=$(mktemp -d)
    git -C "${TEMP_MOCK_DIR}" init -b main &>/dev/null
    git -C "${TEMP_MOCK_DIR}" config user.name "${GDC_RELEASE_USER_NAME:-GDC Release Builder}"
    git -C "${TEMP_MOCK_DIR}" config user.email "${GDC_RELEASE_USER_EMAIL:-gdc-release@google.com}"
    
    cat <<EOF > "${TEMP_MOCK_DIR}/local.yml"
---
- name: GDC Desired State Baseline Fallback
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: "GDC-SDS | Debug: No customer desired state repository configured"
      ansible.builtin.debug:
        msg: "The node is operating successfully in standalone mode. To apply configurations, point the desired state repository to an upstream git remote."
EOF
    
    git -C "${TEMP_MOCK_DIR}" add local.yml &>/dev/null
    git -C "${TEMP_MOCK_DIR}" commit -m "chore: mock empty desired state playbook" &>/dev/null
    git -C "${TEMP_MOCK_DIR}" push "${SECONDARY_BARE_REPO}" HEAD:main &>/dev/null
    rm -rf "${TEMP_MOCK_DIR}"
fi

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

# Prune nested tests to prevent test.iso generation and other test bloat (GDC-SPEC-001)
rm -rf "${COLLECTIONS_DIR}/collections/ansible_collections/community/general/tests"

# ==========================================
# 3. Dynamic Banners, bootloaders, and Casper bypass
# ==========================================
echo "[-] Copying and configuring Python Netplan hydrator and storage generator..."
cp "${SCRIPT_DIR}/configure_netplan.py" "${EXTRACT_DIR}/custom-data/"
chmod +x "${EXTRACT_DIR}/custom-data/configure_netplan.py"
cp "${SCRIPT_DIR}/generate_storage_config.sh" "${EXTRACT_DIR}/custom-data/"
chmod +x "${EXTRACT_DIR}/custom-data/generate_storage_config.sh"
cp "${SCRIPT_DIR}/scan_ips.py" "${EXTRACT_DIR}/custom-data/"
chmod +x "${EXTRACT_DIR}/custom-data/scan_ips.py"

echo "[-] Obtaining gdc-collector..."
CACHE_DIAG="${PROJECT_ROOT}/.cache/binaries/gdc-collector"
if [[ -f "${CACHE_DIAG}" ]]; then
    echo "  [x] Using cached gdc-collector."
    cp "${CACHE_DIAG}" "${EXTRACT_DIR}/custom-data/gdc-collector"
else
    echo "  [!] ERROR: gdc-collector not found in cache! Ensure it is synced from GCS first." >&2
    exit 1
fi
chmod +x "${EXTRACT_DIR}/custom-data/gdc-collector"

echo "[-] Obtaining gdc-companion..."
CACHE_COMPANION="${PROJECT_ROOT}/.cache/binaries/gdc-companion"
if [[ -f "${CACHE_COMPANION}" ]]; then
    echo "  [x] Using cached gdc-companion."
    cp "${CACHE_COMPANION}" "${EXTRACT_DIR}/custom-data/gdc-companion"
    chmod +x "${EXTRACT_DIR}/custom-data/gdc-companion"
else
    echo "  [!] WARNING: gdc-companion not found in cache. Skipping." >&2
fi

echo "[-] Generating dynamic Message of the Day (MOTD) banner..."
"${SCRIPT_DIR}/generate_banner.py" "${EXTRACT_DIR}/custom-data/boot-banner.txt" "${ISO_VERSION}"

# Unpack, patch, and repack initrd to inject GDC early-boot progress logs
INITRD_PATH="${EXTRACT_DIR}/casper/initrd"
if [[ -f "${INITRD_PATH}" ]]; then
    # Ensure cpio and unmkinitramfs are present in the builder environment
    if ! command -v cpio &>/dev/null || ! command -v unmkinitramfs &>/dev/null; then
        echo "[-] Required initramfs tools are missing in builder environment. Bootstrapping on the fly..."
        apt-get update &>/dev/null && apt-get install -y cpio initramfs-tools-core &>/dev/null || true
    fi
    
    echo "[-] Unpacking and patching initrd to inject GDC early-boot progress logs..."
    INITRD_TMP=$(mktemp -d)
    
    # Extract using the official multi-segment unmkinitramfs tool
    unmkinitramfs "${INITRD_PATH}" "${INITRD_TMP}"
    
    CASPER_HELPER="${INITRD_TMP}/main/scripts/casper"
    if [[ -f "${CASPER_HELPER}" ]]; then
        echo "  [-] Found scripts/casper inside initrd. Patching with progress messages..."
        # Create a python helper script on the fly to patch scripts/casper safely without shell quoting issues
        cat <<'EOF' > /tmp/patch_initrd.py
import os
fpath = os.environ.get('CASPER_HELPER_PATH')
if fpath and os.path.exists(fpath):
    with open(fpath, 'r') as f:
        content = f.read()
    old_val = 'wget "$url" -O "$dest"'
    if old_val in content:
        new_val = """echo "=============================================================================="
echo "[-] GDC-BOOT-STAGE | Ingesting GDC Remastered ISO over the Network..."
echo "[-] Target URL:  $url"
echo "[-] File Size:   ~4.3 GB (Contains complete offline Gitea/Nexus repositories)"
echo "[-] Status:      Copying image directly into RAM (typically takes 45-120s)..."
echo "=============================================================================="
wget "$url" -O "$dest"
echo "=============================================================================="
echo "[x] GDC-BOOT-STAGE | Download 100% complete! Mount overlay successful."
echo "[-] GDC-BOOT-STAGE | Handing off control to systemd..."
echo "=============================================================================="""
        content = content.replace(old_val, new_val)
        with open(fpath, 'w') as f:
            f.write(content)
        print('  [x] scripts/casper successfully patched.')
    else:
        print('  [!] Error: wget download block not found in scripts/casper.')
else:
    print('  [!] Error: CASPER_HELPER_PATH is missing or invalid.')
EOF
        CASPER_HELPER_PATH="${CASPER_HELPER}" python3 /tmp/patch_initrd.py
        rm -f /tmp/patch_initrd.py
    fi
    
    # Repack concatenated multi-segment initrd
    echo "  [-] Repacking multi-segment initrd..."
    (cd "${INITRD_TMP}/early" && find . | cpio -o -H newc --quiet) > "${INITRD_PATH}"
    
    # Process subsequent early segments if they exist
    for early_seg in "${INITRD_TMP}/early"*; do
        if [[ "${early_seg}" != "${INITRD_TMP}/early" && -d "${early_seg}" ]]; then
            (cd "${early_seg}" && find . | cpio -o -H newc --quiet) >> "${INITRD_PATH}"
        fi
    done
    
    (cd "${INITRD_TMP}/main" && find . | cpio -o -H newc --quiet | zstd -c -8) >> "${INITRD_PATH}"
    rm -rf "${INITRD_TMP}"
    echo "  [x] initrd successfully repacked and optimized."
fi

# Patch GRUB boot loader config
GRUB_CFG="${EXTRACT_DIR}/boot/grub/grub.cfg"
if [[ -f "${GRUB_CFG}" ]]; then
    echo "[-] Overwriting GRUB configuration to enforce unattended bootstrap..."
    cat <<'EOF' > "${GRUB_CFG}"
set timeout=5
set default=0

serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1
terminal_input console serial
terminal_output console serial

menuentry "Google Distributed Cloud (GDC) Automated Installer [Default]" {
    set gfxpayload=keep
    echo "Booting GDC Unattended Installer..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 autoinstall "ds=nocloud;s=/cdrom/nocloud/" ip=dhcp apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp ---
    initrd /casper/initrd
}

menuentry "GDC Interactive Subiquity Installer (Manual Step-by-Step)" {
    set gfxpayload=keep
    echo "Booting GDC Interactive Installer..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp ---
    initrd /casper/initrd
}

menuentry "GDC Manual Rescue Shell (Interactive Terminal)" {
    set gfxpayload=keep
    echo "Booting GDC Manual Rescue Shell..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp init=/bin/sh ---
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

# Ensure the El Torito boot image exists
if [[ ! -f "${EXTRACT_DIR}/boot/grub/i386-pc/eltorito.img" ]]; then
    # In some modern Ubuntu ISOs it's relocated or absent. Try to find an alternative.
    ALT_ELTORITO=$(find "${EXTRACT_DIR}" -name "eltorito.img" | head -n 1)
    if [[ -n "${ALT_ELTORITO}" ]]; then
         mkdir -p "${EXTRACT_DIR}/boot/grub/i386-pc"
         cp "${ALT_ELTORITO}" "${EXTRACT_DIR}/boot/grub/i386-pc/eltorito.img"
    else
         echo "WARN: eltorito.img not found! xorriso might fail. Creating dummy if absent."
         mkdir -p "${EXTRACT_DIR}/boot/grub/i386-pc"
         dd if=/dev/zero of="${EXTRACT_DIR}/boot/grub/i386-pc/eltorito.img" bs=512 count=4 status=none
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
