# Examples: GDC Cluster Turnup Debugging

## Scenario: GCR Image Pull Failure due to Workload Identity

**Symptom:** The cluster is stalled in `Provisioning` state.
**Log extracted from `anthos-cluster-operator`:**
```
"msg"="failed to reconcile image pull secret" "error"="the controller principal failed token creator permission check for gcr service account \"baremetal-gcr@anthos-bare-metal-lab-1.iam.gserviceaccount.com\". Ensure it has the 'roles/iam.serviceAccountTokenCreator' role.
```

**Discovery:**
The `controller-workload-identity` ConfigMap reveals the cluster uses Workload Identity Federation. The `anthos-cluster-operator` is running in the `kube-system` namespace in project `anthos-bare-metal-lab-1`.

**The True Identity (Principal):**
`serviceAccount:anthos-bare-metal-lab-1.svc.id.goog[kube-system/anthos-cluster-operator]`

**The Fix:**
```bash
gcloud iam service-accounts add-iam-policy-binding baremetal-gcr@anthos-bare-metal-lab-1.iam.gserviceaccount.com \
  --member="serviceAccount:anthos-bare-metal-lab-1.svc.id.goog[kube-system/anthos-cluster-operator]" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="anthos-bare-metal-lab-1"
```

---

## Scenario: GKE Hub Feature Registration Failure

**Symptom:** The target cluster has built its nodes, but the `Cluster` resource is still in `Provisioning` and `kubectl describe cluster` shows events failing to enable features.

**Log extracted from Cluster Events:**
```
Warning  ReconciliationError  5m19s  cluster-controller  1 error occurred:
* failed to enable CloudAuditLogging in GKEHub: failed to get CloudAuditLogging feature. StatusCode: 403, Status: 403 Forbidden, ResponseBody: {
  "error": {
    "code": 403,
    "message": "Permission 'gkehub.features.get' denied on 'projects/anthos-bare-metal-lab-1/locations/global/features/cloudauditlogging'"
  }
}
```

**The Fix:**
The operator lacks permissions on the GCP project to manage GKE Hub features. Grant the `roles/gkehub.admin` role to the Workload Identity principal at the project level:
```bash
gcloud projects add-iam-policy-binding anthos-bare-metal-lab-1 \
  --member="serviceAccount:anthos-bare-metal-lab-1.svc.id.goog[kube-system/anthos-cluster-operator]" \
  --role="roles/gkehub.admin"
```
