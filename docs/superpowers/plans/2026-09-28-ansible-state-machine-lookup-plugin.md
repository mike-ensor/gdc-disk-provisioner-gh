# Ansible Dynamic State Machine & Lookup Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a centralized Python state machine (`GdcStage` Enum), an on-demand Ansible lookup plugin (`lookup('gdc_state')`), new mocked stages (`post-cluster` and `upkeep`), and guaranteed telemetry execution across all 8 GDC lifecycle stages.

**Architecture:** A pure Python module `gdc_state_machine.py` models the 8 lifecycle stages with an Enum and resolves current active stage from `/var/gdc-install/state/*.json`. An Ansible lookup plugin `gdc_state.py` allows dynamic evaluation in task `when:` conditions. Success telemetry is moved to the end of each stage task file, while failure telemetry is handled in `rescue:` blocks, eliminating `always:` skipping.

**Tech Stack:** Python 3 (`enum`, `json`, `os`), Ansible (`LookupBase`, `lookup_plugins`, YAML), Jinja2 (`user-data.j2`), Python `unittest`.

---

## File Structure

- **New:** `src/ansible/lookup_plugins/gdc_state_machine.py` - Core state resolver and `GdcStage` Enum.
- **New:** `src/ansible/lookup_plugins/gdc_state.py` - Ansible lookup plugin entrypoint.
- **New:** `test/test_gdc_state_machine.py` - Unit tests for state machine transitions, edge cases, and lookup plugin.
- **New:** `src/ansible/stages/stage_post_cluster.yml` - Stage 7 entrypoint.
- **New:** `src/ansible/roles/post_cluster/tasks/main.yml` - Stage 7 role tasks.
- **New:** `src/ansible/stages/stage_upkeep.yml` - Stage 8 entrypoint.
- **New:** `src/ansible/roles/upkeep/tasks/main.yml` - Stage 8 role tasks.
- **Modify:** `src/build/templates/user-data.j2` - Write `live-cd.json` and trigger LiveCD telemetry in `late-commands`.
- **Modify:** `src/ansible/local.yml` - Replace compound conditions with `lookup('gdc_state') == '<stage>'` and embed telemetry.

---

### Task 1: Create State Machine Engine and Unit Tests

**Files:**
- Create: `src/ansible/lookup_plugins/gdc_state_machine.py`
- Test: `test/test_gdc_state_machine.py`

- [ ] **Step 1: Write the failing unit tests for `GdcStage` and `get_current_stage`**

