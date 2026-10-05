# Custom Playbook Lifecycle Extensions Design

**Date:** 2026-10-04  
**Author:** AI Product Manager / Architecture Specialist  
**Tracking Issue:** GitLab Issue #19 (`Investigate using a playbook as the "create-cluster" and "post-cluster" phases`)  
**Specification Link:** `docs/specs/17-custom-playbook-lifecycle-extensions.md`  
**Companion Specification Link:** `docs/specs/18-gdc-companion-bundle-service-spec.md`  

---

## 1. Context & Background

The Google Distributed Cloud (GDC) Bare Metal Offline Bootloader ISO & Disk Provisioner uses a multi-stage `ansible-pull` provisioning pipeline orchestrated by `gdc-provision.service`. 
The core lifecycle steps are:
1. `STAGE 2: FIRST_BOOT` (Local Gitea & Nexus service hubs)
2. `STAGE 3: SECOND_BOOT` (TPM 2.0 unsealing & gateway sanity)
3. `STAGE 4: LINUX_READY` (OS hardening, kernel sysctl tuning, CIS benchmark)
4. `STAGE 5: CLUSTER_READY` (Machine config, networking, mTLS cert generation)
5. `STAGE 6: CLUSTER_TURNUP` (Bare metal cluster inception via `create_cluster.sh`)
6. `STAGE 7: POST_CLUSTER` (Cluster health verification, CoreDNS, storage classes, ConfigSync)
7. `STAGE 8: UPKEEP` (Drift synchronization & systemd timers)

Teams deploying bare-metal clusters frequently require post-cluster hardware and storage burn-in testing, pre-production conformance verification, and custom workload seeding without having to customize and re-master the offline ISO image itself.

---

## 2. Requirements & Goals

### 2.1 Functional Requirements
- **FR-1:** Allow edge nodes to retrieve a custom Ansible playbook bundle from `gdc-companion` or any HTTPS URL, authenticated via Bearer token and/or Step-CA mTLS client certificates.
- **FR-2:** Support air-gapped lab testing by automatically detecting sideloaded bundles at `/var/gdc-install/custom-bundle.tar.gz`.
- **FR-3:** Enforce cryptographic integrity checking using SHA-256 before extraction.
- **FR-4:** Extract bundles to `/var/gdc-install/custom-playbooks/` and resolve `requirements.yml` dependencies via `ansible-galaxy` if present.
- **FR-5:** Execute custom post-stage plays (`cluster_ready.yml`, `cluster_turnup.yml`, `post_cluster.yml`) immediately after the corresponding core stage tasks succeed.
- **FR-6:** In the event of a custom play failure, fail the stage, capture clear attribution in the stage evidence JSON (`failed_in_custom_extension: true`), and direct the operator to `/var/log/gdc-ansible-pull.log`.
- **FR-7:** Default to zero configuration: when no bundle is specified or present, execute the baseline stages with zero overhead.

### 2.2 Non-Requirements & Deferred Scope
- **NR-1 (Pre-Stage Hooks / Stage Overrides):** Overriding core stages or injecting pre-stage hooks is explicitly out of scope. The built-in golden path must not be bypassed.
- **NR-2 (Moving `machine-info` to `LINUX_READY`):** Deferred to a future release. Moving `machine-info` alters the physical provisioning sequence and telemetry dashboard expectations in `gdc-companion`.
- **NR-3 (Avoid Snowflake Clusters Anti-Pattern):** While the schema technically allows assigning distinct bundles per machine or per cluster, documentation and operational guidance explicitly discourage this. Bundles should represent standardized fleet-wide suites (e.g. burn-in, storage stress, CIS audit) rather than divergent ad-hoc cluster configs.

---

## 3. Architecture & Execution Flow

### 3.1 Ingestion in Stage 5 (`CLUSTER_READY`)
Implemented as a new role `roles/custom_extensions/` executed after `machine_orchestration`:
1. Check for `/var/gdc-install/custom-bundle.tar.gz` (sideloaded).
2. If absent and `custom_extensions.bundle_url` is defined in machine facts:
   - Download tarball to `/var/gdc-install/custom-bundle.tar.gz` presenting `Authorization: Bearer {{ gdc_companion_api_key }}` and `/var/gdc-install/keys/client.crt`.
3. If `custom_extensions.sha256` is defined, verify hash; fail stage on mismatch.
4. Extract archive to `/var/gdc-install/custom-playbooks/`.
5. If `requirements.yml` exists in the extracted directory, run `ansible-galaxy install -r requirements.yml`.
6. Invoke `stages/execute_custom_stage.yml` with `target_custom_stage: cluster_ready`.

### 3.2 Post-Stage Execution in Stage 6 & 7
Reusable task `stages/execute_custom_stage.yml` is included at the end of `stage_cluster_turnup.yml` and `stage_post_cluster.yml`:
- Checks if `/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml` exists.
- If present, executes tasks in a `block/rescue` wrapper.
- On failure:
  - Registers `custom_extension_failure` facts.
  - Updates stage evidence with attribution and log location.
  - Triggers stage failure.

---

## 4. Documentation & Examples

- Create comprehensive operator documentation in `docs/custom-playbook-extensions.md`.
- Provide a working reference burn-in bundle in `custom-data/examples/burnin-bundle/` containing:
  - `requirements.yml`
  - `post_cluster.yml` (deploys test namespace, launches verification workload, checks pod connectivity, tears down test namespace).
