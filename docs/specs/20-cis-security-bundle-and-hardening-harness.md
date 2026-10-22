# GDC Specification: CIS Security Bundle Interface & Hardening Harness

**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Specification File:** `docs/specs/20-cis-security-bundle-and-hardening-harness.md`  
**Target Repository:** `gdc-disk-provisioner`  
**Related Specifications:** `docs/specs/03-ready-linux-provisioning.md`, `docs/specs/17-custom-playbook-lifecycle-extensions.md`  

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Statement
Google Distributed Cloud (GDC) bare-metal nodes currently execute the CIS-CAT Assessor tool during Stage 4 (`LINUX_READY`) via `src/ansible/scripts/run_cis_benchmark.py`. Because the node is never hardened prior to this audit, it assesses an essentially vanilla Ubuntu 24.04 server, returning low compliance scores (~35–40%).

While a customer-provided CIS hardening package (`forge-cognition-Hardening-CIS-Ubuntu24-master.zip`) contains the official CIS Linux Build Kit and extensive remediation scripts, hardcoding third-party shell scripts into GDC core Ansible roles introduces severe maintenance debt, breaks modularity, and risks clobbering native GDC workloads (such as Anthos bare-metal container networking, containerd, and Nexus TLS).

### 1.2 Solution Overview
This specification establishes an **External CIS Security Bundle Architecture**:
1. **Loose Coupling & Independent Ownership:** An external party (Customer / Vendor Security Team) maintains, versions, and compiles the CIS Build Kit, remediation scripts, and Assessor tool into a self-contained tarball (`cis-hardening-amd64.tar.gz`).
2. **Standardized Interface Contract:** GDC defines `GDC-SPEC-CIS-BUNDLE-v1.0`, specifying bundle entrypoints (`bin/run-hardening.sh`), a machine-readable `manifest.json`, standard environment variables, and exit code conventions.
3. **Strict Idempotency & Coexistence:** Because GDC maintains local hardening rules (in `security_hardening` and `system_tuning`), all configurations must use non-destructive drop-in directories (`/etc/sysctl.d/`, `/etc/audit/rules.d/`, `/etc/ssh/sshd_config.d/`). Re-running the bundle against an already-hardened system must be a verified zero-change no-op.
4. **Platform Guardrails Injection:** GDC's harness injects mandatory platform flags ensuring that Anthos Bare Metal requirements (UFW disabled, containerd overlayfs enabled, IP forwarding active, rp_filter=2, /dev/shm execution allowed, GPU ptrace allowed, Nginx TLS proxy preserved) are never overridden.
5. **Automated Kernel Reboot:** When GRUB parameters (`audit=1 audit_backlog_limit=8192`) change, the bundle touches `/var/run/reboot-required`, allowing GDC's existing Stage 4.5 harness to reboot the node cleanly into the audited kernel before Stage 5 (`CLUSTER_READY`).
6. **Telemetry Ingestion:** Standardized JSON evidence (`/var/gdc-install/state/cis-benchmark.json`) is slurped into `linux-ready.json` and uploaded via `gdc-collector`.

---

## 2. Architecture & Data Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Stage 4: LINUX_READY                            │
│                                                                        │
│ 1. host_foundations   -> Admin user, local Nexus APT repo wiring       │
│ 2. system_tuning      -> Kernel sysctls, swapoff, module blacklists    │
│ 3. storage_prereqs    -> Multipath, LVM setup                          │
│ 4. nvidia_gpu         -> NVIDIA drivers & container toolkit            │
│ 5. security_hardening -> Local baseline security & unattended upgrades │
│                                                                        │
│ 6. cis_bundle_harness Role:                                            │
│    +──────────────────────────────────────────────────────────────+    │
│    | - Unpack /var/gdc-install/iso-cache/security/cis-bundle      |    │
│    | - Validate manifest.json & entrypoint permissions            |    │
│    | - Export GDC_* Platform Guardrails (UFW=off, Nginx=keep,etc) |    │
│    | - Execute bin/run-hardening.sh                               |    │
│    | - Verify /var/gdc-install/state/cis-benchmark.json exists    |    │
│    | - Slurp facts into linux_ready_evidence.cis_benchmarks       |    │
│    +──────────────────────────────────────────────────────────────+    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ If /var/run/reboot-required exists
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Stage 4.5: Reboot Reconciliation                     │
│                                                                        │
│ - Detects pending kernel reboot (GRUB audit=1)                         │
│ - Issues graceful local reboot: shutdown -r now                        │
│ - Node reboots into active audited kernel and resumes at Stage 5       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Stage 5: CLUSTER_READY                           │
│ - Anthos Bare Metal inception begins on fully hardened node            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Interface Contract (`GDC-SPEC-CIS-BUNDLE-v1.0`)

