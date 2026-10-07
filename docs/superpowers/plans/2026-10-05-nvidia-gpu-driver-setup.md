# Automated NVIDIA GPU Driver & Toolkit Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automated, gated NVIDIA GPU driver, container toolkit, persistence daemon, and clock locking setup for GDC bare-metal nodes during the LinuxReady provisioning stage.

**Architecture:** A dedicated Ansible role `src/ansible/roles/nvidia_gpu` probes the host's PCI bus for NVIDIA display/compute devices (`vendor 0x10de`). If absent (e.g. `192.168.9.242`), the role skips all operations instantly. If present (e.g. `192.168.9.238`), it blacklists `nouveau`, rebuilds initramfs with `dracut -f`, installs headless server drivers and container toolkit from the local Nexus repository, deploys `nvidia-persistenced.service` with inference memory clock locking (`nvidia-smi -lmc`), and flags `/var/run/reboot-required` so GDC's Stage 4.5 executes a clean reboot into the active NVIDIA driver before `ClusterReady`.

**Tech Stack:** Python 3.12, Ansible, Jinja2, Pytest, Ubuntu 24.04 LTS, systemd, dracut, NVIDIA server drivers & toolkit.

---

### File Structure Map

- **Test Suite:**
  - Create: `test/test_nvidia_gpu.py` (Unit tests verifying role structure, packages config, template rendering, detection parsing, and stage integration)
- **Offline ISO & Build Caching:**
  - Modify: `src/build/packages_config.yaml:73-75` (Add GPU packages to `customer_added`)
- **Global Variables:**
  - Modify: `src/ansible/vars/all.yml` & `src/ansible/vars/all.yml.j2` (Add driver package and clock lock variables)
- **Ansible Role `nvidia_gpu`:**
  - Create: `src/ansible/roles/nvidia_gpu/defaults/main.yml` (Default variables)
  - Create: `src/ansible/roles/nvidia_gpu/templates/blacklist-nouveau.conf.j2` (Modprobe blacklist configuration)
  - Create: `src/ansible/roles/nvidia_gpu/templates/nvidia-persistenced.service.j2` (Systemd persistence unit)
  - Create: `src/ansible/roles/nvidia_gpu/tasks/main.yml` (Entrypoint with PCI probe and gate)
  - Create: `src/ansible/roles/nvidia_gpu/tasks/detect.yml` (PCI bus scanning & fact setting)
  - Create: `src/ansible/roles/nvidia_gpu/tasks/blacklist_nouveau.yml` (Modprobe blacklisting & dracut initramfs regeneration)
  - Create: `src/ansible/roles/nvidia_gpu/tasks/install_driver.yml` (Apt package installation)
  - Create: `src/ansible/roles/nvidia_gpu/tasks/configure_persistence.yml` (Systemd persistence daemon & memory clock lock)
  - Create: `src/ansible/roles/nvidia_gpu/tasks/collect_evidence.yml` (LinuxReady evidence recording)
- **Stage Integration:**
  - Modify: `src/ansible/stages/stage_linux_ready.yml` (Invoke `nvidia_gpu` role and inject evidence)

---

### Task 1: Package Configuration & Dependency Caching

**Files:**
- Create: `test/test_nvidia_gpu.py`
- Modify: `src/build/packages_config.yaml:73-76`

- [ ] **Step 1: Write the failing test for packages_config**

```python
#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for automated NVIDIA GPU driver and container toolkit provisioning."""

import os
import unittest
import yaml
from jinja2 import Environment

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestNvidiaGPU(unittest.TestCase):
    """Verifies NVIDIA GPU package declarations, Ansible role structure, and stage integration."""

    def test_packages_config_contains_gpu_packages(self):
        """Verifies packages_config.yaml declares NVIDIA drivers and container toolkit for offline caching."""
        config_path = os.path.join(PROJECT_ROOT, "src/build/packages_config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        packages = set(cfg.get("packages_to_include", {}).get("customer_added", []))
        self.assertIn("nvidia-driver-580-server", packages, "Missing 'nvidia-driver-580-server' in packages_config.yaml customer_added")
        self.assertIn("nvidia-utils-580-server", packages, "Missing 'nvidia-utils-580-server' in packages_config.yaml customer_added")
        self.assertIn("nvidia-container-toolkit", packages, "Missing 'nvidia-container-toolkit' in packages_config.yaml customer_added")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_packages_config_contains_gpu_packages -v`
