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

MACHINE_IP="${MACHINE_IP:-192.168.9.241}"
CLUSTER_NAME="${CLUSTER_NAME:-gdc-default-241}"
PROJECT_ID="${PROJECT_ID:-anthos-bare-metal-lab-1}"
REGION="${REGION:-us-west1}"

CLUSTER_VIP="${CLUSTER_VIP:-192.168.9.143}"
CLUSTER_INGRESS="${CLUSTER_INGRESS:-192.168.9.144}"
PRIMARY_LOAD_BALANCER="${PRIMARY_LOAD_BALANCER:-192.168.9.144-192.168.9.150}"

ADMIN_USER_EMAIL="${ADMIN_USER_EMAIL:-}"
FACTS_FILE="${FACTS_FILE:-}"
PRIMARY_ROOT_REPO="${PRIMARY_ROOT_REPO:-MISSING!!!}"

CLI_CLUSTER_NAME=""
CLI_MACHINE_IP=""
CLI_PROJECT_ID=""
CLI_REGION=""
CLI_CLUSTER_VIP=""
CLI_CLUSTER_INGRESS=""
CLI_PRIMARY_LOAD_BALANCER=""
CLI_ADMIN_USER_EMAIL=""

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
  --name <NAME>          Cluster name (default: ${CLUSTER_NAME})
  --ip <IP>              Node machine IP (default: ${MACHINE_IP})
  --project <PROJECT>    GCP Project ID (default: ${PROJECT_ID})
  --region <REGION>      GCP Region (default: ${REGION})
  --vip <VIP>            Cluster Control Plane VIP (default: ${CLUSTER_VIP})
  --ingress <INGRESS>    Cluster Ingress VIP (default: ${CLUSTER_INGRESS})
  --lb-range <RANGE>     MetalLB pool address range (default: ${PRIMARY_LOAD_BALANCER})
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
        val=$(jq -r "${jsonpath} // empty" "$file" 2>/dev/null || true)
        if [[ "$val" != "null" && -n "$val" ]]; then
            echo "$val"
        fi
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "
import json, sys
try:
    with open('$file') as f:
        data = json.load(f)
    keys = '$jsonpath'.strip('.').split('.')
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
" 2>/dev/null || true
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

if [[ -n "${FACTS_FILE}" && -f "${FACTS_FILE}" ]]; then
    echo "[-] Sourcing cluster parameters from facts: ${FACTS_FILE}"
    FACT_CLUSTER_NAME=$(get_json_val "${FACTS_FILE}" ".cluster.cluster_name")
    FACT_PROJECT_ID=$(get_json_val "${FACTS_FILE}" ".gcp_info.project_id")
    FACT_REGION=$(get_json_val "${FACTS_FILE}" ".gcp_info.region")
    FACT_CLUSTER_VIP=$(get_json_val "${FACTS_FILE}" ".cluster.networking.cluster_vip")
    FACT_CLUSTER_INGRESS=$(get_json_val "${FACTS_FILE}" ".cluster.networking.cluster_ingress")
    FACT_PRIMARY_LOAD_BALANCER=$(get_json_val "${FACTS_FILE}" ".cluster.networking.cluster_lb_range")
    FACT_IP_CIDR=$(get_json_val "${FACTS_FILE}" ".network.cluster_network.ip_cidr")
    FACT_ADMIN_USER_EMAIL=$(get_json_val "${FACTS_FILE}" ".cluster.admin_user_email")
    FACT_PRIMARY_ROOT_REPO=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo")

    if [[ -n "${FACT_CLUSTER_NAME}" ]]; then CLUSTER_NAME="${FACT_CLUSTER_NAME}"; fi
    if [[ -n "${FACT_PROJECT_ID}" ]]; then PROJECT_ID="${FACT_PROJECT_ID}"; fi
    if [[ -n "${FACT_REGION}" ]]; then REGION="${FACT_REGION}"; fi
    if [[ -n "${FACT_CLUSTER_VIP}" ]]; then CLUSTER_VIP="${FACT_CLUSTER_VIP}"; fi
    if [[ -n "${FACT_CLUSTER_INGRESS}" ]]; then CLUSTER_INGRESS="${FACT_CLUSTER_INGRESS}"; fi
    if [[ -n "${FACT_PRIMARY_LOAD_BALANCER}" ]]; then PRIMARY_LOAD_BALANCER="${FACT_PRIMARY_LOAD_BALANCER}"; fi
    if [[ -n "${FACT_IP_CIDR}" ]]; then MACHINE_IP="${FACT_IP_CIDR%%/*}"; fi
    if [[ -n "${FACT_ADMIN_USER_EMAIL}" ]]; then ADMIN_USER_EMAIL="${FACT_ADMIN_USER_EMAIL}"; fi
    if [[ -n "${FACT_PRIMARY_ROOT_REPO}" ]]; then PRIMARY_ROOT_REPO="${FACT_PRIMARY_ROOT_REPO}"; fi
