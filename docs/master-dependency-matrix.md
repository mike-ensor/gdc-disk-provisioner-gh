# Specification: GDC Master Dependency Matrix

**Spec Identifier:** `GDC-SPEC-DEP-001`  
**Status:** APPROVED  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Overview & Objectives
This document consolidates and defines all dependencies, binaries, libraries, operating system packages, and cached data assets that are added, updated, or utilized during each of the five distinct phases of the Google Distributed Cloud (GDC) node bootstrapping lifecycle. 

It serves as a single source of truth for build-time dependencies, offline pre-seeded packages, and runtime security libraries.

---

## 2. Stage-by-Stage Dependency Matrix

```text
[ Blessed OS ISO ] ──> STAGE 1: IaC BUILD ───────────> Add xorriso, rsync, Gitea & Nexus Bins
                            │
                            ▼
                       STAGE 2: BOOT & INSTALL ──────> Add Subiquity, cryptsetup, LVM2, Git, Ansible
                            │
                            ▼
                       STAGE 3: PROVISIONING ────────> Add tpm2-tools, systemd-cryptenroll, step-cli, auditd
                            │
                            ▼
                       STAGE 4: BOOTSTRAPPING ───────> Start Gitea, Nexus Groups, Cosign, udev triggers
                            │
                            ▼
                       STAGE 5: CLUSTER TURNUP ──────> Add bmctl, containerd, docker, GDC OCI images
```

---

## 3. Detailed Phase Dependencies

### 3.1. Stage 1: ISO Generation & Build (Build-Time Host)
Executed on the builder workstation or CI/CD runner. It assemblies the remastered offline ISO.

*   **Host Operating System:** Any standard Linux system (Ubuntu 22.04/24.04 LTS) or unprivileged Docker compilation container.
*   **Host Tool Dependencies:**
    *   `xorriso` (v1.5.6+): Performs non-root ISO extraction and bootable hybrid ISO compilation.
    *   `rsync` (v3.2.7+): Handles fast, incremental file copies and layout structuring.
    *   `curl` or `wget`: Fetches upstream official ISOs and Gitea/Nexus binaries.
    *   `git` (v2.43.0+): Clones the playbook repositories during build-time.
*   **Downloaded & Cached Assets (Saved in `.cache/`):**
    *   `ubuntu-24.04-live-server-amd64.iso`: The "blessed" baseline operating system.
    *   `gitea` (v1.22.0+, Go-based): Standalone Gitea Go binary.
    *   `nexus` (v3.68.0+): Standalone Sonatype Nexus Repository Manager package.
    *   `openjdk-17-jre-headless`: Standalone Java JVM required by Nexus.
    *   `bootstrap-playbooks.git`: Bare mirror of GDC playbooks cloned from `UPSTREAM_PLAYBOOKS_REPO`.

---

### 3.2. Stage 2: Baseline OS & LVM Setup (Boot/Installer-Time)
Executed in the RAM-disk environment of the booting Live GDC ISO, and during the baseline OS write.

*   **Live-Boot RAM OS Packages (Natively in Casper):**
    *   `subiquity` (v24.04.1+): Natively executes unattended autoinstall partitioning.
    *   `cloud-init` (v24.1.1+): Reads `NoCloud` virtual drive configuration metadata.
    *   `cryptsetup` (v2.7.0+): Formats and maps the LUKS encrypted physical partition.
    *   `lvm2` (v2.03.16+): Initializes LVM `vg_system` and formats logical blocks.
*   **Target OS Packages Pre-Installed (Pulled from local Live-ISO Nexus proxy):**
    *   These packages are specified inside `src/build/build.env` under `POST_INSTALL_PACKAGES` and pre-seeded inside the ISO:
    *   `ansible` (v2.16.3+): Includes Ansible Core and the local `ansible-pull` engine.
    *   `git` (v2.43.0+): Required by `ansible-pull` to pull playbooks from Gitea.
    *   `python3-pip` (v24.0+): Python package installer for Ansible module dependencies.
    *   `wireguard` (v1.0.20210914+): Secure networking kernel module for GDC tunnels.

---

### 3.3. Stage 3: Ready-Linux Provisioning (First-Boot Target OS)
Executed locally on the target server's first boot, orchestrated by the Ansible playbook `local.yml`.

*   **TPM 2.0 Security & Cryptography Packages:**
    *   `tpm2-tools` (v5.6+): Command line utilities to interface with the physical TPM 2.0 chip (`tpm2_quote`, `tpm2_getekcertificate`).
    *   `libtss2-tcti-device` (v4.0.1+): Low-level TPM driver communication libraries.
    *   `systemd-cryptenroll` (v255+): Native systemd utility used to seal LUKS keys to TPM PCR `0+7`.
    *   `ssh-tpm-agent` (v0.5.1+): Hardware-backed TPM SSH host-key agent.
    *   `step-cli` (v0.24.4+): Step CA utility to enroll device identity certs via TPM CSRs.
*   **Hardening & Slimming Packages:**
    *   `auditd` & `audispd-plugins` (v3.1.2+): System audit logging for CIS Level 2 rules.
    *   `snapd`, `unattended-upgrades`, `x11-common`: Purged and deleted from system.
*   **System Upgrades:**
    *   All system-installed deb packages are upgraded (`apt-get upgrade`) completely offline utilizing the local Nexus APT group proxy.

---

### 3.4. Stage 4: GDC Bootstrapping (Local Dependency Integration)
Running continuously on the hardened GDC node to act as the offline boundary interfaces.

*   **Boundary Service Hubs:**
    *   `gitea` (v1.22.0+): Persistent Go daemon managed by systemd, listening on port `3000`.
    *   `nexus` (v3.68.0+): Persistent Java JRE daemon managed by systemd, listening on port `8081`. Exposes the OCI registry group on port `5001`.
*   **Sideload & Update Verification Tools:**
    *   `cosign` (v2.2.0+): Sigstore Cosign utility used to verify OCI container image signatures offline.
    *   `udev` (v255+): Custom rule `/etc/udev/rules.d/99-gdc-usb-update.rules` mapping GDC update media.
    *   `gdc-headless-update.sh`: Playbook sync and REST API sideload coordinator.
    *   `beep` / PC Speaker kernel module: Emits motherboard status signals.

---

### 3.5. Stage 5: Cluster Turnup (Cluster Creation)
The final turnup phase executed on the bootstrapped hardware node.

*   **Cluster Orchestration Software:**
    *   `bmctl` (v1.29.0+): Google Distributed Cloud Bare Metal deployment and control CLI.
    *   `kubectl` (v1.29.0+): Kubernetes cluster controller.
*   **Container Runtimes:**
    *   `containerd` (v1.7.12+): High-performance container runtime engine.
    *   `docker-ce` (v25.0.3+): Standalone container engine for workstation operations.
*   **OCI Container Images (Seeded in local Nexus Group OCI Registry):**
    *   Google Kubernetes Engine (GKE) system images.
    *   MetalLB Load Balancer images.
    *   CSI Host-Path and dynamic LVM Disk Provisioner images.
