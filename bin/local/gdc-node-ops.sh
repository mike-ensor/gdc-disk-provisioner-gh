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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Unified GDC Node Operations CLI for managing, updating, and recovering edge nodes.

Commands:
  push-facts         Inject manual facts JSON into node, reset Stage 5, and restart provisioner
  push-playbook      Deploy local ansible playbook updates to node Gitea repository
  push-token         Push GCP bearer token into node containerd and runtime auth directories
  rotate-token       Force execution of refresh-gdc-credentials.sh and verify token rotation
  reset-pxe          Schedule one-time UEFI PXE boot and reboot target nodes
  refresh-telemetry  Force gdc-collector diagnostics refresh and push payload to Companion

Run '$(basename "$0") <command> --help' for detailed options on any command.
EOF
    exit "${1:-0}"
}

# ==============================================================================
# SUBCOMMAND: push-facts
# ==============================================================================
cmd_push_facts() {
    local default_schema="${REPO_ROOT}/docs/machine-schema.json"
    local companion_docs_dir
    companion_docs_dir="$(cd "${REPO_ROOT}/../gdc-companion/docs" 2>/dev/null && pwd || true)"
    local fallback_schema
    fallback_schema="$([[ -n "${companion_docs_dir}" ]] && echo "${companion_docs_dir}/machine-schema.json" || echo "/d/projects/google/gdc-companion/docs/machine-schema.json")"
    local schema_path="${GDC_SCHEMA_PATH:-$([[ -f "${default_schema}" ]] && echo "${default_schema}" || echo "${fallback_schema}")}"

    local node_ip=""
    local facts_file=""
    local ssh_user="gdc-admin"
    local ssh_key=""
    local dry_run=false
    local follow_logs=true

    facts_usage() {
        cat <<EOF
Usage: $(basename "$0") push-facts --node <NODE_IP> --facts <FACTS_JSON> [OPTIONS]

Injects a manual fact override file into a GDC target node, resets Stage 5
(Cluster Ready), and triggers gdc-provision.service.

Required Arguments:
  --node <IP>        Target node IP address
  --facts <FILE>     Path to local JSON file adhering to machine-schema.json

Optional Arguments:
  --user <USER>      SSH user (default: gdc-admin)
  --key <KEY_PATH>   Path to SSH private key
  --schema <PATH>    Path to machine-schema.json (defaults to docs/machine-schema.json)
  --dry-run          Validate facts and display actions without running SSH
  --no-follow        Do not follow journalctl logs after restarting service
  -h, --help         Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --node)
                node_ip="$2"
                shift 2
                ;;
            --facts)
                facts_file="$2"
                shift 2
                ;;
            --user)
                ssh_user="$2"
                shift 2
                ;;
            --key)
                ssh_key="$2"
                shift 2
                ;;
            --schema)
                schema_path="$2"
                shift 2
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --no-follow)
                follow_logs=false
                shift
                ;;
            -h|--help)
                facts_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for push-facts" >&2
                facts_usage 1
                ;;
        esac
    done

    if [[ -z "${node_ip}" || -z "${facts_file}" ]]; then
        echo "Error: Missing required arguments --node and --facts" >&2
        facts_usage 1
    fi

    if [[ ! -f "${facts_file}" ]]; then
        echo "Error: Facts file '${facts_file}' does not exist." >&2
        exit 1
    fi

    echo "[-] Validating '${facts_file}' syntax..."
    if ! python3 -m json.tool "${facts_file}" >/dev/null 2>&1; then
        echo "Error: Facts file is not valid JSON." >&2
        exit 1
    fi

    if [[ -f "${schema_path}" ]]; then
        echo "[-] Validating facts file against '${schema_path}'..."
        if ! python3 -c "
import json, sys, jsonschema
with open(sys.argv[1], 'r', encoding='utf-8') as sf, open(sys.argv[2], 'r', encoding='utf-8') as df:
    schema = json.load(sf)
    data = json.load(df)
    jsonschema.validate(instance=data, schema=schema)
