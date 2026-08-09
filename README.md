# Google Distributed Cloud (GDC) Disk Provisioner & Bootloader ISO

`gdc-disk-provisioner` contains the design, tooling, and configurations for building, provisioning, and maintaining secure, offline-first bootloader ISOs for Google Distributed Cloud (GDC) environments.

The project implements a **Hub-and-Spoke Sideloading Architecture** that enables nodes to bootstrap, configure, and receive updates completely offline in low-internet or air-gapped environments, while supporting proxy-pass-thru when internet connectivity is active.

## :alert: ALPHA STATE :alert:

NOTE: This project is in very early alpha state and should not be considered runable or usable at this current point in time.

---

## GDC Overarching Machine States State Machine

```mermaid
flowchart LR
    %% Define Google Brand Styles
    classDef start fill:#F1F3F4,stroke:#9AA0A6,stroke-width:2px,color:#202124;
    classDef blue fill:#4285F4,stroke:#1A73E8,stroke-width:2px,color:#FFFFFF;
    classDef red fill:#EA4335,stroke:#C5221F,stroke-width:2px,color:#FFFFFF;
    classDef yellow fill:#FBBC05,stroke:#F29900,stroke-width:2px,color:#202124;
    classDef green fill:#34A853,stroke:#137333,stroke-width:2px,color:#FFFFFF;
    classDef orange fill:#F57C00,stroke:#E65100,stroke-width:2px,color:#FFFFFF;

    %% Nodes
    Stage1["Phase 1: LiveCD\n(ISO & Subiquity)"]
    Stage2["Phase 2: First Boot\n(Services & TPM)"]
    Stage3["Phase 3: Second Boot\n(Unseal & Stability)"]
    Stage4["Phase 4: Linux Ready\n(CIS & Hardening)"]
    Stage5["Phase 5: Cluster Ready\n(Config & NodeAgent)"]
    Stage6["Phase 6: Cluster Turnup\n(bmctl creation)"]
    Stage7["Phase 7: Post Cluster\n(Validation)"]
    Stage8["Phase 8: Upkeep\n(Drift & Sideloads)"]

    %% Connections
    Stage1 --> Stage2
    Stage2 --> Stage3
    Stage3 --> Stage4
    Stage4 --> Stage5
    Stage5 --> Stage6
    Stage6 --> Stage7
    Stage7 --> Stage8

    %% Apply Styles
    class Stage1 blue;
    class Stage2 red;
    class Stage3 yellow;
    class Stage4 green;
    class Stage5 orange;
    class Stage6 blue;
    class Stage7 green;
    class Stage8 yellow;
```

---

## Hub-and-Spoke Sideloading & Proxy Pass-Thru Architecture

```mermaid
flowchart LR
    %% Define Google Brand Styles
    classDef gray fill:#F1F3F4,stroke:#9AA0A6,stroke-width:2px,color:#202124;
    classDef blue fill:#4285F4,stroke:#1A73E8,stroke-width:2px,color:#FFFFFF;
    classDef red fill:#EA4335,stroke:#C5221F,stroke-width:2px,color:#FFFFFF;
    classDef yellow fill:#FBBC05,stroke:#F29900,stroke-width:2px,color:#202124;
    classDef green fill:#34A853,stroke:#137333,stroke-width:2px,color:#FFFFFF;
    classDef orange fill:#F57C00,stroke:#E65100,stroke-width:2px,color:#FFFFFF;

    subgraph Machine["GDC Node (Host Machine)"]
        direction TB

        subgraph AppLayer["Application Layer (User space)"]
            Pods["Pods & User Apps"]:::green
        end

        subgraph K8sLayer["Orchestration Layer (Kubernetes)"]
            K8s["Cluster Control Plane / Kubelet"]:::orange
            NodeAgent["GDC NodeAgent DaemonSet"]:::orange
        end

        subgraph OSLayer["Operating System Layer (Host OS)"]
            HostOS["Host OS (Ubuntu 24.04)"]:::red
        end
    end

    subgraph LocalHub["Local Boundary Services"]
        direction TB
        Gitea["Gitea Mirror<br>(Git Configs & Playbooks)"]:::gray

        subgraph Nexus["Nexus Repository Manager"]
            direction TB
            NexusOCI["Container/OCI Proxy<br>(Port 5001)"]:::blue
            NexusAPT["APT/Debian Proxy<br>(Port 8081)"]:::red
            NexusLLM["LLM/Hugging Face Proxy<br>(Port 8081/raw)"]:::yellow
        end
    end

    subgraph Upstream["Upstream Source Registries (Internet / Intranet)"]
        direction TB
        UpstreamGit["Upstream Git Repo<br>(GCP Source Repo / GitHub)"]:::gray
        UpstreamOCI["Upstream Container Registries<br>(gcr.io, docker.io, etc.)"]:::blue
        UpstreamAPT["Upstream Debian Mirrors<br>(archive.ubuntu.com, apt.company.com)"]:::red
        UpstreamLLM["Upstream Model Sources<br>(Hugging Face, GCS)"]:::yellow
    end

    %% Connections within the Node/Machine to Local Hub
    HostOS -->|"Fetches apt updates"| NexusAPT
    K8s -->|"Pulls cluster components"| NexusOCI
    NodeAgent -->|"Pulls system images"| NexusOCI
    Pods -->|"Pulls container images"| NexusOCI
    Pods -->|"Loads LLM weights"| NexusLLM

    %% Local Hub to External Upstreams (Pass-thru / Proxy)
    Gitea -->|"Clones / Pulls / Forks"| UpstreamGit
    NexusOCI -->|"Proxies requests"| UpstreamOCI
    NexusAPT -->|"Proxies requests"| UpstreamAPT
    NexusLLM -->|"Proxies requests"| UpstreamLLM

    %% Apply Styles
    class Gitea gray;
    class NexusOCI blue;
    class NexusAPT red;
    class NexusLLM yellow;
    class Pods green;
    class K8s,NodeAgent orange;
    class HostOS red;
    class UpstreamGit gray;
    class UpstreamOCI blue;
    class UpstreamAPT red;
    class UpstreamLLM yellow;
```

