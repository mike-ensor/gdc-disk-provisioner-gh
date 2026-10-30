# GDC Specification: Custom Playbook Lifecycle Extensions

**Document Version:** 2.0.0  
**Status:** Approved for Implementation  
**Tracking Issue:** Issue #19 (`Investigate using a playbook as the "create-cluster" and "post-cluster" phases`)  
**Target Repository:** `gdc-disk-provisioner`  
**Related Specification:** `docs/specs/18-gdc-companion-bundle-service-spec.md`  

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Statement
Google Distributed Cloud (GDC) bare-metal installations follow an opinionated, multi-stage provisioning lifecycle (`first-boot` $\rightarrow$ `second-boot` $\rightarrow$ `linux-ready` $\rightarrow$ `cluster-ready` $\rightarrow$ `cluster-turnup` $\rightarrow$ `post-cluster` $\rightarrow$ `upkeep`). While this pipeline reliably deploys hardened operating systems and bare-metal Kubernetes clusters, platform engineering and customer operations teams require a modular mechanism to:
1. Extend stage behaviors without forking or maintaining custom ISO builds.
2. Execute automated, post-cluster hardware and application **burn-in suites** (e.g. stress-testing node local storage, validating networking ingress, and testing container runtime throughput).
3. Validate and trigger customized post-deployment configurations, Day-2 maintenance, and service reconciliations.
4. Distribute stage-scoped auxiliary binaries, OCI image archives, and OS package archives alongside stage playbooks in an organized, declarative structure.

### 1.2 Solution Overview
This specification defines the **Post-Stage Lifecycle Extension Framework** powered by an external Ansible playbook bundle:
* **Zero-Configuration Default:** If no custom bundle is configured or present on disk, the system runs with zero overhead and zero operational changes.
* **Stage 5 (`CLUSTER_READY`) Ingestion:** The node discovers, authenticates, downloads (or checks for sideloaded media), validates SHA-256 integrity, unpacks into `/var/gdc-install/bundle/`, asserts `manifest.yaml` and `VERSION` compliance, and resolves dependencies (`requirements.yml`).
* **Declarative Manifest Authority:** `manifest.yaml` serves as the authoritative definition of bundle identity and enabled lifecycle stages. Only stages explicitly declared in `manifest.yaml.stages` are executed across Stages 5, 6, 7, and 8 (`cluster_ready`, `cluster_turnup`, `post_cluster`, `upkeep`).
* **Hierarchical Asset Conventions:** Each stage folder encapsulates its tasks (`<stage>/playbook.yaml`) and optional asset folders (`bin/`, `oci/`, `pkg/`).
* **Asset Context Variables:** The lifecycle runner exposes standard variables (`bundle_root_dir`, `bundle_stage_dir`, `bundle_bin_dir`, `bundle_oci_dir`, `bundle_pkg_dir`) to playbooks.
* **Strict Failure Attribution:** If a custom play fails, the stage fails with clear telemetry attributing the error to the external playbook bundle, recording bundle metadata, stage, and log paths.

---

## 2. Architecture & Data Flow

