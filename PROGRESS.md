# Project Progress & Feature Tracker

This document tracks the implementation, operational stages, and roadmap of the **GDC Offline Bootloader ISO & Disk Provisioner**. It maps all functional capabilities across both **Architectural Feature Domains** and **Physical Provisioning Lifecycle Stages** (`docs/specs/02b-installer-sequence-and-timeline.md`).

> [!NOTE]
> **Active Version:** `v0.8.4`  
> **Major Milestone (2026-09-07):** Released `v0.7.1-debug` featuring native CIS-CAT Assessor auditing during `LINUX_READY` and self-healing systemd retry loops on `gdc-provision.service` (recovering automatically from transient network/SSL drops into `CLUSTER_READY` completion).  
> **Previous Milestone:** Hardware-resilient `CLUSTER_READY` deployment via `v0.4.38-debug` (bypasses AMD NVMe Host Memory Buffer memory exhaustion, scales up via dual parallel Cloud Builds).  
> **Initial Milestone (2026-06-30):** Achieved project's first **physical bare-metal boot to completion** under `v0.0.85-debug` on physical UEFI single-disk nodes with integrated Gitea and Nexus service hubs.

---

## 1. Active Blockers & High-Profile Bug Track

Immediate blockers and high-profile bugs prioritized for upcoming releases:

| Priority | Issue / Bug | Affected Stage | Impact & Root Cause | Planned Resolution |
| :--- | :--- | :--- | :--- | :--- |
| **P0 (Bug)** | **Netplan VRF Indentation Error** | `Stage 5: Cluster Ready` | `/etc/netplan/01-netcfg.yaml:18:8: Error in network definition: expected mapping (check indentation) vrfs: ^`. Breaks network generation on boot for multi-VRF nodes. | Correct Netplan Jinja2 template indentation and nesting rules in `src/build/templates/netplan.j2`. |
| **P0 (Bug)** | **mTLS Hostname CN Mismatch (HTTP 403)** | `Stage 5: Cluster Ready` | `provision-mtls-cert.sh` requests certificates using physical MAC address instead of `machine_config.hostname`. Zero-Trust Companion API rejects connection with HTTP 403. | Align certificate subject CN generation with `machine_config.hostname`. |
| **P1 (Bug)** | **HTTP 301 Telemetry POST Drop** | `Stage 1 & Stage 5` | Non-HTTPS Companion URLs receive HTTP 301 redirects from gateways, dropping POST bodies and losing diagnostic uploads. | Enforce strict HTTPS URL schemes in `INSTALL_COMPANION_URL` and template configs. |
| **P1 (Feature)** | **Zero-SSH NodeAgent Pre-Seeding** | `Stage 2: First Boot` | Current bootstrapping requires preliminary SSH access for operator debugging. | Automate pre-seeding of Server CA, Client CA, and Node Server Certs during Stage 2. |
| **P1 (Feature)** | **Automated Offline Standalone Turnup** | `Stage 6: Cluster Up` | `bmctl create cluster` currently requires manual execution of `create_cluster.sh`. | Migrate standalone cluster turnup directly into Ansible `CLUSTER_READY` orchestration role. |
| **P2 (Feature)** | **Non-LUKS Storage Mode (`GDC-SPEC-008`)** | `Stage 1: LiveCD` | Bare-metal lab hardware lacking TPM 2.0 or UEFI support cannot complete installation. | Implement `GDC_ENABLE_LUKS=false` build parameter to conditionally bypass LUKS partitioning. |
| **P2 (Feature)** | **3-Node HA Cluster Orchestration** | `Stage 6: Cluster Up` | Multi-node turnup requires manual trust exchanges and registry sharing across nodes. | Implement primary-secondary node role assignment, Gitea SSH key exchange, and registry proxy routing. |

---

## 2. 2D Provisioning Lifecycle & Feature Matrix

The table below maps project capabilities across **Functional Domains** (columns) and **Provisioning Stages** (rows):

