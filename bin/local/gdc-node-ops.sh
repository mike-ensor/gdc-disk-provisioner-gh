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
  pull-profile       Pull or list ISO environment profiles from GDC Companion
  push-facts         Inject manual facts JSON into node, reset Stage 5, and restart provisioner
  push-playbook      Deploy local ansible playbook updates to node Gitea repository
  push-token         Push GCP bearer token into node containerd and runtime auth directories
  rotate-token       Force execution of refresh-gdc-credentials.sh and verify token rotation
  reset-pxe          Schedule one-time UEFI PXE boot and reboot target nodes
  rebuild-cycle      Run full rebuild cycle: pull-profile -> build.sh -> bootimus -> reset-pxe
  refresh-telemetry  Force gdc-collector diagnostics refresh and push payload to Companion
  create-fallback-ca Generate self-signed fallback Sub-CA and upload to Secret Manager

Run '$(basename "$0") <command> --help' for detailed options on any command.
EOF
    exit "${1:-0}"
}

# ==============================================================================
# SUBCOMMAND: pull-profile
# ==============================================================================
cmd_pull_profile() {
    local profile_name=""
    local companion_url=""
    local api_key=""
    local force_list=false

    # Capture incoming process environment variables before sourcing local.env
    local env_companion_base="${INSTALL_COMPANION_BASE:-}"
    local env_companion_api_key="${INSTALL_COMPANION_API_KEY:-}"

    if [ -f "$REPO_ROOT/src/build/local.env" ]; then
        # shellcheck disable=SC1091
        source "$REPO_ROOT/src/build/local.env"
    fi

    # Precedence: process env > local.env > default
    local resolved_base="${env_companion_base:-${INSTALL_COMPANION_BASE:-https://gdc-companion.gdc-labs.com/}}"
    local resolved_api_key="${env_companion_api_key:-${INSTALL_COMPANION_API_KEY:-}}"

    pull_profile_usage() {
        cat <<EOF
Usage: $(basename "$0") pull-profile [OPTIONS]

Pull down or list centralized ISO environment profiles hosted in GDC Companion.

Options:
  --name <NAME>         Name of the ISO profile to pull (e.g. honeywell, barn, local)
  --companion-url <URL> Base URL of GDC Companion (default: ${resolved_base})
  --api-key <KEY>       API key for GDC Companion authentication
  --list                List available profiles without pulling
  -h, --help            Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --name)
                if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
                    echo "Error: Missing value for $1" >&2
                    pull_profile_usage 1
                fi
                profile_name="$2"
                shift 2
                ;;
            --companion-url)
                if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
                    echo "Error: Missing value for $1" >&2
                    pull_profile_usage 1
                fi
                companion_url="$2"
                shift 2
                ;;
            --api-key)
                if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
                    echo "Error: Missing value for $1" >&2
                    pull_profile_usage 1
                fi
                api_key="$2"
                shift 2
                ;;
            --list)
                force_list=true
                shift
                ;;
            -h|--help)
                pull_profile_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for pull-profile" >&2
                pull_profile_usage 1
                ;;
        esac
    done

    # Precedence: CLI flag > process env / local.env / default
    companion_url="${companion_url:-$resolved_base}"
    api_key="${api_key:-$resolved_api_key}"
    [[ "${companion_url}" != */ ]] && companion_url="${companion_url}/"

    local auth_header=()
    if [[ -n "${api_key}" ]]; then
        auth_header=(-H "X-API-Key: ${api_key}")
    fi

    if [[ -z "${profile_name}" || "${force_list}" == "true" ]]; then
        echo "[-] Fetching available ISO profiles from ${companion_url}v1/iso-profiles..."
        local response_body=""
        local http_code="000"
        local json_payload=""

        if command -v curl >/dev/null 2>&1; then
            response_body=$(curl -sS --connect-timeout 10 -w "\n%{http_code}" ${auth_header[@]+"${auth_header[@]}"} "${companion_url}v1/iso-profiles" 2>/dev/null || true)
            http_code=$(echo "${response_body}" | tail -n1)
            http_code="${http_code:-000}"
            json_payload=$(echo "${response_body}" | sed '$d')
        elif command -v python3 >/dev/null 2>&1; then
            local py_script='
import sys, urllib.request, urllib.error
url = sys.argv[1]
key = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
req = urllib.request.Request(url)
if key:
    req.add_header("X-API-Key", key)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        sys.stdout.write(r.read().decode("utf-8", errors="replace"))
        sys.stderr.write(f"\n{r.status}\n")
except urllib.error.HTTPError as e:
    sys.stderr.write(f"\n{e.code}\n")
except Exception:
    sys.stderr.write("\n000\n")
