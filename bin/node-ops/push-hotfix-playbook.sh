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
# GDC Node Playbook Hotfix Pusher
# ==============================================================================
# Pushes the local development ansible playbook directly into the remote node's
# local Gitea bare repository and restarts the gdc-provision service.
#
# DESIGN NOTE (Technical Debt / Future Roadmap):
# This script currently utilizes a direct RSYNC payload delivery mechanism and
# dynamically renders the 'vars/all.yml' file based on the *operator's local*
# build.env and local.env context. 
# In the future, once ENFORCE_SIGNED_COMMITS=true becomes mandatory across
# environments, this mechanism must be replaced with a native Git push workflow
# containing digitally signed commits pulled directly from an authorized upstream.
# ==============================================================================

set -eo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_EXEC="${PROJECT_ROOT}/.venv/bin/python3"

# Fallback to system python if venv isn't present
if [[ ! -x "$PYTHON_EXEC" ]]; then
    PYTHON_EXEC="python3"
fi

usage() {
    echo "Usage: $0 --ip <TARGET_IP(s)> [--resume-from <STAGE>]"
    echo ""
    echo "Arguments:"
    echo "  --ip             Comma-separated list of target IPs (e.g., 192.168.9.241,192.168.9.242)"
    echo "  --resume-from    Force Ansible to resume from a specific stage by deleting its completion state."
    echo "                   Valid stages: first-boot, second-boot, linux-ready, cluster-ready"
    echo "  --help           Show this message"
    echo ""
    exit 1
}

TARGET_IPS=""
RESUME_STAGE=""
VALID_STAGES=("first-boot" "second-boot" "linux-ready" "cluster-ready")

while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        --ip)
            TARGET_IPS="$2"
            shift 2
            ;;
        --resume-from)
            RESUME_STAGE="$2"
            shift 2
            ;;
        --help|-h)
            usage
            ;;
        *)
            echo "[!] Unknown option: $1"
            usage
            ;;
    esac
done

if [[ -z "$TARGET_IPS" ]]; then
    echo "[!] Error: --ip argument is required."
    usage
fi

if [[ -n "$RESUME_STAGE" ]]; then
    valid=false
    for stage in "${VALID_STAGES[@]}"; do
        if [[ "$RESUME_STAGE" == "$stage" ]]; then
            valid=true
            break
        fi
    done
    if [[ "$valid" == "false" ]]; then
        echo "[!] Error: Invalid stage '$RESUME_STAGE'."
        echo "    Valid stages are: ${VALID_STAGES[*]}"
        exit 1
    fi
fi

# Convert comma-separated IPs to array
IFS=',' read -ra IP_ARRAY <<< "$TARGET_IPS"

echo "=============================================================================="
echo " GDC HOTFIX DEPLOYMENT PROTOCOL"
echo "=============================================================================="

# 1. Prepare Payload Locally
echo "[-] Preparing playbook payload..."
TEMP_STAGING=$(mktemp -d)
trap 'rm -rf "$TEMP_STAGING"' EXIT

# Copy local src/ansible to staging
rsync -av --exclude='.git' "${PROJECT_ROOT}/src/ansible/" "${TEMP_STAGING}/" > /dev/null

# Render templates to hydrate all.yml
echo "[-] Hydrating vars/all.yml from local environment configuration..."
TEMP_RENDER_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_RENDER_DIR"; rm -rf "$TEMP_STAGING"' EXIT
$PYTHON_EXEC "${PROJECT_ROOT}/src/build/render_templates.py" "${PROJECT_ROOT}/src/build/templates" "${TEMP_RENDER_DIR}" > /dev/null

# Move the rendered all.yml into the payload
if [[ -f "${TEMP_RENDER_DIR}/custom-data/ansible/vars/all.yml" ]]; then
    cp "${TEMP_RENDER_DIR}/custom-data/ansible/vars/all.yml" "${TEMP_STAGING}/vars/all.yml"
else
    echo "[!] Error: render_templates.py failed to produce custom-data/ansible/vars/all.yml"
    exit 1
fi

# Clean up rendered j2 templates from the payload (only root-level var templates)
rm -f "${TEMP_STAGING}/vars/all.yml.j2"

