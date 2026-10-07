# Project Terminology Dictionary

This dictionary defines key terms, concepts, acronyms, and architectural patterns used throughout the `gdc-disk-provisioner` codebase, specifications, and operational workflows.

---

## 1. Core Provisioning Lifecycle Stages

The GDC bare-metal node lifecycle progresses through discrete, deterministic stages from build-time packaging to an active Kubernetes cluster (`docs/specs/02b-installer-sequence-and-timeline.md`).

### Stage 0: Build & Remaster
The build-time compilation phase orchestrated by `src/build/Makefile` and Google Cloud Build (`cloudbuild.yaml`). A "blessed" (vetted, official) upstream Ubuntu 24.04 LTS server ISO is unpacked, hydrated with declarative Jinja2 templates, pre-seeded with offline package caches (Gitea and Nexus binaries, APT packages, container layers), and repacked into a bootable hybrid ISO via non-root `xorriso`.

### Stage 1: LiveCD (Baseline Installer)
The initial in-memory bootstrapping stage where the physical server boots headlessly from the ISO (via iPXE/Bootimus or USB) with the kernel parameter `autoinstall ds=nocloud;s=/cdrom/nocloud/`. The operating system executes entirely in RAM from Casper `overlayfs`. Subiquity performs hardware discovery, executes dynamic LVM auto-partitioning (`generate_storage_config.sh`), formats DM-Crypt LUKS containers, writes the base Ubuntu 24.04 OS image into `lv_root`, and migrates offline caches to persistent disk partitions before initiating a hardware restart.

### Stage 2: First Boot (Identity & Sealing)
The initial boot of the freshly installed operating system on the physical target drive. The kernel decrypts the LUKS storage using an ephemeral one-time transition keyfile (`/boot/temp_key.key`), systemd launches persistent local Gitea (port 3000) and Nexus (port 8081) daemons, and `gdc-provision.service` executes `ansible-pull`. Ansible enrolls the physical motherboard TPM 2.0 chip via `systemd-cryptenroll` bound to PCR registers `0+7`, purges the temporary keyfile and password slots, creates administrative credentials, and triggers a reboot.

### Stage 3: Second Boot (Auto-Unlock Verification)
The verification boot verifying that the storage volume decrypts automatically and headlessly via the physical TPM 2.0 chip without passwords or console prompts. It asserts the presence of Dracut kernel line UUID mappings (`rd.luks.uuid=`) and confirms that blacklisted drivers (`ccp`, `amd_sfh`) were not packaged into target ramdisks.

### Stage 4: Linux Ready (System Hardening & Foundation)
The host configuration and hardening phase executed via `ansible-pull`. The node executes offline CIS-CAT Assessor auditing (`run_cis_benchmark.py`), establishes aggressive `logrotate` and `systemd-journald` 50MB disk caps, enforces `auditd` kernel file-integrity rules, purges unneeded packages (`snapd`, `lxd`, `x11-common`), configures Chrony NTP kernel synchronization, tunes kernel sysctl parameters, installs Docker/containerd runtimes, and configures standalone Google Cloud SDK utilities.

### Stage 5: Cluster Ready (Fleet Gating & Preflights)
The pre-cluster orchestration phase. The node initializes Linux VRF (`vrf-k8s`) to isolate cluster VLAN interfaces (`vlan109`) from management traffic, queries the GDC Companion API over mTLS for machine metadata (or loads `/etc/gdc/fallback-config.json`), deploys `/usr/local/bin/create_cluster.sh`, configures global gcloud authentication tokens, and verifies network reachability to all peer nodes and required Google Cloud endpoints.

### Stage 6: Cluster Up / Cluster Turnup
The final inception stage where the standalone or high-availability (3-node) GDC Kubernetes cluster is deployed. The node executes `bmctl create cluster` completely offline against local Nexus container registry mirrors on port `5001`, deploys the GDC NodeAgent daemonset, binds keyless authentication profiles, and purges temporary installer accounts.

