# Project Progress & Feature Tracker

This document tracks the ongoing implementation and delivery of the GDC Offline Bootloader ISO process. It acts as an active checklist compared to our technical specification files (`docs/specs/`).

> [!NOTE]
> **Major Milestone:** We now have a **CLUSTER_READY** stage ISO in with `0.2.31-debug`!
>
> **Previous Milestone (2026-06-30):** The GDC Bootloader ISO has successfully achieved its first **absolute physical bare-metal boot to completion** under `v0.0.85-debug`! The installation loop completed flawlessly on physical UEFI single-disk nodes, and all local and remote service boundaries (Gitea and Nexus local caches) are fully integrated.

---

## 1. Specification Stage (Docs & Architecture)

- [x] **GDC-SPEC-001: ISO Generation & Build Pipeline** (`docs/specs/01-iso-build-pipeline.md`) — Written & Approved
- [x] **GDC-SPEC-002: Baseline Installer & LVM Storage Layout** (`docs/specs/02-baseline-installer.md`) — Written & Approved
- [x] **GDC-SPEC-002-SEQ: Installation Sequence, Timeline, & Transition Gaps** (`docs/specs/02b-installer-sequence-and-timeline.md`) — Written & Approved
- [x] **GDC-SPEC-003: Ready-Linux Provisioning & Sideloading** (`docs/specs/03-ready-linux-provisioning.md`) — Written & Approved
- [x] **GDC-SPEC-004: ISO Verification & QEMU E2E Testing** (`docs/specs/04-verification-and-testing.md`) — Written & Approved
- [x] **GDC-SPEC-005: Machine Database & Cloud Verification Requirements** (`docs/specs/05-cluster-turnup.md`) — Written & Approved
- [x] **GDC-SPEC-005-TURNUP: GDC Offline Cluster Turnup** (`docs/specs/05-cluster-turnup.md`) — Written & Approved
- [x] **GDC-SPEC-006: GDC Lifecycle Update Flows** (`docs/specs/06-lifecycle-update-flows.md`) — Written & Approved
- [x] **GDC-SPEC-007: GDC Companion Design (Rust Stack)** (`docs/specs/07-gdc-companion-design.md`) — Written & Decoupled
- [ ] **GDC-SPEC-008: Non-LUKS Storage Provisioning Feature** (`docs/specs/08-no-luks-feature-plan.md`) — Planned
- [x] **GDC-SPEC-009: Temporary Installer Removal Plan** (`docs/specs/09-temporary-installer-removal.md`) — Written & Planned
- [x] **GDC-SPEC-DEP-001: GDC Master Dependency Matrix** — Written & Approved
- [x] **GDC-SPEC-READY-LINUX: GDC Ready-Linux & Idempotent Post-Install Provisioning Plan** (`docs/specs/03-ready-linux-provisioning.md`) — Written & Approved
- [x] **Stage-Gate Software Supply Chain Design (`docs/specs/01-iso-build-pipeline.md`)** — Aligned & Approved
- [x] **Jinja2 Declarative Configuration Templating (`docs/specs/02-baseline-installer.md`)** — Aligned & Approved
- [x] **Port-forwarding Loopback Isolation & SSH Assertions (`docs/specs/04-verification-and-testing.md`)** — Aligned & Approved
- [x] **Decoupled Job-Release Orchestration Guide (`docs/DEVELOPMENT.md`)** — Aligned & Approved
- [x] **Governance Rules (`GEMINI.md`)** — Documented
- [x] **Domain Glossary (`DICTIONARY.md`)** — Documented
- [x] **Architecture User Guides (`docs/DISKS.md`, `docs/NETWORK.md`, `docs/SECURITY.md`, `docs/POST-INSTALL.md`)** — Documented & Aligned

---

## 2. Feature Checklist & Implementation Status

### Phase 1: ISO Generation & Build Pipeline (Stage-Gate Model) — [`docs/specs/01-iso-build-pipeline.md`](docs/specs/01-iso-build-pipeline.md)

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
  - [x] Stage 2: Acquire dependencies (`make deps`) with cryptographic SHA-256 integrity checks
  - [x] Stage 3: Extract source media (`make extract`) using non-root xorriso layers
  - [x] Stage 4: Render templates (`make hydrate`) via `src/build/render_templates.py`
  - [x] Stage 5: Validation gate (`make validate`) running shellcheck, yamllint, and cloud-init schemas
  - [x] Stage 6: Remaster configuration (`make assemble`) compiling final hybrid ISO via `xorriso`
  - [x] Stage 7: Static inspection (`make test-static`) auditing ISO file table positions and permissions
  - [x] Stage 8: Dynamic E2E boot (`make test-dynamic`) spawning VM and asserting interfaces
  - [x] Stage 9: Release deployment (`make deploy`) copying final build to regional GCS buckets
  - [x] Stage 10: Publication (`make publish`) updating symlinks and generating signed provenance JSONs
