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
            # Export only if not already set in active shell (always load ADMIN_SSH_PUB_KEYS from file to handle spaces)
            if [[ -z "${!key:-}" ]] || [[ "${key}" == "ADMIN_SSH_PUB_KEYS" ]]; then
                export "${key}"="${value}"
            fi
        fi
    done < "${ENV_FILE}"
else
    echo "[!] Error: Configuration file build.env not found in ${SCRIPT_DIR}" >&2
    exit 1
fi

# Load local environment overrides (if present) to augment/override defaults
LOCAL_ENV_FILE="${SCRIPT_DIR}/local.env"
if [[ -f "${LOCAL_ENV_FILE}" ]]; then
    echo "[-] Loading local environment overrides from local.env..."
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
            # Local overrides always take precedence and overwrite
            export "${key}"="${value}"
        fi
    done < "${LOCAL_ENV_FILE}"
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
FINAL_ISO_NAME="${ISO_NAME_PREFIX}-v${ISO_VERSION}.iso"
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
# Production-grade user-data enforcing dynamic LVM schemes, SSH enablement, webhook reporting, and robust error logging.
cat <<'EOF' > "${EXTRACT_DIR}/nocloud/user-data"
#cloud-config
autoinstall:
  version: 1
  identity:
    hostname: gdc-standalone-node
    username: temporary-installer
    password: "$6$lXNktB5evbvaOJPd$xytpJZFOGTZ0Lj9c4EWIMrMfyOC7qkT5sO0baZckP3bx3AvIFFpl3j4FYbWXMuvfd1/pbWgPQZSv4/LvV9MQP/"
  locale: en_US.UTF-8
  keyboard: {layout: us}
  network:
    version: 2
    ethernets:
      all-en:
        match:
          name: "e*"
        dhcp4: true
  ssh:
    install-server: true
    allow-pw: true
    authorized-keys:
      - __ADMIN_SSH_PUB_KEYS__
  packages:
    - ansible
    - git
  reporting:
    gdc-gateway:
      type: webhook
      endpoint: __INSTALL_COMPANION_URL__
      level: info
  early-commands:
    - |
      # Print GDC vintage parchment boot banner with version and build timestamp
      if [ -f /cdrom/custom-data/boot-banner.txt ]; then
        cat /cdrom/custom-data/boot-banner.txt > /dev/ttyS0 2>/dev/null || true
        cat /cdrom/custom-data/boot-banner.txt > /dev/console 2>/dev/null || true
        cat /cdrom/custom-data/boot-banner.txt
      fi
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Activating Live ISO network segment"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Activating Live ISO network segment"
      PHYS_IFACE=$(ls /sys/class/net | grep -E '^e' | head -n 1 || echo "eth0")
      
      # Configure Live ISO network interface based on VLAN ID using DHCP
      VLAN_ID="__MACHINE_VLAN_ID__"
      if [ -z "${VLAN_ID}" ] || [ "${VLAN_ID}" = "0" ]; then
        # Untagged native configuration (directly on physical interface!)
        echo "[-] Running on untagged native network. Retaining existing DHCP configuration."
        ip link set dev "${PHYS_IFACE}" up || true
      else
        # Tagged VLAN configuration
        echo "[-] Running on tagged VLAN ${VLAN_ID}. Activating VLAN interface..."
        ip link add link "${PHYS_IFACE}" name "${PHYS_IFACE}.${VLAN_ID}" type vlan id "${VLAN_ID}" 2>/dev/null || true
        ip link set dev "${PHYS_IFACE}.${VLAN_ID}" up || true
        echo "[-] Requesting DHCP address on VLAN interface..."
        dhclient "${PHYS_IFACE}.${VLAN_ID}" 2>/dev/null || systemctl restart systemd-networkd || true
      fi
      
      # Add static DNS host mapping for GDC Companion resolving
      echo "__COMPANION_RESOLVED_IP__ __COMPANION_HOST__" >> /etc/hosts
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Scanning block devices and generating dynamic storage config"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Scanning block devices and generating dynamic storage config"
      cp /cdrom/custom-data/generate_storage_config.sh /tmp/generate_storage_config.sh
      chmod +x /tmp/generate_storage_config.sh
      if /tmp/generate_storage_config.sh; then
        echo "=============================================================================="
        echo "[GDC-INSTALL-GOAL] Task Succeeded: Dynamic storage config generated successfully"
        echo "=============================================================================="
        logger -t gdc-provisioner "[GOAL] Dynamic storage config generated successfully"
      else
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo "[GDC-INSTALL-FAIL] Critical Failure: Dynamic storage configuration generation failed!"
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        logger -p user.err -t gdc-provisioner "[FAILURE] Dynamic storage configuration generation failed"
        exit 1
      fi
    - |
      # Merge storage config into /autoinstall.yaml and Subiquity autoinstall configurations
      python3 -c "
      import os, yaml
      base_path = '/cdrom/nocloud/user-data'
      if not os.path.exists(base_path):
          base_path = '/run/installer/autoinstall-user-data'
      with open(base_path, 'r') as f:
          c = yaml.safe_load(f)
      with open('/run/autoinstall-storage.yaml', 'r') as f:
          s = yaml.safe_load(f)
      c['autoinstall']['storage'] = s['storage']
      
      # Save to standard autoinstall configurations
      yaml.safe_dump(c, open('/autoinstall.yaml', 'w'))
      os.makedirs('/run/installer', exist_ok=True)
      yaml.safe_dump(c, open('/run/installer/autoinstall-user-data', 'w'))
      "
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Verifying connectivity to GDC Installation Companion"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Verifying connectivity to GDC Installation Companion"
      COMPANION_URL="__INSTALL_COMPANION_URL__"
      SUCCESS=false
      for i in 1 2 3; do
        echo "[-] Attempt $i of 3: Connecting to GDC Companion at ${COMPANION_URL}..."
        if curl -s -I --connect-timeout 2 "${COMPANION_URL}" &>/dev/null; then
          echo "[-] Connection to GDC Installation Companion established successfully!"
          SUCCESS=true
          break
        fi
        if [ "$i" -lt 3 ]; then
          echo "[!] Connection failed. Retrying in 5 seconds..."
          sleep 5
        fi
      done
      if [ "${SUCCESS}" = "false" ]; then
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo "[GDC-INSTALL-FAIL] Critical Failure: Connectivity to GDC Installation Companion could not be verified after 3 attempts!"
        echo "[GDC-INSTALL-FAIL] Ensure that the companion server is running and accessible."
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        logger -p user.err -t gdc-provisioner "[FAILURE] Connectivity to GDC Installation Companion failed"
        exit 1
      fi
  late-commands:
    # Sync pre-seeded assets cleanly and set up service persistent storage
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Syncing Gitea, Nexus, & Ansible collections"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Syncing Gitea, Nexus, & Ansible collections"
      mkdir -p /target/var/lib/gitea /target/var/lib/nexus /target/usr/share/ansible/collections
      if rsync -a --sparse /cdrom/custom-data/gitea/ /target/var/lib/gitea/ && \
         rsync -a --sparse /cdrom/custom-data/nexus/ /target/var/lib/nexus/ && \
         { [ ! -d /cdrom/custom-data/ansible/collections ] || rsync -a /cdrom/custom-data/ansible/collections/ /target/usr/share/ansible/collections/; }; then
        logger -t gdc-provisioner "[GOAL] Asset synchronization completed"
      else
        echo "[GDC-INSTALL-FAIL] Critical Failure: Syncing pre-seeded assets failed!"
        exit 1
      fi
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Deploying and enabling systemd service units & timers"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Deploying and enabling systemd service units & timers"
      cp /cdrom/custom-data/systemd/gitea.service /target/etc/systemd/system/
      cp /cdrom/custom-data/systemd/nexus.service /target/etc/systemd/system/
      cp /cdrom/custom-data/systemd/gdc-provision.service /target/etc/systemd/system/
      cp /cdrom/custom-data/systemd/gdc-provision.timer /target/etc/systemd/system/
      curtin in-target -- systemctl enable gdc-provision.service gdc-provision.timer
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Injecting custom administrative SSH public keys"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Injecting custom administrative SSH public keys"
      PUB_KEY="__ADMIN_SSH_PUB_KEYS__"
      if [ -n "${PUB_KEY}" ]; then
        mkdir -p /target/root/.ssh /target/home/temporary-installer/.ssh
        echo "${PUB_KEY}" >> /target/root/.ssh/authorized_keys
        echo "${PUB_KEY}" >> /target/home/temporary-installer/.ssh/authorized_keys
        chmod 700 /target/root/.ssh /target/home/temporary-installer/.ssh
        chmod 600 /target/root/.ssh/authorized_keys /target/home/temporary-installer/.ssh/authorized_keys
        chown -R 1000:1000 /target/home/temporary-installer/.ssh
        logger -t gdc-provisioner "[GOAL] SSH public keys successfully authorized"
      else
        logger -t gdc-provisioner "[GOAL] No custom SSH public keys configured, skipping injection"
      fi
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Deploying GDC Message of the Day (MOTD)"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Deploying GDC Message of the Day (MOTD)"
      if [ -f /cdrom/custom-data/boot-banner.txt ]; then
        cp /cdrom/custom-data/boot-banner.txt /target/etc/motd
        logger -t gdc-provisioner "[GOAL] GDC boot banner copied to MOTD successfully"
      else
        logger -t gdc-provisioner "[GOAL] Boot banner not found, skipping MOTD setup"
      fi
    # Ssh and passwordless root-unlock setup for transition gap
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Configuring passwordless boot-unlock key file"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Configuring passwordless boot-unlock key file"
      mkdir -p /target/etc/keys
      echo -n "temporary_bootstrap_key_to_be_enrolled_to_tpm" > /target/etc/keys/temp_key.key
      chmod 400 /target/etc/keys/temp_key.key
      CRYPT_DEV=$(blkid -t TYPE=crypto_LUKS -o device | head -n 1)
      if [ -n "$CRYPT_DEV" ]; then
        echo -n "temporary_bootstrap_key_to_be_enrolled_to_tpm" > /tmp/pass.txt
        if cryptsetup luksAddKey --key-file=/tmp/pass.txt "$CRYPT_DEV" /target/etc/keys/temp_key.key; then
          logger -t gdc-provisioner "[GOAL] Added key to LUKS device $CRYPT_DEV"
          sed -i 's/ none / \/etc\/keys\/temp_key.key /' /target/etc/crypttab
          logger -t gdc-provisioner "[GOAL] Updated crypttab to use key file"
        else
          echo "[GDC-INSTALL-FAIL] Critical Failure: Failed to add key to LUKS device!"
          exit 1
        fi
        rm -f /tmp/pass.txt
      else
        logger -t gdc-provisioner "[GOAL] No LUKS device found, skipping key enrollment"
      fi
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Deploying GDC Production VRF Netplan configuration"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Deploying GDC Production VRF Netplan configuration"
      PHYS_IFACE=$(ls /sys/class/net | grep -E '^e' | head -n 1 || echo "eth0")
      mkdir -p /target/etc/netplan
      if sed "s/__PHYS_IFACE__/${PHYS_IFACE}/g" /cdrom/custom-data/network-template.yaml > /target/etc/netplan/01-netcfg.yaml; then
        chmod 600 /target/etc/netplan/01-netcfg.yaml
        logger -t gdc-provisioner "[GOAL] GDC Production VRF Netplan deployed successfully on ${PHYS_IFACE}"
      else
        echo "[GDC-INSTALL-FAIL] Critical Failure: Failed to generate production Netplan!"
        exit 1
      fi
    - |
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Rebuilding initramfs ramdisks"
      echo "=============================================================================="
      logger -t gdc-provisioner "[GOAL] Rebuilding initramfs ramdisks"
      if curtin in-target -- update-initramfs -u -k all; then
        echo "=============================================================================="
        echo "[GDC-INSTALL-GOAL] All custom late commands succeeded!"
        echo "=============================================================================="
        logger -t gdc-provisioner "[GOAL] Rebuilding initramfs succeeded"
      else
        echo "[GDC-INSTALL-FAIL] Critical Failure: Rebuilding initramfs failed!"
        exit 1
      fi