Expected: FAIL with `AssertionError: Missing 'nvidia-driver-580-server' in packages_config.yaml customer_added`

- [ ] **Step 3: Modify `src/build/packages_config.yaml`**

In `src/build/packages_config.yaml`, update `customer_added`:

```yaml
  # Optional packages specified by the customer/operator for target environments
  customer_added:
    - "nvidia-driver-580-server"
    - "nvidia-utils-580-server"
    - "nvidia-container-toolkit"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_packages_config_contains_gpu_packages -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test/test_nvidia_gpu.py src/build/packages_config.yaml
git commit -m "feat(build): add NVIDIA driver and toolkit packages to offline cache config"
```

---

### Task 2: Global Configuration Variables

**Files:**
- Modify: `src/ansible/vars/all.yml`
- Modify: `src/ansible/vars/all.yml.j2`
- Test: `test/test_nvidia_gpu.py`

- [ ] **Step 1: Write the failing test for vars/all.yml**

Add to `test/test_nvidia_gpu.py`:

```python
    def test_vars_all_nvidia_settings(self):
        """Verifies vars/all.yml and vars/all.yml.j2 define required NVIDIA GPU provisioning variables."""
        for filename in ("all.yml", "all.yml.j2"):
            vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars", filename)
            with open(vars_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("nvidia_driver_package: \"nvidia-driver-580-server\"", content, f"{filename} missing nvidia_driver_package")
            self.assertIn("nvidia_utils_package: \"nvidia-utils-580-server\"", content, f"{filename} missing nvidia_utils_package")
            self.assertIn("nvidia_gpu_enable_persistence: true", content, f"{filename} missing nvidia_gpu_enable_persistence")
            self.assertIn("nvidia_gpu_lock_memory_clock: true", content, f"{filename} missing nvidia_gpu_lock_memory_clock")
            self.assertIn("nvidia_gpu_memory_clock_mhz: 7000", content, f"{filename} missing nvidia_gpu_memory_clock_mhz")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_vars_all_nvidia_settings -v`
Expected: FAIL with `AssertionError: all.yml missing nvidia_driver_package`

- [ ] **Step 3: Modify `src/ansible/vars/all.yml` and `src/ansible/vars/all.yml.j2`**

Append the following configuration block to both `src/ansible/vars/all.yml` and `src/ansible/vars/all.yml.j2`:

```yaml
# ==============================================================================
# NVIDIA GPU Provisioning Configuration
# ==============================================================================
# Target driver packages
nvidia_driver_package: "nvidia-driver-580-server"
nvidia_utils_package: "nvidia-utils-580-server"

# Persistence & Performance Tuning
nvidia_gpu_enable_persistence: true
nvidia_gpu_lock_memory_clock: true
nvidia_gpu_memory_clock_mhz: 7000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_vars_all_nvidia_settings -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/vars/all.yml src/ansible/vars/all.yml.j2 test/test_nvidia_gpu.py
git commit -m "feat(ansible): define global NVIDIA GPU driver and tuning variables"
```

---

### Task 3: NVIDIA GPU Ansible Role Structure & Templates

**Files:**
- Create: `src/ansible/roles/nvidia_gpu/defaults/main.yml`
- Create: `src/ansible/roles/nvidia_gpu/templates/blacklist-nouveau.conf.j2`
- Create: `src/ansible/roles/nvidia_gpu/templates/nvidia-persistenced.service.j2`
- Test: `test/test_nvidia_gpu.py`

- [ ] **Step 1: Write the failing tests for role structure and template rendering**

Add to `test/test_nvidia_gpu.py`:

```python
    def test_nvidia_gpu_role_structure(self):
        """Verifies the nvidia_gpu role directory, defaults, templates, and task files exist."""
        role_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/nvidia_gpu")
        self.assertTrue(os.path.isdir(role_dir), "Role directory src/ansible/roles/nvidia_gpu does not exist")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "defaults/main.yml")), "Missing defaults/main.yml")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "templates/blacklist-nouveau.conf.j2")), "Missing blacklist-nouveau.conf.j2")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "templates/nvidia-persistenced.service.j2")), "Missing nvidia-persistenced.service.j2")

    def test_nvidia_gpu_template_rendering(self):
        """Verifies blacklist-nouveau.conf.j2 and nvidia-persistenced.service.j2 render expected directives."""
        role_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/nvidia_gpu")
        env = Environment()

        # Render blacklist-nouveau.conf.j2
        with open(os.path.join(role_dir, "templates/blacklist-nouveau.conf.j2"), "r", encoding="utf-8") as f:
            blacklist_tmpl = env.from_string(f.read())
        rendered_blacklist = blacklist_tmpl.render()
        self.assertIn("blacklist nouveau", rendered_blacklist)
        self.assertIn("options nouveau modeset=0", rendered_blacklist)
        self.assertIn("alias nouveau off", rendered_blacklist)

        # Render nvidia-persistenced.service.j2 with clock lock
        with open(os.path.join(role_dir, "templates/nvidia-persistenced.service.j2"), "r", encoding="utf-8") as f:
            service_tmpl = env.from_string(f.read())
        rendered_service_locked = service_tmpl.render({
            "nvidia_gpu_lock_memory_clock": True,
            "nvidia_gpu_memory_clock_mhz": 7000
        })
        self.assertIn("ExecStart=/usr/bin/nvidia-persistenced --user root", rendered_service_locked)
        self.assertIn("ExecStartPost=/usr/bin/nvidia-smi -lmc 7000", rendered_service_locked)
        self.assertIn("Before=containerd.service kubelet.service", rendered_service_locked)

        # Render nvidia-persistenced.service.j2 without clock lock
        rendered_service_unlocked = service_tmpl.render({
            "nvidia_gpu_lock_memory_clock": False,
            "nvidia_gpu_memory_clock_mhz": 7000
        })
        self.assertNotIn("ExecStartPost=", rendered_service_unlocked)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_nvidia_gpu_role_structure -v`
Expected: FAIL with `AssertionError: Role directory src/ansible/roles/nvidia_gpu does not exist`

- [ ] **Step 3: Create defaults and templates**

Create `src/ansible/roles/nvidia_gpu/defaults/main.yml`:
```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

nvidia_driver_package: "nvidia-driver-580-server"
nvidia_utils_package: "nvidia-utils-580-server"
nvidia_gpu_enable_persistence: true
nvidia_gpu_lock_memory_clock: true
nvidia_gpu_memory_clock_mhz: 7000
```

Create `src/ansible/roles/nvidia_gpu/templates/blacklist-nouveau.conf.j2`:
```ini
# Managed by GDC Disk Provisioner
blacklist nouveau
blacklist lbm-nouveau
options nouveau modeset=0
alias nouveau off
alias lbm-nouveau off
```

Create `src/ansible/roles/nvidia_gpu/templates/nvidia-persistenced.service.j2`:
```ini
[Unit]
Description=NVIDIA Persistence Daemon
Before=containerd.service kubelet.service
Wants=containerd.service

[Service]
Type=forking
ExecStart=/usr/bin/nvidia-persistenced --user root
{% if nvidia_gpu_lock_memory_clock | default(true) %}
ExecStartPost=/usr/bin/nvidia-smi -lmc {{ nvidia_gpu_memory_clock_mhz | default(7000) }}
{% endif %}
ExecStopPost=/bin/rm -rf /var/run/nvidia-persistenced
Restart=always

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_nvidia_gpu_role_structure test/test_nvidia_gpu.py::TestNvidiaGPU::test_nvidia_gpu_template_rendering -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/nvidia_gpu/defaults/main.yml src/ansible/roles/nvidia_gpu/templates/ test/test_nvidia_gpu.py
git commit -m "feat(ansible): create nvidia_gpu defaults and systemd templates"
```

---

### Task 4: NVIDIA GPU Role Task Implementation

**Files:**
- Create: `src/ansible/roles/nvidia_gpu/tasks/detect.yml`
- Create: `src/ansible/roles/nvidia_gpu/tasks/blacklist_nouveau.yml`
- Create: `src/ansible/roles/nvidia_gpu/tasks/install_driver.yml`
- Create: `src/ansible/roles/nvidia_gpu/tasks/configure_persistence.yml`
- Create: `src/ansible/roles/nvidia_gpu/tasks/collect_evidence.yml`
- Create: `src/ansible/roles/nvidia_gpu/tasks/main.yml`
- Test: `test/test_nvidia_gpu.py`

- [ ] **Step 1: Write the failing tests for task structure and detection logic**

