# Implementation Plan: CIS Security Bundle Interface & Hardening Harness

**Date:** 2026-10-21  
**Target Specification:** `docs/specs/20-cis-security-bundle-and-hardening-harness.md`  
**Status:** Ready for Execution  

---

## 1. Goal
Implement the loosely-coupled CIS Security Bundle architecture on GDC bare-metal nodes:
1. Standardize the customer-supplied CIS bundle (`cis-hardening-amd64.tar.gz`) with a compliant `manifest.json` and entrypoint script (`bin/run-hardening.sh`) that respects GDC platform guardrails and idempotency.
2. Build an Ansible harness role (`src/ansible/roles/cis_bundle_harness/`) to unpack, validate, and execute the bundle with injected guardrails during Stage 4 (`LINUX_READY`).
3. Reconcile reboot signaling via `/var/run/reboot-required` into Stage 4.5 before cluster inception.
4. Capture and ingest structured compliance evidence into `/var/gdc-install/state/cis-benchmark.json` and `linux-ready.json`.

---

## 2. Proposed Changes

### Component 1: CIS Bundle Packaging & Contract Compliance
* **Files**:
  - `manifest.json` (inside bundle root)
  - `bin/run-hardening.sh` (inside bundle root)
  - `bin/run-assessment.sh` (inside bundle root)
  - `config/exclusion_list.txt` (inside bundle root)
* **Contract Responsibilities**:
  - Parse `GDC_*` environment variables (`GDC_FIREWALL_POLICY=disabled`, `GDC_ENABLE_CONTAINERD=true`, `GDC_ENABLE_K8S_ROUTING=true`, `GDC_ENABLE_SHM_EXEC=true`, `GDC_ENABLE_GPU_PTRACE=true`, `GDC_ENABLE_NGINX=true`, `GDC_ENABLE_CHRONY=true`).
  - Execute Build Kit L1 and L2 with suppressed rules.
  - Run idempotent custom remediations using modular drop-ins (`/etc/sysctl.d/`, `/etc/audit/rules.d/`, `/etc/ssh/sshd_config.d/`).
  - If GRUB is modified with `audit=1 audit_backlog_limit=8192`, touch `/var/run/reboot-required`.
  - Execute CIS-CAT Assessor and output structured metrics to `$GDC_STATE_FILE`.

### Component 2: GDC Harness Ansible Role
* **Files**:
  - `src/ansible/roles/cis_bundle_harness/defaults/main.yml`
  - `src/ansible/roles/cis_bundle_harness/tasks/main.yml`
  - `src/ansible/roles/cis_bundle_harness/tasks/unpack.yml`
  - `src/ansible/roles/cis_bundle_harness/tasks/execute.yml`
  - `src/ansible/roles/cis_bundle_harness/tasks/evidence.yml`
* **Tasks**:
  - Ensure `/opt/cis-hardening` directory exists.
  - Unpack `/var/gdc-install/iso-cache/security/cis-hardening-amd64.tar.gz`.
  - Validate `manifest.json` schema version and entrypoint executable permissions.
  - Execute `bin/run-hardening.sh` with environment guardrails. Timeout: `1800s`. Accept rc `0` and `1`.
  - Validate presence of `/var/gdc-install/state/cis-benchmark.json` and slurp facts into `cis_benchmark_facts`.

### Component 3: Stage 4 & Stage 4.5 Pipeline Integration
* **File**: `src/ansible/stages/stage_linux_ready.yml`
  - Replace legacy `cis_benchmark` role call with `cis_bundle_harness`.
  - Retain `linux_ready_evidence.cis_benchmarks` fact mapping.
* **File**: `src/ansible/local.yml`
  - Ensure Stage 4.5 reboot logic cleanly catches `/var/run/reboot-required` and reboots before Stage 5 (`CLUSTER_READY`).

### Component 4: Static Audits & Dependency Management
* **File**: `src/dependencies.env`
  - Verify `CIS_TARBALL_FILENAME=cis-hardening-amd64.tar.gz` and `CIS_ISO_DEST_DIR=/custom-data/security`.
* **File**: `test/validate_iso_static.py`
  - Verify test assertion checks for `/custom-data/security/cis-hardening-amd64.tar.gz`.

---

## 3. Verification Plan

### Automated Test Cases
1. **Manifest Validation**:
   - Verify `manifest.json` is present and parsed correctly by the harness.
2. **Idempotency Assertions**:
   - Run the harness twice consecutively in test sandbox. Verify second run produces zero duplicate lines in `/etc/default/grub` and no sysctl errors.
3. **Guardrail Enforcements**:
   - Verify `ufw status` remains `inactive`.
   - Verify `nginx` service is active and responsive on `https://127.0.0.1:443`.
   - Verify `/dev/shm` is mounted with `exec`.
   - Verify `sysctl net.ipv4.ip_forward` equals `1` and `net.ipv4.conf.all.rp_filter` equals `2`.
4. **Reboot Hook Verification**:
   - Confirm `/var/run/reboot-required` triggers the Stage 4.5 reboot before Stage 5.
5. **Evidence Ingestion**:
   - Assert `/var/gdc-install/state/cis-benchmark.json` contains valid `score_percentage` >= 90.0% for both Level 1 and Level 2 profiles.

### Manual / Integration Verification
- Execute `test/verify_ansible.sh` against the updated playbooks.
- Build test ISO with `make iso-fast` and validate outer file layout with `python3 test/validate_iso_static.py`.