EOF

# C. Inject Custom Services Directory (Hub and Spoke structures)
mkdir -p "${EXTRACT_DIR}/custom-data/gitea"
mkdir -p "${EXTRACT_DIR}/custom-data/nexus"
mkdir -p "${EXTRACT_DIR}/custom-data/systemd"
mkdir -p "${EXTRACT_DIR}/custom-data/ansible/collections"

echo "[-] Pre-packaging Ansible collections for offline use..."
COLLECTIONS_DIR="${EXTRACT_DIR}/custom-data/ansible"
if command -v ansible-galaxy &>/dev/null; then
    echo "[-] Pre-installing community.general via ansible-galaxy..."
    ansible-galaxy collection install community.general -p "${COLLECTIONS_DIR}/collections"
else
    echo "[-] ansible-galaxy not found on host. Downloading community.general collection archive directly..."
    # Download community.general 8.6.0 (stable and highly compatible)
    GALAXY_URL="https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/artifacts/community-general-8.6.0.tar.gz"
    TEMP_TAR="/tmp/community-general.tar.gz"
    mkdir -p "${COLLECTIONS_DIR}/collections/ansible_collections/community/general"
    if curl -sSL -o "${TEMP_TAR}" "${GALAXY_URL}"; then
        echo "[-] Successfully downloaded community.general collection archive."
        tar -xzf "${TEMP_TAR}" -C "${COLLECTIONS_DIR}/collections/ansible_collections/community/general"
        rm -f "${TEMP_TAR}"
        echo "[-] community.general collection extracted successfully."
    else
        echo "[!] Warning: Failed to download community.general collection offline asset. Building without it."
    fi
