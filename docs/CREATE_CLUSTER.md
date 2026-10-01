# Creating a GDC Software-Only Cluster

This document outlines the steps and common pitfalls when creating a Google Distributed Cloud (GDC) Software-Only (bare-metal) cluster.

## QUICK START

This is a quick start script, for more details, refer to `bin/cluster/create_cluster.sh` and the lower sections of this document.

:warning: NOTE: :warning: This `quick-script` assumes the GCP project has been configured with workload identity pools.

```shell
###################################################
##############  192.168 4.241  ####################
###################################################

export PROJECT_ID="your-gcp-project-id"
export REGION="us-west1"

export MACHINE_IP="192.168.4.241"
export CLUSTER_NAME="my-cluster-name"

export CLUSTER_VIP="192.168.4.100"
export CLUSTER_INGRESS="192.168.4.101"
export PRIMARY_LOAD_BALANCER="192.168.4.101-192.168.4.109"

export ADMIN_USER_EMAIL="admin-user@company.com"

# Create SSH for system admin user for passwordless SSH for Ansible
ssh-keygen -t ed25519 -C "gdc-admin@local" -N "" -f /home/gdc-admin/.ssh/id_ed25519
# Authorize the public key
cat /home/gdc-admin/.ssh/id_ed25519.pub >> /home/gdc-admin/.ssh/authorized_keys

# Secure permissions to only gdc-admin user
chown -R gdc-admin:gdc-admin /home/gdc-admin/.ssh/
chmod 700 /home/gdc-admin/.ssh/
chmod 600 /home/gdc-admin/.ssh/authorized_keys
chmod 600 /home/gdc-admin/.ssh/id_ed25519.pub

## Remove existing cluster config (if exists)
CLUSTER_CONFIG_FILE="/var/gdc-install/bmctl-workspace/${CLUSTER_NAME}/${CLUSTER_NAME}.yaml"
# Remove current Cluster Config runtime file
if [[ -f "${CLUSTER_CONFIG_FILE}" ]]; then
  # Question, do you want to remove the previous configuration?
  read -p "Are you sure (Y/n)? " -n 1 -r
  echo # new line for readability
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "${CLUSTER_CONFIG_FILE}"
  else
    echo "Keeping existing config file at '${CLUSTER_CONFIG_FILE}'"
  fi
fi

## Progress the build state sequence (artificially)
bash -c 'cat << EOF > /var/gdc-install/state/cluster-turnup.json
{
  "stage": "CLUSTER_TURNUP",
  "status": "in_progress",
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "evidence": {
    "override": "Manual cluster ingestion actively waiting on NodeAgent..."
  }
}
EOF'

export ADMIN_GSA="admin-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export GCR_GSA="baremetal-gcr@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding \
  "${GCR_GSA}" \
  --member="serviceAccount:${ADMIN_GSA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="${PROJECT_ID}"

gcloud iam service-accounts add-iam-policy-binding "${GCR_GSA}" \
  --member="serviceAccount:${ADMIN_GSA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="${PROJECT_ID}"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[kube-system/anthos-cluster-operator]" \
  --role="roles/gkehub.admin" \
  --project="${PROJECT_ID}"


# 2. Create cluster
/usr/local/bin/cluster/create_cluster.sh

# 3. Export Verified Kubeconfig and verify ConfigSync / RootSync status
export KUBECONFIG="/var/gdc-install/bmctl-workspace/${CLUSTER_NAME}/${CLUSTER_NAME}-kubeconfig"

# In the automated installation pipeline, Stage 7 (post_cluster) automatically
# enables Fleet Config Management, applies the ACM operator configuration (unstructured format),
# retrieves registry or Git secrets directly from GSM into memory, and creates the primary RootSync.

# Verify RootSync custom resource and reconciliation status:
kubectl get rootsync -n config-management-system
kubectl describe rootsync root-sync -n config-management-system

# Verify sync status via nomos or gcloud fleet:
nomos status --contexts="${CLUSTER_NAME}"
# Or via gcloud fleet:
gcloud beta container fleet config-management status --project="${PROJECT_ID}"
```

## Overview

GDC Turnup relies on a temporary, local bootstrap cluster (KIND) on the admin workstation to orchestrate the build of the target cluster. The bootstrap cluster runs operators (like `anthos-cluster-operator`) that connect to the target nodes over SSH, install the required packages, and bootstrap Kubernetes.

When using **Fleet Workload Identity Federation** (configured via the `baremetal.cluster.gke.io/enable-workload-identity-cluster-authentication: "true"` annotation), the orchestrator authenticates to Google Cloud APIs using an OIDC token tied to its Kubernetes Service Account, rather than a static JSON service account key.

## Common IAM Blocks & Solutions

