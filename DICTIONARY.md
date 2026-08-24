# Project Terminology Dictionary

This dictionary defines key terms, concepts, and acronyms used throughout the `gdc-disk-provisioner` codebase, specifications, and workflows.

---

### Core Stages

The GDC Node lifecycle is orchestrated across distinct system stages, ensuring deterministic progression from bare-metal RAM to a fully clustered state.

#### 1. Stage 1: LiveCD
The initial bootstrap stage where a "blessed" (vetted, official) Ubuntu 24.04 LTS server ISO boots, automated disk LVM partitioning is established, a minimal Ubuntu OS is installed onto the target drive, and basic offline networking is configured. This is orchestrated entirely via `subiquity` and `cloud-init` (NoCloud). In this ephemeral state, the machine runs entirely in-memory from the read-only custom bootloader ISO (backed by a RAM `tmpfs` / `overlayfs`).

#### 2. Stage 2: First Boot
The initial boot cycle of the newly written operating system on the physical target drive after rebooting from the Live ISO. This state is characterized by unlocking the LUKS storage with a temporary boot-unlock key, starting persistent local services (Gitea and Nexus), and running local `ansible-pull` playbooks to enroll the physical TPM 2.0 chip and finalize the node into an immutable, secure state.

#### 3. Stage 3-5: Ready-Linux (SecondBoot to ClusterReady)
The post-baseline configuration, provisioning, and hardening phase. Orchestrated by localized `ansible-pull` runs, this creates persistent administrative users, enforces CIS hardening scripts, verifies auto-unsealing stability, and gates the execution of the node-agent until all configurations are verified.

#### 4. Stage 6-8: Cluster Turnup & Upkeep (ClusterTurnup to UpdateUpkeep)
This final lifecycle span involves reaching up to the machine database for configurations to create a GDC Software Only Standalone Edge-profile cluster. It uses `ansible-pull` and `bmctl` to perform cluster inception. Upon completion, a fully usable cluster enters the automated Upkeep stage, receiving daily drift correction.

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

#### 5. Docker Group Repository

An OCI registry pattern in Sonatype Nexus that aggregates multiple repositories under a single unified endpoint URL to simplify container image retrieval:

- **Hosted Repository:** A read-write repository (e.g., `docker-internal`) used for manually pushing or sideloading custom and pre-downloaded OCI container images.
- **Proxy Repository:** A read-only cache repository (e.g., `docker-upstream`) that lazily fetches and caches images from public/upstream registries (like `gcr.io` or `docker.io`).
- **Unified Workflow:** Container runtimes (CRI/Kubelet) pull exclusively from the single Group Repository URL. Nexus automatically resolves requests by checking the Hosted repository first for sideloaded images, falling back to the Proxy repository to fetch and cache from upstream when online.

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

#### 2. Customer-added Packages

Dependencies to be applied to the Operating System via the ISO on initial boot. Often packages are added from a Tarball during ISO creation or USB side-loading.

#### 3. TPM 2.0 (Trusted Platform Module)