```
+-----------------------------------------------------------------------------------------+
|                                    STAGE 5: CLUSTER_READY                               |
|                                                                                         |
| 1. Query machine-info (Companion / gdc.fact)                                            |
| 2. Provision Node mTLS Certs (provision-mtls-cert.sh)                                    |
| 3. Execute custom_extensions Role:                                                      |
|    +-------------------------------------------------------------------------------+    |
|    | - Detect bundle source (Bearer Token + mTLS GET or /var/gdc-install/sideload) |    |
|    | - Verify SHA-256 Checksum                                                     |    |
|    | - Extract to /var/gdc-install/bundle/                                          |    |
|    | - Validate manifest.yaml schema, VERSION match, and declared playbooks        |    |
|    | - Persist validated manifest to /var/gdc-install/state/bundle-manifest.json   |    |
|    | - Install requirements.yml (via ansible-galaxy if present)                     |    |
|    | - Run cluster_ready/playbook.yaml with asset context (if declared in manifest)|    |
|    +-------------------------------------------------------------------------------+    |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 6: CLUSTER_TURNUP                              |
|                                                                                         |
| 1. Core Cluster Inception (create_cluster.sh --yes)                                     |
| 2. Shared Extension Runner (execute_custom_stage.yml):                                  |
|    - Inspect /var/gdc-install/state/bundle-manifest.json                                |
|    - Gate: Is cluster_turnup declared in manifest? If not -> skip                       |
|    - If declared -> run cluster_turnup/playbook.yaml with asset context                 |
|    - On failure -> set custom_extension failure evidence, mark failed, halt             |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 7: POST_CLUSTER                                |
|                                                                                         |
| 1. Core Platform Validation (Nodes Ready, CoreDNS, StorageClass, ConfigSync)            |
| 2. Shared Extension Runner (execute_custom_stage.yml):                                  |
|    - Inspect /var/gdc-install/state/bundle-manifest.json                                |
|    - Gate: Is post_cluster declared in manifest? If not -> skip                         |
|    - If declared -> run post_cluster/playbook.yaml with asset context                   |
|    - On failure -> set custom_extension failure evidence, mark failed, halt             |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 8: UPKEEP                                      |
|                                                                                         |
| 1. Core Node & Cluster Upkeep (health assertions, certificate renewals)                 |
| 2. Shared Extension Runner (execute_custom_stage.yml):                                  |
|    - Inspect /var/gdc-install/state/bundle-manifest.json                                |
|    - Gate: Is upkeep declared in manifest? If not -> skip                               |
|    - If declared -> run upkeep/playbook.yaml with asset context                         |
|    - On failure -> set custom_extension failure evidence, mark failed, halt             |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Data Contract & Machine Facts

The node receives custom extension configuration through the `machine-info` payload (`GET /v1/machine-info/{mac}` or `/var/gdc-install/state/gdc-fact-manual.json`) rendered to `/etc/ansible/facts.d/gdc.fact`:

```json
{
  "custom_extensions": {
    "bundle_url": "https://companion.internal/v1/bundles/burnin-suite-v1.2.tar.gz",
    "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
  }
}
```

### Field Definitions:
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `custom_extensions` | Object | Optional | Container for extension settings. Omitted or `null` if no extensions are used. |
| `bundle_url` | String (URI) | Optional | Remote HTTPS URL serving the gzip-compressed tarball. If omitted, runner checks for sideloaded bundle. |
| `sha256` | String (Hex) | Optional | SHA-256 cryptographic digest of the bundle tarball. When provided, must match before extraction. |

---

## 4. Bundle Package Structure & Convention

Custom extension bundles employ a standardized hierarchical layout with declarative stage gating and asset convention subdirectories.

### 4.1 Hierarchical Directory Layout
```text
my-custom-bundle/
├── manifest.yaml                    # Required: Declarative authority for bundle & stages
├── VERSION                          # Required: Semantic version matching manifest.yaml
├── requirements.yml                 # Optional: Ansible galaxy collections or roles
├── roles/                           # Optional: Bundled self-contained Ansible roles
├── cluster_ready/
│   ├── bin/                         # Optional: Stage binaries/tools
│   ├── oci/                         # Optional: Container image tarballs
│   ├── pkg/                         # Optional: Debian packages (.deb)
│   └── playbook.yaml                # Required if stage declared: Stage tasks
├── cluster_turnup/
│   ├── bin/
│   ├── oci/
│   ├── pkg/
│   └── playbook.yaml
├── post_cluster/
│   ├── bin/
│   ├── oci/
│   ├── pkg/
│   └── playbook.yaml
└── upkeep/
    ├── bin/
    ├── oci/
    ├── pkg/
    └── playbook.yaml
```

### 4.2 Declarative `manifest.yaml` Authority
`manifest.yaml` is the declarative authority for bundle identity and stage execution:

```yaml
# Required: Human-readable bundle name
name: "burnin-suite"

# Optional: Upstream origin / source repository URI
origin: "https://git.internal/gdc/platform/bundles/burnin-suite"

# Optional: Detailed description of bundle purpose
description: |
  Hardware burn-in and storage benchmark suite.

# Required: Semantic version matching root VERSION file
version: "1.0.0"

# Required: Non-empty list of lifecycle stages enabled for execution
stages:
  - cluster_ready
  - cluster_turnup
  - post_cluster
  - upkeep
