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
# This script provisions a Google Distributed Cloud (GDC) Bare Metal standalone
# cluster. It is designed to be idempotent: if the cluster is already running,
# it will safely skip the creation process.
# ==============================================================================

MACHINE_IP="${MACHINE_IP:-192.168.9.241}"
CLUSTER_NAME="${CLUSTER_NAME:-gdc-default-241}"
PROJECT_ID="${PROJECT_ID:-anthos-bare-metal-lab-1}"

CLUSTER_VIP="${CLUSTER_VIP:-192.168.9.143}"
CLUSTER_INGRESS="${CLUSTER_INGRESS:-192.168.9.144}"
PRIMARY_LOAD_BALANCER="${PRIMARY_LOAD_BALANCER:-192.168.9.144-192.168.9.150}"

ADMIN_USER_EMAIL="${ADMIN_USER_EMAIL:-}"
AUTO_YES=false
DRY_RUN=false
RESPONSE="y"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Provisions a Google Distributed Cloud (GDC) Bare Metal standalone cluster using bmctl.
Idempotent: skips creation if the cluster is already running.

Options:
  --name <NAME>          Cluster name (default: ${CLUSTER_NAME})
  --ip <IP>              Node machine IP (default: ${MACHINE_IP})
  --project <PROJECT>    GCP Project ID (default: ${PROJECT_ID})
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
        --name)
            CLUSTER_NAME="$2"
            shift 2
            ;;
        --ip)
            MACHINE_IP="$2"
            shift 2
            ;;
        --project)
            PROJECT_ID="$2"
            shift 2
            ;;
        --vip)
            CLUSTER_VIP="$2"
            shift 2
            ;;
        --ingress)
            CLUSTER_INGRESS="$2"
            shift 2
            ;;
        --lb-range)
            PRIMARY_LOAD_BALANCER="$2"
            shift 2
            ;;
        --admin-email)
            ADMIN_USER_EMAIL="$2"
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

export MACHINE_IP
export CLUSTER_NAME
export PROJECT_ID
export CLUSTER_VIP
export CLUSTER_INGRESS
export PRIMARY_LOAD_BALANCER
export ADMIN_USER_EMAIL

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

echo "=============================================================================="
echo "  NOTE: Temporary cluster creation process. DO NOT USE FOR PRODUCTION         "
echo "=============================================================================="
echo "Starting GDC Cluster Creation Process"
echo "  Cluster Name:          ${CLUSTER_NAME}"
echo "  Project ID:            ${PROJECT_ID}"
echo "  Machine IP:            ${MACHINE_IP}"
echo "  Cluster VIP:           ${CLUSTER_VIP}"
echo "  Cluster Ingress:       ${CLUSTER_INGRESS}"
echo "  Primary Load Balancer: ${PRIMARY_LOAD_BALANCER}"
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
    location: us-west1
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
    location: us-west1
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