Add to `test/test_nvidia_gpu.py`:

```python
    def test_nvidia_gpu_tasks_exist(self):
        """Verifies all task files for the nvidia_gpu role exist."""
        tasks_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/nvidia_gpu/tasks")
        for filename in ("main.yml", "detect.yml", "blacklist_nouveau.yml", "install_driver.yml", "configure_persistence.yml", "collect_evidence.yml"):
            self.assertTrue(os.path.isfile(os.path.join(tasks_dir, filename)), f"Missing task file {filename}")

    def test_pci_detection_regex(self):
        """Verifies the regex properly matches NVIDIA display controllers and ignores others."""
        import re
        pattern = re.compile(r'\[(0300|0302|0380)\]:.*10de:', re.IGNORECASE)

        # 192.168.9.238 sample line (RTX 4000 SFF Ada)
        gpu_line = "02:00.0 VGA compatible controller [0300]: NVIDIA Corporation Device [10de:2c34] (rev a1)"
        self.assertIsNotNone(pattern.search(gpu_line))

        # NVIDIA audio endpoint on same card - must NOT match display/compute controller
        audio_line = "02:00.1 Audio device [0403]: NVIDIA Corporation Device [10de:22e9] (rev a1)"
        self.assertIsNone(pattern.search(audio_line))

        # 192.168.9.242 sample line (AMD Phoenix APU)
        amd_line = "05:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Phoenix1 [1002:15bf] (rev c4)"
        self.assertIsNone(pattern.search(amd_line))

        # Intel Arrow Lake graphics
        intel_line = "00:02.0 VGA compatible controller [0300]: Intel Corporation Arrow Lake-U [Intel Graphics] [8086:7d67] (rev 06)"
        self.assertIsNone(pattern.search(intel_line))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_nvidia_gpu_tasks_exist -v`
Expected: FAIL with `AssertionError: Missing task file main.yml`

- [ ] **Step 3: Implement task files**

Create `src/ansible/roles/nvidia_gpu/tasks/detect.yml`:
```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

- name: "GDC-GPU | Probe PCI bus for NVIDIA display/compute controllers"
  ansible.builtin.shell: |
    set -o pipefail
    lspci -nn | grep -E '\[(0300|0302|0380)\]:.*10de:' || true
  register: pci_gpu_probe
  changed_when: false

- name: "GDC-GPU | Evaluate NVIDIA GPU presence"
  ansible.builtin.set_fact:
    nvidia_gpu_present: "{{ (pci_gpu_probe.stdout | trim | length) > 0 }}"
    nvidia_gpu_pci_raw: "{{ pci_gpu_probe.stdout | trim }}"
    nvidia_reboot_required: false

- name: "GDC-GPU | Extract GPU PCI address if detected"
  ansible.builtin.set_fact:
    nvidia_gpu_pci_id: "{{ nvidia_gpu_pci_raw.split()[0] if nvidia_gpu_present else 'NONE' }}"

- name: "GDC-GPU | Log detection outcome"
  ansible.builtin.debug:
    msg: "NVIDIA GPU Detected: {{ nvidia_gpu_present }} (PCI: {{ nvidia_gpu_pci_id }})"
```

Create `src/ansible/roles/nvidia_gpu/tasks/blacklist_nouveau.yml`:
```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

- name: "GDC-GPU | Deploy Nouveau modprobe blacklist configuration"
  ansible.builtin.template:
    src: blacklist-nouveau.conf.j2
    dest: /etc/modprobe.d/blacklist-nouveau.conf
    owner: root
    group: root
    mode: '0644'
  register: nouveau_blacklist_result

- name: "GDC-GPU | Check if Nouveau kernel module is currently loaded"
  ansible.builtin.shell: |
    lsmod | grep -q nouveau
  register: nouveau_loaded_check
  failed_when: false
  changed_when: false

- name: "GDC-GPU | Regenerate initramfs if Nouveau was newly blacklisted"
  ansible.builtin.shell: |
    if command -v dracut >/dev/null 2>&1; then
      dracut -f
    elif command -v update-initramfs >/dev/null 2>&1; then
      update-initramfs -u
    else
      echo "No supported initramfs generator found" >&2
      exit 1
    fi
  when: nouveau_blacklist_result.changed or nouveau_loaded_check.rc == 0
  register: initramfs_rebuilt

- name: "GDC-GPU | Flag system reboot required due to Nouveau suppression"
  ansible.builtin.set_fact:
    nvidia_reboot_required: true
  when: nouveau_blacklist_result.changed or nouveau_loaded_check.rc == 0
```

