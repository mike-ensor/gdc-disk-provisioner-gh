# Specification: GDC LVM Disk Layout Sizing Updates

**Spec Identifier:** `GDC-SPEC-2026-09-28-LVM-SIZING`  
**Status:** APPROVED  
**Date:** 2026-09-28  
**Author:** GDC Core Platform Engineering  

---

## 1. Executive Summary

In Google Distributed Cloud (GDC) Bare Metal installations, storage isolation is critical to satisfy preflight requirements and protect latency-sensitive services like `etcd` from write contention. 

This specification establishes updated capacity allocations for key Logical Volumes:
1. **`lv_var_log` (Log Volume):** Increased from `15G` to **`100G`** across all topologies to support expanded systemd-journald and Fluent-bit log buffering.
2. **`lv_nexus` (Nexus Mirror & OCI Cache):**
   * **Single-Disk Topology:** Fixed at **`300G`** (increased from `50G`).
   * **Dual-Disk Topology:** Allocated **`size: -1`** ("rest of disk"), consuming the full remaining unallocated space of Disk 1 (`vg_system`), with the guarantee that compliant drives provide $\ge$ **`300G`**.
3. **`lv_sds` (Customer Software-Defined Storage):** Confirmed and preserved with **`size: -1`** across all topologies, automatically claiming 100% of remaining free space without requiring manual subtraction.
4. **Drive Capacity Validation:** Enforces a minimum sector threshold in `src/build/generate_storage_config.sh` and expands test harness image sizing to ensure single- and dual-disk environments accommodate the larger footprints without storage exhaustion.

---

## 2. Capacity Analysis & Sizing Rules

### 2.1. Single-Disk Topology

In a single-disk topology, all operating system partitions, container runtimes, and customer volumes share a single physical NVMe/SSD drive formatted with the Volume Group `vg_system`.

#### Fixed Logical Volumes (`vg_system`)
| Logical Volume | Mount Point | New Size | Previous Size | Filesystem | Mount Options |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `lv_root` | `/` | 15 GiB | 15 GiB | EXT4 | `defaults` |
| `lv_var` | `/var` | 25 GiB | 25 GiB | EXT4 | `defaults,noatime` |
| **`lv_var_log`** | `/var/log` | **100 GiB** | 15 GiB | EXT4 | `defaults,noatime` |
| `lv_var_opt_metrics` | `/var/opt/buffered-metrics` | 12 GiB (10 GiB in j2) | 12 GiB | EXT4 | `defaults,noatime` |
| `lv_containerd` | `/var/lib/containerd` | 33 GiB (30 GiB in j2) | 33 GiB | XFS | `defaults,noatime,prjquota` |
| `lv_etcd` | `/var/lib/etcd` | 22 GiB (20 GiB in j2) | 22 GiB | EXT4 | `noatime,nodiratime,commit=1` |
| `lv_etcd_events` | `/var/lib/etcd-events` | 7 GiB (5 GiB in j2) | 7 GiB | EXT4 | `noatime,nodiratime,commit=1` |
| `lv_gitea` | `/var/lib/gitea` | 15 GiB | 15 GiB | EXT4 | `defaults,noatime` |
| **`lv_nexus`** | `/var/lib/nexus` | **300 GiB** | 50 GiB | EXT4 | `defaults,noatime` |
| `lv_local_disk` | `/customer/local-disk` | 25 GiB | 25 GiB | XFS | `defaults,noatime,prjquota` |
| **`lv_sds`** | `/customer/sds` | **`size: -1`** | `size: -1` | XFS | `defaults,noatime` |

* **Total Fixed LVs:** $15 + 25 + 100 + 12 + 33 + 22 + 7 + 15 + 300 + 25 = 554\text{ GiB}$.
* **Boot & EFI Overhead:** ~3 GiB (1 GiB EFI + 2 GiB `/boot`).
* **Base Required Disk Footprint:** ~557 GiB.
* **Customer SDS Allocation:** All remaining extents beyond 557 GiB are dynamically mapped to `lv_sds`.
* **Minimum Physical Drive Requirement:** $\ge 600\text{ GB}$ (recommended $\ge 1\text{ TB}$) so `lv_sds` has usable persistent storage.

---

### 2.2. Dual-Disk Topology

In a dual-disk topology, system and customer workloads are physically isolated across two separate drives.

#### Disk 1: System Volume Group (`vg_system`)
| Logical Volume | Mount Point | New Size | Previous Size | Filesystem | Mount Options |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `lv_root` | `/` | 20 GiB | 20 GiB | EXT4 | `defaults` |
| `lv_var` | `/var` | 25 GiB | 25 GiB | EXT4 | `defaults,noatime` |
| **`lv_var_log`** | `/var/log` | **100 GiB** | 15 GiB | EXT4 | `defaults,noatime` |
| `lv_var_opt_metrics` | `/var/opt/buffered-metrics` | 12 GiB (10 GiB in j2) | 12 GiB | EXT4 | `defaults,noatime` |
| `lv_containerd` | `/var/lib/containerd` | 33 GiB (30 GiB in j2) | 33 GiB | XFS | `defaults,noatime,prjquota` |
| `lv_etcd` | `/var/lib/etcd` | 22 GiB (20 GiB in j2) | 22 GiB | EXT4 | `noatime,nodiratime,commit=1` |
| `lv_etcd_events` | `/var/lib/etcd-events` | 7 GiB (5 GiB in j2) | 7 GiB | EXT4 | `noatime,nodiratime,commit=1` |
| `lv_gitea` | `/var/lib/gitea` | 20 GiB | 20 GiB | EXT4 | `defaults,noatime` |
| **`lv_nexus`** | `/var/lib/nexus` | **`size: -1`** | `size: -1` | EXT4 | `defaults,noatime` |

