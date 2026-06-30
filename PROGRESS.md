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
- [x] **GDC-SPEC-DEP-001: GDC Master Dependency Matrix** — Written & Approved
- [x] **Stage-Gate Software Supply Chain Design (`docs/specs/01-iso-build-pipeline.md`)** — Aligned & Approved
- [x] **Jinja2 Declarative Configuration Templating (`docs/specs/02-baseline-installer.md`)** — Aligned & Approved
- [x] **Port-forwarding Loopback Isolation & SSH Assertions (`docs/specs/04-verification-and-testing.md`)** — Aligned & Approved
- [x] **Decoupled Job-Release Orchestration Guide (`docs/DEVELOPMENT.md`)** — Aligned & Approved
- [x] **Governance Rules (`GEMINI.md`)** — Documented
- [x] **Domain Glossary (`DICTIONARY.md`)** — Documented
- [x] **Architecture User Guides (`docs/DISKS.md`, `docs/NETWORK.md`, `docs/SECURITY.md`, `docs/POST-INSTALL.md`)** — Documented & Aligned

---

## 2. Feature Checklist & Implementation Status

### Phase 1: ISO Generation (Build Pipeline)

- [x] **Workspace Scaffolding**
  - [x] Create `src/build/Makefile` for orchestration
  - [x] Create `src/build/remaster.sh` script for ISO manipulation
  - [x] Integrate GCP target configuration parameters (`PROJECT_ID` and `REGION` in `build.env`)
- [x] **Local Build Caching & Workspace Isolation**
  - [x] Formulate `.cache/` scoped local storage directories (isos, binaries, blobs)
  - [x] Scaffold `.cache/isos/` path for caching blessed OS sources
  - [x] Enforce git ignoring of `.cache/` and `build-workspace/` targets
- [x] **Offline Services Acquisition**
  - [x] Fetch and configure standalone Go-based Gitea binary
  - [x] Fetch and configure Java/JVM & Sonatype Nexus binary (capable of APT/deb, OCI/Docker registry, and Raw Hugging-Face GGUF caches)
- [ ] **Pre-seeding Asset Pipeline**
  - [x] Configure Gitea Playbook Mirror:
    - [x] Dynamically clone `UPSTREAM_PLAYBOOKS_REPO` at ISO creation time
    - [x] Inject read-only Git `pre-receive` hook to block direct local pushes
    - [ ] **FUTURE INVESTIGATION:** Research background sync scheduler/timer for pull-only updates on target OS
  - [ ] Configure Nexus Repository Group boundaries (merge Hosted & Proxy cache lines):
    - [ ] Establish OCI Docker Registry Group (Port 5001) for direct `docker push` + public pull-through cache
    - [ ] Establish APT Repository Group for local deb uploads + upstream cache proxies
    - [ ] Establish LLM Raw Group for local GGUF weight files + Hugging Face proxies
  - [ ] Pre-populate initial offline caches & packages into Gitea and Nexus blobs
- [x] **Live ISO systemd Integration**
  - [x] Configure Live environment `live-gitea.service` unit file
  - [x] Configure Live environment `live-nexus.service` unit file
  - [ ] Set up live OverlayFS mounting scripts for RAM-execution
- [x] **Remastering Compilations**
  - [x] Integrate boot loader GRUB configurations
  - [x] Compile finished hybrid ISO via `xorriso`

---

### Phase 2: Baseline Installer (Boot & Execute)

- [x] **Autoinstall Configurations**
  - [x] Design smart installation logging structures (`log_goal` and `log_fail`)
  - [x] Integrate automated error traps and exit-line captures inside partition scripts
  - [x] Create `/nocloud/user-data` autoinstall schema
  - [x] Configure DHCP networking settings
  - [x] Redirect autoinstall APT source to local live Nexus APT proxy
- [x] **Enterprise LVM Provisioning Automation**
  - [x] Formulate dynamic 1-or-2 disk auto-sizing script (`generate_storage_config.sh`)
  - [x] Optimize dual-disk setups (isolate etcd/OS to Disk 1; dedicate Disk 2 to SDS)
  - [x] Formulate single-disk scaling algorithms (scale Gitea, Nexus, and local-disk to fit 250GB)
  - [x] Define `/boot/efi` (1 GiB) and `/boot` (2 GiB) physical partitions
  - [x] Initialize Volume Group `vg_system`
  - [x] Allocate System Logical Volumes (`lv_root`, `lv_var`, `lv_var_log`, `lv_var_opt_metrics`)
  - [x] Allocate GDC Logical Volumes (`lv_containerd`, `lv_etcd`, `lv_etcd_events`)
  - [x] Allocate Service Logical Volumes (`lv_gitea`, `lv_nexus`)
  - [x] Allocate Customer Logical Volumes (`lv_local_disk` [100GiB max], `lv_sds` [remainder])
- [ ] **FUTURE INVESTIGATION: Linux VRF for Multi-IP Isolation**
  - [ ] Explore Linux VRF to support two IPs on a single physical interface (see `docs/future/linux-vrf.md`)
  - [ ] Complete full technical specification for VRF-based routing isolation
- [ ] **FUTURE INVESTIGATION: Installation Companion Webhook Receiver ("install-companion")**
  - [ ] Research/Design a secure, lightweight deployment companion app (running locally or in the cloud, pointed to in configuration via IP/DNS).
  - [ ] The companion will act as the native Subiquity webhook log recipient and translate/forward logs to GCP Cloud Logging.
  - [ ] Explore other potential installer helper hooks (e.g. dynamic state verification, network checks).
  - [ ] **FUTURE FEATURE:** Reach out to the "companion" API during build-time inside `remaster.sh` to dynamically retrieve target VLAN tags, subnets, and gateways.

