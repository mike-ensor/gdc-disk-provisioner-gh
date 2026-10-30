# GDC Operator Guide: Custom Playbook Lifecycle Extensions

This document provides operational instructions, bundle authoring guidelines, and troubleshooting procedures for deploying and managing custom Ansible playbook lifecycle extensions on Google Distributed Cloud (GDC) bare-metal edge nodes.

---

## 1. Overview & Architectural Principles

Google Distributed Cloud bare-metal nodes execute an offline-first, idempotent provisioning lifecycle managed by `ansible-pull` and persistent state tracking files under `/var/gdc-install/state/`. 

While the core installation sequence reliably provisions hardened Linux hosts, local service hubs (Gitea and Nexus), and Anthos bare-metal clusters, operators frequently require post-installation automation—such as hardware burn-in validation, local storage benchmarking, enterprise network validation, and Day-1 application bootstrapping.

To avoid maintaining divergent, custom ISO builds, the **Custom Playbook Lifecycle Extensions** framework (`GDC-SPEC-017`) allows operators to supply an external Ansible playbook bundle without modifying the immutable core ISO.

### Key Tenets:
* **Zero-Configuration Default:** When no custom bundle is provided or configured, provisioning executes standard golden paths without latency or behavior changes.
* **Declarative Manifest Authority:** Bundle execution is governed by `manifest.yaml` and verified against a root `VERSION` file.
* **Non-Invasive Augmentation:** Custom extensions run strictly *after* core tasks within a stage complete. Built-in tasks and safety guardrails are never overridden.
* **Strict Failure Attribution:** Failures in external playbooks are explicitly isolated and recorded in telemetry, clearly distinguishing third-party playbook defects from platform infrastructure failures.

---

## 2. Lifecycle Integration Points

Custom playbook extensions hook into four key stages of the GDC provisioning sequence:

| Provisioning Stage | Execution Hook Path | Timing & Lifecycle Purpose |
| :--- | :--- | :--- |
| **Stage 5: Cluster Ready** (`stage_cluster_ready.yml`) | `cluster_ready/playbook.yaml` | Executes after host networking, VRF isolation, and certificate generation, immediately following bundle download, validation, and dependency installation. |
| **Stage 6: Cluster Turnup** (`stage_cluster_turnup.yml`) | `cluster_turnup/playbook.yaml` | Executes immediately following successful standalone bare-metal cluster inception (`create_cluster.sh`). |
| **Stage 7: Post Cluster** (`stage_post_cluster.yml`) | `post_cluster/playbook.yaml` | Executes immediately after cluster readiness checks, CoreDNS verification, and ConfigSync synchronization. Ideal for automated hardware burn-in suites, storage validation, and baseline workload deployment. |
| **Stage 8: Upkeep** (`stage_upkeep.yml`) | `upkeep/playbook.yaml` | Executes during recurring node upkeep and maintenance cycles. Ideal for periodic health audits, certificate renewal assertions, and Day-2 operational checks. |

### Stage Gating
Execution is strictly gated: only stages explicitly listed in `manifest.yaml` under `stages:` are executed. If a stage is not declared in `manifest.yaml`, it is cleanly skipped as a no-op even if a stage directory or playbook exists on disk.

---

## 3. Bundle Ingestion & Integrity Verification

Bundles can be ingested through either remote authenticated network transfer or physical offline sideloading.

### 3.1. Remote Ingestion via GDC Companion (mTLS & Bearer Auth)
When managed via the GDC Companion service, machine configuration facts (`/etc/ansible/facts.d/gdc.fact` or `/var/gdc-install/state/gdc-fact-manual.json`) declare the bundle URL and its cryptographic hash:

```json
{
  "custom_extensions": {
    "bundle_url": "https://companion.internal/v1/bundles/burnin-suite-v1.2.tar.gz",
    "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
  }
}
```

During Stage 5 (`CLUSTER_READY`), the `custom_extensions` role:
1. Detects `custom_extensions.bundle_url`.
2. Authenticates using the node's Companion API key (`Authorization: Bearer <API_KEY>`) and mutual TLS client certificates (`/var/gdc-install/keys/client.crt` and `client.key`).
3. Downloads the archive to `/var/gdc-install/custom-bundle.tar.gz`.