| Provisioning Stage | Storage & Partitioning | Hardware & Kernel Security | Networking & Isolation | Core Services & Orchestration | Validation & Diagnostics |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 0: Build & Remaster** | • 40GB Nexus cache cap<br>• Outer SquashFS layout | • Unprivileged build container<br>• SHA-256 dep checks | • Bootimus PXE automation<br>• Dynamic ISO prefix | • 9-Stage Makefile<br>• Concurrent CloudBuild | • Pre-flight static validator<br>• QEMU headless E2E |
| **Stage 1: LiveCD (Installer)** | • Dynamic 1/2-disk LVM<br>• Recursive superblock wipe | • AMD PSP/CCP `rmmod`<br>• PBKDF2 LUKS (HMB fix) | • Subiquity DHCP fallback<br>• Air-gapped Nexus APT | • Subiquity autoinstall<br>• Late-commands rsync | • SMBIOS telemetry injection<br>• Smart install logging |
| **Stage 2: First Boot (Sealing)** | • `/boot/temp_key.key` decrypt<br>• Keyfile secure wipe | • TPM 2.0 PCR 0+7 sealing<br>• Step CA device identity | • Boundary port handshakes<br>• Offline APT sources | • `gdc-provision.service`<br>• Self-healing retry loop | • First-boot self-test<br>• Diagnostics transmit |
| **Stage 3: Second Boot (Verify)** | • Unattended disk decrypt<br>• Dracut UUID kernel line | • Headless auto-unlock check<br>• Blacklist driver pruning | • Local Gitea/Nexus bound<br>• Gateway reachability | • Ansible state verification<br>• Stage guardrails | • 5-point initrd audit<br>• Post-boot health gate |
| **Stage 4: Linux Ready** | • Dedicated LVs for etcd/CRI<br>• Partition size scaling | • CIS-CAT Assessor audit<br>• Auditd file-integrity rules | • Chrony NTP kernel sync<br>• Kernel sysctl tuning | • Docker-CE & Containerd<br>• Google Cloud SDK cron | • `report-schema.json` audit<br>• Logrotate 50MB capping |
| **Stage 5: Cluster Ready** | • `/customer/local-disk`<br>• SDS dedicated block paths | • Global gcloud auth tokens<br>• Workload Identity fake key | • Linux VRF (`vrf-k8s`)<br>• Companion mTLS client | • `create_cluster.sh` deploy<br>• Mock Companion fallback | • Pre-flight lab auditor<br>• Cluster network validator |
| **Stage 6: Cluster Up** | • Host/CRI volume mounts<br>• Container storage pools | • Keyless security profile<br>• NodeAgent mTLS gRPC | • Inter-node reachability<br>• Registry mirror (:5001) | • `bmctl create cluster`<br>• NodeAgent daemonset | • `bmctl check preflight`<br>• Cluster health gate |
| **Day-2 Lifecycle** | • Pre-update cluster backup<br>• USB bundle ingest mounts | • Cryptographic GPG checks<br>• Sigstore/Cosign container | • Reverse WireGuard tunnel<br>• Outbound-only sync | • Headless USB updater<br>• Gitea/Nexus bundle sync | • Audio status beeps<br>• Automated rollback trap |

---

## 3. Stage-by-Stage Task Breakdown

### Stage 0: Build & Remaster (Cloud Build & Tooling)
*Ref: `GDC-SPEC-001` (Pipeline), `GDC-SPEC-004` (Verification)*

- [x] **Pipeline Orchestration & Tooling**
  - [x] Create multi-stage `src/build/Makefile` (`check-env`, `deps`, `extract`, `hydrate`, `validate`, `assemble`, `test-static`, `test-dynamic`, `deploy`, `publish`)
  - [x] Create standalone remaster script `src/build/remaster.sh`
  - [x] Decouple build workflows into `./build-builder.sh` and `./build-iso.sh`
  - [x] Integrate Google Cloud Build pipeline (`cloudbuild.yaml`) with regional GCS bucket sync and 5-build retention policy
  - [x] Concurrent Dual ISO Orchestrator (`concurrent_build.sh`): parallel Cloud Builds for standard and companion-less ISOs
  - [x] Add `--skip-pxe`, auto-increment versioning, and build-state tracking to `concurrent_build.sh`
- [x] **Configuration Hydration & Templating**
  - [x] Pure Jinja2 declarative rendering via `src/build/render_templates.py` (`user-data.j2`, `storage_config.j2`, `netplan.j2`)
  - [x] Parameterize dynamic physical network interfaces (`__PHYS_IFACE__`) instead of hardcoding `eth0`
  - [x] Support git-ignored custom host overlays via `src/build/add-hosts` and `PERSIST_ADD_HOSTS`
  - [x] Standardize version management in root `VERSION` and `.envrc`