- [-] **Pre-seeding Asset Pipeline & Space Guardrails**
  - [-] Configure Gitea Playbook Mirror:
    - [x] Dynamically clone `UPSTREAM_PLAYBOOKS_REPO` at ISO creation time
    - [x] Inject read-only Git `pre-receive` hook to block direct local pushes
    - [ ] FUTURE INVESTIGATION: Research background sync scheduler/timer for pull-only updates on target OS
  - [x] Configure Nexus Repository Group boundaries (merge Hosted & Proxy cache lines):
    - [x] Establish OCI Docker Registry Group (Port 5001) for direct `docker push` + public pull-through cache
    - [x] Establish APT Repository Group for local deb uploads + upstream cache proxies
    - [x] Establish LLM Raw Group for local GGUF weight files + Hugging Face proxies
  - [x] Enforce strict 40 GB maximum pre-seed footprint cap on `/custom-data/nexus/` to prevent single-disk out-of-space crashes
  - [x] Pre-populate initial offline caches & packages into Gitea and Nexus blobs
    - [x] Preload official Google GDC dependencies into the local Nexus APT repository
    - [x] Pre-seed and upload system OCI images to the local Nexus Docker hosted registry
    - [x] Download and pre-seed the standalone Google Cloud SDK (gcloud CLI) archive into `/custom-data/tools/`
    - [x] Compare system packages with baseline Ubuntu Core ISO and download missing dependencies into local Nexus APT
- [-] **Live ISO systemd Integration**
  - [x] Configure Live environment `live-gitea.service` unit file (restricted to localhost loopback `127.0.0.1` binding)
  - [x] Configure Live environment `live-nexus.service` unit file (restricted to localhost loopback `127.0.0.1` binding)
  - [ ] Set up live OverlayFS mounting scripts for RAM-execution (FUTURE INVESTIGATION)
- [x] **Outer FS Remastering Compilations (YAGNI & Performance)**
  - [x] SquashFS Separation Strategy (storing Gitea/Nexus custom data on outer ISO filesystem for sub-10 second repacks)
  - [x] Dynamic build-time hashing for user credentials using randomized salt SHA-512 rounds
  - [x] Bypassing Casper integrity check drop-to-shells by deleting `/md5sum.txt`
  - [x] High-Security Logging Webhook configuration streaming Subiquity logs to local Admin Workstation proxy

---

### Phase 2: Baseline Installer (Boot, LVM Layout & Storage) — [`docs/specs/02-baseline-installer.md`](docs/specs/02-baseline-installer.md)

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
  - [x] Optimize dual-disk setups: Isolate etcd/OS to Disk 1; dedicate Disk 2 to heavy customer storage (local-disk & SDS)
  - [x] Formulate single-disk scaling algorithms (scale Gitea, Nexus, and local-disk to fit 250GB)
  - [x] Define `/boot/efi` (1 GiB, FAT32) and `/boot` (2 GiB, EXT4) physical boot partitions
  - [x] Initialize Volume Group `vg_system` backing LUKS container on `/dev/nvme0n1p3`
  - [x] Allocate Logical Volumes inside `vg_system` with custom tuned mounts (root, var, log, metrics, containerd, etcd, gitea, nexus, local_disk, sds)
- [x] **Linux VRF for Multi-IP Isolation**
  - [x] Explore Linux VRF to support two IPs on a single physical interface
  - [x] Complete full technical specification for VRF-based routing isolation