fi

# Generate the custom boot-banner containing compilation version and timestamp
"${SCRIPT_DIR}/generate_banner.py" "${EXTRACT_DIR}/custom-data/boot-banner.txt" "${ISO_VERSION}"

# Dynamically generate the Network Netplan template and substitute variables in user-data using Python (dependency-free)
python3 -c "
import os, urllib.parse, socket

paths = ['${EXTRACT_DIR}/nocloud/user-data']

companion_url = os.environ.get('INSTALL_COMPANION_URL', 'http://192.168.10.1:8080/v1/install-logs')
parsed_url = urllib.parse.urlparse(companion_url)
companion_host = parsed_url.hostname or '192.168.10.1'

try:
    companion_ip = socket.gethostbyname(companion_host)
except Exception:
    companion_ip = '192.168.1.53'

machine_vlan = os.environ.get('MACHINE_VLAN_ID', '10').strip()
k8s_vlan = os.environ.get('K8S_VLAN_ID', '20').strip()

# Build the Netplan string dynamically using robust Python string operations
vlan_block = ''
vrf_interfaces = \"['__PHYS_IFACE__']\"

if machine_vlan and machine_vlan != '0':
    vlan_block = f'''
  vlans:
    __PHYS_IFACE__.{machine_vlan}:
      id: {machine_vlan}
      link: __PHYS_IFACE__
      addresses: [{os.environ.get('MACHINE_IP_CIDR', '192.168.9.5/29')}]
      routes:
        - to: default
          via: {os.environ.get('MACHINE_GATEWAY', '192.168.9.1')}
          metric: 100
      nameservers:
        addresses: [{os.environ.get('MACHINE_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4')}]'''
    vrf_interfaces = f\"['__PHYS_IFACE__.{machine_vlan}']\"