### Day-2 Lifecycle & Upkeep
The ongoing post-installation operational phase. Nodes maintain desired configuration states through recurring `ansible-pull` cron cycles, ingest offline updates from cryptographically signed USB drives (`GDC-UPDATE-USB`), execute automated pre-update cluster backups (`bmctl backup cluster`), and signal operational status via physical console audio indicators.

---

## 2. Architecture & Service Topologies

### Hub-and-Spoke Topology
The architectural model where each target GDC node hosts localized **Service Hubs** (Gitea and Sonatype Nexus) that serve as the single point-of-entry boundary for external code, packages, binaries, and container images. Internal node consumers (CRI, Kubelet, APT package manager, Google Cloud SDK, LLM runtimes) act as **Spokes** that fetch directly from these local loopback hubs (`127.0.0.1`), ensuring 100% air-gapped survivability.

### Gitea Hub
A persistent Go-based local Git repository manager operating on localhost port `3000`. It serves two functions:
1. Operates on the target OS to host local Ansible provisioning playbooks and cluster configuration templates for `ansible-pull`.
2. Receives offline Git bundle updates during Day-2 sideloading operations with read-only Git `pre-receive` hooks preventing unauthorized pushes.

### Nexus Hub
A local Sonatype Nexus Repository Manager operating on localhost port `8081`. It serves as an offline registry and cache for Debian APT packages, Docker/OCI container image layers, and Raw files (such as Hugging Face GGUF LLM weights and gcloud tool archives). It runs persistently on the target OS, serving cached assets when offline and proxying through to upstream registries when external connectivity is available.

### Docker Group Repository
An OCI registry design pattern in Sonatype Nexus (exposed on loopback port `5001`) that aggregates multiple repositories under a single unified endpoint URL:
* **Hosted Repository (`docker-internal`):** A read-write repository used for sideloading pre-seeded container images.
* **Proxy Repository (`docker-upstream`):** A read-only caching repository that pulls and caches layers from public registries (`gcr.io`, `docker.io`).
* **Unified Workflow:** Container runtimes (CRI-O, containerd, Kubelet) pull strictly from `localhost:5001`. Nexus checks the hosted repository first, falling back to upstream proxy caching when connected.

### Pull-Based Desired State Configuration
A continuous configuration pattern executed by `ansible-pull`. Instead of a centralized push controller holding SSH credentials to thousands of edge machines, each GDC node periodically polls its local Gitea repository on a systemd timer, evaluates local state differences ("observe", "diff"), and applies playbooks to maintain desired state ("reconcile").

### Outer SquashFS Strategy
A remastering optimization pattern. Rather than unpacking and modifying the heavy base Ubuntu `filesystem.squashfs` (which incurs expensive multi-minute repacking times), the base SquashFS is left pristine and untouched. Custom binaries, Gitea repositories, and Nexus package blobs are placed in the uncompressed outer ISO directory (`/custom-data/`), reducing ISO compilation cycles to sub-10-second repacks.

---

## 3. Security, Identity & Cryptography

### TPM 2.0 (Trusted Platform Module)
A physical cryptographic microprocessor integrated into server motherboards. In this architecture, TPM 2.0 is used via `systemd-cryptenroll` to bind LUKS storage encryption to firmware registers PCR `0+7`, store hardware-bound SSH keys (`ssh-tpm-agent`), and generate non-exportable private keys for device identity certificates.

### Transition Key (`temp_key.key`)
An ephemeral random cryptographic keyfile generated during Subiquity `late-commands` and stored at `/target/boot/temp_key.key` (permissions `400`). It is registered in a free LUKS keyslot and configured in `/etc/crypttab` to allow a passwordless first reboot before the host operating system has initialized its TPM drivers. Once the First Boot playbook successfully binds the TPM, `/boot/temp_key.key` is permanently deleted and its keyslot is wiped.