Create `test/test_gdc_state_machine.py`:
```python
import os
import sys
import json
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ANSIBLE_LOOKUP_DIR = os.path.join(PROJECT_ROOT, "src", "ansible", "lookup_plugins")
if ANSIBLE_LOOKUP_DIR not in sys.path:
    sys.path.insert(0, ANSIBLE_LOOKUP_DIR)

from gdc_state_machine import GdcStage, get_current_stage


class TestGdcStateMachine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.state_dir = os.path.join(self.test_dir, "state")
        os.makedirs(self.state_dir, exist_ok=True)
        self.fallback_config = os.path.join(self.test_dir, "fallback-config.json")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_state(self, stage_file, status="completed"):
        path = os.path.join(self.state_dir, stage_file)
        with open(path, "w") as f:
            json.dump({"stage": stage_file.split(".")[0], "status": status}, f)

    def test_clean_filesystem_returns_first_boot(self):
        """Clean host filesystem (with fstab present) starts at first-boot."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w") as f:
            f.write("# dummy fstab")
        stage = get_current_stage(state_dir=self.state_dir, fstab_path=fstab)
        self.assertEqual(stage, GdcStage.FIRST_BOOT)

    def test_livecd_returned_if_fstab_and_livecd_state_missing(self):
        """If fstab does not exist and live-cd.json is missing, current stage is LIVECD."""
        stage = get_current_stage(state_dir=self.state_dir, fstab_path="/nonexistent/fstab")
        self.assertEqual(stage, GdcStage.LIVECD)

    def test_sequential_transitions(self):
        """Validates ordered transition through all 8 stages."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w") as f:
            f.write("# dummy fstab")

        # 1. First Boot
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.FIRST_BOOT)
        self.write_state("first-boot.json")

        # 2. Second Boot
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.SECOND_BOOT)
        self.write_state("second-boot.json")

        # 3. Linux Ready
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.LINUX_READY)
        self.write_state("linux-ready.json")

        # 4. Cluster Ready
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.CLUSTER_READY)
        self.write_state("cluster-ready.json")

        # 5. Cluster Turnup
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.CLUSTER_TURNUP)
        self.write_state("cluster-turnup.json")

        # 6. Post Cluster (post-validation.json)
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.POST_CLUSTER)
        self.write_state("post-validation.json")

        # 7. Upkeep (update-upkeep.json)
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.UPKEEP)
        self.write_state("update-upkeep.json")

        # 8. Complete
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.COMPLETE)

    def test_failed_state_retains_current_stage(self):
        """A stage with status=failed must remain active for retry."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w") as f:
            f.write("# dummy fstab")
        self.write_state("first-boot.json", status="completed")
        self.write_state("second-boot.json", status="failed")

        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.SECOND_BOOT)

    def test_corrupted_json_retains_current_stage(self):
        """Corrupted/truncated state file is treated as incomplete."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w") as f:
            f.write("# dummy fstab")
        self.write_state("first-boot.json", status="completed")
        bad_json = os.path.join(self.state_dir, "second-boot.json")
        with open(bad_json, "w") as f:
            f.write("{invalid json...")

        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.SECOND_BOOT)

    def test_stop_stage_respected(self):
        """If machine_state_stop_stage is reached and completed, return COMPLETE."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w") as f:
            f.write("# dummy fstab")
        self.write_state("first-boot.json", status="completed")
        self.write_state("second-boot.json", status="completed")

        with open(self.fallback_config, "w") as f:
            json.dump({"machine_state_stop_stage": "SECOND_BOOT"}, f)

        stage = get_current_stage(self.state_dir, fallback_config_path=self.fallback_config, fstab_path=fstab)
        self.assertEqual(stage, GdcStage.COMPLETE)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_gdc_state_machine.py`  
Expected: `ModuleNotFoundError: No module named 'gdc_state_machine'`

- [ ] **Step 3: Implement `src/ansible/lookup_plugins/gdc_state_machine.py`**