When using Workload Identity Federation, the most common reason a cluster stalls in the `Provisioning` state is missing Google Cloud IAM permissions for the orchestrator's principal.

For a cluster named `my-cluster-name` in project `anthos-bare-metal-lab-1`, the principal making the API calls is:
`serviceAccount:anthos-bare-metal-lab-1.svc.id.goog[kube-system/anthos-cluster-operator]`

### 1. Image Pull Secret Failure

**Symptom:** The bootstrap cluster logs show `the controller principal failed token creator permission check for gcr service account "baremetal-gcr@..."`.

**Cause:** The operator needs permission to impersonate the GCR service account to generate a short-lived token to pull container images.

**Solution:** Grant the `roles/iam.serviceAccountTokenCreator` role to the Workload Identity principal on the GCR service account.

```bash
gcloud iam service-accounts add-iam-policy-binding baremetal-gcr@anthos-bare-metal-lab-1.iam.gserviceaccount.com \
  --member="serviceAccount:anthos-bare-metal-lab-1.svc.id.goog[kube-system/anthos-cluster-operator]" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="anthos-bare-metal-lab-1"
```

### 2. GKE Hub Feature Registration Failure

**Symptom:** The target nodes are successfully built and `Ready`, but the cluster remains in `Provisioning`. The `Cluster` resource events show a `403 Forbidden` error when trying to enable a feature like `CloudAuditLogging`.

**Cause:** The operator lacks permissions on the GCP project to manage GKE Hub (Fleet) features.

**Solution:** Grant the `roles/gkehub.admin` role to the Workload Identity principal at the project level.

```bash
gcloud projects add-iam-policy-binding anthos-bare-metal-lab-1 \
  --member="serviceAccount:anthos-bare-metal-lab-1.svc.id.goog[kube-system/anthos-cluster-operator]" \
  --role="roles/gkehub.admin"
```

## Important Notes on Propagation

After applying IAM policy bindings, you must account for **IAM Propagation Delay**. Google Cloud IAM changes, especially those involving Workload Identity Federation, can take **3 to 7 minutes** to fully propagate across global caches.

During this time, the operator's backoff loops may generate new `403 Permission Denied` errors. **Do not apply further changes or restart operators.** Wait for the backoff loops to naturally succeed once the permissions propagate.

---

## ConfigSync & PrimaryRootRepo Prerequisites

GDC Software-Only clusters support automated GitOps synchronization via Anthos Config Management (ConfigSync) and primary root repositories (`.cluster.primary_root_repo`). Both Git repositories and OCI registries are supported as synchronization sources.

Before cluster provisioning begins, ensure the following Google Cloud IAM roles, Secret Manager secrets, and repository structures are established.

### 1. Google Secret Manager (GSM) Secret Formats

When syncing from private repositories requiring authentication, store credentials as a single JSON object within Google Secret Manager. The GDC installer extracts these credentials dynamically into memory and streams them directly into the `config-management-system` namespace without writing unencrypted secrets to disk.

#### Create Secret Container:
First, create the secret container in Google Secret Manager before adding versions:
```bash
gcloud secrets create "${GSM_SECRET_NAME}" \
  --replication-policy="automatic" \
  --project="${PROJECT_ID}"
```

Then add the secret version payload:

#### For OCI Registry Pull:
```bash
echo -n '{"username":"your-registry-user","password":"your-pat-or-token"}' | \
  gcloud secrets versions add "${GSM_SECRET_NAME}" --data-file=- --project="${PROJECT_ID}"
```

#### For Git with PAT:
```bash
echo -n '{"username":"git-user","token":"your-personal-access-token"}' | \
  gcloud secrets versions add "${GSM_SECRET_NAME}" --data-file=- --project="${PROJECT_ID}"
```

#### For Git with SSH:
```bash
echo -n '{"ssh-privatekey":"-----BEGIN OPENSSH PRIVATE KEY-----\n..."}' | \
  gcloud secrets versions add "${GSM_SECRET_NAME}" --data-file=- --project="${PROJECT_ID}"
```

### 2. IAM Permissions & Workload Identity Bindings

#### Secret Manager Accessor Role for Node Primary GSA:
The node's primary Google Service Account (`gcp_info.primary_gsa`) requires the `roles/secretmanager.secretAccessor` role to retrieve pull credentials during pre-flight checks and Stage 7 secret injection:
```bash
export PRIMARY_GSA="sa@${PROJECT_ID}.iam.gserviceaccount.com" # Full GSA email address

gcloud secrets add-iam-policy-binding "${GSM_SECRET_NAME}" \
  --member="serviceAccount:${PRIMARY_GSA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}"
```

