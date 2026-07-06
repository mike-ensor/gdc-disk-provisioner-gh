# GDC Node Provisioner - Architecture & Sequence Specification

This document details the complete end-to-end lifecycle of the Google Distributed Cloud (GDC) Bare Metal Node Provisioner pipeline. It outlines the sequence of transitions from initial variable configuration up to automated PXE-driven operating system installation, local Gitea hosting, and daily drift-correction execution via systemd timers.

---

## 1. End-to-End Sequence Diagram

The provisioning sequence is divided into four distinct stages:
1. **Stage 1 (ISO Creation):** Code and environment variables are compiled into a bootable, self-contained ISO containing pre-seeded Ansible playbooks, dependent collections, and local repositories.
2. **Stage 2 (Publish & Deploy):** The compiled ISO is uploaded to versioned Google Cloud Storage (GCS) or a local corporate NFS mount.
3. **Stage 3 (PXE Ingestion):** Bootimus (the PXE engine) pulls the ISO and configures local iPXE menus.
4. **Stage 4 (Bare-Metal Provisioning):** The physical node boots, performs a dynamic DHCP discovery install, transitions to local static VRF networking, and starts daily drift-correction.

```mermaid
sequenceDiagram
    autonumber
    
    box rgb(33, 37, 41) Stage 1: Build & Package (ISO Creation)
        actor Dev as Platform Engineer
        participant Env as build.env
        participant Eng as remaster.sh (ISO Engine)
        participant Git as GitLab Remote
        participant Gal as Ansible Galaxy API
    end

    box rgb(24, 43, 73) Stage 2: Publish & Deploy
        participant Pub as buildAll.sh
        participant GCS as Cloud Storage / NFS
    end

    box rgb(18, 53, 36) Stage 3: PXE Ingestion (Bootimus)
        participant Boot as Bootimus PXE Server
    end

    box rgb(64, 43, 11) Stage 4: Bare-Metal Provision (Node Boot)
        participant Node as Physical Node
        participant Comp as install_companion.py
    end

    %% --- STAGE 1 ---
    Dev->>Env: Define IP, VLAN, DNS, UPSTREAM_PLAYBOOKS_REPO, & ANSIBLE_PULL_SCHEDULE
    Dev->>Eng: Execute 'make build'
    activate Eng
    Eng->>Eng: Check cached Ubuntu 24.04 Base ISO
    Eng->>Git: Clone UPSTREAM_PLAYBOOKS_REPO as bare repo
    Git-->>Eng: Save into /custom-data/gitea/.../bootstrap-playbooks.git
    Eng->>Gal: Fetch community.general collection
    Gal-->>Eng: Extract into /custom-data/ansible/collections
    Eng->>Eng: Inject systemd timers & gdc-provision.service
    Eng->>Eng: Compile Custom Bootable ISO (xorriso)
    Eng-->>Dev: Output gdc-bootstrap-ubuntu-24.04-v0.0.7.iso
    deactivate Eng

    %% --- STAGE 2 ---
    Dev->>Pub: Run './buildAll.sh'
    activate Pub
    Pub->>GCS: Push versioned ISO to GCS Bucket / NFS Mount
    deactivate Pub

    %% --- STAGE 3 ---
    Boot->>GCS: Pull latest compiled GDC Bootstrap ISO
    Boot->>Boot: Extract kernel & initramfs (vmlinuz/initrd)
    Boot->>Boot: Register PXE/iPXE menu entry (Grub config with ds=nocloud)

    %% --- STAGE 4 ---
    Node->>Boot: Turn on -> DHCP -> PXE Boot request
    Boot-->>Node: Stream kernel, initrd, and boot parameters
    Node->>Node: Boot Live OS (Stage 1: Dynamic DHCP)
    Node->>Comp: Stream installation status/log payloads via webhook
    Node->>Node: Partition disks (LVM lv_gitea, lv_nexus, etc.)
    Node->>Node: Sync pre-seeded Gitea, Nexus, & Ansible collections
    Node->>Node: Deploy & Enable gdc-provision.timer
    Node->>Node: Reboot into Hardened OS
    
    Note over Node,Comp: Stage 2: Static VRF Active
    Node->>Node: systemd starts gitea.service (Port 3000)
    Node->>Node: gdc-provision.service runs local ansible-pull
    Node->>Node: Daily at 2AM, gdc-provision.timer triggers drift correction
```