Create `src/ansible/lookup_plugins/gdc_state_machine.py`:
```python
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""GDC Node Lifecycle State Machine and Gate Resolution Engine."""

from enum import Enum
import json
import os
from typing import Optional


class GdcStage(str, Enum):
    LIVECD = "live-cd"
    FIRST_BOOT = "first-boot"
    SECOND_BOOT = "second-boot"
    LINUX_READY = "linux-ready"
    CLUSTER_READY = "cluster-ready"
    CLUSTER_TURNUP = "cluster-turnup"
    POST_CLUSTER = "post-cluster"
    UPKEEP = "upkeep"
    COMPLETE = "complete"


# Map from stop_stage string representations to canonical GdcStage
STOP_STAGE_MAP = {
    "LIVECD": GdcStage.LIVECD,
    "LIVE_CD": GdcStage.LIVECD,
    "FIRST_BOOT": GdcStage.FIRST_BOOT,
    "SECOND_BOOT": GdcStage.SECOND_BOOT,
    "LINUX_READY": GdcStage.LINUX_READY,
    "CLUSTER_READY": GdcStage.CLUSTER_READY,
    "CLUSTER_TURNUP": GdcStage.CLUSTER_TURNUP,
    "POST_CLUSTER": GdcStage.POST_CLUSTER,
    "POST_VALIDATION": GdcStage.POST_CLUSTER,
    "UPDATE_UPKEEP": GdcStage.UPKEEP,
    "UPKEEP": GdcStage.UPKEEP,
}

# Gate definitions: (Stage Enum, List of acceptable state filenames)
GDC_GATE_SEQUENCE = [
    (GdcStage.LIVECD, ["live-cd.json"]),
    (GdcStage.FIRST_BOOT, ["first-boot.json"]),
    (GdcStage.SECOND_BOOT, ["second-boot.json"]),
    (GdcStage.LINUX_READY, ["linux-ready.json"]),
    (GdcStage.CLUSTER_READY, ["cluster-ready.json"]),
    (GdcStage.CLUSTER_TURNUP, ["cluster-turnup.json"]),
    (GdcStage.POST_CLUSTER, ["post-validation.json", "post-cluster.json"]),
    (GdcStage.UPKEEP, ["update-upkeep.json", "upkeep.json"]),
]


def _is_stage_file_completed(state_dir: str, filenames: list[str]) -> bool:
    """Checks whether any matching state file exists and has status == 'completed'."""
    for fn in filenames:
        path = os.path.join(state_dir, fn)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and data.get("status", "").lower() == "completed":
                        return True
            except Exception:
                continue
    return False


def get_current_stage(
    state_dir: str = "/var/gdc-install/state",
    fallback_config_path: str = "/etc/gdc/fallback-config.json",
    fstab_path: str = "/etc/fstab",
) -> GdcStage:
    """Resolves the current active GDC lifecycle stage.

    Evaluates gates sequentially. Returns the first stage that is not yet completed.
    If a configured stop_stage has completed, returns GdcStage.COMPLETE.
    """
    # 1. Read stop stage if configured
    stop_stage_enum: Optional[GdcStage] = None
    if os.path.exists(fallback_config_path):
        try:
            with open(fallback_config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                stop_str = cfg.get("machine_state_stop_stage", "")
                if stop_str in STOP_STAGE_MAP:
                    stop_stage_enum = STOP_STAGE_MAP[stop_str]
        except Exception:
            pass

    # 2. Evaluate stage sequence
    for stage_enum, filenames in GDC_GATE_SEQUENCE:
        is_completed = False

        if stage_enum == GdcStage.LIVECD:
            # LiveCD is complete if state file exists or host fstab exists
            if _is_stage_file_completed(state_dir, filenames) or os.path.exists(fstab_path):
                is_completed = True
        else:
            is_completed = _is_stage_file_completed(state_dir, filenames)

        if not is_completed:
            return stage_enum

        # If this stage completed and matched the stop target, halt further execution
        if stop_stage_enum is not None and stage_enum == stop_stage_enum:
            return GdcStage.COMPLETE

    return GdcStage.COMPLETE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_gdc_state_machine.py`  
Expected: `Ran 5 tests in ... OK`

- [ ] **Step 5: Commit**

```bash
git add src/ansible/lookup_plugins/gdc_state_machine.py test/test_gdc_state_machine.py
git commit -m "feat(ansible): add gdc_state_machine enum and gate resolution engine"
```

---

### Task 2: Create Ansible Lookup Plugin and Integration Tests

**Files:**
- Create: `src/ansible/lookup_plugins/gdc_state.py`
- Modify: `test/test_gdc_state_machine.py`

- [ ] **Step 1: Add unit test verifying LookupModule execution**

Add to `test/test_gdc_state_machine.py`:
```python
    def test_ansible_lookup_plugin_execution(self):
        """Verifies Ansible LookupModule run method returns correct stage value."""
        from gdc_state import LookupModule
        lookup = LookupModule()
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w") as f:
            f.write("# dummy")

        result = lookup.run([], state_dir=self.state_dir, fstab_path=fstab)
        self.assertEqual(result, ["first-boot"])

        self.write_state("first-boot.json")
        result = lookup.run([], state_dir=self.state_dir, fstab_path=fstab)
        self.assertEqual(result, ["second-boot"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test.test_gdc_state_machine.TestGdcStateMachine.test_ansible_lookup_plugin_execution`  
Expected: `ModuleNotFoundError: No module named 'gdc_state'`

