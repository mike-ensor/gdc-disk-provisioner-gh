# Project Progress & Feature Tracker

This document tracks the ongoing implementation and delivery of the GDC Offline Bootloader ISO process. It acts as an active checklist compared to our technical specification files (`docs/specs/`).

> [!NOTE]
> **Major Milestone (2026-06-30):** The GDC Bootloader ISO has successfully achieved its first **absolute physical bare-metal boot to completion** under `v0.0.85-debug`! The installation loop completed flawlessly on physical UEFI single-disk nodes, and all local and remote service boundaries (Gitea and Nexus local caches) are fully integrated.

---

## 1. Specification Stage (Docs & Architecture)

- [x] **GDC-SPEC-001: ISO Generation & Build Pipeline** — Written & Approved
- [x] **GDC-SPEC-002: Baseline Installer & LVM Storage Layout** — Written & Approved
- [x] **GDC-SPEC-002-SEQ: Installation Sequence, Timeline, & Transition Gaps** — Written & Approved
- [x] **GDC-SPEC-003: Ready-Linux Provisioning & Sideloading** — Written & Approved
- [x] **GDC-SPEC-004: ISO Verification & QEMU E2E Testing** — Written & Approved
- [x] **GDC-SPEC-005: Machine Database & Cloud Verification Requirements** — Written & Approved
- [x] **GDC-SPEC-005-TURNUP: GDC Offline Cluster Turnup** — Written & Approved
- [x] **GDC-SPEC-006: GDC Lifecycle Update Flows** — Written & Approved
- [x] **GDC-SPEC-007: GDC Companion Design (Rust Stack)** — Written & Decoupled
- [ ] **GDC-SPEC-008: Non-LUKS Storage Provisioning Feature** — Planned
- [x] **GDC-SPEC-009: Temporary Installer Removal Plan** — Written & Planned
- [x] **GDC-SPEC-DEP-001: GDC Master Dependency Matrix** — Written & Approved
- [x] **GDC-SPEC-READY-LINUX: GDC Ready-Linux & Idempotent Post-Install Provisioning Plan** — Written & Approved
- [x] **Stage-Gate Software Supply Chain Design (`docs/specs/01-iso-build-pipeline.md`)** — Aligned & Approved
- [x] **Jinja2 Declarative Configuration Templating (`docs/specs/02-baseline-installer.md`)** — Aligned & Approved
- [x] **Port-forwarding Loopback Isolation & SSH Assertions (`docs/specs/04-verification-and-testing.md`)** — Aligned & Approved
- [x] **Decoupled Job-Release Orchestration Guide (`docs/DEVELOPMENT.md`)** — Aligned & Approved
- [x] **Governance Rules (`GEMINI.md`)** — Documented
- [x] **Domain Glossary (`DICTIONARY.md`)** — Documented
- [x] **Architecture User Guides (`docs/DISKS.md`, `docs/NETWORK.md`, `docs/SECURITY.md`, `docs/POST-INSTALL.md`)** — Documented & Aligned

---

## 2. Feature Checklist & Implementation Status

### Phase 1: ISO Generation & Build Pipeline (Stage-Gate Model)

- [x] **Workspace Scaffolding**
  - [x] Create `src/build/Makefile` for multi-stage orchestration
  - [x] Create `src/build/remaster.sh` script for ISO manipulation
  - [x] Integrate GCP target configuration parameters (`PROJECT_ID` and `REGION` in `build.env`)
- [x] **Local Build Caching & Workspace Isolation**
  - [x] Formulate `.cache/` scoped local storage directories (isos, binaries, blobs)
  - [x] Scaffold `.cache/isos/` path for caching blessed OS sources
  - [x] Enforce git ignoring of `.cache/` and `build-workspace/` targets
- [x] **Offline Services Acquisition**
  - [x] Fetch and configure standalone Go-based Gitea binary
  - [x] Fetch and configure Java/JVM & Sonatype Nexus binary (capable of APT/deb, OCI/Docker registry, and Raw Hugging-Face GGUF caches)
