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
        participant Comp as External Telemetry
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

### AMD Zen 4 Bare-Metal Silicon & Firmware Compatibility Specification
Physical bare-metal deployments on AMD Ryzen Zen 4 (AM5) chipsets mandate dual-context kernel parameter separation to bypass low-level firmware deadlocks:
1. **Live CD Environment (Installation Phase):** `modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp` is enforced. Blacklisting the AMD Cryptographic Coprocessor (`ccp`) on the Live CD prevents Subiquity's `Filesystem/_probe` task from deadlocking the Platform Security Processor (PSP) bus when scanning raw NVMe sectors for pre-existing LUKS containers.
2. **Installed Target OS Environment (Production Phase):** `/target/etc/default/grub` is configured without `ccp` in the blacklist, allowing the AMD Secure Processor to initialize CPU power and clock scaling states cleanly without hanging at `1.6s`.
3. **fTPM Hardware Interrupt Bypassing:** Both environments append `tpm_tis.interrupts=0` to the kernel command-line, forcing the built-in TPM driver to run in polling-only mode and bypassing the ACPI hardware interrupt storm bug present on AMD AM5 motherboards.
4. **Target-Side Systemd Ramdisk (`dracut`):** Because Ubuntu 24.04 noble removed `systemd-initramfs`, the installed target OS uses `dracut` to compile a 65MB hostonly systemd initrd, natively packaging `systemd-cryptsetup` and `systemd-cryptenroll` for passwordless TPM 2.0 PCR `0+7` volume unsealing.

### CI/CD Pipeline & Base ISO Caching
* **Cloud Build Integration:** The entire ISO remastering and compilation process is fully automated and runs within a **Google Cloud Build** CI/CD pipeline.
* **Base ISO GCS Caching:** To prevent unnecessary external network requests and guarantee high-speed, deterministic compilation, the "blessed" official Ubuntu 24.04 LTS Base ISO is cached inside a secure Google Cloud Storage (GCS) bucket. The Cloud Build pipeline fetches this cached base ISO directly from GCS into the workspace prior to starting the `remaster.sh` execution.

---

## 3. GDC Deterministic Stage-Gate Bootstrap Architecture

To eliminate temporal race conditions arising from hardware timing deviations (such as DRAM-less NVMe flush latencies or CPU clock scaling), the provisioner enforces a **Stage-Gate Execution Pattern with Barrier Blocking**.

The installation and bootstrapping process is divided into **7 Discrete Stages**. The system is strictly barred from proceeding from Stage $N$ to Stage $N+1$ until all entry/exit qualifications are successfully met. Each stage utilizes an explicit **Polling Loop with a Counter-based Timeout Ceiling** to avoid indefinite hangs.

```
+---------------------------------------+
|  Stage 1: HARDWARE_SETTLING           |
+---------------------------------------+
                   | (Disks stable, TPM, NICs present)
                   v
+---------------------------------------+
|  Stage 2: DISK_SANITIZATION           |
+---------------------------------------+
                   | (Wipefs done, mapper empty)
                   v
+---------------------------------------+
|  Stage 3: NAMESPACE_SYNC              |
+---------------------------------------+
                   | (Write loopback matches host)
                   v
+---------------------------------------+
|  Stage 4: STORAGE_LAYOUT              |
+---------------------------------------+
                   | (LVM created, LUKS container open)
                   v
+---------------------------------------+
|  Stage 5: OS_PAYLOAD                  |
+---------------------------------------+
                   | (/target populated, GRUB in EFI)
                   v
+---------------------------------------+
|  Stage 6: TPM_SEALING                 |
+---------------------------------------+
                   | (LUKS bound, temp key wiped)
                   v
+---------------------------------------+
|  Stage 7: BOUNDARY_HUB_TURNUP         |
+---------------------------------------+
                   | (Gitea/Nexus up, Ansible pull OK)
```

---

### Detailed Stage-Gate Specifications

#### Stage 1: Hardware Bus Settling & Enumeration (`HARDWARE_SETTLING`)
*   **Description:** Wait until physical controllers (PCI, USB, Storage, and TPM) have negotiated links and registered proper interfaces in the system bus.
*   **Entry Qualifications:** Linux Kernel successfully booted (initramfs loaded).
*   **Exit Qualifications:**
    *   Target disk is detected with a physical model name and size $> 0$ sectors.
    *   TPM character device nodes `/dev/tpm0` and `/dev/tpmrm0` are present.
    *   Primary physical NIC (e.g., `enp1s0`) is registered and active.
*   **Error / Failure Handling:** If assertions fail after 30 seconds (30 polls of 1.0s), abort installation and drop to the `crash-cart` debug console.

#### Stage 2: Disk Sanitization & Interface Purge (`DISK_SANITIZATION`)
*   **Description:** Clear the installation drive of residual partitions, signatures, logical volumes, or encrypted mappings that might conflict with partition maps.
*   **Entry Qualifications:** Stage 1 (`HARDWARE_SETTLING`) successfully completed.
*   **Exit Qualifications:**
    *   `wipefs` returns zero active signatures on the block device.
    *   Device-mapper directories (`/dev/mapper/*`) contain no active system logical volumes or conflicting crypt tunnels.
    *   `/proc/mdstat` indicates no software RAID layers are bound to the disk.
*   **Error / Failure Handling:** If drive sanitization or volume close fails after 15 seconds (15 polls of 1.0s), mark partition layout as `FAILED` and log trace.

