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
