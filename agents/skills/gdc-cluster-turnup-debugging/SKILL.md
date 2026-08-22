---
name: gdc-cluster-turnup-debugging
description: >
  Debugging methodology for GDC Software-Only Cluster Turnup.
  Use when a bare-metal cluster installation is stalled, hanging, or failing.
version: 1.0.0
author: GDC Core
tags:
  - gdc
  - debugging
  - bare-metal
  - kubernetes
---

# GDC Cluster Turnup Debugging

## Overview

A structured workflow for identifying and resolving issues during Google Distributed Cloud (GDC) Software-Only (bare-metal) cluster turnup. Since GDC Turnup relies on an ephemeral, local bootstrap cluster (KIND) to orchestrate the build, debugging the *target* cluster requires extracting logs and status directly from the *bootstrap* operators.

## When to Use

- A GDC bare-metal cluster installation is stalled, hanging, or failing.
- The target `Cluster` object remains in a `Provisioning` state.
- Target nodes are not receiving their configurations or joining the cluster.
- The installation fails with `ReconciliationError` or stalls waiting for the kubeconfig.

## Process

### Phase 1: Environment Discovery
Locate and connect to the ephemeral bootstrap cluster running on the admin workstation.

1. **Locate the KIND container:**
   Check for the KIND Docker container on the admin/target node:
   ```bash
   sudo docker ps | grep kindest/node
   ```
   *Note: The container is typically named `bmctl-control-plane`.*

2. **Locate the Workspace:**
   Find the `bmctl-workspace` directory containing the configuration and credentials. It is usually found in `/var/gdc-install/bmctl-workspace/` or `/var/gdc-admin/bmctl-workspace/`.

3. **Set KUBECONFIG:**
   Export the KUBECONFIG to the hidden `.kindkubeconfig` file:
   ```bash
   export KUBECONFIG=/path/to/bmctl-workspace/.kindkubeconfig
   ```

### Phase 2: Status & Resource Inspection
Determine the high-level health of the cluster and identify stalled Custom Resources (CRDs).

1. **Check Bootstrap Health:**
   ```bash
   kubectl get nodes
   kubectl get pods -A
   ```
   Ensure core operators like `anthos-cluster-operator` and `capi-controller-manager` are running.

2. **Inspect CRDs:**
   ```bash
   kubectl get baremetalclusters,clusters,machines,baremetalmachines -A
   kubectl describe cluster -A
   kubectl describe nodepool -A
   ```
   Look closely at the `Status.Conditions` and `Events` for `ReconciliationError` messages, such as `Secret "<cluster-name>-kubeconfig" not found`.

### Phase 3: Operator Log Extraction & Analysis
Extract the exact error from the specific operator responsible for the stalled resource.

1. **Find Operator Pod:**
   Locate the specific operator pod causing the issue (e.g., `anthos-cluster-operator`):
   ```bash
   kubectl get pods -n kube-system -l k8s-app=anthos-cluster-operator
   ```

2. **Extract Logs:**
   Tail the logs for errors related to permissions, secrets, or API failures:
   ```bash
   kubectl logs -n kube-system deploy/anthos-cluster-operator -c operator
   ```
   *Look for:* `failed to reconcile image pull secret` or `permission check for gcr service account`.

### Phase 4: Identity & Credential Tracing (Workload Identity)
Identify the *true* identity of the "controller principal" making the API request.

1. **Inspect Workload Identity:**
   If the cluster uses Fleet Workload Identity Federation, verify the projected credentials:
   ```bash
   kubectl get configmap controller-workload-identity -n kube-system -o yaml
   kubectl get secret google-cloud-credentials -n kube-system -o jsonpath='{.data.credentials\.json}' | base64 --decode
   ```

2. **Determine the Principal:**
   If the credential shows an `"external_account"` mapping to an `identitynamespace`, the identity is projected from the Kubernetes Service Account.
   The format is: `serviceAccount:<PROJECT_ID>.svc.id.goog[<NAMESPACE>/<KSA>]`
   *(e.g., `serviceAccount:anthos-bare-metal-lab-1.svc.id.goog[kube-system/anthos-cluster-operator]`)*.

### Phase 5: Resolution & Verification
Apply the correct fix and understand the API telemetry indicating progress.

1. **Apply IAM Bindings:**
   Grant the required role to the correct principal (not just the target GCP service account):
   ```bash
   gcloud iam service-accounts add-iam-policy-binding <TARGET_GCP_SA> \
     --member="serviceAccount:<PROJECT_ID>.svc.id.goog[<NAMESPACE>/<KSA>]" \
     --role="roles/iam.serviceAccountTokenCreator" \
     --project="<PROJECT_ID>"
   ```

   *If the error is related to GKE Hub Features (like CloudAuditLogging), grant the role on the Project instead:*
   ```bash
   gcloud projects add-iam-policy-binding <PROJECT_ID> \
     --member="serviceAccount:<PROJECT_ID>.svc.id.goog[<NAMESPACE>/<KSA>]" \
     --role="roles/gkehub.admin"
   ```

2. **Acknowledge Propagation Delays:**
   After applying IAM bindings, monitor the `NodePool` events. You may observe a new `403 Permission Denied` error for a few minutes. 
   **Do not apply further changes.** IAM policy bindings (especially for Workload Identity Federation) typically take 3 to 7 minutes to propagate globally. Wait for the backoff loops to succeed.

## Output Format

When executing this skill, provide the user with:
1. The status of the bootstrap cluster connection.
2. The specific operator and log line causing the stall.
3. The exact GCP principal and command needed to remediate the issue.
4. A warning regarding GCP IAM propagation delays.

## Notes

- **Never** assume standard Google Service Account credentials. Always check the Workload Identity ConfigMap (`controller-workload-identity`) to understand *how* the operator is authenticating.
- **Do not** manually restart operator pods unnecessarily; they run in exponential backoff loops and will recover naturally once IAM propagation completes.
- **Always** ensure your shell sessions export the hidden `.kindkubeconfig` before running `kubectl` commands against the bootstrap cluster.