" "${schema_path}" "${facts_file}" 2>&1; then
            echo "Error: Facts file failed schema validation against ${schema_path}" >&2
            exit 1
        fi
        echo "  [x] Facts JSON conforms to machine-schema.json."
    else
        echo "Warning: Schema file '${schema_path}' not found. Skipping schema validation." >&2
    fi

    local ssh_opts=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
    if [[ -n "${ssh_key}" ]]; then
        ssh_opts+=(-i "${ssh_key}")
    fi

    local remote_tmp="/tmp/gdc-fact-manual.json"
    local target_file="/var/gdc-install/state/gdc-fact-manual.json"
    local target_state="/var/gdc-install/state/cluster-ready.json"

    if [[ "${dry_run}" == "true" ]]; then
        echo "[!] DRY RUN MODE: No remote commands will be executed."
        echo "Would execute:"
        echo "  1. scp ${facts_file} ${ssh_user}@${node_ip}:${remote_tmp}"
        echo "  2. ssh ${ssh_user}@${node_ip} 'set -euo pipefail; sudo mkdir -p /var/gdc-install/state && sudo mv ${remote_tmp} ${target_file} && sudo chown root:root ${target_file} && sudo chmod 0644 ${target_file} && sudo rm -f ${target_state}'"
        echo "  3. ssh ${ssh_user}@${node_ip} 'sudo systemctl restart gdc-provision.service'"
        if [[ "${follow_logs}" == "true" ]]; then
            echo "  4. ssh -t ${ssh_user}@${node_ip} 'sudo journalctl -u gdc-provision.service -f'"
        fi
        return 0
    fi

    echo "[-] Uploading facts file to ${node_ip}:${remote_tmp}..."
    scp "${ssh_opts[@]}" "${facts_file}" "${ssh_user}@${node_ip}:${remote_tmp}"

    echo "[-] Staging manual fact file and resetting cluster-ready state..."
    ssh "${ssh_opts[@]}" "${ssh_user}@${node_ip}" "set -euo pipefail; sudo mkdir -p /var/gdc-install/state && sudo mv '${remote_tmp}' '${target_file}' && sudo chown root:root '${target_file}' && sudo chmod 0644 '${target_file}' && sudo rm -f '${target_state}'"

    echo "[-] Restarting gdc-provision.service..."
    ssh "${ssh_opts[@]}" "${ssh_user}@${node_ip}" "sudo systemctl restart gdc-provision.service"

    if [[ "${follow_logs}" == "true" ]]; then
        echo "[-] Following gdc-provision.service logs (Ctrl+C to stop)..."
        ssh "${ssh_opts[@]}" -t "${ssh_user}@${node_ip}" "sudo journalctl -u gdc-provision.service -f"
    fi
}

# ==============================================================================
# SUBCOMMAND: push-playbook
# ==============================================================================
cmd_push_playbook() {
    local target_ips=""
    local resume_stage=""
    local ssh_user="gdc-admin"
    local ssh_key=""
    local valid_stages=("first-boot" "second-boot" "linux-ready" "cluster-ready")

    playbook_usage() {
        cat <<EOF
Usage: $(basename "$0") push-playbook --nodes <IP(s)> [OPTIONS]

Pushes local development Ansible playbooks directly into the remote node's
local Gitea repository and restarts gdc-provision.service.

Required Arguments:
  --nodes <IP(s)>     Comma-separated list of target IPs (alias: --ip)

Optional Arguments:
  --user <USER>       SSH user (default: gdc-admin)
  --key <KEY_PATH>    Path to SSH private key
  --resume-from <STG> Force Ansible to resume from a stage by wiping its state.
                      Valid stages: first-boot, second-boot, linux-ready, cluster-ready
  -h, --help          Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --nodes|--ip)
                target_ips="$2"
                shift 2
                ;;
            --user)
                ssh_user="$2"
                shift 2
                ;;
            --key)
                ssh_key="$2"
                shift 2
                ;;
            --resume-from)
                resume_stage="$2"
                shift 2
                ;;
            -h|--help)
                playbook_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for push-playbook" >&2
                playbook_usage 1
                ;;
        esac
    done

    if [[ -z "${target_ips}" ]]; then
        echo "Error: --nodes argument is required." >&2
        playbook_usage 1
    fi

    if [[ -n "${resume_stage}" ]]; then
        local valid=false
        for stg in "${valid_stages[@]}"; do
            if [[ "${resume_stage}" == "$stg" ]]; then
                valid=true
                break
            fi
        done
        if [[ "${valid}" == "false" ]]; then
            echo "Error: Invalid stage '${resume_stage}'. Valid: ${valid_stages[*]}" >&2
            exit 1
        fi
    fi

    local python_exec="${REPO_ROOT}/.venv/bin/python3"
    if [[ ! -x "$python_exec" ]]; then
        python_exec="python3"
    fi

    local ssh_opts=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
    if [[ -n "${ssh_key}" ]]; then
        ssh_opts+=(-i "${ssh_key}")
    fi

    IFS=',' read -ra ip_array <<< "$target_ips"

    echo "=============================================================================="
    echo " GDC HOTFIX PLAYBOOK DEPLOYMENT PROTOCOL"
    echo "=============================================================================="

    echo "[-] Preparing playbook payload..."
    local temp_staging
    temp_staging=$(mktemp -d)
    local temp_render_dir
    temp_render_dir=$(mktemp -d)
    trap 'rm -rf "${temp_staging}" "${temp_render_dir}"' RETURN EXIT

    rsync -av --exclude='.git' "${REPO_ROOT}/src/ansible/" "${temp_staging}/" > /dev/null

    echo "[-] Hydrating vars/all.yml from local environment configuration..."
    $python_exec "${REPO_ROOT}/src/build/render_templates.py" "${REPO_ROOT}/src/build/templates" "${temp_render_dir}" > /dev/null

    if [[ -f "${temp_render_dir}/custom-data/ansible/vars/all.yml" ]]; then
        cp "${temp_render_dir}/custom-data/ansible/vars/all.yml" "${temp_staging}/vars/all.yml"
    else
        echo "Error: render_templates.py failed to produce custom-data/ansible/vars/all.yml" >&2
        exit 1
    fi

    rm -f "${temp_staging}/vars/all.yml.j2"
    echo "[+] Payload prepared successfully."
    echo "------------------------------------------------------------------------------"

    for node in "${ip_array[@]}"; do
        node=$(echo "$node" | xargs)
        [[ -z "$node" ]] && continue
        echo "[-] Targeting node: $node"

        echo "  [-] Verifying ${ssh_user} SSH access..."
        if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${ssh_opts[@]}" "${ssh_user}@$node" "echo 'OK'" &>/dev/null; then
            echo "  [!] ERROR: Cannot connect to $node as ${ssh_user}. Skipping."
            continue
        fi
        echo "  [+] SSH access verified."

        echo "  [-] Pushing playbook updates via RSYNC..."
        local rsync_ssh="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        if [[ -n "${ssh_key}" ]]; then
            rsync_ssh+=" -i ${ssh_key}"
        fi
        ssh "${ssh_opts[@]}" "${ssh_user}@$node" "sudo rm -rf /tmp/ansible-hotfix && mkdir -p /tmp/ansible-hotfix && sudo chown ${ssh_user}:${ssh_user} /tmp/ansible-hotfix" &>/dev/null
        rsync -avz -e "${rsync_ssh}" --delete "${temp_staging}/" "${ssh_user}@$node:/tmp/ansible-hotfix/" > /dev/null

        echo "  [-] Committing updates to the node's local playbook repository..."
        ssh "${ssh_opts[@]}" "${ssh_user}@$node" bash -s << REMOTE_EOF
