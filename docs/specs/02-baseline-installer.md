# Specification: GDC Baseline Installer & Enterprise LVM Storage Layout

**Spec Identifier:** `GDC-SPEC-002`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Executive Summary & Purpose
This specification details the Baseline OS installation phase. It outlines the BIOS/UEFI bootloaders, the unattended Subiquity autoinstall yaml configurations, and the exact GDC Bare Metal compliant Enterprise LVM disk layouts. 

To satisfy GDC's strict pre-flight requirements, the storage architecture introduces an encrypted dm-crypt LUKS partition directly at installation time, isolates write-intensive containerd images and log queues, and separates latency-sensitive etcd transactions onto isolated logical volumes with performance-enhancing mount options.

---

## 2. Unattended Boot Arguments (GRUB Template)
To boot and install in fully automated, headless environments, the ISO GRUB configuration forces an autoinstall target pointing to the local NoCloud datasource `/cdrom/nocloud/`. Network checks are ignored by using a DHCP default fallback.

**Config Location inside ISO:** `/boot/grub/grub.cfg`
```text
set timeout=5
set default=0

menuentry "Google Distributed Cloud (GDC) Automated Unattended Bootstrap" {
    set gfxpayload=keep
    linux /casper/vmlinuz quiet autoinstall ds=nocloud;s=/cdrom/nocloud/ ip=dhcp ---
    initrd /casper/initrd
}
```

---

## 3. Storage LVM Layout Specification

### 3.1. Physical Layout Map
The primary target SSD/NVMe drive is formatted with three partitions:
* **`/dev/nvme0n1p1`**: `/boot/efi` – 1 GiB (FAT32) – ESP System boot loader.
* **`/dev/nvme0n1p2`**: `/boot` – 2 GiB (EXT4) – Standard static Linux boot directory.
* **`/dev/nvme0n1p3`**: LUKS Enclave (`dm_crypt` container) backing Volume Group `vg_system`.

### 3.2. Logical Volumes inside `vg_system` & Mount Tuning

| Volume Name | Mount Point | Size | Filesystem | Mount Options | GDC Compliance Role / Isolated Metric |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `lv_root` | `/` | 20 GiB | EXT4 | `defaults` | Base system files & temporary tools |
| `lv_var` | `/var` | 20 GiB | EXT4 | `defaults,noatime` | Kubelet states and runtime data |
| `lv_var_log` | `/var/log` | 15 GiB | EXT4 | `defaults,noatime` | **Logs Isolation:** Fluent-bit buffers (12 GiB req) |
| `lv_metrics` | `/var/opt/buffered-metrics` | 10 GiB | EXT4 | `defaults,noatime` | **Metrics Isolation:** GDC metrics buffers (10,016 MiB req) |
| `lv_containerd` | `/var/lib/containerd` | 30 GiB | XFS | `defaults,noatime,prjquota` | **Image Isolation:** containerd container space (30 GiB req) |
| `lv_etcd` | `/var/lib/etcd` | 20 GiB | EXT4 | `noatime,nodiratime,commit=1` | **Performance Isolation:** etcd core database (20 GiB req) |
| `lv_etcd_events` | `/var/lib/etcd-events` | 5 GiB | EXT4 | `noatime,nodiratime,commit=1` | **Performance Isolation:** etcd event records (5 GiB req) |
| `lv_gitea` | `/var/lib/gitea` | 20 GiB | EXT4 | `defaults,noatime` | Persistent Gitea git storage boundary |
| `lv_nexus` | `/var/lib/nexus` | 150 GiB | EXT4 | `defaults,noatime` | Persistent Nexus package/image storage boundary |
| `lv_local_disk` | `/customer/local-disk` | 100 GiB | XFS | `defaults,noatime,prjquota` | **GDC Bounds:** Standalone `local-disk` provisioner |
| `lv_sds` | `/customer/sds` | Remainder | XFS | `defaults,noatime` | **SDS Storage:** Allocated for SDS system backends |

*Note on etcd mounts: Specifying `commit=1` forces write barriers to sync metadata changes in under 1 second, reducing etcd database write latency to guarantee cluster consensus loops under high load.*

### 3.3. Dynamic Multi-Disk (1 or 2 Disks) Storage Architecture
To support hardware nodes containing either **1 or 2 physical disks** of varying sizes ($\ge 250\text{GB}$), the installer executes a dynamic block analyzer script (`src/build/generate_storage_config.sh`) during the early stages of cloud-init boot.

