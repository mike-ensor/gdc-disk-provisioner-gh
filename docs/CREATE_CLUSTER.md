# Creating a GDC Software-Only Cluster

This document outlines the steps and common pitfalls when creating a Google Distributed Cloud (GDC) Software-Only (bare-metal) cluster. 

## Overview

GDC Turnup relies on a temporary, local bootstrap cluster (KIND) on the admin workstation to orchestrate the build of the target cluster. The bootstrap cluster runs operators (like `anthos-cluster-operator`) that connect to the target nodes over SSH, install the required packages, and bootstrap Kubernetes.

When using **Fleet Workload Identity Federation** (configured via the `baremetal.cluster.gke.io/enable-workload-identity-cluster-authentication: "true"` annotation), the orchestrator authenticates to Google Cloud APIs using an OIDC token tied to its Kubernetes Service Account, rather than a static JSON service account key.

## Common IAM Blocks & Solutions

When using Workload Identity Federation, the most common reason a cluster stalls in the `Provisioning` state is missing Google Cloud IAM permissions for the orchestrator's principal.

For a cluster named `gdc-test-241` in project `anthos-bare-metal-lab-1`, the principal making the API calls is:
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