- [x] **Asset Pre-Seeding & Storage Guardrails**
  - [x] Formulate `.cache/` local directory hierarchy (`isos/`, `binaries/`, `blobs/`) and git-ignore
  - [x] Fetch standalone Go Gitea binary and Java/Sonatype Nexus binaries
  - [x] Configure Gitea repository mirror with read-only Git `pre-receive` hooks
  - [x] Configure Nexus repository groups (OCI Docker port 5001, APT proxy, Raw proxy)
  - [x] Enforce strict 40GB pre-seed footprint cap on `/custom-data/nexus/`
  - [x] Pre-seed standalone Google Cloud SDK (gcloud CLI) archive into `/custom-data/tools/`
  - [x] OOP Python pre-seeding caching engine (`preseed_packages.py`) with declarative YAML configuration (`packages_config.yaml`)
- [x] **PXE & Bootimus Integration**
  - [x] Bootimus automation CLI (`src/build/bootimus.py`) with Infisical credential retrieval
  - [x] Automated filesystem scanning (`POST /api/scan`) and non-interactive autoinstall parameter locking
  - [x] Extraction race condition protection: temporarily mark ISO profiles `enabled: False` during background extraction
  - [x] Unbuffered polling loop with 4–6 consecutive check verifications (20–30s) to prevent Synology sync clobbering
  - [x] Polling timeout gate (300 attempts / ~20 minutes) preventing infinite polling hangs
- [x] **Testing & Pre-Flight Static Validation**
  - [x] Static validator (`validate-hydrated-files.sh`): cloud-init schema, systemd service analyze, and sandboxed `netplan generate`
  - [x] Strict `ansible-lint` gating inside ISO builder container (`iso-builder 0.0.90`)
  - [x] POSIX `sh -n` syntax validation audits on Subiquity early-commands
  - [x] Headless E2E QEMU harness (`test/run_qemu_e2e.sh`): dual sparse block devices, `swtpm` emulation, and loopback SSH assertions
  - [x] Isolated GCE sandbox test harness (`test/provision_gce_sandbox.sh`, `test/gce_startup_test.sh`)
  - [x] Dynamic test runner and reporting pipeline (`bin/run_all_tests.py`, `generate_build_report.py`)
- [-] **In Progress & Planned Build Enhancements**
  - [-] **Multi-LTS Target Compilation Architecture:** Parameterize Docker builder and GCS cache prefixes to build both 22.04 Jammy and 26.04 Noble/Plucky targets
  - [ ] **GCS Cache Retention Sweeper:** Automated pruning of older ISO builds in `gs://gdc-disk-provisioner-isos/sync/` and `/archived/`
  - [ ] **Static Boot Banner:** Replace dynamic `generate_banner.py` execution with static `boot-banner.txt` template

---

### Stage 1: LiveCD & Baseline Installer (Subiquity / Partitioning)
*Ref: `GDC-SPEC-002` (Installer & Storage Layout), `GDC-SPEC-002-SEQ` (Timeline)*

- [x] **Autoinstall & Subiquity Execution**
  - [x] Unattended autoinstall target via GRUB: `ds=nocloud;s=/cdrom/nocloud/`
  - [x] Smart installation logging wrapper (`log_goal` and `log_fail`) with global bash error traps
  - [x] Offline APT source redirection to local Live ISO Nexus proxy (`http://127.0.0.1:8081/repository/gdc-apt-proxy/`) with `suites: [noble]`
  - [x] Guard logger against missing `/dev/log` syslog sockets in headless containerized environments
- [x] **Enterprise LVM & Storage Topology**
  - [x] Dynamic 1-or-2 disk auto-sizing generator (`generate_storage_config.sh`)
  - [x] Single-disk scaling algorithms: proportional partition scaling on drives $\ge 250\text{GB}$
  - [x] Dual-disk isolation: OS, etcd, containerd, Gitea, Nexus on Disk 1; heavy customer storage (`/customer/local-disk`, SDS) on Disk 2
  - [x] Dedicated logical volumes: `root`, `var`, `log`, `metrics`, `containerd`, `etcd`, `gitea`, `nexus`, `local_disk`, `sds`
  - [x] Physical boot partitions: `/boot/efi` (1 GiB, FAT32) and `/boot` (2 GiB, EXT4)
  - [x] Recursive superblock wiping on disks (`wipe: superblock-recursive`) and standard wiping on sub-LVs (`wipe: superblock`)
  - [x] Storage sanitization safety: Exclude USB flash drives and installer boot media from disk discovery and wiping
