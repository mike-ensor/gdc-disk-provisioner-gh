# Design Specification: ConfigSync & PrimaryRootRepo Integration

**Date:** 2026-09-30  
**Status:** Approved  
**Author:** AI Agent & Michael Ensor  
**Target Branch:** `feature/configsync-primary-root-repo`  

---

## 1. Overview & Objectives

In Google Distributed Cloud (GDC) bare-metal environments, GitOps management is standard for Day-1/Day-2 operations. This design incorporates ConfigSync as a native post-install feature, driven by the machine configuration payload received from `gdc-companion` (or local fallback/manual facts).

### Key Requirements
1. **Schema Updates:** Expand `docs/machine-schema.json` to support both `git` and `oci` source types under `.cluster.primary_root_repo`.
2. **Cluster Directory Target:** Route GitOps synchronization to `config/clusters/<cluster-name>/` (recursively syncing subfolders `traits/`, `packages/`, `root/`), with an optional override via `cluster_config_name`.
3. **Secret Security & Bootstrapping:**
   - Secrets are **never** stored in plaintext inside the JSON configuration, ISO, or disk.
   - Credentials referenced by `gsm_secret_name` are pulled dynamically from Google Cloud Secret Manager (GSM) and piped directly into Kubernetes Secrets inside namespace `config-management-system`.
   - Workload Identity (`gcpserviceaccount`) is used for GSA-based OCI registries; Kubernetes Secrets with `auth: token` are used for external registries / PAT tokens.
4. **Fail-Fast Early Pre-flight:** Verify GSM secret existence and permissions during Stage 1 preflight before spending 15+ minutes turning up the cluster.
5. **Ansible Native Orchestration:** Implement the workflow cleanly inside Stage 7 (`post_cluster` role) with structured evidence tracking.
6. **Documentation & Release Workflow:** Update the quick-start and post-install guides with prerequisite IAM roles, implement on a feature branch, and submit a squashed Merge Request via `glab` for user review.

---

## 2. Schema Specification (`docs/machine-schema.json`)

The `.cluster` object is updated to support structured `primary_root_repo`:

```json
{
  "cluster": {
    "type": "object",
    "required": [
      "cluster_name",
      "networking",
      "fleet_cluster_labels"
    ],
    "properties": {
      "cluster_name": { "type": "string" },
      "config_sync_enabled": {
        "type": "boolean",
        "description": "Optional toggle to install ConfigSync operator. Defaults to true.",
        "default": true
      },
      "primary_root_repo": {
        "description": "Primary RootSync repository configuration (git or oci).",
        "oneOf": [
          { "type": "string", "description": "Legacy OCI or Git URI string for backward compatibility." },
          {
            "type": "object",
            "properties": {
              "cluster_config_name": {
                "type": "string",
                "description": "Optional override for cluster subfolder directory under config/clusters/."
              },
              "git": {
                "type": "object",
                "required": ["repo_url"],
                "properties": {
                  "repo_url": { "type": "string", "format": "uri" },
                  "branch": { "type": "string", "default": "main" },
                  "gsm_secret_name": {
                    "type": "string",
                    "description": "Secret Manager secret name containing read-only Git PAT / credentials."
                  }
                }
              },
              "oci": {
                "type": "object",
                "required": ["image"],
                "properties": {
                  "image": { "type": "string" },
                  "gsa": {
                    "type": "string",
                    "description": "GCP Service Account name for Workload Identity Artifact Registry access."
                  },
                  "gsm_secret_name": {
                    "type": "string",
                    "description": "Secret Manager secret name containing read-only registry pull credentials."
                  }
                }
              }
            }
          }
        ]
      }
    }
  }
}
```

---

## 3. Pre-flight Fail-Fast Validation (`src/ansible/stages/stage_preflight_checks.yml`)

Prior to node hardening and cluster creation:
1. Extract `gsm_secret_name` if `primary_root_repo` is defined (checking `git.gsm_secret_name` or `oci.gsm_secret_name`).
2. Run `gcloud secrets describe <gsm_secret_name> --project=<project_id>`.
3. Test read capability:
   ```bash
   gcloud secrets versions access latest --secret="<gsm_secret_name>" --project="<project_id>"
   ```