'
            local py_err_tmp
            py_err_tmp=$(mktemp)
            json_payload=$(python3 -c "${py_script}" "${companion_url}v1/iso-profiles" "${api_key}" 2>"${py_err_tmp}" || true)
            http_code=$(grep -E '^[0-9]{3}$' "${py_err_tmp}" | tail -n1 || echo "000")
            http_code="${http_code:-000}"
            rm -f "${py_err_tmp}"
        else
            echo "[!] Error: Neither 'curl' nor 'python3' is available to query GDC Companion." >&2
            exit 1
        fi

        if [[ "${http_code}" != "200" ]]; then
            echo "[!] Error: Failed to fetch profile listing from GDC Companion (HTTP ${http_code})." >&2
            exit 1
        fi

        echo ""
        echo "AVAILABLE ISO PROFILES (${companion_url}):"
        printf "%-20s %-20s %-12s %s\n" "NAME" "NETWORK SEGMENT" "OVERRIDES" "LAST UPDATED"
        echo "--------------------------------------------------------------------------------"

        local count=0
        if command -v jq >/dev/null 2>&1; then
            while IFS=$'\t' read -r p_name p_segment p_count p_updated; do
                [[ -z "${p_name}" ]] && continue
                printf "%-20s %-20s %-12s %s\n" "${p_name}" "${p_segment}" "${p_count}" "${p_updated}"
                count=$((count + 1))
            done < <(echo "${json_payload}" | jq -r '.[] | [ .name, .network_segment, (.override_count|tostring), (.updated_at // "N/A") ] | @tsv')
        elif command -v python3 >/dev/null 2>&1; then
            while IFS=$'\t' read -r p_name p_segment p_count p_updated; do
                [[ -z "${p_name}" ]] && continue
                printf "%-20s %-20s %-12s %s\n" "${p_name}" "${p_segment}" "${p_count}" "${p_updated}"
                count=$((count + 1))
            done < <(echo "${json_payload}" | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    for p in data:
        print("\t".join([str(p.get("name","")), str(p.get("network_segment","")), str(p.get("override_count","")), str(p.get("updated_at") or "N/A")]))
except Exception:
    pass
')
        else
            echo "${json_payload}"
        fi

        echo ""
        echo "Total profiles found: ${count}"
        echo "To pull a profile: $(basename "$0") pull-profile --name <name>"
        exit 0
    fi

    # Validate profile name
    if [[ ! "${profile_name}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        echo "[!] Error: Invalid profile name '${profile_name}'. Must contain only alphanumeric characters, dashes, and underscores." >&2
        exit 1
    fi

    local target_file="${REPO_ROOT}/src/build/${profile_name}.env"
    local fetch_url="${companion_url}v1/iso-profiles/${profile_name}?format=env"
    echo "[-] Fetching profile '${profile_name}' from ${fetch_url}..."

    local staging_tmp
    staging_tmp=$(mktemp "/tmp/iso-profile.XXXXXX")
    trap 'rm -f "${staging_tmp}" 2>/dev/null || true' EXIT INT TERM

    local http_code="000"
    if command -v curl >/dev/null 2>&1; then
        http_code=$(curl -sS --connect-timeout 10 -w "%{http_code}" ${auth_header[@]+"${auth_header[@]}"} -o "${staging_tmp}" "${fetch_url}" 2>/dev/null || true)
        http_code="${http_code:-000}"
    elif command -v python3 >/dev/null 2>&1; then
        http_code=$(python3 -c '
import sys, urllib.request, urllib.error
url = sys.argv[1]
dest = sys.argv[2]
key = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
req = urllib.request.Request(url)
if key:
    req.add_header("X-API-Key", key)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        with open(dest, "wb") as f:
            f.write(r.read())
        print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print("000")
' "${fetch_url}" "${staging_tmp}" "${api_key}" 2>/dev/null || echo "000")
        http_code="${http_code:-000}"
    else
        rm -f "${staging_tmp}"
        echo "[!] Error: Neither 'curl' nor 'python3' is available to download from GDC Companion." >&2
        exit 1
    fi

    if [[ "${http_code}" != "200" ]]; then
        rm -f "${staging_tmp}"
        case "${http_code}" in
            401|403)
                echo "[!] Error: Authentication failed with GDC Companion (HTTP ${http_code}). Check your API key." >&2
                ;;
            404)
                echo "[!] Error: ISO profile '${profile_name}' not found on GDC Companion (HTTP 404)." >&2
                ;;
            000)
                echo "[!] Error: Failed to connect to GDC Companion at ${companion_url} (network timeout or connection refused)." >&2
                ;;
            *)
                echo "[!] Error: Upstream request failed with HTTP ${http_code}." >&2
                ;;
        esac
        exit 1
    fi

    # Backup existing profile if present
    if [[ -f "${target_file}" ]]; then
        local backup_dir="${REPO_ROOT}/src/build/.backups"
        mkdir -p "${backup_dir}"
        local ts
        ts=$(date +%Y%m%d-%H%M%S)
        local backup_file="${backup_dir}/${profile_name}.env.${ts}"
        cp "${target_file}" "${backup_file}"
        echo "[x] Existing profile detected. Backed up to: src/build/.backups/${profile_name}.env.${ts}"
    fi

    # Set permissions before atomic move
    chmod 0644 "${staging_tmp}"
    mv "${staging_tmp}" "${target_file}"
    trap - EXIT INT TERM
    echo "[x] Successfully synchronized profile to: src/build/${profile_name}.env"
    exit 0
}