- [x] **Hardware & Platform Compatibility Fixes**
  - [x] **DRAM-Less NVMe HMB Panic Fix:** Demoted LUKS KDF from Argon2id to PBKDF2 (1000 iterations) to prevent Host Memory Buffer exhaustion on Kingston/AMD SSD arrays
  - [x] **AMD PSP/CCP Module Lockup Fix:** Programmed early-commands to probe for `AuthenticAMD` and physically unload (`rmmod`) `ccp`, `amd_sfh`, and `pcie_mp2_amd` prior to storage operations
  - [x] **LiveCD Ramdisk Expansion:** Scaled `ramdisk_size` from 4.5GB to 7.5GB to avoid PXE rootfs fragmentation loops
  - [x] **Target OS Framebuffer Scaling:** Enforced `video=efifb:1280x1024` in GRUB to prevent early systemd prompts from rendering off-screen
- [x] **Installer Migration & Transition Handshake**
  - [x] Subiquity `late-commands` rsync script migrating Gitea/Nexus data pools to persistent LVs (`lv_gitea`, `lv_nexus`)
  - [x] Deploy target systemd service units for persistent Gitea and Nexus daemons
  - [x] Deploy `bmctl` binaries from ISO `/custom-data/tools` into persistent `/var/gdc-install/tools`
  - [x] Dynamic SMBIOS telemetry injection (`bootcmd` queries UUID/MAC to parameterize reporting webhooks)
  - [x] Explicit Subiquity `phone_home` retry limit (`tries: 2`) preventing 23-minute hangs when Companion is offline
- [-] **In Progress & Planned Installer Tasks**
  - [ ] **GDC-SPEC-008: Non-LUKS Storage Provisioning:** Build flag `GDC_ENABLE_LUKS=false` to bypass LUKS on hardware lacking TPM/UEFI
  - [ ] **Installer Removal Execution Plan (`GDC-SPEC-009`):** Verification checklist for post-install cleanup

---

### Stage 2: First Boot (Identity & TPM 2.0 Sealing)
*Ref: `GDC-SPEC-002-SEQ` (Gaps), `GDC-SPEC-003` (Ready-Linux)*

- [x] **Boot Decryption & Service Initialization**
  - [x] Transition key decryption: `/target/boot/temp_key.key` configured in `/etc/crypttab` for one-time passwordless boot
  - [x] Systemd launches local persistent Gitea (port 3000) and Nexus (port 8081)
  - [x] Playbook wait-for-port handshakes on ports 3000 (60s timeout) and 8081 (90s timeout) to eliminate race conditions
- [x] **Self-Healing Provisioner Service (`gdc-provision.service`)**
  - [x] First-boot systemd runner executing `ansible-pull` against localhost Gitea
  - [x] Configured with `Restart=on-failure`, `RestartSec=20m`, `StartLimitIntervalSec=0`, and `-o pipefail`
  - [x] Environmental configuration file `/etc/default/gdc-provision` for flags and signed-commit toggles
  - [x] Persistent cron runner deployed for regular scheduled `ansible-pull` checking
- [x] **Hardware TPM 2.0 Cryptographic Sealing**
  - [x] Enrolls LUKS slot to hardware registers PCR `0+7` via `systemd-cryptenroll --tpm2-device=auto`
  - [x] Rewrites `/etc/crypttab` to `tpm2-device=auto,discard`
  - [x] Securely deletes temporary keyfile `/boot/temp_key.key` and wipes temporary password slot (`--wipe-slot=password`)
  - [x] Generates TPM-backed device identity certs via Step CA
  - [x] fTPM polling mode enforced (`tpm_tis.interrupts=0`) to bypass AMD fTPM ACPI interrupt bugs
- [x] **Administrative Identity & Access**
  - [x] Create administrative user `gdc-admin` and group `gdc-admin`
  - [x] Deploy passwordless sudo configuration `/etc/sudoers.d/gdc-admin`
  - [x] Inject authorized administrator SSH public keys
- [-] **In Progress & Planned First-Boot Tasks**
  - [-] **NodeAgent mTLS Certificate Pre-Seeding:** Automated injection of Server CA, Client CA, and Node Server Cert/Key for Zero-SSH bootstrapping
  - [-] **GPG Signed-Commit Enforcement:** Activate `--verify-commit` on `ansible-pull`
  - [ ] **SSH Host Key TPM Binding:** Secure host keys using `ssh-tpm-agent`
  - [ ] **mTLS Phone-Home Authentication:** Inject SSL client certificates to enable native mTLS on Subiquity `cc_phone_home`

