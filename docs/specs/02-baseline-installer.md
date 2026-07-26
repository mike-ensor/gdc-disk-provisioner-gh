# Specification: GDC Baseline Installer & Templated Storage Layouts

**Spec Identifier:** `GDC-SPEC-002`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Storage Architecture Team

---

## 1. Executive Summary & Purpose
This specification details the GDC Baseline OS installation phase. It outlines the bootloaders, the unattended Subiquity autoinstall configurations, and the exact GDC Bare Metal compliant Enterprise LVM disk layouts.

To eliminate the brittle shell-regex string replacements that corrupted Subiquity configs in previous builds, GDC implements a **Jinja2-based Declarative Templating Strategy**. Build configurations are hydrated cleanly at build-time using a unified Python rendering script. At install time, dynamic block scanning on the target allows the node to automatically size and layout LVM volumes depending on discovered disk counts, safely backing them with hardware-bound TPM 2.0 LUKS encryption.

---

## 2. Declarative Templating Strategy
To ensure 100% syntactical correctness and prevent indentation drift, all raw configuration payloads are stored as Jinja2 templates under `src/build/templates/` and compiled during the build phase:

```text
[ build.env / local.env ] ─┐
                           ├─> [ render_templates.py ] ──> [ Hydrated YAML configs ]
[ Jinja2 templates (.j2) ] ─┘
```

The template engine handles variables safely using native Python yaml serialization rather than raw text matching.

### 2.1. GRUB Bootloader & Kernel Command-Line Syntax Matrix (`/boot/grub/grub.cfg`)
To boot and install in fully automated or interactive environments, the Live CD GRUB bootloader presents three options with a 5-second timeout on both VGA and Serial (`ttyS0`) consoles:

```grub
set timeout=5
set default=0

serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1
terminal_input console serial
terminal_output console serial

menuentry "Google Distributed Cloud (GDC) Automated Installer [Default]" {
    set gfxpayload=keep
    echo "Booting GDC Unattended Installer..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 autoinstall "ds=nocloud;s=/cdrom/nocloud/" ip=dhcp apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp ---
    initrd /casper/initrd
}

menuentry "GDC Interactive Subiquity Installer (Manual Step-by-Step)" {
    set gfxpayload=keep
    echo "Booting GDC Interactive Installer..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp ---
    initrd /casper/initrd
}

menuentry "GDC Manual Rescue Shell (Interactive Terminal)" {
    set gfxpayload=keep
    echo "Booting GDC Manual Rescue Shell..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp init=/bin/sh ---
    initrd /casper/initrd
}
```

#### **GRUB Kernel Parameter Syntax Matrix**

| Environment | Primary Purpose | Mandatory Parameters | Module Blacklist (`modprobe.blacklist=...`) | Hardware Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Live CD (Installer / PXE)** | Unattended installation & disk partitioning | `console=tty1 console=ttyS0,115200 autoinstall apparmor=0 tpm_tis.interrupts=0` | `pcie_mp2_amd,amd_sfh,ccp` | Blacklists `ccp` during `Filesystem/_probe` to prevent PSP bus deadlocks when Subiquity scans existing encrypted LUKS drives. |
| **Installed Target OS** | Production Ready-Linux & TPM unsealing | `console=tty1 console=ttyS0,115200 systemd.log_level=debug rd.debug rd.shell tpm_tis.interrupts=0` | `pcie_mp2_amd,amd_sfh` *(Note: `ccp` ENABLED)* | Re-enables `ccp` so the AMD Secure Processor can manage CPU power/clock transitions without hanging at `1.6s`. |

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

---

## 4. Subiquity Autoinstall User-Data Template Integration

During target boot, the user-data template (`user-data.j2`) compiles with standard network parameters. Subiquity then executes target-side early-commands to dynamically merge LVM layouts:

```yaml
# Simplified segment of hydrated /nocloud/user-data
#cloud-config
autoinstall:
  version: 1
  identity:
    hostname: gdc-standalone-node
    username: temporary-installer
    password: "$6$rounds=4096$salt$calculated_hash"
  early-commands:
    # 1. Boot banner log
    - |
      if [ -f /cdrom/custom-data/boot-banner.txt ]; then
        cat /cdrom/custom-data/boot-banner.txt > /dev/ttyS0 2>/dev/null || true
        cat /cdrom/custom-data/boot-banner.txt
      fi
    # 2. Disk topological scanning and output creation
    - |
      cp /cdrom/custom-data/generate_storage_config.sh /tmp/generate_storage_config.sh
      chmod +x /tmp/generate_storage_config.sh
      /tmp/generate_storage_config.sh
    # 3. Dynamic YAML block merge
    - |
      python3 -c "
      import os, yaml
      base_path = '/cdrom/nocloud/user-data'
      if not os.path.exists(base_path):
          base_path = '/run/installer/autoinstall-user-data'
      with open(base_path, 'r') as f:
          c = yaml.safe_load(f)
      with open('/run/autoinstall-storage.yaml', 'r') as f:
          s = yaml.safe_load(f)
      c['autoinstall']['storage'] = s['storage']
      
      yaml.safe_dump({'autoinstall': c['autoinstall']}, open('/autoinstall.yaml', 'w'))
      os.makedirs('/run/installer', exist_ok=True)
      yaml.safe_dump(c, open('/run/installer/autoinstall-user-data', 'w'))
      "
```

---

## 5. Preflight Verification checklist
Before compiling any ISO, the **Validation Gate** (`make validate`) verifies these structures statically:
- [ ] Run `yamllint` on all hydrated files to assert structural compliance.
- [ ] Run `cloud-init schema` to verify Subiquity directives are error-free.
- [ ] Perform python syntactic audits on `render_templates.py`.
- [ ] Run `shellcheck` against `generate_storage_config.sh` and internal bash scripts.
