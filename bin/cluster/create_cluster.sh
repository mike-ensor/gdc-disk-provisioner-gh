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

# ==============================================================================
# GDC Standalone Cluster Creation Script (Idempotent)
# ==============================================================================
# GDC Standalone Cluster Creation Script (Idempotent)
# ==============================================================================
# This script provisions a Google Distributed Cloud (GDC) Bare Metal standalone
# cluster. It is designed to be idempotent: if the cluster is already running,
# it will safely skip the creation process.
# ==============================================================================

ENV_CLUSTER_NAME="${CLUSTER_NAME:-}"
ENV_PROJECT_ID="${PROJECT_ID:-}"
ENV_REGION="${REGION:-}"
ENV_MACHINE_IP="${MACHINE_IP:-}"
ENV_CLUSTER_VIP="${CLUSTER_VIP:-}"
ENV_CLUSTER_INGRESS="${CLUSTER_INGRESS:-}"
ENV_PRIMARY_LOAD_BALANCER="${PRIMARY_LOAD_BALANCER:-}"
ENV_ADMIN_USER_EMAIL="${ADMIN_USER_EMAIL:-}"
ENV_PRIMARY_ROOT_REPO="${PRIMARY_ROOT_REPO:-}"
ENV_ROOT_REPO_TYPE="${ROOT_REPO_TYPE:-}"
ENV_ROOT_REPO_BRANCH="${ROOT_REPO_BRANCH:-}"
ENV_ROOT_REPO_SECRET="${ROOT_REPO_SECRET:-}"
ENV_ROOT_REPO_GSA="${ROOT_REPO_GSA:-}"
ENV_CLUSTER_CONFIG_NAME="${CLUSTER_CONFIG_NAME:-}"
ENV_ROOT_SYNC_DIR="${ROOT_SYNC_DIR:-}"
ENV_CONFIG_SYNC_ENABLED="${CONFIG_SYNC_ENABLED:-}"
ENV_ANTHOS_VERSION="${ANTHOS_VERSION:-${ANTHOS_BARE_METAL_VERSION:-}}"
ENV_POD_CIDR="${POD_CIDR:-}"
ENV_SERVICE_CIDR="${SERVICE_CIDR:-}"
FACTS_FILE="${FACTS_FILE:-}"

CLI_CLUSTER_NAME=""
CLI_MACHINE_IP=""
CLI_PROJECT_ID=""
CLI_REGION=""
CLI_CLUSTER_VIP=""
CLI_CLUSTER_INGRESS=""
CLI_PRIMARY_LOAD_BALANCER=""
CLI_ADMIN_USER_EMAIL=""
CLI_PRIMARY_ROOT_REPO=""
CLI_ROOT_REPO_TYPE=""
CLI_ROOT_REPO_BRANCH=""
CLI_ROOT_REPO_SECRET=""
CLI_ROOT_REPO_GSA=""
CLI_CLUSTER_CONFIG_NAME=""
CLI_ROOT_SYNC_DIR=""
CLI_CONFIG_SYNC_ENABLED=""
CLI_ANTHOS_VERSION=""
CLI_POD_CIDR=""
CLI_SERVICE_CIDR=""

AUTO_YES=false
DRY_RUN=false
RESPONSE="y"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Provisions a Google Distributed Cloud (GDC) Bare Metal standalone cluster using bmctl.
Idempotent: skips creation if the cluster is already running.

Options:
  --facts <FILE>         Path to JSON facts file (default: auto-detects from state/facts.d)
  --name <NAME>          Cluster name (default: ${ENV_CLUSTER_NAME:-none})
  --ip <IP>              Node machine IP (default: ${ENV_MACHINE_IP:-none})
  --project <PROJECT>    GCP Project ID (default: ${ENV_PROJECT_ID:-none})
  --region <REGION>      GCP Region (default: ${ENV_REGION:-us-west1})
  --vip <VIP>            Cluster Control Plane VIP (default: ${ENV_CLUSTER_VIP:-none})
  --ingress <INGRESS>    Cluster Ingress VIP (default: ${ENV_CLUSTER_INGRESS:-none})
  --lb-range <RANGE>     MetalLB pool address range (default: ${ENV_PRIMARY_LOAD_BALANCER:-none})
  --version <VERSION>    Anthos bare metal version (default: ${ENV_ANTHOS_VERSION:-1.35.300-gke.87})
  --pod-cidr <CIDR>      Pods CIDR block (default: ${ENV_POD_CIDR:-172.28.0.0/16})
  --service-cidr <CIDR>  Services CIDR block (default: ${ENV_SERVICE_CIDR:-172.29.0.0/20})
  --config-sync          Explicitly enable Config Sync (default: true)
  --no-config-sync       Disable Config Sync installation
  --root-repo <REPO>     Git repo URL or OCI image for primary RootSync (default: ${ENV_PRIMARY_ROOT_REPO:-none})
  --root-repo-type <TYPE>
                         Repository type: 'git' or 'oci' (default: auto-detected)
  --root-repo-branch <BRANCH>
                         Git branch for RootSync (default: main)
  --root-repo-secret <SECRET>
                         GSM secret name containing registry or git credentials
  --root-repo-gsa <GSA>  Google Service Account name for OCI Workload Identity
  --root-sync-dir <DIR>  Directory path in repository for RootSync (default: ${ENV_ROOT_SYNC_DIR:-config/clusters/<cluster-config-name|cluster-name>})
  --cluster-config-name <NAME>
                         Subfolder override under config/clusters/ (default: cluster name)
  --admin-email <EMAIL>  Administrator email for ClusterRoleBinding (optional)
  --dry-run              Validate configuration and simulate inception without modifying system
  -y, --yes              Skip confirmation prompt
  -h, --help             Display this help message and exit
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --facts)
            FACTS_FILE="$2"
            shift 2
            ;;
        --name)
            CLI_CLUSTER_NAME="$2"
            shift 2
            ;;
        --ip)
            CLI_MACHINE_IP="$2"
            shift 2
            ;;
        --project)
            CLI_PROJECT_ID="$2"
            shift 2
            ;;
        --region)
            CLI_REGION="$2"
            shift 2
            ;;
        --vip)
            CLI_CLUSTER_VIP="$2"
            shift 2
            ;;
        --ingress)
            CLI_CLUSTER_INGRESS="$2"
            shift 2
            ;;
        --lb-range)
            CLI_PRIMARY_LOAD_BALANCER="$2"
            shift 2
            ;;
        --version)
            CLI_ANTHOS_VERSION="$2"
            shift 2
            ;;
        --pod-cidr)
            CLI_POD_CIDR="$2"
            shift 2
            ;;
        --service-cidr)
            CLI_SERVICE_CIDR="$2"
            shift 2
            ;;
        --config-sync|--enable-config-sync)
            CLI_CONFIG_SYNC_ENABLED="true"
            shift
            ;;
        --no-config-sync|--disable-config-sync)
            CLI_CONFIG_SYNC_ENABLED="false"
            shift
            ;;
        --root-repo|--primary-root-repo)
            CLI_PRIMARY_ROOT_REPO="$2"
            shift 2
            ;;
        --root-repo-type)
            CLI_ROOT_REPO_TYPE="$2"
            shift 2
            ;;
        --root-repo-branch)
            CLI_ROOT_REPO_BRANCH="$2"
            shift 2
            ;;
        --root-repo-secret)
            CLI_ROOT_REPO_SECRET="$2"
            shift 2
            ;;
        --root-repo-gsa)
            CLI_ROOT_REPO_GSA="$2"
            shift 2
            ;;
        --root-sync-dir)
            CLI_ROOT_SYNC_DIR="$2"
            shift 2
            ;;
        --cluster-config-name)
            CLI_CLUSTER_CONFIG_NAME="$2"
            shift 2
            ;;
        --admin-email)
            CLI_ADMIN_USER_EMAIL="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -y|--yes)
            AUTO_YES=true
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        *)
            echo "Error: Unknown option '$1'" >&2
            usage 1
            ;;
    esac