```

#### Authority & Gating Rules:
1. **Manifest Validation:** During Stage 5, the provisioner asserts:
   - `manifest.yaml` exists and is a valid dictionary.
   - `name`, `version`, and `stages` are non-empty.
   - Root `VERSION` exists and its trimmed content matches `manifest.yaml.version`.
   - `stages` contains only valid lifecycle stages (`cluster_ready`, `cluster_turnup`, `post_cluster`, `upkeep`).
   - For every stage listed in `stages`, the corresponding `<stage>/playbook.yaml` exists on disk.
2. **Gated Execution:** During Stages 5, 6, 7, and 8, the shared runner checks `/var/gdc-install/state/bundle-manifest.json`. Only stages listed in `stages` are executed; undeclared stages are skipped.

### 4.3 Asset Context Variables
When executing each stage's `playbook.yaml`, the runner provides standard context variables:

| Variable | Description | Value |
| :--- | :--- | :--- |
| `bundle_root_dir` | Absolute path of bundle directory | `/var/gdc-install/bundle` |
| `bundle_stage_dir` | Absolute path of active stage directory | `/var/gdc-install/bundle/<target_custom_stage>` |
| `bundle_bin_dir` | Absolute path of stage binary directory | `/var/gdc-install/bundle/<target_custom_stage>/bin` |
| `bundle_oci_dir` | Absolute path of stage OCI container image directory | `/var/gdc-install/bundle/<target_custom_stage>/oci` |
| `bundle_pkg_dir` | Absolute path of stage Debian package directory | `/var/gdc-install/bundle/<target_custom_stage>/pkg` |

### 4.4 Packaging Command
Bundles must be packaged with standard tarball tooling:
```bash
tar -czvf /var/gdc-install/custom-bundle.tar.gz -C my-custom-bundle/ .
```

### 4.5 Sideload Support (Air-Gapped / Lab Use)
If `bundle_url` is not set or network egress is blocked, operators can place the tarball at:
`/var/gdc-install/custom-bundle.tar.gz`  
The ingestion task checks for this local file before attempting network retrieval.

### 4.6 Operational Guidance: Avoid Snowflake Clusters
> [!WARNING]
> **Anti-Pattern Notice:** Because `custom_extensions` is configured within machine facts, it is architecturally possible to associate different bundle URLs with different individual machines or clusters. While not strictly blocked, operators and platform engineering teams are **strongly urged not to use this capability to create per-cluster "snowflake" bundles**. Custom bundles should be managed as standardized, version-controlled fleet suites (e.g., standard hardware burn-in, enterprise storage benchmarking, regulatory audit checks). Allowing clusters to diverge via ad-hoc custom bundles degrades fleet maintainability and complicates root-cause analysis.

---

## 5. Technical Implementation Details

### 5.1 Role: `roles/custom_extensions/`
Executed inside `src/ansible/stages/stage_cluster_ready.yml`:

1. **Detection & Fetch:**
   - Evaluates `/var/gdc-install/custom-bundle.tar.gz`.
   - If missing and `bundle_url` is defined, downloads archive via `ansible.builtin.get_url` with Bearer auth and mTLS certificates.
2. **Integrity Assertion:**
   - Validates SHA-256 checksum if provided.
3. **Extraction:**
   - Extracts archive into `/var/gdc-install/bundle/` with permissions `0750` (`root:root`).
4. **Manifest Schema & Version Assertion:**
   - Verifies `manifest.yaml` and `VERSION`.
   - Validates declared stages and playbook files.
   - Persists validated manifest to `/var/gdc-install/state/bundle-manifest.json`.
5. **Playbook Normalization:**
   - Automatically normalizes playbooks wrapped in play structure into task lists.
6. **Dependency Resolution:**
   - Evaluates `requirements.yml` in `/var/gdc-install/bundle/`. If present, runs `ansible-galaxy install`.
7. **Stage 5 Execution:**
   - Calls `stages/execute_custom_stage.yml` with `target_custom_stage: cluster_ready`.

### 5.2 Reusable Runner: `src/ansible/stages/execute_custom_stage.yml`
Included at the end of `stage_cluster_ready.yml`, `stage_cluster_turnup.yml`, `stage_post_cluster.yml`, and `stage_upkeep.yml`:

1. Checks for `/var/gdc-install/state/bundle-manifest.json`.
2. Inspects `stages` list in the active manifest. If `target_custom_stage` is omitted, skips execution cleanly with an informative notice.
3. If declared, runs `/var/gdc-install/bundle/{{ target_custom_stage }}/playbook.yaml` with asset variables (`bundle_root_dir`, `bundle_stage_dir`, `bundle_bin_dir`, `bundle_oci_dir`, `bundle_pkg_dir`).
4. Catches errors in a `rescue` block, populates `custom_extension_evidence` with bundle metadata, and halts stage progression.

### 5.3 Evidence & State File Integration
When a stage fails inside a custom extension, the stage's state file (`/var/gdc-install/state/<stage>.json`) explicitly captures the failure block:

```json
{
  "stage": "POST_CLUSTER",
  "status": "failed",
  "timestamp": "2026-10-04T12:00:00Z",
  "evidence": {
    "kubernetes_nodes_ready": true,
    "coredns_operational": true,
    "custom_extension": {
      "failed_in_custom_extension": true,
      "executed": true,
      "custom_stage": "post_cluster",
      "custom_file": "/var/gdc-install/bundle/post_cluster/playbook.yaml",
      "bundle_name": "burnin-suite",
      "bundle_version": "1.0.0",
      "message": "Execution failed within external custom playbook (post_cluster/playbook.yaml). Inspect /var/log/gdc-ansible-pull.log for details."
    }
  }
}
```

---

## 6. Scope Boundaries & Future Expansion Notes

### 6.1 Included in Scope
- Discovery via `gdc.fact` / `machine-info` or local file `/var/gdc-install/custom-bundle.tar.gz`.
- Ingestion in Stage 5 (`CLUSTER_READY`) after mTLS credential provisioning.
- Extraction to `/var/gdc-install/bundle/`.
- Declarative `manifest.yaml` authority and stage gating across Stages 5, 6, 7, and 8 (`cluster_ready`, `cluster_turnup`, `post_cluster`, `upkeep`).
- Hierarchical layout convention with asset directories (`bin/`, `oci/`, `pkg/`) and context variables.
- Canonical bundle template at `custom-data/templates/bundle_template.tar.gz`.
- SHA-256 verification and `ansible-galaxy` dependency resolution.
- Attribution in evidence JSON and `/var/log/gdc-ansible-pull.log`.
- Sample post-cluster burn-in bundle under `custom-data/examples/burnin-bundle/`.
- Operator documentation in `docs/custom-playbook-extensions.md`.

### 6.2 Explicitly Deferred / Out of Scope (Future Phases)
1. **Pre-Stage Hooks & Task Overrides:**
   - *Rationale:* Allowing arbitrary pre-stage injections or overriding core installer roles risks bypassing hardened platform defaults, invalidates cluster certification, and complicates debugging.
2. **Moving `machine-info` to Stage 4 (`LINUX_READY`):**
   - *Rationale:* Moving the `machine-info` retrieval from Stage 5 to Stage 4 alters the physical provisioning sequence.

---

## 7. Verification & Acceptance Criteria

- [ ] **AC-1 (Zero Config):** When no `custom_extensions` block is provided in `machine-info` and no `/var/gdc-install/custom-bundle.tar.gz` exists, all stages execute identically to baseline with zero regressions.
- [ ] **AC-2 (Sideload Execution):** Placing a valid `custom-bundle.tar.gz` with a declared `post_cluster` stage into `/var/gdc-install/` causes Stage 7 to execute the custom tasks successfully and output status `completed`.
- [ ] **AC-3 (Remote Fetch & Integrity):** Providing `bundle_url` and valid `sha256` downloads the bundle, verifies integrity, unpacks, and executes tasks. If `sha256` is invalid, the stage fails before extraction.
- [ ] **AC-4 (Failure Attribution):** A failing assertion in `post_cluster/playbook.yaml` marks Stage 7 as `failed`, records `failed_in_custom_extension: true` in `/var/gdc-install/state/post-cluster.json`, and preserves failure details in `/var/log/gdc-ansible-pull.log`.
- [ ] **AC-5 (Manifest Gating):** Undeclared stages in `manifest.yaml` are not executed even if corresponding playbook files are present in the bundle.
