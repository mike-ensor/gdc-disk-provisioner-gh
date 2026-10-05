# GDC Specification: Custom Playbook Lifecycle Extensions

**Document Version:** 1.0.0  
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
3. Validate and trigger customized post-deployment configurations and service reconciliations.

### 1.2 Solution Overview
This specification introduces a **Post-Stage Lifecycle Extension Framework** powered by an external Ansible playbook bundle:
* **Zero-Configuration Default:** If no custom bundle is configured or present on disk, the system runs with zero overhead and zero operational changes.
* **Stage 5 (`CLUSTER_READY`) Ingestion:** The node discovers, authenticates, downloads (or checks for sideloaded media), validates SHA-256 integrity, unpacks, and resolves dependencies (`requirements.yml`) into `/var/gdc-install/custom-playbooks/`.
* **Standardized Post-Stage Augmentation:** Custom stage plays (`<stage_name>.yml`) run immediately *after* the core stage tasks complete. Built-in tasks and golden paths are never overridden or hijacked.
* **Strict Failure Attribution:** If a custom play fails, the stage fails with clear telemetry attributing the error to the external playbook bundle, directing operators to `/var/log/gdc-ansible-pull.log`.

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
|    | - Extract to /var/gdc-install/custom-playbooks/                                |    |
|    | - Install requirements.yml (via ansible-galaxy if present)                     |    |
|    | - Run cluster_ready.yml (if present)                                          |    |
|    +-------------------------------------------------------------------------------+    |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 6: CLUSTER_TURNUP                              |
|                                                                                         |
| 1. Core Cluster Inception (create_cluster.sh --yes)                                     |
| 2. Shared Extension Runner:                                                             |
|    - Stat /var/gdc-install/custom-playbooks/cluster_turnup.yml                          |
|    - If present -> execute custom tasks post-inception                                  |
|    - On failure -> set custom_extension failure evidence, mark failed, halt             |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                    STAGE 7: POST_CLUSTER                                |
|                                                                                         |
| 1. Core Platform Validation (Nodes Ready, CoreDNS, StorageClass, ConfigSync)            |
| 2. Shared Extension Runner:                                                             |
|    - Stat /var/gdc-install/custom-playbooks/post_cluster.yml                            |
|    - If present -> execute custom Burn-in / Workload Validation                         |
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

A custom bundle is an unnested or single-directory `.tar.gz` archive conforming to the following convention:

```text
my-custom-bundle/
├── requirements.yml           # Optional: Ansible galaxy collections or roles
├── roles/                     # Optional: Bundled self-contained Ansible roles
├── cluster_ready.yml          # Optional: Tasks executed at end of Stage 5
├── cluster_turnup.yml         # Optional: Tasks executed post-cluster inception in Stage 6
└── post_cluster.yml           # Optional: Tasks executed post-validation / burn-in in Stage 7
```

### 4.1 Packaging Command
Bundles must be packaged with standard tarball tooling:
```bash
tar -czvf custom-bundle.tar.gz -C my-custom-bundle/ .
```

### 4.2 Sideload Support (Air-Gapped / Lab Use)
If `bundle_url` is not set or network egress is blocked, operators can place the tarball at:
`/var/gdc-install/custom-bundle.tar.gz`  
The ingestion task checks for this local file before attempting network retrieval.

### 4.3 Operational Guidance: Avoid Snowflake Clusters
> [!WARNING]
> **Anti-Pattern Notice:** Because `custom_extensions` is configured within machine facts, it is architecturally possible to associate different bundle URLs with different individual machines or clusters. While not strictly blocked, operators and platform engineering teams are **strongly urged not to use this capability to create per-cluster "snowflake" bundles**. Custom bundles should be managed as standardized, version-controlled fleet suites (e.g., standard hardware burn-in, enterprise storage benchmarking, regulatory audit checks). Allowing clusters to diverge via ad-hoc custom bundles degrades fleet maintainability and complicates root-cause analysis.

---

## 5. Technical Implementation Details

### 5.1 New Role: `roles/custom_extensions/`
Executed inside `src/ansible/stages/stage_cluster_ready.yml` after `machine_orchestration`:

1. **Detection & Fetch:**
   - Evaluates `/var/gdc-install/custom-bundle.tar.gz`.
   - If missing and `machine_config.custom_extensions.bundle_url` is defined:
     - Downloads using `ansible.builtin.get_url` presenting `Authorization: Bearer {{ gdc_companion_api_key }}` and client certificates (`/var/gdc-install/keys/client.crt` and `client.key`) if available.
2. **Integrity Assertion:**
   - If `machine_config.custom_extensions.sha256` is present, calculates checksum using `stat` (checksum algorithm `sha256`).
   - Fails immediately if hash differs from expected value.
3. **Extraction:**
   - Extracts archive into `/var/gdc-install/custom-playbooks/` with directory mode `0750` owned by `root:root`.