This script outputs a tailored, GDC-compliant Subiquity storage layout block based on the discovered disk count:

#### A. Single-Disk Topology (1x NVMe/SSD $\ge 250\text{GB}$)
* **The Sizing Constraint:** Because the sum of default logical volumes exceeds 400 GiB, booting on a 250GB drive requires dynamic scaling.
* **The Resolution:** Gitea, Nexus, and local-disk partitions are scaled down (Gitea to 15G, Nexus to 60G, Local-Disk to 25G) to guarantee they fit within 250GB, leaving the remaining block capacity (~20GB) to `/customer/sds`.

#### B. Dual-Disk Topology (2x NVMe/SSD $\ge 250\text{GB}$)
* **Workload Separation (Separation of Concerns):** To maximize performance and satisfy etcd leader latency parameters, we isolate standard system operations from high-volume customer storage pipelines across the two physical drives:
  * **Disk 1 (System Disk):** Holds EFI, Boot, and the core encrypted OS volume group (`vg_system`), carrying the operating system, logging, containerd CRI, etcd databases, and local Service Hubs (Gitea and Nexus). This consumes ~240GB, fitting perfectly on a 250GB drive.
  * **Disk 2 (Data Disk):** Initialized as a separate encrypted volume group (`vg_data`), dedicated entirely to `/customer/local-disk` (100G) and `/customer/sds` (remainder of Disk 2). If Disk 2 is a 1TB SSD, `/customer/sds` automatically receives the remaining ~800GB.
  * *Result:* Heavy container image extractions and customer storage I/O on Disk 2 are mathematically isolated from the low-latency consensus database of etcd on Disk 1.

### 3.4. Pre-seeded Storage & Docker Group Repository
To facilitate immediate offline operations post-boot, the persistent storage allocated to `/var/lib/nexus` is pre-seeded during the late-commands phase with a configured Nexus Repository Manager instance. This instance implements a **Docker Group Repository** pattern to aggregate and serve OCI container images.
* **Pre-seeded Content:** At ISO creation time, all required OCI container images for the **Cluster** (Kubernetes, etcd, CoreDNS, etc.), **Platform** (management controllers, logging agents), and **Applications** (user workloads and microservices)—complete with their specific semantic versions at the time of compilation—are pre-fetched, packed, and placed inside the ISO's pre-seed structure (`/custom-data/nexus/`).
* **Storage Allocation:** On Single-Disk topologies, the scaled-down 60 GiB `/var/lib/nexus` logical volume is carefully size-budgeted to ensure the pre-seeded OCI image layers and deb packages cleanly fit within the allocation bounds.

---

## 4. Subiquity Autoinstall User-Data (`/nocloud/user-data`)
This declarative configuration enforces the encrypted storage partitioning schemes, redirects APT package installs to the local live-ISO Nexus server, and shuts down the host on completion.

