# GEMINI: Agent Governance & Engineering Manual

This document provides strict architectural directives, coding conventions, and workflow rules for all AI agents and engineers contributing to the `gdc-disk-provisioner` project.

---

## 1. Architectural Directives

All implementations in this repository must align with the following core architectural tenets:

### Rule 1.1: Air-gapped Boundary Isolation
* **Directive:** Do not configure GDC system components (kubelet, containerd, apt, etc.) to fetch directly from external internet-facing mirrors.
* **Enforcement:** All package fetches and image downloads must go through the local **Service Hubs** (`localhost:3000` for Gitea, `localhost:8081` for Nexus). Proxy pass-thru is acceptable *only* as a fallback when an external connection is verified.

### Rule 1.2: Strict Performance & Isolation for GDC Storage
* **Directive:** Never group high-IOPS, low-latency filesystems with general OS partitions.
* **Enforcement:** The Logical Volumes (`lv_etcd`, `lv_etcd_events`, `lv_containerd`, and `lv_var_log`) must remain on separate logical block devices with dedicated EXT4 configurations to meet GDC preflight checks and protect the etcd leader election cycle.

### Rule 1.3: Hardware-Backed Cryptographic Bound
* **Directive:** All target machines must tie root encryption and device certificates to physical hardware.
* **Enforcement:** Remanded LUKS partitions must enroll PCR indices `0+2+7` on the TPM 2.0 chip using `systemd-cryptenroll`. SSH host keys and device administrative identities must be backed by the local TPM, with soft fallbacks only permitted for development test builds.

### Rule 1.4: Binary Integrity & Supply Chain Mitigation
* **Directive:** Standalone third-party binaries (such as Gitea, OpenJDK, and Nexus) baked into the ISO must have their supply chain integrity cryptographically verified.
* **Enforcement:** The build pipeline must define a hardcoded list of expected SHA-256 hashes. Every build must download/locate the binaries, compute their active hashes, and abort with a critical error if a mismatch is detected.

### Rule 1.5: Credential Leakage Prevention (MANDATORY)
* **Directive:** No static passwords, credentials, private API keys, or raw SSH private keys may be baked onto the ISO or stored inside playbooks.
* **Enforcement:**
  * Administrator and system service password hashes inside cloud-init/subiquity must be encrypted using salted SHA-512 rounds.
  * Node private SSH keys must be bound dynamically to the target TPM 2.0 chip during the provisioning stage instead of being pre-generated and stored statically.
  * A secret scanner pre-flight task must run prior to every ISO compilation to block builds containing raw credentials.

### Rule 1.6: Network Exposure Mitigation (MANDATORY)
* **Directive:** Gitea and Nexus services running on the Live ISO during the install phase must not expose administration ports (3000 and 8081) to the wider physical network.
* **Enforcement:**
  * Ephemeral services running on the Live ISO must bind strictly to the local loopback interface (`127.0.0.1`).
  * A verification test task must query local sockets (`ss -tulpn` or `netstat`) during headless boot tests to assert that ports 3000 and 8081 are isolated from external interfaces.

### Rule 1.7: Layered Asset Caching Strategy
* **Directive:** Large binary objects, caches, and weight files (such as Hugging Face LLM model weights) are prohibited from being compressed inside the core SquashFS or base ISO filesystem to avoid rebuild latency and deployment memory exhaustion.
* **Enforcement:**
  * The core ISO size is capped at 5 GB, containing only base system packages and service binaries.
  * Heavy caches must reside in a dedicated workspace directory on the physical USB drive labeled `GDC-SEED-CACHE`.
  * Gitea/Nexus startup layers must execute dynamic mounting loops to hook this storage directory into their local cache blobs upon boot.

---

## 2. Coding & Tooling Standards

### Rule 2.1: Bash Pipeline Remastering
* **Directive:** Do not introduce heavy virtual machine layers or Packer configurations to build the ISO.
* **Enforcement:** Build actions must reside in a unified `Makefile` using standard Linux remastering utilities (`xorriso`, `rsync`, `mksquashfs`, and `grub-mkrescue`). Remastering must be declarative, deterministic, and runnable within standard containerized build environments.

### Rule 2.2: Ansible Idempotency & Playbook Structure
* **Directive:** All playbooks run via `ansible-pull` must be strictly idempotent.
* **Enforcement:**
  * Avoid raw `shell` or `command` modules unless no specialized Ansible module exists. If utilized, a `register` combined with a `changed_when` or `failed_when` check is **mandatory**.
  * Keep the plays separated into structural roles: `gdc-users`, `gdc-tpm`, `gdc-services-persistent`, `gdc-hardening`, and `gdc-slimming`.

---

## 3. Directory Layout Rules

Keep files within these structured boundaries:
* **`docs/specs/`**: Structural designs and autoinstall configurations. Never add raw scripts here.
* **`src/ansible/`**: Base location for the `ansible-pull` roles and tasks.
* **`src/build/`**: Remastering scripts, grub templates, and Makefile configs.
* **`test/`**: Integration tests, QEMU/KVM virtual machine launch scripts for ISO verification.

---

## 4. Verification Workflow

Before declaring any change or feature "completed", agents must verify the following:
1. **Autoinstall Validation:** Run `cloud-init schema --config-file src/nocloud/user-data` to guarantee that Subiquity schemas are syntactically flawless.
2. **Ansible Linting:** Run `ansible-lint` against all playbooks in `src/ansible/`.
3. **Idempotency Test:** Verify that running the playbooks twice sequentially yields `changed=0` on the second run.
4. **Credential Leakage Test:** Scan the `src/` directory for raw keys or passwords before packing.
5. **Network Exposure Test:** During dynamic QEMU boot tests, execute remote checks to ensure ports 3000 and 8081 are strictly listening on local loopback `127.0.0.1`.
6. **Mandatory ISO Compilation Loop (Rule 4.6):** Whenever any change is made to the bootloader, cloud-init templates, partitioning scripts (`generate_storage_config.sh`), systemd units, or late commands, you **MUST** run the remastering compilation locally (`make -C src/build build`) and execute the static validator (`test/validate_iso_static.sh`). Under no circumstances may a task be marked complete without compiling and verifying the resulting ISO.
7. **Cloud Build Alignments:** To prevent GCS retrieval failures during Google Cloud Build pipelines, `SOURCE_ISO_FILENAME` inside `src/build/build.env` must always be kept as the unversioned name (`ubuntu-24.04-live-server-amd64.iso`) to match the blessed base image filename stored in the GCS bucket. For local downloads, point `SOURCE_ISO_URL` to the latest point-release (e.g. `ubuntu-24.04.4-live-server-amd64.iso`), which will download and save locally using the unversioned filename.