---

### Enumeration of Overarching Machine States

To coordinate node bootstrap across separate reboots and prevent premature cluster sync operations, each physical GDC node implements a strict sequential state-machine pattern.

#### **Phase 1: LiveCD (ISO Build & Unattended Install)**
*   **Description:** Physical server runs in RAM from the read-only custom GDC Bootloader ISO. Subiquity handles drive partitioning (LVM logical volumes), formats filesystems, writes the base OS, and synchronizes Gitea/Nexus pre-seeded assets to target disks.
*   **Measurement:** Successful completion of the installation loop and a clean system reboot into the newly provisioned disk-based operating system.

#### **Phase 2: First Boot (Services Hubs Setup & TPM Sealing)**
*   **Description:** Node boots on physical target drive for the first time, unlocks LUKS using a temporary bootstrap key file, and launches Gitea and Sonatype Nexus services. The post-install Ansible playbook seals LUKS disk encryption directly to the hardware TPM 2.0 chip and erases the temporary key file.
*   **Measurement:** Ports `3000` (Gitea) and `8081` (Nexus) respond with `200 OK` on loopback, and `/var/gdc-install/state/first-boot.json` status is `"completed"`. A controlled reboot is triggered immediately.

#### **Phase 3: Second Boot (Auto-Unlock & Stability Verification)**
*   **Description:** The system executes a controlled reboot to verify full, unattended boot stability, ensuring LUKS auto-decrypts cleanly using systemd-cryptenroll / TPM 2.0 without manual passcodes or files.
*   **Measurement:** Successful boot to multi-user target with `/var/gdc-install/state/second-boot.json` written with status `"completed"`.

#### **Phase 4: Linux Ready (CIS Hardening & System Optimization)**
*   **Description:** Playbook applies system sysctl tuning, timezone synchronization, and CIS Level 2 security hardening, while purging unnecessary baseline system packages.
*   **Measurement:** Successful execution of standard `verify_ansible.sh` validation checks; file `/var/gdc-install/state/linux-ready.json` status is `"completed"`.

#### **Phase 5: Cluster Ready (Companion Configuration & NodeAgent Gating)**
*   **Description:** The node queries the GDC Companion API (`GET /v1/machine-info/{mac-address}`) using mTLS client certificates to fetch custom bootstrap configurations. It templates `/etc/hosts` with peer resolutions, stages `nodeagentd` binaries, authenticates `gcloud`, and activates (starts and enables) the `node-agent` systemd service.
*   **Measurement:** `bmctl` exists on `$PATH`, `gcloud` confirms valid credentials, all peers successfully ping, and `/var/gdc-install/state/cluster-ready.json` status is `"completed"`.

