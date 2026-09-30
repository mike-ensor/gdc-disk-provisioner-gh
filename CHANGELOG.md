# Changelog

All notable changes to the `gdc-disk-provisioner` repository are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), adhering to Semantic Versioning.

---

## [Unreleased] (v0.8.x)

### Added
- **Step CA and Companion URL Preflight Readiness Checks**: Enhanced `src/ansible/scripts/check_endpoints.py` and `src/ansible/stages/stage_preflight_checks.yml` to explicitly validate both `gdc_step_ca_url` and `gdc_companion_reports_url` during early preflight checks. Accurately distinguishes between DNS resolution failures and TCP socket reachability/firewall blocks with actionable remediation hints.
- **Dynamic Boot ID and Primary MAC Telemetry Resolution**: Implemented dynamic ephemeral kernel `boot_id` and node `PRIMARY_MAC` parameter injection into Live ISO `user-data` for correlation of installation sessions by physical machine and boot attempt.
- **Dynamic Companion Binary Fetch**: Dynamically pulls the latest `gdc-companion` binary from Google Cloud Storage into system `PATH` during build and provisioning.
- **Concurrent Build Flags & Telemetry**: Added `--skip-pxe` flag, auto-increment versioning logic, and build-state tracking to `concurrent_build.sh`.
- **PXE Netboot Optimization Spec (`docs/specs/`)**: Authored architecture specifications covering dynamic ISO prefixes (e.g., `honeywell`), mTLS security hardening, and netboot transfer optimization.

### Changed
- **Step CA Static Host Mapping Injection**: Added `192.168.20.102 step-ca.ensor-labs.com` to `src/build/add-hosts` and enabled `PERSIST_ADD_HOSTS=true` across environment profiles (`barn.env`, `local.env`). Guarantees deterministic Step CA resolution during early boot across LiveCD and target OS, preventing transient `systemd-resolved` EDNS0/TCP degradation failures against gateway DNS servers.
- **Bootimus Configuration & Profile Precedence**: Standardized Group 11 Bootimus/PXE configurations across `src/build/build.env` (generic defaults `pxe.example-labs.com:26000`), `src/build/local.env`, and `src/build/honeywell.env` (`192.168.254.12:26000`). Corrected `bootimus.sh` sourcing precedence so environment profile overrides take priority over `build.env` base defaults without requiring redundant variables in `.envrc`.
- **Bootimus CLI Variable Aliasing & Standalone Fallback**: Updated `src/build/bootimus.py` to support `BOOTIMUS_API_HOST`/`PXE_SERVER_HOST` and `BOOTIMUS_API_PORT`/`PXE_SERVER_PORT` variable aliasing, plus automatic profile fallback parsing when executed standalone outside `bootimus.sh`.
- **Storage Sanitization Media Exclusion**: Explicitly excluded USB flash drives and installer boot media from disk discovery and automated wiping routines.
- **Stage Completion Status Standard**: Standardized internal Ansible state outputs to lowercase (`ready-linux`, `linux-ready`).

### Fixed
- **FirstBoot Reboot Transition Race**: Added explicit `meta: end_play` to `stage_first_boot.yml` and `local.yml` immediately following the scheduled reboot task. This prevents Ansible from prematurely executing `second-boot` and `linux-ready` (`host_foundations` package installation) during the background reboot countdown, preventing partial package installations and abrupt SIGTERM aborts.
- **CI/CD Test Suite Fixtures for Git-Ignored Profiles**: Added dynamic test fixtures in `test/test_bootimus_env.py` (`setUpClass`/`tearDownClass`) ensuring robust unit test execution across headless and clean CI runners where local environment profiles are git-ignored.
- **Netplan VLAN Collision and Silent Route Rejection**: Resolved Netplan default route conflict where installer-generated `/etc/netplan/01-netcfg.yaml` retained legacy VLAN definitions, causing `netplan apply` to silently abort creating `vlan109` while exiting 0. Added automated purging of stale `vlans:` blocks from `01-netcfg.yaml` and dynamic kernel cleanup of legacy `*.<vlan>` links in `machine_orchestration`, followed by `systemd-networkd` restart to guarantee `.netdev` instantiation.
- **Dynamic Bootstrap Network Seed Generation**: Configured `render_templates.py` to persist `BOOTSTRAP_K8S_IP_CIDR`, `BOOTSTRAP_MACHINE_IP_CIDR`, and gateways into `custom-data/bootstrap_network.env`, enabling `configure_netplan.py` to dynamically hydrate initial boot networking rather than falling back to hardcoded static addresses (`172.31.250.10`).
- **Storage Kernel Module Preloading**: Preloaded `iscsi_tcp` and `ib_iser` in host system tuning (`/etc/modules-load.d/gdc-storage.conf`) to resolve container `Invalid ELF header magic` module load failures within `bmctl` bootstrap clusters.
- **Headless Container Storage Logger**: Guarded storage logging against missing `/dev/log` syslog sockets in headless containerized build environments.
- **POSIX Shell Compliance**: Ensured POSIX `sh -n` compliance across Subiquity `early-commands` and injected automated shell syntax validation gates.

