# Google Distributed Cloud (GDC) Enterprise LVM Storage & Disk Partitioning Map

This document specifies the design, dynamic discovery heuristics, partitioning mechanics, and LVM logical volume layouts implemented by the GDC Offline Bootloader ISO and installer. 

To satisfy Google Distributed Cloud (GDC) Bare Metal pre-flight requirements, the storage pipeline automates disk analysis, deploys baseline LUKS encryption, separates latency-sensitive etcd consensus logs from write-heavy container/registry workloads, and preserves raw block devices for Software-Defined Storage (SDS).

---

## 1. Storage Architecture Overview

GDC Bare Metal requires strict isolation of disk workloads to prevent resource contention, write-exhaustion, and etcd transaction delays. The GDC installer achieves this by automatically analyzing the host's block device layout at boot, selecting either a **Single-Disk** or **Dual/Multi-Disk** performance topology, and deploying a secured, encrypted, and tuned LVM structure.

```text
                                  [ DISK DISCOVERY ]
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
        [ Single-Disk Topology ]                  [ Multi-Disk Topology ]
        • 1x NVMe/SSD >= 250 GiB                 • >= 2x NVMe/SSD >= 250 GiB
        • Scales down local services             • Dedicates Disk 1 to OS & etcd
        • Combines OS & SDS onto Disk 1          • Dedicates Disk 2 to local-disk & SDS
                                                 • Leaves Disks 3 & 4 completely pristine
```

---

## 2. Disk Detection & Filtering Heuristics

The dynamic disk analyzer script (`src/build/generate_storage_config.sh`) executes during the early stage of cloud-init boot. It scans block devices using the following heuristics:

1. **Size Filtering:** Only devices with a capacity $\ge 560\text{ GiB}$ ($1,174,405,120$ sectors of 512 bytes) are registered as GDC-compliant target drives. Smaller storage targets are ignored.
2. **Device Exclusion:** System loopback devices (`/dev/loop*`), active bootable installer live media (`/cdrom`, `/isodevice`, `iso9660` optical/USB drives), and all USB transport storage devices (`TRAN=usb` or `/sys/devices/.../usb*`) are explicitly excluded to prevent accidental self-erasure when booting from USB media.
3. **Ascending Size Sorting:** Disks are sorted ascending by sector count. The smaller physical drive is always allocated as the **System Disk (Disk 1)**, while the larger drive is designated as the **Data Disk (Disk 2)**. This ensures optimal utilization of high-capacity storage on dense hardware platforms.

---

## 3. Dynamic Topology & Scaling Rules

### A. Single-Disk Topology (1x NVMe/SSD $\ge 600\text{ GiB}$ / $1\text{ TB}$)
* **The Constraint:** The sum of standard GDC Logical Volume targets (including 100 GiB logs and 300 GiB Nexus) requires at least 557 GiB baseline storage before customer SDS allocation.
* **The Resolution:** Logical volumes are allocated with dedicated quotas:
  * `lv_var_log` is allocated **100 GiB**.
  * `lv_gitea` is scaled to **15 GiB**.
  * `lv_nexus` (registry mirror) is allocated **300 GiB**.
  * `lv_local_disk` is scaled to **25 GiB**.
  * `lv_sds` (Software-Defined Storage) is assigned all remaining capacity (`size: -1`).
* **LUKS Container:** A single encrypted DM-Crypt container (`crypt-system`) is initialized, backing the Volume Group `vg_system`.

