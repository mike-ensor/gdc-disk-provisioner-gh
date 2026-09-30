# GDC Ansible Dynamic State Machine & Lookup Plugin Architecture

**Date:** 2026-09-28  
**Status:** Approved  
**Scope:** `src/ansible/`, `src/build/templates/user-data.j2`, `test/`

---

## 1. Overview & Problem Statement

### 1.1 Premature Failure Reporting on GDC Companion
When `gdc-collector` runs during intermediate node stages, its internal stage evaluator checks whether `gitea` (port 3000) and `nexus` (port 8081) are up. If active, but `gdc-provision.service` has not completed the full post-install sequence (`SUCCESS: All Ready-Linux Post-Install`), `gdc-collector` marks `BOUNDARY_HUB_TURNUP` as `FAILED` (`"ansible_pull_success": false`), streaming a premature failure status to the GDC Companion UI.

### 1.2 Ansible Dynamic `block/always` Skip Bug
In `src/ansible/local.yml`, stage execution blocks have compound conditions such as:
```yaml
when:
  - second_boot_state.status == "completed"
  - linux_ready_state.status != "completed"
```
In Ansible, block conditions are dynamically re-evaluated on **every task** in the `block`, `rescue`, and `always` sections. When `stage_linux_ready.yml` sets `linux_ready_state: { status: "completed" }`, Ansible re-evaluates the block condition before entering `always:`. Because `status != "completed"` is now false, Ansible **skips the post-stage telemetry collection task**, leaving Companion stuck with the stale, premature failure report.

### 1.3 Incomplete 8-Stage Lifecycle Implementation
`docs/ARCHITECTURE.md` and `gdc-companion` define an 8-stage lifecycle, but `src/ansible/` currently stops at Stage 6 (`CLUSTER_TURNUP`), lacking task and role implementations for Stage 7 (`post-cluster`) and Stage 8 (`upkeep`).

### 1.4 Missing LiveCD Milestone Artifact
The LiveCD installer (`user-data.j2`) finishes and reboots without writing `/target/var/gdc-install/state/live-cd.json` or transmitting a completion report, creating a visibility blind spot on initial physical boot.

---

## 2. Canonical Stage Enum & State Machine Engine

### 2.1 The Stage Enum (`GdcStage`)
Defined in `src/ansible/lookup_plugins/gdc_state_machine.py`:

```python
from enum import Enum

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
```

### 2.2 Deterministic Gate Resolution Algorithm
The state resolver function `get_current_stage(state_dir="/var/gdc-install/state", fallback_config_path="/etc/gdc/fallback-config.json") -> GdcStage` evaluates from the first stage to the last. The **first incomplete stage** is the active stage:

| Order | Stage Enum | State File | Completion Condition | Next Stage |
| :---: | :--- | :--- | :--- | :--- |
| **0** | `LIVECD` | `live-cd.json` | `status == "completed"` or `/etc/fstab` exists | `FIRST_BOOT` |
| **1** | `FIRST_BOOT` | `first-boot.json` | `status == "completed"` | `SECOND_BOOT` |
| **2** | `SECOND_BOOT` | `second-boot.json` | `status == "completed"` | `LINUX_READY` |
| **3** | `LINUX_READY` | `linux-ready.json` | `status == "completed"` | `CLUSTER_READY` |
| **4** | `CLUSTER_READY` | `cluster-ready.json` | `status == "completed"` | `CLUSTER_TURNUP` |
| **5** | `CLUSTER_TURNUP` | `cluster-turnup.json`| `status == "completed"` | `POST_CLUSTER` |
| **6** | `POST_CLUSTER` | `post-validation.json`| `status == "completed"` | `UPKEEP` |
| **7** | `UPKEEP` | `update-upkeep.json` | `status == "completed"` | `COMPLETE` |
| **8** | `COMPLETE` | N/A | All 8 state files verified | Finished |

*If any stage's JSON file is missing, empty, or has `status: "failed"` / `"pending"`, evaluation halts immediately and returns that stage.*

To ensure 100% interoperability with `gdc-companion` and backwards compatibility, both naming conventions are supported:
- `post-validation.json` and `post-cluster.json`
- `update-upkeep.json` and `upkeep.json`

### 2.3 Stopper Stage Support (`machine_state_stop_stage`)
If `/etc/gdc/fallback-config.json` specifies `machine_state_stop_stage` (e.g. `CLUSTER_READY`), and that stage has completed, `get_current_stage` halts and returns `GdcStage.COMPLETE` (or signals stopped state) to prevent unwanted over-provisioning during test cycles.

