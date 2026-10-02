# GDC Companion Specification: ConfigSync Dual-Secret Architecture & UX Redesign

**Document Version:** 1.0.0  
**Target Application:** `gdc-companion` Microservice & Web UI (`gdc-companion-ui`)  
**Target Repository:** `gdc-companion`  
**Coordinated Feature:** GDC Disk Provisioner Dual-Secret Decoupling (`gsm-auth-secret`)  
**Schema Authority:** `docs/machine-schema.json` (Draft-07, updated in both repos)  
**Parent Specification:** [`docs/specs/14-gdc-companion-configsync-spec.md`](14-gdc-companion-configsync-spec.md)

---

## 1. Executive Summary & Problem Statement

In the original Day-1/Day-2 GitOps integration (Spec 14), `gdc-companion` supplied a single flat field: `gsm_secret_name`. This introduced a critical logic bug during physical edge cluster turnup:

1. **Naming Conflation**: The installer used `gsm_secret_name` as **both** the Google Cloud Secret Manager (GSM) source identifier (e.g., `es-git-creds`) and the Kubernetes target Secret name in `config-management-system`.
2. **Reconciler Authentication Stalls**: In many production and demo GitOps repositories (such as `dp-primary-root.git`), child or embedded RootSync manifests (e.g. `primary-rs-embed`) specifically hardcode `secretRef.name: git-creds`. When the GSM secret was named `es-git-creds`, Kubernetes only received `es-git-creds`, causing the embedded reconciler to stall permanently with:
   ```text
   KNV1061: Secret git-creds not found: create one to allow client authentication
   ```
3. **Regional Secret Requirements**: Regionalized Secret Manager secrets (e.g., `--location=us-west1` with user-managed replication) require passing `--location` to `gcloud secrets versions access`, which was previously omitted.

To eliminate this bug and technical debt, the schema has been updated to decouple the **GSM source secret** from the **Kubernetes target Secret** via a structured `gsm-auth-secret` object.

> **CRITICAL UX IMPACT:**  
> This change primarily affects the **User Experience (UX) and Web Interface** of `gdc-companion`. The frontend forms must be re-addressed to present clear, distinct inputs for the GSM source secret versus the in-cluster Kubernetes secret name, rather than a single ambiguous credential box.

---

## 2. Updated Data Contract (`machine-schema.json`)

The machine configuration returned by `GET /v1/machine-info/{mac}` must support the updated `.cluster.primary_root_repo.git` definition:

```json
{
  "cluster": {
    "cluster_name": "gdc-extreme-243",
    "config_sync_enabled": true,
    "primary_root_repo": {
      "cluster-config-name": "gdc-extreme-243",
      "git": {
        "repo-url": "https://gitlab.com/gcp-solutions-public/retail-edge/customer-demos/dp-primary-root.git",
        "branch": "main",
        "gsm-auth-secret": {
          "gsm-name": "es-git-creds",
          "gsm-location": "global",
          "k8s-name": "git-creds",
          "k8s-namespace": "config-management-system"
        }
      }
    }
  }
}
```

### 2.1 Field Specification

| JSON Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `repo-url` / `repo_url` | string (URL) | *Required* | Git repository clone URL (`https://`, `ssh://`, or `git@`). |
| `branch` | string | `"main"` | Target Git branch to sync. |
| `cluster-config-name` | string | `null` | Optional subfolder override under `config/clusters/`. |
| `gsm-auth-secret` | object | *Optional* | Structured secret mapping Google Secret Manager to Kubernetes. |
| `gsm-auth-secret.gsm-name` | string | *Required* | The secret identifier as stored in Google Cloud Secret Manager (e.g., `es-git-creds`). |
| `gsm-auth-secret.gsm-location` | string | `"global"` | Secret Manager location (`"global"`, or region e.g. `"us-west1"`, `"us-central1"`). |
| `gsm-auth-secret.k8s-name` | string | `gsm-name` | Target `Secret` name in Kubernetes referenced by RootSync `secretRef.name` (e.g. `git-creds`). |
| `gsm-auth-secret.k8s-namespace` | string | `"config-management-system"` | Target Kubernetes namespace where the secret is populated. |

*Backward Compatibility Note*: The provisioner continues to parse legacy flat `gsm_secret_name` and `primary_root_repo_auth_secret` if present, but `gdc-companion` should emit the structured `gsm-auth-secret` object for all new and updated machine records.

---

## 3. Frontend UI / UX Redesign Requirements (`gdc-companion-ui`)

The UI form in `gdc-companion` must be updated to clearly communicate the separation of the cloud secret from the cluster secret.

### 3.1 Proposed Wireframe Layout

