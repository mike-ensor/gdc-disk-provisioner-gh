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
  --root-repo <IMG>      OCI image for primary RootSync (default: ${ENV_PRIMARY_ROOT_REPO:-none})
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
        --root-repo|--primary-root-repo)
            CLI_PRIMARY_ROOT_REPO="$2"
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

get_json_array() {
    local file="$1"
    local jsonpath="$2"
    if [[ ! -f "$file" ]]; then
        return
    fi
    if command -v jq >/dev/null 2>&1; then
        jq -r "${jsonpath} // [] | .[]" "$file" 2>/dev/null || true
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "
import json
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
    if isinstance(val, list):
        for item in val:
            if item is not None and str(item).strip():
                print(str(item).strip())
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

FACT_CLUSTER_NAME=""
FACT_PROJECT_ID=""
FACT_REGION=""
FACT_CLUSTER_VIP=""
FACT_CLUSTER_INGRESS=""
FACT_PRIMARY_LOAD_BALANCER=""
FACT_IP_CIDR=""
FACT_ADMIN_USER_EMAIL=""
FACT_PRIMARY_ROOT_REPO=""
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
    FACT_PRIMARY_ROOT_REPO=$(get_json_val "${FACTS_FILE}" ".cluster.primary_root_repo")
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
printf "  %-35s %s\n" "Primary Root Repo:" "${PRIMARY_ROOT_REPO:-none}"
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

	# 6. Deploy Config Sync
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
	gcloud beta container fleet config-management apply \
		--membership="${MEMBERSHIP}" \
		--config="${APPLY_SPEC_FILE}" \
		--project="${PROJECT_ID}"
	echo "[OK] Config Sync deployment initiated for ${CLUSTER_NAME}."

	# 7. Deploy OCI Primary RootSync (if specified)
	if [[ -n "${PRIMARY_ROOT_REPO}" && "${PRIMARY_ROOT_REPO}" != "none" ]]; then
		echo "[-] Deploying Primary RootSync for OCI image: ${PRIMARY_ROOT_REPO}..."
		echo "[-] Waiting for RootSync CRD to be established..."
		for i in {1..30}; do
			if sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl get crd rootsyncs.configsync.gke.io &>/dev/null; then
				break
			fi
			sleep 2
		done

		if ! sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl get crd rootsyncs.configsync.gke.io &>/dev/null; then
			echo "[!] ERROR: Timed out waiting for rootsyncs.configsync.gke.io CRD to be established." >&2
			exit 1
		fi

		ROOTSYNC_FILE="${CLUSTER_CONFIG_DIR}/rootsync-primary.yaml"
		echo "[-] Generating RootSync manifest for primary root repo..."
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
    dir: .
    auth: k8sserviceaccount
EOF

		echo "[-] Applying RootSync 'root-sync' to cluster..."
		sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f "${ROOTSYNC_FILE}"
		echo "[OK] Primary RootSync deployed successfully."
	else
		echo "[-] No primary root repo specified. Skipping RootSync deployment."
	fi
else
	echo "[!] Warning: /etc/kubernetes/admin.conf not found. Ensure the cluster creation completed successfully."
fi