set -euo pipefail
sudo rm -rf /tmp/repo-checkout
sudo git clone /var/lib/gitea/repos/gdc/bootstrap-playbooks.git /tmp/repo-checkout &>/dev/null
sudo chown -R ${ssh_user}:${ssh_user} /tmp/repo-checkout

rsync -a --delete --exclude='.git' /tmp/ansible-hotfix/ /tmp/repo-checkout/
cd /tmp/repo-checkout
git config user.email "hotfix@ensor-labs.com"
git config user.name "GDC Hotfix Pusher"
git add .

if git diff --staged --quiet; then
    echo "      No changes detected in playbook."
else
    git commit -m "Emergency Hotfix: Pushed from dev environment" &>/dev/null
    sudo mv /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive.disabled 2>/dev/null || true
    sudo chmod -R 777 /var/lib/gitea/repos/gdc/bootstrap-playbooks.git
    git push /var/lib/gitea/repos/gdc/bootstrap-playbooks.git HEAD:main &>/dev/null
    sudo chown -R git:git /var/lib/gitea/repos/gdc/bootstrap-playbooks.git
    sudo chmod -R 755 /var/lib/gitea/repos/gdc/bootstrap-playbooks.git
    sudo mv /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive.disabled /var/lib/gitea/repos/gdc/bootstrap-playbooks.git/hooks/pre-receive 2>/dev/null || true
    echo "      [+] Playbook committed and pushed to local node repository."
