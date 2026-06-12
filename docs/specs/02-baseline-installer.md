# Specification: GDC Baseline Installer & Enterprise LVM Storage Layout

**Spec Identifier:** `GDC-SPEC-002`  
**Status:** DRAFT  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Overview & Purpose
This specification details the baseline OS installation phase. It covers the automated boot configuration, the Subiquity autoinstall schema, and the exact GDC Bare Metal compliant LVM storage layout. The layout isolates high-IOPS write targets (such as etcd) and high-volume write targets (such as container registries and logging buffers) to prevent system crashes and performance degradation.

---

## 2. Boot Arguments (GRUB Template)
To trigger automated installation offline, the ISO's boot parameters must explicitly reference the embedded `NoCloud` configuration path. The GRUB template configures Subiquity and instructs it to bypass network checks:

```text
menuentry "GDC Automated Baseline Install (Ubuntu 24.04)" {
    set gfxpayload=keep
    linux /casper/vmlinuz quiet autoinstall ds=nocloud;s=/cdrom/nocloud/ ip=dhcp ---
    initrd /casper/initrd
}
```

---

## 3. Storage LVM Layout Specification
The installer partitions the disk and isolates directories in accordance with the official GDC Bare Metal machine prerequisites (v1.29.100+). The target volume group is `vg_system`.

### 3.1. Physical Layout Map
* **`/dev/nvme0n1p1`**: `/boot/efi` – 1 GiB (FAT32) – ESP System boot loader.
* **`/dev/nvme0n1p2`**: `/boot` – 2 GiB (EXT4) – Standard static Linux boot directory.
* **`/dev/nvme0n1p3`**: LVM Physical Volume (PV) backing Volume Group `vg_system`.

### 3.2. Logical Volumes inside `vg_system`

| Name | Mount Point | Size | Filesystem | GDC Compliance Role / Isolated Metric |
| :--- | :--- | :--- | :--- | :--- |
| `lv_root` | `/` | 20 GiB | EXT4 | Standard operating system binaries |
| `lv_var` | `/var` | 20 GiB | EXT4 | Shared runtime directories (includes `/var/lib/kubelet`) |
| `lv_var_log` | `/var/log` | 15 GiB | EXT4 | **Isolated:** Logs & Fluent-bit log buffers (12 GiB req) |
| `lv_var_opt_metrics` | `/var/opt/buffered-metrics` | 10 GiB | EXT4 | **Isolated:** GDC Buffered Metrics buffer space (10,016 MiB req) |
| `lv_containerd` | `/var/lib/containerd` | 30 GiB | EXT4 | **Isolated:** Local containerd container storage (30 GiB CP req) |
| `lv_etcd` | `/var/lib/etcd` | 20 GiB | EXT4 | **Isolated (Performance):** etcd database storage (20 GiB req) |
| `lv_etcd_events` | `/var/lib/etcd-events` | 5 GiB | EXT4 | **Isolated:** etcd event logging storage (5 GiB req) |
| `lv_gitea` | `/var/lib/gitea` | 20 GiB | EXT4 | Persistent Gitea server repository storage |
| `lv_nexus` | `/var/lib/nexus` | 150 GiB | EXT4 | Persistent Nexus local binary/cache database storage |
| `lv_local_disk` | `/customer/local-disk` | 100 GiB | EXT4/XFS | GDC standalone host static persistent disk provisioner root |
| `lv_sds` | `/customer/sds` | Remainder | EXT4/XFS | Allocated to the Software-Defined Storage (SDS) backend |

---

## 4. Subiquity Autoinstall User-Data (`/nocloud/user-data`)
The declarative `user-data` configuration maps the partitions and dictates offline installations.

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
    # REDIRECT APT TO LOCAL EPHEMERAL NEXUS INSTEAD OF ONLINE MIRRORS
    primary:
      - arches: [default]
        uri: http://localhost:8081/repository/gdc-apt-proxy/
    geoip: false
    fallback: offline
  storage:
    layout:
      name: direct
    config:
      - {type: disk, id: disk-primary, match: {size: largest}}
      - {type: partition, id: partition-efi, device: disk-primary, size: 1GiB, flag: bios_grub}
      - {type: partition, id: partition-boot, device: disk-primary, size: 2GiB}
      - {type: partition, id: partition-lvm, device: disk-primary, size: -1}
      - {type: format, id: format-efi, volume: partition-efi, fstype: fat32}
      - {type: format, id: format-boot, volume: partition-boot, fstype: ext4}
      - {type: mount, id: mount-efi, volume: format-efi, path: /boot/efi}
      - {type: mount, id: mount-boot, volume: format-boot, path: /boot}
      - {type: lvm_volgroup, id: vg-system, name: vg_system, devices: [partition-lvm]}
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
      - {type: lvm_partition, id: lv-sds, volgroup: vg-system, name: lv_sds, size: -1}
      - {type: format, id: fmt-root, volume: lv-root, fstype: ext4}
      - {type: mount, id: mnt-root, volume: fmt-root, path: /}
      - {type: format, id: fmt-var, volume: lv-var, fstype: ext4}
      - {type: mount, id: mnt-var, volume: fmt-var, path: /var}
      - {type: format, id: fmt-varlog, volume: lv-varlog, fstype: ext4}
      - {type: mount, id: mnt-varlog, volume: fmt-varlog, path: /var/log}
      - {type: format, id: fmt-metrics, volume: lv-metrics, fstype: ext4}
      - {type: mount, id: mnt-metrics, volume: fmt-metrics, path: /var/opt/buffered-metrics}
      - {type: format, id: fmt-containerd, volume: lv-containerd, fstype: ext4}
      - {type: mount, id: mnt-containerd, volume: fmt-containerd, path: /var/lib/containerd}
      - {type: format, id: fmt-etcd, volume: lv-etcd, fstype: ext4}
      - {type: mount, id: mnt-etcd, volume: fmt-etcd, path: /var/lib/etcd}
      - {type: format, id: fmt-etcd-events, volume: lv-etcd-events, fstype: ext4}
      - {type: mount, id: mnt-etcd-events, volume: fmt-etcd-events, path: /var/lib/etcd-events}
      - {type: format, id: fmt-gitea, volume: lv-gitea, fstype: ext4}
      - {type: mount, id: mnt-gitea, volume: fmt-gitea, path: /var/lib/gitea}
      - {type: format, id: fmt-nexus, volume: lv-nexus, fstype: ext4}
      - {type: mount, id: mnt-nexus, volume: fmt-nexus, path: /var/lib/nexus}
      - {type: format, id: fmt-localdisk, volume: lv-localdisk, fstype: ext4}
      - {type: mount, id: mnt-localdisk, volume: fmt-localdisk, path: /customer/local-disk}
      - {type: format, id: fmt-sds, volume: lv-sds, fstype: ext4}
      - {type: mount, id: mnt-sds, volume: fmt-sds, path: /customer/sds}
```

---

## 5. Verification Metrics & Schema Check
Before finalizing any installation profile, validators must run:
1. **Schema Check:** Run `cloud-init schema --config-file user-data` to confirm the autoinstall block compiles.
2. **Mount Verification:** Following bootstrap, verify active mounts and filesystem separation using `lsblk -f`.