- [ ] **Step 3: Implement `src/ansible/lookup_plugins/gdc_state.py`**

Create `src/ansible/lookup_plugins/gdc_state.py`:
```python
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Ansible lookup plugin for dynamic GDC stage evaluation."""

import os
import sys

# Ensure plugin directory is on sys.path for local module import
PLUGIN_DIR = os.path.dirname(__file__)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ansible.plugins.lookup import LookupBase
from gdc_state_machine import get_current_stage


class LookupModule(LookupBase):
    """Lookup plugin providing on-demand current GDC stage."""

    def run(self, terms, variables=None, **kwargs):
        state_dir = kwargs.get("state_dir", "/var/gdc-install/state")
        fallback_config = kwargs.get("fallback_config", "/etc/gdc/fallback-config.json")
        fstab_path = kwargs.get("fstab_path", "/etc/fstab")

        stage = get_current_stage(
            state_dir=state_dir,
            fallback_config_path=fallback_config,
            fstab_path=fstab_path,
        )
        return [stage.value]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_gdc_state_machine.py`  
Expected: `Ran 6 tests in ... OK`

- [ ] **Step 5: Commit**

```bash
git add src/ansible/lookup_plugins/gdc_state.py test/test_gdc_state_machine.py
git commit -m "feat(ansible): add gdc_state lookup plugin"
```

---

### Task 3: Implement `post_cluster` and `upkeep` Stages and Roles

**Files:**
- Create: `src/ansible/stages/stage_post_cluster.yml`
- Create: `src/ansible/roles/post_cluster/tasks/main.yml`
- Create: `src/ansible/stages/stage_upkeep.yml`
- Create: `src/ansible/roles/upkeep/tasks/main.yml`

- [ ] **Step 1: Create `src/ansible/roles/post_cluster/tasks/main.yml`**

```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-POST | Verify cluster nodes reach Ready condition"
  ansible.builtin.command:
    cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf wait --for=condition=Ready nodes --all --timeout=180s"
  register: nodes_ready_check
  changed_when: false
  failed_when: false

- name: "GDC-POST | Verify CoreDNS operational readiness"
  ansible.builtin.command:
    cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf rollout status deployment/coredns -n kube-system --timeout=120s"
  register: coredns_rollout_check
  changed_when: false
  failed_when: false

- name: "GDC-POST | Check storage classes availability"
  ansible.builtin.command:
    cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf get sc"
  register: storage_class_check
  changed_when: false
  failed_when: false

- name: "GDC-EVIDENCE | Structure PostCluster Evidence Facts"
  ansible.builtin.set_fact:
    post_cluster_evidence:
      kubernetes_nodes_ready: "{{ nodes_ready_check.rc == 0 }}"
      coredns_operational: "{{ coredns_rollout_check.rc == 0 }}"
      storage_classes_present: "{{ storage_class_check.rc == 0 }}"
```

- [ ] **Step 2: Create `src/ansible/stages/stage_post_cluster.yml`**