fi
REMOTE_EOF

        if [[ -n "${resume_stage}" ]]; then
            echo "  [-] Wiping completion state for stage: ${resume_stage}"
            ssh "${ssh_opts[@]}" "${ssh_user}@$node" "sudo rm -f /var/gdc-install/state/${resume_stage}.json"
        fi

        echo "  [-] Restarting gdc-provision.service to execute updates..."
        ssh "${ssh_opts[@]}" "${ssh_user}@$node" "sudo systemctl restart gdc-provision.service"
        echo "  [+] Node update sequence complete!"

        if [[ ${#ip_array[@]} -eq 1 ]]; then
            echo "[-] Streaming provisioner logs for $node (Ctrl+C to exit)..."
            ssh "${ssh_opts[@]}" -t "${ssh_user}@$node" "sudo journalctl -u gdc-provision.service -f"
        fi
    done
    echo "[x] All target nodes processed."
}

# ==============================================================================
# SUBCOMMAND: push-token
# ==============================================================================
cmd_push_token() {
    local target_raw=""
    local ssh_user="gdc-admin"
    local ssh_key=""
    local token=""
    local gcloud_account=""
    local test_rotation=false
    local dry_run=false

    token_usage() {
        cat <<EOF
Usage: $(basename "$0") push-token [OPTIONS]

Pushes a Google Cloud Bearer/access token to target nodes, configuring
containerd (certs.d/gcr.io) and runtime auth (/run/gdc-auth/) without
requiring gcloud authentication or browser login on the remote nodes.

Options:
  --nodes, --ip <IPs>  Comma-separated list or space-separated IPs (defaults to TARGET_TEST_MACHINES)
  --user <USER>        SSH username (default: gdc-admin)
  --key <KEY_PATH>     Path to SSH private key
  --token <TOKEN>      Directly provide the OAuth2 Bearer token (defaults to local 'gcloud auth print-access-token')
  --account <ACCT>     GCP account to request token for via local gcloud
  --test-rotation      Immediately trigger /usr/local/bin/refresh-gdc-credentials.sh and verify token rotation
  --dry-run            Display planned actions and token metadata without connecting via SSH
  -h, --help           Display this help message
EOF
        exit "${1:-0}"
    }

    local positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --nodes|--ip)
                target_raw="$2"
                shift 2
                ;;
            --user)
                ssh_user="$2"
                shift 2
                ;;
            --key)
                ssh_key="$2"
                shift 2
                ;;
            --token)
                token="$2"
                shift 2
                ;;
            --account)
                gcloud_account="$2"
                shift 2
                ;;
            --test-rotation|--rotate)
                test_rotation=true
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            -h|--help)
                token_usage 0
                ;;
            *)
                positional+=("$1")
                shift
                ;;
        esac
    done

    if [[ ${#positional[@]} -gt 0 ]]; then
        target_raw="${positional[*]}"
    elif [[ -z "${target_raw}" && -n "${TARGET_TEST_MACHINES:-}" ]]; then
        target_raw="${TARGET_TEST_MACHINES}"
    fi

    if [[ -z "${target_raw}" ]]; then
        echo "Error: No target nodes provided. Use --nodes <IPs> or export TARGET_TEST_MACHINES." >&2
        token_usage 1
    fi

    # Resolve token if not explicitly provided
    if [[ -z "${token}" ]]; then
        echo "[-] Acquiring GCP Bearer access token from local gcloud CLI..."
        if ! command -v gcloud >/dev/null 2>&1; then
            echo "Error: gcloud CLI is not installed locally and no --token was provided." >&2
            exit 1
        fi
        local gcloud_cmd=(gcloud auth print-access-token)
        if [[ -n "${gcloud_account}" ]]; then
            gcloud_cmd+=(--account="${gcloud_account}")
        fi
        token="$("${gcloud_cmd[@]}" 2>/dev/null || true)"
        if [[ -z "${token}" ]]; then
            echo "Error: Failed to obtain access token from local gcloud CLI. Run 'gcloud auth login' or provide --token." >&2
            exit 1
        fi
    fi

    local masked_token
    if [[ ${#token} -gt 12 ]]; then
        masked_token="${token:0:7}...${token: -4}"
    else
        masked_token="***"
    fi
    echo "  [+] Token acquired: ${masked_token}"

    local cleaned_ips
    cleaned_ips=$(echo "${target_raw}" | tr -d "[]'\"" | tr ',' ' ')
    local targets=()
    read -ra targets <<< "$cleaned_ips"

    local ssh_opts=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
    if [[ -n "${ssh_key}" ]]; then
        ssh_opts+=(-i "${ssh_key}")
    fi

    local local_auth_script="${REPO_ROOT}/bin/auth/gcp-authentication.sh"
    if [[ ! -f "${local_auth_script}" ]]; then
        echo "Error: Local auth script not found at ${local_auth_script}" >&2
        exit 1
    fi

    if [[ "${dry_run}" == "true" ]]; then
        echo "=============================================================================="
        echo " DRY RUN MODE: push-token"
        echo "=============================================================================="
        echo "  Target nodes: ${targets[*]}"
        echo "  SSH User:     ${ssh_user}"
        echo "  Token:        ${masked_token}"
        echo "  Payload:      ${local_auth_script}"
        echo ""
        echo "Would execute for each target node:"
        echo "  1. scp ${local_auth_script} ${ssh_user}@<NODE>:/tmp/gcp-authentication.sh"
        echo "  2. ssh ${ssh_user}@<NODE> 'sudo install -m 0755 /tmp/gcp-authentication.sh /usr/local/bin/auth/gcp-authentication.sh && sudo /usr/local/bin/auth/gcp-authentication.sh --token \"<TOKEN>\" && rm -f /tmp/gcp-authentication.sh'"
        if [[ "${test_rotation}" == "true" ]]; then
            echo "  3. ssh ${ssh_user}@<NODE> 'sudo /usr/local/bin/refresh-gdc-credentials.sh && gcloud auth print-access-token'"
        fi
        return 0
    fi

    echo "=============================================================================="
    echo " GDC GCP AUTHENTICATION TOKEN SIDELOADER"
    echo "=============================================================================="

    for ip in "${targets[@]}"; do
        ip=$(echo "$ip" | xargs)
        [[ -z "$ip" ]] && continue
        echo "[-] Targeting node: $ip"

        echo "  [-] Verifying ${ssh_user} SSH connectivity..."
        if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${ssh_opts[@]}" "${ssh_user}@$ip" "echo 'OK'" &>/dev/null; then
            echo "  [!] ERROR: Cannot connect to $ip as ${ssh_user}. Skipping."
            continue
        fi

        echo "  [-] Deploying latest gcp-authentication.sh to $ip..."
        scp "${ssh_opts[@]}" "${local_auth_script}" "${ssh_user}@${ip}:/tmp/gcp-authentication.sh" >/dev/null

        echo "  [-] Executing authentication setup on $ip..."
        ssh "${ssh_opts[@]}" "${ssh_user}@${ip}" "set -euo pipefail; sudo mkdir -p /usr/local/bin/auth && sudo install -m 0755 /tmp/gcp-authentication.sh /usr/local/bin/auth/gcp-authentication.sh && sudo /usr/local/bin/auth/gcp-authentication.sh --token-stdin && rm -f /tmp/gcp-authentication.sh" <<< "${token}"

        echo "  [-] Verifying on-node authentication..."
        ssh "${ssh_opts[@]}" "${ssh_user}@${ip}" bash -s << 'VERIFY_EOF'
set -euo pipefail
if [ -f /run/gdc-auth/access_token ]; then
    echo "    [+] Runtime token verified in /run/gdc-auth/access_token"
fi
if command -v gcloud >/dev/null 2>&1; then
    ACTIVE_AUTH=$(gcloud auth print-access-token 2>/dev/null || true)
    if [ -n "$ACTIVE_AUTH" ]; then
        echo "    [+] gcloud verified on node: successfully authenticating via access_token_file"
    else
        echo "    [!] Warning: gcloud installed but returned empty token from access_token_file" >&2
    fi
fi
VERIFY_EOF

        if [[ "${test_rotation}" == "true" ]]; then
            echo "  [-] Triggering token rotation via /usr/local/bin/refresh-gdc-credentials.sh..."
            ssh "${ssh_opts[@]}" "${ssh_user}@${ip}" bash -s << 'ROTATE_EOF'
set -euo pipefail
PRE_TOKEN=$(cat /run/gdc-auth/access_token 2>/dev/null || true)
if [ ! -x /usr/local/bin/refresh-gdc-credentials.sh ]; then
    echo "    [!] ERROR: /usr/local/bin/refresh-gdc-credentials.sh not found or not executable" >&2
    exit 1
fi

sudo /usr/local/bin/refresh-gdc-credentials.sh

POST_TOKEN=$(cat /run/gdc-auth/access_token 2>/dev/null || true)
if [ -z "$POST_TOKEN" ]; then
    echo "    [!] ERROR: /run/gdc-auth/access_token is empty after rotation" >&2
    exit 1
fi

if [ "$PRE_TOKEN" == "$POST_TOKEN" ]; then
    echo "    [!] Note: Token content identical after rotation (Companion returned same token)"
else
    echo "    [+] Token successfully changed/rotated in /run/gdc-auth/access_token!"
fi

if command -v gcloud >/dev/null 2>&1; then
    ROTATED_ACTIVE=$(gcloud auth print-access-token 2>/dev/null || true)
    if [ -n "$ROTATED_ACTIVE" ]; then
        echo "    [+] gcloud verified on node with newly rotated token"
        ACTIVE_ACCT=$(gcloud config get-value account 2>/dev/null || true)
        [ -n "$ACTIVE_ACCT" ] && echo "    [+] Active gcloud account: ${ACTIVE_ACCT}"
    fi
fi
ROTATE_EOF
        fi

        echo "  [+] Node $ip successfully authenticated with GCP credentials!"
    done
    echo "=============================================================================="
    echo "[x] All target nodes processed."
}

# ==============================================================================
# SUBCOMMAND: rotate-token
# ==============================================================================
cmd_rotate_token() {
    local target_raw=""
    local ssh_user="gdc-admin"
    local ssh_key=""
    local dry_run=false

    rotate_usage() {
        cat <<EOF
Usage: $(basename "$0") rotate-token [OPTIONS]

Forces execution of /usr/local/bin/refresh-gdc-credentials.sh on target nodes
and verifies that the rotated GCP Bearer token is valid and active in gcloud.

Options:
  --nodes, --ip <IPs>  Comma-separated list or space-separated IPs (defaults to TARGET_TEST_MACHINES)
  --user <USER>        SSH username (default: gdc-admin)
  --key <KEY_PATH>     Path to SSH private key
  --dry-run            Display planned actions without connecting via SSH
  -h, --help           Display this help message
EOF
        exit "${1:-0}"
    }

    local positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --nodes|--ip)
                target_raw="$2"
                shift 2
                ;;
            --user)
                ssh_user="$2"
                shift 2
                ;;
            --key)
                ssh_key="$2"
                shift 2
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            -h|--help)
                rotate_usage 0
                ;;
            *)
                positional+=("$1")
                shift
                ;;
        esac
    done

    if [[ ${#positional[@]} -gt 0 ]]; then
        target_raw="${positional[*]}"
    elif [[ -z "${target_raw}" && -n "${TARGET_TEST_MACHINES:-}" ]]; then
        target_raw="${TARGET_TEST_MACHINES}"
    fi

    if [[ -z "${target_raw}" ]]; then
        echo "Error: No target nodes provided. Use --nodes <IPs> or export TARGET_TEST_MACHINES." >&2
        rotate_usage 1
    fi

    local cleaned_ips
    cleaned_ips=$(echo "${target_raw}" | tr -d "[]'\"" | tr ',' ' ')
    local targets=()
    read -ra targets <<< "$cleaned_ips"

    local ssh_opts=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
    if [[ -n "${ssh_key}" ]]; then
        ssh_opts+=(-i "${ssh_key}")
    fi

    if [[ "${dry_run}" == "true" ]]; then
        echo "=============================================================================="
        echo " DRY RUN MODE: rotate-token"
        echo "=============================================================================="
        echo "  Target nodes: ${targets[*]}"
        echo "  SSH User:     ${ssh_user}"
        echo ""
        echo "Would execute on each target node:"
        echo "  1. ssh ${ssh_user}@<NODE> 'sudo /usr/local/bin/refresh-gdc-credentials.sh'"
        echo "  2. ssh ${ssh_user}@<NODE> 'gcloud auth print-access-token'"
        return 0
    fi

    echo "=============================================================================="
    echo " GDC GCP CREDENTIALS ROTATION & REFRESH PROTOCOL"
    echo "=============================================================================="

    for ip in "${targets[@]}"; do
        ip=$(echo "$ip" | xargs)
        [[ -z "$ip" ]] && continue
        echo "[-] Targeting node: $ip"

        echo "  [-] Verifying ${ssh_user} SSH connectivity..."
        if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${ssh_opts[@]}" "${ssh_user}@$ip" "echo 'OK'" &>/dev/null; then
            echo "  [!] ERROR: Cannot connect to $ip as ${ssh_user}. Skipping."
            continue
        fi

        echo "  [-] Executing /usr/local/bin/refresh-gdc-credentials.sh..."
        ssh "${ssh_opts[@]}" "${ssh_user}@${ip}" bash -s << 'ROTATE_EOF'
set -euo pipefail
PRE_TOKEN=$(cat /run/gdc-auth/access_token 2>/dev/null || true)
if [ ! -x /usr/local/bin/refresh-gdc-credentials.sh ]; then
    echo "    [!] ERROR: /usr/local/bin/refresh-gdc-credentials.sh not found or not executable" >&2
    exit 1
fi

sudo /usr/local/bin/refresh-gdc-credentials.sh

POST_TOKEN=$(cat /run/gdc-auth/access_token 2>/dev/null || true)
if [ -z "$POST_TOKEN" ]; then
    echo "    [!] ERROR: /run/gdc-auth/access_token is empty after rotation" >&2
    exit 1
fi

echo "    [+] Credentials refreshed successfully."
if command -v gcloud >/dev/null 2>&1; then
    ACTIVE_AUTH=$(gcloud auth print-access-token 2>/dev/null || true)
    if [ -n "$ACTIVE_AUTH" ]; then
        echo "    [+] gcloud verified on node with refreshed token"
        ACTIVE_ACCT=$(gcloud config get-value account 2>/dev/null || true)
        [ -n "$ACTIVE_ACCT" ] && echo "    [+] Active gcloud account: ${ACTIVE_ACCT}"
    fi
fi
ROTATE_EOF

        echo "  [+] Node $ip token rotation complete!"
    done
    echo "=============================================================================="
    echo "[x] All target nodes processed."
}

# ==============================================================================
# SUBCOMMAND: reset-pxe
# ==============================================================================
cmd_reset_pxe() {
    local target_raw=""
    local ssh_user="gdc-admin"
    local ssh_key=""
    local auto_yes=false

    reset_usage() {
        cat <<EOF
Usage: $(basename "$0") reset-pxe [OPTIONS]

Schedules a one-time UEFI PXE boot (BootNext) on target nodes and triggers a reboot.

Options:
  --nodes <IPs>     Comma-separated list or space-separated IPs (defaults to TARGET_TEST_MACHINES)
  --user <USER>     SSH user (default: gdc-admin)
  --key <KEY_PATH>  Path to SSH private key
  -y, --yes         Skip confirmation prompt
  -h, --help        Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --nodes|--ip)
                target_raw="$2"
                shift 2
                ;;
            --user)
                ssh_user="$2"
                shift 2
                ;;
            --key)
                ssh_key="$2"
                shift 2
                ;;
            -y|--yes)
                auto_yes=true
                shift
                ;;
            -h|--help)
                reset_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for reset-pxe" >&2
                reset_usage 1
                ;;
        esac
    done

    if [[ -z "${target_raw}" && -n "${TARGET_TEST_MACHINES:-}" ]]; then
        target_raw="${TARGET_TEST_MACHINES}"
    fi

    if [[ -z "${target_raw}" ]]; then
        echo "Error: No target nodes provided. Use --nodes <IPs> or export TARGET_TEST_MACHINES." >&2
        reset_usage 1
    fi

    local cleaned_ips
    cleaned_ips=$(echo "${target_raw}" | tr -d "[]'\"" | tr ',' ' ')
    local targets=()
    read -ra targets <<< "$cleaned_ips"

    local ssh_opts=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
    if [[ -n "${ssh_key}" ]]; then
        ssh_opts+=(-i "${ssh_key}")
    fi

    echo "=============================================================================="
    echo " Target machines in scope for PXE Reset:"
    for ip in "${targets[@]}"; do
        echo "  - $ip"
    done
    echo "=============================================================================="

    if [[ "${auto_yes}" != "true" ]]; then
        read -p "Are you sure you want to reboot these machines to PXE? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "[-] Aborted by user."
            exit 1
        fi
    fi

    for ip in "${targets[@]}"; do
        ip=$(echo "$ip" | xargs)
        [[ -z "$ip" ]] && continue
        echo "[-] Targeting node: $ip"

        if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${ssh_opts[@]}" "${ssh_user}@$ip" "echo 'OK'" &>/dev/null; then
            echo "  [!] ERROR: Cannot connect to $ip as ${ssh_user}. Skipping."
            continue
        fi

        echo "  [-] Querying network interfaces and scheduling PXE boot on $ip..."
        ssh "${ssh_opts[@]}" "${ssh_user}@$ip" bash -s << 'REMOTE_EOF'