#### Workload Identity Binding (when using OCI with GSA):
When using an OCI registry on Google Cloud (e.g., Artifact Registry) authenticated via Google Service Account (GSA) without static secrets, bind the GSA to the ConfigSync root reconciler Kubernetes Service Account using Workload Identity Federation:
```bash
gcloud iam service-accounts add-iam-policy-binding "${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[config-management-system/root-reconciler]" \
  --project="${PROJECT_ID}"
```
*(Note: ConfigSync names the reconciler ServiceAccount after the RootSync resource name: for `name: root-sync`, the ServiceAccount is `root-reconciler`).*

### 3. Repository Directory Structure

ConfigSync uses `sourceFormat: unstructured` and syncs cluster configurations from a designated subfolder within the repository or OCI image. By default, this directory resolves to:
```text
config/clusters/<cluster-name>/
```
You can override the target cluster directory name using `.cluster.primary_root_repo.cluster_config_name` in your machine configuration.

A recommended directory layout within the repository:
```text
config/
└── clusters/
    └── <cluster-name>/        # Or <cluster_config_name> if overridden
        ├── traits/            # Shared cluster traits (e.g. logging, monitoring)
        ├── packages/          # Deployed applications and workloads
        └── root/              # Base cluster definitions and namespaces
```

### 4. Machine Configuration Examples

#### Git Repository with GSM Token:
```json
{
  "cluster": {
    "cluster_name": "edge-cluster-01",
    "config_sync_enabled": true,
    "primary_root_repo": {
      "git": {
        "repo_url": "https://gitlab.com/retail-edge/clusters.git",
        "branch": "main",
        "gsm_secret_name": "git-creds"
      }
    }
  }
}
```

#### Git Repository with SSH Key:
```json
{
  "cluster": {
    "cluster_name": "edge-cluster-01",
    "config_sync_enabled": true,
    "primary_root_repo": {
      "git": {
        "repo_url": "git@github.com:my-org/clusters.git",
        "branch": "main",
        "gsm_secret_name": "git-ssh-key"
      }
    }
  }
}
```

#### OCI Registry with Google Service Account (Workload Identity):
```json
{
  "cluster": {
    "cluster_name": "edge-cluster-01",
    "config_sync_enabled": true,
    "primary_root_repo": {
      "cluster_config_name": "edge-tier-1",
      "oci": {
        "image": "us-docker.pkg.dev/my-project/edge-manifests/root:v1.0.0",
        "gsa": "config-sync-reader"
      }
    }
  }
}
```

#### OCI Registry with GSM Credentials:
```json
{
  "cluster": {
    "cluster_name": "edge-cluster-01",
    "config_sync_enabled": true,
    "primary_root_repo": {
      "oci": {
        "image": "ghcr.io/my-org/edge-manifests:v1.0.0",
        "gsm_secret_name": "ext-oci-secret"
      }
    }
  }
}
```

---

## Static Manual Cluster Creation (WIP)

> **Note:** This section describes the current static, manual method to orchestrate a cluster. Eventually, this process will be fully automated through the GDC Companion and Ansible state machine, **but not yet**.

### 1. Configure SSH Access

The `bmctl` orchestrator requires SSH key-pair access to the target nodes, even for single-node standalone clusters.

Generate a new key-pair and authorize it locally:

```bash
# Generate the SSH key
ssh-keygen -t ed25519 -C "gdc-admin@local" -N "" -f /home/gdc-admin/.ssh/id_ed25519

# Authorize the public key
cat /home/gdc-admin/.ssh/id_ed25519.pub >> /home/gdc-admin/.ssh/authorized_keys

# Secure permissions
chown -R gdc-admin:gdc-admin /home/gdc-admin/.ssh/
chmod 700 /home/gdc-admin/.ssh/
chmod 600 /home/gdc-admin/.ssh/authorized_keys
chmod 600 /home/gdc-admin/.ssh/id_ed25519.pub
```

### 2. Generate the Cluster Configuration

Use `bmctl` to scaffold the initial cluster configuration file. Be sure to define non-overlapping CIDRs for the bootstrap KIND cluster to prevent networking collisions.

```bash
cd /var/gdc-install
export CLUSTER_NAME="my-cluster-name"

# Export GCP credentials for GKE Connect / Fleet registration
export GCP_ACCESS_TOKEN=$(gcloud auth application-default print-access-token)

# Scaffold the configuration file
bmctl create config -c "${CLUSTER_NAME}" \
  --bootstrap-cluster-pod-cidr="10.200.10.0/16" \
  --bootstrap-cluster-service-cidr="100.200.20.0/24"
```

### 3. Modify the Cluster Spec

Open the generated configuration file at `/var/gdc-install/bmctl-workspace/${CLUSTER_NAME}/${CLUSTER_NAME}.yaml` and modify it to match your target environment.

