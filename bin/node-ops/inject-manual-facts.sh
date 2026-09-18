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

DEFAULT_SCHEMA="${REPO_ROOT}/docs/machine-schema.json"
COMPANION_DOCS_DIR="$(cd "${REPO_ROOT}/../gdc-companion/docs" 2>/dev/null && pwd || true)"
FALLBACK_SCHEMA="$([[ -n "${COMPANION_DOCS_DIR}" ]] && echo "${COMPANION_DOCS_DIR}/machine-schema.json" || echo "/d/projects/google/gdc-companion/docs/machine-schema.json")"
SCHEMA_PATH="${GDC_SCHEMA_PATH:-$([[ -f "${DEFAULT_SCHEMA}" ]] && echo "${DEFAULT_SCHEMA}" || echo "${FALLBACK_SCHEMA}")}"

NODE_IP=""
FACTS_FILE=""
SSH_USER="gdc-admin"
SSH_KEY=""
DRY_RUN=false
FOLLOW_LOGS=true

usage() {
    cat <<EOF
Usage: $(basename "$0") --node <NODE_IP> --facts <FACTS_JSON> [OPTIONS]

Injects a manual fact override file into a GDC target node, resets Stage 5
(Cluster Ready), and triggers gdc-provision.service.

Required Arguments:
  --node <IP>        Target node IP address
  --facts <FILE>     Path to local JSON file adhering to machine-schema.json

Optional Arguments:
  --user <USER>      SSH user (default: gdc-admin)
  --key <KEY_PATH>   Path to SSH private key
  --schema <PATH>    Path to machine-schema.json (defaults to companion schema)
  --dry-run          Validate facts and display actions without running SSH
  --no-follow        Do not follow journalctl logs after restarting service
  -h, --help         Display this help message
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --node)
            NODE_IP="$2"
            shift 2
            ;;
        --facts)
            FACTS_FILE="$2"
            shift 2
            ;;
        --user)
            SSH_USER="$2"
            shift 2
            ;;
        --key)
            SSH_KEY="$2"
            shift 2
            ;;
        --schema)
            SCHEMA_PATH="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-follow)
            FOLLOW_LOGS=false
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        *)
            echo "Error: Unknown argument '$1'" >&2
            usage 1
            ;;
    esac
done

if [[ -z "${NODE_IP}" || -z "${FACTS_FILE}" ]]; then
    echo "Error: Missing required arguments --node and --facts" >&2
    usage 1
fi

if [[ ! -f "${FACTS_FILE}" ]]; then
    echo "Error: Facts file '${FACTS_FILE}' does not exist." >&2
    exit 1
fi

echo "[-] Validating '${FACTS_FILE}' syntax..."
if ! python3 -m json.tool "${FACTS_FILE}" >/dev/null 2>&1; then
    echo "Error: Facts file is not valid JSON." >&2
    exit 1
fi

# Schema validation
if [[ -f "${SCHEMA_PATH}" ]]; then
    echo "[-] Validating facts file against '${SCHEMA_PATH}'..."
    if ! python3 -c "
import json, sys, jsonschema
with open(sys.argv[1], 'r', encoding='utf-8') as sf, open(sys.argv[2], 'r', encoding='utf-8') as df:
    schema = json.load(sf)
    data = json.load(df)
    jsonschema.validate(instance=data, schema=schema)
" "${SCHEMA_PATH}" "${FACTS_FILE}" 2>&1; then
        echo "Error: Facts file failed schema validation against ${SCHEMA_PATH}" >&2
        exit 1
    fi
    echo "  [x] Facts JSON conforms to machine-schema.json."
else
    echo "Warning: Schema file '${SCHEMA_PATH}' not found. Skipping schema validation." >&2
fi

SSH_OPTS=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
if [[ -n "${SSH_KEY}" ]]; then
    SSH_OPTS+=(-i "${SSH_KEY}")
fi

REMOTE_TMP="/tmp/gdc-fact-manual.json"
TARGET_FILE="/var/gdc-install/state/gdc-fact-manual.json"
TARGET_STATE="/var/gdc-install/state/cluster-ready.json"

if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[!] DRY RUN MODE: No remote commands will be executed."
    echo "Would execute:"
    echo "  1. scp ${FACTS_FILE} ${SSH_USER}@${NODE_IP}:${REMOTE_TMP}"
    echo "  2. ssh ${SSH_USER}@${NODE_IP} 'set -euo pipefail; sudo mkdir -p /var/gdc-install/state && sudo mv ${REMOTE_TMP} ${TARGET_FILE} && sudo chown root:root ${TARGET_FILE} && sudo chmod 0644 ${TARGET_FILE} && sudo rm -f ${TARGET_STATE}'"
    echo "  3. ssh ${SSH_USER}@${NODE_IP} 'sudo systemctl restart gdc-provision.service'"
    if [[ "${FOLLOW_LOGS}" == "true" ]]; then
        echo "  4. ssh -t ${SSH_USER}@${NODE_IP} 'sudo journalctl -u gdc-provision.service -f'"
    fi
    exit 0
fi

echo "[-] Uploading facts file to ${NODE_IP}:${REMOTE_TMP}..."
scp "${SSH_OPTS[@]}" "${FACTS_FILE}" "${SSH_USER}@${NODE_IP}:${REMOTE_TMP}"

echo "[-] Staging manual fact file and resetting cluster-ready state..."
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${NODE_IP}" "set -euo pipefail; sudo mkdir -p /var/gdc-install/state && sudo mv '${REMOTE_TMP}' '${TARGET_FILE}' && sudo chown root:root '${TARGET_FILE}' && sudo chmod 0644 '${TARGET_FILE}' && sudo rm -f '${TARGET_STATE}'"

echo "[-] Restarting gdc-provision.service..."
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${NODE_IP}" "sudo systemctl restart gdc-provision.service"

if [[ "${FOLLOW_LOGS}" == "true" ]]; then
    echo "[-] Following gdc-provision.service logs (Ctrl+C to stop)..."
    ssh "${SSH_OPTS[@]}" -t "${SSH_USER}@${NODE_IP}" "sudo journalctl -u gdc-provision.service -f"
fi