### 3.1 Bundle Directory Structure
The compressed bundle (`cis-hardening-amd64.tar.gz`) must extract into a standardized layout:
```
cis-hardening-amd64/
├── manifest.json              # Contract metadata (Schema 1.0)
├── bin/
│   ├── run-hardening.sh       # Hardening execution entrypoint (chmod 0750)
│   └── run-assessment.sh      # Standalone read-only audit entrypoint (chmod 0750)
├── config/
│   └── exclusion_list.txt     # Build Kit recommendation suppression list
├── build-kit/                 # Official CIS Linux Build Kit
├── assessor/                  # CIS-CAT Pro Assessor CLI, embedded JRE, benchmarks
└── remediations/              # Custom modular remediation scripts
```

### 3.2 Manifest Schema (`manifest.json`)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_version": "1.0",
  "bundle_name": "cis-ubuntu24-hardening",
  "bundle_version": "1.0.0",
  "target_os": "Ubuntu 24.04 LTS",
  "entrypoints": {
    "harden": "bin/run-hardening.sh",
    "assess": "bin/run-assessment.sh"
  },
  "contracts": {
    "idempotent": true,
    "supports_offline": true,
    "reboot_signaling": "/var/run/reboot-required"
  },
  "outputs": {
    "state_file": "/var/gdc-install/state/cis-benchmark.json",
    "report_dir": "/opt/cis-benchmark/reports"
  }
}
```

### 3.3 Environment Variables & Guardrail Injection
GDC invokes `bin/run-hardening.sh` with the following environment variables:

| Environment Variable | Allowed Values | Mandatory Enforcement Behavior |
| :--- | :--- | :--- |
| `GDC_STATE_FILE` | Absolute Path | Target path for JSON evidence (default: `/var/gdc-install/state/cis-benchmark.json`). |
| `GDC_REPORT_DIR` | Absolute Path | Target directory for HTML/TXT reports (default: `/opt/cis-benchmark/reports`). |
| `GDC_LOG_DIR` | Absolute Path | Target directory for execution logs (default: `/var/gdc-install/logs/cis`). |
| `GDC_FIREWALL_POLICY` | `disabled` | **UFW must remain inactive.** Per GDC Bare Metal OS specs, host UFW must not be enabled. |
| `GDC_ENABLE_CONTAINERD` | `true` | **`overlayfs` and `squashfs` must not be blocked.** Required for container layers. |
| `GDC_ENABLE_K8S_ROUTING`| `true` | **`net.ipv4.ip_forward = 1` and `rp_filter = 2` must be maintained.** |
| `GDC_ENABLE_SHM_EXEC` | `true` | **`/dev/shm` must permit execution (`exec`).** Required for container/DB IPC. |
| `GDC_ENABLE_GPU_PTRACE` | `true` | **`kernel.yama.ptrace_scope <= 1` must be maintained.** Required for NVIDIA CUDA. |
| `GDC_ENABLE_NGINX` | `true` | **Nginx must not be purged or disabled.** Required as Nexus TLS reverse proxy. |
| `GDC_ENABLE_CHRONY` | `true` | **Chrony must not be masked.** Required for air-gapped node clock synchronization. |

### 3.4 Exit Code Conventions
- `0`: All recommendations passed or remediated cleanly.
- `1`: Expected advisory status (manual recommendations require review, e.g., disk partitioning). Non-fatal.
- `>1`: Unrecoverable fatal script failure. Halts GDC provisioning.

### 3.5 Evidence Schema (`cis-benchmark.json`)
The bundle must output structured results conforming to:
```json
{
  "timestamp": "ISO8601 UTC String",
  "execution_status": "COMPLETED | ERROR",
  "bundle_version": "string",
  "profiles": {
    "level_1_server": {
      "score_percentage": 92.4,
      "rules_passed": 185,
      "rules_failed": 12,
      "rules_other": 15,
      "rules_total": 212,
      "report_path": "/opt/cis-benchmark/reports/cis-benchmark-level_1_server.html"
    },
    "level_2_server": {
      "score_percentage": 88.1,
      "rules_passed": 210,
      "rules_failed": 25,
      "rules_other": 20,
      "rules_total": 255,
      "report_path": "/opt/cis-benchmark/reports/cis-benchmark-level_2_server.html"
    }
  }
}
```

---

## 4. Requirements

### 4.1 Functional Requirements (FR)
- **FR-1 (ISO Packaging & Offline Delivery):** The build engine (`src/build/remaster.sh`) must package `cis-hardening-amd64.tar.gz` into `/custom-data/security/` on the outer ISO filesystem. `user-data.j2` must rsync this archive to `/var/gdc-install/iso-cache/security/`.
- **FR-2 (Harness Execution):** In `stage_linux_ready.yml`, the `cis_bundle_harness` role must extract the archive to `/opt/cis-hardening/`, validate `manifest.json`, export `GDC_*` environment guardrails, and execute `bin/run-hardening.sh`.
- **FR-3 (Strict Idempotency):** Both the bundle and GDC local tasks must use modular configuration drop-ins (`/etc/sysctl.d/99-cis.conf`, `/etc/audit/rules.d/99-cis.rules`, `/etc/ssh/sshd_config.d/99-cis.conf`). Multiple runs must produce zero drift and zero duplication.
- **FR-4 (Platform Workload Compatibility):**
  - UFW remains inactive (`ufw status` = `inactive`).
  - Nginx remains active on port 443 with `server_tokens off;`.
  - Kernel routing (`ip_forward=1`, `rp_filter=2`) remains enforced.
  - `/dev/shm` retains execution privileges (`nodev,nosuid,exec`).
  - `kernel.yama.ptrace_scope = 1` remains active.
- **FR-5 (Reboot Reconciliation):** If GRUB commandline changes (`audit=1 audit_backlog_limit=8192`), the bundle must touch `/var/run/reboot-required`. Stage 4.5 in `local.yml` must execute the clean reboot before Stage 5.
- **FR-6 (Telemetry Evidence):** `/var/gdc-install/state/cis-benchmark.json` must be slurped into Ansible facts and included in `/var/gdc-install/state/linux-ready.json` under `evidence.cis_benchmarks`.

### 4.2 Non-Functional Requirements (NFR)
- **NFR-1 (Sub-10s Compilation):** The core Ubuntu SquashFS must remain untouched. Bundle packaging occurs strictly on the outer ISO partition (`/custom-data/security/`).
- **NFR-2 (Offline Determinism):** All tools (Build Kit, Assessor, JRE, benchmarks) must execute 100% offline without external network queries.
- **NFR-3 (Execution Time Budget):** Bundle execution must complete within `1800` seconds (30 minutes).

---

## 5. Verification & Acceptance Criteria
1. **Static Validation:**
   - `python3 test/validate_iso_static.py` passes with `/custom-data/security/cis-hardening-amd64.tar.gz` accounted for.
   - `yamllint` and `ansible-lint` pass on `src/ansible/roles/cis_bundle_harness/`.
2. **Sandbox Execution (`test/verify_ansible.sh`):**
   - Stage 4 invokes `cis_bundle_harness` cleanly.
   - `/var/gdc-install/state/cis-benchmark.json` is generated with valid Level 1 and Level 2 percentage scores (>= 90%).
   - UFW remains inactive.
   - Nginx responds to TLS queries on loopback.
   - `/var/run/reboot-required` triggers Stage 4.5 reboot before ClusterReady.
