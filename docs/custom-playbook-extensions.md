# GDC Operator Guide: Custom Playbook Lifecycle Extensions

This document provides operational instructions, bundle authoring guidelines, and troubleshooting procedures for deploying and managing custom Ansible playbook lifecycle extensions on Google Distributed Cloud (GDC) bare-metal edge nodes.

---

## 1. Overview & Architectural Principles

Google Distributed Cloud bare-metal nodes execute an offline-first, idempotent provisioning lifecycle managed by `ansible-pull` and persistent state tracking files under `/var/gdc-install/state/`. 

While the core installation sequence reliably provisions hardened Linux hosts, local service hubs (Gitea and Nexus), and Anthos bare-metal clusters, operators frequently require post-installation automation—such as hardware burn-in validation, local storage benchmarking, enterprise network validation, and Day-1 application bootstrapping.

To avoid maintaining divergent, custom ISO builds, the **Custom Playbook Lifecycle Extensions** framework (`GDC-SPEC-017`) allows operators to supply an external Ansible playbook bundle without modifying the immutable core ISO.

### Key Tenets:
* **Zero-Configuration Default:** When no custom bundle is provided or configured, provisioning executes standard golden paths without latency or behavior changes.
* **Non-Invasive Augmentation:** Custom extensions run strictly *after* core tasks within a stage complete. Built-in tasks and safety guardrails are never overridden.
* **Strict Failure Attribution:** Failures in external playbooks are explicitly isolated and recorded in telemetry, clearly distinguishing third-party playbook defects from platform infrastructure failures.

---

## 2. Lifecycle Integration Points

Custom playbook extensions hook into three key stages of the GDC provisioning sequence:

| Provisioning Stage | Execution Hook File | Timing & Lifecycle Purpose |
| :--- | :--- | :--- |
| **Stage 5: Cluster Ready** (`stage_cluster_ready.yml`) | `cluster_ready.yml` | Executes after host networking, VRF isolation, and certificate generation, immediately following bundle download and dependency installation. |
| **Stage 6: Cluster Turnup** (`stage_cluster_turnup.yml`) | `cluster_turnup.yml` | Executes immediately following successful standalone bare-metal cluster inception (`create_cluster.sh`). |
| **Stage 7: Post Cluster** (`stage_post_cluster.yml`) | `post_cluster.yml` | Executes immediately after cluster readiness checks, CoreDNS verification, and ConfigSync synchronization. Ideal for automated hardware burn-in suites, storage validation, and baseline workload deployment. |

If a stage's corresponding hook file (e.g. `cluster_turnup.yml` or `post_cluster.yml`) is not present in the bundle, that stage's extension step completes as a no-op.

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

### 3.3. SHA-256 Integrity Assertion
If the configuration provides a `sha256` digest:
* The provisioner computes the SHA-256 checksum of `/var/gdc-install/custom-bundle.tar.gz`.
* If the digest does not match the expected value, the task halts immediately, logs an integrity violation, and prevents execution of untrusted code.

---

## 4. Bundle Structure & Dependency Resolution

A custom extension bundle is a gzip-compressed tarball (`custom-bundle.tar.gz`) containing Ansible task files, roles, and collections.

### 4.1. Directory Layout
```text
custom-bundle/
├── requirements.yml           # Optional: Ansible Galaxy collections or roles
├── roles/                     # Optional: Bundled self-contained Ansible roles
│   └── burnin_benchmark/
│       └── tasks/
│           └── main.yml
├── cluster_ready.yml          # Optional: Stage 5 post-ready extensions
├── cluster_turnup.yml         # Optional: Stage 6 post-turnup extensions
├── post_cluster.yml           # Optional: Stage 7 post-cluster validation / burn-in
└── README.md                  # Documentation and bundle change log
```

### 4.2. Dependency Management (`requirements.yml`)
If `requirements.yml` is present in the root of the extracted bundle, the provisioner executes `ansible-galaxy` automatically during Stage 5:
```bash
ansible-galaxy install -r /var/gdc-install/custom-playbooks/requirements.yml
```
Example `requirements.yml`:
```yaml
collections:
  - name: community.general
    version: ">=9.0.0"
  - name: kubernetes.core
    version: ">=5.0.0"
```

### 4.3. Packaging a Bundle
To create a bundle archive conforming to GDC requirements:
```bash
# Navigate to the bundle source directory
cd /path/to/my-bundle-source

# Archive and compress root contents
tar -czvf /var/gdc-install/custom-bundle.tar.gz -C . .

# Generate the SHA-256 digest
sha256sum /var/gdc-install/custom-bundle.tar.gz
```

A reference implementation is available in the repository at `custom-data/examples/burnin-bundle/`.

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
      "custom_file": "/var/gdc-install/custom-playbooks/post_cluster.yml",
      "message": "Execution failed within external custom playbook (post_cluster.yml). Inspect /var/log/gdc-ansible-pull.log for details."
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
ls -la /var/gdc-install/custom-playbooks/

# Verify bundle archive presence
ls -lh /var/gdc-install/custom-bundle.tar.gz
```
