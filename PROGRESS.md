# Project Progress & Feature Tracker

This document tracks the ongoing implementation and delivery of the GDC Offline Bootloader ISO process. It acts as an active checklist compared to our technical specification files (`docs/specs/`).

---

## 1. Specification Stage (Docs & Architecture)
* [x] **GDC-SPEC-001: ISO Generation & Build Pipeline** — Written & Approved
* [x] **GDC-SPEC-002: Baseline Installer & LVM Storage Layout** — Written & Approved
* [x] **GDC-SPEC-003: Ready-Linux Provisioning & Sideloading** — Written & Approved
* [x] **GDC-SPEC-004: ISO Verification & QEMU E2E Testing** — Written & Approved
* [x] **Governance Rules (`GEMINI.md`)** — Documented
* [x] **Domain Glossary (`DICTIONARY.md`)** — Documented

---

## 2. Feature Checklist & Implementation Status

### Phase 1: ISO Generation (Build Pipeline)
* [x] **Workspace Scaffolding**
  * [x] Create `src/build/Makefile` for orchestration
  * [x] Create `src/build/remaster.sh` script for ISO manipulation
* [ ] **Offline Services Acquisition**
  * [ ] Fetch standalone Go-based Gitea binary
  * [ ] Fetch Java/JVM & Sonatype Nexus binary
* [ ] **Pre-seeding Asset Pipeline**
  * [ ] Populate Gitea bare repository with core Ansible playbooks
  * [ ] Pre-populate Nexus APT repo storage with baseline debs
  * [ ] Pre-populate Nexus Docker registry storage with core container images
  * [ ] Pre-populate Nexus Raw storage with LLM Hugging Face safetensors
* [ ] **Live ISO systemd Integration**
  * [ ] Configure Live environment `live-gitea.service` unit file
  * [ ] Configure Live environment `live-nexus.service` unit file
  * [ ] Set up live OverlayFS mounting scripts for RAM-execution
* [x] **Remastering Compilations**
  * [x] Integrate boot loader GRUB configurations
  * [x] Compile finished hybrid ISO via `xorriso`

---

### Phase 2: Baseline Installer (Boot & Execute)
* [ ] **Autoinstall Configurations**
  * [ ] Create `/nocloud/user-data` autoinstall schema
  * [ ] Configure DHCP networking settings
  * [ ] Redirect autoinstall APT source to local live Nexus APT proxy
* [ ] **Enterprise LVM Provisioning Automation**
  * [ ] Define `/boot/efi` (1 GiB) and `/boot` (2 GiB) physical partitions
  * [ ] Initialize Volume Group `vg_system`
  * [ ] Allocate System Logical Volumes (`lv_root`, `lv_var`, `lv_var_log`, `lv_var_opt_metrics`)
  * [ ] Allocate GDC Logical Volumes (`lv_containerd`, `lv_etcd`, `lv_etcd_events`)
  * [ ] Allocate Service Logical Volumes (`lv_gitea`, `lv_nexus`)
  * [ ] Allocate Customer Logical Volumes (`lv_local_disk` [100GiB max], `lv_sds` [remainder])

---

### Phase 3: Ready-Linux Provisioning & Security Hardening
* [ ] **First-Boot State Transition**
  * [ ] Subiquity `late-commands` rsync script for Gitea/Nexus partition migrations
  * [ ] Deploy target systemd service units for persistent Gitea and Nexus
* [ ] **Ansible-Pull Bootstrap Automation**
  * [ ] Create systemd `gdc-provision.service` to run `ansible-pull` on first boot
  * [ ] Configure cron cycles for persistent `ansible-pull` checking
* [ ] **Administrative Configurations**
  * [ ] Create `gdc-admin` user
  * [ ] Deploy passwordless sudo config
  * [ ] Inject passwordless SSH key pair
* [ ] **Hardware Security (TPM 2.0)**
  * [ ] LUKS decryption enrollment using `systemd-cryptenroll` for PCR `0+2+7`
  * [ ] SSH host key TPM-secure binding using `ssh-tpm-agent`
  * [ ] Generate TPM-backed device identity certs via step-ca
* [ ] **CIS Hardening & Slimming**
  * [ ] Implement Ansible roles for CIS Level 2 benchmark rules
  * [ ] Implement Ansible tasks to purge unneeded packages (snapd, x11, etc.)

---

### Phase 4: Sideloading & Maintenance Interfaces
* [ ] **USB Sideload Integration**
  * [ ] Create `gdc-update` CLI tool to detect, mount, and pull USB bundles
  * [ ] Write update sync script for Git Bundles to Gitea
* [ ] **API Upload Sync Pipelines**
  * [ ] Write Nexus API upload scripts for APT debs
  * [ ] Write Docker registry push wrapper scripts
  * [ ] Write LLM weights Raw upload sync tooling

---

### Phase 5: ISO Verification & Testing Framework
* [x] **First-Boot Self-Test Playbook (local.yml)**
  * [x] Service Port readiness checks (Gitea 3000, Nexus 8081)
  * [x] Execution verification (Hello World task)
  * [x] Partition block querying task (lsblk)
  * [x] Outbound gateway ping test task (ping 8.8.8.8)
* [x] **Static Verification (Tier 1)**
  * [x] Create `test/validate_iso_static.sh` script
  * [x] Integrate cloud-init schema and YAML syntax verification
* [x] **Headless E2E Boot Testing (Tier 2)**
  * [x] Create `test/run_qemu_e2e.sh` script
  * [x] Implement sparse 400G virtual disk allocation schema
  * [x] Script serial log console monitoring with automated polling and timeout boundaries
  * [ ] Implement software TPM emulator (`swtpm`) local port bindings
  * [ ] Implement remote port-forwarding SSH assertion suite