4. Parse and validate JSON structure:
   - For `git`: verify keys include `token` or `password` or `ssh-privatekey`.
   - For `oci`: verify keys include `username` and `password`.
5. If missing or unauthorized, fail pre-flight immediately with an actionable error.

---

## 4. Stage 7 Post-Cluster Execution (`src/ansible/roles/post_cluster/`)

New task file `src/ansible/roles/post_cluster/tasks/config_sync.yml`, imported from `src/ansible/roles/post_cluster/tasks/main.yml`:

```text
[ Post-Cluster Stage 7 ]
          │
          ▼
1. Check & Auto-enable Fleet feature:
   `gcloud beta container fleet config-management enable --project={{ gcp_project_id }}`
          │
          ▼
2. Apply ConfigManagement Operator Spec to Cluster Membership:
   `gcloud beta container fleet config-management apply --membership={{ membership }} --config=acm-config.yaml`
          │
          ▼
3. Wait for `rootsyncs.configsync.gke.io` CRD readiness in cluster (timeout: 180s)
          │
          ▼
4. Has `primary_root_repo`?
   ├── NO  --> Record ConfigSync enabled; skip RootSync; complete.
   └── YES --> Proceed to Step 5
          │
          ▼
5. Inject Bootstrap Secret (if `gsm_secret_name` defined):
   - Access secret via `gcloud secrets versions access latest` into in-memory variable
   - Pipe into `kubectl create secret generic {{ gsm_secret_name }} -n config-management-system --dry-run=client -o yaml | kubectl apply -f -`
   - Zero plaintext written to disk
          │
          ▼
6. Render & Apply `primary-root-repo.yaml`:
   - Calculate dir: `config/clusters/{{ primary_root_repo.cluster_config_name | default(cluster_name) }}`
   - Git branch: `auth: token` (or `ssh`), `secretRef: {{ gsm_secret_name }}`
   - OCI branch: `auth: gcpserviceaccount` (if GSA) OR `auth: token` with `secretRef`
          │
          ▼
7. Wait for RootSync reconciliation status and record evidence in `post_cluster_evidence`
```

---

## 5. Standalone Script Alignment (`bin/cluster/create_cluster.sh`)

Update `create_cluster.sh`:
- Refactor rudimentary steps 6 & 7 to read both string and dictionary `.cluster.primary_root_repo` representations.
- Let Ansible handle the full fleet and secret orchestration in Stage 7, ensuring `create_cluster.sh` does not collide if executed during automation.

---

## 6. Documentation & Quick Start Guide

Update `docs/CREATE_CLUSTER.md` and `docs/POST-INSTALL.md` with explicit prerequisite instructions:
- **Workload Identity Binding (if using OCI with GSA):**
  ```bash
  gcloud iam service-accounts add-iam-policy-binding "${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/iam.workloadIdentityUser" \
    --member="serviceAccount:${PROJECT_ID}.svc.id.goog[config-management-system/root-reconciler-primary-root-repo]"
  ```
- **Secret Manager Role:**
  The node's primary GSA must have `roles/secretmanager.secretAccessor` on the configured `gsm_secret_name`.

---

## 7. Verification & Testing Strategy

1. **Schema Validation:** Validate `docs/machine-schema.json` against mock files (`custom-data/machine-info-mock-net-9.json` and a new test fixture covering both Git and OCI).
2. **Pre-flight Unit Test:** Execute preflight tests to confirm validation catches missing secrets and passes valid mocks.
3. **Ansible Syntax & Lint Check:** Run `ansible-lint` and `ansible-playbook --syntax-check` on `src/ansible/local.yml`.
4. **Mock Turnup / Post-Cluster Verification:** Test the post_cluster role execution against a test cluster / mock environment verifying:
   - Secret injection in `config-management-system` without disk leakage.
   - Correct `RootSync` CR applied with computed `dir: config/clusters/<target_name>`.

---

## 8. Release & Git Workflow

1. Create a dedicated feature branch: `feature/configsync-primary-root-repo`.
2. Implement code, schema, and documentation changes.
3. Commit with structured conventional commit messages.
4. Push and open a GitLab Merge Request via `glab`:
   ```bash
   glab mr create --title "feat(configsync): add primary root repo support with GSM secret injection" --description "..." --squash-before-merge
   ```
5. Hand off to user for testing, review, and merge approval.