### `systemd-cryptenroll`
A native systemd utility used during First Boot to enroll hardware security tokens into LUKS2 volume headers:
```bash
systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=0+7 /dev/nvme0n1p3
```
It binds disk decryption to PCR 0 (Core System Firmware) and PCR 7 (Secure Boot state), then wipes insecure installation passcodes via `--wipe-slot=password`.

### Keyless Profile & Token Federation
An authentication architecture (`GDC-SPEC-010`) that eliminates the need to store long-lived Google Cloud Service Account (GSA) JSON keys on physical edge disks. During cluster turnup, the node authenticates to the GDC Companion via mTLS. The Companion impersonates the node's assigned GSA via the GCP IAM Credentials API (`generateAccessToken`) and mints a short-lived OAuth 2.0 access token (valid for 1 hour), which is written to `/run/gdc-auth/access_token` and consumed globally by `gcloud`.

### Mutual TLS (mTLS)
A bidirectional cryptographic authentication protocol where both the client (edge node) and server (GDC Companion) authenticate each other's X.509 certificates. The node presents an identity certificate issued by Step CA with a Common Name (CN) matching its registered hostname or primary MAC address.

### Step CA
An automated internal Certificate Authority infrastructure that manages X.509 certificates for edge nodes. It validates host CSRs during bootstrap, issues device identity certificates, and enables Zero-Trust mTLS communication with centralized fleet management gateways.

### Sigstore / Cosign
A container signing and verification framework. Container images cached in or sideloaded to the local Nexus Docker registry (port 5001) are cryptographically validated against GDC public keys prior to admission into the Kubernetes runtime, preventing execution of tampered container layers.

### GPG Signed-Commit Enforcement
A supply-chain verification control enabled via `ENFORCE_SIGNED_COMMITS=true`. When active, `ansible-pull` executes with `--verify-commit`, instructing Git to verify GPG signatures on playbook commits against an authorized keyring in `/etc/gpg/gdc-release.gpg` before executing code.

### CIS-CAT Assessor
The Center for Internet Security Configuration Assessment Tool. Integrated into `LINUX_READY` via `run_cis_benchmark.py`, it executes automated audit assessments against Ubuntu 24.04 CIS Level 2 benchmarks and exports compliance scores as structured Ansible facts.

---

## 4. Hardware & Platform Compatibility

### HMB (Host Memory Buffer) Starvation Fix
A critical hardware mitigation for DRAM-less NVMe SSDs (such as Kingston arrays on AMD architectures). Ubuntu 24.04's default LUKS format uses the `argon2id` Key Derivation Function (KDF), requiring ~1GB of RAM. On DRAM-less drives relying on system RAM for controller cache (Host Memory Buffer), this causes buffer starvation, driving the AMD cryptographic coprocessor (`ccp`) into an unrecoverable kernel panic. The installer demotes the KDF to `pbkdf2` (1000 iterations), preventing HMB exhaustion.

### AMD PSP / CCP Bus Contention
A hardware race condition on AMD Zen 4 platforms where the AMD Cryptographic Coprocessor (`ccp`), AMD Sensor Fusion Hub (`amd_sfh`), and PCIe MP2 drivers collide with firmware TPM communications on the Platform Security Processor (PSP) bus during disk partitioning. The installer blacklists these drivers in GRUB (`modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp`) and dynamically runs `rmmod` during LiveCD `early-commands` prior to storage manipulation.

### fTPM Polling Mode
A kernel command-line configuration (`tpm_tis.interrupts=0`) enforced across GRUB templates. It forces the TPM driver to use polling mode rather than hardware ACPI interrupts, eliminating deadlocks caused by firmware TPM interrupt bugs on AMD platforms.

### Target OS Framebuffer Scaling
A GRUB display parameter (`video=efifb:1280x1024`) that forces a standard 16:9 1280p VGA geometry, preventing early-boot systemd interactive prompts and console panic messages from rendering off-screen on physical console crash carts.

