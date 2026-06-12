# Project Terminology Dictionary

This dictionary defines key terms, concepts, and acronyms used throughout the `gdc-disk-provisioner` codebase, specifications, and workflows.

---

### Core Phases

#### 1. Baseline Phase

The initial bootstrap phase where a "blessed" (vetted, official) Ubuntu 24.04 LTS server ISO boots, automated disk LVM partitioning is established, a minimal Ubuntu OS is installed onto the target drive, and basic offline networking is configured. This is orchestrated entirely via `subiquity` and `cloud-init` (NoCloud).

#### 2. Ready-Linux Phase

The post-baseline configuration, provisioning, and hardening phase. It begins immediately on the first boot of the target OS and is orchestrated by a localized `ansible-pull` run. This phase creates the persistent administrative users, deploys persistent services (Gitea and Nexus), configures hardware cryptography (TPM 2.0 LUKS, SSH, and identity), and applies security hardening scripts.

#### 3. Cluster Turnup Phase

After `ready-linux`, this phase invovles reaching up to the **machine database** with the unique information to pull a set of desired state variables. Uing thse variables, this phase will create a GDC Software Only Standalone Edge-profile cluster. This phase will utilize `ansible-pull` to perform coordnation between one or three nodes (based on upstream configuration), `bmctl` and the rest of the setup to create a cluster. Upon completion a fully usable, registered cluter will be available.

---

### Architecture & Service Topologies

#### 1. Hub-and-Spoke Topology

The architectural model where the target GDC node hosts localized **Service Hubs** (Gitea and Nexus) that act as the single point-of-entry boundary for external code, binaries, or image updates. The node's inner components (CRI, Kubelet, OS package manager, LLM clients) act as the **Spokes** that fetch directly from these local Hubs.

#### 2. Gitea Hub

A persistent Go-based local Git repository manager installed on the target GDC node. It serves two purposes:

1. Runs ephemerally in RAM during the live installation boot to host the Ansible provisioning playbooks.
2. Runs persistently on the final target OS to receive updates and act as the git endpoint for `ansible-pull` cron cycles.

#### 3. Nexus Hub

A persistent Sonatype Nexus Repository Manager installed on the target GDC node. It serves as a local offline cache and registry for APT packages, Docker container images, and Hugging Face (raw files) LLM caches. It runs ephemerally in RAM during live installation and persistently on the target OS, supporting proxy pass-thru when internet is available, and serving strictly from cache when offline.

#### 4. Pull-based Configuration / Desired State Configuration

A set of centralized configuration representing the desired state of a configurable distinct layer of the system. Often these are "platform", "operating-system" and "applications". The configuration is peformed in a "reconcillation loop" consisting of "observe", "diff", and "reconcile" loop allowing a system to maintain a desired state until given a new state. Pull-based configuration means that each entity polls and pulls down the configuration in which to be come consistent with. Pull-based configuration is also known as "Desired State" configuration

---

### Provisioning & Storage

#### 1. Subiquity

The standard declarative server installer for Ubuntu. It reads installation parameters from an autoinstall YAML definition and automates the partitioning, operating system writing, and baseline network setup.

#### 2. NoCloud Provider

A metadata and configuration provider for `cloud-init` that allows offline bootstrapping. It loads configurations from local files placed in a virtual CD-ROM, USB, or filesystem partition labeled `CIDATA`.

#### 3. Enterprise LVM Partitioning

A GDC Bare Metal compliant Logical Volume Management configuration. It isolates system partitions (EFI, boot) from logical volumes (root, var, log, containerd, metrics, etcd, etcd-events) to prevent storage exhaustion and IOPS write-latency interference.

#### 4. SDS (Software-Defined Storage)

The storage subsystem (such as Portworx, Ceph, or a custom storage layer) that runs on top of the physical node. It consumes the remainder of the disk space via `/customer/sds` to provide distributed, replicated persistent volume storage for Kubernetes workloads.

#### 5. `local-disk` Provisioner

The GDC standalone static disk provisioner that allocates local host storage paths (mounted on `/customer/local-disk` and capped at 100 GiB) directly to Kubernetes persistent volume claims (PVCs).

---

### Sideloading & Security

#### 1. Sideloading

The process of transferring system patches, code changes, Docker images, or machine learning models into the air-gapped node entirely offline. This is accomplished either via API uploads from a tethered workstation or through a script-guided USB physical media sync.

#### 2. TPM 2.0 (Trusted Platform Module)

A dedicated, physical cryptographic microchip on the target server. In our architecture, it is used via `systemd-cryptenroll` to bind LUKS disk encryption (meaning the disk will only decrypt automatically if the server's firmware and BIOS boot parameters have not been tampered with), secure SSH private keys, and generate verifiable device identity certificates.
