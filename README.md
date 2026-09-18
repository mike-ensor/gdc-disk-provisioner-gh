# Google Distributed Cloud (GDC) Disk Provisioner & Bootloader ISO

The `gdc-disk-provisioner` provides the tooling, design specifications, and configurations required to build, provision, and maintain secure, **offline-first bootloader ISOs** for Google Distributed Cloud (GDC) bare-metal environments.

## Why this project exists
Bare-metal GDC environments often operate in strictly air-gapped or low-internet conditions. Provisioning physical servers in these environments traditionally requires manual intervention or complex PXE infrastructures that break down without internet access.

This project exists to solve this by implementing a **Hub-and-Spoke Sideloading Architecture**. It allows physical nodes to bootstrap, configure, secure themselves, and receive ongoing updates completely offline.

Key pillars of this architecture include:
*   **Hardware-Backed Security:** LUKS disk encryption, SSH host keys, and device identities are cryptographically bound directly to the physical hardware's TPM 2.0 chip.
*   **GDC Bare Metal Compliance:** Automates dynamic disk partitioning to implement the official enterprise LVM layout required by GDC out-of-the-box.
*   **Local Boundary Interfaces (Service Hubs):** Installs local instances of Gitea (for IaC/Ansible playbooks) and Sonatype Nexus (for containers, packages, and LLM caches) that act as the offline boundary endpoints for the target node.
*   **Autonomous Upkeep:** Once provisioned, nodes maintain themselves autonomously by periodically pulling configuration updates via `ansible-pull` from their local Gitea instance.

## :rotating_light: ALPHA STATE :rotating_light:

**NOTE: This project is in very early alpha state and should not be considered runable or usable at this current point in time.**

---

## The GDC Node State Machine

To coordinate node bootstrap across separate reboots and prevent premature cluster operations, each physical GDC node implements a strict 8-stage sequential state machine.

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
    Stage1["Stage 1: LiveCD\n(ISO & Subiquity)"]
    Stage2["Stage 2: First Boot\n(Services & TPM)"]
    Stage3["Stage 3: Second Boot\n(Unseal & Stability)"]
    Stage4["Stage 4: Linux Ready\n(OS Deps, CIS/Hardening)"]
    Stage5["Stage 5: Cluster Ready\n(Config & NodeAgent)"]
    Stage6["Stage 6: Cluster Turnup\n(bmctl creation)"]
    Stage7["Stage 7: Post Cluster\n(Validation)"]
    Stage8["Stage 8: Upkeep\n(Drift & Sideloads)"]

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

For detailed specifications and transition triggers for each stage, refer to the [AI-Readable State-Transition Matrix in docs/ARCHITECTURE.md](https://gitlab.com/gcp-solutions-public/retail-edge/gdc-disk-provisioner/-/blob/main/docs/ARCHITECTURE.md?ref_type=heads#412-ai-readable-state-transition-matrix).

### Stage Breakdown
*   **Stage 1: LiveCD (ISO & Unattended Install):** Server runs in RAM from the custom ISO. Subiquity partitions drives, formats filesystems, and synchronizes Gitea/Nexus assets to disks.
*   **Stage 2: First Boot (Services & TPM Sealing):** Node boots from target drive, temporarily unlocks LUKS, launches Gitea/Nexus, and seals LUKS encryption directly to the hardware TPM 2.0 chip.
*   **Stage 3: Second Boot (Auto-Unlock & Stability):** Controlled reboot verifies full, unattended LUKS auto-decryption using the TPM.
*   **Stage 4: Linux Ready (CIS Hardening):** Applies sysctl tuning, timezone sync, and CIS Level 2 security hardening.
*   **Stage 5: Cluster Ready (NodeAgent Gating):** Node queries GDC Companion for configs, templates `/etc/hosts`, and starts the `node-agent`.
*   **Stage 6: Cluster Turnup (Cluster Inception):** Initiates offline cluster creation (`bmctl create cluster`), pulling layers locally from the Nexus loopback.
*   **Stage 7: Post Cluster (Validation):** Runs post-install sanity tests (Storage Classes, CoreDNS, MetalLB).
*   **Stage 8: Upkeep (Drift Control):** Ongoing `ansible-pull` against local Gitea for drift correction, and headless USB sideload updates.

---

## Core Principles

*   **Private Mode as a First-Class Citizen:** `gdc-disk-provisioner` treats fully air-gapped ("Private Mode") operation as the primary baseline. Every feature must have a deterministic offline operation strategy.
*   **Evolutionary Architecture:** Strict separation of interfaces from underlying implementations. Installers and downstream providers can be swapped without breaking system boundaries.
*   **Operational Simplicity:** Built for massive scale edge deployments using declarative automation, eventual consistency (`ansible-pull`), and automated validation to ensure nodes autonomously converge on healthy states without human intervention.

---

## Architecture & Directory Structure

*   **`docs/specs/`**: Technical specification files describing architecture and configurations.
*   **`docs/DISKS.md`**: Breakdown of dynamic disk detection, partition scaling, and enterprise LVM layout.
*   **`docs/TPM_ATTESTATION_AND_MTLS.md`**: Detailed guide on Zero-Touch TPM 2.0 hardware attestation, EKCert verification, and mTLS integration with GDC Companion.
*   **`src/build/`**: **[Start Here for Building]** Contains the Cloud Build automation, Makefile, and scripts to compile the custom ISO. See [src/build/README.md](src/build/README.md) for build instructions.
*   **`src/ansible/`**: Declarative playbooks used by `ansible-pull` for node configuration and state progression.
*   **`test/`**: Verification scripts, VM-based bootstrap tests, and pre-flight validation.

---

## System Dependencies

* **Smallstep CA (`step-ca`):** The zero-touch hardware attestation workflow absolutely requires a centralized `step-ca` server to be reachable by the bare-metal nodes during *first boot*. Google Cloud CAS and Certbot are explicitly unsupported for TPM hardware attestation in this architecture. By default, the nodes will attempt to communicate with `https://step-ca.ensor-labs.com`. For complete details on the hardware attestation, EKCert verification, and mTLS lifecycle, see [`docs/TPM_ATTESTATION_AND_MTLS.md`](docs/TPM_ATTESTATION_AND_MTLS.md).
