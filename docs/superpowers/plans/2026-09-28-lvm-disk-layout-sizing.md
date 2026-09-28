# LVM Disk Layout Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update GDC Bare Metal storage layout templates and discovery logic to allocate 100GB to `/var/log` (`lv_var_log`), 300GB to Nexus (`lv_nexus`) on single-disk setups, "rest of disk" (`size: -1`) to Nexus on dual-disk setups, and confirm customer SDS (`lv_sds`) dynamically consumes the remainder of the disk (`size: -1`).

**Architecture:** Modify the static and dynamic YAML/Jinja2 Subiquity storage configuration templates to set the updated logical volume sizes. Update `generate_storage_config.sh` to enforce drive capacity thresholds ($\ge 560\text{ GiB}$) so undersized drives fail fast with clear diagnostics. Update the QEMU test harness and documentation to reflect the new sizing baseline.

**Tech Stack:** Bash, Jinja2, YAML, Python (`unittest`), Curtin / Subiquity LVM specifications.

---

### Task 1: Update Storage Templates with New LVM Sizing

**Files:**
- Modify: `src/build/templates/storage/storage_config_bios_single.yaml:14-25`
- Modify: `src/build/templates/storage/storage_config_uefi_single.yaml:16-27`
- Modify: `src/build/templates/storage/storage_config_bios_dual.yaml:18-28`
- Modify: `src/build/templates/storage/storage_config_uefi_dual.yaml:20-30`
- Modify: `src/build/templates/storage_config.j2:25-37,66-77`
- Test: `test/test_template_hydration.py`

- [ ] **Step 1: Write unit tests in `test/test_template_hydration.py` verifying new LVM partition sizes**

Add `test_storage_config_lvm_partition_sizes` in `test/test_template_hydration.py`:

```python
    def test_storage_config_lvm_partition_sizes(self):
        """Verifies updated LVM sizes: lv_var_log=100G, single lv_nexus=300G, dual lv_nexus=-1, lv_sds=-1."""
        storage_dir = os.path.join(self.template_dir, "storage")
        
        # Test Single Disk Templates (BIOS & UEFI)
        for single_file in ["storage_config_bios_single.yaml", "storage_config_uefi_single.yaml"]:
            with open(os.path.join(storage_dir, single_file), "r") as f:
                content = f.read().replace("${DISK_1}", "vda")
            parsed = yaml.safe_load(content)
            lvs = {item["name"]: str(item.get("size")) for item in parsed["config"] if item.get("type") == "lvm_partition"}
            self.assertEqual(lvs.get("lv_var_log"), "100G", f"{single_file} lv_var_log must be 100G")
            self.assertEqual(lvs.get("lv_nexus"), "300G", f"{single_file} lv_nexus must be 300G")
            self.assertEqual(lvs.get("lv_sds"), "-1", f"{single_file} lv_sds must be -1")

        # Test Dual Disk Templates (BIOS & UEFI)
        for dual_file in ["storage_config_bios_dual.yaml", "storage_config_uefi_dual.yaml"]:
            with open(os.path.join(storage_dir, dual_file), "r") as f:
                content = f.read().replace("${DISK_1}", "vda").replace("${DISK_2}", "vdb")
            parsed = yaml.safe_load(content)
            lvs = {item["name"]: str(item.get("size")) for item in parsed["config"] if item.get("type") == "lvm_partition"}
            self.assertEqual(lvs.get("lv_var_log"), "100G", f"{dual_file} lv_var_log must be 100G")
            self.assertEqual(lvs.get("lv_nexus"), "-1", f"{dual_file} lv_nexus must be -1")
            self.assertEqual(lvs.get("lv_sds"), "-1", f"{dual_file} lv_sds must be -1")

        # Test Jinja2 storage_config.j2 hydration
        template = self.jinja_env.get_template("storage_config.j2")
        
        # Single disk context
        ctx_single = self.get_context({'SINGLE_DISK': 'true'})
        rendered_single = template.render(ctx_single)
        parsed_single = yaml.safe_load(rendered_single)
        lvs_single = {item["name"]: str(item.get("size")) for item in parsed_single["config"] if item.get("type") == "lvm_partition"}
        self.assertEqual(lvs_single.get("lv_var_log"), "100G", "storage_config.j2 single lv_var_log must be 100G")
        self.assertEqual(lvs_single.get("lv_nexus"), "300G", "storage_config.j2 single lv_nexus must be 300G")
        self.assertEqual(lvs_single.get("lv_sds"), "-1", "storage_config.j2 single lv_sds must be -1")

        # Dual disk context
        ctx_dual = self.get_context({'SINGLE_DISK': 'false'})
        rendered_dual = template.render(ctx_dual)
        parsed_dual = yaml.safe_load(rendered_dual)
        lvs_dual = {item["name"]: str(item.get("size")) for item in parsed_dual["config"] if item.get("type") == "lvm_partition"}
        self.assertEqual(lvs_dual.get("lv_var_log"), "100G", "storage_config.j2 dual lv_var_log must be 100G")
        self.assertEqual(lvs_dual.get("lv_nexus"), "-1", "storage_config.j2 dual lv_nexus must be -1")
        self.assertEqual(lvs_dual.get("lv_sds"), "-1", "storage_config.j2 dual lv_sds must be -1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_template_hydration.py -k test_storage_config_lvm_partition_sizes`
