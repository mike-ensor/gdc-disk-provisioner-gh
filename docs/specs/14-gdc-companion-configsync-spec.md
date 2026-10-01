# GDC Companion Specification: ConfigSync & PrimaryRootRepo GitOps Integration

**Document Version:** 1.0.0  
**Target Application:** `gdc-companion` microservice & Web UI  
**Target Repository:** `gdc-companion`  
**Coordinated Feature:** GDC Disk Provisioner Post-Install ConfigSync Automation  
**Schema Authority:** `docs/machine-schema.json` (Draft-07)

---

## 1. Executive Summary

The Google Distributed Cloud (GDC) Bare Metal provisioning pipeline now supports automated Day-1/Day-2 GitOps onboarding via ConfigSync. The target bare-metal node expects the GDC Companion service (`GET /v1/machine-info/{mac}`) to serve cluster configuration that optionally defines a structured `primary_root_repo` supporting both **Git** and **OCI** registries, credential references in Google Secret Manager (GSM), and subfolder directory overrides.

This specification defines the required changes in `gdc-companion` across:
1. **JSON Schema & Validation** (updating the vendored `machine-schema.json`)
2. **Backend Data Models & Serde Serialization** (Rust / Axum)
3. **Database Migration & Variable Merge Logic**
4. **REST API Endpoints** (`/v1/machine-info/{mac}` and `/v1/machines`)
5. **Frontend Web UI / UX** (Cluster Configuration Form & Status Badges)
6. **Telemetry Ingestion & Status Reporting**

---

## 2. Data Contract & Schema Specifications

The configuration payload delivered by `GET /v1/machine-info/{mac}` must support the updated `.cluster` structure below.

### 2.1 Schema Definition (`docs/machine-schema.json`)

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
      "cluster_name": {
        "type": "string",
        "description": "Unique Kubernetes cluster identifier."
      },
      "config_sync_enabled": {
        "type": "boolean",
        "description": "Optional toggle to enable/install ConfigSync operator. Defaults to true.",
        "default": true
      },
      "primary_root_repo": {
        "description": "Primary RootSync repository configuration (git, oci, legacy string, or null).",
        "oneOf": [
          { "type": "string", "description": "Legacy OCI or Git URI string for backward compatibility." },
          { "type": "null", "description": "Omitted/unmanaged GitOps repository." },
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
                  "repo_url": {
                    "type": "string",
                    "format": "uri",
                    "description": "HTTPS or SSH repository URL."
                  },
                  "branch": {
                    "type": "string",
                    "default": "main",
                    "description": "Target Git branch for RootSync."
                  },
                  "gsm_secret_name": {
                    "type": "string",
                    "description": "Name of the secret in Google Secret Manager containing read-only credentials."
                  }
                }
              },
              "oci": {
                "type": "object",
                "required": ["image"],
                "properties": {
                  "image": {
                    "type": "string",
                    "description": "OCI container image artifact URI."
                  },
                  "gsa": {
                    "type": "string",
                    "description": "GCP Service Account name used for Workload Identity authentication."
                  },
                  "gsm_secret_name": {
                    "type": "string",
                    "description": "Name of the secret in Google Secret Manager containing registry pull credentials."
                  }
                }
              }
            }
          }
        ]
      },
      "primary_root_repo_auth_secret": {
        "type": ["string", "null"],
        "description": "Legacy auth secret field retained for backward compatibility."
      }
    }
  }
}
```

### 2.2 Operational Rules
1. **Precedence:** If both `git` and `oci` objects are provided, `git` takes precedence.
2. **Directory Resolution:** RootSync targets:
   $$\text{dir} = \text{"config/clusters/"} + (\text{cluster\_config\_name} \mathbin{\Vert} \text{cluster\_name})$$
3. **Secret Security:** Only secret *identifiers* (`gsm_secret_name`) are stored in `gdc-companion`. Plaintext passwords, tokens, and private keys must **never** be saved in Companion databases or transmitted in JSON configs.

---

## 3. Backend Implementation (`gdc-companion/src`)

### 3.1 Rust Data Structures (`src/models/cluster.rs` / `src/schemas.rs`)

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(untagged)]
pub enum PrimaryRootRepo {
    /// Legacy plain URL/image string
    Legacy(String),
    /// Structured configuration object
    Structured(StructuredRootRepo),
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct StructuredRootRepo {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cluster_config_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub git: Option<GitRepoConfig>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub oci: Option<OciRepoConfig>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GitRepoConfig {
    pub repo_url: String,
    #[serde(default = "default_git_branch")]
    pub branch: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gsm_secret_name: Option<String>,
}

fn default_git_branch() -> String {
    "main".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OciRepoConfig {
    pub image: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gsa: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gsm_secret_name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ClusterConfig {
    pub cluster_name: String,
    #[serde(default = "default_true")]
    pub config_sync_enabled: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub primary_root_repo: Option<PrimaryRootRepo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub primary_root_repo_auth_secret: Option<String>,
    pub networking: ClusterNetworking,
    pub fleet_cluster_labels: Vec<String>,
    #[serde(default)]
    pub cluster_admin_emails: Vec<String>,
}

fn default_true() -> bool {
    true
}
```