- [x] **Installation Companion Webhook Receiver ("install-companion")**
  - [x] Research/Design a secure, lightweight deployment [companion app](https://gitlab.com/gcp-solutions-public/retail-edge/gdc-companion)
  - [x] Translate/forward Subiquity webhook logs to GCP Cloud Logging
  - [x] Explore other potential installer helper hooks (e.g. dynamic state verification, network checks)
  - [x] Address CD-ROM extraction gap during Subiquity `late-commands` so `bmctl` binaries successfully migrate from the ISO `/custom-data/tools` into persistent `/var/gdc-install/tools`

---

### Phase 3: Ready-Linux Provisioning, Hardening & Zero-SSH — [`docs/specs/03-ready-linux-provisioning.md`](docs/specs/03-ready-linux-provisioning.md)

- [x] **First-Boot State Transition & Mitigating Gaps**
  - [x] Subiquity `late-commands` rsync script for Gitea/Nexus partition migrations
  - [x] Deploy target systemd service units for persistent Gitea and Nexus
  - [x] **Transition Gap 3.1:** The Boot-Unlock Chicken-and-Egg Transition
  - [x] **Transition Gap 3.2:** Race Conditions wait-for-port handshakes
  - [x] **Transition Gap 3.3:** Serial Console Logger Deadlocks
- [x] **Ansible-Pull Bootstrap Automation**
  - [x] Create systemd `gdc-provision.service` to run `ansible-pull` on first boot
  - [x] Configure environmental signed-commits toggles (`/etc/default/gdc-provision`)
  - [x] Configure persistent Gitea & Nexus persistent service states in playbook
  - [x] Execute safe offline system-wide upgrades (`apt-get upgrade`) in playbook
  - [x] Implement loop package installations (`POST_INSTALL_PACKAGES` list matching `build.env`)
  - [x] Configure cron cycles for persistent `ansible-pull` checking
- [x] **Administrative Configurations**
  - [x] Create `gdc-admin` user
  - [x] Deploy passwordless sudo config
  - [x] Inject passwordless SSH key pair
- [-] **Hardware Security (TPM 2.0) & Zero-SSH Bootstrapping**
  - [x] LUKS decryption enrollment using `systemd-cryptenroll` for PCR `0+7`
  - [x] Configure target `/etc/crypttab` with `tpm2-device=auto` and rebuild systemd-based initramfs natively with blacklisted drivers
  - [x] Establish secure randomized Recovery Key and wipe insecure temporary passcode slot
  - [ ] SSH host key TPM-secure binding using `ssh-tpm-agent`
  - [x] Generate TPM-backed device identity certs via Step-CA
  - [ ] **NodeAgent mTLS Certificate Pre-Seeding:** Automated injection of Server CA, Client CA, and Node Server Cert/Key to enable 100% Zero-SSH bootstrapping
  - [ ] **Future mTLS Phone-Home Authentication:** Inject `write_files` module inside `user-data` to write `/var/lib/cloud/data/ssl/cert.pem` and `key.pem` to enable native mTLS with the `cc_phone_home` POST to the GDC Companion.
  - [ ] **Future GPG Signed-Commit Enforcement:** Mandate cryptographic signed-commits for Ansible-Pull (`--verify-commit` activation)
- [-] **CIS Hardening & Slimming**
  - [ ] Implement Ansible roles for CIS Level 2 benchmark rules
  - [ ] Implement Kubernetes tasks in Ansible to [verify CIS benchmarking](https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/concepts/cis-benchmarks#how_to_audit_benchmarks)
  - [x] Implement Ansible tasks to purge unneeded packages (snapd, x11, lxd, compiler runtimes, etc.)
- [x] **Idempotent Post-Install System Hardening (Ansible-Pull)**
  - [x] Task 01: Wait on local boundary hubs readiness (Gitea Port 3000, Nexus Port 8081)
  - [x] Task 02: Programmatic Sonatype Nexus repository group/hosted/proxy setup
  - [x] Task 03: Create `/var/gdc-install/` workspace directories
  - [x] Task 04: Implement `gdc-admin` user creation and passwordless sudoers
  - [x] Task 05: Offline APT sources setup
  - [x] Task 06: Package installation loop & declarative APT reconciliation
  - [x] Task 07: Deploy persistent kernel sysctl tuning parameters
  - [x] Task 08: Enforce universal UTC system timezone and configure Chrony NTP
  - [x] Task 09: Setup Container engines (`docker-ce` daemon and `containerd` config/hosts TOML definitions)
  - [x] Task 10: Standalone non-apt Google Cloud SDK deployment
  - [x] Task 11: Security configurations (Mask `ufw`, unattended-upgrades)
  - [x] Task 12: Offline management deployment
- [x] Task 13: System logging (auditd, rsyslog) with aggressive size/rotation constraints
- [ ] **IMMEDIATE NEXT FIX:** Fix Netplan VRF indentation mapping error (`/etc/netplan/01-netcfg.yaml:18:8: Error in network definition: expected mapping (check indentation) vrfs: ^`)
- [x] **Diagnostics & System Fixes**
  - [x] Fix URGENT BUG: `LINUX_READY` diagnostic reports fail to collect proper HWE kernel statuses due to stale initramfs.
  - [x] Configure diagnostic tools to tag bypassed overarching pipeline stages as `BYPASSED`
  - [x] Deploy weekly cron job for automated Google Cloud SDK updates
- [ ] **FUTURE SECURITY TASK:** Implement GRUB bootloader password protection (`grub-mkpasswd-pbkdf2`) when not running in `GDC_DEBUG_MODE`
- [ ] **FUTURE SECURITY TASK:** Migrate `refresh-gdc-credentials.sh` and ADC to natively use OIDC Identity Tokens and Workload Identity Federation (once the GDC Companion API is updated).

---

### Phase 4: Offline Updates & USB Sideloading — [`docs/specs/06-lifecycle-update-flows.md`](docs/specs/06-lifecycle-update-flows.md)

- [-] **USB Sideload Integration**
  - [x] Design headless automated USB updater (`udev` rules & systemd triggers detecting `GDC-UPDATE-USB`)
  - [x] Formulate cryptographic signature verification standards (GPG commit checks & openssl SHA-256 update signatures)
  - [x] Script headless update execution loops (`gdc-headless-update.sh` with console audio beeps)
  - [ ] Create `gdc-update` CLI tool to detect, mount, and pull USB bundles
  - [ ] Write update sync script for Git Bundles to Gitea
- [ ] **API Upload Sync Pipelines**
  - [ ] Write Nexus API upload scripts for APT debs
  - [ ] Write Docker registry push wrapper scripts (supporting secure registry authentication and TLS sharing)
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

### Phase 5: ISO Verification & Testing Framework — [`docs/specs/04-verification-and-testing.md`](docs/specs/04-verification-and-testing.md)

- [x] **Static Verification (Tier 1)**
  - [x] Create `test/validate_iso_static.sh` script
  - [x] Integrate cloud-init schema and YAML syntax verification
  - [x] Integrate dynamic sandboxed Netplan verification (`netplan generate`)
  - [x] Use `xorriso` non-root extraction configuration audits
- [x] **First-Boot Self-Test Playbook (local.yml) & Idempotency**
  - [x] Create `test/verify_ansible.sh` playbook testing harness (Syntax check + dry run)
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
  - [x] Implement dual-disk sparse block device allocations
  - [x] Script serial log console monitoring with automated polling and timeout boundaries
  - [x] Implement software TPM emulator (`swtpm`) isolated socket mapping
  - [x] Implement remote port-forwarding SSH assertion suite over local-only `127.0.0.1:2222`
  - [x] Generate dynamic short-lived ephemeral SSH key pairs wiped upon test cleanup
  - [x] Global signal trap cleanups killing background QEMU and `swtpm` subprocesses
  - [x] Pre-Reboot Initramfs Verification Checks
  - [x] Static Command & Option Auditor (parsing hydrated user-data scripts against compiled host manual pages)
  - [x] Consecutive-Success Stability Verification for PXE boot parameters
  - [x] Dynamic Test Discovery & Reporting Pipeline (`bin/run_all_tests.py`)

---

### Phase 6: Cluster Turnup & Target Finalization (CLUSTER_READY) — [`docs/specs/05-cluster-turnup.md`](docs/specs/05-cluster-turnup.md)

- [-] **Mock Companion & Orchestration Simulation (`machine_orchestration`)**
  - [x] Build out Mock Companion Service to serve structured `gdc-companion` telemetry and states in air-gapped labs. (Integrated `fallback-config.json` payload refactor; #9)
  - [x] Ensure connection failure timeouts are handled gracefully during offline turnup. (Explicit `phone_home` tries limit resolving 23min hangs; #9)
  - [ ] Webhook/Phone-Home Integration: Enable node to report post-boot completion and state transitions back to the orchestrator.
  - [ ] **CMDB Identity Sync:** Pull cluster data to dynamically assert and Change Host Name to match the upstream machine database.
- [-] **Standalone Cluster Turnup (`bmctl` & Local Registries)**
  - [x] Seed GDC bootstrap workstation credentials (`bmctl` and `nodeagent` integrated).
  - [ ] Configuration Generation: Automate the creation of `bmctl` configuration file (`cluster-config.yaml`) defining target networks, VIPs, and storage paths.
  - [ ] Registry Mirroring: Redirect container registry mirror to local Nexus Group Registry loopback Port `5001`.
  - [ ] Offline Cluster Creation: Execute `bmctl create cluster` completely offline using pre-seeded local container layers.
  - [ ] Version Alignment: Ensure Node Agent version strictly matches the target deployed `bmctl` version.
- [-] **Security & NodeAgent Integration**
  - [ ] Authenticate `gcloud` using a service-account key securely during CLUSTER_TURNUP.
  - [ ] Enforce Keyless/GSA-less Security Profile (using NodeAgent TPM-bound federation instead of static JSON keys).
  - [ ] Deploy GDC NodeAgent daemonset offline via `bmctl deploy nodeagent`.
  - [ ] Configure standalone NodeAgent secure mTLS gRPC channel over Port `9192`.
- [ ] **Multi-Node (3-Node) Coordination Plan**
  - [ ] Role designation (Primary Node 1 Bootstrap vs. passive Node 2/3 Secondary machines).
  - [ ] Bake offline SSH trust & passwordless root SSH key distribution into Gitea.
  - [ ] Redirect Node 2/3 container image fetches to Node 1's local IP on Port `5001`.
  - [ ] Implement reachability handshakes and pre-requisite package triggers (e.g., `socat`, `conntrack`) prior to HA cluster turnup.
- [ ] **Target Finalization & Cleanup**
  - [ ] Remove Temp User (`temporary-installer`) from the machine after transitioning to a healthy clustered state (Ref: `GDC-SPEC-009`).

---

### Phase 7: Centralized Coordination Gateway (GDC Companion) — [`docs/specs/07-gdc-companion-design.md`](docs/specs/07-gdc-companion-design.md)

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
- [x] **URGENT:** Investigate ISO creation report and tests (gcloud SDK was not installed on target OS, potentially due to missing binaries during ISO creation phase)
- [-] **Multi-LTS Target Compilation Architecture (Support for 22.04 Jammy & 26.06 Future LTS Options)**
  - [ ] Docker Builder Generalization: Parameterize `src/build/Dockerfile` compilation rules to build and cache isolated compile images for separate target LTS releases.
  - [ ] GCS Packages Isolation: Generalize Google Cloud Storage cache prefixes to include release target trees.
  - [ ] Preseed Resolvers Verification: Enhance `preseed_packages.sh` to dynamically query and map release repositories matching `_UBUNTU_VERSION`.
  - [ ] Variables & Settings Audit: Review LVM fstab patterns, Netplan DBus protocols, and systemd units for system-level differences across Jammy, Noble, and Plucky configurations.
- [x] **Hardware Diagnostics & Node Uniqueness Updates (Near Future)**
  - [x] Enforce MAC-based Node Uniqueness: Migrated system identity mapping to physical MAC addresses instead of duplicate motherboard System UUIDs.
  - [x] Hardware Inventory Auto-Discovery: Integrated auto-discovery and telemetry for CPU cores, RAM DIMM serials, NVMe storage devices, AMD fTPM modules, and NIC MACs.
- [ ] **FUTURE INVESTIGATION:** Investigate the use of a custom webserver to serve dynamic metadata for ISO boot. This would be served up dynamically by `gdc-companion` using kernel commandline parameters or SMBIOS string values, eliminating the need for static metadata files embedded inside the ISO.
- [ ] **FUTURE TASK:** Clean up older compiled ISOs in the GCS bucket (`gs://gdc-disk-provisioner-isos/sync/` and `gs://gdc-disk-provisioner-isos/archived/`) to reduce cloud storage retention costs over time (Low Priority).
- [ ] **FUTURE TASK:** Rip out the dynamic python execution of `generate_banner.py` from the ISO build pipeline and replace it with a single, static `boot-banner.txt` template inside `src/build/templates/`.
- [ ] **FUTURE TASK:** Create a regular update system for `collect-diagnostics.sh` to automatically push the newest version to GCS, which is dependent on having a `gcloud` authentication pipeline configured.
- [ ] **APT configuration:** Review fallback error commands.
- [ ] **Ubuntu Pro config:** Implementation guidelines.
- [ ] **Error handling during install:** Improve Subiquity exit-line traps.

- [ ] **FUTURE TASK:** Look into whether `nodeagent` would be a better or more efficient choice to determine if the expected peers are all online compared to the current 5-minute ICMP ping loop.
- [ ] Address HTTP 301 Redirect payload dropping: Updated `INSTALL_COMPANION_URL` to explicitly use HTTPS to ensure telemetry logs are uploaded correctly instead of hitting a redirect and losing the POST body.
- [ ] Address mTLS CN Hostname mismatch: The Companion API uses Zero-Trust logic and verifies the CN of the cert against the node's registered Hostname. The `provision-mtls-cert.sh` script inside the ISO currently uses the physical MAC address, causing `gdc-companion` to throw an HTTP 403. Needs adjustment to request the cert matching `machine_config.hostname`.