Expected: FAIL (`AssertionError: '15G' != '100G'`)

- [ ] **Step 3: Update template files**

1. In `src/build/templates/storage/storage_config_bios_single.yaml`:
   - Change `lv_var_log` size from `15G` to `100G`
   - Change `lv_nexus` size from `50G` to `300G`
   - Ensure `lv_sds` size is `-1`
   - Update comment: `# Scaled Logical Volumes for Single Disk (Total requested: ~554 G)`

2. In `src/build/templates/storage/storage_config_uefi_single.yaml`:
   - Change `lv_var_log` size from `15G` to `100G`
   - Change `lv_nexus` size from `50G` to `300G`
   - Ensure `lv_sds` size is `-1`
   - Update comment: `# Scaled Logical Volumes for Single Disk (Total requested: ~554 G)`

3. In `src/build/templates/storage/storage_config_bios_dual.yaml`:
   - Change `lv_var_log` size from `15G` to `100G`
   - Ensure `lv_nexus` size is `-1`
   - Ensure `lv_sds` size is `-1`

4. In `src/build/templates/storage/storage_config_uefi_dual.yaml`:
   - Change `lv_var_log` size from `15G` to `100G`
   - Ensure `lv_nexus` size is `-1`
   - Ensure `lv_sds` size is `-1`

5. In `src/build/templates/storage_config.j2`:
   - Single disk section: `lv_var_log` to `100G`, `lv_nexus` to `300G`, `lv_sds` to `-1`
   - Dual disk section: `lv_var_log` to `100G`, `lv_nexus` to `-1`, `lv_sds` to `-1`

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_template_hydration.py`
Expected: ALL PASS

- [ ] **Step 5: Commit template updates**

```bash
git add src/build/templates/storage/ test/test_template_hydration.py src/build/templates/storage_config.j2
git commit -m "feat(storage): bump lv_var_log to 100G and lv_nexus to 300G/rest of disk"
```

---

### Task 2: Update Storage Discovery Minimum Disk Threshold

**Files:**
- Modify: `src/build/generate_storage_config.sh:66,138-144`
- Modify: `test/test_storage_discovery.py:180-185`
- Test: `test/test_storage_discovery.py`

- [ ] **Step 1: Write failing test / update mock sizes in `test/test_storage_discovery.py`**

In `test/test_storage_discovery.py`:
- In `test_generate_storage_config_dual_disk_with_usb_installer`:
  - Update `sdb` (USB installer) to `536870912` (256GB).
  - Update `nvme0n1` to `2000409600` sectors (~1TB NVMe Disk 1).
  - Update `nvme1n1` to `4000819200` sectors (~2TB NVMe Disk 2).
- Add a new test: `test_generate_storage_config_skips_undersized_disks`:
  - Create a mock disk `nvme0n1` with size 250GB (503316480 sectors) and assert it is skipped as undersized in stderr.

- [ ] **Step 2: Run test to verify behavior**

Run: `python3 -m unittest test/test_storage_discovery.py -k test_generate_storage_config_skips_undersized_disks`
Expected: FAIL because 503316480 was previously considered valid ($\ge 240\text{ GB}$).

- [ ] **Step 3: Update `src/build/generate_storage_config.sh`**

Update disk sector requirement from 240 GB (`503316480` sectors) to 560 GiB (`1174405120` sectors of 512 bytes):
```bash
    # Get sector size of block device
    if [[ -f "/sys/block/${disk}/size" ]]; then
        SECTORS=$(cat "/sys/block/${disk}/size")
        # 560 GiB = 1174405120 sectors (512-byte blocks) to guarantee 100GB logs and 300GB+ Nexus
        if [[ ${SECTORS} -ge 1174405120 ]]; then
            DETECTED_DISKS+=("${disk}")
        else
            echo "[-] Skipping undersized disk: /dev/${disk} (${SECTORS} sectors < 1174405120)" >&2
        fi
    fi
