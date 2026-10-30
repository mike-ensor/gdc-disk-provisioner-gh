# GDC Design Specification: Hierarchical Custom Playbook Bundle System & Stage Gating

**Document Version:** 1.0.0  
**Date:** 2026-10-30  
**Status:** Approved for Implementation  
**Target Repository:** `gdc-disk-provisioner`  
**Related Specifications:** `docs/specs/17-custom-playbook-lifecycle-extensions.md`, `docs/specs/18-gdc-companion-bundle-service-spec.md`  

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Statement
Google Distributed Cloud (GDC) bare-metal nodes utilize the Custom Playbook Lifecycle Extension framework (`GDC-SPEC-017`) to execute post-stage operations such as hardware burn-in testing, storage benchmarking, and workload validation. 

In the initial implementation, bundles were extracted directly into `/var/gdc-install/custom-playbooks/` with a flat directory convention (`cluster_ready.yml`, `cluster_turnup.yml`, `post_cluster.yml`). This design exhibited several limitations:
1. **Lacked Stage Execution Authority:** Stages were executed based solely on file presence rather than an explicit, declarative contract. Operators could not inspect a bundle to determine which stages it targeted without inspecting the archive's file listing.
2. **No Structured Asset Segregation:** Binary executables, OCI container image tarballs, and OS Debian packages could not be organized cleanly per stage without colliding or polluting the playbooks directory.
3. **No Upkeep Stage Hook:** Stage 8 (`UPKEEP`) lacked lifecycle extension wiring, preventing post-deployment auditing or periodic health extension hooks.
4. **Missing Standardized Scaffold/Template:** No official bundle template existed for distribution or integration with the `gdc-companion` service.

### 1.2 Solution Overview
This specification upgrades the bundle system to a **declarative, hierarchical bundle architecture**:
* **`manifest.yaml` as Sole Authority:** Stage execution is gated strictly by the bundle's `manifest.yaml`. If a stage is not declared in `manifest.yaml.stages`, it will not be executed—even if the stage directory and playbook exist on disk.
* **Per-Stage Isolated Layout:** Each stage maintains its own isolated sub-folder (`cluster_ready/`, `cluster_turnup/`, `post_cluster/`, `upkeep/`) containing `playbook.yaml` and convention subdirectories (`bin/`, `oci/`, `pkg/`).
* **Playbook-Driven Asset Unpacking:** Subdirectories `bin/`, `oci/`, and `pkg/` provide human clarity; `<stage>/playbook.yaml` is responsible for unpacking, installing, or loading assets as needed, aided by standardized Ansible context variables (`bundle_bin_dir`, `bundle_oci_dir`, `bundle_pkg_dir`).
* **Standard Extraction Path:** Bundles are extracted to `/var/gdc-install/bundle/`.
* **Universal Stage Support:** Integrates extension hooks across all post-cluster stages: Stage 5 (`CLUSTER_READY`), Stage 6 (`CLUSTER_TURNUP`), Stage 7 (`POST_CLUSTER`), and Stage 8 (`UPKEEP`).
* **Standardized Bundle Template:** Provides a packaged template `bundle_template.tar.gz` with complete inline documentation for all fields and `VERSION` set to `0.0.1`.

---

## 2. Bundle Specification & Conventions

### 2.1 File & Directory Layout
A custom extension bundle archive (`custom-bundle.tar.gz` or `.tar.gz`) adheres to the following structure:

```text
custom-bundle/
├── manifest.yaml                    # Required: Declarative authority for bundle & stages
├── VERSION                          # Required: Semantic version string matching manifest.yaml
├── cluster_ready/                   # Executed at end of Stage 5 (CLUSTER_READY)
│   ├── bin/                         # Optional: Binaries & scripts
│   ├── oci/                         # Optional: Container image tarballs
│   ├── pkg/                         # Optional: OS packages (.deb)
│   └── playbook.yaml                # Required if stage declared: Stage playbook/tasks
├── cluster_turnup/                  # Executed post-inception in Stage 6 (CLUSTER_TURNUP)
│   ├── bin/
│   ├── oci/
│   ├── pkg/
│   └── playbook.yaml
├── post_cluster/                    # Executed post-validation in Stage 7 (POST_CLUSTER)
│   ├── bin/
│   ├── oci/
│   ├── pkg/
│   └── playbook.yaml
└── upkeep/                          # Executed post-timer setup in Stage 8 (UPKEEP)
    ├── bin/
    ├── oci/
    ├── pkg/
    └── playbook.yaml
```