---

## 2. Key Architecture Principles

### 100% Offline-First (Local Gitea Hosting)
At ISO build time, our custom scripting clones the target Ansible playbooks repository as a read-only Git mirror and bakes it into Gitea's persistent data directories inside the ISO (`/custom-data/gitea/`). When the node boots into production, Gitea automatically launches and serves this exact bare Git repository locally on port `3000` via loopback. This ensures `ansible-pull` runs purely from local loopback with zero external network dependencies.

### Dual-Mode Sonatype Nexus Proxy (Local Package Mirrors)
On the **First Initial Boot** of the target machine, a local instance of Sonatype Nexus is automatically spun up on port `8081` to act as the local APT registry (`gdc-apt-proxy`):
*   **Connected Mode (Developer Labs & Connected Testing):** If the node has external internet connectivity, Nexus operates as an on-demand caching proxy. If a requested package is missing from the local cache, Nexus fetches it from public Ubuntu mirrors, caches it in its persistent local blob store, and serves it to the node's package manager.
*   **Air-Gapped Mode (Isolated GDC Production Targets):** In fully isolated production networks with no internet routing, Nexus operates completely offline. Because our remastering pipeline (`remaster.sh`) pre-populates and bundles every required system package (such as `ansible`, `git`, `python3`, and all of their python/system dependencies) directly into the offline GDC ISO during compilation, all required packages are guaranteed to already reside inside the local Nexus cache. If an un-cached package is requested, Nexus gracefully returns a `404/504` error instead of hanging on infinite timeouts, guaranteeing deterministic, 100% offline installation success.

### Transition of Overarching States
The GDC deployment enforces a clean separation between two states:
* **Live ISO State:** The target node runs in RAM from the read-only custom bootloader ISO. Gitea and Nexus are inactive. Subiquity partitions the disks, formats LVM volumes, writes the base OS, and syncs pre-seeded service assets to `/target` before rebooting.
* **First Initial Boot State:** The node reboots into the physical SSD, starts persistent Gitea and Nexus services, and launches `gdc-provision.service`. This service waits for local Nexus to initialize, automatically bootstraps the `ansible` and `git` packages completely offline, and runs local `ansible-pull` playbooks to enroll the TPM 2.0 cryptobindings and finalize the node.

### Transition of Network Stages
* **Bootstrap Phase (Stage 1):** The Subiquity installer boots with native DHCP to establish a reliable connection to the `install-companion` log monitoring webhook.
* **Production Phase (Stage 2):** On the first reboot of the completed installation, systemd activates the segmented VRF (Virtual Routing and Forwarding) tables, mapping `Table 10` for "Machine" management interfaces and `Table 20` for "Kubernetes" container network interfaces natively or over tagged VLAN boundaries.

### Automated Drift Management
To prevent runtime configuration skew, the installer registers and starts a standard `gdc-provision.timer` systemd unit. Daily at the specified schedule (configured via `ANSIBLE_PULL_SCHEDULE`), this timer triggers `ansible-pull` to query the local Gitea instance and align the physical server with the declared git-state.

### CI/CD Pipeline & Base ISO Caching
* **Cloud Build Integration:** The entire ISO remastering and compilation process is fully automated and runs within a **Google Cloud Build** CI/CD pipeline.
* **Base ISO GCS Caching:** To prevent unnecessary external network requests and guarantee high-speed, deterministic compilation, the "blessed" official Ubuntu 24.04 LTS Base ISO is cached inside a secure Google Cloud Storage (GCS) bucket. The Cloud Build pipeline fetches this cached base ISO directly from GCS into the workspace prior to starting the `remaster.sh` execution.