---

## 5. Storage & Enterprise LVM

### Enterprise LVM Partitioning
A GDC Bare Metal compliant storage partitioning standard. It isolates system partitions (EFI, boot) from 9 to 11 dedicated Logical Volumes inside an encrypted Volume Group (`vg_system`), preventing single-filesystem saturation from impacting Kubernetes operations:
* `/` (`lv_root`): 40 GiB — Base operating system.
* `/var` (`lv_var`): 20 GiB — Kubelet states and runtime data.
* `/var/log` (`lv_var_log`): 100 GiB — Fluent-bit, journald, and system log isolation.
* `/var/opt/buffered-metrics` (`lv_var_opt_metrics`): 10 GiB — GDC telemetry metrics buffer.
* `/var/lib/containerd` (`lv_containerd`): 30 GiB — CRI runtime container storage (XFS with `prjquota`).
* `/var/lib/etcd` (`lv_etcd`): 20 GiB — etcd consensus database (`commit=1` mount optimization).
* `/var/lib/etcd-events` (`lv_etcd_events`): 5 GiB — etcd events database (`commit=1`).
* `/var/lib/gitea` (`lv_gitea`): 15–20 GiB — Local Gitea repository storage.
* `/var/lib/nexus` (`lv_nexus`): 300 GiB (single-disk) or remainder (dual-disk) — Local Nexus caching registries and blob stores.

### Single-Disk Topology
The automated storage layout deployed on servers with exactly one NVMe/SSD ($\ge 560\text{ GiB}$ / $600\text{ GB+}$). Accommodates the full standard LVM allocations (including 100 GiB logs and 300 GiB Nexus), assigning all remaining capacity to `/customer/sds`.

### Dual/Multi-Disk Topology
The high-performance storage layout deployed on servers with two or more NVMe/SSDs ($\ge 560\text{ GiB}$ / $600\text{ GB+}$). It enforces physical workload isolation across separate physical block devices:
* **Disk 1 (System Disk - `vg_system`):** Hosts OS, etcd, containerd, Gitea, and Nexus. `lv_nexus` expands to consume all remaining space on Disk 1.
* **Disk 2 (Data Disk - `vg_data`):** Dedicated entirely to customer container volumes: `/customer/local-disk` (100 GiB) and `/customer/sds` (remainder of Disk 2). Write-intensive customer storage cannot cause I/O starvation on Disk 1 etcd consensus logs.

### Pristine Block Preservation
The architectural requirement where any physical drives beyond Disk 2 (e.g., Disks 3 and 4 in 4-bay servers) are completely ignored during installation. They are left raw without partition tables, LVM signatures, or filesystems, allowing Kubernetes Software-Defined Storage (SDS) controllers to detect and format them dynamically post-turnup.

### SDS (Software-Defined Storage)
The distributed, replicated storage subsystem (such as Portworx, Ceph/Rook, or GDC local-volume-provisioner) that runs on top of bare-metal nodes, consuming `/customer/sds` or pristine raw block drives to provide persistent volumes for containerized workloads.

### `local-disk` Provisioner
The GDC standalone static disk provisioner that allocates local host storage paths mounted on `/customer/local-disk` (capped at 100 GiB) directly to Kubernetes Persistent Volume Claims (PVCs).

### Recursive Superblock Wiping
The storage cleaning method executed during automated re-installations. `wipe: superblock-recursive` is applied to physical disks to scrub stale LUKS, LVM, and partition headers, while `wipe: superblock` is used on sub-logical volumes to prevent Curtin from colliding with udev asynchronous probing (`NotExclusiveError`).

---

## 6. Networking & Routing Isolation