ethernet_ips = ''
if not machine_vlan or machine_vlan == '0':
    ethernet_ips = f'''
      addresses: [{os.environ.get('MACHINE_IP_CIDR', '192.168.9.5/29')}]
      routes:
        - to: default
          via: {os.environ.get('MACHINE_GATEWAY', '192.168.9.1')}
          metric: 100
      nameservers:
        addresses: [{os.environ.get('MACHINE_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4')}]'''

k8s_vlan_block = ''
k8s_vrf_block = ''
if k8s_vlan and k8s_vlan != '0':
    k8s_vlan_block = f'''
    __PHYS_IFACE__.{k8s_vlan}:
      id: {k8s_vlan}
      link: __PHYS_IFACE__
      addresses: [{os.environ.get('K8S_IP_CIDR', '192.168.9.10/29')}]
      routes:
        - to: default
          via: {os.environ.get('K8S_GATEWAY', '192.168.9.9')}
          metric: 200
      nameservers:
        addresses: [{os.environ.get('K8S_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4')}]'''
        
    k8s_vrf_block = f'''
    vrf-k8s:
      table: 20
      interfaces: [\\'__PHYS_IFACE__.{k8s_vlan}\\']'''

# Combine vlan blocks
all_vlans = ''
if vlan_block or k8s_vlan_block:
    all_vlans = '\\n  vlans:' + vlan_block.replace('\\n  vlans:\\n', '\\n') + k8s_vlan_block