* **Total Fixed LVs on Disk 1:** $20 + 25 + 100 + 12 + 33 + 22 + 7 + 20 = 239\text{ GiB}$.
* **Boot & EFI Overhead:** ~3 GiB.
* **Base Required Disk Footprint before Nexus:** 242 GiB.
* **Nexus Guarantee ($\ge 300\text{ GiB}$):** Because `lv_nexus` consumes `size: -1` on Disk 1, Disk 1 must be $\ge 542\text{ GiB}$ (e.g. $\ge 600\text{ GB}$ or $1\text{ TB}$) to guarantee Nexus receives at least 300 GiB.

#### Disk 2: Data Volume Group (`vg_data`)
| Logical Volume | Mount Point | New Size | Previous Size | Filesystem | Mount Options |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `lv_local_disk` | `/customer/local-disk` | 100 GiB | 100 GiB | XFS | `defaults,noatime,prjquota` |
| **`lv_sds`** | `/customer/sds` | **`size: -1`** | `size: -1` | XFS | `defaults,noatime` |

* **Customer SDS Allocation:** All remaining extents on Disk 2 beyond the 100 GiB `lv_local_disk` boundary are dynamically claimed by `lv_sds`.

---

## 3. Implementation Details

### 3.1. Template Modifications
The following template files will be updated with the new sizing specifications:
1. `src/build/templates/storage/storage_config_bios_single.yaml`:
   - `lv-varlog`: `size: 100G`
   - `lv-nexus`: `size: 300G`
   - `lv-sds`: `size: -1`
2. `src/build/templates/storage/storage_config_uefi_single.yaml`:
   - `lv-varlog`: `size: 100G`
   - `lv-nexus`: `size: 300G`
   - `lv-sds`: `size: -1`
3. `src/build/templates/storage/storage_config_bios_dual.yaml`:
   - `lv-varlog`: `size: 100G`
   - `lv-nexus`: `size: -1`
   - `lv-sds`: `size: -1`
4. `src/build/templates/storage/storage_config_uefi_dual.yaml`:
   - `lv-varlog`: `size: 100G`
   - `lv-nexus`: `size: -1`
   - `lv-sds`: `size: -1`
5. `src/build/templates/storage_config.j2`:
   - Single disk section: `lv-varlog` to `100G`, `lv-nexus` to `300G`, `lv-sds` to `-1`.
   - Dual disk section: `lv-varlog` to `100G`, `lv-nexus` to `-1`, `lv-sds` to `-1`.

### 3.2. Dynamic Sizing Enforcement (`generate_storage_config.sh`)
* Update disk size detection heuristic:
  * Minimum disk sector threshold updated to reflect the new sizing baseline ($560\text{ GiB} = 1,174,405,120\text{ sectors}$ of 512 bytes).
  * Informative warning and failure reporting if target drives are under 560 GiB.

### 3.3. Test Harness & Mock Alignment
* `test/run_qemu_e2e.sh`: Update `TEMP_DISK_1` sparse creation from `250G` to `600G` (or `1000G`), ensuring end-to-end tests provide $\ge 300\text{ GiB}$ for `lv_nexus`.
* `test/bin/run-qemu-detached.sh`: Update QEMU system disk from `250G` to `600G`.
* `test/test_storage_discovery.py`: Ensure mock sector counts for internal drives reflect $\ge 600\text{ GB}$ drives (`1258291200` sectors).

### 3.4. Documentation Updates
* `docs/DISKS.md`: Reflect the new sizing tables, scaling rules, and minimum disk sizes ($\ge 600\text{ GB}$ / $1\text{ TB}$).
* `DICTIONARY.md`: Update `lv_var_log` (100 GiB) and `lv_nexus` (300 GiB / remainder).
* `docs/specs/02-baseline-installer.md`: Align baseline LVM partition map with the new allocations.

---

## 4. Verification & Testing Criteria

1. **Jinja2 Hydration & YAML Syntax Tests:**
   * Run `python3 -m unittest test/test_template_hydration.py` to confirm all single/dual and BIOS/UEFI combinations render valid YAML with the new sizes.
2. **Storage Discovery Tests:**
   * Run `python3 -m unittest test/test_storage_discovery.py` to confirm disk filtering, sorting, and template selection logic works as expected.
3. **Storage Prerequisites Tests:**
   * Run `python3 -m unittest test/test_storage_prereqs.py` to verify that Longhorn and `/customer/sds` preconditions are satisfied.
4. **Shell Syntax Checks:**
   * Validate modified shell scripts with `bash -n`.