### B. Dual/Multi-Disk Topology (2x to 4x+ NVMe/SSD $\ge 600\text{ GiB}$ / $1\text{ TB}$)
* **Workload Isolation (Separation of Concerns):** To maximize IOPS performance and satisfy etcd's low-latency requirements under high loads, system processes and customer container data pipelines are physically separated across independent physical drives:
  * **Disk 1 (System Disk):** Automatically partitioned and mapped under the encrypted volume group `vg_system`. It hosts `/`, `/var`, `/var/log` (100 GiB), `containerd`, `etcd`, Gitea, and Nexus. Since local storage blocks are moved to Disk 2, the installer removes the fixed sizing limits on local mirrors, allowing `lv_nexus` to scale to the **entire remainder of Disk 1** (`size: -1`, guaranteed $\ge 300\text{ GiB}$ on compliant drives) to cache massive registries.
  * **Disk 2 (Data Disk):** Initialized under a separate encrypted LVM Volume Group `vg_data`. This drive is dedicated entirely to high-volume user data: `/customer/local-disk` (100 GiB) and `/customer/sds` (remainder of Disk 2, `size: -1`).
  * **Outcome:** Write-heavy container extractions on Disk 2 do not cause I/O latency spikes on Disk 1, ensuring the etcd consensus database maintains uninterrupted quorum.

### C. Pristine Block Preservation (Disks 3 and 4)
* **The Rule:** Any additional drives beyond the first two (e.g., Disk 3 and Disk 4 in a 4-disk system) are **completely ignored** by the installer's partitioning routines.
* **The Importance for SDS:** Kubernetes Software-Defined Storage (SDS) systems (such as GDC local-volume-provisioner, Ceph/Rook, or Portworx) require raw, unpartitioned physical drives for volume pooling. Writing LVM structures to these additional disks would cause the SDS auto-discovery agents to skip them. Leaving them pristine allows the SDS storage controllers to detect, format, and claim them dynamically post-install.

---

## 4. LVM Storage Layout & Partition Map

The primary target drives are partitioned and formatted based on the detected topology. Under both topologies, the core OS layout maps the following logical volumes inside LVM:

### System Volume Group (`vg_system`) - Mounted on Disk 1

| Logical Volume | Mount Point | Default Size | Filesystem | Mount Options | GDC Compliance Role & Tuning |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `lv_root` | `/` | 20 GiB | EXT4 | `defaults` | Host operating system binaries & basic tools. |
| `lv_var` | `/var` | 20 GiB | EXT4 | `defaults,noatime` | Kubelet states and runtime data directories. |
| `lv_var_log` | `/var/log` | 100 GiB | EXT4 | `defaults,noatime` | **Logs Isolation:** Fluent-bit buffers and journald logs isolated from system root. |
| `lv_var_opt_metrics` | `/var/opt/buffered-metrics` | 10 GiB | EXT4 | `defaults,noatime` | **Metrics Isolation:** GDC metrics collection buffer (10,016 MiB required). |
| `lv_containerd` | `/var/lib/containerd` | 30 GiB | XFS | `defaults,noatime,prjquota` | **CRI Isolation:** Container image storage; enforces XFS Project Quotas (`prjquota`). |
| `lv_etcd` | `/var/lib/etcd` | 20 GiB | EXT4 | `noatime,nodiratime,commit=1` | **Performance Isolation:** Core etcd database. `commit=1` minimizes consensus write latency. |
| `lv_etcd_events` | `/var/lib/etcd-events` | 5 GiB | EXT4 | `noatime,nodiratime,commit=1` | **Performance Isolation:** etcd events database. `commit=1` minimizes event write latency. |
| `lv_gitea` | `/var/lib/gitea` | 20 GiB | EXT4 | `defaults,noatime` | Local Gitea mirror git repositories storage boundary. |
| `lv_nexus` | `/var/lib/nexus` | 300 GiB* | EXT4 | `defaults,noatime` | Local Nexus cache and blob stores (APT, OCI registry layers, LLMs). |

*\* Note: On Single-Disk topologies, `lv_var_log` is 100 GiB, `lv_gitea` is scaled to 15 GiB, `lv_nexus` to 300 GiB, and `lv_root`/`lv_var` to 15 GiB/25 GiB. On Dual-Disk topologies, `lv_nexus` consumes the entire remainder of Disk 1 (`size: -1`, guaranteed $\ge 300\text{ GiB}$ on compliant drives).*