### 2.2 `manifest.yaml` Schema
```yaml
# ==============================================================================
# GDC Custom Playbook Lifecycle Extension Manifest
# Specification: GDC-SPEC-017 & GDC-SPEC-018
# ==============================================================================

# Human-readable identifier for this extension bundle
name: "fleet-standard-bundle"

# Upstream origin / CI-CD pipeline source tracking URI
origin: "https://git.internal/gdc/platform/bundles/fleet-standard"

# Detailed description of the purpose, hardening, or tests run by this bundle
description: |
  Standard fleet bundle providing custom network assertions in cluster_ready,
  pre-provisioning checks in cluster_turnup, burn-in validation in post_cluster,
  and periodic health auditing in upkeep.

# Semantic version matching the VERSION file
version: "0.0.1"

# Ordered list of lifecycle stages enabled for execution.
# Valid options: cluster_ready, cluster_turnup, post_cluster, upkeep.
# Only stages listed below will execute, even if stage directories exist on disk.
stages:
  - cluster_ready
  - cluster_turnup
  - post_cluster
  - upkeep
```

### 2.3 Strict Validation Invariants
1. **Mandatory Manifest:** The bundle must contain `manifest.yaml` at its root. Bundles missing `manifest.yaml` fail ingestion immediately.
2. **Mandatory Version:** The bundle must contain a `VERSION` file matching `manifest.yaml.version`.
3. **Stage Existence:** Every stage declared in `manifest.yaml.stages` must possess a valid `<stage>/playbook.yaml`. Missing playbooks fail ingestion fast.
4. **Strict Gating:** If a directory (e.g. `upkeep/`) exists on disk but is omitted from `manifest.yaml.stages`, the stage runner skips it cleanly without execution.

---

## 3. Node Provisioner Architecture & Data Flow

```text
+-----------------------------------------------------------------------------------------+
|                                    STAGE 5: CLUSTER_READY                               |
|                                                                                         |
| 1. Download/Sideload /var/gdc-install/custom-bundle.tar.gz                              |
| 2. Verify SHA-256 Checksum (if configured in gdc.fact)                                  |
| 3. Unpack into /var/gdc-install/bundle/                                                 |
| 4. Validate manifest.yaml & stage playbooks                                             |
| 5. Persist /var/gdc-install/state/bundle-manifest.json                                   |
| 6. Normalize playbooks in active stages                                                 |
| 7. Shared Runner: execute_custom_stage (target: cluster_ready)                          |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 6: CLUSTER_TURNUP                              |
|                                                                                         |
| 1. Core Cluster Inception (create_cluster.sh)                                           |
| 2. Shared Runner: execute_custom_stage (target: cluster_turnup)                          |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 7: POST_CLUSTER                                |
|                                                                                         |
| 1. Core Platform Validation (Nodes Ready, CoreDNS, StorageClass)                        |
| 2. Shared Runner: execute_custom_stage (target: post_cluster)                           |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 8: UPKEEP                                      |
|                                                                                         |
| 1. Core Systemd Timers (Provision & Desired State)                                      |
| 2. Shared Runner: execute_custom_stage (target: upkeep)                                  |
+-----------------------------------------------------------------------------------------+
```

---

## 4. Technical Implementation Details

### 4.1 Ingestion Role (`roles/custom_extensions/tasks/main.yml`)
* **Default Directory:** `/var/gdc-install/bundle` (configured via `custom_extensions_bundle_dir`).
* **Unpack Task:** Unarchives to `{{ custom_extensions_bundle_dir }}` with `owner: root`, `group: root`, `mode: 'u=rwX,g=rX,o='`.
* **Validation Tasks:**
  * Checks `stat` on `manifest.yaml`. Asserts existence with clear error message.
  * Slurps and parses `manifest.yaml` using Python/YAML.
  * Writes `/var/gdc-install/state/bundle-manifest.json`.
  * Verifies `<stage>/playbook.yaml` exists for all stages in `manifest.stages`.