```yaml
#cloud-config
autoinstall:
  version: 1
  identity:
    hostname: gdc-standalone-node
    username: temporary-installer
    password: "$6$rounds=4096$rounds_salt$placeholder_hash"
  locale: en_US.UTF-8
  keyboard: {layout: us}
  network:
    # AUTOMATED MULTI-IP VRF SEGREGATION ON INITIAL PROVISION
    network:
      version: 2
      renderer: networkd
      ethernets:
        eth0:
          dhcp4: no
          dhcp6: no
          link-local: []
      vlans:
        eth0.10:
          id: 10
          link: eth0
          addresses: [192.168.10.5/24]
          routes:
            - to: default
              via: 192.168.10.1
              metric: 100
          nameservers:
            addresses: [8.8.8.8, 8.8.4.4]
        eth0.20:
          id: 20
          link: eth0
          addresses: [192.168.20.5/24]
          routes:
            - to: default
              via: 192.168.20.1
              metric: 200
          nameservers:
            addresses: [1.1.1.1]
      vrfs:
        vrf-machine:
          table: 10
          interfaces: [eth0.10]
        vrf-k8s:
          table: 20
          interfaces: [eth0.20]
  apt:
    # REDIRECT APT TO LOCAL EPHEMERAL NEXUS PROXIES DURING INSTALL
    primary:
      - arches: [default]
        uri: http://127.0.0.1:8081/repository/gdc-apt-proxy/
    geoip: false
    fallback: offline
  storage:
    layout:
      name: direct
    config:
      # --- 1. Identify Target Disk ---
      - {type: disk, id: disk-primary, match: {size: largest}}
      
      # --- 2. System Partitions ---
      - {type: partition, id: partition-efi, device: disk-primary, size: 1GiB, flag: bios_grub}
      - {type: partition, id: partition-boot, device: disk-primary, size: 2GiB}
      - {type: partition, id: partition-lvm, device: disk-primary, size: -1}
      
      # --- 3. Format/Mount System Partitions ---
      - {type: format, id: format-efi, volume: partition-efi, fstype: fat32}
      - {type: format, id: format-boot, volume: partition-boot, fstype: ext4}
      - {type: mount, id: mount-efi, volume: format-efi, path: /boot/efi}
      - {type: mount, id: mount-boot, volume: format-boot, path: /boot}
      
      # --- 4. LUKS Encryption Layer (MANDATORY) ---
      - {type: dm_crypt, id: crypt-lvm, volume: partition-lvm, key: "temporary_bootstrap_key_to_be_enrolled_to_tpm"}
      
      # --- 5. LVM Volume Group ---
      - {type: lvm_volgroup, id: vg-system, name: vg_system, devices: [crypt-lvm]}
      
      # --- 6. Logical Volumes (LVs) ---
      - {type: lvm_partition, id: lv-root, volgroup: vg-system, name: lv_root, size: 20GiB}
      - {type: lvm_partition, id: lv-var, volgroup: vg-system, name: lv_var, size: 20GiB}
      - {type: lvm_partition, id: lv-varlog, volgroup: vg-system, name: lv_var_log, size: 15GiB}
      - {type: lvm_partition, id: lv-metrics, volgroup: vg-system, name: lv_var_opt_metrics, size: 10GiB}
      - {type: lvm_partition, id: lv-containerd, volgroup: vg-system, name: lv_containerd, size: 30GiB}
      - {type: lvm_partition, id: lv-etcd, volgroup: vg-system, name: lv_etcd, size: 20GiB}
      - {type: lvm_partition, id: lv-etcd-events, volgroup: vg-system, name: lv_etcd_events, size: 5GiB}
      - {type: lvm_partition, id: lv-gitea, volgroup: vg-system, name: lv_gitea, size: 20GiB}
      - {type: lvm_partition, id: lv-nexus, volgroup: vg-system, name: lv_nexus, size: 150GiB}
      - {type: lvm_partition, id: lv-localdisk, volgroup: vg-system, name: lv_local_disk, size: 100GiB}
      - {type: lvm_partition, id: lv-sds, volgroup: vg-system, name: lv_sds, size: -1} # Remainder for SDS
      
      # --- 7. Format Logical Volumes ---
      - {type: format, id: fmt-root, volume: lv-root, fstype: ext4}
      - {type: format, id: fmt-var, volume: lv-var, fstype: ext4}
      - {type: format, id: fmt-varlog, volume: lv-varlog, fstype: ext4}
      - {type: format, id: fmt-metrics, volume: lv-metrics, fstype: ext4}
      - {type: format, id: fmt-containerd, volume: lv-containerd, fstype: xfs}
      - {type: format, id: fmt-etcd, volume: lv-etcd, fstype: ext4}
      - {type: format, id: fmt-etcd-events, volume: lv-etcd-events, fstype: ext4}
      - {type: format, id: fmt-gitea, volume: lv-gitea, fstype: ext4}
      - {type: format, id: fmt-nexus, volume: lv-nexus, fstype: ext4}
      - {type: format, id: fmt-localdisk, volume: lv-localdisk, fstype: xfs}
      - {type: format, id: fmt-sds, volume: lv-sds, fstype: xfs}
      
      # --- 8. Mount Logical Volumes & Apply Mount Options ---
      - {type: mount, id: mnt-root, volume: fmt-root, path: /}
      - {type: mount, id: mnt-var, volume: fmt-var, path: /var, options: "defaults,noatime"}
      - {type: mount, id: mnt-varlog, volume: fmt-varlog, path: /var/log, options: "defaults,noatime"}
      - {type: mount, id: mnt-metrics, volume: fmt-metrics, path: /var/opt/buffered-metrics, options: "defaults,noatime"}
      - {type: mount, id: mnt-containerd, volume: fmt-containerd, path: /var/lib/containerd, options: "defaults,noatime,prjquota"}
      - {type: mount, id: mnt-etcd, volume: fmt-etcd, path: /var/lib/etcd, options: "noatime,nodiratime,commit=1"}
      - {type: mount, id: mnt-etcd-events, volume: fmt-etcd-events, path: /var/lib/etcd-events, options: "noatime,nodiratime,commit=1"}
      - {type: mount, id: mnt-gitea, volume: fmt-gitea, path: /var/lib/gitea, options: "defaults,noatime"}
      - {type: mount, id: mnt-nexus, volume: fmt-nexus, path: /var/lib/nexus, options: "defaults,noatime"}
      - {type: mount, id: mnt-localdisk, volume: fmt-localdisk, path: /customer/local-disk, options: "defaults,noatime,prjquota"}
      - {type: mount, id: mnt-sds, volume: fmt-sds, path: /customer/sds, options: "defaults,noatime"}
EOF
```