```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-TIMING | Ensure PostCluster start time is set"
  ansible.builtin.set_fact:
    post_cluster_start_time: "{{ post_cluster_start_time | default(now(utc=true, fmt='%Y-%m-%dT%H:%M:%SZ')) }}"
    post_cluster_start_epoch: "{{ post_cluster_start_epoch | default(now(utc=true).strftime('%s') | int) }}"

- name: "Run post_cluster role"
  ansible.builtin.include_role:
    name: post_cluster

- name: "GDC-TIMING | Calculate PostCluster timing facts"
  ansible.builtin.set_fact:
    post_cluster_end_time: "{{ now(utc=true, fmt='%Y-%m-%dT%H:%M:%SZ') }}"
    post_cluster_duration_seconds: "{{ [(now(utc=true).strftime('%s') | int) - (post_cluster_start_epoch | int), 0] | max }}"

- name: "GDC-EVIDENCE | Update PostCluster Evidence Timing"
  ansible.builtin.set_fact:
    post_cluster_evidence: "{{ (post_cluster_evidence | default({})) | combine({'timing': {'start_time': post_cluster_start_time, 'end_time': post_cluster_end_time, 'duration_seconds': post_cluster_duration_seconds | int, 'overall_provisioning_start_time': provisioning_start_time | default(post_cluster_start_time)}}) }}"

- name: "GDC-STATE | Write PostCluster completion state"
  ansible.builtin.copy:
    dest: /var/gdc-install/state/post-validation.json
    owner: root
    group: root
    mode: '0644'
    content: |
      {
        "stage": "POST_CLUSTER",
        "status": "completed",
        "timestamp": "{{ post_cluster_end_time }}",
        "evidence": {{ post_cluster_evidence | to_json }}
      }

- name: "GDC-STATE | Create post-cluster.json compatibility symlink"
  ansible.builtin.file:
    src: /var/gdc-install/state/post-validation.json
    dest: /var/gdc-install/state/post-cluster.json
    state: link
    force: true

- name: "GDC-STATE | Trigger Post-Stage 7 Diagnostic Collection"
  ansible.builtin.shell: |
    if [ -x /usr/local/bin/gdc-collector ]; then
      /usr/local/bin/gdc-collector --stage post-cluster --companion-url="{{ gdc_companion_reports_url }}"
    fi
  ignore_errors: true
  failed_when: false
```

- [ ] **Step 3: Create `src/ansible/roles/upkeep/tasks/main.yml`**

```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-UPKEEP | Verify gdc-provision periodic timer is active"
  ansible.builtin.systemd:
    name: gdc-provision.timer
    enabled: true
    state: started
  register: provision_timer_stat
  failed_when: false

- name: "GDC-UPKEEP | Verify gdc-desired-state timer is active"
  ansible.builtin.systemd:
    name: gdc-desired-state.timer
    enabled: true
    state: started
  register: desired_state_timer_stat
  failed_when: false

- name: "GDC-UPKEEP | Verify headless USB sideload update rule exists"
  ansible.builtin.stat:
    path: /etc/udev/rules.d/99-gdc-usb-updater.rules
  register: usb_udev_rule_stat

- name: "GDC-EVIDENCE | Structure Upkeep Evidence Facts"
  ansible.builtin.set_fact:
    upkeep_evidence:
      provision_timer_configured: "{{ provision_timer_stat is succeeded }}"
      desired_state_timer_configured: "{{ desired_state_timer_stat is succeeded }}"
      usb_updater_rule_configured: "{{ usb_udev_rule_stat.stat.exists }}"
```

- [ ] **Step 4: Create `src/ansible/stages/stage_upkeep.yml`**

```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-TIMING | Ensure Upkeep start time is set"
  ansible.builtin.set_fact:
    upkeep_start_time: "{{ upkeep_start_time | default(now(utc=true, fmt='%Y-%m-%dT%H:%M:%SZ')) }}"
    upkeep_start_epoch: "{{ upkeep_start_epoch | default(now(utc=true).strftime('%s') | int) }}"

- name: "Run upkeep role"
  ansible.builtin.include_role:
    name: upkeep

- name: "GDC-TIMING | Calculate Upkeep timing facts"
  ansible.builtin.set_fact:
    upkeep_end_time: "{{ now(utc=true, fmt='%Y-%m-%dT%H:%M:%SZ') }}"
    upkeep_duration_seconds: "{{ [(now(utc=true).strftime('%s') | int) - (upkeep_start_epoch | int), 0] | max }}"

- name: "GDC-EVIDENCE | Update Upkeep Evidence Timing"
  ansible.builtin.set_fact:
    upkeep_evidence: "{{ (upkeep_evidence | default({})) | combine({'timing': {'start_time': upkeep_start_time, 'end_time': upkeep_end_time, 'duration_seconds': upkeep_duration_seconds | int, 'overall_provisioning_start_time': provisioning_start_time | default(upkeep_start_time)}}) }}"

- name: "GDC-STATE | Write Upkeep completion state"
  ansible.builtin.copy:
    dest: /var/gdc-install/state/update-upkeep.json
    owner: root
    group: root
    mode: '0644'
    content: |
      {
        "stage": "UPDATE_UPKEEP",
        "status": "completed",
        "timestamp": "{{ upkeep_end_time }}",
        "evidence": {{ upkeep_evidence | to_json }}
      }

- name: "GDC-STATE | Create upkeep.json compatibility symlink"
  ansible.builtin.file:
    src: /var/gdc-install/state/update-upkeep.json
    dest: /var/gdc-install/state/upkeep.json
    state: link
    force: true

- name: "GDC-STATE | Trigger Final Post-Stage 8 Telemetry"
  ansible.builtin.shell: |
    if [ -x /usr/local/bin/gdc-collector ]; then
      /usr/local/bin/gdc-collector --stage upkeep --companion-url="{{ gdc_companion_reports_url }}"
    fi
  ignore_errors: true
  failed_when: false
```