A dedicated, physical cryptographic microchip on the target server. In our architecture, it is used via `systemd-cryptenroll` to bind LUKS disk encryption (meaning the disk will only decrypt automatically if the server's firmware and BIOS boot parameters have not been tampered with), secure SSH private keys, and generate verifiable device identity certificates.

---

### Network & Isolation

#### 1. Default Interface (Host Interface / Machine Interface)

The default physical interface that the network is using. It carries the primary host-level management traffic, DNS resolution, and standard outbound connectivity on the node.

#### 2. Kubernetes Interface

The network interface/sub-interface that Kubernetes uses to define the Control Plane, Node IPs, VIPs, and MetalLB CIDR ranges, isolating container orchestration traffic from standard machine administration.

---

### Machine States & Connectivity Modes

#### 1. Connected Mode

Indicates a node with full outbound public internet connectivity. It can directly pass-thru local proxies to pull updates, packages, and container layers from public upstream registries and repositories.

#### 2. Private Mode Normal (or Private Mode)

Indicates an air-gapped node operating offline/locally. It has automated update and upgrade processes configured identically to Connected mode, with the key difference being that it retrieves assets strictly from local Gitea and Sonatype Nexus mirrors/proxies, and will fail if those local repositories are not pre-seeded or updated.

#### 3. Private Mode Strict

Indicates a high-security machine that is exclusively off the internet. It does not attempt any automated update, upgrade, or synchronization processes. All maintenance, patching, and configuration updates must be executed purely as manual, operator-triggered efforts.

---

### Diagnostics & Recovery

#### 1. Crashed Provision

A term used to identify that a remote system has tried to run the ISO self-installer, and there was a failure before a fully provisioned system during **Baseline Phase**. A system in this state will not have the default user (`gdc-installer`) or password. **IF** the ISO is a `DEBUG` build, then the `root` user with `gdc-password-123` should be available to use. If the ISO is **NOT** `DEBUG`, then we need to use the "Crash Cart" `bin/bootloader-crash-cart.sh` script, which will be run on the target system.

#### 2. Crash Cart

```shell
bin/bootloader-crash-cart.sh
```

A script that is run on a remote machine that is in "Crashed Provision" state. The script is intended to be run from within the crashed shell. The script enables SSH, temporarily sets up a root password, and enables root to use SSH. Scripts or Agent/LLM tools can then be used to extract the failure reason. This script will enable `ssh` and setting `root` password and enabling root as an SSH user.

#### 3. Network Scan

Finding a "Crashed Provision" system on the network requires Network Console or subnet scanning (L2). `bin/crash-cart-scan-subnet.sh` script can be used to run a scan to identify possible machines in the subnet. Since DHCP is used in **Baseline Phase**, the range is dependent on the networking configuration. A list of IPs can be provided to automatically skip (not record) to avoid unnecssary identification of successful or non-GDC nodes.

---

### GDC Bootstrap Installation Gates

The standardized sequence of internal gates executed during the automated GDC bare-metal LiveCD installation and post-install bootstrap. Each gate acts as a blocking barrier with specific entry/exit qualifications to prevent temporal race conditions.

#### 1. Gate 1: Hardware Bus Settling & Enumeration (`HARDWARE_SETTLING`)
The gate that waits for physical system hardware buses (PCI, USB, storage controllers, TPM) and device nodes to fully initialize and register in `/dev/` and `/sys/`.

#### 2. Gate 2: Disk Sanitization & Interface Purge (`DISK_SANITIZATION`)
The gate where the primary installation block device is cleaned of all residual partitions, signatures, filesystems, logical volumes, and LUKS encryption mappings from any previous installations.

#### 3. Gate 3: Cross-Namespace Integrity Verification (`NAMESPACE_SYNC`)
The gate that performs file-system read/write synchronization loops between the container/snap mount namespace and the host overlayfs namespace to ensure no propagation latencies block keyfiles.

#### 4. Gate 4: Storage Structure & Partitioning (`STORAGE_LAYOUT`)
The gate where the physical partitions are created, the LUKS2 secure cryptographic container is formatted and mapped, and the LVM volume group and all 11 required logical volumes are allocated.

#### 5. Gate 5: OS Payload Injection & Bootloader Stage (`OS_PAYLOAD`)
The gate that writes the baseline operating system filesystem payload, mounts system paths under `/target`, and installs and configures the UEFI GRUB bootloader.

#### 6. Gate 6: First-Boot Security Sealing & Key Sanitization (`TPM_SEALING`)
The first-boot gate where the physical node's fTPM/dTPM chip is initialized and enrolled to seal the LUKS encryption key to PCR values 0+7, and any temporary bootstrap keyfiles are permanently wiped and deleted from disk.

#### 7. Gate 7: Local Boundary Hubs & Playbook Execution (`BOUNDARY_HUB_TURNUP`)
The final bootstrap gate where the local isolated Gitea and Sonatype Nexus services are verified as healthy, and `ansible-pull` is executed locally to apply system post-install configurations.
