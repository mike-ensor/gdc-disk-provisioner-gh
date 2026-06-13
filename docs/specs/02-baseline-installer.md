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
    network:
      version: 2
      ethernets:
        all-en:
          match:
            name: "e*"
          dhcp4: true
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

## 5. Preflight Verification Metrics

Before deploying any configuration, testing engines must execute and assert:
1. **Schema Check:** Confirm `/nocloud/user-data` validates completely using `cloud-init schema --config-file user-data`.
2. **LUKS Encryption Verification:** Post-boot scripts must verify LVM Physical Volumes resides on active `/dev/mapper/` loopback crypt enclaves.
3. **Partition Boundary Separation Check:** Confirm independent logical blocks have been formatted with correct filesystems (EXT4 vs. XFS) and are mounted with accurate performance options (`commit=1` and `noatime`).