netcfg_text = f'''network:
  version: 2
  renderer: networkd
  ethernets:
    __PHYS_IFACE__:
      dhcp4: no
      dhcp6: no
      link-local: []{ethernet_ips}{all_vlans}
  vrfs:
    vrf-machine:
      table: 10
      interfaces: {vrf_interfaces}{k8s_vrf_block}
'''

os.makedirs(os.path.dirname('${EXTRACT_DIR}/custom-data/network-template.yaml'), exist_ok=True)
with open('${EXTRACT_DIR}/custom-data/network-template.yaml', 'w') as f:
    f.write(netcfg_text)

# Substitutes standard variables in user-data on-the-fly
replacements = {
    '__MACHINE_VLAN_ID__': machine_vlan,
    '__K8S_VLAN_ID__': k8s_vlan,
    '__MACHINE_IP_CIDR__': os.environ.get('MACHINE_IP_CIDR', '192.168.9.5/29'),
    '__MACHINE_GATEWAY__': os.environ.get('MACHINE_GATEWAY', '192.168.9.1'),
    '__MACHINE_DNS__': os.environ.get('MACHINE_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4'),
    '__K8S_IP_CIDR__': os.environ.get('K8S_IP_CIDR', '192.168.9.10/29'),
    '__K8S_GATEWAY__': os.environ.get('K8S_GATEWAY', '192.168.9.9'),
    '__K8S_DNS__': os.environ.get('K8S_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4'),
    '__INSTALL_COMPANION_URL__': companion_url,
    '__COMPANION_HOST__': companion_host,
    '__COMPANION_RESOLVED_IP__': companion_ip,
    '__ADMIN_SSH_PUB_KEYS__': os.environ.get('ADMIN_SSH_PUB_KEYS', '').strip(),
}

for path in paths:
    if os.path.exists(path):
        with open(path, 'r') as f:
            content = f.read()
        for placeholder, val in replacements.items():
            content = content.replace(placeholder, str(val))
        with open(path, 'w') as f:
            f.write(content)
"

# Copy the dynamic LVM layout generator script onto the ISO
cp "${SCRIPT_DIR}/generate_storage_config.sh" "${EXTRACT_DIR}/custom-data/"
chmod +x "${EXTRACT_DIR}/custom-data/generate_storage_config.sh"

# Write out Gitea, Nexus, and GDC provisioning systemd service configurations
cat <<'EOF' > "${EXTRACT_DIR}/custom-data/systemd/gitea.service"
[Unit]
Description=Gitea (Git with a cup of tea)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/lib/gitea
ExecStart=/var/lib/gitea/gitea web --config /var/lib/gitea/custom/conf/app.ini
Restart=always
Environment=USER=root HOME=/var/lib/gitea GITEA_WORK_DIR=/var/lib/gitea