- [ ] **Step 5: Commit**

```bash
git add src/ansible/stages/stage_post_cluster.yml src/ansible/roles/post_cluster/tasks/main.yml src/ansible/stages/stage_upkeep.yml src/ansible/roles/upkeep/tasks/main.yml
git commit -m "feat(ansible): mock out post_cluster and upkeep stages and roles"
```

---

### Task 4: Add LiveCD State Recording and Telemetry in `user-data.j2`

**Files:**
- Modify: `src/build/templates/user-data.j2`
- Test: `test/test_template_hydration.py`

- [ ] **Step 1: Add unit test in `test_template_hydration.py` for LiveCD state writing**

Add to `test/test_template_hydration.py`:
```python
    def test_livecd_state_and_telemetry_in_late_commands(self):
        """Verifies that user-data writes live-cd.json and emits telemetry in late-commands."""
        template = self.jinja_env.get_template('user-data.j2')
        rendered = template.render(self.base_env)
        self.assertIn("/target/var/gdc-install/state/live-cd.json", rendered)
        self.assertIn("/usr/local/bin/gdc-collector --stage live-cd", rendered)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test.test_template_hydration.TestGgdTemplateHydration.test_livecd_state_and_telemetry_in_late_commands`  
Expected: `AssertionError: '/target/var/gdc-install/state/live-cd.json' not found`

- [ ] **Step 3: Update `src/build/templates/user-data.j2`**

In `src/build/templates/user-data.j2`, add right before the final `echo "[GDC-INSTALL-GOAL] All custom late commands succeeded and validated!"` (around line 1160):
```bash
      # Write persistent LiveCD completion state
      mkdir -p /target/var/gdc-install/state
      cat <<'EOF' > /target/var/gdc-install/state/live-cd.json
      {
        "stage": "LIVECD",
        "status": "completed",
        "timestamp": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
      }
      EOF

      # Emit LiveCD completion report to Companion before reboot
      if [ -x /usr/local/bin/gdc-collector ]; then
        /usr/local/bin/gdc-collector --stage live-cd --companion-url="{{ companion_url }}" >/dev/ttyS0 2>&1 || true
      fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test.test_template_hydration.TestGgdTemplateHydration.test_livecd_state_and_telemetry_in_late_commands`  
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/build/templates/user-data.j2 test/test_template_hydration.py
git commit -m "feat(installer): write live-cd.json and trigger telemetry at end of LiveCD"
```

---

### Task 5: Refactor `local.yml` to Use `lookup('gdc_state')` with Guaranteed Telemetry

**Files:**
- Modify: `src/ansible/local.yml`
- Modify: `src/ansible/stages/stage_first_boot.yml`
- Modify: `src/ansible/stages/stage_second_boot.yml`
- Modify: `src/ansible/stages/stage_linux_ready.yml`
- Modify: `src/ansible/stages/stage_cluster_ready.yml`
- Modify: `src/ansible/stages/stage_cluster_turnup.yml`

- [ ] **Step 1: Update success telemetry in each stage task file**

In:
- `src/ansible/stages/stage_first_boot.yml`: Add post-stage telemetry call after writing `first-boot.json`.
- `src/ansible/stages/stage_second_boot.yml`: Add post-stage telemetry call after writing `second-boot.json`.
- `src/ansible/stages/stage_linux_ready.yml`: Add post-stage telemetry call after writing `linux-ready.json`.
- `src/ansible/stages/stage_cluster_ready.yml`: Add post-stage telemetry call after writing `cluster-ready.json`.
- `src/ansible/stages/stage_cluster_turnup.yml`: Add post-stage telemetry call after writing `cluster-turnup.json`.

Pattern:
```yaml
- name: "GDC-STATE | Trigger Post-Stage Telemetry"
  ansible.builtin.shell: |
    if [ -x /usr/local/bin/gdc-collector ]; then
      /usr/local/bin/gdc-collector --stage <stage-name> --companion-url="{{ gdc_companion_reports_url }}"
    fi
  ignore_errors: true
  failed_when: false