### 3.2. Offline Sideloading (Air-Gapped / Lab Use)
For completely isolated environments or manual lab bootstrapping where remote network distribution is unavailable:
1. Copy or flash the compressed archive directly onto the target node at:
   ```text
   /var/gdc-install/custom-bundle.tar.gz
   ```
2. The ingestion task checks for the presence of this sideloaded file before attempting any network requests. If found, it bypasses network retrieval and proceeds directly to integrity verification and extraction.

### 3.3. SHA-256 Integrity Assertion & Extraction
If the configuration provides a `sha256` digest:
* The provisioner computes the SHA-256 checksum of `/var/gdc-install/custom-bundle.tar.gz`.
* If the digest does not match the expected value, the task halts immediately, logs an integrity violation, and prevents execution of untrusted code.
* Upon verification, the archive is unpacked into `/var/gdc-install/bundle/` with permissions `0750` (`root:root`).

---

## 4. Bundle Structure, Manifest & Convention

Custom extension bundles employ a standardized hierarchical layout with declarative stage gating and asset convention subdirectories.

### 4.1. Directory Layout
```text
custom-bundle/
├── manifest.yaml                    # Required: Declarative authority for bundle & stages
├── VERSION                          # Required: Semantic version matching manifest.yaml
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

Optional top-level files:
* `requirements.yml`: Ansible Galaxy collections and roles.
* `roles/`: Bundled self-contained Ansible roles.
* `README.md`: Bundle documentation and release notes.

### 4.2. `manifest.yaml` Schema
Every bundle must include a `manifest.yaml` file at its root acting as the declarative authority for bundle identity and enabled lifecycle stages:

```yaml
# ==============================================================================
# GDC Custom Playbook Lifecycle Extension Manifest
# ==============================================================================

# Required: Human-readable identifier for this extension bundle
name: "burnin-suite"

# Optional: Upstream origin / CI-CD pipeline source tracking URI
origin: "https://git.internal/gdc/platform/bundles/burnin-suite"

# Optional: Detailed description of the purpose or tests run by this bundle
description: |
  Hardware burn-in and local storage benchmarking suite for GDC edge nodes.

# Required: Semantic version matching the root VERSION file
version: "1.0.0"

# Required: Ordered list of lifecycle stages enabled for execution.
# Valid options: cluster_ready, cluster_turnup, post_cluster, upkeep.
stages:
  - cluster_ready
  - cluster_turnup
  - post_cluster
  - upkeep
```

#### Manifest Validation Rules:
1. `name`, `version`, and `stages` are mandatory.
2. The root `VERSION` file must exist and its content must match `manifest.yaml`'s `version`.
3. `stages` must be a non-empty list containing only valid stages: `cluster_ready`, `cluster_turnup`, `post_cluster`, `upkeep`.
4. For every stage declared in `stages`, the corresponding stage playbook (`<stage>/playbook.yaml`) **must** exist on disk.
5. Validated manifest data is persisted to `/var/gdc-install/state/bundle-manifest.json` for consumption by subsequent stage runners.

### 4.3. Stage Gating Rules
* **Strict Whitelist:** Only stages declared in `manifest.yaml.stages` are executed by the lifecycle runner.
* **Undeclared Stages Skipped:** If a directory (e.g. `upkeep/playbook.yaml`) exists on disk but `upkeep` is omitted from `manifest.yaml.stages`, the stage is skipped and a log notice is emitted.
* **Missing Playbook Error:** If a stage is declared in `manifest.yaml.stages` but its `playbook.yaml` does not exist, manifest validation immediately fails during Stage 5 before any extension code runs.

### 4.4. Standard Context Variables
When executing each stage's `playbook.yaml`, the extension runner automatically exposes standard directory context variables:

| Variable Name | Description | Example Value |
| :--- | :--- | :--- |
| `bundle_root_dir` | Root path of the unpacked bundle | `/var/gdc-install/bundle` |
| `bundle_stage_dir` | Path to the active stage directory | `/var/gdc-install/bundle/post_cluster` |
| `bundle_bin_dir` | Path to stage-specific executables/binaries | `/var/gdc-install/bundle/post_cluster/bin` |
| `bundle_oci_dir` | Path to stage-specific container image tarballs | `/var/gdc-install/bundle/post_cluster/oci` |
| `bundle_pkg_dir` | Path to stage-specific Debian package archives | `/var/gdc-install/bundle/post_cluster/pkg` |

Playbooks can reliably reference stage assets without hardcoding absolute paths:
```yaml
- name: Install stage-specific debian packages
  ansible.builtin.apt:
    deb: "{{ bundle_pkg_dir }}/fio-custom_amd64.deb"
  when: bundle_pkg_dir is defined