---

### Stage 3: Second Boot (Auto-Unlock Verification)
*Ref: `GDC-SPEC-002-SEQ` (Phase 3), `GDC-SPEC-003` (Ready-Linux)*

- [x] **Headless Auto-Unlock & Ramdisk Verification**
  - [x] Verifies that target storage decrypted and mounted headless without interactive console intervention
  - [x] Native `dracut` compilation with `tpm2-tss` hooks and systemd cryptenroll
  - [x] Injected `rd.luks.uuid=` via `blkid` query into kernel command line to prevent emergency rescue shell drops
  - [x] `zz-gdc-blacklist` initramfs hook ensuring zero deadlocking AMD drivers are packaged into target initrds
  - [x] Five-point initrd validation in `late-commands` via `lsinitrd`
  - [x] Framebuffer geometry locked to prevent prompt clipping
- [x] **Rescue & Diagnostic Utilities**
  - [x] Created `bin/recover-tpm-unseal.sh` rescue utility to unlock LUKS via TPM and rebuild initramfs from LiveCD
  - [x] Created `bin/bootloader-crash-cart.sh` helper to generate root shells and bypass sshd restrictions
- [x] **State Initialization & Guards**
  - [x] State machine directory initialization (`/var/run/gdc-state/` or `/etc/gdc/state/`)
  - [x] Ansible guard rails: `MACHINE_STATE_STOP_STAGE` parameter to halt execution after specific boot stages
  - [x] Fail-safe telemetry generation on premature stage halts

---

### Stage 4: Linux Ready (System Hardening & Foundation)
*Ref: `GDC-SPEC-003` (Ready-Linux), `GDC-SPEC-DEP-001` (Dependencies)*

- [x] **Security Hardening & Auditing**
  - [x] CIS-CAT Assessor integration (`run_cis_benchmark.py` in `LINUX_READY`), parsing HTML/TXT and exporting facts
  - [x] Aggressive log capping: centralized `logrotate` (50MB/shard, 14-day cycle) and `systemd-journald` capped at 50MB
  - [x] High-security `auditd` rules (`/etc/audit/rules.d/99-gdc-audit.rules`) monitoring `/etc/passwd`, `/etc/sudoers`, `/etc/shadow`
  - [x] Route kernel flows to `/var/log/syslog`, `/var/log/secure`, `/var/log/cron`, `/var/log/boot.log` via `rsyslog`
  - [x] Purge unneeded attack surface: `snapd`, `lxd`, `x11-common`
  - [x] Defensive UFW handling: check service existence before stopping/masking
- [x] **System Foundation & Runtimes**
  - [x] Kernel sysctl tuning deployment
  - [x] UTC timezone enforcement and Chrony NTP server synchronization
  - [x] Container engines: offline installation of `docker-ce` daemon and `containerd` CRI (`hosts.toml`)
  - [x] Standalone Google Cloud SDK (gcloud CLI) installation with weekly automated cron update jobs
  - [x] Global gcloud authentication (`--installation` flag) via `/run/gdc-auth/access_token`
  - [x] Kubernetes swap disablement (`swap: {size: 0}` and fstab comment-outs)
  - [x] Purge `ubuntu-server` and `cloud-init` packages to eliminate circular package locks
  - [x] Disable Nexus proxy auto-blocking (`autoBlock: false`) to avoid lockouts during transient boot drops
- [-] **In Progress & Planned Hardening Tasks**
  - [-] **CIS Level 2 Complete Remediation:** Implement remaining Ansible roles for strict CIS Level 2 rules
  - [ ] **Kubernetes CIS Benchmarking:** Implement automated Kubernetes CIS auditing tasks
  - [ ] **GRUB Bootloader Password:** Configure `grub-mkpasswd-pbkdf2` outside of `GDC_DEBUG_MODE`
  - [ ] **Token Permissions Hardening:** Restrict `/run/gdc-auth/access_token` file permissions to `640`

---

### Stage 5: Cluster Ready (Network Isolation & Fleet Gating)
*Ref: `GDC-SPEC-005` (Cluster Turnup), `GDC-SPEC-007` (Companion)*