```

- [ ] **Step 2: Update `src/ansible/local.yml` to use `lookup('gdc_state')`**

Refactor the stage blocks in `src/ansible/local.yml`:
- Stage 2: `when: lookup('gdc_state') == 'first-boot'`
- Stage 3: `when: lookup('gdc_state') == 'second-boot'`
- Stage 4: `when: lookup('gdc_state') == 'linux-ready'`
- Stage 5: `when: lookup('gdc_state') == 'cluster-ready'`
- Stage 6: `when: lookup('gdc_state') == 'cluster-turnup'`
- Stage 7: `when: lookup('gdc_state') == 'post-cluster'`
- Stage 8: `when: lookup('gdc_state') == 'upkeep'`

Remove the brittle block-level `always:` tasks and replace them with immediate telemetry in `rescue:` blocks.

- [ ] **Step 3: Verify Ansible playbook syntax**

Run: `ansible-playbook --syntax-check src/ansible/local.yml`  
Expected: `playbook: src/ansible/local.yml` (Returncode 0)

- [ ] **Step 4: Commit**

```bash
git add src/ansible/local.yml src/ansible/stages/
git commit -m "refactor(ansible): migrate local.yml to lookup('gdc_state') with guaranteed telemetry"
```

---

### Task 6: Full Regression Testing & Verification

**Files:**
- Repository test suite

- [ ] **Step 1: Run the full python unit test discovery**

Run: `python3 -m unittest discover -s test -p "test_*.py"`  
Expected: All 158+ tests pass with 0 failures.

- [ ] **Step 2: Run shellcheck on all build scripts**

Run: `shellcheck src/build/generate_storage_config.sh`  
Expected: Clean with 0 warnings.

- [ ] **Step 3: Commit and Push**

```bash
git push -u origin feature/ansible-state-machine-lookup-plugin
```

- [ ] **Step 4: Create GitLab Merge Request via `glab`**

Run:
```bash
glab mr create \
  --title "feat(ansible): implement dynamic lifecycle state machine and lookup plugin" \
  --target-branch "main" \
  --source-branch "feature/ansible-state-machine-lookup-plugin" \
  --description "## Summary
- Introduces pure Python GdcStage Enum and gate resolution engine in \`src/ansible/lookup_plugins/gdc_state_machine.py\`.
- Implements Ansible lookup plugin \`lookup('gdc_state')\` for clean, on-demand stage evaluation.
- Resolves the Ansible \`block/always\` telemetry skip bug by embedding post-stage telemetry inside stage files and failure telemetry in \`rescue:\` blocks.
- Adds mocked \`post_cluster\` (Stage 7) and \`upkeep\` (Stage 8) stages and roles matching existing patterns.
- Adds LiveCD state recording (\`live-cd.json\`) and telemetry in \`user-data.j2\`.
- Comprehensive unit tests covering all 8 stage transitions and edge cases."
```