### Data Volume Group (`vg_data`) - Mounted on Disk 2 (Multi-Disk Only)

| Logical Volume | Mount Point | Default Size | Filesystem | Mount Options | GDC Compliance Role & Tuning |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `lv_local_disk` | `/customer/local-disk` | 100 GiB | XFS | `defaults,noatime,prjquota` | GDC standalone `local-disk` storage provisioner boundary. |
| `lv_sds` | `/customer/sds` | Remainder | XFS | `defaults,noatime` | Allocated as backing storage for our custom SDS engine. |

---

## 5. Performance Mount Tuning

To guarantee cluster performance under heavy workloads:
* **`commit=1`:** Forced on `/var/lib/etcd` and `/var/lib/etcd-events` to force metadata write barriers in under 1 second. This guarantees metadata consistency and keeps etcd database disk latency within bare metal consensus requirements.
* **`noatime` / `nodiratime`:** Applied across all active datastores to completely bypass write overhead from updating inode access timestamps on read commands.
* **`prjquota`:** Enforced on XFS filesystems (`/var/lib/containerd` and `/customer/local-disk`) to support strict container directory disk limits and directory project quotas.

---

## 6. Security & Cryptographic Lifecycle (LUKS & TPM 2.0)

To achieve secure, unattended, and air-gapped provisioning, GDC Bare Metal nodes follow a **two-phase hybrid cryptographic lifecycle** to initialize, seal, and protect host storage volumes.

### Phase 1: Unattended Partitioning (Installation Phase)
* **The Challenge:** To format LUKS2 volumes non-interactively, the installer must supply a decryption key. Running Subiquity inside a strictly confined Snap container causes timing and write-propagation delays across the mount namespace boundary if keys are written to standard `/tmp/` paths.
* **The Resolution (GDC-RCA-2026-07-11-01):** The installer writes a temporary bootstrap key (`temporary_bootstrap_key_to_be_enrolled_to_tpm`) directly to `/var/log/installer/gdc-luks-key`. Because `/var/log/installer` is a direct host-to-snap bind-mount, propagation is instantaneous, allowing `cryptsetup` to reliably partition and format target NVMe drives on first attempt.
* **Storage Encryption State:** During this phase, all encrypted block devices (e.g., `nvme0n1p3`) use this static bootstrap passphrase.

### Phase 2: Host Hardening (First-Boot Ansible Phase)
Upon first boot, the system transitions from the generic installation state to a hardened, node-specific secure state via the post-install Ansible-pull pipeline (`src/ansible/roles/security_hardening/tasks/main.yml`):

1. **Hardware Sealing (TPM 2.0):** Ansible queries the host for an active Trusted Platform Module (TPM 2.0) device (`/dev/tpmrm0`). It seals the LUKS Master Key to the node's physical TPM chip PCR registers (`0+7` in UEFI mode) using `systemd-cryptenroll`. This locks the decryption key specifically to the host's physical motherboard and system integrity state, while preventing Option ROM device shifts (PCR 2) from locking the boot on subsequent reboots.
2. **Password Revocation:** It purges the insecure, static bootstrap passphrase slot from the LUKS container keyslots using:
   ```bash
   systemd-cryptenroll --wipe-slot=password --unlock-key-file=/etc/keys/temp_key.key <device>
   ```
   After this command completes, the bootstrap key string is permanently revoked and can no longer decrypt the disk.
3. **Plaintext Erasing:** The plaintext keyfile `/etc/keys/temp_key.key` is permanently deleted from the host filesystem.
4. **Boot-Time Unlocking:** It reconfigures `/etc/crypttab` with the `tpm2-device=auto` option and rebuilds `initramfs` so that the local systemd-cryptsetup daemon can automatically and securely unseal the volumes during subsequent boots without manual password entry or plaintext keys on disk.