### Known Issues / In-Progress Fixes
- **Netplan VRF Indentation Error**: `/etc/netplan/01-netcfg.yaml:18:8` indentation mapping syntax requires correction for multi-VRF generation.
- **mTLS Hostname Mismatch (HTTP 403)**: `provision-mtls-cert.sh` requests certificates using MAC address instead of `machine_config.hostname`, failing zero-trust companion validation.
- **Telemetry Upload HTTP 301 Drop**: Non-HTTPS Companion endpoints trigger HTTP 301 redirects that drop POST bodies; requires strict HTTPS.
- **Non-LUKS Storage Mode (`GDC-SPEC-008`)**: Planned `GDC_ENABLE_LUKS=false` build parameter for platforms without hardware TPM 2.0 or UEFI.

---

## [0.7.1] - 2026-09-07

### Added
- **Self-Healing Provisioner Service (`gdc-provision.service`)**: Configured `ansible-pull` systemd service with `Restart=on-failure`, `RestartSec=20m`, `StartLimitIntervalSec=0`, and `-o pipefail` to automatically recover from transient network or token refresh failures indefinitely without manual operator intervention.
- **CIS-CAT Benchmarking Audit Integration**: Integrated offline CIS-CAT Assessor into the `LINUX_READY` stage via `run_cis_benchmark.py`, exposing compliance metrics as structured Ansible facts for upstream telemetry.
- **Dual Concurrent Cloud Build Release**: Automated parallel Google Cloud Build pipelines compiling both standard and offline companion-less bootstrap ISOs.

### Changed
- **Pipeline Stage Relocation**: Moved `bmctl` installation to `LINUX_READY` and accelerated chrony NTP kernel synchronization.
- **CI Build Hardening**: Integrated strict `ansible-lint` gating into the ISO builder container (`iso-builder 0.0.90`).

### Fixed
- **Cluster-Ready Token Refresh Stalls**: Resolved transient SSL handshake EOF disconnects during Companion token refreshes that permanently stalled nodes prior to `CLUSTER_READY`.

---

## [0.4.39] - 2026-09-04

### Added
- **Global gcloud Token Access**: Applied `gcloud` access token file configuration globally (`--installation` flag) via `/run/gdc-auth/access_token` for all system users.
- **Non-Admin Authentication Documentation**: Published `FAQ.md` covering non-admin gcloud authentication and Application Default Credentials (ADC) usage.

---

## [0.4.38] - 2026-09-01

### Added
- **Dual ISO Concurrent Orchestrator (`concurrent_build.sh`)**: Orchestrates parallel Cloud Build execution for companion-enabled and air-gapped ISO variants with strict subshell environment scoping.
- **Bootimus Polling Timeout Gate**: Hard-aborts polling after 300 attempts (~20 min) to prevent infinite loops during saturated NAS extraction queues.

### Fixed
- **HMB NVMe Cryptsetup Kernel Panics (DRAM-less SSDs)**: Fixed fatal memory exhaustion on AMD nodes with DRAM-less SSDs (e.g., Kingston arrays) by demoting LUKS KDF from Argon2id (~1GB RAM) to PBKDF2 (1000 iterations), preventing Host Memory Buffer (HMB) starvation and AMD CCP cryptographic co-processor lockups.
- **Pre-Format AMD PSP Module Lockups**: Programmed LiveCD `early-commands` to probe for `AuthenticAMD` and physically unload (`rmmod`) `ccp`, `amd_sfh`, and `pcie_mp2_amd` prior to storage partitioning.
- **Udev Partition Racing (`NotExclusiveError`)**: Reverted sub-LV wiping to `wipe: superblock` while retaining `wipe: superblock-recursive` strictly on physical disks, preventing Curtin/udev lock collisions on dirty drives.
- **PXE Ramdisk Fragmentation Limits**: Increased LiveCD `ramdisk_size` from 4.5GB to 7.5GB to absorb large offline package bundles.
- **Bootimus Extraction PXE Race**: Temporarily disables unextracted ISO profiles in Bootimus until autoinstall parameters are safely committed.