fi

# Explicit CLI arguments take highest precedence
if [[ -n "${CLI_CLUSTER_NAME}" ]]; then CLUSTER_NAME="${CLI_CLUSTER_NAME}"; fi
if [[ -n "${CLI_MACHINE_IP}" ]]; then MACHINE_IP="${CLI_MACHINE_IP}"; fi
if [[ -n "${CLI_PROJECT_ID}" ]]; then PROJECT_ID="${CLI_PROJECT_ID}"; fi
if [[ -n "${CLI_REGION}" ]]; then REGION="${CLI_REGION}"; fi
if [[ -n "${CLI_CLUSTER_VIP}" ]]; then CLUSTER_VIP="${CLI_CLUSTER_VIP}"; fi
if [[ -n "${CLI_CLUSTER_INGRESS}" ]]; then CLUSTER_INGRESS="${CLI_CLUSTER_INGRESS}"; fi
if [[ -n "${CLI_PRIMARY_LOAD_BALANCER}" ]]; then PRIMARY_LOAD_BALANCER="${CLI_PRIMARY_LOAD_BALANCER}"; fi
if [[ -n "${CLI_ADMIN_USER_EMAIL}" ]]; then ADMIN_USER_EMAIL="${CLI_ADMIN_USER_EMAIL}"; fi

export MACHINE_IP
export CLUSTER_NAME
export PROJECT_ID
export REGION
export CLUSTER_VIP
export CLUSTER_INGRESS
export PRIMARY_LOAD_BALANCER
export ADMIN_USER_EMAIL
export PRIMARY_ROOT_REPO

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
printf "  %-35s %s\n" "Machine IP:" "${MACHINE_IP}"
printf "  %-35s %s\n" "Cluster VIP:" "${CLUSTER_VIP}"
printf "  %-35s %s\n" "Cluster Ingress:" "${CLUSTER_INGRESS}"
printf "  %-35s %s\n" "Primary Load Balancer:" "${PRIMARY_LOAD_BALANCER}"
printf "  %-35s %s\n" "Primary Root Repo:" "${PRIMARY_ROOT_REPO}"
printf "  %-35s %s\n" "GOOGLE_APP_CREDS:" "${GOOGLE_APP_CREDS}"
printf "  %-35s %s\n" "gcloud token authenticated:" "${GCLOUD_TOKEN_AUTH}"
echo "=============================================================================="

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

# Ensure workspace exists
sudo mkdir -p /var/gdc-install
sudo chown -R "$USER":"$USER" /var/gdc-install

# 2. Configure SSH Access
echo "[-] Configuring local SSH access..."
if [ ! -f "$HOME/.ssh/id_ed25519" ]; then
	ssh-keygen -t ed25519 -C "gdc-admin@local" -N "" -f "$HOME/.ssh/id_ed25519"
fi

if ! grep -F -x -q "$(cat "$HOME"/.ssh/id_ed25519.pub)" "$HOME/.ssh/authorized_keys" 2>/dev/null; then
	cat "$HOME/.ssh/id_ed25519.pub" >>"$HOME/.ssh/authorized_keys"
fi

sudo chown -R "$USER":"$USER" "$HOME/.ssh/"
chmod 700 "$HOME/.ssh/"
chmod 600 "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/id_ed25519"
chmod 644 "$HOME/.ssh/id_ed25519.pub"

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
  anthosBareMetalVersion: 1.35.300-gke.87
  gkeConnect:
    projectID: ${PROJECT_ID}
  controlPlane:
    nodePoolSpec:
      nodes:
        - address: ${MACHINE_IP}
  clusterNetwork:
    pods:
      cidrBlocks:
        - 10.200.0.0/16
    services:
      cidrBlocks:
        - 10.201.0.0/16
  loadBalancer:
    mode: bundled
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
    loginUser: ${USER}
EOF
else
	echo "[OK] Configuration file already exists at ${CLUSTER_CONFIG_FILE}"
fi

# 4. Initiate Cluster Inception
echo "[-] Executing Preflight Checks..."
GCP_ACCESS_TOKEN=$(gcloud auth application-default print-access-token)
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

	if [ -n "${ADMIN_USER_EMAIL:-}" ]; then
		echo "[-] ADMIN_USER_EMAIL is defined (${ADMIN_USER_EMAIL}). Creating ClusterRoleBinding..."
		sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gdc-primary-cluster-admins
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ${ADMIN_USER_EMAIL}
EOF
		echo "[OK] ClusterRoleBinding for ${ADMIN_USER_EMAIL} created."
	else
		echo "[-] ADMIN_USER_EMAIL is not defined. Skipping ClusterRoleBinding creation."
	fi
else
	echo "[!] Warning: /etc/kubernetes/admin.conf not found. Ensure the cluster creation completed successfully."
fi