#### Stage 3: Cross-Namespace Integrity Verification (`NAMESPACE_SYNC`)
*   **Description:** Mitigate snap-to-host mount namespace write propagation delays.
*   **Entry Qualifications:** Stage 2 (`DISK_SANITIZATION`) successfully completed.
*   **Exit Qualifications:**
    *   A test string written inside the Subiquity/Snap private namespace successfully appears in the host overlayfs with matching cryptographic hash within 5.0 seconds (50 polls of 0.1s).
    *   The staging key file is verified as non-empty (size $> 0$) and readable in both namespaces.
*   **Error / Failure Handling:** If file propagation times out, halt installation immediately to prevent formatting with an empty (0-byte) key.

#### Stage 4: Storage Structure & Partitioning (`STORAGE_LAYOUT`)
*   **Description:** Partition disks, initialize LUKS2 containers, and configure the LVM volume group.
*   **Entry Qualifications:** Stage 3 (`NAMESPACE_SYNC`) successfully completed.
*   **Exit Qualifications:**
    *   `cryptsetup` successfully formats and maps `/dev/mapper/crypt-system` using the valid staging key.
    *   Volume group `vg_system` and all 11 required logical volumes are queryable and show expected sizes.
*   **Error / Failure Handling:** If `cryptsetup` formats using a fallback or empty key, or if partition offsets fail to align, abort and write a core installer crash dump.

#### Stage 5: OS Payload Injection & Bootloader Stage (`OS_PAYLOAD`)
*   **Description:** Write base OS filesystem payload, mount essential paths, configure EFI bootloader settings, and compile the systemd-based initramfs using native initramfs-tools.
*   **Entry Qualifications:** Stage 4 (`STORAGE_LAYOUT`) successfully completed.
*   **Exit Qualifications:**
    *   System structures mounted under `/target` match target specifications.
    *   UEFI GRUB bootloader successfully written to partition 1 with the module blacklist `modprobe.blacklist=pcie_mp2_amd,amd_sfh` and `tpm_tis.interrupts=0` appended to the kernel cmdline to prevent early fTPM deadlocks on AMD platforms.
    *   `initramfs-tools` and `cryptsetup-initramfs` successfully compile a highly optimized (35MB) boot ramdisk containing `crypt` and `lvm` modules, and packages `/etc/keys/temp_key.key` (represented inside initrd as `/cryptroot/keyfiles/crypt-system.key`) to allow passwordless first-boot decryption. A custom, alphabetically late compile hook (`zz-gdc-blacklist`) executes at the very end of the staging phase to surgically prune blacklisted deadlock modules (`amd_sfh.ko.zst`).
    *   **Pre-Reboot Initramfs Validation Checks:** The Subiquity `late-commands` automatically execute `lsinitramfs` to run five programmatic assertions verifying:
        1. Transition keyfile presence.
        2. `crypt` decryption module inclusion.
        3. `lvm` logical volume module inclusion.
        4. Physical storage controller (NVMe/SATA) drivers inclusion.
        5. Absolute exclusion of fTPM-deadlocking drivers (`pcie_mp2_amd` and `amd_sfh`).
*   **Error / Failure Handling:** If GRUB fails to write, or if any of the five pre-reboot initramfs assertions fail, the installer halts execution immediately, writes the exit status to `/dev/ttyS0`, and reports the error to GDC Companion, blocking reboot to prevent silent black-screen hangs.

#### Stage 6: First-Boot Security Sealing & Key Sanitization (`TPM_SEALING`)
*   **Description:** Bind the LUKS volume encryption to the physical TPM 2.0 PCR registers and wipe transient keys.
*   **Entry Qualifications:** First boot of the target OS initiated; Stage 5 completed.
*   **Exit Qualifications:**
    *   `systemd-cryptenroll` binds the key to PCRs `0+7` on `/dev/tpmrm0`.
    *   The temporary boot keyfile `/boot/temp_key.key` is cryptographically shredded (via `shred -u`) and its keyslot is cleared.
*   **Error / Failure Handling:** If TPM enrollment fails, keep the fallback recovery key and register a critical warning with the diagnostics subsystem to block standalone cluster enrollment.

#### Stage 7: Local Boundary Hubs & Playbook Execution (`BOUNDARY_HUB_TURNUP`)
*   **Description:** Initialize the local offline caches (Gitea and Nexus) and run the local `ansible-pull` playbooks.
*   **Entry Qualifications:** Node booted, Stage 6 (`TPM_SEALING`) successfully verified.
*   **Exit Qualifications:**
    *   Ports `3000` (Gitea) and `8081` (Nexus) respond with successful HTTP handshakes.
    *   `ansible-pull` completes execution with exit code `0`.
*   **Error / Failure Handling:** If ports do not open within 120 seconds (60 polls of 2.0s), automatically trigger `@bin/collect-node-diagnostics.sh` and push the diagnostics bundle to `gdc-companion`.

---

### Progress Tracking & Verification Evidence
To enable real-time tracking of node state transitions in the **GDC Companion** application, the `collect-node-diagnostics.sh` script automatically records and transmits the current completed stage. The status payload includes:
1.  **Stage ID:** Current active stage string (e.g., `NAMESPACE_SYNC`).
2.  **State Status:** `PENDING`, `IN_PROGRESS`, `COMPLETED`, or `FAILED`.
3.  **Verification Evidence:** Specific telemetry readings (e.g., MAC, disk sizes, partition mounts, socket statuses) acting as proof of transition.