### Linux VRF (`vrf-k8s`)
A Virtual Routing and Forwarding domain implemented in the Linux kernel (mapped to Routing Table `20`). It isolates Kubernetes cluster VLAN interfaces (`vlan109`) into a private routing table with dedicated gateways and DNS servers, completely separating Kubernetes container and etcd traffic from standard host management.

### Split-Plane Networking
The architectural model separating network traffic into two independent routing planes:
1. **Host/Management Plane (`main` routing table):** Carries host-level management, outbound telemetry webhooks, SSH, and GCS synchronization over untagged IPv4 DHCP.
2. **Cluster Data Plane (`vrf-k8s` routing table `20`):** Carries Kubernetes Control Plane, Node IPs, VIPs, etcd consensus, and pod traffic over tagged VLAN 109.

### Default Interface (Host Interface / Machine Interface)
The primary physical network interface (e.g., `enp1s0`) operating on untagged native ports. It uses standard IPv4 DHCP in the default `main` routing table for external reachability and diagnostic telemetry.

### Kubernetes Interface (Cluster Interface)
The dedicated VLAN sub-interface (e.g., `enp1s0.109`) bound to `vrf-k8s`. It operates with a static IP allocation (e.g., `192.168.109.x/24`) to handle internal cluster traffic.

---

## 7. Management, Orchestration & Fleet Tooling

### Bootimus
The central automated PXE boot server and REST API engine. It manages iPXE boot menus, performs asynchronous ISO kernel/initrd extraction, and enforces non-interactive autoinstall parameters (`autoinstall ds=nocloud-net`) while locking image configurations in its database.

### GDC Companion (`gdc-companion`)
A decoupled, high-security REST microservice written in Rust (Axum + SQLx + Serde) and backed by PostgreSQL with CloudNativePG (CNPG) operator control. Exposed via the Kubernetes Gateway API over mTLS, it manages hardware enrollment, dynamic variable deep-merging across hierarchical scopes (Global $\rightarrow$ Fleet $\rightarrow$ Machine), token federation for `gcloud`, and live installation telemetry logging.

### `bmctl` (Bare Metal Control)
The official Google Distributed Cloud CLI tool. Used on edge nodes to generate cluster configuration files, execute preflight verification gates (`bmctl check preflight`), create standalone or high-availability clusters (`bmctl create cluster`), and perform cluster backups.

### NodeAgent (`nodeagent`)
A specialized GDC system daemon deployed to bare-metal nodes. It communicates with Anthos/GDC control plane controllers, applies node configurations, and exposes secure mTLS gRPC services on port `9192`.

### `gdc-provision.service`
The first-boot systemd one-shot service that launches `ansible-pull` against the local Gitea repository. It features self-healing restart parameters (`Restart=on-failure`, `RestartSec=20m`, `StartLimitIntervalSec=0`) and `-o pipefail` execution wrappers to ensure nodes autonomously retry provisioning indefinitely upon transient network drops.

### `create_cluster.sh`
An idempotent bash automation script deployed to `/usr/local/bin/create_cluster.sh` during `CLUSTER_READY`. It automates ed25519 SSH key generation, hydrates `bmctl` YAML definitions, generates a fake GCR JSON key to satisfy Workload Identity Federation constraints, executes preflight gates, and configures cluster-admin `ClusterRoleBinding` permissions.

---

## 8. Connectivity Modes & Machine States

### Connected Mode
Operational mode for nodes with full outbound public internet access. Local Nexus hubs act as lazy-pull caching proxies to public package and image registries (`gcr.io`, `docker.io`, `archive.ubuntu.com`).

### Private Mode (Normal)
Operational mode for air-gapped nodes operating without internet access. All system updates, container layers, and playbooks are resolved strictly against pre-seeded or sideloaded local Gitea and Nexus caches.

### Private Mode (Strict)
High-security operational mode for completely isolated nodes where all automated synchronization, background polling, and scheduled drift-correction timers are disabled. Node updates occur exclusively through manual, script-guided operator execution.

---

## 9. Diagnostics, Recovery & Crash Cart