```text
+---------------------------------------------------------------------------------------------------+
|  [x] Enable ConfigSync Operator (ACM)                                                             |
+---------------------------------------------------------------------------------------------------+
|  Primary Root Repository (GitOps)                                                                 |
|  ( ) None / Unmanaged        (*) Git Repository              ( ) OCI Registry Artifact             |
+---------------------------------------------------------------------------------------------------+
|  Git Repository Settings                                                                          |
|                                                                                                   |
|  Repository URL: *                                                                                |
|  [ https://gitlab.com/gcp-solutions-public/retail-edge/customer-demos/dp-primary-root.git        ] |
|                                                                                                   |
|  Branch:                                                                                          |
|  [ main                                                                                         ] |
|                                                                                                   |
|  +-- Repository Authentication (Google Secret Manager & In-Cluster Secret) ---------------------+ |
|  |  [x] Require Authentication for Repository                                                   | |
|  |                                                                                              | |
|  |  GSM Secret Name (GCP Source): *                                                             | |
|  |  [ es-git-creds                                                                            ] | |
|  |  ℹ️  The Secret ID in Google Cloud Secret Manager containing read-only PAT or SSH key.       | |
|  |                                                                                              | |
|  |  Secret Location / Replication:                                                              | |
|  |  [ Global (default)                                                                       ▼] | |
|  |  Options: global, us-west1, us-central1, us-east1, custom...                                    | |
|  |                                                                                              | |
|  |  Kubernetes Secret Name (Cluster Target): *                                                  | |
|  |  [ git-creds                                                                               ] | |
|  |  ℹ️  The Secret resource name created in Kubernetes. Must match 'secretRef.name' in RootSync. | |
|  |                                                                                              | |
|  |  Kubernetes Namespace:                                                                       | |
|  |  [ config-management-system                                                                ] | |
|  +----------------------------------------------------------------------------------------------+ |
|                                                                                                   |
|  [▼] Advanced Directory Overrides                                                                 |
|      Cluster Subfolder Override:                                                                  |
|      [ gdc-extreme-243                                                                          ] |
|      Target Sync Path: config/clusters/gdc-extreme-243/                                           |
+---------------------------------------------------------------------------------------------------+
```

### 3.2 Form Behavior & Interaction Rules

1. **Smart Defaulting / Autofill**:
   - When the operator types into **GSM Secret Name** (e.g., `git-creds`), automatically mirror the value into **Kubernetes Secret Name** unless the user has explicitly edited the Kubernetes Secret Name field.
   - If the operator specifies a known trait prefix (e.g., `es-git-creds`), display helper text:
     *“Tip: RootSync manifests in the repo (such as `primary-rs-embed`) typically expect `git-creds`. Ensure the Kubernetes Secret Name matches your repo manifests.”*
2. **Secret Location Selector**:
   - Provide a combobox/dropdown defaulting to `global`.
   - Allow selection of common GCP regions (`us-west1`, `us-central1`, `us-east1`) or typing a custom region.
3. **Form Validation**:
   - If "Require Authentication" is checked:
     - `gsm-name` is **Required** (RFC 1123 / GCP secret naming syntax: letters, numbers, hyphens, underscores).
     - `k8s-name` is **Required** (valid DNS-1123 subdomain: lowercase alphanumeric and hyphens).
     - `k8s-namespace` defaults to `config-management-system`.

---

## 4. Backend Rust Data Model Updates (`gdc-companion`)

In `gdc-companion/crates/models/src/` (or wherever machine configuration structs are defined):

### 4.1 Struct Definitions

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GsmAuthSecret {
    #[serde(rename = "gsm-name", alias = "gsm_name")]
    pub gsm_name: String,

    #[serde(rename = "gsm-location", alias = "gsm_location", default = "default_gsm_location")]
    pub gsm_location: String,

    #[serde(rename = "k8s-name", alias = "k8s_name", default = "default_k8s_name")]
    pub k8s_name: Option<String>,

    #[serde(rename = "k8s-namespace", alias = "k8s_namespace", default = "default_k8s_namespace")]
    pub k8s_namespace: String,
}

fn default_gsm_location() -> String {
    "global".to_string()
}

fn default_k8s_namespace() -> String {
    "config-management-system".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GitRepoConfig {
    #[serde(rename = "repo-url", alias = "repo_url")]
    pub repo_url: String,

    #[serde(default = "default_branch")]
    pub branch: String,

    #[serde(rename = "gsm-auth-secret", alias = "gsm_auth_secret", skip_serializing_if = "Option::is_none")]
    pub gsm_auth_secret: Option<GsmAuthSecret>,

    // Legacy fallback field
    #[serde(rename = "gsm_secret_name", skip_serializing_if = "Option::is_none")]
    pub gsm_secret_name: Option<String>,
}

fn default_branch() -> String {
    "main".to_string()
}
```

### 4.2 Legacy Migration / Ingestion Logic

When loading machine configurations from SQLite / PostgreSQL:
- If a record has legacy `gsm_secret_name: "es-git-creds"` and `primary_root_repo_auth_secret: "git-creds"`, deserialize or promote it automatically to:
  ```rust
  gsm_auth_secret: Some(GsmAuthSecret {
      gsm_name: "es-git-creds".to_string(),
      gsm_location: "global".to_string(),
      k8s_name: Some("git-creds".to_string()),
      k8s_namespace: "config-management-system".to_string(),
  })
  ```

---

## 5. Verification Checklist for `gdc-companion`

- [ ] Update `docs/machine-schema.json` in `gdc-companion` (already synchronized).
- [ ] Implement `GsmAuthSecret` model in Rust crates (`models` and `companion`).
- [ ] Run `cargo check` and `cargo test` in `gdc-companion`.
- [ ] Re-address the frontend form in `gdc-companion-ui`:
  - Split credential inputs into **GSM Secret Name** and **Kubernetes Secret Name**.
  - Add **Secret Location** dropdown (`global` default).
  - Add auto-mirroring from GSM Name to K8s Name with manual override capability.
- [ ] Verify endpoint `GET /v1/machine-info/{mac}` renders the structured `gsm-auth-secret` JSON payload.
- [ ] Test provisioned node output using `nomos status` on edge hardware.