---

## 5. Smart Installation Logging & Cryptic Failure Mitigation
The standard Subiquity reporting output can be extremely cryptic when storage partitioning or configuration tasks fail. To enforce highly-visible, human-readable installation logging and facilitate immediate on-site diagnostics, the baseline installation runs under a strict **Goal-Based Logging Wrapper**.

### 5.1. The Logging Standard
Before performing any shell operation inside `early-commands`, `late-commands`, or other custom installation scripts, the system must invoke a structured logging wrapper that writes to both the active installation TTY console and the system's syslog (`/var/log/syslog` / systemd-journald):

*   **Format for Goals:**
    `[GDC-INSTALL-GOAL] Starting Task: <High-Level Activity and Intent>`
*   **Format for Failures:**
    `[GDC-INSTALL-FAIL] Critical Failure: <Descriptive activity name>! Details: <Error Message, Line Number, and Exit Code>`

### 5.2. Example Execution Wrapper (Shell Trap Method)
All scripts executed during the baseline installer phase must implement automatic error trapping. This translates raw bash crashes into explicit diagnostic blocks:

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Diagnostic Helpers
log_goal() {
    local goal_desc="$1"
    echo "=============================================================================="
    echo "[GDC-INSTALL-GOAL] Starting Task: ${goal_desc}"
    echo "=============================================================================="
    logger -t gdc-provisioner "[GOAL] ${goal_desc}"
}

log_fail() {
    local fail_desc="$1"
    local error_msg="${2:-No extra context provided}"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "[GDC-INSTALL-FAIL] Critical Failure: ${fail_desc}" >&2
    echo "[GDC-INSTALL-FAIL] Diagnostic Details: ${error_msg}" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    logger -p user.err -t gdc-provisioner "[FAILURE] ${fail_desc} - Details: ${error_msg}"
}

# 2. Automated Crash Handler
failure_handler() {
    local last_line="$1"
    local last_code="$2"
    log_fail "The disk partitioning script crashed unexpectedly!" "Exit Code: ${last_code} on line ${last_line}"
}
trap 'failure_handler ${LINENO} $?' ERR

# 3. Instrumented Execution
log_goal "Scanning hardware block devices for GDC-compliant storage drives (>= 250 GiB)"
# (Disk Scanning logic...)

log_goal "Activating SINGLE-DISK LVM storage configuration"
# (Partitioning execution...)
```

### 5.3. Subiquity YAML Webhook Reporting
To stream these structured goal logs and failures to the centralized GCP log monitoring gateway via our local admin workstation proxy (as defined in `GDC-SPEC-001`), Subiquity's webhook reporting is hooked directly into the autoinstall config:

```yaml
autoinstall:
  reporting:
    gdc-gateway:
      type: webhook
      url: http://10.0.0.1:8080/v1/install-logs
      level: info
```
This guarantees that any fail signal is instantly captured and centralized for network-wide visibility.

---

## 6. Preflight Verification Metrics

Before deploying any configuration, testing engines must execute and assert:
1. **Schema Check:** Confirm `/nocloud/user-data` validates completely using `cloud-init schema --config-file user-data`.
2. **LUKS Encryption Verification:** Post-boot scripts must verify LVM Physical Volumes resides on active `/dev/mapper/` loopback crypt enclaves.
3. **Partition Boundary Separation Check:** Confirm independent logical blocks have been formatted with correct filesystems (EXT4 vs. XFS) and are mounted with accurate performance options (`commit=1` and `noatime`).