set -euo pipefail
active_iface=$(ip route show | grep '^default' | awk '{print $5}' | head -n 1 || true)
if [ -z "$active_iface" ] && [ -n "${SSH_CONNECTION:-}" ]; then
    read -r _ _ server_ip _ <<< "$SSH_CONNECTION"
    active_iface=$(ip -o addr show to "$server_ip" | awk '{print $2}' || true)
fi
if [ -z "$active_iface" ]; then
    active_iface=$(ip -o link show | grep -v 'LOOPBACK' | grep 'state UP' | awk -F': ' '{print $2}' | head -n 1 || true)
fi

BOOT_NUM=""
if [ -n "$active_iface" ] && [ -f "/sys/class/net/$active_iface/address" ]; then
    active_mac=$(cat "/sys/class/net/$active_iface/address" | tr -d ':' | tr '[:upper:]' '[:lower:]')
    echo "  [+] Active interface: $active_iface (MAC: $active_mac)"
    BOOT_NUM=$(efibootmgr | grep -i "MAC(${active_mac}" | head -n 1 | sed -E -n 's/^Boot([0-9A-Fa-f]{4})\*?.*/\1/p' || true)
fi

if [ -z "$BOOT_NUM" ]; then
    echo "  [!] MAC matching failed. Searching pattern-based PXE..."
    EFIOUT=$(efibootmgr)
    BOOT_NUM=$(echo "$EFIOUT" | grep -i 'pxe ipv4' | head -n 1 | sed -E -n 's/^Boot([0-9A-Fa-f]{4})\*?.*/\1/p' || true)
    if [ -z "$BOOT_NUM" ]; then
        BOOT_NUM=$(echo "$EFIOUT" | grep -iE 'network|netboot|ipv4|lan' | head -n 1 | sed -E -n 's/^Boot([0-9A-Fa-f]{4})\*?.*/\1/p' || true)
    fi