### Crashed Provision
A failure state occurring when the automated Subiquity installer or early first-boot Ansible playbook crashes before provisioning administrative users (`gdc-admin`). In non-debug releases, the node is inaccessible via standard credentials.

### Crash Cart CLI (`bootloader-crash-cart.sh`)
An emergency recovery utility provided via `bin/local/gdc-crash-cart.sh snippet`. When executed from a crashed installation shell or serial console, it temporarily starts `ssh`, configures `/etc/ssh/sshd_config.d/99-root-ssh.conf` to permit root logins, and sets an ephemeral password so diagnostic logs can be extracted remotely.

### TPM Recovery Utility (`recover-tpm-unseal.sh`)
A diagnostic script located at `bin/recover-tpm-unseal.sh`. Designed to be executed from a LiveCD on a bricked node, it unseals the LUKS partition using the motherboard's TPM, mounts `/` and `/boot`, chroots into the environment, installs missing drivers, and rebuilds initramfs with systemd TPM2 TSS hooks.

### Pre-Flight Lab Dependency Auditor (`check-lab-setup.py`)
An automated Python verification tool that audits the local network and cloud environment before booting bare-metal nodes. It asserts Step CA mTLS certificates, Google Cloud IAM permissions, 19 mandatory GDC APIs, Bootimus PXE endpoints, and VRF subnet parameters.

### Node Diagnostics Collector (`collect-node-diagnostics.sh`)
An object-oriented diagnostic test runner deployed to target nodes. It executes sub-tests evaluating systemd run-states, listening ports, hardware DIMM/NVMe health, and network reachability to 25 Google Cloud GDC endpoints, outputting schema-validated JSON reports (`report-schema.json`).

---

## 10. GDC Bootstrap Installation Gates

The standardized sequence of blocking internal gates executed during the automated GDC bare-metal LiveCD installation and first-boot bootstrap:

### Gate 1: Hardware Bus Settling & Enumeration (`HARDWARE_SETTLING`)
Waits for physical system hardware buses (PCI, USB, NVMe storage controllers, and TPM chips) and device nodes to fully enumerate and settle in `/dev/` and `/sys/`.

### Gate 2: Disk Sanitization & Interface Purge (`DISK_SANITIZATION`)
Scans physical storage devices, filters out USB boot media, and purges all residual partition tables, filesystem superblocks, LVM volume groups, and LUKS encryption signatures from target drives.

### Gate 3: Cross-Namespace Integrity Verification (`NAMESPACE_SYNC`)
Executes synchronization loops between container/snap mount namespaces and the host overlayfs to ensure files written during early boot are visible to the Subiquity installer.

### Gate 4: Storage Structure & Partitioning (`STORAGE_LAYOUT`)
Formats physical EFI and boot partitions, establishes the DM-Crypt LUKS container using PBKDF2, allocates the Volume Group `vg_system`, and carves out all required logical volumes.

### Gate 5: OS Payload Injection & Bootloader Stage (`OS_PAYLOAD`)
Writes the base Ubuntu 24.04 operating system payload to `/target`, mounts system volumes, configures `/etc/fstab` with performance mount options, installs the UEFI GRUB bootloader, and writes `/boot/temp_key.key`.

### Gate 6: First-Boot Security Sealing & Key Sanitization (`TPM_SEALING`)
First-boot gate where `systemd-cryptenroll` binds the LUKS volume keyslot to hardware registers PCR `0+7`, updates `/etc/crypttab` to `tpm2-device=auto`, permanently erases `/boot/temp_key.key`, and wipes the temporary password slot.

### Gate 7: Local Boundary Hubs & Playbook Execution (`BOUNDARY_HUB_TURNUP`)
Verifies that local Gitea (port 3000) and Nexus (port 8081) daemons are healthy via wait-for-port loops, after which `ansible-pull` executes system hardening and machine orchestration playbooks.