```

### 4.5. Playbook Normalization
Playbooks can be written either directly as task lists or as standard Ansible playbooks containing `hosts:` and `tasks:`. The provisioner automatically normalizes wrapped playbooks into clean task lists before execution.

### 4.6. Dependency Management (`requirements.yml`)
If `requirements.yml` is present in the root of the extracted bundle, the provisioner executes `ansible-galaxy` automatically during Stage 5:
```bash
ansible-galaxy install -r /var/gdc-install/bundle/requirements.yml
```

### 4.7. Starter Template & Reference Implementation
* **Turnkey Starting Template:** Operators can use the canonical reference template located at `custom-data/templates/bundle_template.tar.gz` (or `custom-data/templates/bundle_template/`) as a starting point. It contains the complete hierarchical structure, `manifest.yaml`, `VERSION`, and `.gitkeep` files in `bin/`, `oci/`, and `pkg/` across all four stages.
* **Reference Implementation:** A functional reference burn-in bundle is available in the repository at `custom-data/examples/burnin-bundle/`.

### 4.8. Packaging a Bundle
To create a bundle archive conforming to GDC requirements:
```bash
# Navigate to the bundle source directory
cd /path/to/my-bundle-source

# Archive and compress root contents
tar -czvf /var/gdc-install/custom-bundle.tar.gz -C . .

# Generate the SHA-256 digest
sha256sum /var/gdc-install/custom-bundle.tar.gz
```

---

## 5. Operational Guidance

### Anti-Pattern Notice: Avoid Snowflake Clusters
> [!WARNING]
> **Anti-Pattern Notice: Avoid Snowflake Clusters**  
> Because `custom_extensions` can be declared per-machine in machine facts, it is architecturally possible to assign disparate, unique bundle URLs to individual nodes or clusters.
>
> Operators and platform engineering teams are **strongly urged to avoid creating per-cluster "snowflake" bundles**. 
>
> Custom bundles should represent standardized, version-controlled fleet suites (for example, standard hardware burn-in validation, approved storage benchmarking, or enterprise security baseline assertions). Divergent, ad-hoc bundles per cluster create operational blind spots, complicate root cause analysis during incidents, and undermine fleet consistency.

---

## 6. Troubleshooting & Diagnostics

When custom playbook extensions execute, state tracking and diagnostic logs record execution health and error attribution.

### 6.1. Failure Attribution in State JSON
If an error occurs during the execution of a custom stage playbook, the shared extension runner catches the error in an Ansible `rescue` block and annotates the stage's state file (`/var/gdc-install/state/<stage>.json`):

```json
{
  "status": "failed",
  "evidence": {
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

This telemetry clearly distinguishes custom user task failures from core platform turnup failures.

### 6.2. Log Inspection
To inspect live or historic execution logs:
```bash
# Tail live provisioner output
tail -f /var/log/gdc-ansible-pull.log

# Search for custom extension tasks
grep -E "GDC-EXTENSION|custom_extensions" /var/log/gdc-ansible-pull.log

# Inspect journald logs for gdc-provision service
journalctl -u gdc-provision.service -n 100 --no-pager
```

### 6.3. Sideload Verification on Target Host
To inspect extracted playbooks on an active node:
```bash
# Verify extracted files and permissions (root:root, 0750)
ls -la /var/gdc-install/bundle/

# Inspect active bundle manifest state
cat /var/gdc-install/state/bundle-manifest.json

# Verify bundle archive presence
ls -lh /var/gdc-install/custom-bundle.tar.gz
```