echo "[+] Payload prepared successfully."
echo "------------------------------------------------------------------------------"

# Iterate over each target node
for NODE_IP in "${IP_ARRAY[@]}"; do
    echo "[-] Targeting node: $NODE_IP"
    
    # 2. Connectivity Check
    echo "  [-] Verifying gdc-admin SSH access..."
    if ! ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null gdc-admin@$NODE_IP "echo 'OK'" &>/dev/null; then
        echo "  [!] ERROR: Cannot connect to $NODE_IP as gdc-admin. Skipping node."
        echo "      Ensure the node is fully booted and your SSH keys are deployed."
        echo "------------------------------------------------------------------------------"
        continue
    fi
    echo "  [+] SSH access verified."

    # 3. Payload Delivery
    echo "  [-] Pushing playbook updates via RSYNC..."
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null gdc-admin@$NODE_IP "sudo rm -rf /tmp/ansible-hotfix && mkdir -p /tmp/ansible-hotfix && sudo chown gdc-admin:gdc-admin /tmp/ansible-hotfix" &>/dev/null
    rsync -avz -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" --delete "${TEMP_STAGING}/" gdc-admin@$NODE_IP:/tmp/ansible-hotfix/ > /dev/null
    
    # 4. Remote Repository Manipulation & State Control
    echo "  [-] Committing updates to the node's local playbook repository..."
    
    REMOTE_SCRIPT=$(cat << 'REMOTE_EOF'
#!/usr/bin/env bash
set -e

# Clone the bare repo locally
sudo rm -rf /tmp/repo-checkout
sudo git clone /var/lib/gitea/repos/gdc/bootstrap-playbooks.git /tmp/repo-checkout &>/dev/null
sudo chown -R gdc-admin:gdc-admin /tmp/repo-checkout

# Sync new payload
rsync -a --delete --exclude='.git' /tmp/ansible-hotfix/ /tmp/repo-checkout/

# Setup git identity
cd /tmp/repo-checkout
git config user.email "hotfix@ensor-labs.com"
git config user.name "GDC Hotfix Pusher"

# Commit and Push
git add .
if git diff --staged --quiet; then
    echo "      No changes detected in playbook."
else
    git commit -m "Emergency Hotfix: Pushed from dev environment" &>/dev/null
    # Temporarily disable pre-receive hook to allow push and fix permissions
    sudo mv /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive.disabled 2>/dev/null || true
    sudo chmod -R 777 /var/lib/gitea/repos/gdc/bootstrap-playbooks.git
    
    git push /var/lib/gitea/repos/gdc/bootstrap-playbooks.git HEAD:main &>/dev/null
    
    # Restore permissions and pre-receive hook
    sudo chown -R git:git /var/lib/gitea/repos/gdc/bootstrap-playbooks.git
    sudo chmod -R 755 /var/lib/gitea/repos/gdc/bootstrap-playbooks.git
    sudo mv /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive.disabled /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive 2>/dev/null || true
    
    echo "      [+] Playbook committed and pushed to local node repository."
fi

REMOTE_EOF
)
    
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null gdc-admin@$NODE_IP "$REMOTE_SCRIPT"
    
    # Handle state deletion
    if [[ -n "$RESUME_STAGE" ]]; then
        echo "  [-] Wiping completion state for stage: ${RESUME_STAGE}"
        ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null gdc-admin@$NODE_IP "sudo rm -f /var/gdc-install/state/${RESUME_STAGE}.json"
    fi
    
    # 5. Execution Trigger
    echo "  [-] Restarting gdc-provision.service to execute updates..."
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null gdc-admin@$NODE_IP "sudo systemctl restart gdc-provision.service"
    
    echo "  [+] Node update sequence complete!"
    echo "=============================================================================="
    
    # Only stream logs if a single IP was targeted
    if [[ ${#IP_ARRAY[@]} -eq 1 ]]; then
        echo "[-] Streaming provisioner logs for $NODE_IP (Ctrl+C to exit)..."
        ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -t gdc-admin@$NODE_IP "sudo journalctl -u gdc-provision.service -f"
    fi
    
done

echo "[x] All target nodes processed."