done

get_json_val() {
    local file="$1"
    local jsonpath="$2"
    if [[ ! -f "$file" ]]; then
        return
    fi
    if command -v jq >/dev/null 2>&1; then
        local val
        val=$(jq -r "try (${jsonpath}) catch empty | if . == null or type == \"object\" or type == \"array\" then empty else . end" "$file" 2>/dev/null || true)
        if [[ "$val" != "null" && -n "$val" ]]; then
            echo "$val"
        fi
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c '
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    keys = sys.argv[2].strip(".").split(".")
    val = data
    for k in keys:
        if val is None or not isinstance(val, dict):
            val = None
            break
        val = val.get(k)
    if val is not None and not isinstance(val, (dict, list)):
        print(val)
except Exception:
    pass
' "$file" "$jsonpath" 2>/dev/null || true
    fi
}

get_json_array() {
    local file="$1"
    local jsonpath="$2"
    if [[ ! -f "$file" ]]; then
        return
    fi
    if command -v jq >/dev/null 2>&1; then
        jq -r "${jsonpath} // [] | .[]" "$file" 2>/dev/null || true
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c '
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    keys = sys.argv[2].strip(".").split(".")
    val = data
    for k in keys:
        if val is None or not isinstance(val, dict):
            val = None
            break
        val = val.get(k)
    if isinstance(val, list):
        for item in val:
            if item is not None and str(item).strip():
                print(str(item).strip())
except Exception:
    pass
' "$file" "$jsonpath" 2>/dev/null || true
    fi
}

# Auto-detect facts file if not explicitly supplied
if [[ -z "${FACTS_FILE}" ]]; then
    for candidate in \
        "/var/gdc-install/state/gdc-fact-manual.json" \
        "/var/gdc-install/state/gdc-machine-facts-manual.json" \
        "/var/gdc-install/stage/gdc-fact-manual.json" \
        "/var/gdc-install/stage/gdc-machine-facts-manual.json" \
        "/var/gdc-install/stage/machine-info.json" \
        "/etc/ansible/facts.d/gdc.fact" \
        "/etc/gdc/machine-info-mock.json" \
        "/etc/gdc/fallback-config.json"; do
        if [[ -f "${candidate}" ]]; then
            FACTS_FILE="${candidate}"
            break
        fi
    done
fi

FACT_CLUSTER_NAME=""
FACT_PROJECT_ID=""
FACT_REGION=""
FACT_CLUSTER_VIP=""
FACT_CLUSTER_INGRESS=""
FACT_PRIMARY_LOAD_BALANCER=""
FACT_IP_CIDR=""
FACT_ADMIN_USER_EMAIL=""
FACT_PRIMARY_ROOT_REPO=""
FACT_ROOT_REPO_TYPE=""
FACT_ROOT_REPO_BRANCH=""
FACT_ROOT_REPO_SECRET=""
FACT_ROOT_REPO_GSA=""
FACT_CLUSTER_CONFIG_NAME=""
FACT_ROOT_SYNC_DIR=""
FACT_ANTHOS_VERSION=""
FACT_POD_CIDR=""
FACT_SERVICE_CIDR=""
CLUSTER_ADMIN_EMAILS=()