- [x] **Network Isolation & Architecture**
  - [x] Linux VRF routing isolation: bind Kubernetes VLAN interfaces (`vlan109`) to `vrf-k8s`
  - [x] Decouple hardcoded lab IP boundaries (replace `.9.x` with `192.168.4.x` fallbacks)
  - [x] Documented complete architecture setup diagram in `docs/LAB_SETUP.md`
  - [x] Dynamic L3 network checks auditing all 25 Google Cloud GDC endpoints
- [x] **Companion Integration & API Fallbacks**
  - [x] Decoupled GDC Companion architecture: Axum Rust stack with PostgreSQL/CNPG and mTLS Gateway API
  - [x] Fallback configuration payload generated at `/target/etc/gdc/fallback-config.json`
  - [x] Safe DHCP fallbacks across generic hostnames (`gdc-default`) when Companion API lookups fail
  - [x] Standardize stage completion facts to lowercase (`ready-linux`, `linux-ready`)
  - [x] Dynamic companion binary fetch: pull latest binary from GCS bucket into `PATH`
  - [x] Manual Fact Override & State Reset: upstream ingestion of `/var/gdc-install/state/gdc-fact-manual.json` bypassing Companion API, automated workstation operator script (`bin/node-ops/inject-manual-facts.sh`), and runbook in `docs/on-device-ansible.md`
- [x] **Cluster Pre-Flight Automation**
  - [x] Pre-Flight Lab Dependency Auditor (`check-lab-setup.py`): validates Step CA mTLS, GCP IAM, 19 mandatory GDC APIs, Bootimus, and VRFs
  - [x] Cluster creation script (`create_cluster.sh`) packaging and deployment to `/usr/local/bin/create_cluster.sh`
- [-] **In Progress & Planned Gating Tasks**
  - [ ] **P0 FIX: Netplan VRF Indentation Mapping Error** (`/etc/netplan/01-netcfg.yaml:18:8`)
  - [ ] **P0 FIX: mTLS Hostname CN Mismatch** (request certificate matching `machine_config.hostname`)
  - [ ] **P1 FIX: HTTP 301 Redirect Body Drop** (enforce HTTPS in `INSTALL_COMPANION_URL`)
  - [ ] **CMDB Identity Sync:** Dynamically assert and apply target hostnames from upstream machine database
  - [ ] **OIDC / Workload Identity Migration:** Migrate credentials refresh script to native OIDC identity tokens

---

### Stage 6: Cluster Up (Cluster Turnup & Workload Readiness)
*Ref: `GDC-SPEC-005` & `GDC-SPEC-005-TURNUP` (Turnup), `GDC-SPEC-009` (Sanitization)*

- [x] **Cluster Deployment Scripting**
  - [x] Idempotent `create_cluster.sh` script: ed25519 key generation, `bmctl` YAML hydration, fake GCR key generation for WIF, preflight checks, execution timer trap, and `ClusterRoleBinding` provisioning
- [-] **Standalone Offline Turnup Automation**
  - [x] Pre-seed GDC bootstrap credentials (`bmctl` and `nodeagent` integrated)
  - [ ] **Configuration Generation:** Automate creation of `cluster-config.yaml` defining target networks, VIPs, and storage paths
  - [ ] **Registry Mirror Redirection:** Redirect container registry mirror to local Nexus Group loopback Port 5001
  - [ ] **Hands-off Turnup Execution:** Fully orchestrate `bmctl create cluster` from within Ansible playbooks
  - [ ] **Version Alignment Guardrails:** Strictly assert Node Agent version matches target deployed `bmctl` release
- [-] **Security & NodeAgent Integration**
  - [ ] **Keyless Security Profile:** Enforce NodeAgent TPM-bound federation in place of static JSON service account keys
  - [ ] **NodeAgent Deployment:** Deploy offline GDC NodeAgent daemonset via `bmctl deploy nodeagent`
  - [ ] **Standalone mTLS Channel:** Configure NodeAgent secure mTLS gRPC channel over Port 9192
- [ ] **Multi-Node (3-Node HA) Coordination Plan**
  - [ ] Role designation: Node 1 Bootstrap Primary vs. Nodes 2/3 Secondary machines
  - [ ] Automated offline SSH trust & passwordless root SSH key distribution via Gitea
  - [ ] Secondary node image routing: redirect Nodes 2/3 container pulls to Node 1 on Port 5001
  - [ ] Inter-node reachability handshakes and pre-requisite package triggers (`socat`, `conntrack`)