Create `src/ansible/roles/nvidia_gpu/tasks/install_driver.yml`:
```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

- name: "GDC-GPU | Install NVIDIA server driver, headers, and container toolkit"
  ansible.builtin.apt:
    name:
      - "linux-headers-{{ ansible_kernel }}"
      - "{{ nvidia_driver_package }}"
      - "{{ nvidia_utils_package }}"
      - "nvidia-container-toolkit"
    state: present
    update_cache: false
  register: gpu_packages_installed

- name: "GDC-GPU | Flag system reboot required if packages were installed or upgraded"
  ansible.builtin.set_fact:
    nvidia_reboot_required: true
  when: gpu_packages_installed.changed
```

Create `src/ansible/roles/nvidia_gpu/tasks/configure_persistence.yml`:
```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

- name: "GDC-GPU | Deploy nvidia-persistenced systemd service unit"
  ansible.builtin.template:
    src: nvidia-persistenced.service.j2
    dest: /etc/systemd/system/nvidia-persistenced.service
    owner: root
    group: root
    mode: '0644'
  register: persistenced_service_result

- name: "GDC-GPU | Reload systemd daemon if persistence unit changed"
  ansible.builtin.systemd:
    daemon_reload: true
  when: persistenced_service_result.changed

- name: "GDC-GPU | Enable nvidia-persistenced service"
  ansible.builtin.systemd:
    name: nvidia-persistenced
    enabled: "{{ nvidia_gpu_enable_persistence | bool }}"

- name: "GDC-GPU | Start nvidia-persistenced service (if driver already active without pending reboot)"
  ansible.builtin.systemd:
    name: nvidia-persistenced
    state: started
  when:
    - nvidia_gpu_enable_persistence | bool
    - not (nvidia_reboot_required | default(false))
  ignore_errors: true

- name: "GDC-GPU | Mark reboot-required flag for Stage 4.5"
  ansible.builtin.copy:
    dest: /var/run/reboot-required
    content: "NVIDIA driver installation and Nouveau blacklisting require reboot before ClusterReady\n"
    owner: root
    group: root
    mode: '0644'
  when: nvidia_reboot_required | default(false)
```

Create `src/ansible/roles/nvidia_gpu/tasks/collect_evidence.yml`:
```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

- name: "GDC-GPU | Record GPU evidence facts"
  ansible.builtin.set_fact:
    nvidia_gpu_evidence:
      present: "{{ nvidia_gpu_present | bool }}"
      status: "{{ 'CONFIGURED' if nvidia_gpu_present else 'SKIPPED_NO_GPU' }}"
      pci_bus: "{{ nvidia_gpu_pci_id | default('NONE') }}"
      driver_package: "{{ nvidia_driver_package if nvidia_gpu_present else 'NONE' }}"
      memory_clock_locked_mhz: "{{ nvidia_gpu_memory_clock_mhz if (nvidia_gpu_present and nvidia_gpu_lock_memory_clock) else 0 }}"
      persistence_service_configured: "{{ nvidia_gpu_enable_persistence if nvidia_gpu_present else false }}"
      reboot_pending: "{{ nvidia_reboot_required | default(false) }}"
```

Create `src/ansible/roles/nvidia_gpu/tasks/main.yml`:
```yaml
---
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

# 1. Probe hardware for NVIDIA GPU
- name: "GDC-GPU | Detect GPU hardware"
  ansible.builtin.import_tasks: detect.yml

# 2. Execute configuration ONLY if NVIDIA GPU is present
- name: "GDC-GPU | Provision NVIDIA Driver Stack"
  block:
    - name: "GDC-GPU | Suppress Nouveau"
      ansible.builtin.import_tasks: blacklist_nouveau.yml

    - name: "GDC-GPU | Install Driver & Toolkit Packages"
      ansible.builtin.import_tasks: install_driver.yml

    - name: "GDC-GPU | Configure Persistence Daemon & Clock Locking"
      ansible.builtin.import_tasks: configure_persistence.yml
  when: nvidia_gpu_present | bool

# 3. Always collect structured evidence
- name: "GDC-GPU | Collect Structured Telemetry Evidence"
  ansible.builtin.import_tasks: collect_evidence.yml
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_nvidia_gpu_tasks_exist test/test_nvidia_gpu.py::TestNvidiaGPU::test_pci_detection_regex -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/nvidia_gpu/tasks/ test/test_nvidia_gpu.py
git commit -m "feat(ansible): implement nvidia_gpu role tasks with hardware gating"
```

