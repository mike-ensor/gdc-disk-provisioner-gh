# Longhorn Storage Prerequisites & Capability Benchmarking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete host-level OS prerequisites for Longhorn v1 and v2 engines (udev NVMe scheduler rules, multipath blacklisting, common/engine sysctl tunings, dynamic validation script) and implement the post-cluster CSI capability benchmarking utility (`kubestr fio`).

**Architecture:** Extend the `storage_prereqs` Ansible role with udev rules, multipath configuration, and dual-track sysctl (`v1` vs `v2`). Upgrade `validate-storage-prereqs.sh` to dynamic engine verification, integrate with `machine_orchestration` evidence collection, and provide `bin/cluster/run-storage-benchmark.py` for automated FIO metrics extraction.

**Tech Stack:** Ansible, Bash, Linux udev/sysctl/multipath, Python 3, pytest, `kubestr`, `kubectl`, `glab`.

---

### Task 1: Implement Common Baseline Host Prerequisites (udev, multipath, sysctl)

**Files:**
- Modify: `src/ansible/roles/storage_prereqs/defaults/main.yml`
- Modify: `src/ansible/roles/storage_prereqs/tasks/main.yml`
- Modify: `src/build/templates/user-data.j2:648-653`
- Modify: `test/test_storage_prereqs.py`

- [x] **Step 1: Write failing unit tests for udev rules, multipath blacklist, and common sysctl**

Update `test/test_storage_prereqs.py` with:
```python
    def test_storage_prereqs_common_baseline(self):
        """Verifies udev NVMe scheduler rules, multipath blacklist, and common sysctl."""
        role_tasks_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/storage_prereqs/tasks/main.yml"
        )
        with open(role_tasks_path, "r", encoding="utf-8") as f:
            content = f.read()

        # udev rule
        self.assertIn("60-nvme-longhorn.rules", content)
        self.assertIn("queue/scheduler", content)
        self.assertIn("queue/read_ahead_kb", content)
        self.assertIn("udevadm control --reload-rules", content)

        # multipath blacklist
        self.assertIn("longhorn.conf", content)
        self.assertIn('vendor "LONGHORN"', content)

        # common sysctl
        self.assertIn("90-longhorn-common.conf", content)
        self.assertIn("fs.file-max", content)
        self.assertIn("net.core.somaxconn", content)
```

- [x] **Step 2: Run test to verify it fails**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_prereqs.py::TestStoragePrereqs::test_storage_prereqs_common_baseline -v`
Expected: FAIL.

- [x] **Step 3: Update `src/ansible/roles/storage_prereqs/defaults/main.yml`**
Add variables:
```yaml
storage_udev_rules_file: /etc/udev/rules.d/60-nvme-longhorn.rules
storage_multipath_dir: /etc/multipath/conf.d
storage_multipath_file: /etc/multipath/conf.d/longhorn.conf
storage_common_sysctl_file: /etc/sysctl.d/90-longhorn-common.conf
storage_common_sysctl_parameters:
  - { name: "fs.file-max", value: "2097152" }
  - { name: "fs.inotify.max_user_watches", value: "524288" }
  - { name: "fs.inotify.max_user_instances", value: "8192" }
  - { name: "net.core.somaxconn", value: "32768" }
  - { name: "net.core.netdev_max_backlog", value: "16384" }
  - { name: "net.ipv4.tcp_max_syn_backlog", value: "16384" }
```

- [x] **Step 4: Update `src/ansible/roles/storage_prereqs/tasks/main.yml` and `src/build/templates/user-data.j2`**
Add tasks in `main.yml`:
1. Deploy `/etc/udev/rules.d/60-nvme-longhorn.rules` with:
```
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/scheduler}="none"
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/read_ahead_kb}="128"
```
and trigger `udevadm control --reload-rules && udevadm trigger --subsystem-match=block`.
2. Ensure `/etc/multipath/conf.d` directory exists and deploy `longhorn.conf`:
```
blacklist {
    devnode "^sd[a-z0-9]+"
    device {
        vendor "LONGHORN"
        product ".*"
    }
}
```
3. Deploy `/etc/sysctl.d/90-longhorn-common.conf` and apply `/sbin/sysctl -p /etc/sysctl.d/90-longhorn-common.conf`.
In `user-data.j2`, add the udev rule creation in Subiquity late-commands so bare-metal first-boot enforces the `none` scheduler.

- [x] **Step 5: Run tests to verify they pass**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_prereqs.py -v`
Expected: PASS.

- [x] **Step 6: Commit**
```bash
git add src/ansible/roles/storage_prereqs/ src/build/templates/user-data.j2 test/test_storage_prereqs.py
git commit -m "feat(storage): implement udev NVMe scheduler rules, multipath blacklist, and common sysctl"
```

---

### Task 2: Implement Engine-Specific Configuration (Track A v1 vs Track B v2)