---

### Phase 3: Ready-Linux Provisioning & Security Hardening

- [x] **First-Boot State Transition**
  - [x] Subiquity `late-commands` rsync script for Gitea/Nexus partition migrations
  - [x] Deploy target systemd service units for persistent Gitea and Nexus
- [x] **Ansible-Pull Bootstrap Automation**
  - [x] Create systemd `gdc-provision.service` to run `ansible-pull` on first boot
  - [x] Configure environmental signed-commits toggles (`/etc/default/gdc-provision`)
  - [x] Configure persistent Gitea & Nexus persistent service states in playbook
  - [x] Execute safe offline system-wide upgrades (`apt-get upgrade`) in playbook
  - [x] Implement loop package installations (`POST_INSTALL_PACKAGES` list) in playbook
  - [x] Configure cron cycles for persistent `ansible-pull` checking
- [ ] **Administrative Configurations**
  - [ ] Create `gdc-admin` user
  - [ ] Deploy passwordless sudo config
  - [ ] Inject passwordless SSH key pair
- [ ] **Hardware Security (TPM 2.0)**
  - [x] LUKS decryption enrollment using `systemd-cryptenroll` for PCR `0+2+7`
  - [x] Configure target `/etc/crypttab` with `tpm2-device=auto` and rebuild `initramfs` ramdisks
  - [x] Establish secure randomized Recovery Key and wipe insecure temporary passcode slot
  - [ ] SSH host key TPM-secure binding using `ssh-tpm-agent`
  - [x] Generate TPM-backed device identity certs via Step-CA (Remote Attestation, Quote & Cloud CSR verification)
  - [ ] **NodeAgent mTLS Certificate Pre-Seeding:** Address the generation and automated injection of unique Server CA, Client CA, and Node Server Cert/Key to enable 100% Zero-SSH bootstrapping.
- [ ] **CIS Hardening & Slimming**
  - [ ] Implement Ansible roles for CIS Level 2 benchmark rules
  - [ ] Implement Ansible tasks to purge unneeded packages (snapd, x11, etc.)

---

### Phase 4: GDC Bootstrapping (Local Dependency Integration)

- [x] **USB Sideload Integration**
  - [x] Design headless automated USB updater (`udev` rules & systemd triggers)
  - [x] Formulate cryptographic signature verification standards (GPG commit checks & Cosign OCI signatures)
  - [x] Script headless update execution loops (`gdc-headless-update.sh` with console audio beeps)
  - [ ] Create `gdc-update` CLI tool to detect, mount, and pull USB bundles
  - [ ] Write update sync script for Git Bundles to Gitea
- [ ] **API Upload Sync Pipelines**
  - [ ] Write Nexus API upload scripts for APT debs
  - [ ] Write Docker registry push wrapper scripts
  - [ ] Write LLM weights Raw upload sync tooling

---

### Phase 5: ISO Verification & Testing Framework

- [x] **Service Boundary Integration Testing**
  - [x] Create `test/verify_service_integration.sh` script
  - [x] Verify Gitea read-only push block (asserts pre-receive hook rejection)
  - [x] Verify Gitea local fetch/pull capabilities
  - [x] Verify Nexus OCI proxy routing query schemas (via `TEST_PULL_OCI_IMAGE` variable)
- [x] **First-Boot Self-Test Playbook (local.yml)**
  - [x] Create `test/verify_ansible.sh` playbook testing harness
  - [x] Implement Tier 1 Syntax validation and Tier 2 local dry-run check-mode checks
  - [x] Service Port readiness checks (Gitea 3000, Nexus 8081)
  - [x] Execution verification (Hello World task)
  - [x] Partition block querying task (lsblk)
  - [x] Outbound gateway ping test task (ping 8.8.8.8)
- [x] **Static Verification (Tier 1)**
  - [x] Create `test/validate_iso_static.sh` script
  - [x] Integrate cloud-init schema and YAML syntax verification
  - [x] Integrate dynamic sandboxed Netplan verification (`netplan generate`) into the pre-flight validator
- [x] **Isolated Cloud Sandbox Testing (GCE)**
  - [x] Create `test/gce_startup_test.sh` first-boot startup script
  - [x] Create `test/provision_gce_sandbox.sh` lifecycle orchestrator
  - [x] Program local port socket-mocks for Gitea/Nexus during playbook validation
  - [x] Automate GCE serial log polling and mandatory cloud VM teardown
- [x] **Headless E2E Boot Testing (Tier 2)**
  - [x] Create `test/run_qemu_e2e.sh` script
  - [x] Implement dual-disk sparse block device allocations (250G and 350G SSD targets)
  - [x] Script serial log console monitoring with automated polling and timeout boundaries
  - [x] Implement software TPM emulator (`swtpm`) isolated socket mapping via `mktemp`
  - [x] Implement remote port-forwarding SSH assertion suite and Bootimus PXE automated local integration (`src/build/bootimus.py`)

---

### Phase 6: Cluster Turnup (Cluster Creation)

- [ ] **Offline Cluster Deployment**
  - [ ] Seed GDC bootstrap workstation credentials
  - [ ] Create bmctl configuration file defining target cluster IP networks and VIPs
  - [ ] Execute `bmctl create cluster` offline using pre-seeded container layers in local Nexus group registry

---

### UNPLANNED
- [ ] **APT** configuration
  - [ ] https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#apt
  - [ ] https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#fallback
- [ ] **Ubuntu Pro** config - https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#ubuntu-pro
- [ ] **Error handling during install**
  - [ ] https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#error-commands
  