```
Update line 66:
```bash
log_goal "Scanning hardware block devices for GDC-compliant storage drives (>= 560 GiB / 600 GB)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_storage_discovery.py`
Expected: PASS

- [ ] **Step 5: Commit discovery updates**

```bash
git add src/build/generate_storage_config.sh test/test_storage_discovery.py
git commit -m "feat(storage): increase minimum compliant disk size threshold to 560 GiB"
```

---

### Task 3: Update QEMU Test Harness and Detached Runner

**Files:**
- Modify: `test/run_qemu_e2e.sh:129,185`
- Modify: `test/bin/run-qemu-detached.sh:18`
- Test: Shell syntax validation (`bash -n`)

- [ ] **Step 1: Check existing scripts for disk sizes**

Verify:
- `test/run_qemu_e2e.sh` line 129: `qemu-img create -f qcow2 /tmp/gdc-sys-disk.qcow2 250G`
- `test/run_qemu_e2e.sh` line 185: `qemu-img create -f qcow2 "${TEMP_DISK_1}" 250G`
- `test/bin/run-qemu-detached.sh` line 18: `qemu-img create -f qcow2 /tmp/gdc-qemu-sys.qcow2 250G`

- [ ] **Step 2: Update sparse image size in test harnesses**

Update `TEMP_DISK_1` from `250G` to `650G` (sparse qcow2 takes negligible real disk space upon creation, but presents a 650 GiB virtual disk satisfying the 560 GiB sector threshold and guaranteeing $> 300\text{ GiB}$ for `lv_nexus`).
1. In `test/run_qemu_e2e.sh`:
   - Line 129: Update help message to `650G`.
   - Line 184-185: Update creation log to `650 GiB` and size argument to `650G`.
2. In `test/bin/run-qemu-detached.sh`:
   - Line 18: Update size argument to `650G`.

- [ ] **Step 3: Run shell syntax check**

Run: `bash -n test/run_qemu_e2e.sh test/bin/run-qemu-detached.sh`
Expected: Exit code 0 (valid syntax).

- [ ] **Step 4: Commit test harness updates**

```bash
git add test/run_qemu_e2e.sh test/bin/run-qemu-detached.sh
git commit -m "test(qemu): expand system validation disk size to 650G for LVM requirements"
```

---

### Task 4: Update Documentation and Technical References

**Files:**
- Modify: `docs/DISKS.md`
- Modify: `DICTIONARY.md`
- Modify: `docs/specs/02-baseline-installer.md`

- [ ] **Step 1: Update `docs/DISKS.md`**

1. Section 2 (Disk Detection & Filtering Heuristics):
   - Update size filtering: capacity $\ge 560\text{ GiB}$ ($1,174,405,120$ sectors).
2. Section 3 (Dynamic Topology & Scaling Rules):
   - Single-Disk: Update `lv_var_log` to **100 GiB**, `lv_nexus` to **300 GiB**, and note minimum single-disk requirement $\ge 600\text{ GB}$.
   - Dual-Disk: Note `lv_var_log` is **100 GiB** and `lv_nexus` consumes the full remainder of Disk 1 (`size: -1`, guaranteed $\ge 300\text{ GiB}$ on compliant drives).
3. Section 4 (LVM Storage Layout & Partition Map tables):
   - In `vg_system` table: Update `lv_var_log` Default Size to **100 GiB** and note `lv_nexus` is **300 GiB** (Single-Disk) / **Remainder** (Dual-Disk).

- [ ] **Step 2: Update `DICTIONARY.md`**

1. Update `lv_var_log`: `100 GiB — Fluent-bit and system log isolation.`
2. Update `lv_nexus`: `300 GiB (single-disk) or remainder (dual-disk) — Local Nexus caching registries and blob stores.`

- [ ] **Step 3: Update `docs/specs/02-baseline-installer.md`**

1. In LVM layout table: Update `lv_var_log` to `100 GiB` and `lv_nexus` to `300 GiB (single) / Remainder (dual)`.

- [ ] **Step 4: Commit documentation updates**

```bash
git add docs/DISKS.md DICTIONARY.md docs/specs/02-baseline-installer.md
git commit -m "docs(storage): update LVM sizing specifications for lv_var_log and lv_nexus"
```

---

### Task 5: Final Full Regression Test Suite

**Files:**
- Test: All test suites in `test/`

- [ ] **Step 1: Run all unit and integration tests**

Run: `python3 -m unittest discover -s test -p "test_*.py"`
Expected: All tests pass with 0 failures or errors.

- [ ] **Step 2: Verify git status is clean**

Run: `git status`
Expected: Working tree clean on branch `feature/lvm-disk-layout-sizing`.