---

## [0.4.0] - 2026-08-24

### Added
- **Automated Bare-Metal Cluster Creation (`create_cluster.sh`)**: Idempotent cluster deployment script that generates ed25519 keys, hydrates `bmctl` YAML, seeds a fake GCR key for Workload Identity Federation, executes preflight verification, and configures `ClusterRoleBinding` permissions.
- **Target OS Script Deployment**: Integrated deployment of `create_cluster.sh` to `/usr/local/bin/` during the `CLUSTER_READY` Ansible role.

### Changed
- **Lab Networking Decoupling**: Scrubbed hardcoded lab IP ranges (replacing `.9.x` with `192.168.4.x` fallbacks) and added architecture diagrams (`docs/LAB_SETUP.md`).
- **Gitea Local Forge Architecture**: Published proposal (`docs/future/gitea-expansion-proposal.md`) for hardened, systemd-jailed Gitea with REST API synchronization.

---

## [0.3.50] - 2026-08-22

### Added
- **Pre-Flight Lab Dependency Auditor (`check-lab-setup.py`)**: Automated diagnostic script validating Step CA mTLS certificates, GCP IAM permissions, 19 mandatory GDC APIs, Bootimus PXE reachability, and VRF network boundaries.
- **Aggressive Log Space Capping**: Deployed centralized `logrotate` (50MB/shard, 14-day retention) and clamped `systemd-journald` to 50MB max (`SystemMaxUse=50M`, `SystemMaxFileSize=10M`) to eliminate runaway log disk pressure loops.
- **CIS-Compliant System & Kernel Auditing**: Configured `rsyslog` routing and `auditd` rules (`/etc/audit/rules.d/99-gdc-audit.rules`) monitoring critical system files (`/etc/passwd`, `/etc/sudoers`, `/etc/shadow`).

### Changed
- **Unified Cache Bucket**: Replaced hardcoded GCS bucket strings with `DEPENDENCY_CACHE_GCS_BUCKET`.

---

## [0.3.19] - 2026-08-12

### Added
- **Subiquity Phone-Home Timeout Gate**: Limited Subiquity `phone_home` retries to `tries: 2`, resolving a 23-minute hang when the GDC Companion API is unreachable.
- **Offline Bootstrapping Payload**: Configured `user-data.j2` to generate `/target/etc/gdc/fallback-config.json` containing complete network, peer, and GCP variables for offline bootstrapping.

### Changed
- **Environment Isolation**: Isolated LiveCD boot parameters from Target OS runtime variables using the `BOOTSTRAP_*` namespace.

---

## [0.3.14] - 2026-08-11

### Added
- **Linux VRF Cluster Network Isolation**: Placed Kubernetes VLAN interfaces (`vlan109`) into `vrf-k8s` routing tables, isolating cluster traffic from the node management network.
- **Graceful API Fallbacks**: Defaulted network interfaces to safe DHCP with generic hostnames (`gdc-default`) when Companion API queries fail.

---

## [0.2.23] - 2026-08-08

### Added
- **Granular Machine State Guardrails**: Added `MACHINE_STATE_STOP_STAGE` to allow controlled playbook execution halts with mandatory diagnostic telemetry generation.

### Fixed
- **HWE Kernel Initramfs Deadlock**: Refactored `user-data.j2` late-commands to compile initramfs strictly for the highest semantic-versioned kernel detected on target storage.
- **Subiquity Schema & Package Verification**: Fixed `shutdown: reboot` schema validation and replaced fragile `dpkg-query` shell tests with declarative Ansible `apt` reconciliation.

---

## [0.2.5] - 2026-07-28

### Added
- **OOP Diagnostics Engine (`collect-node-diagnostics.sh`)**: Refactored diagnostic collection into an OOP test runner with JSON schema validation (`report-schema.json`) and `--no-upload` dry-run capability.
- **Provisioning State Tracking**: Added `system_state` telemetry reporting ("First Boot" vs. "Baseline Ready").

### Fixed
- **APT Package Deadlocks**: Purged `ubuntu-server`, `ubuntu-server-minimal`, and `cloud-init` in late-commands to eliminate circular package installation locks.
- **Nexus Outbound Lockouts**: Set `autoBlock: false` on Nexus proxy repositories to prevent permanent offline repository blocks during transient boot network drops.
- **Kubernetes Swap Enforcement**: Explicitly disabled swap via autoinstall (`swap: {size: 0}`) and persistent fstab comment-outs.

---