#### **Phase 6: Cluster Turnup (Local Standalone / HA Cluster Inception)**
*   **Description:** Initiates offline cluster creation via `bmctl create cluster`, pulling system OCI container layers locally from the loopback Nexus group repository (Port `5001`), and deploys GDC NodeAgent controllers.
*   **Measurement:** Admin kubeconfig exists at `/root/bmctl-workspace/gdc-edge-cluster/gdc-edge-cluster-kubeconfig` and control plane pods are marked `Ready` in Kubernetes.

#### **Phase 7: Post Cluster (Verification & Validation)**
*   **Description:** Runs post-install sanity tests (validating local Storage Classes, CoreDNS lookup, MetalLB route tables, and telemetry streams) to verify the cluster is healthy and operational.
*   **Measurement:** Ephemeral namespace deployment checks succeed, and `/var/gdc-install/state/post-validation.json` status is `"completed"`.

#### **Phase 8: Upkeep (Drift Control & Headless Updates)**
*   **Description:** Daily systemd timers trigger `ansible-pull` against Gitea for local configuration drift correction, and custom `udev` rules orchestrate headless USB sideload updates.
*   **Measurement:** Playbook execution finishes with `changed=0` (stable convergence).

---

## Core Project Goals

1. **Automated Baseline Installation:** Boot from a remastered Ubuntu 24.04 LTS ISO using `subiquity` and `cloud-init` (NoCloud) to establish standard networking and partition schemes without manual intervention.
2. **GDC Bare Metal Resource Compliance:** Dynamically implement the official GDC Bare Metal enterprise LVM layout, providing isolated partitions for log buffers, metrics collection, container image stores (`containerd`), and low-latency `etcd` transactions.
3. **Local Boundary Interfaces (Gitea & Nexus Hub):** Spin up Gitea and Nexus within the booting live environment to host Ansible playbooks, local APT repositories, private Docker registries, and Hugging Face/LLM caches. These services are persistently migrated onto the target OS during installation.
4. **Seamless Offline Sideloading:** Enable operators to sideload system updates, updated playbooks, updated Docker containers, and new LLM models completely offline via physical USB bundles or localized administrative API pushing.
5. **Hardware-Backed Security:** Bind LUKS disk encryption directly to the TPM 2.0 chip, store host SSH keys securely in the TPM, register TPM-based device identity certificates, and apply CIS Benchmark Level 1/2 hardening policies.

---

## Architecture & Directory Structure

This project is organized as a spec-driven engineering effort:

*   **`docs/specs/`**: Technical specification files describing the architecture, build workflows, and configurations.
    *   `01-iso-build-pipeline.md`: The Infrastructure-as-Code (IaC) pipeline to remaster the base ISO using a reproducible `Makefile` and `xorriso`.
    *   `02-baseline-installer.md`: The Subiquity Autoinstall configuration and GDC Bare Metal enterprise LVM partition map.
    *   `03-ready-linux-provisioning.md`: The first-boot transition, local Gitea/Nexus persistence setup, local `ansible-pull` automation, TPM 2.0 configuration, CIS hardening, and the offline update/sideloading mechanics.
*   **`docs/DISKS.md`**: Comprehensive breakdown of dynamic disk detection, single/dual-disk partitioning rules, enterprise LVM layout, and performance mount tunings.
*   **`src/`**: Declarative playbooks, custom update utilities, and scripts.
*   **`test/`**: Verification scripts, VM-based bootstrap tests, and pre-flight validation.

---

## Storage & Partition Map

The installation process automates the dynamic partitioning of physical block devices into GDC-compliant enterprise LVM structures. For details on dynamic disk scanning, 1-disk vs 2-disk partition scaling, preservation of raw SDS block storage, and performance mount options, refer to:

👉 **[docs/DISKS.md](docs/DISKS.md)**

---

## Offline Sideloading Workflows

Gitea and Nexus act as the local boundary endpoints for the target node. Operators can update the node entirely offline:

1.  **Code Updates (Gitea):** `git push` new playbooks directly to Gitea from a tethered administrator workstation, or insert a USB drive containing a `.bundle` update. Local cron tasks automatically trigger `ansible-pull` from the local Gitea repo.
2.  **Binary & Image Updates (Nexus):** Sideload new packages or containers using the Nexus HTTP API or a local `gdc-update` CLI tool directly from mounted USB drives.
3.  **LLM Model Syncs (Nexus Raw):** Sideload Hugging Face models directly to Nexus raw stores. Inference clients fetch locally offline by targeting `HF_ENDPOINT=http://localhost:8081/repository/gdc-llm-raw/`.