---

### Task 5: Stage LinuxReady & Evidence Integration

**Files:**
- Modify: `src/ansible/stages/stage_linux_ready.yml:25-30,75-95`
- Test: `test/test_nvidia_gpu.py`

- [ ] **Step 1: Write the failing test for stage_linux_ready integration**

Add to `test/test_nvidia_gpu.py`:

```python
    def test_stage_linux_ready_integration(self):
        """Verifies stage_linux_ready.yml includes the nvidia_gpu role and captures nvidia_gpu evidence."""
        stage_path = os.path.join(PROJECT_ROOT, "src/ansible/stages/stage_linux_ready.yml")
        with open(stage_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("name: nvidia_gpu", content, "stage_linux_ready.yml does not include role nvidia_gpu")
        self.assertIn("nvidia_gpu: \"{{ nvidia_gpu_evidence", content, "stage_linux_ready.yml does not record nvidia_gpu evidence")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_stage_linux_ready_integration -v`
Expected: FAIL with `AssertionError: stage_linux_ready.yml does not include role nvidia_gpu`

- [ ] **Step 3: Modify `src/ansible/stages/stage_linux_ready.yml`**

In `src/ansible/stages/stage_linux_ready.yml`:
1. Include the `nvidia_gpu` role right after `storage_prereqs` and before `security_hardening`:
```yaml
- name: Run nvidia_gpu role
  ansible.builtin.include_role:
    name: nvidia_gpu
```
2. In the `Structure LinuxReady Evidence Facts` task, add `nvidia_gpu`:
```yaml
      nvidia_gpu: "{{ nvidia_gpu_evidence | default({'status': 'SKIPPED_NO_GPU', 'present': false}) }}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_nvidia_gpu.py::TestNvidiaGPU::test_stage_linux_ready_integration -v`
Expected: PASS

- [ ] **Step 5: Run full test suite for `test_nvidia_gpu.py`**

Run: `pytest test/test_nvidia_gpu.py -v`
Expected: ALL 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/ansible/stages/stage_linux_ready.yml test/test_nvidia_gpu.py
git commit -m "feat(ansible): integrate nvidia_gpu role into stage_linux_ready"
```

---

### Task 6: End-to-End Validation Across Target Nodes

**Files:**
- Test: Verification on `192.168.9.242` (No GPU) and `192.168.9.238` (Has GPU)

- [ ] **Step 1: Run complete repository test suite**

Run: `python3 test/bin/run_all_tests.py`
Expected: All tests pass with 0 failures

- [ ] **Step 2: Run Ansible syntax check on `local.yml`**

Run: `ansible-playbook --syntax-check src/ansible/local.yml`
Expected: `playbook: src/ansible/local.yml` (syntax OK)

- [ ] **Step 3: Live Dry-Run on `192.168.9.242` (NO GPU)**

Execute command over SSH to test detection script on `192.168.9.242`:
```bash
ssh 192.168.9.242 "lspci -nn | grep -E '\[(0300|0302|0380)\]:.*10de:' || echo 'NO_NVIDIA_GPU'"
```
Expected: Output is `NO_NVIDIA_GPU` (role will skip all tasks).

- [ ] **Step 4: Live Dry-Run on `192.168.9.238` (HAS GPU)**

Execute command over SSH to test detection script on `192.168.9.238`:
```bash
ssh 192.168.9.238 "lspci -nn | grep -E '\[(0300|0302|0380)\]:.*10de:'"
```
Expected: Output matches `02:00.0 VGA compatible controller [0300]: NVIDIA Corporation Device [10de:2c34] (rev a1)`.

- [ ] **Step 5: Final Documentation & Changelog Update**

Update `CHANGELOG.md` with:
```markdown
### Added
- Automated NVIDIA GPU driver, toolkit, persistence daemon, and clock locking setup gated by hardware detection in `nvidia_gpu` role during LinuxReady.
```
Commit:
```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record automated NVIDIA GPU driver and toolkit setup"
```