## [0.1.130] - 2026-07-26

### Added
- **Target OS Framebuffer Scaling**: Enforced `video=efifb:1280x1024` on target GRUB to prevent early systemd prompts from rendering off-screen.
- **Five-Point Initrd Verification**: Automated post-compilation check in `late-commands` via `lsinitrd` validating LUKS/LVM drivers and omission of buggy AMD modules before reboot.
- **Dynamic Test Discovery Runner (`bin/run_all_tests.py`)**: Automated Python test runner exporting test results and generating dynamic After Action Report (AAR) verification tables.

### Fixed
- **Dracut & LUKS Kernel Line Mapping**: Resolved `dracut` rescue shell timeouts (`vg_system-lv_root does not exist`) by dynamically injecting active LUKS partition UUIDs (`rd.luks.uuid=`) via `blkid` in `late-commands` and pre-seeding `dracut`/`dracut-core`.
- **AMD Zen 4 PSP Driver Deadlocks**: Blacklisted `ccp`, `amd_sfh`, and `pcie_mp2_amd` in GRUB and target `/etc/dracut.conf.d/gdc.conf` to prevent early-boot hardware bus freezes.
- **Subiquity Offline APT Mirror**: Restricted offline APT configuration to `suites: [noble]` to prevent failed update/backport 404 queries on single-release CD-ROM media.

---

## [0.1.119] - 2026-07-21

### Added
- **TPM 2.0 Early-Boot Unsealing**: Switched to native target `dracut` compilation with `tpm2-tss` hooks and systemd cryptenroll bound to PCR `0+2+7`.
- **Driver Blacklist Pruning Hook (`zz-gdc-blacklist`)**: Path-agnostic initramfs hook ensuring zero deadlocking AMD drivers are packaged into boot ramdisks.
- **fTPM Polling Mode**: Enforced `tpm_tis.interrupts=0` in GRUB to bypass buggy fTPM hardware ACPI interrupts on AMD platforms.

---

## [0.1.57] - 2026-07-11

### Added
- **Dynamic SMBIOS Telemetry Injection**: Cloud-init `bootcmd` queries SMBIOS product UUID and MAC address to parameterize Subiquity reporting webhooks prior to installer initialization.
- **Declarative Package Pre-seeding (`packages_config.yaml`)**: Replaced shell scripts with an OOP Python caching engine (`preseed_packages.py`) with strict version guardrails.
- **Automated Superblock Wiping**: Configured recursive superblock wiping on disks and partition elements to ensure clean automated re-installs on dirty storage.

---

## [0.1.26] - 2026-07-06

### Added
- **Centralized Version Tracker (`VERSION`)**: Standardized version management via root `VERSION` file with automated sync to build scripts.
- **TPM 2.0 Recovery Utility (`bin/recover-tpm-unseal.sh`)**: Created rescue script to unlock LUKS via motherboard TPM, mount system partitions, and rebuild initramfs from the Live CD.

### Fixed
- **Offline Ansible Installation Failure**: Resolved Subiquity `system-install --download-only ansible` exit status 100 by routing APT mirrors to the local Live ISO Nexus proxy (`127.0.0.1:8081/repository/gdc-apt-proxy/`).
- **TPM 2.0 Cryptenroll Boot Failure**: Fixed `ignoring unknown option 'tpm2-device'` by introducing `systemd-initramfs` and setting `CRYPTENROLL=y` in `cryptsetup-initramfs`.

---

## [0.1.11] - 2026-07-01

### Added
- **Programmatic Nexus Bootstrapping**: Automated provisioning of 7 core offline repositories (APT, Docker OCI, and Raw) and local GPG signing key generation.
- **Administrative Provisioning**: Automated creation of `gdc-admin` with passwordless sudo and SSH keys.
- **System Footprint Slimming**: Purged redundant snap packages (`snapd`, `lxd`, `x11-common`) to reduce attack surface and resource usage.
- **Comprehensive System Diagnostics (`collect-diagnostics.sh`)**: Gathers systemd run-states, listening ports, hardware stats, and 25 GDC GCP endpoint network connectivity checks.

---

## [0.0.85] - 2026-06-30

### Fixed
- **UEFI Bare-Metal Bootloader Verification**: Added `grub_device: true` and `flag: uefi` to EFI partition templates, achieving the project's first successful physical bare-metal boot to completion.

---

## [0.0.80] - 2026-06-25