4. **Dependency Resolution:**
   - Evaluates `/var/gdc-install/custom-playbooks/requirements.yml`.
   - If present, executes:
     ```bash
     ansible-galaxy install -r /var/gdc-install/custom-playbooks/requirements.yml
     ```
5. **Stage 5 Execution:**
   - Calls `stages/execute_custom_stage.yml` with `target_custom_stage: cluster_ready`.

### 5.2 Reusable Runner: `src/ansible/stages/execute_custom_stage.yml`
Included at the end of `stage_cluster_turnup.yml` and `stage_post_cluster.yml`:

```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
- name: "GDC-EXTENSION | Check for custom tasks: {{ target_custom_stage }}"
  ansible.builtin.stat:
    path: "/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml"
  register: custom_stage_stat

- name: "GDC-EXTENSION | Execute custom {{ target_custom_stage }} tasks"
  when: custom_stage_stat.stat.exists
  block:
    - name: "GDC-EXTENSION | Run {{ target_custom_stage }}.yml"
      ansible.builtin.include_tasks:
        file: "/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml"
  rescue:
    - name: "GDC-EXTENSION | Record failure evidence"
      ansible.builtin.set_fact:
        custom_extension_evidence:
          failed_in_custom_extension: true
          custom_stage: "{{ target_custom_stage }}"
          custom_file: "/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml"
          message: "Execution failed within external custom playbook ({{ target_custom_stage }}.yml). Inspect /var/log/gdc-ansible-pull.log for details."
          error_detail: "{{ ansible_failed_result | default({}) }}"

    - name: "GDC-EXTENSION | Fail stage due to external playbook failure"
      ansible.builtin.fail:
        msg: "Execution failed within external custom playbook ({{ target_custom_stage }}.yml). See /var/log/gdc-ansible-pull.log."
```

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
      "custom_stage": "post_cluster",
      "custom_file": "/var/gdc-install/custom-playbooks/post_cluster.yml",
      "message": "Execution failed within external custom playbook (post_cluster.yml). Inspect /var/log/gdc-ansible-pull.log for details."
    }
  }
}
```

---

## 6. Scope Boundaries & Future Expansion Notes

### 6.1 Included in Scope (Phase 1)
- Discovery via `gdc.fact` / `machine-info` or local file `/var/gdc-install/custom-bundle.tar.gz`.
- Ingestion in Stage 5 (`CLUSTER_READY`) after mTLS credential provisioning.
- SHA-256 verification and `ansible-galaxy` dependency resolution.
- Post-stage extension hooks in Stage 5 (`cluster_ready.yml`), Stage 6 (`cluster_turnup.yml`), and Stage 7 (`post_cluster.yml`).
- Attribution in evidence JSON and `/var/log/gdc-ansible-pull.log`.
- Sample post-cluster burn-in bundle under `custom-data/examples/burnin-bundle/`.
- Operator documentation in `docs/custom-playbook-extensions.md`.

### 6.2 Explicitly Deferred / Out of Scope (Future Phases)
1. **Pre-Stage Hooks & Task Overrides:**
   - *Rationale:* Allowing arbitrary pre-stage injections or overriding core installer roles (e.g. replacing `create_cluster.sh`) risks bypassing hardened platform defaults, invalidates cluster certification, and complicates debugging.
2. **Moving `machine-info` to Stage 4 (`LINUX_READY`):**
   - *Rationale:* Moving the `machine-info` retrieval from Stage 5 to Stage 4 alters the physical provisioning sequence. Because `gdc-companion` live telemetry, real-time dashboard state, and stage progression gates are coupled to the current stage ordering, altering this timeline requires end-to-end telemetry coordination across both repositories. This was deemed too complex and unnecessary for the primary use case of post-cluster burn-in testing.

---

## 7. Verification & Acceptance Criteria

- [ ] **AC-1 (Zero Config):** When no `custom_extensions` block is provided in `machine-info` and no `/var/gdc-install/custom-bundle.tar.gz` exists, all stages execute identically to baseline with zero regressions.
- [ ] **AC-2 (Sideload Execution):** Placing a valid `custom-bundle.tar.gz` with a `post_cluster.yml` into `/var/gdc-install/` causes Stage 7 to execute the custom tasks successfully and output status `completed`.
- [ ] **AC-3 (Remote Fetch & Integrity):** Providing `bundle_url` and valid `sha256` downloads the bundle, verifies integrity, unpacks, and executes tasks. If `sha256` is invalid, the stage fails before extraction.
- [ ] **AC-4 (Failure Attribution):** A failing assertion in `post_cluster.yml` marks Stage 7 as `failed`, records `failed_in_custom_extension: true` in `/var/gdc-install/state/post-cluster.json`, and preserves failure details in `/var/log/gdc-ansible-pull.log`.