- [x] **Discrete Stage-Gate Lifecycle Targets**
  - [x] Stage 1: Environment check (`make check-env`) with nested virtualization diagnostics
  - [x] Stage 2: Acquire dependencies (`make deps`) with cryptographic SHA-256 integrity checks (Rule 1.4)
  - [x] Stage 3: Extract source media (`make extract`) using non-root xorriso layers (Rule 1.8)
  - [x] Stage 4: Render templates (`make hydrate`) via `src/build/render_templates.py` (Rule 1.9)
  - [x] Stage 5: Validation gate (`make validate`) running shellcheck, yamllint, and cloud-init schemas
  - [x] Stage 6: Remaster configuration (`make assemble`) compiling final hybrid ISO via `xorriso`
  - [x] Stage 7: Static inspection (`make test-static`) auditing ISO file table positions and permissions
  - [x] Stage 8: Dynamic E2E boot (`make test-dynamic`) spawning VM and asserting interfaces
  - [x] Stage 9: Release deployment (`make deploy`) copying final build to regional GCS buckets
  - [x] Stage 10: Publication (`make publish`) updating symlinks and generating signed provenance JSONs
- [x] **Pre-seeding Asset Pipeline & Space Guardrails**
  - [x] Configure Gitea Playbook Mirror:
    - [x] Dynamically clone `UPSTREAM_PLAYBOOKS_REPO` at ISO creation time
    - [x] Inject read-only Git `pre-receive` hook to block direct local pushes
    - [ ] **FUTURE INVESTIGATION:** Research background sync scheduler/timer for pull-only updates on target OS
  - [x] Configure Nexus Repository Group boundaries (merge Hosted & Proxy cache lines):
    - [x] Establish OCI Docker Registry Group (Port 5001) for direct `docker push` + public pull-through cache
    - [x] Establish APT Repository Group for local deb uploads + upstream cache proxies
    - [x] Establish LLM Raw Group for local GGUF weight files + Hugging Face proxies
  - [x] Enforce strict 40 GB maximum pre-seed footprint cap on `/custom-data/nexus/` to prevent single-disk out-of-space crashes
  - [x] Pre-populate initial offline caches & packages into Gitea and Nexus blobs
    - [x] Preload official Google GDC dependencies into the local Nexus APT repository (Ref: https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/installing/package-server#needed_packages_and_their_dependencies)
    - [x] Pre-seed and upload system OCI images to the local Nexus Docker hosted registry with authenticated client registry-mirroring (Ref: https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/how-to/node-agent#deploy-na and https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/installing/registry-mirror#authenticate_with_your_registry_and_share_the_tls_certificate)
    - [x] Download and pre-seed the standalone Google Cloud SDK (gcloud CLI) archive into `/custom-data/tools/` for offline installation (Ref: https://docs.cloud.google.com/sdk/docs/install-sdk#latest-version)
    - [x] Compare system packages with baseline Ubuntu Core ISO (`dpkg --get-selections | grep -v deinstall`) and download missing dependencies into local Nexus APT repository (APT Hosted/Proxy)
- [x] **Live ISO systemd Integration**
  - [x] Configure Live environment `live-gitea.service` unit file (restricted to localhost loopback `127.0.0.1` binding)
  - [x] Configure Live environment `live-nexus.service` unit file (restricted to localhost loopback `127.0.0.1` binding)
  - [ ] Set up live OverlayFS mounting scripts for RAM-execution (FUTURE INVESTIGATION)
- [x] **Outer FS Remastering Compilations (YAGNI & Performance)**
  - [x] SquashFS Separation Strategy (storing Gitea/Nexus custom data on outer ISO filesystem for sub-10 second repacks)
  - [x] Dynamic build-time hashing for user credentials using randomized salt SHA-512 rounds (Rule 5.4)
  - [x] Bypassing Casper integrity check drop-to-shells by deleting `/md5sum.txt` (Rule 5.1)
  - [x] High-Security Logging Webhook configuration streaming Subiquity logs to local Admin Workstation proxy

---

### Phase 2: Baseline Installer (Boot, LVM Layout & Storage)

- [x] **Autoinstall Configurations & Jinja2 Templating**
  - [x] Design smart installation logging structures (`log_goal` and `log_fail`)
  - [x] Integrate automated error traps and exit-line captures inside partition scripts
  - [x] Create `/nocloud/user-data` autoinstall schema
  - [x] Configure DHCP networking settings
  - [x] Redirect autoinstall APT source to local live Nexus APT proxy
  - [x] GRUB boot loader config specifying unattended autoinstall target `ds=nocloud;s=/cdrom/nocloud/`
  - [x] Pure Jinja2 declarative rendering using Python yaml serialization to avoid spacing corruption
- [x] **Enterprise LVM Provisioning & Multi-Disk Topology**
  - [x] Formulate dynamic 1-or-2 disk auto-sizing script (`generate_storage_config.sh`)
  - [x] Optimize dual-disk setups: Isolate etcd/OS to Disk 1 (System Disk); dedicate Disk 2 (Data Disk) to heavy customer storage (local-disk & SDS) to isolate leader consensus latencies
  - [x] Formulate single-disk scaling algorithms (scale Gitea, Nexus, and local-disk to fit 250GB)
  - [x] Define `/boot/efi` (1 GiB, FAT32) and `/boot` (2 GiB, EXT4) physical boot partitions
  - [x] Initialize Volume Group `vg_system` backing LUKS container on `/dev/nvme0n1p3`
  - [x] Allocate Logical Volumes inside `vg_system` with custom tuned mounts:
    - [x] `lv_root` (20 GiB, EXT4, defaults) — Base system files
    - [x] `lv_var` (20 GiB, EXT4, defaults,noatime) — Kubelet states and runtime data
    - [x] `lv_var_log` (15 GiB, EXT4, defaults,noatime) — Isolated logs space for fluent-bit buffer
    - [x] `lv_metrics` (10 GiB, EXT4, defaults,noatime) — Isolated metrics space for GDC buffers
    - [x] `lv_containerd` (30 GiB, XFS, defaults,noatime,prjquota) — Isolated image space
    - [x] `lv_etcd` (20 GiB, EXT4, noatime,nodiratime,commit=1) — Performance-isolated etcd database
    - [x] `lv_etcd_events` (5 GiB, EXT4, noatime,nodiratime,commit=1) — Performance-isolated etcd events
    - [x] `lv_gitea` (20 GiB, EXT4, defaults,noatime) — Persistent Gitea git storage boundary
    - [x] `lv_nexus` (150 GiB, EXT4, defaults,noatime) — Persistent Nexus package/image cache boundary
    - [x] `lv_local_disk` (100 GiB max, XFS, defaults,noatime,prjquota) — GDC standalone local-disk provisioner
    - [x] `lv_sds` (remainder, XFS, defaults,noatime) — Allocated for SDS system backends
- [x] **FUTURE INVESTIGATION: Linux VRF for Multi-IP Isolation**
  - [x] Explore Linux VRF to support two IPs on a single physical interface (see `docs/future/linux-vrf.md`)
  - [x] Complete full technical specification for VRF-based routing isolation
- [ ] **FUTURE INVESTIGATION: Installation Companion Webhook Receiver ("install-companion")**
  - [ ] Research/Design a secure, lightweight deployment companion app
  - [ ] Translate/forward Subiquity webhook logs to GCP Cloud Logging
  - [ ] Explore other potential installer helper hooks (e.g. dynamic state verification, network checks)
  - [ ] **FUTURE TASK:** Investigate authorization and other methods of identification for webhook logging later
  - [ ] **FUTURE FEATURE:** Integrate cloud-init phone-home module (https://docs.cloud-init.io/en/latest/reference/modules.html#phone-home) to report post-boot completion status to GDC Companion
  - [ ] **FUTURE FEATURE:** Reach out to the "companion" API during build-time inside `remaster.sh` to dynamically retrieve target VLAN tags, subnets, and gateways
  - [ ] **FUTURE FEATURE:** Build out a local Mock Companion Service or expand `machine_orchestration` to allow structured `gdc-companion` simulation data for easier air-gapped testing (handling Connection failure timeouts gracefully)
  - [ ] **FUTURE FIX:** Address CD-ROM extraction gap during Subiquity `late-commands` so `bmctl` binaries successfully migrate from the ISO `/custom-data/tools` into persistent `/var/gdc-install/tools` storage for subsequent Ansible stages

---

### Phase 3: Ready-Linux Provisioning, Hardening & Zero-SSH

- [x] **First-Boot State Transition & Mitigating Gaps**
  - [x] Subiquity `late-commands` rsync script for Gitea/Nexus partition migrations
  - [x] Deploy target systemd service units for persistent Gitea and Nexus
  - [x] **Transition Gap 3.1: The Boot-Unlock Chicken-and-Egg Transition** (LVM encrypted with temp passcode -> late-commands writes one-time `/boot/temp_key.key` -> reboot unlocks automatically -> Ansible seals to TPM 2.0 PCR 0+7 -> deletes key and wipes temporary passcode slot)
  - [x] **Transition Gap 3.2: Race Conditions wait-for-port handshakes** (Ansible playbooks block via `wait_for` until Gitea Port 3000 and Nexus Port 8081 are healthy)
  - [x] **Transition Gap 3.3: Serial Console Logger Deadlocks** (Wrap success signaling to `/dev/ttyS0` in non-blocking loop with a 3-second timeout fallback)
- [x] **Ansible-Pull Bootstrap Automation**
  - [x] Create systemd `gdc-provision.service` to run `ansible-pull` on first boot
  - [x] Configure environmental signed-commits toggles (`/etc/default/gdc-provision`): Development vs Production `--verify-commit` activation
  - [x] Configure persistent Gitea & Nexus persistent service states in playbook
  - [x] Execute safe offline system-wide upgrades (`apt-get upgrade`) in playbook
  - [x] Implement loop package installations (`POST_INSTALL_PACKAGES` list matching `build.env`)
  - [x] Configure cron cycles for persistent `ansible-pull` checking
- [x] **Administrative Configurations**
  - [x] Create `gdc-admin` user
  - [x] Deploy passwordless sudo config
  - [x] Inject passwordless SSH key pair
- [ ] **Hardware Security (TPM 2.0) & Zero-SSH Bootstrapping**
  - [x] LUKS decryption enrollment using `systemd-cryptenroll` for PCR `0+7`
  - [x] Configure target `/etc/crypttab` with `tpm2-device=auto` and rebuild systemd-based initramfs natively via `initramfs-tools` and `cryptsetup-initramfs` (`crypt` and `lvm` modules) with blacklisted fTPM-deadlocking drivers
  - [x] Establish secure randomized Recovery Key and wipe insecure temporary passcode slot
  - [ ] SSH host key TPM-secure binding using `ssh-tpm-agent`
  - [x] Generate TPM-backed device identity certs via Step-CA (Remote Attestation, Quote & Cloud CSR verification)
  - [ ] **NodeAgent mTLS Certificate Pre-Seeding:** Automated injection of Server CA, Client CA, and Node Server Cert/Key to enable 100% Zero-SSH bootstrapping
  - [ ] **Future GPG Signed-Commit Enforcement:** Mandate cryptographic signed-commits for Ansible-Pull (`--verify-commit` activation) and configure local GPG release keyrings during ISO pre-seeding for 100% verified playbook executions
- [ ] **CIS Hardening & Slimming**
  - [ ] Implement Ansible roles for CIS Level 2 benchmark rules
  - [x] Implement Ansible tasks to purge unneeded packages (snapd, x11, lxd, compiler runtimes, etc.)
- [x] **Idempotent Post-Install System Hardening (Ansible-Pull)**
  - [x] Task 01: Wait on local boundary hubs readiness (Gitea Port 3000, Nexus Port 8081)
  - [x] Task 02: Programmatic Sonatype Nexus repository group/hosted/proxy setup (gdc-apt-hosted/proxy, gdc-docker-group port 5001, hosted port 5002)
  - [x] Task 03: Create `/var/gdc-install/` workspace directories (fully owned by `gdc-admin` with `0755` permissions)
  - [x] Task 04: Implement `gdc-admin` user creation, supplementary groups setup (`sudo`, `docker`), and passwordless sudoers rules
  - [x] Task 05: Offline APT sources setup (Write DEB822 sources and deactivate default public Ubuntu files)
  - [x] Task 06: Package installation loop (`gdc_core_packages` list containing `containerd.io`, `docker-ce`, `chrony`, `step-cli`, etc.; Tagged: `external-dependency`)
  - [x] Integrate declarative APT reconciliation and purge legacy dpkg-query wrappers
  - [x] Task 07: Deploy persistent kernel sysctl tuning parameters (`99-gdc.conf` for max inotify and BPF JIT)
  - [x] Task 08: Enforce universal UTC system timezone and configure Chrony NTP with Google pools (Tagged: `external-dependency`)
  - [x] Task 09: Setup Container engines (`docker-ce` daemon and `containerd` config/hosts TOML definitions for local mirrors redirects)
  - [x] Task 10: Standalone non-apt Google Cloud SDK deployment, silent installer configuration, and global symlinking (Tagged: `external-dependency`)
  - [x] Task 11: Security configurations (Mask `ufw` firewall, implement reboot-free unattended-upgrades with blacklist)
  - [x] Task 12: Offline management deployment
  - [x] Integrate robust `import_tasks` and overarching system halting using `MACHINE_STATE_STOP_STAGE` guard rails
- [x] **URGENT BUG:** `LINUX_READY` diagnostic reports fail to collect proper HWE kernel statuses due to stale initramfs packages. The node requires a full manual reboot to properly validate.
  - [x] Configure diagnostic tools to tag bypassed overarching pipeline stages as `BYPASSED` (Deploy skeleton update scripts and link daily logrotate hourly with mode `0755` executable permissions)
  - [x] Deploy weekly cron job for automated Google Cloud SDK updates (`gcloud components update -q`; Tagged: `external-dependency`)
  - [x] Ensure all playbook tasks are tagged according to GDC Machine State Taxonomy
- [ ] **FUTURE SECURITY TASK:** Implement GRUB bootloader password protection (`grub-mkpasswd-pbkdf2`) when not running in `GDC_DEBUG_MODE` to prevent physical boot parameter tampering.

---

### Phase 4: Offline Updates & USB Sideloading

- [x] **USB Sideload Integration**
  - [x] Design headless automated USB updater (`udev` rules & systemd triggers detecting `GDC-UPDATE-USB`)
  - [x] Formulate cryptographic signature verification standards (GPG commit checks & openssl SHA-256 update signatures)
  - [x] Script headless update execution loops (`gdc-headless-update.sh` with console audio beeps)
  - [ ] Create `gdc-update` CLI tool to detect, mount, and pull USB bundles
  - [ ] Write update sync script for Git Bundles to Gitea
- [ ] **API Upload Sync Pipelines**
  - [ ] Write Nexus API upload scripts for APT debs
  - [ ] Write Docker registry push wrapper scripts (supporting secure registry authentication and TLS certificate sharing; Ref: https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/installing/registry-mirror#authenticate_with_your_registry_and_share_the_tls_certificate)
  - [ ] Write LLM weights Raw upload sync tooling
- [ ] **Lifecycle Update Pathways**
  - [ ] Option A: Low-Internet Sideload Pathway (GDC-UPDATE-USB or authenticated GCS bucket sideloads)
  - [ ] Option B: Connected Tunnel Pathway (outbound-only WireGuard reverse VPN tunnel execution)
- [ ] **Pre-Update Safety: Local Cluster Backup**
  - [ ] Mandatory task: Execute local automated `bmctl backup cluster` prior to OS or platform modifications
  - [ ] Implement exit-code 0 verification and fallback traps aborting update on backup failure
- [ ] **Diagnostic Audio Indicators**
  - [ ] Implement local physical sound signaling (Success: 1 long high-pitch beep; Error/Fail: 2 rapid loud beeps)

---

### Phase 5: ISO Verification & Testing Framework

- [x] **Static Verification (Tier 1)**
  - [x] Create `test/validate_iso_static.sh` script
  - [x] Integrate cloud-init schema and YAML syntax verification
  - [x] Integrate dynamic sandboxed Netplan verification (`netplan generate`) into the pre-flight validator
  - [x] Use `xorriso` non-root extraction configuration audits to avoid loopback sudo permissions on secure runners
- [x] **First-Boot Self-Test Playbook (local.yml) & Idempotency**
  - [x] Create `test/verify_ansible.sh` playbook testing harness (Syntax check + Local check-mode dry run with `--check --diff`)
  - [x] Service Port readiness checks (Gitea 3000, Nexus 8081)
  - [x] Execution verification (Hello World task)
  - [x] Partition block querying task (lsblk)
  - [x] Outbound gateway ping test task (ping 8.8.8.8)
  - [x] Enforce strict idempotency standards (twin sequential executions returning `changed=0`)
- [x] **Isolated Cloud Sandbox Testing (GCE)**
  - [x] Create `test/gce_startup_test.sh` first-boot startup script
  - [x] Create `test/provision_gce_sandbox.sh` GCE lifecycle orchestrator with nested-virtualization
  - [x] Program local port socket-mocks for Gitea/Nexus during playbook validation
  - [x] Automate GCE serial log polling and mandatory cloud VM teardown
- [x] **Headless E2E Boot Testing (Tier 2)**
  - [x] Create `test/run_qemu_e2e.sh` script
  - [x] Implement dual-disk sparse block device allocations (250G and 350G SSD targets)
  - [x] Script serial log console monitoring with automated polling and timeout boundaries
  - [x] Implement software TPM emulator (`swtpm`) isolated socket mapping via `mktemp` to prevent port collisions
  - [x] Implement remote port-forwarding SSH assertion suite over local-only `127.0.0.1:2222` (Ref: `src/build/bootimus.py`)
  - [x] Generate dynamic short-lived ephemeral SSH key pairs wiped upon test cleanup
  - [x] Global signal trap cleanups (`trap EXIT`) killing background QEMU and `swtpm` subprocesses
  - [x] Dual-Track verification: Support virtual cloud emulator vs physical bare-metal lab PXE boots (via Bootimus & Synology sync)
  - [x] **Pre-Reboot Initramfs Verification Checks:** Programmed automated tests in Subiquity `late-commands` using `lsinitramfs` to verify transition keyfile packaging, crypt/lvm modules inclusion, storage driver presence, and absolute exclusion of deadlocking drivers prior to first reboot.
  - [x] **Static Command & Option Auditor:** Built a static CLI option auditor inside `test/validate_artifacts.py` parsing and testing hydrated cloud-init user-data scripts against compiled host manual pages (`man`) and help menus (`--help`).
  - [x] **Consecutive-Success Stability Verification:** Implemented feedback control loops in `src/build/bootimus.py` to ensure custom PXE boot parameters and kernel redirections persist consecutively over 20-second database settling windows.
  - [x] **Dynamic Test Discovery & Reporting Pipeline:** Engineered a dynamic unittest discovery engine (`bin/run_all_tests.py`) that executes, gathers, and groups all 40+ unit/static tests natively and outputs fully automated, Category-grouped verification tables in the human-readable build reports, removing hardcoded test registries completely.

---

### Phase 6: Standalone & Multi-Node Cluster Turnup (Stage 5)

- [ ] **Offline Cluster Deployment**
  - [x] Seed GDC bootstrap workstation credentials (`bmctl` and `nodeagent` integrated)
  - [ ] **Authenticate `gcloud` using a service-account key securely on the new machine during CLUSTER_TURNUP (TBD on delivery mechanism)**
  - [ ] Create `bmctl` configuration file (`cluster-config.yaml`) defining target cluster IP networks, VIPs, and storage paths
  - [ ] Execute `bmctl create cluster` offline using pre-seeded container layers in local Nexus group registry
  - [ ] Redirect container registry mirror to local Nexus Group Registry loopback Port `5001`
  - [ ] Enforce Keyless/GSA-less Security Profile (omitting static JSON credential keys on node disk, using NodeAgent TPM-bound federation instead)
  - [ ] Deploy GDC NodeAgent daemonset via offline `bmctl deploy nodeagent` using local registries
  - [ ] Configure standalone NodeAgent secure mTLS gRPC channel over Port `9192`
- [ ] **Multi-Node (3-Node) Cluster Coordination Plan**
  - [ ] Role designation (Primary Node 1 Bootstrap vs passive Node 2/3 Secondary machines)
  - [ ] Offline SSH trust & passwordless root SSH key distribution baked in Gitea
  - [ ] Redirect Node 2 and Node 3 container image fetches to Node 1's local IP on Port `5001`
  - [ ] Implement reachability handshakes and pre-requisite package triggers (e.g. `socat`, `conntrack`) prior to HA cluster turnup

---

### Phase 7: Centralized Coordination Gateway (GDC Companion)

- [x] **Decoupled Architecture & API Contract**
  - [x] GDC Companion microservice migrated to dedicated peer repository `gdc-companion`
  - [x] Axum Rust Stack (SQLx + Serde DTOs) providing compile-time memory safety and sub-20MB container footprint
- [x] **Hierarchical Recursive Variable Overrides**
  - [x] Global -> Fleet -> Machine overrides utilizing recursive deep-merge algorithm
  - [x] Automated Rust unit tests for multi-level overrides and list augmentations
- [x] **Relational Database Design & Gateway API**
  - [x] PostgreSQL relational design backed by CloudNativePG (CNPG) operator
  - [x] Kubernetes Gateway API layout terminating client certificates securely via Mutual TLS (mTLS)

---

## 3. Unplanned & Future Reference

- [ ] **GDC-SPEC-008: Non-LUKS Storage Provisioning Feature** (Enables compiling unencrypted target OS installations with a 'GDC_ENABLE_LUKS=false' build parameter to bypass specialized UEFI/TPM hardware blocks; Ref: `docs/specs/08-no-luks-feature-plan.md`)
- [ ] **FUTURE TASK: Configure for Clustered State & CMDB Integration**
  - [ ] **Change Host Name** to match upstream by pulling data from the Machine Database (CMDB).
  - [ ] **Remove Temp User** (`temporary-installer`) from the machine after transitioning to a healthy state (Ref: `docs/specs/09-temporary-installer-removal.md`).
  - [ ] **BMCTL Alignment:** Ensure the installed version matches the correct pulled `bmctl` binary.
  - [ ] **Node Agent Alignment:** Deploy the Node Agent version that strictly matches the target `bmctl` version.
- [x] **URGENT:** Investigate ISO creation report and tests (gcloud SDK was not installed on target OS, potentially due to missing binaries during ISO creation phase)
- [ ] **Multi-LTS Target Compilation Architecture (Support for 22.04 Jammy & 26.06 Future LTS Options)**
  - [ ] **Docker Builder Generalization:** Parameterize `src/build/Dockerfile` compilation rules to build and cache isolated compile images for separate target LTS releases.
  - [ ] **GCS Packages Isolation:** Generalize Google Cloud Storage cache prefixes to include release target trees (e.g. `gs://.../packages/22.04/`, `gs://.../packages/24.04/`) to prevent library pollution across target node OS sets.
  - [ ] **Preseed Resolvers Verification:** Enhance `preseed_packages.sh` to dynamically query and map release repositories matching `_UBUNTU_VERSION`.
  - [ ] **Variables & Settings Audit:** Review LVM fstab patterns, Netplan DBus protocols, and systemd units for system-level differences across Jammy, Noble, and Plucky configurations.
- [x] **Hardware Diagnostics & Node Uniqueness Updates (Near Future)**
  - [x] **Enforce MAC-based Node Uniqueness:** Migrated system identity/uniqueness mapping in `bin/collect-node-diagnostics.sh` to physical MAC addresses instead of the duplicate motherboard `System UUID` (which conflicts across Zen 4 bare-metal platforms).
  - [x] **Hardware Inventory Auto-Discovery:** Integrated auto-discovery and telemetry for CPU cores, RAM DIMM serials, NVMe storage devices, AMD fTPM modules, and NIC MACs into both JSON and text reports.
- [ ] **FUTURE INVESTIGATION:** Investigate the use of a custom webserver to serve dynamic metadata for ISO boot (https://docs.cloud-init.io/en/23.3.2/reference/datasources/nocloud.html#method-3-custom-webserver-kernel-commandline-or-smbios and https://docs.cloud-init.io/en/23.3.2/reference/datasources/nocloud.html#example-meta-data). This would be served up dynamically by `gdc-companion` using kernel commandline parameters or SMBIOS string values, completely eliminating the need for static metadata files embedded inside the ISO.
- [ ] **FUTURE TASK:** Clean up older compiled ISOs in the GCS bucket (`gs://gdc-disk-provisioner-isos/sync/` and `gs://gdc-disk-provisioner-isos/archived/`) to reduce cloud storage retention costs over time (Low Priority).
- [ ] **FUTURE TASK:** Rip out the dynamic python execution of `generate_banner.py` from the ISO build pipeline and replace it with a single, static `boot-banner.txt` template inside `src/build/templates/` to decouple Python execution from the baseline ISO assembly.
- [ ] **APT** configuration
  - [ ] https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#apt
  - [ ] https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#fallback
- [ ] **Ubuntu Pro** config - https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#ubuntu-pro
- [ ] **Error handling during install**
  - [ ] https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#error-commands