**Files:**
- Modify: `src/ansible/roles/storage_prereqs/defaults/main.yml`
- Modify: `src/ansible/roles/storage_prereqs/tasks/main.yml`
- Modify: `test/test_storage_prereqs.py`

- [x] **Step 1: Write unit tests for v1 vs v2 engine selection**
Add `test_storage_prereqs_engine_tracks` in `test/test_storage_prereqs.py` asserting:
1. `storage_engine_mode` default is `"v2"`.
2. v1 parameters (`vm.dirty_ratio = 10`, `vm.dirty_background_ratio = 5`, `vm.nr_hugepages = 0`, `net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`) deployed to `/etc/sysctl.d/99-longhorn-engine.conf`.
3. v2 parameters (`vm.nr_hugepages = 2048`, `nvme-tcp`, `uio`, `uio_pci_generic`, `vfio_pci`) deployed when `storage_engine_mode == 'v2'`.

- [x] **Step 2: Run test to verify it fails**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_prereqs.py::TestStoragePrereqs::test_storage_prereqs_engine_tracks -v`
Expected: FAIL.

- [x] **Step 3: Update `defaults/main.yml` and `tasks/main.yml`**
Configure:
- `storage_engine_mode: "v2"`
- Track A tasks (`when: storage_engine_mode == 'v1'`): deploy `/etc/sysctl.d/99-longhorn-engine.conf` with v1 tunings, reload sysctl, ensure no hugepages.
- Track B tasks (`when: storage_engine_mode == 'v2'`): deploy `/etc/sysctl.d/99-longhorn-engine.conf` with `vm.nr_hugepages: 2048`, deploy `/etc/modules-load.d/longhorn-v2.conf`, modprobe modules.

- [x] **Step 4: Run tests to verify they pass**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_prereqs.py -v`
Expected: PASS.

- [x] **Step 5: Commit**
```bash
git add src/ansible/roles/storage_prereqs/ test/test_storage_prereqs.py
git commit -m "feat(storage): support dual-engine configuration for Longhorn v1 and v2"
```

---

### Task 3: Upgrade Verification Script and Orchestration Evidence Collection

**Files:**
- Modify: `src/ansible/roles/storage_prereqs/files/validate-storage-prereqs.sh`
- Modify: `src/ansible/roles/machine_orchestration/files/validate-storage-prereqs.sh`
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml:457-463,530-536`
- Modify: `test/test_storage_prereqs.py`

- [ ] **Step 1: Write test for upgraded `validate-storage-prereqs.sh` and orchestration evidence**
Update `test/test_storage_prereqs.py` to test:
- Bash syntax validation.
- All 5 sections (`iscsid`, `inotify`, NVMe schedulers, `/customer/sds`, and engine mode `$1`).
- Validation script supports `v1` and `v2` flags.

- [ ] **Step 2: Run test to verify it fails**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_prereqs.py -v`
Expected: FAIL.

- [ ] **Step 3: Replace `validate-storage-prereqs.sh` with the Issue #17 specification**
Update both files (`roles/storage_prereqs/files/` and `roles/machine_orchestration/files/`):
```shell
#!/usr/bin/env bash
set -eo pipefail

ENGINE_MODE="${1:-v2}" # Default to v2 if not supplied; pass "v1" or "v2"

echo "=== 1. Common: Checking iscsid Service ==="
if systemctl is-active --quiet iscsid; then
  echo "OK: iscsid is running"
else
  echo "FAIL: iscsid is inactive or missing"
  exit 1
fi

echo "=== 2. Common: Checking inotify Limits ==="
WATCHES=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo 0)
if [ "$WATCHES" -ge 524288 ]; then
  echo "OK: fs.inotify.max_user_watches = $WATCHES"
else
  echo "FAIL: fs.inotify.max_user_watches ($WATCHES) < 524288"
  exit 1
fi

echo "=== 3. Common: Checking NVMe Schedulers ==="
for dev in /sys/block/nvme*n1; do
  if [ -d "$dev" ]; then
    SCHED=$(cat "$dev/queue/scheduler" 2>/dev/null || true)
    echo "Device $(basename "$dev") scheduler: $SCHED"
  fi
done

echo "=== 4. Common: Checking Storage Directory ==="
if [ -d "/customer/sds" ]; then
  echo "OK: /customer/sds exists"
  df -h /customer/sds
else
  echo "FAIL: /customer/sds directory does not exist"
  exit 1
fi

echo "=== 5. Engine Verification ($ENGINE_MODE) ==="
HP=$(cat /proc/sys/vm/nr_hugepages 2>/dev/null || echo 0)

if [ "$ENGINE_MODE" == "v2" ]; then
  if [ "$HP" -ge 2048 ]; then
    echo "OK: HugePages = $HP (>= 2048)"
  else
    echo "FAIL: HugePages ($HP) < 2048 required for SPDK"
    exit 1
  fi

  REQUIRED_MODULES=("nvme_tcp" "uio" "uio_pci_generic" "vfio_pci")
  for mod in "${REQUIRED_MODULES[@]}"; do
    if [ -d "/sys/module/$mod" ] || lsmod | grep -q "^$mod "; then
      echo "OK: Module $mod is loaded"
    else
      echo "FAIL: Module $mod is not loaded"
      exit 1
    fi
  done
else
  if [ "$HP" -eq 0 ]; then
    echo "OK: HugePages disabled ($HP) for v1"
  else
    echo "WARN: HugePages is set to $HP; should be 0 for v1 to reclaim memory"
  fi
fi
```