- [ ] **Post-Turnup Target Sanitization (`GDC-SPEC-009`)**
  - [ ] Remove temporary installer account (`temporary-installer`) after cluster transitions to healthy state

---

### Day-2 Lifecycle: Offline Sideloading & Updates
*Ref: `GDC-SPEC-006` (Lifecycle Update Flows)*

- [x] **Headless USB Ingestion Engine**
  - [x] Headless automated USB updater via `udev` rules and systemd runner (`gdc-usb-updater.service`) detecting `GDC-UPDATE-USB`
  - [x] Cryptographic verification standards: GPG commit checks and OpenSSL SHA-256 update signatures
  - [x] Headless update execution loops (`gdc-headless-update.sh`)
- [-] **Tooling & API Ingest Pipelines**
  - [ ] **`gdc-update` CLI Tool:** Tooling to detect, mount, and pull USB bundles
  - [ ] **Git Bundle Sync:** Automated ingestion script for Git Bundles into Gitea
  - [ ] **Nexus API Upload Sync:** Automated scripts for APT debs, Docker image layers, and raw LLM weights
- [ ] **Update Pathways & Safety Gates**
  - [ ] **Pre-Update Local Cluster Backup:** Mandatory automated `bmctl backup cluster` pre-update verification gate
  - [ ] **Exit-Code Verification Trap:** Abort update sequence immediately on backup failure
  - [ ] **Physical Diagnostic Audio Signaling:** Motherboard buzzer indicators (1 long beep = success, 2 rapid loud beeps = failure/abort)
  - [ ] **Connected Tunnel Pathway:** Outbound-only WireGuard reverse VPN tunnel execution

---

## 4. Architectural Specifications Index (`docs/specs/`)

| Specification ID | Document Title | Primary Stage | Status |
| :--- | :--- | :--- | :--- |
| **GDC-SPEC-001** | ISO Generation & Build Pipeline (`01-iso-build-pipeline.md`) | `Stage 0: Build` | Approved / Implemented |
| **GDC-SPEC-002** | Baseline Installer & LVM Storage Layout (`02-baseline-installer.md`) | `Stage 1: LiveCD` | Approved / Implemented |
| **GDC-SPEC-002-SEQ** | Installation Sequence, Timeline & Transition Gaps (`02b-installer-sequence-and-timeline.md`) | `All Stages` | Approved / Implemented |
| **GDC-SPEC-003** | Ready-Linux Provisioning & Sideloading (`03-ready-linux-provisioning.md`) | `Stages 2–4` | Approved / Implemented |
| **GDC-SPEC-004** | ISO Verification & QEMU E2E Testing (`04-verification-and-testing.md`) | `Stage 0: Build` | Approved / Implemented |
| **GDC-SPEC-005** | Machine Database & Cloud Verification (`05-cluster-turnup.md`) | `Stage 5: Cluster Ready` | Approved / Implemented |
| **GDC-SPEC-005-TURNUP**| GDC Offline Cluster Turnup (`05-cluster-turnup.md`) | `Stage 6: Cluster Up` | Approved / In Progress |
| **GDC-SPEC-006** | GDC Lifecycle Update Flows (`06-lifecycle-update-flows.md`) | `Day-2 Lifecycle` | Approved / In Progress |
| **GDC-SPEC-007** | GDC Companion Design - Rust Stack (`07-gdc-companion-design.md`) | `Stage 5: Cluster Ready` | Decoupled / Implemented |
| **GDC-SPEC-008** | Non-LUKS Storage Provisioning Feature (`08-no-luks-feature-plan.md`) | `Stage 1: LiveCD` | Planned |
| **GDC-SPEC-009** | Temporary Installer Removal Plan (`09-temporary-installer-removal.md`) | `Stage 6: Cluster Up` | Planned |
| **GDC-SPEC-010** | GCloud Token Federation & ADC Bypass (`10-gcloud-token-federation.md`) | `Stage 4: Linux Ready` | Approved / Implemented |
| **GDC-SPEC-011** | PXE Netboot Optimization & Deduplication (`11-pxe-netboot-optimization-and-deduplication.md`) | `Stage 0: Build` | Approved / In Progress |
| **GDC-SPEC-DEP-001** | GDC Master Dependency Matrix | `All Stages` | Approved / Implemented |
| **GDC-SPEC-READY-LINUX**| GDC Ready-Linux & Idempotent Post-Install Plan | `Stages 2–4` | Approved / Implemented |
