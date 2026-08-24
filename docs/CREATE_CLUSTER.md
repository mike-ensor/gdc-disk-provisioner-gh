# Creating a GDC Software-Only Cluster

This document outlines the steps and common pitfalls when creating a Google Distributed Cloud (GDC) Software-Only (bare-metal) cluster.

## Overview

GDC Turnup relies on a temporary, local bootstrap cluster (KIND) on the admin workstation to orchestrate the build of the target cluster. The bootstrap cluster runs operators (like `anthos-cluster-operator`) that connect to the target nodes over SSH, install the required packages, and bootstrap Kubernetes.

When using **Fleet Workload Identity Federation** (configured via the `baremetal.cluster.gke.io/enable-workload-identity-cluster-authentication: "true"` annotation), the orchestrator authenticates to Google Cloud APIs using an OIDC token tied to its Kubernetes Service Account, rather than a static JSON service account key.

## Common IAM Blocks & Solutions

When using Workload Identity Federation, the most common reason a cluster stalls in the `Provisioning` state is missing Google Cloud IAM permissions for the orchestrator's principal.

For a cluster named `gdc-default` in project `anthos-bare-metal-lab-1`, the principal making the API calls is:
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
export CLUSTER_NAME="gdc-default"

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
gcrKeyPath: /bmctl/fake.json # Fake path required when using Workload Identity
sshPrivateKeyPath: /home/gdc-admin/.ssh/id_ed25519
---
apiVersion: v1
kind: Namespace
metadata:
  name: "gdc-default" # Must match ${CLUSTER_NAME}
---
apiVersion: baremetal.cluster.gke.io/v1
kind: Cluster
metadata:
  name: "gdc-default" # Must match ${CLUSTER_NAME}
  namespace: "gdc-default" # Must match ${CLUSTER_NAME}
  annotations:
    baremetal.cluster.gke.io/enable-workload-identity-cluster-authentication: "true"
spec:
  type: standalone
  profile: edge
  anthosBareMetalVersion: 1.35.300-gke.87
  gkeConnect:
    projectID: anthos-bare-metal-lab-1
  controlPlane:
    nodePoolSpec:
      nodes:
        - address: 192.168.9.241 # Target Node IP
  clusterNetwork:
    pods:
      cidrBlocks:
        - 10.200.0.0/16 # Non-overlapping pod network
    services:
      cidrBlocks:
        - 10.201.0.0/16
  loadBalancer:
    mode: bundled
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

### 5a. Setup a cluster-admin user

One-line script **OR** create a file with multiple users. Unless using ConfigSync Primary Root Repo to create the ClusterRoleBinding, the RBAC needs to be created on the cluster.

```shell
sudo KUBECONFIG="/etc/kubernetes/admin.conf" \
     USER_EMAIL="michael.d.ensor@gmail.com" \
     kubectl apply -f - <<EOF
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
  name: ${USER_EMAIL}
EOF
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