### 3.2 Database Migration (`migrations/YYYYMMDD_add_config_sync_fields.sql`)

If storing JSON directly in a `JSONB` column (`cluster_info` or `variables`):
- No schema alteration is strictly required, but existing validation constraints must be updated to accept the new schema.
- Default existing records to include `"config_sync_enabled": true`.

```sql
-- Migration: Backfill default config_sync_enabled if missing from existing JSON configs
UPDATE machines
SET configuration = jsonb_set(
    configuration,
    '{cluster,config_sync_enabled}',
    'true'::jsonb,
    true
)
WHERE configuration->'cluster' IS NOT NULL
  AND configuration->'cluster'->'config_sync_enabled' IS NULL;
```

---

## 4. Frontend UI / UX Requirements (`gdc-companion-ui`)

The Web UI must provide an intuitive, error-preventing interface for operators defining or editing cluster specifications.

```text
+-----------------------------------------------------------------------------------+
|  [x] Enable ConfigSync Operator                                                   |
+-----------------------------------------------------------------------------------+
|  Primary Root Repository (GitOps)                                                 |
|  ( ) None / Disabled     (*) Git Repository            ( ) OCI Registry Artifact  |
+-----------------------------------------------------------------------------------+
|  Git Repository Settings                                                          |
|                                                                                   |
|  Repository URL: *                                                                |
|  [ https://gitlab.com/retail-edge/customer-demos/dp-primary-root.git            ] |
|                                                                                   |
|  Branch:                                                                          |
|  [ main                                                                         ] |
|                                                                                   |
|  Authentication Credential:                                                       |
|  [ ext-git-creds                                                                ] |
|  ℹ️  Google Secret Manager secret name containing read-only PAT or SSH key.       |
|                                                                                   |
|  [▼] Advanced Directory Overrides                                                 |
|      Cluster Subfolder Override:                                                  |
|      [ overridden-name                                                          ] |
|      Target Sync Path: config/clusters/overridden-name/                           |
+-----------------------------------------------------------------------------------+
```

### 4.1 Form Behavior & Field Rules
1. **ConfigSync Toggle (`config_sync_enabled`):**
   - Checkbox or toggle switch. Defaults to **Checked** (`true`).
   - If unchecked, disable/hide the repository configuration inputs.
2. **Repository Type Segmented Selector:**
   - Three options: **None / Unmanaged**, **Git Repository**, and **OCI Registry Artifact**.
   - Dynamically swaps between Git and OCI input fieldsets.
3. **Git Fieldset:**
   - `repo_url` (Required): Text input with URL format validation (`https://` or `ssh://` or `git@`).
   - `branch` (Optional): Text input defaulting to placeholder `main`.
   - `gsm_secret_name` (Optional): Text input with helper text:
     *"Secret Manager secret name containing `token`/`password` or `ssh-privatekey`. Do not enter raw credentials."*
4. **OCI Fieldset:**
   - `image` (Required): Text input with container image format validation (e.g. `us-docker.pkg.dev/...`).
   - **Authentication Radio Buttons:**
     - `Workload Identity (GSA)` $\to$ Reveals `GSA Name` field (e.g., `sa-name` or `sa@project.iam...`).
     - `Registry Secret` $\to$ Reveals `GSM Secret Name` field.
     - `Public / None` $\to$ Clears authentication parameters.
5. **Cluster Config Name Override (`cluster_config_name`):**
   - Placed in a collapsible "Advanced Directory Settings" accordion.
   - Shows a live-updating preview badge of the final computed path:
     `Preview: config/clusters/<cluster_config_name || cluster_name>/`

---

## 5. Telemetry & Evidence Dashboard Display

During Stage 7, the node's `/usr/local/bin/gdc-collector` posts `/var/gdc-install/state/post-validation.json` to `POST /v1/machine-reports/ingest`.

### Ingested Evidence Structure:
```json
{
  "stage": "POST_CLUSTER",
  "status": "completed",
  "evidence": {
    "config_sync": {
      "enabled": true,
      "rootsync_applied": true,
      "source_type": "git",
      "cluster_sync_dir": "config/clusters/gdc-extreme-241",
      "status": "configured"
    }
  }
}
```

### Dashboard UX Component:
In the Machine Overview / Deployment Status card:
- Render a **GitOps / ConfigSync** badge:
  - 🟢 **Configured** (`rootsync_applied: true`)
  - 🔵 **Operator Only** (`enabled: true`, `rootsync_applied: false`)
  - ⚪ **Disabled** (`enabled: false`)
- Hover tooltip showing `source_type` and `cluster_sync_dir`.

---

## 6. Implementation Checklist for `gdc-companion`

- [ ] Sync `docs/machine-schema.json` from `gdc-disk-provisioner`.
- [ ] Implement Rust structs `StructuredRootRepo`, `GitRepoConfig`, and `OciRepoConfig` in `src/models/cluster.rs`.
- [ ] Update `merge_machine_config()` to handle structured `primary_root_repo` without overwriting peer values.
- [ ] Add unit tests verifying serialization and deserialization for Git, OCI, legacy string, and null payloads.
- [ ] Update Web UI form components to render the GitOps segmented control and dynamic fieldsets.
- [ ] Update the Machine Details view to surface GitOps configuration and post-cluster telemetry status.