* **Normalization Task:**
  * Loops over declared stages and converts any play-wrapped YAML (`hosts:`) into flat task lists.
* **Stage 5 Hook:**
  * Calls `stages/execute_custom_stage.yml` with `target_custom_stage: "cluster_ready"`.

### 4.2 Reusable Stage Runner (`src/ansible/stages/execute_custom_stage.yml`)
1. Reads `/var/gdc-install/state/bundle-manifest.json`.
2. Checks if `target_custom_stage` is contained in `manifest.stages`.
3. If not in `manifest.stages`:
   * Emits debug log: `[GDC-EXTENSION] Stage '{{ target_custom_stage }}' is not enabled in bundle manifest. Skipping.`
   * Leaves `custom_extension_evidence` untouched or marked skipped.
4. If in `manifest.stages`:
   * Exposes stage-specific context variables:
     * `bundle_root_dir`: `/var/gdc-install/bundle`
     * `bundle_stage_dir`: `/var/gdc-install/bundle/{{ target_custom_stage }}`
     * `bundle_bin_dir`: `/var/gdc-install/bundle/{{ target_custom_stage }}/bin`
     * `bundle_oci_dir`: `/var/gdc-install/bundle/{{ target_custom_stage }}/oci`
     * `bundle_pkg_dir`: `/var/gdc-install/bundle/{{ target_custom_stage }}/pkg`
   * Executes `/var/gdc-install/bundle/{{ target_custom_stage }}/playbook.yaml`.
   * On failure: sets `failed_in_custom_extension: true` with error details, failing the stage and recording attribution.

### 4.3 Stage 8 (`UPKEEP`) Wiring (`src/ansible/stages/stage_upkeep.yml`)
* Adds execution of `execute_custom_stage.yml` with `target_custom_stage: "upkeep"`.
* Incorporates `custom_extension: (custom_extension_evidence | default({}))` into `upkeep_evidence` in `/var/gdc-install/state/update-upkeep.json`.

### 4.4 Bundle Template (`custom-data/templates/bundle_template/`)
* Contains a fully scaffolded, commented reference template:
  * `manifest.yaml` with version `0.0.1` and inline explanations for `name`, `origin`, `description`, `version`, and `stages`.
  * `VERSION` containing `0.0.1`.
  * Subfolders for `cluster_ready/`, `cluster_turnup/`, `post_cluster/`, and `upkeep/`, each containing empty `bin/`, `oci/`, `pkg/` directories (with `.gitkeep`) and skeleton `playbook.yaml` files.
* Pre-compiled tarball `custom-data/templates/bundle_template.tar.gz` packaged via `tar -czf`.

---

## 5. Verification & Acceptance Criteria

- [ ] **AC-1 (Strict Manifest Requirement):** A bundle without `manifest.yaml` is rejected during Stage 5 ingestion, failing with an explicit security alert.
- [ ] **AC-2 (Stage Gating):** If a stage directory (e.g. `cluster_turnup/`) exists in the bundle but is omitted from `manifest.yaml.stages`, Stage 6 does not execute the playbook and completes cleanly.
- [ ] **AC-3 (Missing Playbook Assertion):** If a stage is declared in `manifest.yaml.stages` but its `<stage>/playbook.yaml` is missing, ingestion fails fast with a validation error.
- [ ] **AC-4 (Asset Context Availability):** Stage playbooks have access to `bundle_bin_dir`, `bundle_oci_dir`, and `bundle_pkg_dir`.
- [ ] **AC-5 (Stage 8 Upkeep Extension):** Stage 8 (`UPKEEP`) executes `upkeep/playbook.yaml` when declared in `manifest.yaml` and records outcome in `update-upkeep.json`.
- [ ] **AC-6 (Bundle Template Packaging):** `custom-data/templates/bundle_template.tar.gz` exists, unpacks cleanly, and validates against the schema.
- [ ] **AC-7 (Automated Tests):** All pytest suites in `test/test_custom_extensions.py` pass without errors.