- [ ] **Step 4: Update `machine_orchestration` evidence task**
In `src/ansible/roles/machine_orchestration/tasks/main.yml`:
- Pass engine mode: `/usr/local/bin/validate-storage-prereqs.sh {{ storage_engine_mode | default('v2') }}`
- Update evidence facts to extract `iscsid_active`, `inotify_verified`, `engine_mode_verified`, `sds_directory_present`, and `validation_status`.

- [ ] **Step 5: Run tests to verify they pass**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_prereqs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add src/ansible/roles/storage_prereqs/files/ src/ansible/roles/machine_orchestration/ test/test_storage_prereqs.py
git commit -m "feat(storage): align validation script and orchestration evidence with Issue #17"
```

---

### Task 4: Implement Storage Capability Validation & Benchmarking Utility (`run-storage-benchmark.py`)

**Files:**
- Create: `bin/cluster/run-storage-benchmark.py`
- Modify: `docs/BINARIES.md`
- Modify: `src/dependencies.env`
- Create: `test/test_storage_benchmark.py`

- [ ] **Step 1: Write unit tests for `run-storage-benchmark.py`**
Create `test/test_storage_benchmark.py` covering:
- Pre-flight guard: If `longhorn-system` namespace is missing or not fully running (unready/missing pods/components), safely skip `kubestr` execution with clear log and clean JSON status `SKIPPED_NOT_READY` or `NOT_INSTALLED`.
- CLI argument parsing (`--storage-class`, `--volume-size`, `--kubeconfig`, `--timeout`, `--json-output`, `--dry-run`, `--skip-guard`).
- Extraction of metrics schema fields (`Elapsed Time`, `Random Read IOPS`, `Random Read Bandwidth`, `Random Write IOPS`, `Random Write Bandwidth`, `Sequential Read IOPS`, `Sequential Read Bandwidth`, `Sequential Write IOPS`, `Sequential Write Bandwidth`, `Device Utilization`, `Health / Pass Status`).
- Verification that no dangling volumes or PVCs remain.

- [ ] **Step 2: Run test to verify it fails**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_benchmark.py -v`
Expected: FAIL (file not found).

- [ ] **Step 3: Implement `bin/cluster/run-storage-benchmark.py`**
Implement the benchmark orchestrator:
1. Architecture verification (`x86_64` / `amd64`).
2. Resolution of kubeconfig (`/etc/kubernetes/admin.conf`).
3. Pre-flight guard: Query Kubernetes API (`kubectl get ns longhorn-system`, check rollout/pod status of longhorn-manager/daemonset/deployments). If `longhorn-system` is not fully running or functional, log warning and write skipped status to JSON evidence (`status: SKIPPED`, `reason: longhorn-system not ready`), exiting gracefully without error.
4. Discovery of `kubestr` binary (in path or download if permitted).
5. Inspection of StorageClasses (`kubectl get sc -o json`).
6. Execution of `kubestr fio -s <sc> -z <size> --cleanup=true`.
7. Regex parsing and normalization of stdout metrics into Issue #17 schema.
8. Persistence of evidence to `/var/gdc-install/state/storage-benchmark.json` and stdout.

- [ ] **Step 4: Update `docs/BINARIES.md` and `src/dependencies.env`**
- Add `run-storage-benchmark.py` to `docs/BINARIES.md`.
- Add `KUBESTR_PACKAGE_URL` / `KUBESTR_VERSION` to `src/dependencies.env`.

- [ ] **Step 5: Run tests and ensure all pass**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/test_storage_benchmark.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add bin/cluster/run-storage-benchmark.py docs/BINARIES.md src/dependencies.env test/test_storage_benchmark.py
git commit -m "feat(storage): implement kubestr storage capability validation and benchmarking utility"
```

---

### Task 5: Full Integration Verification

**Files:**
- Entire repository

- [ ] **Step 1: Run complete test suite**
Run: `/d/projects/google/gdc-disk-provisioner/venv/bin/pytest test/ -q`
Expected: All tests pass.

- [ ] **Step 2: Run static syntax and bash linting**
Run:
```bash
bash -n src/ansible/roles/storage_prereqs/files/validate-storage-prereqs.sh
bash -n src/ansible/roles/machine_orchestration/files/validate-storage-prereqs.sh
python3 -m py_compile bin/cluster/run-storage-benchmark.py
```
Expected: Returncode 0.