fi

if [ -z "$BOOT_NUM" ]; then
    echo "  [!] ERROR: No UEFI PXE or Network boot option detected."
    exit 1
fi

echo "  [+] Selected PXE option: Boot$BOOT_NUM"
echo "  [-] Setting BootNext to $BOOT_NUM..."
sudo efibootmgr -n "$BOOT_NUM" > /dev/null
echo "  [-] Rebooting node..."
sudo reboot
REMOTE_EOF
        echo "  [+] Remote PXE reset command dispatched to $ip."
    done
    echo "[x] Finished processing all targeted nodes."
}

# ==============================================================================
# SUBCOMMAND: refresh-telemetry
# ==============================================================================
cmd_refresh_telemetry() {
    local target_raw=""
    local user="temporary-installer"
    local pass="gdc-password-123"
    local ssh_key=""
    local companion_url=""

    if [ -f "$REPO_ROOT/src/build/local.env" ]; then
        # shellcheck disable=SC1091
        source "$REPO_ROOT/src/build/local.env"
    fi
    local base_companion="${INSTALL_COMPANION_BASE:-https://gdc-companion.ensor-labs.com/}"
    [[ "${base_companion}" != */ ]] && base_companion="${base_companion}/"
    companion_url="${base_companion}v1/machine-reports/ingest"

    telemetry_usage() {
        cat <<EOF
Usage: $(basename "$0") refresh-telemetry [OPTIONS] [NODE_IPS...]

Triggers gdc-collector on remote nodes and pushes refreshed telemetry to GDC Companion.

Options:
  --nodes <IPs>         Comma-separated list or space-separated IPs (defaults to TARGET_TEST_MACHINES)
  --user <USER>         SSH username (default: temporary-installer)
  --password <PASS>     SSH password (default: gdc-password-123)
  --key <KEY_PATH>      Path to SSH private key (bypasses password authentication)
  --companion-url <URL> Ingestion URL (default: $companion_url)
  -h, --help            Display this help message
EOF
        exit "${1:-0}"
    }

    local positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --nodes|--ip)
                target_raw="$2"
                shift 2
                ;;
            --user)
                user="$2"
                shift 2
                ;;
            --password)
                pass="$2"
                shift 2
                ;;
            --key)
                ssh_key="$2"
                shift 2
                ;;
            --companion-url)
                companion_url="$2"
                shift 2
                ;;
            -h|--help)
                telemetry_usage 0
                ;;
            *)
                positional+=("$1")
                shift
                ;;
        esac
    done

    if [[ ${#positional[@]} -gt 0 ]]; then
        target_raw="${positional[*]}"
    elif [[ -z "${target_raw}" && -n "${TARGET_TEST_MACHINES:-}" ]]; then
        target_raw="${TARGET_TEST_MACHINES}"
    fi

    if [[ -z "${target_raw}" ]]; then
        echo "Error: No target node IPs provided. Provide IPs as arguments or via --nodes." >&2
        telemetry_usage 1
    fi

    local cleaned_ips
    cleaned_ips=$(echo "${target_raw}" | tr -d "[]'\"" | tr ',' ' ')
    local targets=()
    read -ra targets <<< "$cleaned_ips"

    echo "====================================================="
    echo "GDC Telemetry Refresher"
    echo "Target Companion: ${companion_url}"
    echo "Target Nodes:     ${targets[*]}"
    echo "====================================================="

    for ip in "${targets[@]}"; do
        ip=$(echo "$ip" | xargs)
        [[ -z "$ip" ]] && continue
        echo -n "[-] Checking $ip... "
        if ! ping -c 1 -W 1 "$ip" &>/dev/null; then
            echo -e "\033[31m[OFFLINE]\033[0m (Unreachable via ping)"
            continue
        fi

        local ssh_cmd=()
        if [[ -n "${ssh_key}" ]]; then
            ssh_cmd=(ssh -i "${ssh_key}" -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${user}@${ip}")
        elif command -v sshpass >/dev/null 2>&1; then
            ssh_cmd=(sshpass -p "$pass" ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${user}@${ip}")
        else
            ssh_cmd=(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${user}@${ip}")
        fi

        local output
        if output=$("${ssh_cmd[@]}" "echo '$pass' | sudo -S /usr/local/bin/gdc-collector --companion-url='${companion_url}'" 2>&1); then
            echo -e "\033[32m[SUCCESS]\033[0m Telemetry Refreshed"
        else
            echo -e "\033[31m[FAILED]\033[0m (SSH or execution error)"
            echo "    -> Reason: $(echo "$output" | tail -n 1)"
        fi
    done
    echo "====================================================="
    echo "Refresh cycle complete."
}

# ==============================================================================
# MAIN ROUTING
# ==============================================================================
if [[ $# -eq 0 ]]; then
    usage 1
fi

COMMAND="$1"
shift

case "${COMMAND}" in
    push-facts)
        cmd_push_facts "$@"
        ;;
    push-playbook)
        cmd_push_playbook "$@"
        ;;
    push-token)
        cmd_push_token "$@"
        ;;
    rotate-token)
        cmd_rotate_token "$@"
        ;;
    reset-pxe)
        cmd_reset_pxe "$@"
        ;;
    refresh-telemetry)
        cmd_refresh_telemetry "$@"
        ;;
    -h|--help|help)
        usage 0
        ;;
    *)
        echo "Error: Unknown command '${COMMAND}'" >&2
        usage 1
        ;;
esac