# ==============================================================================
# SUBCOMMAND: push-facts
# ==============================================================================
cmd_push_facts() {
    local default_schema="${REPO_ROOT}/docs/machine-schema.json"
    local companion_docs_dir
    companion_docs_dir="$(cd "${REPO_ROOT}/../gdc-companion/docs" 2>/dev/null && pwd || true)"
    local fallback_schema
    fallback_schema="$([[ -n "${companion_docs_dir}" ]] && echo "${companion_docs_dir}/machine-schema.json" || echo "")"
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
    local valid_stages=("first-boot" "second-boot" "linux-ready" "cluster-ready" "cluster-turnup" "post-cluster")

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
                      Valid stages: first-boot, second-boot, linux-ready, cluster-ready, cluster-turnup, post-cluster
  --no-follow         Do not stream provisioner logs after restarting service
  -h, --help          Display this help message
EOF
        exit "${1:-0}"
    }

    local follow_logs=true
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
            --no-follow)
                follow_logs=false
                shift
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
    trap 'rm -rf "${temp_staging:-}" "${temp_render_dir:-}"' RETURN EXIT

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
        ssh "${ssh_opts[@]}" "${ssh_user}@$node" "sudo systemctl restart --no-block gdc-provision.service"
        echo "  [+] Node update sequence complete!"

        if [[ "${follow_logs}" == "true" && ${#ip_array[@]} -eq 1 ]]; then
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
    local reissue_cert=false
    local iso_env=""
    local step_ca_url=""
    local step_prov_name=""
    local step_prov_pass=""

    rotate_usage() {
        cat <<EOF
Usage: $(basename "$0") rotate-token [OPTIONS]

Forces execution of /usr/local/bin/refresh-gdc-credentials.sh on target nodes
and verifies that the rotated GCP Bearer token is valid and active in gcloud.
Optionally re-issues expired mTLS client certificates via Step CA.

Options:
  --nodes, --ip <IPs>       Comma-separated list or space-separated IPs (defaults to TARGET_TEST_MACHINES)
  --user <USER>             SSH username (default: gdc-admin)
  --key <KEY_PATH>          Path to SSH private key
  --reissue-cert            Re-issue mTLS client certificate via Step CA before refreshing token
  --env, --profile <NAME>   Target profile to load Step CA credentials from (default: barn)
  --step-ca <URL>           Step CA URL (overrides profile/env)
  --provisioner <NAME>      Step CA provisioner name (default: admin)
  --step-pass <PASS>        Step CA provisioner password (overrides profile/env)
  --dry-run                 Display planned actions without connecting via SSH
  -h, --help                Display this help message
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
            --reissue-cert|--reissue|--reissue-mtls)
                reissue_cert=true
                shift
                ;;
            --env|--profile)
                iso_env="$2"
                shift 2
                ;;
            --step-ca|--ca-url)
                step_ca_url="$2"
                shift 2
                ;;
            --provisioner|--provisioner-name)
                step_prov_name="$2"
                shift 2
                ;;
            --step-pass|--provisioner-pass|--step-password)
                step_prov_pass="$2"
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

    # If reissuing cert, resolve Step CA config from environment profile
    if [[ "${reissue_cert}" == "true" ]]; then
        iso_env="${iso_env:-${ISO_ENVIRONMENT:-barn}}"
        local profile_file="${REPO_ROOT}/src/build/${iso_env}.env"
        if [[ -f "${profile_file}" ]]; then
            # Source profile safely for Step CA variables if not overridden
            local env_ca
            env_ca=$(grep -E '^[[:space:]]*STEP_CA_URL=' "${profile_file}" 2>/dev/null | tail -n 1 | cut -d'=' -f2- | tr -d '"'\'' ' || true)
            local env_prov
            env_prov=$(grep -E '^[[:space:]]*STEP_PROVISIONER_NAME=' "${profile_file}" 2>/dev/null | tail -n 1 | cut -d'=' -f2- | tr -d '"'\'' ' || true)
            local env_pass
            env_pass=$(grep -E '^[[:space:]]*STEP_PROVISIONER_PASSWORD=' "${profile_file}" 2>/dev/null | tail -n 1 | cut -d'=' -f2- | tr -d '"'\'' ' || true)

            [[ -z "${step_ca_url}" ]] && step_ca_url="${env_ca}"
            [[ -z "${step_prov_name}" ]] && step_prov_name="${env_prov}"
            [[ -z "${step_prov_pass}" ]] && step_prov_pass="${env_pass}"
        fi

        step_ca_url="${step_ca_url:-${STEP_CA_URL:-https://step-ca.ensor-labs.com}}"
        step_prov_name="${step_prov_name:-${STEP_PROVISIONER_NAME:-admin}}"
        step_prov_pass="${step_prov_pass:-${STEP_PROVISIONER_PASSWORD:-}}"

        if [[ -z "${step_prov_pass}" && "${dry_run}" != "true" ]]; then
            echo "Error: Step CA provisioner password not found. Pass --step-pass or ensure STEP_PROVISIONER_PASSWORD is set." >&2
            exit 1
        fi

        if ! command -v step >/dev/null 2>&1 && [[ "${dry_run}" != "true" ]]; then
            echo "Error: 'step' CLI is required locally on workstation to generate mTLS provisioner tokens." >&2
            exit 1
        fi
    fi

    if [[ "${dry_run}" == "true" ]]; then
        echo "=============================================================================="
        echo " DRY RUN MODE: rotate-token"
        echo "=============================================================================="
        echo "  Target nodes:  ${targets[*]}"
        echo "  SSH User:      ${ssh_user}"
        echo "  Re-issue cert: ${reissue_cert}"
        echo "  Auth Protocol: Dynamic (Day-2 K8s STS if cluster active, Day-0 Step CA if pre-cluster)"
        if [[ "${reissue_cert}" == "true" ]]; then
            echo "  Step CA URL:   ${step_ca_url}"
            echo "  Provisioner:   ${step_prov_name}"
        fi
        echo ""
        echo "Would execute on each target node:"
        if [[ "${reissue_cert}" == "true" ]]; then
            echo "  1. Discover node identity/hostname and primary MAC over SSH as ${ssh_user}"
            echo "  2. Generate short-lived Step CA authorization token via local 'step ca token'"
            echo "  3. ssh ${ssh_user}@<NODE> 'sudo step ca certificate <ID> /var/gdc-install/keys/client.crt /var/gdc-install/keys/client.key --token=<TOKEN> --force'"
            echo "  4. ssh ${ssh_user}@<NODE> 'sudo chmod 0600 /var/gdc-install/keys/client.key && sudo chmod 0644 /var/gdc-install/keys/client.crt'"
            echo "  5. ssh ${ssh_user}@<NODE> 'sudo /usr/local/bin/refresh-gdc-credentials.sh'"
            echo "  6. ssh ${ssh_user}@<NODE> 'gcloud auth print-access-token'"
        else
            echo "  1. ssh ${ssh_user}@<NODE> 'sudo /usr/local/bin/refresh-gdc-credentials.sh'"
            echo "  2. ssh ${ssh_user}@<NODE> 'gcloud auth print-access-token'"
        fi
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

        local is_post_cluster=false
        if ssh "${ssh_opts[@]}" "${ssh_user}@$ip" "test -f /etc/kubernetes/admin.conf && sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf get nodes" &>/dev/null; then
            is_post_cluster=true
            echo "  [+] Active Kubernetes cluster detected on $ip (Day-2 STS Workload Identity active)."
        else
            echo "  [-] Node $ip operating in Pre-Cluster mode (Day-0 Step CA / Companion mTLS)."
        fi

        if [[ "${reissue_cert}" == "true" ]]; then
            echo "  [-] Discovering node identity and MAC on $ip..."
            local node_meta
            node_meta=$(ssh "${ssh_opts[@]}" "${ssh_user}@$ip" bash -s << 'META_EOF' 2>/dev/null || true
set -uo pipefail
node_h=$(hostname 2>/dev/null || echo "")
def_if=$(ip route show | grep '^default' | awk '{print $5}' | head -n 1 || true)
[ -z "$def_if" ] && def_if=$(ls /sys/class/net 2>/dev/null | grep -E '^e' | grep -v '\.' | head -n 1 || true)
node_m=$(cat "/sys/class/net/${def_if}/address" 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]' || true)
echo "${node_h}|${node_m}"
META_EOF
)
            local node_hostname
            node_hostname=$(echo "${node_meta}" | cut -d'|' -f1 | xargs)
            local node_mac
            node_mac=$(echo "${node_meta}" | cut -d'|' -f2 | xargs)

            if [[ -z "${node_mac}" ]]; then
                echo "  [!] ERROR: Could not determine MAC address for $ip. Skipping cert re-issuance."
                continue
            fi

            local cert_identity="${node_hostname:-$node_mac}"
            echo "  [-] Node identity: ${cert_identity} (MAC: ${node_mac})"

            echo "  [-] Generating Step CA authorization token locally..."
            local token_err_file
            token_err_file=$(mktemp)
            local step_jwt=""
            step_jwt=$(echo -n "${step_prov_pass}" | step ca token "${cert_identity}" \
                --san="${node_mac}" \
                --provisioner="${step_prov_name}" \
                --ca-url="${step_ca_url}" \
                --password-file=/dev/stdin 2>"${token_err_file}" || true)

            if [[ -z "${step_jwt}" ]]; then
                echo "  [!] ERROR: Failed to generate Step CA token:" >&2
                cat "${token_err_file}" >&2
                rm -f "${token_err_file}"
                continue
            fi
            rm -f "${token_err_file}"
            echo "  [+] Step CA token generated successfully."

            echo "  [-] Re-issuing mTLS client certificate on $ip..."
            ssh "${ssh_opts[@]}" "${ssh_user}@$ip" bash -s << REMOTE_CERT_EOF
set -euo pipefail
sudo step ca certificate "${cert_identity}" /var/gdc-install/keys/client.crt /var/gdc-install/keys/client.key \
    --token="${step_jwt}" \
    --ca-url="${step_ca_url}" \
    --root="/var/gdc-install/keys/root_ca.crt" \
    --force

sudo chmod 0600 /var/gdc-install/keys/client.key
sudo chmod 0644 /var/gdc-install/keys/client.crt
sudo chown root:root /var/gdc-install/keys/client.key /var/gdc-install/keys/client.crt
echo "  [+] mTLS client certificate re-issued and permissions verified."
REMOTE_CERT_EOF
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
    local skip_fleet=false
    local next_boot_iso=""
    local bootimus_secret_method=""
    local bootimus_user=""
    local bootimus_pass=""
    local bootimus_secret_file=""
    local iso_env=""

    reset_usage() {
        cat <<EOF
Usage: $(basename "$0") reset-pxe [OPTIONS]

Schedules a one-time UEFI PXE boot (BootNext) on target nodes and triggers a reboot.
Optionally unregisters the active cluster from Google Cloud Fleet/GKE Hub if present.
Optionally configures Bootimus one-shot next-boot image for hands-off automation.

Options:
  --nodes <IPs>             Comma-separated list or space-separated IPs (defaults to TARGET_TEST_MACHINES)
  --user <USER>             SSH user (default: gdc-admin)
  --key <KEY_PATH>          Path to SSH private key
  --iso, --next-boot <ISO>  Configure Bootimus one-shot next-boot image for target MAC before reboot
  --env, --profile <NAME>   Target environment profile (default: auto-detected from ISO or barn)
  --secret-method <METHOD>  Bootimus secret method: infisical (default), gcloud, file, or env
  --bootimus-user <USER>    Bootimus API username (default: from secret provider or BOOTIMUS_USER)
  --bootimus-pass <PASS>    Bootimus API password (default: from secret provider or BOOTIMUS_PASS)
  --secret-file <FILE>      Bootimus secret file path
  --skip-fleet              Skip unregistering cluster from Google Cloud Fleet / GKE Hub
  -y, --yes                 Skip confirmation prompt
  -h, --help                Display this help message
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
            --iso|--next-boot)
                next_boot_iso="$2"
                shift 2
                ;;
            --env|--profile)
                iso_env="$2"
                shift 2
                ;;
            --secret-method|--bootimus-secret-method|--secret-provider|--bootimus-secret-provider|---secret-method)
                bootimus_secret_method="$2"
                shift 2
                ;;
            --bootimus-user)
                bootimus_user="$2"
                shift 2
                ;;
            --bootimus-pass|--bootimus-password)
                bootimus_pass="$2"
                shift 2
                ;;
            --secret-file|--bootimus-secret-file)
                bootimus_secret_file="$2"
                shift 2
                ;;
            --skip-fleet|--no-fleet)
                skip_fleet=true
                shift
                ;;
            --unregister-fleet)
                skip_fleet=false
                shift
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

    if [[ -z "${iso_env}" && -n "${next_boot_iso}" ]]; then
        if [[ "${next_boot_iso}" == *gdc-labs* || "${next_boot_iso}" == *barn* ]]; then
            iso_env="barn"
        elif [[ "${next_boot_iso}" == *honeywell* ]]; then
            iso_env="honeywell"
        fi
    fi
    iso_env="${iso_env:-${ISO_ENVIRONMENT:-barn}}"

    bootimus_secret_method="${bootimus_secret_method:-${BOOTIMUS_SECRET_METHOD:-${BOOTIMUS_SECRET_PROVIDER:-infisical}}}"
    bootimus_user="${bootimus_user:-${BOOTIMUS_USER:-}}"
    bootimus_pass="${bootimus_pass:-${BOOTIMUS_PASS:-}}"
    bootimus_secret_file="${bootimus_secret_file:-${BOOTIMUS_SECRET_FILE:-}}"

    local bootimus_cmd_flags=()
    [[ -n "${bootimus_user}" ]] && bootimus_cmd_flags+=(--bootimus-user "${bootimus_user}")
    [[ -n "${bootimus_pass}" ]] && bootimus_cmd_flags+=(--bootimus-pass "${bootimus_pass}")
    [[ -n "${bootimus_secret_method}" ]] && bootimus_cmd_flags+=(--secret-method "${bootimus_secret_method}")
    [[ -n "${bootimus_secret_file}" ]] && bootimus_cmd_flags+=(--secret-file "${bootimus_secret_file}")
    [[ -n "${iso_env}" ]] && bootimus_cmd_flags+=(--env "${iso_env}")

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

        # 1. Check and unregister from Google Cloud Fleet if membership exists
        if [[ "${skip_fleet}" != "true" ]]; then
            echo "  [-] Checking for Fleet membership on $ip..."
            ssh "${ssh_opts[@]}" "${ssh_user}@$ip" bash -s << 'FLEET_EOF' || true