---

## 3. Ansible Lookup Plugin (`lookup('gdc_state')`)

In `src/ansible/lookup_plugins/gdc_state.py`:
```python
import os
import sys

# Ensure local lookup directory is in sys.path for sibling imports
plugin_dir = os.path.dirname(__file__)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from ansible.plugins.lookup import LookupBase
from gdc_state_machine import get_current_stage

class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        state_dir = kwargs.get("state_dir", "/var/gdc-install/state")
        fallback_config = kwargs.get("fallback_config", "/etc/gdc/fallback-config.json")
        stage = get_current_stage(state_dir=state_dir, fallback_config_path=fallback_config)
        return [stage.value]
```

### Usage in Playbooks:
```yaml
- name: "LINUX_READY | Execute Baseline Hardening"
  when: lookup('gdc_state') == 'linux-ready'
  block:
    - ansible.builtin.import_tasks: stages/stage_linux_ready.yml
```

---

## 4. Telemetry Collection Guarantee

To eliminate the `always:` skipping issue:
1. **Success Telemetry:** Staged as the final step within each `stage_*.yml` immediately following state file writing:
   ```yaml
   - name: "GDC-STATE | Trigger Post-Stage Telemetry"
     ansible.builtin.shell: |
       if [ -x /usr/local/bin/gdc-collector ]; then
         /usr/local/bin/gdc-collector --stage <stage> --companion-url="{{ gdc_companion_reports_url }}"
       fi
     ignore_errors: true
     failed_when: false
   ```
2. **Failure Telemetry:** Triggered inside the `rescue:` block of `local.yml` immediately after writing the failed state JSON:
   ```yaml
   rescue:
     - name: "GDC-STATE | Record Failure State"
       ansible.builtin.copy:
         dest: /var/gdc-install/state/<stage>.json
         content: '{"stage": "<STAGE>", "status": "FAILED", "timestamp": "{{ now(utc=true, fmt="%Y-%m-%dT%H:%M:%SZ") }}"}'
     - name: "GDC-STATE | Emit Failure Diagnostics"
       ansible.builtin.shell: |
         if [ -x /usr/local/bin/gdc-collector ]; then
           /usr/local/bin/gdc-collector --stage <stage> --companion-url="{{ gdc_companion_reports_url }}"
         fi
       ignore_errors: true
       failed_when: false
     - ansible.builtin.fail:
         msg: "Stage <STAGE> failed!"
   ```

---

## 5. Mocked Stages & Roles

### 5.1 Stage 6: `post-cluster`
* **Entrypoint:** `src/ansible/stages/stage_post_cluster.yml`
* **Role:** `src/ansible/roles/post_cluster/tasks/main.yml`
* **Validation:** Kubernetes node `Ready` condition, CoreDNS rollout status, and StorageClass availability.
* **State File:** `/var/gdc-install/state/post-validation.json` (with symlink `/var/gdc-install/state/post-cluster.json`).

### 5.2 Stage 7: `upkeep`
* **Entrypoint:** `src/ansible/stages/stage_upkeep.yml`
* **Role:** `src/ansible/roles/upkeep/tasks/main.yml`
* **Validation:** Asserts `gdc-provision.timer`, `gdc-desired-state.timer`, and USB updater udev rule.
* **State File:** `/var/gdc-install/state/update-upkeep.json` (with symlink `/var/gdc-install/state/upkeep.json`).

### 5.3 LiveCD Milestone
* **Entrypoint:** `src/build/templates/user-data.j2` (`late-commands`).
* **State File:** Writes `/target/var/gdc-install/state/live-cd.json`.
* **Telemetry:** Invokes `/usr/local/bin/gdc-collector --stage live-cd --companion-url="{{ companion_url }}"`.

---

## 6. Testing & Validation Strategy

1. **Unit Tests (`test/test_gdc_state_machine.py`):**
   * Verifies initial resolution to `first-boot` on clean filesystems.
   * Verifies sequential gate resolution through all 8 stages.
   * Verifies failed/corrupted state file handling and idempotency.
   * Verifies `machine_state_stop_stage` early exit behavior.
   * Verifies lookup plugin functionality under Ansible runtime.
2. **Regression Testing:**
   * Run full test suite: `python3 -m unittest discover -s test -p "test_*.py"`.
   * Syntax check playbook: `ansible-playbook --syntax-check src/ansible/local.yml`.