Below is a reference configuration for an Edge-profile standalone cluster using Workload Identity Federation:

```yaml
---
sshPrivateKeyPath: /home/gdc-admin/.ssh/id_ed25519
---
apiVersion: v1
kind: Namespace
metadata:
  name: "my-cluster-name" # Must match ${CLUSTER_NAME}
---
apiVersion: baremetal.cluster.gke.io/v1
kind: Cluster
metadata:
  name: "my-cluster-name" # Must match ${CLUSTER_NAME}
  namespace: "my-cluster-name" # Must match ${CLUSTER_NAME}
  annotations:
    baremetal.cluster.gke.io/enable-workload-identity-cluster-authentication: "true"
spec:
  type: standalone
  profile: edge
  anthosBareMetalVersion: 1.35.300-gke.87
  gkeConnect:
    projectID: anthos-bare-metal-lab-1
    location: us-west1
  controlPlane:
    nodePoolSpec:
      nodes:
        - address: 192.168.9.241 # Target Node IP
  clusterNetwork:
    bundledIngress: false
    flatIPv4: false
    pods:
      cidrBlocks:
        - 172.28.0.0/16 # Non-overlapping pod network
    services:
      cidrBlocks:
        - 172.29.0.0/20
  loadBalancer:
    mode: bundled
    type: layer2
    ports:
      controlPlaneLBPort: 443
    vips:
      controlPlaneVIP: 192.168.9.143 # Outside the address pool
      ingressVIP: 192.168.9.144 # Must be inside the address pool
    addressPools:
      - name: primary-load-balancer
        addresses:
          - 192.168.9.144-192.168.9.150
  clusterOperations:
    projectID: anthos-bare-metal-lab-1
    location: us-west1
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
    location: us-west1
  nodeAccess:
    loginUser: gdc-admin # The SSH user authorized above
```

### 4. Preflight Check & Inception

Once the configuration is finalized, validate the target machine and initiate the cluster build.

```bash
# Verify the target machine meets all GDC bare-metal prerequisites
bmctl check preflight --cluster "${CLUSTER_NAME}"

# Initiate cluster inception (this will take 15-30 minutes)
bmctl create cluster -c "${CLUSTER_NAME}"
```

### 5a. Setup cluster-admin users (RBAC)

The cluster turnup script (`create_cluster.sh`) automatically creates two distinct `ClusterRoleBinding` resources:

1. **Automated Admin User (`automated-admin-email`)**: Created when `--admin-email` or `$ADMIN_USER_EMAIL` is supplied.
2. **Dynamic Installed Cluster Admins (`dynamic-installed-cluster-admin-list`)**: Ingested directly from `.cluster.cluster_admin_emails` (array of strings) in the facts JSON.

#### Manifest Examples

**Automated Admin Binding (`cluster-admin-automated.yaml`):**
```yaml
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
  name: user@company.com
```

**Dynamic Admin List Binding (`cluster-admins-dynamic.yaml`):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dynamic-installed-cluster-admin-list
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ensor@google.com
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: michael.d.ensor@gmail.com
```

### 5b. (OPTIONAL) Get Local Credentials

Optionally setup local credentials when SSH'd into the box. Normal interaction is performed through gke-connect gateway

1.  ```shell
    # Get cluster-admin credentials to the bmctl-workspace/{cluster-name}/{cluster-name}-{date-time}-kubeconfig
    sudo bmctl get credentials --cluster ${CLUSTER_NAME} --admin-kubeconfig /etc/kubernetes/admin.conf
    sudo chown gdc-admin:gdc-admin "bmctl-workspace/${CLUSTER_NAME}/${CLUSTER_NAME}-kubeconfig"
    export KUBECONFIG="/var/gdc-install/bmctl-workspace/${CLUSTER_NAME}/${CLUSTER_NAME}-kubeconfig"
    ```
1.  Add the KUBECONFIG to the bash profile:

```shell
echo "export KUBECONFIG=\"/var/gdc-install/bmctl-workspace/${CLUSTER_NAME}/${CLUSTER_NAME}-kubeconfig\"" >> ~/.bashrc
```

### 6. Get Remote Credentials using GKE Connect (PREFERRED)

Performed from any internet connected computer/shell, use [gke-connect](https://docs.cloud.google.com/sdk/gcloud/reference/container/fleet/memberships/get-credentials)

```shell
# Get cluster-admin credentials to the bmctl-workspace/{cluster-name}/{cluster-name}-{date-time}-kubeconfig
gcloud container fleet memberships get-credentials ${CLUSTER_NAME} --project "${PROJECT_ID}"
```

### AUX

```shell
# Get the new config via GKE Connect
gcloud container fleet memberships get-credentials ${CLUSTER_NAME} --project ${PROJECT_ID}
```
