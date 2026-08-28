#!/bin/bash
set -euo pipefail

# ==============================================================================
# GDC Standalone Cluster Creation Script (Idempotent)
# ==============================================================================
# This script provisions a Google Distributed Cloud (GDC) Bare Metal standalone
# cluster. It is designed to be idempotent: if the cluster is already running,
# it will safely skip the creation process.
# ==============================================================================

export MACHINE_IP="${MACHINE_IP:-192.168.9.241}"
export CLUSTER_NAME="${CLUSTER_NAME:-gdc-default-241}"
export PROJECT_ID="${PROJECT_ID:-anthos-bare-metal-lab-1}"

export CLUSTER_VIP="${CLUSTER_VIP:-192.168.9.143}"
export CLUSTER_INGRESS="${CLUSTER_INGRESS:-192.168.9.144}"
export PRIMARY_LOAD_BALANCER="${PRIMARY_LOAD_BALANCER:-192.168.9.144-192.168.9.150}"

export ADMIN_USER_EMAIL="${ADMIN_USER_EMAIL:-}"

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

## Add check for "are you sure"
read -r -p "Are you sure you want to run preflight and create cluster '${CLUSTER_NAME}'? (Y/n) " response
if [[ ! "$response" =~ ^([yY][eE][sS]|[yY]|"")$ ]]; then
	echo "Cluster creation aborted by user."
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

if ! grep -q "$(cat "$HOME"/.ssh/id_ed25519.pub)" "$HOME/.ssh/authorized_keys" 2>/dev/null; then
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