### Added
- **Stage-Gate Release Pipeline (`src/build/Makefile`)**: Structured build lifecycle into 9 discrete targets (`check-env`, `deps`, `extract`, `hydrate`, `validate`, `assemble`, `test-static`, `test-dynamic`, `deploy`, `publish`).
- **Declarative Jinja2 Templating (`render_templates.py`)**: Replaced fragile shell string replacement with validated Jinja2 templates for `user-data`, `storage_config`, and Netplan.
- **Pre-Flight Static Validator (`validate-hydrated-files.sh`)**: Statically lints cloud-init schemas, systemd services, Netplan configurations, and Python scripts prior to ISO assembly.
- **Isolated QEMU Test Harness (`test/run_qemu_e2e.sh`)**: Headless testing harness with loopback-bound SSH, ephemeral keys, and automated serial log monitoring.

---

## [0.0.50] - 2026-06-18

### Added
- **Google Cloud Build Integration (`cloudbuild.yaml`)**: Cloud remastering pipeline using unprivileged builder containers and GCS bucket lifecycle retention policies.
- **Bootimus PXE Automation CLI (`src/build/bootimus.py`)**: Python CLI for Bootimus PXE server automating filesystem scans, kernel/initrd extraction, and autoinstall parameter enforcement with Infisical credential management.

---

## [0.0.1] - 2026-06-12

### Added
- **Core Architecture Specifications**: Approved specifications `GDC-SPEC-001` through `GDC-SPEC-006` covering ISO generation, baseline installation, post-install provisioning, E2E testing, cluster turnup, and lifecycle update flows.
- **Hub-and-Spoke Offline Architecture**: Designed LiveCD architecture running ephemeral Gitea (Git) and Sonatype Nexus (APT/OCI/Raw) services on OverlayFS RAM loopback to support 100% offline air-gapped provisioning.
- **Dynamic 1-Disk vs. 2-Disk LVM Topology**: Storage generator (`generate_storage_config.sh`) auto-detecting and sizing logical volumes, isolating latency-sensitive `etcd` and `containerd` partitions from bulk storage.
- **Hardware-Sealed Security Architecture**: Designed TPM 2.0 remote attestation, EK/AK certification, temporary transition key unsealing, and `systemd-cryptenroll` PCR `0+2+7` binding.

---

## Architectural Decision Records (ADRs)

1. **ADR-001: Tooling Choice — Xorriso over Packer**
   - *Decision:* Use standard Linux filesystem tools (`xorriso`, `mksquashfs`) instead of Packer VMs.
   - *Context:* Remastering must be fast, deterministic, reproducible in CI/CD containers, and directly integrated with Infrastructure-as-Code without nested hypervisor requirements.
2. **ADR-002: Service Topology — Ephemeral Hub-and-Spoke on OverlayFS**
   - *Decision:* Run local dependency services (Gitea, Nexus) directly from an OverlayFS RAM partition on the bootloader LiveCD.
   - *Context:* Target nodes must install and provision in completely air-gapped environments without external internet or network registries.
3. **ADR-003: Storage Architecture — Dedicated Performance Logical Volumes**
   - *Decision:* Partition disks into dedicated Logical Volumes for `etcd`, `containerd`, metrics, and logs; isolate etcd on Disk 1 in dual-disk deployments.
   - *Context:* Prevents heavy customer I/O (`/customer/local-disk`, SDS) or runaway logs from starving etcd write latency, satisfying strict GDC bare-metal prerequisites.
4. **ADR-004: Network Isolation — Linux VRF for Cluster Traffic**
   - *Decision:* Route Kubernetes VLAN interfaces (`vlan109`) via a dedicated Virtual Routing and Forwarding domain (`vrf-k8s`).
   - *Context:* Guarantees strict L3 traffic separation between internal cluster communications and the node management network.
5. **ADR-005: Cryptographic Security — Hardware TPM 2.0 PCR Binding with Transition Keys**
   - *Decision:* Format root disks with LUKS using a temporary installation keyfile, then enroll motherboard TPM 2.0 via `systemd-cryptenroll` bound to PCR `0+2+7` before wiping the transition key.
   - *Context:* Solves the "chicken-and-egg" problem where Subiquity cannot natively bind TPM 2.0 during initial drive formatting.
6. **ADR-006: Hardware Compatibility — Low-Memory LUKS PBKDF2 on DRAM-less NVMe**
   - *Decision:* Demote LUKS KDF from Argon2id down to PBKDF2 (1000 iterations) on physical nodes.
   - *Context:* Default Argon2id consumes ~1GB RAM, starving the Host Memory Buffer (HMB) on DRAM-less NVMe SSDs and causing AMD cryptographic coprocessors (`ccp`) to crash the kernel during installation.