set -uo pipefail
if sudo test -f /etc/kubernetes/admin.conf; then
    if sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf get membership membership --request-timeout=5s &>/dev/null; then
        echo "  [-] Deleting in-cluster 'membership' custom resource..."
        sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf delete membership membership --ignore-not-found=true --timeout=30s 2>/dev/null || true
        echo "  [+] In-cluster Fleet membership custom resource deleted."
    else
        echo -e "  \033[93m[!] Notice: No in-cluster 'membership' resource found.\033[0m"
    fi
else
    echo -e "  \033[93m[!] Notice: No active Kubernetes cluster found on node.\033[0m"
fi
FLEET_EOF

            # Also attempt to unregister from Google Cloud GKE Hub if gcloud is authenticated
            if command -v gcloud &>/dev/null; then
                local node_meta
                node_meta=$(ssh "${ssh_opts[@]}" "${ssh_user}@$ip" "cat /etc/ansible/facts.d/gdc.fact 2>/dev/null || cat /var/gdc-install/state/gdc.fact 2>/dev/null || true" 2>/dev/null || true)
                if [[ -n "$node_meta" ]] && command -v jq &>/dev/null; then
                    local cluster_name
                    local project_id
                    cluster_name=$(echo "$node_meta" | jq -r '.cluster.cluster_name // .hostname // empty' 2>/dev/null || true)
                    project_id=$(echo "$node_meta" | jq -r '.gcp_info.project_id // empty' 2>/dev/null || true)
                    if [[ -n "$cluster_name" && -n "$project_id" ]]; then
                        local mem_loc
                        mem_loc=$(gcloud container fleet memberships list --project="${project_id}" --filter="name:${cluster_name}" --format="value(LOCATION)" 2>/dev/null | head -n 1 || true)
                        if [[ -n "$mem_loc" ]]; then
                            echo "  [-] Unregistering '${cluster_name}' (${mem_loc}) from Google Cloud Fleet in project '${project_id}'..."
                            if gcloud container fleet memberships delete "${cluster_name}" --location="${mem_loc}" --project="${project_id}" --quiet 2>/dev/null; then
                                echo "  [+] Fleet membership '${cluster_name}' removed from Google Cloud GKE Hub."
                            else
                                echo -e "  \033[93m[!] WARNING: Could not remove membership '${cluster_name}' from GKE Hub. Continuing.\033[0m"
                            fi
                        else
                            echo -e "  \033[93m[!] WARNING: Cluster '${cluster_name}' was not found in Google Cloud Fleet (project '${project_id}'). Skipping Fleet unregistration.\033[0m"
                        fi
                    else
                        echo -e "  \033[93m[!] WARNING: Could not determine cluster name or project ID from node facts. Skipping Fleet unregistration.\033[0m"
                    fi
                fi
            fi
        fi

        if [[ -n "${next_boot_iso}" ]]; then
            local node_mac=""
            node_mac=$(ssh "${ssh_opts[@]}" "${ssh_user}@$ip" "cat /sys/class/net/\$(ip route show | grep '^default' | awk '{print \$5}' | head -n 1 || ip -o link show | grep -v 'LOOPBACK' | grep 'state UP' | awk -F': ' '{print \$2}' | head -n 1)/address 2>/dev/null | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]'" 2>/dev/null || true)
            local script_root
            script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
            if [[ -n "${node_mac}" ]]; then
                echo "  [-] Configuring Bootimus next-boot to '${next_boot_iso}' for MAC ${node_mac}..."
                if [[ -x "${script_root}/bootimus.sh" ]]; then
                    ISO_ENVIRONMENT="${iso_env}" "${script_root}/bootimus.sh" --next-boot "${next_boot_iso}" --mac "${node_mac}" "${bootimus_cmd_flags[@]}" || echo -e "  \033[93m[!] Warning: Could not set next-boot on Bootimus for ${node_mac}.\033[0m"
                elif [[ -f "${script_root}/src/build/bootimus.py" ]]; then
                    ISO_ENVIRONMENT="${iso_env}" python3 "${script_root}/src/build/bootimus.py" --next-boot "${next_boot_iso}" --mac "${node_mac}" "${bootimus_cmd_flags[@]}" || echo -e "  \033[93m[!] Warning: Could not set next-boot on Bootimus for ${node_mac}.\033[0m"
                fi
            else
                echo "  [-] SSH MAC lookup failed; configuring Bootimus next-boot by node IP ($ip)..."
                if [[ -x "${script_root}/bootimus.sh" ]]; then
                    ISO_ENVIRONMENT="${iso_env}" "${script_root}/bootimus.sh" --next-boot "${next_boot_iso}" --nodes "${ip}" "${bootimus_cmd_flags[@]}" || echo -e "  \033[93m[!] Warning: Could not set next-boot on Bootimus for $ip.\033[0m"
                elif [[ -f "${script_root}/src/build/bootimus.py" ]]; then
                    ISO_ENVIRONMENT="${iso_env}" python3 "${script_root}/src/build/bootimus.py" --next-boot "${next_boot_iso}" --nodes "${ip}" "${bootimus_cmd_flags[@]}" || echo -e "  \033[93m[!] Warning: Could not set next-boot on Bootimus for $ip.\033[0m"
                fi
            fi
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
    local base_companion="${INSTALL_COMPANION_BASE:-https://gdc-companion.gdc-labs.com/}"
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
# SUBCOMMAND: create-fallback-ca
# ==============================================================================
cmd_create_fallback_ca() {
    local project_id=""
    local secret_name="gdc-fallback-sub-ca"
    local location="us-east4"
    local output_file=""
    local validity_days=3650
    local subject="/CN=GDC Fallback Local CA/O=Google Distributed Cloud"
    local dry_run=false

    fallback_ca_usage() {
        cat <<EOF
Usage: $(basename "$0") create-fallback-ca [OPTIONS]

Generates a self-signed Root/Sub-CA (basicConstraints: CA:TRUE, keyCertSign,
no Name Constraints), formats it into the standard JSON schema (root.crt,
sub-ca.crt, sub-ca.key), and uploads it to Google Cloud Secret Manager.

Options:
  --project <PROJECT_ID>  Target GCP Project ID (defaults to active gcloud project)
  --secret <SECRET_NAME>  Name of the GSM secret (default: gdc-fallback-sub-ca)
  --location <LOCATION>   Replication region for regional secret (default: us-east4)
  --output <FILE_PATH>    Also save the generated JSON payload to a local file
  --days <DAYS>           Validity period in days (default: 3650)
  --subject <SUBJECT>     Certificate subject DN (default: /CN=GDC Fallback Local CA/O=Google Distributed Cloud)
  --dry-run               Generate certificates locally without uploading to Secret Manager
  -h, --help              Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project=*)
                project_id="${1#*=}"
                shift
                ;;
            --project)
                project_id="$2"
                shift 2
                ;;
            --secret=*)
                secret_name="${1#*=}"
                shift
                ;;
            --secret)
                secret_name="$2"
                shift 2
                ;;
            --location=*|--locations=*)
                location="${1#*=}"
                shift
                ;;
            --location|--locations)
                location="$2"
                shift 2
                ;;
            --output=*)
                output_file="${1#*=}"
                shift
                ;;
            --output)
                output_file="$2"
                shift 2
                ;;
            --days=*)
                validity_days="${1#*=}"
                shift
                ;;
            --days)
                validity_days="$2"
                shift 2
                ;;
            --subject=*)
                subject="${1#*=}"
                shift
                ;;
            --subject)
                subject="$2"
                shift 2
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            -h|--help)
                fallback_ca_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for create-fallback-ca" >&2
                fallback_ca_usage 1
                ;;
        esac
    done

    # Resolve project ID and location defaults from environment / build.env
    local env_fallback_proj=""
    local env_fallback_loc=""
    if [[ -f "${REPO_ROOT}/src/build/build.env" ]]; then
        env_fallback_proj=$(grep -E '^[[:space:]]*FALLBACK_SUB_CA_GSM_PROJECT=' "${REPO_ROOT}/src/build/build.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"'\'' ' || true)
        env_fallback_loc=$(grep -E '^[[:space:]]*FALLBACK_SUB_CA_GSM_LOCATION(S)?=' "${REPO_ROOT}/src/build/build.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"'\'' ' || true)
    fi

    if [[ -z "${project_id}" ]]; then
        project_id="${FALLBACK_SUB_CA_GSM_PROJECT:-${env_fallback_proj:-${PROJECT_ID:-}}}"
        if [[ -z "${project_id}" ]]; then
            project_id="$(gcloud config get-value project 2>/dev/null || true)"
        fi
        if [[ -z "${project_id}" ]]; then
            project_id="anthos-bare-metal-lab-1"
        fi
    fi

    if [[ -z "${location}" ]]; then
        location="${FALLBACK_SUB_CA_GSM_LOCATIONS:-${FALLBACK_SUB_CA_GSM_LOCATION:-${env_fallback_loc:-us-east4}}}"
    fi

    echo "=============================================================================="
    echo " GDC SELF-SIGNED FALLBACK SUB-CA GENERATOR"
    echo "=============================================================================="
    echo "  Secret Name:   ${secret_name}"
    echo "  GCP Project:   ${project_id}"
    echo "  Location:      ${location}"
    echo "  Validity Days: ${validity_days}"
    echo "  Subject DN:    ${subject}"
    echo "  Dry Run:       ${dry_run}"
    echo "=============================================================================="

    local work_dir
    work_dir=$(mktemp -d "/tmp/gdc-fallback-ca.XXXXXX")
    trap 'rm -rf "${work_dir:-}" 2>/dev/null || true' EXIT INT TERM

    echo "[-] Generating 4096-bit RSA self-signed CA authority..."
    openssl req -x509 -newkey rsa:4096 -nodes -days "${validity_days}" \
        -keyout "${work_dir}/sub-ca.key" -out "${work_dir}/sub-ca.crt" \
        -subj "${subject}" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null

    echo "[-] Packaging certificate bundle into JSON schema..."
    python3 -c '
import json, sys
crt_path, key_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(crt_path) as f:
    crt = f.read()
with open(key_path) as f:
    key = f.read()
payload = {
    "root.crt": crt,
    "sub-ca.crt": crt,
    "sub-ca.key": key
}
with open(out_path, "w") as out:
    json.dump(payload, out, indent=2)
' "${work_dir}/sub-ca.crt" "${work_dir}/sub-ca.key" "${work_dir}/payload.json"

    if [[ -n "${output_file}" ]]; then
        mkdir -p "$(dirname "${output_file}")"
        cp "${work_dir}/payload.json" "${output_file}"
        chmod 0600 "${output_file}"
        echo "  [x] Saved local copy to: ${output_file}"
    fi

    if [[ "${dry_run}" == "true" ]]; then
        echo "[!] DRY RUN MODE: Skipping Secret Manager upload."
        echo "Generated JSON payload preview:"
        head -n 15 "${work_dir}/payload.json"
        echo "..."
        rm -rf "${work_dir}"
        trap - EXIT INT TERM
        return 0
    fi

    echo "[-] Checking Google Secret Manager for secret '${secret_name}' in project '${project_id}'..."
    if gcloud secrets describe "${secret_name}" --project="${project_id}" &>/dev/null; then
        echo "  [-] Secret exists. Adding new version..."
        gcloud secrets versions add "${secret_name}" \
            --data-file="${work_dir}/payload.json" \
            --project="${project_id}"
        echo "  [+] New version added to '${secret_name}'."
    else
        echo "  [-] Secret not found. Creating regional secret '${secret_name}' in '${location}'..."
        if [[ "${location}" == "global" ]]; then
            gcloud secrets create "${secret_name}" \
                --replication-policy="automatic" \
                --data-file="${work_dir}/payload.json" \
                --project="${project_id}"
        else
            gcloud secrets create "${secret_name}" \
                --replication-policy="user-managed" \
                --locations="${location}" \
                --data-file="${work_dir}/payload.json" \
                --project="${project_id}"
        fi
        echo "  [+] Secret '${secret_name}' created successfully."
    fi

    echo "[-] Verifying secret retrieval (without locations)..."
    if gcloud secrets versions access latest --secret="${secret_name}" --project="${project_id}" >/dev/null 2>&1; then
        echo "  [x] Successfully verified secret access for '${secret_name}' (latest version)."
    fi

    rm -rf "${work_dir}"
    trap - EXIT INT TERM

    echo "=============================================================================="
    echo "[x] Fallback Sub-CA successfully staged in Secret Manager (${secret_name})."
    echo "=============================================================================="
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
    pull-profile)
        cmd_pull_profile "$@"
        ;;
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
    rebuild-cycle|rebuild)
        exec "${SCRIPT_DIR}/gdc-rebuild-environment.sh" "$@"
        ;;
    refresh-telemetry)
        cmd_refresh_telemetry "$@"
        ;;
    create-fallback-ca)
        cmd_create_fallback_ca "$@"
        ;;
    -h|--help|help)
        usage 0
        ;;
    *)
        echo "Error: Unknown command '${COMMAND}'" >&2
        usage 1
        ;;
esac