if [[ -n "${FACTS_FILE}" && -f "${FACTS_FILE}" ]]; then
    echo "[-] Sourcing cluster parameters from facts: ${FACTS_FILE}"
    FACT_CLUSTER_NAME=$(get_json_val "${FACTS_FILE}" ".cluster.cluster_name")
    FACT_PROJECT_ID=$(get_json_val "${FACTS_FILE}" ".gcp_info.project_id")
    FACT_REGION=$(get_json_val "${FACTS_FILE}" ".gcp_info.region")
    FACT_CLUSTER_VIP=$(get_json_val "${FACTS_FILE}" ".cluster.networking.cluster_vip")
    FACT_CLUSTER_INGRESS=$(get_json_val "${FACTS_FILE}" ".cluster.networking.cluster_ingress")
    FACT_PRIMARY_LOAD_BALANCER=$(get_json_val "${FACTS_FILE}" ".cluster.networking.cluster_lb_range")
    FACT_IP_CIDR=$(get_json_val "${FACTS_FILE}" ".network.cluster_network.ip_cidr")
    if [[ -z "${FACT_IP_CIDR}" ]]; then
        FACT_VLAN_ID=$(get_json_val "${FACTS_FILE}" ".network.cluster_network.vlan_id")
        if [[ -n "${FACT_VLAN_ID}" && "${FACT_VLAN_ID}" != "0" ]] && command -v ip >/dev/null 2>&1; then
            FACT_IP_CIDR=$(ip -4 -o addr show 2>/dev/null | awk -v vlan=".${FACT_VLAN_ID}$" '$2 ~ vlan {print $4; exit}' || true)
        fi
    fi
    if [[ -z "${FACT_IP_CIDR}" ]]; then
        FACT_IP_CIDR=$(get_json_val "${FACTS_FILE}" ".network.management_network.ip_cidr")
    fi
    FACT_ADMIN_USER_EMAIL=$(get_json_val "${FACTS_FILE}" ".cluster.admin_user_email")

    # Safely extract primary_root_repo: Git -> OCI -> scalar string -> empty
    FACT_PRIMARY_ROOT_REPO=$(get_json_val "${FACTS_FILE}" '.cluster.primary_root_repo.git["repo-url"]')
    if [[ -z "${FACT_PRIMARY_ROOT_REPO}" ]]; then
        FACT_PRIMARY_ROOT_REPO=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.git.repo_url")
    fi
    if [[ -n "${FACT_PRIMARY_ROOT_REPO}" ]]; then
        FACT_ROOT_REPO_TYPE="git"
        FACT_ROOT_REPO_BRANCH=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.git.branch")
        FACT_ROOT_REPO_GSM_SECRET=$(get_json_val "${FACTS_FILE}" '.cluster.primary_root_repo.git["gsm-auth-secret"]["gsm-name"]')
        if [[ -z "${FACT_ROOT_REPO_GSM_SECRET}" ]]; then
            FACT_ROOT_REPO_GSM_SECRET=$(get_json_val "${FACTS_FILE}" '.cluster.primary_root_repo.git["gsm-auth-secret"].gsm_name')
        fi
        if [[ -z "${FACT_ROOT_REPO_GSM_SECRET}" ]]; then
            FACT_ROOT_REPO_GSM_SECRET=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.git.gsm_secret_name")
        fi

        FACT_ROOT_REPO_K8S_SECRET=$(get_json_val "${FACTS_FILE}" '.cluster.primary_root_repo.git["gsm-auth-secret"]["k8s-name"]')
        if [[ -z "${FACT_ROOT_REPO_K8S_SECRET}" ]]; then
            FACT_ROOT_REPO_K8S_SECRET=$(get_json_val "${FACTS_FILE}" '.cluster.primary_root_repo.git["gsm-auth-secret"].k8s_name')
        fi
        if [[ -z "${FACT_ROOT_REPO_K8S_SECRET}" ]]; then
            FACT_ROOT_REPO_K8S_SECRET=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo_auth_secret")
        fi
        if [[ -z "${FACT_ROOT_REPO_K8S_SECRET}" ]]; then
            FACT_ROOT_REPO_K8S_SECRET="${FACT_ROOT_REPO_GSM_SECRET}"
        fi
        FACT_ROOT_REPO_SECRET="${FACT_ROOT_REPO_K8S_SECRET}"
    else
        FACT_PRIMARY_ROOT_REPO=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.oci.image")
        if [[ -n "${FACT_PRIMARY_ROOT_REPO}" ]]; then
            FACT_ROOT_REPO_TYPE="oci"
            FACT_ROOT_REPO_GSA=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.oci.gsa")
            FACT_ROOT_REPO_SECRET=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.oci.gsm_secret_name")
        else
            FACT_PRIMARY_ROOT_REPO=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo")
            if [[ -n "${FACT_PRIMARY_ROOT_REPO}" ]]; then
                if [[ "${FACT_PRIMARY_ROOT_REPO}" == *.git || "${FACT_PRIMARY_ROOT_REPO}" == http* || "${FACT_PRIMARY_ROOT_REPO}" == git@* || "${FACT_PRIMARY_ROOT_REPO}" == ssh://* ]]; then
                    FACT_ROOT_REPO_TYPE="git"
                else
                    FACT_ROOT_REPO_TYPE="oci"
                fi
            fi
        fi
    fi
    if [[ -z "${FACT_ROOT_REPO_SECRET}" ]]; then
        FACT_ROOT_REPO_SECRET=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo_auth_secret")
    fi
    FACT_CLUSTER_CONFIG_NAME=$(get_json_val "${FACTS_FILE}" '.cluster.primary_root_repo["cluster-config-name"]')
    if [[ -z "${FACT_CLUSTER_CONFIG_NAME}" ]]; then
        FACT_CLUSTER_CONFIG_NAME=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.cluster_config_name")
    fi
    FACT_ROOT_SYNC_DIR=$(get_json_val "${FACTS_FILE}" '.cluster.primary_root_repo["root-sync-dir"]')
    if [[ -z "${FACT_ROOT_SYNC_DIR}" ]]; then
        FACT_ROOT_SYNC_DIR=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo.root_sync_dir")
    fi
    FACT_CONFIG_SYNC_ENABLED=$(get_json_val "${FACTS_FILE}" ".cluster.config_sync_enabled")

    FACT_ANTHOS_VERSION=$(get_json_val "${FACTS_FILE}" ".cluster.anthos_bare_metal_version")
    FACT_POD_CIDR=$(get_json_val "${FACTS_FILE}" ".cluster.networking.pod_cidr")
    FACT_SERVICE_CIDR=$(get_json_val "${FACTS_FILE}" ".cluster.networking.service_cidr")
    while IFS= read -r email; do
        [[ -n "${email}" ]] && CLUSTER_ADMIN_EMAILS+=("${email}")
    done < <(get_json_array "${FACTS_FILE}" ".cluster.cluster_admin_emails")
fi

# Precedence hierarchy: CLI arguments > Environment variables > Facts file
CLUSTER_NAME="${CLI_CLUSTER_NAME:-${ENV_CLUSTER_NAME:-${FACT_CLUSTER_NAME:-}}}"
PROJECT_ID="${CLI_PROJECT_ID:-${ENV_PROJECT_ID:-${FACT_PROJECT_ID:-}}}"
REGION="${CLI_REGION:-${ENV_REGION:-${FACT_REGION:-us-west1}}}"

FACT_MACHINE_IP=""
if [[ -n "${FACT_IP_CIDR:-}" ]]; then
    FACT_MACHINE_IP="${FACT_IP_CIDR%%/*}"
fi
MACHINE_IP="${CLI_MACHINE_IP:-${ENV_MACHINE_IP:-${FACT_MACHINE_IP:-}}}"

CLUSTER_VIP="${CLI_CLUSTER_VIP:-${ENV_CLUSTER_VIP:-${FACT_CLUSTER_VIP:-}}}"
CLUSTER_INGRESS="${CLI_CLUSTER_INGRESS:-${ENV_CLUSTER_INGRESS:-${FACT_CLUSTER_INGRESS:-}}}"
PRIMARY_LOAD_BALANCER="${CLI_PRIMARY_LOAD_BALANCER:-${ENV_PRIMARY_LOAD_BALANCER:-${FACT_PRIMARY_LOAD_BALANCER:-}}}"
ADMIN_USER_EMAIL="${CLI_ADMIN_USER_EMAIL:-${ENV_ADMIN_USER_EMAIL:-${FACT_ADMIN_USER_EMAIL:-}}}"
PRIMARY_ROOT_REPO="${CLI_PRIMARY_ROOT_REPO:-${ENV_PRIMARY_ROOT_REPO:-${FACT_PRIMARY_ROOT_REPO:-}}}"
if [[ -n "${CLI_PRIMARY_ROOT_REPO}" || -n "${ENV_PRIMARY_ROOT_REPO}" ]]; then
    ROOT_REPO_TYPE="${CLI_ROOT_REPO_TYPE:-${ENV_ROOT_REPO_TYPE:-}}"
    ROOT_REPO_SECRET="${CLI_ROOT_REPO_SECRET:-${ENV_ROOT_REPO_SECRET:-}}"
    ROOT_REPO_GSA="${CLI_ROOT_REPO_GSA:-${ENV_ROOT_REPO_GSA:-}}"
    ROOT_REPO_BRANCH="${CLI_ROOT_REPO_BRANCH:-${ENV_ROOT_REPO_BRANCH:-main}}"
    if [[ -n "${PRIMARY_ROOT_REPO}" && "${PRIMARY_ROOT_REPO}" != "none" ]]; then
        if [[ "${PRIMARY_ROOT_REPO}" == *.git || "${PRIMARY_ROOT_REPO}" == http* || "${PRIMARY_ROOT_REPO}" == git@* || "${PRIMARY_ROOT_REPO}" == ssh://* ]]; then
            ROOT_REPO_TYPE="git"
        else
            ROOT_REPO_TYPE="oci"
        fi
    fi
else
    ROOT_REPO_TYPE="${FACT_ROOT_REPO_TYPE:-}"
    ROOT_REPO_BRANCH="${FACT_ROOT_REPO_BRANCH:-main}"
    ROOT_REPO_SECRET="${FACT_ROOT_REPO_SECRET:-}"
    ROOT_REPO_GSA="${FACT_ROOT_REPO_GSA:-}"
    if [[ -n "${PRIMARY_ROOT_REPO}" && "${PRIMARY_ROOT_REPO}" != "none" ]]; then
        if [[ -z "${ROOT_REPO_TYPE}" ]]; then
            if [[ "${PRIMARY_ROOT_REPO}" == *.git || "${PRIMARY_ROOT_REPO}" == http* || "${PRIMARY_ROOT_REPO}" == git@* || "${PRIMARY_ROOT_REPO}" == ssh://* ]]; then
                ROOT_REPO_TYPE="git"
            else
                ROOT_REPO_TYPE="oci"
            fi
        fi
    fi
fi
CLUSTER_CONFIG_NAME="${CLI_CLUSTER_CONFIG_NAME:-${ENV_CLUSTER_CONFIG_NAME:-${FACT_CLUSTER_CONFIG_NAME:-}}}"
DEFAULT_ROOT_SYNC_DIR="config/clusters/${CLUSTER_CONFIG_NAME:-${CLUSTER_NAME}}"
ROOT_SYNC_DIR="${CLI_ROOT_SYNC_DIR:-${ENV_ROOT_SYNC_DIR:-${FACT_ROOT_SYNC_DIR:-${DEFAULT_ROOT_SYNC_DIR}}}}"
CONFIG_SYNC_ENABLED="${CLI_CONFIG_SYNC_ENABLED:-${ENV_CONFIG_SYNC_ENABLED:-${FACT_CONFIG_SYNC_ENABLED:-true}}}"
if [[ "${CONFIG_SYNC_ENABLED}" != "false" ]]; then
    CONFIG_SYNC_ENABLED="true"
fi

ROOT_REPO_AUTH_DISPLAY="none (public)"
if [[ "${ROOT_REPO_TYPE}" == "oci" ]]; then
    if [[ -n "${ROOT_REPO_GSA}" ]]; then
        ROOT_REPO_AUTH_DISPLAY="Workload Identity (GSA: ${ROOT_REPO_GSA})"
    elif [[ -n "${ROOT_REPO_SECRET}" ]]; then
        ROOT_REPO_AUTH_DISPLAY="GSM Secret ('${ROOT_REPO_SECRET}')"
    fi
elif [[ "${ROOT_REPO_TYPE}" == "git" ]]; then
    if [[ -n "${ROOT_REPO_SECRET}" ]]; then
        if [[ "${PRIMARY_ROOT_REPO}" == git@* || "${PRIMARY_ROOT_REPO}" == ssh://* ]]; then
            ROOT_REPO_AUTH_DISPLAY="GSM SSH Key ('${ROOT_REPO_SECRET}')"
        else
            ROOT_REPO_AUTH_DISPLAY="GSM Secret ('${ROOT_REPO_SECRET}')"
        fi
    fi
fi
ANTHOS_VERSION="${CLI_ANTHOS_VERSION:-${ENV_ANTHOS_VERSION:-${FACT_ANTHOS_VERSION:-1.35.300-gke.87}}}"
POD_CIDR="${CLI_POD_CIDR:-${ENV_POD_CIDR:-${FACT_POD_CIDR:-172.28.0.0/16}}}"
SERVICE_CIDR="${CLI_SERVICE_CIDR:-${ENV_SERVICE_CIDR:-${FACT_SERVICE_CIDR:-172.29.0.0/20}}}"

# Fail fast if any required variables are missing
MISSING_VARS=()
[[ -z "${CLUSTER_NAME}" ]] && MISSING_VARS+=("CLUSTER_NAME (or --name)")
[[ -z "${PROJECT_ID}" ]] && MISSING_VARS+=("PROJECT_ID (or --project)")
[[ -z "${MACHINE_IP}" ]] && MISSING_VARS+=("MACHINE_IP (or --ip)")
[[ -z "${CLUSTER_VIP}" ]] && MISSING_VARS+=("CLUSTER_VIP (or --vip)")
[[ -z "${CLUSTER_INGRESS}" ]] && MISSING_VARS+=("CLUSTER_INGRESS (or --ingress)")
[[ -z "${PRIMARY_LOAD_BALANCER}" ]] && MISSING_VARS+=("PRIMARY_LOAD_BALANCER (or --lb-range)")

if [[ ${#MISSING_VARS[@]} -gt 0 ]]; then
  echo "==============================================================================" >&2
  echo "  ERROR: Missing required cluster configuration parameter(s):" >&2
  for var in "${MISSING_VARS[@]}"; do
    echo "    - ${var}" >&2
  done
  echo "" >&2
  echo "  When running manually, please export these environment variables ahead of time:" >&2
  echo "    export CLUSTER_NAME=\"my-cluster\"" >&2
  echo "    export PROJECT_ID=\"my-gcp-project-id\"" >&2
  echo "    export MACHINE_IP=\"192.168.4.241\"" >&2
  echo "    export CLUSTER_VIP=\"192.168.4.100\"" >&2
  echo "    export CLUSTER_INGRESS=\"192.168.4.101\"" >&2
  echo "    export PRIMARY_LOAD_BALANCER=\"192.168.4.101-192.168.4.109\"" >&2
  echo "" >&2
  echo "  Or supply them via CLI arguments, or provide a facts file with --facts <file>." >&2
  echo "==============================================================================" >&2
  exit 1
fi

export MACHINE_IP
export CLUSTER_NAME
export PROJECT_ID
export REGION
export CLUSTER_VIP
export CLUSTER_INGRESS
export PRIMARY_LOAD_BALANCER
export ADMIN_USER_EMAIL
export PRIMARY_ROOT_REPO
export ANTHOS_VERSION
export POD_CIDR
export SERVICE_CIDR

export BMCTL_WORKSPACE="/var/gdc-install/bmctl-workspace"
export CLUSTER_CONFIG_DIR="${BMCTL_WORKSPACE}/${CLUSTER_NAME}"
export CLUSTER_CONFIG_FILE="${CLUSTER_CONFIG_DIR}/${CLUSTER_NAME}.yaml"

START_TIME=$(date +%s)

function print_runtime() {
	local exit_code=$?
	local end_time
	end_time=$(date +%s)
	local elapsed=$((end_time - START_TIME))

	local hours=$((elapsed / 3600))
	local mins=$(((elapsed % 3600) / 60))
	local secs=$((elapsed % 60))

	local formatted_time
	formatted_time=$(printf "%02dh %02dm %02ds" $hours $mins $secs)

	echo "=============================================================================="
	if [ $exit_code -eq 0 ]; then
		echo "[SUCCESS] Operation completed in ${formatted_time}"
	else
		echo "[FAILURE] Operation failed after ${formatted_time}"
	fi
	echo "=============================================================================="
}

trap print_runtime EXIT

GCLOUD_TOKEN_AUTH="FALSE"
TOKEN=$(gcloud auth print-access-token 2>/dev/null || true)

if [[ -n "$TOKEN" ]]; then
    TOKEN_INFO=$(curl -s "https://oauth2.googleapis.com/tokeninfo?access_token=$TOKEN" || true)
    EXPIRES_IN=$(echo "$TOKEN_INFO" | grep -o '"expires_in": [0-9]*' | grep -o '[0-9]*' || true)
    
    if [[ -n "$EXPIRES_IN" ]]; then
        EXPIRES_MIN=$(( EXPIRES_IN / 60 ))
        GCLOUD_TOKEN_AUTH="true (expires in ~${EXPIRES_MIN}m)"
    else
        GCLOUD_TOKEN_AUTH="true (expiration unknown)"
    fi
fi
GOOGLE_APP_CREDS="${GOOGLE_APPLICATION_CREDENTIALS:-MISSING!!!}"

echo "=============================================================================="
echo "  NOTE: Temporary cluster creation process. DO NOT USE FOR PRODUCTION         "
echo "=============================================================================="
echo "Starting GDC Cluster Creation Process"
printf "  %-35s %s\n" "Cluster Name:" "${CLUSTER_NAME}"
printf "  %-35s %s\n" "Project ID:" "${PROJECT_ID}"
printf "  %-35s %s\n" "Region:" "${REGION}"
printf "  %-35s %s\n" "Anthos Version:" "${ANTHOS_VERSION}"
printf "  %-35s %s\n" "Machine IP:" "${MACHINE_IP}"
printf "  %-35s %s\n" "Cluster VIP:" "${CLUSTER_VIP}"
printf "  %-35s %s\n" "Cluster Ingress:" "${CLUSTER_INGRESS}"
printf "  %-35s %s\n" "Pod CIDR:" "${POD_CIDR}"
printf "  %-35s %s\n" "Service CIDR:" "${SERVICE_CIDR}"
printf "  %-35s %s\n" "Primary Load Balancer:" "${PRIMARY_LOAD_BALANCER}"
printf "  %-35s %s\n" "Config Sync:" "${CONFIG_SYNC_ENABLED}"
printf "  %-35s %s\n" "Primary Root Repo:" "${PRIMARY_ROOT_REPO:-none}"
if [[ "${CONFIG_SYNC_ENABLED}" == "true" && -n "${PRIMARY_ROOT_REPO}" && "${PRIMARY_ROOT_REPO}" != "none" ]]; then
    printf "  %-35s %s\n" "Root Repo Type:" "${ROOT_REPO_TYPE:-auto}"
    if [[ "${ROOT_REPO_TYPE}" == "git" ]]; then
        printf "  %-35s %s\n" "Root Repo Branch:" "${ROOT_REPO_BRANCH:-main}"
    fi
    printf "  %-35s %s\n" "Target Sync Directory:" "${ROOT_SYNC_DIR}"
    printf "  %-35s %s\n" "Root Repo Authentication:" "${ROOT_REPO_AUTH_DISPLAY}"
fi
printf "  %-35s %s\n" "Admin User Email (automated):" "${ADMIN_USER_EMAIL:-none}"
if [[ ${#CLUSTER_ADMIN_EMAILS[@]} -gt 0 ]]; then
    printf "  %-35s %s\n" "Cluster Admin Emails (${#CLUSTER_ADMIN_EMAILS[@]}):" "${CLUSTER_ADMIN_EMAILS[*]}"
else
    printf "  %-35s %s\n" "Cluster Admin Emails (0):" "none"
fi
printf "  %-35s %s\n" "GOOGLE_APP_CREDS:" "${GOOGLE_APP_CREDS}"
printf "  %-35s %s\n" "gcloud token authenticated:" "${GCLOUD_TOKEN_AUTH}"
echo "=============================================================================="

if [[ "${DRY_RUN}" != "true" && "$(id -un)" != "gdc-admin" ]]; then
	echo "[!] ERROR: This script must be executed as user 'gdc-admin' (current user: '$(id -un)')." >&2
	exit 1
fi

if [[ "${AUTO_YES}" != "true" ]]; then
    read -r -p "Are you sure you want to run preflight and create cluster '${CLUSTER_NAME}'? (Y/n) " RESPONSE
fi
if [[ ! "${RESPONSE}" =~ ^([yY][eE][sS]|[yY]|"")$ ]]; then
	echo "Cluster creation aborted by user."
	exit 0
fi

if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[DRY-RUN] Preflight and cluster scaffolding simulated successfully."
    echo "[DRY-RUN] Target cluster config file: ${CLUSTER_CONFIG_FILE}"
    echo "[DRY-RUN] Would execute bmctl check preflight and bmctl create cluster."
    exit 0
fi

# 1. Check if the cluster is already running
if sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl get nodes &>/dev/null; then
	echo "[OK] Cluster '${CLUSTER_NAME}' is already running. Skipping creation."
	exit 0
fi

mkdir -p "${BMCTL_WORKSPACE}"

# 2. Configure SSH Access
echo "[-] Configuring local SSH access for gdc-admin..."
mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"
if [ ! -f "${HOME}/.ssh/id_ed25519" ]; then
	ssh-keygen -t ed25519 -C "gdc-admin@local" -N "" -f "${HOME}/.ssh/id_ed25519"
fi

touch "${HOME}/.ssh/authorized_keys"
chmod 600 "${HOME}/.ssh/authorized_keys"
if ! grep -F -x -q "$(cat "${HOME}/.ssh/id_ed25519.pub")" "${HOME}/.ssh/authorized_keys" 2>/dev/null; then
	cat "${HOME}/.ssh/id_ed25519.pub" >> "${HOME}/.ssh/authorized_keys"
fi

# 3. Scaffold the Configuration File
echo "[-] Scaffolding bmctl configuration..."
cd /var/gdc-install

if [ ! -f "${CLUSTER_CONFIG_FILE}" ]; then
	# Create fake GCR key path to satisfy bmctl when using Workload Identity
	sudo mkdir -p /bmctl
	echo "{}" | sudo tee /bmctl/fake.json >/dev/null

	echo "[-] Generating default bmctl config..."
	bmctl create config -c "${CLUSTER_NAME}" \
		--bootstrap-cluster-pod-cidr="10.200.10.0/16" \
		--bootstrap-cluster-service-cidr="100.200.20.0/24"

	# Hydrate the configuration file
	echo "[-] Hydrating target configuration..."
	cat <<EOF >"${CLUSTER_CONFIG_FILE}"
---
sshPrivateKeyPath: ${HOME}/.ssh/id_ed25519
---
apiVersion: v1
kind: Namespace
metadata:
  name: "${CLUSTER_NAME}"
---
apiVersion: baremetal.cluster.gke.io/v1
kind: Cluster
metadata:
  name: "${CLUSTER_NAME}"
  namespace: "${CLUSTER_NAME}"
  annotations:
    baremetal.cluster.gke.io/enable-workload-identity-cluster-authentication: "true"
spec:
  type: standalone
  profile: edge
  anthosBareMetalVersion: ${ANTHOS_VERSION}
  gkeConnect:
    projectID: ${PROJECT_ID}
    location: ${REGION}
  controlPlane:
    nodePoolSpec:
      nodes:
        - address: ${MACHINE_IP}
  clusterNetwork:
    bundledIngress: false
    flatIPv4: false
    pods:
      cidrBlocks:
        - ${POD_CIDR}
    services:
      cidrBlocks:
        - ${SERVICE_CIDR}
  loadBalancer:
    mode: bundled
    type: layer2
    ports:
      controlPlaneLBPort: 443
    vips:
      controlPlaneVIP: ${CLUSTER_VIP}
      ingressVIP: ${CLUSTER_INGRESS}
    addressPools:
      - name: primary-load-balancer
        addresses:
          - ${PRIMARY_LOAD_BALANCER}
  clusterOperations:
    projectID: ${PROJECT_ID}
    location: ${REGION}
    disableCloudAuditLogging: false
  storage:
    lvpNodeMounts:
      path: /mnt/localpv-disk
      storageClassName: local-disks
    lvpShare:
      path: /mnt/localpv-share
      storageClassName: local-shared
      numPVUnderSharedPath: 5
  nodeConfig:
    podDensity:
      maxPodsPerNode: 250
  gkeOnPremAPI:
    enabled: false
    location: ${REGION}
  nodeAccess:
    loginUser: gdc-admin
EOF
else
	echo "[OK] Configuration file already exists at ${CLUSTER_CONFIG_FILE}"
fi

# 4. Initiate Cluster Inception
echo "[-] Executing Preflight Checks..."
if ! GCP_ACCESS_TOKEN=$(gcloud auth application-default print-access-token 2>/dev/null); then
	echo "[!] ERROR: Unable to obtain GCP access token from Application Default Credentials." >&2
	echo "    Please run 'gcloud auth application-default login' or verify GOOGLE_APPLICATION_CREDENTIALS." >&2
	exit 1
fi
export GCP_ACCESS_TOKEN
if ! bmctl check preflight --cluster "${CLUSTER_NAME}"; then
	echo "[!] Preflight checks failed! Please review the errors above."
	exit 1
fi

echo "[-] Creating cluster (this may take 15-30 minutes)..."
bmctl create cluster -c "${CLUSTER_NAME}"

# 5. Extract Kubeconfig
if [ -f "/etc/kubernetes/admin.conf" ]; then
	echo "[-] Extracting local kubeconfig..."
	sudo bmctl get credentials --cluster "${CLUSTER_NAME}" --admin-kubeconfig /etc/kubernetes/admin.conf
	sudo chown "$USER":"$USER" "${CLUSTER_CONFIG_DIR}/${CLUSTER_NAME}-kubeconfig"

	if ! grep -q "export KUBECONFIG=" "$HOME/.bashrc"; then
		echo "export KUBECONFIG=\"${CLUSTER_CONFIG_DIR}/${CLUSTER_NAME}-kubeconfig\"" >>"$HOME/.bashrc"
	fi
	echo "[OK] Cluster creation complete. Kubeconfig available at ${CLUSTER_CONFIG_DIR}/${CLUSTER_NAME}-kubeconfig"

	# 5a. Automated Admin User Role Binding
	if [ -n "${ADMIN_USER_EMAIL:-}" ]; then
		echo "[-] ADMIN_USER_EMAIL is defined (${ADMIN_USER_EMAIL}). Creating ClusterRoleBinding 'automated-admin-email'..."
		ADMIN_EMAIL_FILE="${CLUSTER_CONFIG_DIR}/cluster-admin-automated.yaml"
		cat <<EOF >"${ADMIN_EMAIL_FILE}"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: automated-admin-email
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ${ADMIN_USER_EMAIL}
EOF
		sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f "${ADMIN_EMAIL_FILE}"
		echo "[OK] ClusterRoleBinding 'automated-admin-email' for ${ADMIN_USER_EMAIL} created."
	else
		echo "[-] ADMIN_USER_EMAIL is not defined. Skipping automated-admin-email creation."
	fi

	# 5b. Dynamic Installed Cluster Admin Users Role Binding
	if [ ${#CLUSTER_ADMIN_EMAILS[@]} -gt 0 ]; then
		echo "[-] Applying dynamic cluster admin email list (${#CLUSTER_ADMIN_EMAILS[@]} users)..."
		DYNAMIC_ADMINS_FILE="${CLUSTER_CONFIG_DIR}/cluster-admins-dynamic.yaml"
		cat <<EOF >"${DYNAMIC_ADMINS_FILE}"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dynamic-installed-cluster-admin-list
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
EOF
		for admin_email in "${CLUSTER_ADMIN_EMAILS[@]}"; do
			cat <<EOF >>"${DYNAMIC_ADMINS_FILE}"
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ${admin_email}
EOF
		done
		sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f "${DYNAMIC_ADMINS_FILE}"
		echo "[OK] ClusterRoleBinding 'dynamic-installed-cluster-admin-list' applied successfully."
	else
		echo "[-] No cluster admin emails defined in facts. Skipping dynamic-installed-cluster-admin-list creation."
	fi

	# 5c. Enable Google Managed Service for Prometheus (GMP) for applications
	echo "[-] Enabling Google Managed Prometheus (GMP) for applications in Stackdriver..."
	if sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl get stackdriver stackdriver -n kube-system &>/dev/null; then
		sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl patch stackdriver stackdriver -n kube-system \
			--type=merge -p '{"spec":{"enableGMPForApplications":true}}'
		echo "[OK] Stackdriver GMP for applications enabled."
	else
		echo "[-] Notice: Stackdriver resource not found in kube-system. Skipping GMP enablement."
	fi

	# 6. Deploy Config Sync
	if [[ "${CONFIG_SYNC_ENABLED}" != "true" ]]; then
		echo "[-] Config Sync disabled via configuration. Skipping Config Sync deployment."
	else
		echo "[-] Deploying Config Sync..."
		APPLY_SPEC_FILE="${CLUSTER_CONFIG_DIR}/apply-spec.yaml"
		cat <<EOF >"${APPLY_SPEC_FILE}"
applySpecVersion: 1
spec:
  configSync:
    enabled: true
EOF

		MEMBERSHIP="projects/${PROJECT_ID}/locations/${REGION}/memberships/${CLUSTER_NAME}"
		echo "[-] Applying Config Management to membership: ${MEMBERSHIP}..."
		if gcloud beta container fleet config-management apply \
			--membership="${MEMBERSHIP}" \
			--config="${APPLY_SPEC_FILE}" \
			--project="${PROJECT_ID}"; then
			echo "[OK] Config Sync deployment initiated for ${CLUSTER_NAME}."
		else
			echo "[!] Warning: Failed to apply fleet config-management. Delegating Config Sync setup to Stage 7."
		fi
	fi

	# 7. Deploy Primary RootSync (if specified)
	if [[ "${CONFIG_SYNC_ENABLED}" != "true" ]]; then
		echo "[-] Config Sync disabled. Skipping RootSync deployment."
	elif [[ -n "${PRIMARY_ROOT_REPO}" && "${PRIMARY_ROOT_REPO}" != "none" ]]; then
		echo "[-] Deploying Primary RootSync (${ROOT_REPO_TYPE:-oci}): ${PRIMARY_ROOT_REPO}..."
		echo "[-] Waiting for RootSync CRD to be established..."
		crd_found=false
		for _ in {1..30}; do
			if sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl get crd rootsyncs.configsync.gke.io &>/dev/null; then
				crd_found=true
				break
			fi
			sleep 2
		done

		if [[ "${crd_found}" != "true" ]]; then
			echo "[!] Warning: Timed out waiting for rootsyncs.configsync.gke.io CRD to be established. Gracefully delegating RootSync deployment to Stage 7."
		else
			ROOTSYNC_FILE="${CLUSTER_CONFIG_DIR}/rootsync-primary.yaml"
			echo "[-] Generating RootSync manifest for primary root repo..."
			if [[ "${ROOT_REPO_TYPE}" == "git" ]]; then
				ROOT_GIT_AUTH="none"
				if [[ -n "${ROOT_REPO_SECRET:-}" ]]; then
					if [[ "${PRIMARY_ROOT_REPO}" == git@* || "${PRIMARY_ROOT_REPO}" == ssh://* ]]; then
						ROOT_GIT_AUTH="ssh"
					else
						ROOT_GIT_AUTH="token"
					fi
				fi
				cat <<EOF >"${ROOTSYNC_FILE}"
apiVersion: configsync.gke.io/v1beta1
kind: RootSync
metadata:
  name: root-sync
  namespace: config-management-system
spec:
  sourceFormat: unstructured
  sourceType: git
  git:
    repo: ${PRIMARY_ROOT_REPO}
    branch: ${ROOT_REPO_BRANCH:-main}
    dir: ${ROOT_SYNC_DIR:-.}
    auth: ${ROOT_GIT_AUTH}
EOF
				if [[ -n "${ROOT_REPO_SECRET:-}" ]]; then
					cat <<EOF >>"${ROOTSYNC_FILE}"
    secretRef:
      name: ${ROOT_REPO_SECRET}
EOF
				fi
			else
				cat <<EOF >"${ROOTSYNC_FILE}"
apiVersion: configsync.gke.io/v1beta1
kind: RootSync
metadata:
  name: root-sync
  namespace: config-management-system
spec:
  sourceFormat: unstructured
  sourceType: oci
  oci:
    image: ${PRIMARY_ROOT_REPO}
    dir: ${ROOT_SYNC_DIR:-.}
EOF
				if [[ -n "${ROOT_REPO_GSA:-}" ]]; then
					cat <<EOF >>"${ROOTSYNC_FILE}"
    auth: gcpserviceaccount
    gcpServiceAccountEmail: ${ROOT_REPO_GSA}@${PROJECT_ID}.iam.gserviceaccount.com
EOF
				elif [[ -n "${ROOT_REPO_SECRET:-}" ]]; then
					cat <<EOF >>"${ROOTSYNC_FILE}"
    auth: token
    secretRef:
      name: ${ROOT_REPO_SECRET}
EOF
				else
					cat <<EOF >>"${ROOTSYNC_FILE}"
    auth: none
EOF
				fi
			fi

			echo "[-] Applying RootSync 'root-sync' to cluster..."
			if sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f "${ROOTSYNC_FILE}"; then
				echo "[OK] Primary RootSync deployed successfully."
			else
				echo "[!] Warning: Failed to apply RootSync manifest. Delegating to Stage 7 post_cluster."
			fi
		fi
	else
		echo "[-] No primary root repo specified. Skipping RootSync deployment."
	fi
else
	echo "[!] Warning: /etc/kubernetes/admin.conf not found. Ensure the cluster creation completed successfully."
fi