[Install]
WantedBy=multi-user.target
EOF

cat <<'EOF' > "${EXTRACT_DIR}/custom-data/systemd/nexus.service"
[Unit]
Description=nexus service
After=network.target

[Service]
Type=forking
LimitNOFILE=65536
ExecStart=/var/lib/nexus/nexus-bin/bin/nexus start
ExecStop=/var/lib/nexus/nexus-bin/bin/nexus stop
User=root
Restart=on-abort

[Install]
WantedBy=multi-user.target
EOF

cat <<'EOF' > "${EXTRACT_DIR}/custom-data/systemd/gdc-provision.service"
[Unit]
Description=GDC Ready-Linux First Boot Provisioner
After=gitea.service nexus.service network.target
Requires=gitea.service nexus.service

[Service]
Type=oneshot
EnvironmentFile=-/etc/default/gdc-provision
ExecStart=/bin/bash -c "/usr/bin/ansible-pull \
  -U http://127.0.0.1:3000/gdc/bootstrap-playbooks.git \
  -i localhost, \
  $ANSIBLE_PULL_FLAGS \
  ansible/local.yml"
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF > "${EXTRACT_DIR}/custom-data/systemd/gdc-provision.timer"
[Unit]
Description=Daily GDC Ready-Linux Configuration Pull Sync

[Timer]
OnCalendar=*-*-* ${ANSIBLE_PULL_SCHEDULE}
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Create placeholder binaries to establish the files/directory structure
echo "#!/bin/bash" > "${EXTRACT_DIR}/custom-data/gitea/gitea"
echo "echo 'Gitea Placeholder'" >> "${EXTRACT_DIR}/custom-data/gitea/gitea"
chmod +x "${EXTRACT_DIR}/custom-data/gitea/gitea"

echo "#!/bin/bash" > "${EXTRACT_DIR}/custom-data/nexus/nexus"
echo "echo 'Nexus Placeholder'" >> "${EXTRACT_DIR}/custom-data/nexus/nexus"
chmod +x "${EXTRACT_DIR}/custom-data/nexus/nexus"

# Clone the upstream playbook repository as a read-only mirror (cloned at ISO creation time)
# Organized under the "gdc" owner namespace to allow direct localhost:3000/gdc/bootstrap-playbooks.git fetches
GITEA_REPOS_DIR="${EXTRACT_DIR}/custom-data/gitea/repos/gdc"
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
    linux /casper/vmlinuz quiet autoinstall ds=nocloud;s=/cdrom/nocloud/ ip=none ---
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
# 4.5. Regenerate ISO MD5 Checksums
# ==============================================================================
# Since we overwrote bootloader files and added custom configurations, we must
# regenerate the md5sum.txt file to prevent Casper integrity check failures
# during boot, which can cause Subiquity to drop back to interactive mode.
if [[ -f "${EXTRACT_DIR}/md5sum.txt" ]]; then
    echo "[-] Regenerating md5sum.txt to reflect customized bootloader and configuration files..."
    (cd "${EXTRACT_DIR}" && find . -type f -not -name "md5sum.txt" -print0 | xargs -0 md5sum > md5sum.txt)
    echo "[-] md5sum.txt updated successfully."
fi

# ==============================================================================
# 5. Compile & Repack Bootable ISO (using xorriso)
# ==============================================================================
echo "[-] Compiling bootable custom GDC ISO..."

# ==============================================================================
# 5. Compile & Repack Bootable ISO (using xorriso)
# ==============================================================================
echo "[-] Extracting embedded EFI system partition from original ISO dynamically..."
PART_INFO=$(xorriso -indev "${SOURCE_ISO}" -report_el_torito as_mkisofs 2>/dev/null | grep "\-append_partition 2" || true)

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
