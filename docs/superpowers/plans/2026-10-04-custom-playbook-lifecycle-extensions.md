# Custom Playbook Lifecycle Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a modular post-stage Ansible playbook extension framework that allows edge nodes to retrieve, verify, extract, and execute external playbook bundles during the provisioning lifecycle (`cluster_ready`, `cluster_turnup`, `post_cluster`), providing pluggable post-cluster burn-in testing and verification with strict failure attribution.

**Architecture:** A dedicated Ansible role (`roles/custom_extensions/`) ingests custom bundles at the end of Stage 5 (`CLUSTER_READY`) from either a sideloaded local archive or remote URL (authenticated via Bearer token and mTLS) with SHA-256 integrity verification. A reusable runner task (`stages/execute_custom_stage.yml`) executes matching `<stage>.yml` plays immediately following core tasks in Stage 5, Stage 6, and Stage 7, safely attributing any custom task failures to the external playbook in state evidence files.

**Tech Stack:** Ansible 2.15+, Jinja2, Python 3.12, Pytest, Bash, Systemd, GDC Provisioner State Machine.

---

### File Structure & Responsibilities

| File Path | Responsibility |
| :--- | :--- |
| `src/ansible/roles/custom_extensions/defaults/main.yml` | Default variables for custom extensions (paths, timeouts, directories). |
| `src/ansible/roles/custom_extensions/tasks/main.yml` | Ingestion tasks: detect sideload, download remote bundle, verify SHA-256, unpack tarball, install `requirements.yml`. |
| `src/ansible/stages/execute_custom_stage.yml` | Standardized runner task: checks for `<stage>.yml`, includes tasks within `block/rescue`, formats failure evidence. |
| `src/ansible/stages/stage_cluster_ready.yml` | Modified to execute `roles/custom_extensions` before finalizing Stage 5. |
| `src/ansible/stages/stage_cluster_turnup.yml` | Modified to include `execute_custom_stage.yml` with `target_custom_stage: cluster_turnup`. |
| `src/ansible/stages/stage_post_cluster.yml` | Modified to include `execute_custom_stage.yml` with `target_custom_stage: post_cluster`. |
| `custom-data/examples/burnin-bundle/requirements.yml` | Sample dependency manifest for the reference burn-in bundle. |
| `custom-data/examples/burnin-bundle/cluster_turnup.yml` | Sample post-turnup custom tasks. |
| `custom-data/examples/burnin-bundle/post_cluster.yml` | Sample post-cluster burn-in test (creates namespace, validates pod reachability, tears down). |
| `docs/custom-playbook-extensions.md` | Comprehensive operator and developer guide for authoring, packaging, configuring, and debugging bundles. |
| `test/test_custom_extensions.py` | Pytest test suite covering schema, zero-config default, sideloading, SHA-256 validation, execution hooks, and failure attribution. |

---

### Task 1: Create Custom Extensions Role Defaults and Tasks

**Files:**
- Create: `src/ansible/roles/custom_extensions/defaults/main.yml`
- Create: `src/ansible/roles/custom_extensions/tasks/main.yml`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write the failing unit tests for role tasks and defaults**

```python
# test/test_custom_extensions.py
import os
import yaml
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULTS_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "roles", "custom_extensions", "defaults", "main.yml")
TASKS_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "roles", "custom_extensions", "tasks", "main.yml")

def test_custom_extensions_defaults_exist_and_valid():
    assert os.path.isfile(DEFAULTS_PATH), f"Defaults file missing at {DEFAULTS_PATH}"
    with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data is not None
    assert data.get("custom_extensions_base_dir") == "/var/gdc-install"
    assert data.get("custom_extensions_playbooks_dir") == "/var/gdc-install/custom-playbooks"
    assert data.get("custom_extensions_sideload_tarball") == "/var/gdc-install/custom-bundle.tar.gz"

def test_custom_extensions_tasks_exist_and_parseable():
    assert os.path.isfile(TASKS_PATH), f"Tasks file missing at {TASKS_PATH}"
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    assert isinstance(tasks, list)
    task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
    assert any("Check if sideloaded bundle exists" in n for n in task_names)
    assert any("Extract custom extension bundle" in n for n in task_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test/test_custom_extensions.py -v`  
Expected: FAIL with `Defaults file missing` or `FileNotFoundError`

- [ ] **Step 3: Implement defaults and tasks for `custom_extensions` role**

Create `src/ansible/roles/custom_extensions/defaults/main.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
custom_extensions_base_dir: "/var/gdc-install"
custom_extensions_playbooks_dir: "/var/gdc-install/custom-playbooks"
custom_extensions_sideload_tarball: "/var/gdc-install/custom-bundle.tar.gz"
custom_extensions_download_timeout: 300
```

Create `src/ansible/roles/custom_extensions/tasks/main.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-EXTENSION | Resolve custom extension configuration from machine_config"
  ansible.builtin.set_fact:
    _custom_ext_config: "{{ machine_config.custom_extensions | default({}) }}"
    _custom_bundle_tarball: "{{ custom_extensions_sideload_tarball }}"
    _custom_playbooks_path: "{{ custom_extensions_playbooks_dir }}"

- name: "GDC-EXTENSION | Check if sideloaded bundle exists on local filesystem"
  ansible.builtin.stat:
    path: "{{ _custom_bundle_tarball }}"
  register: _sideload_bundle_stat

- name: "GDC-EXTENSION | Download remote bundle if URL specified and not sideloaded"
  when:
    - not _sideload_bundle_stat.stat.exists
    - _custom_ext_config.bundle_url is defined
    - (_custom_ext_config.bundle_url | trim | length) > 0
  block:
    - name: "GDC-EXTENSION | Ensure client certificates presence is verified"
      ansible.builtin.stat:
        path: "/var/gdc-install/keys/client.crt"
      register: _ext_client_cert_stat

    - name: "GDC-EXTENSION | Fetch bundle tarball from configured URL"
      ansible.builtin.get_url:
        url: "{{ _custom_ext_config.bundle_url }}"
        dest: "{{ _custom_bundle_tarball }}"
        headers:
          Authorization: "Bearer {{ gdc_companion_api_key | default('') }}"
        client_cert: "{{ '/var/gdc-install/keys/client.crt' if _ext_client_cert_stat.stat.exists else omit }}"
        client_key: "{{ '/var/gdc-install/keys/client.key' if _ext_client_cert_stat.stat.exists else omit }}"
        validate_certs: false
        timeout: "{{ custom_extensions_download_timeout | default(300) }}"
        mode: '0640'
        owner: root
        group: root
      register: _bundle_download_result

- name: "GDC-EXTENSION | Re-check bundle presence after retrieval"
  ansible.builtin.stat:
    path: "{{ _custom_bundle_tarball }}"
    checksum_algorithm: sha256
  register: _active_bundle_stat

- name: "GDC-EXTENSION | Validate SHA-256 checksum if specified in configuration"
  when:
    - _active_bundle_stat.stat.exists
    - _custom_ext_config.sha256 is defined
    - (_custom_ext_config.sha256 | trim | length) > 0
  block:
    - name: "GDC-EXTENSION | Assert SHA-256 digest matches expected configuration"
      ansible.builtin.assert:
        that:
          - _active_bundle_stat.stat.checksum | lower == _custom_ext_config.sha256 | lower
        fail_msg: >-
          Security Alert: Checksum mismatch for custom extension bundle {{ _custom_bundle_tarball }}!
          Expected: {{ _custom_ext_config.sha256 | lower }}
          Actual:   {{ _active_bundle_stat.stat.checksum | lower }}
        success_msg: "Custom extension bundle integrity verified against SHA-256 checksum."

- name: "GDC-EXTENSION | Unpack and install bundle when present"
  when: _active_bundle_stat.stat.exists
  block:
    - name: "GDC-EXTENSION | Ensure destination playbooks directory exists"
      ansible.builtin.file:
        path: "{{ _custom_playbooks_path }}"
        state: directory
        owner: root
        group: root
        mode: '0750'

    - name: "GDC-EXTENSION | Extract custom extension bundle into playbooks directory"
      ansible.builtin.unarchive:
        src: "{{ _custom_bundle_tarball }}"
        dest: "{{ _custom_playbooks_path }}"
        remote_src: true
        owner: root
        group: root
        mode: 'u=rwX,g=rX,o='

    - name: "GDC-EXTENSION | Check for requirements.yml in unpacked bundle"
      ansible.builtin.stat:
        path: "{{ _custom_playbooks_path }}/requirements.yml"
      register: _requirements_stat

    - name: "GDC-EXTENSION | Install Ansible dependencies via galaxy if requirements.yml present"
      ansible.builtin.command:
        cmd: "ansible-galaxy install -r {{ _custom_playbooks_path }}/requirements.yml"
      when: _requirements_stat.stat.exists
      register: _galaxy_install_result
      changed_when: _galaxy_install_result.rc == 0

- name: "GDC-EXTENSION | Execute Stage 5 post-hook if cluster_ready.yml is present"
  ansible.builtin.include_tasks:
    file: "{{ playbook_dir }}/stages/execute_custom_stage.yml"
  vars:
    target_custom_stage: "cluster_ready"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest test/test_custom_extensions.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/custom_extensions/ test/test_custom_extensions.py
git commit -m "feat(ansible): create custom_extensions ingestion role and defaults"
```

---

### Task 2: Create Reusable Custom Stage Runner Task

**Files:**
- Create: `src/ansible/stages/execute_custom_stage.yml`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write test for `execute_custom_stage.yml`**

Add to `test/test_custom_extensions.py`:
```python
RUNNER_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "execute_custom_stage.yml")

def test_execute_custom_stage_structure():
    assert os.path.isfile(RUNNER_PATH), f"Runner file missing at {RUNNER_PATH}"
    with open(RUNNER_PATH, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    assert isinstance(tasks, list)
    task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
    assert any("Check for custom tasks: {{ target_custom_stage }}" in n for n in task_names)
    assert any("Execute custom {{ target_custom_stage }} tasks" in n for n in task_names)
    
    # Check that rescue block records external failure attribution
    exec_task = next(t for t in tasks if "Execute custom" in t.get("name", ""))
    assert "rescue" in exec_task
    rescue_tasks = exec_task["rescue"]
    assert any("Record failure evidence" in r.get("name", "") for r in rescue_tasks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_execute_custom_stage_structure" -v`  
Expected: FAIL with `Runner file missing`

- [ ] **Step 3: Implement `src/ansible/stages/execute_custom_stage.yml`**

Create `src/ansible/stages/execute_custom_stage.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-EXTENSION | Check for custom tasks: {{ target_custom_stage }}"
  ansible.builtin.stat:
    path: "/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml"
  register: _custom_stage_file_stat

- name: "GDC-EXTENSION | Execute custom {{ target_custom_stage }} tasks"
  when: _custom_stage_file_stat.stat.exists
  block:
    - name: "GDC-EXTENSION | Run {{ target_custom_stage }}.yml"
      ansible.builtin.include_tasks:
        file: "/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml"

    - name: "GDC-EXTENSION | Record successful custom extension execution in evidence"
      ansible.builtin.set_fact:
        custom_extension_evidence:
          executed: true
          custom_stage: "{{ target_custom_stage }}"
          custom_file: "/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml"
          status: "SUCCESS"
  rescue:
    - name: "GDC-EXTENSION | Record failure evidence attributing external playbook"
      ansible.builtin.set_fact:
        custom_extension_evidence:
          failed_in_custom_extension: true
          executed: true
          custom_stage: "{{ target_custom_stage }}"
          custom_file: "/var/gdc-install/custom-playbooks/{{ target_custom_stage }}.yml"
          message: "Execution failed within external custom playbook ({{ target_custom_stage }}.yml). Inspect /var/log/gdc-ansible-pull.log for details."
          error_detail: "{{ ansible_failed_result | default({}) }}"

    - name: "GDC-EXTENSION | Fail stage due to external playbook failure"
      ansible.builtin.fail:
        msg: "Execution failed within external custom playbook ({{ target_custom_stage }}.yml). Inspect /var/log/gdc-ansible-pull.log for details."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_execute_custom_stage_structure" -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/stages/execute_custom_stage.yml test/test_custom_extensions.py
git commit -m "feat(ansible): create reusable execute_custom_stage runner with failure attribution"
```

---

### Task 3: Integrate Custom Extension Hooks into Stages 5, 6, and 7

**Files:**
- Modify: `src/ansible/stages/stage_cluster_ready.yml`
- Modify: `src/ansible/stages/stage_cluster_turnup.yml`
- Modify: `src/ansible/stages/stage_post_cluster.yml`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write integration tests asserting presence of extension hooks in stages**

Add to `test/test_custom_extensions.py`:
```python
STAGE_CR_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_cluster_ready.yml")
STAGE_CT_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_cluster_turnup.yml")
STAGE_PC_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_post_cluster.yml")

def test_stages_wire_custom_extensions():
    # Stage 5 must run custom_extensions role
    with open(STAGE_CR_PATH, "r", encoding="utf-8") as f:
        cr_content = f.read()
    assert "name: custom_extensions" in cr_content
    assert "custom_extension" in cr_content

    # Stage 6 must invoke execute_custom_stage with cluster_turnup
    with open(STAGE_CT_PATH, "r", encoding="utf-8") as f:
        ct_content = f.read()
    assert "execute_custom_stage.yml" in ct_content
    assert 'target_custom_stage: "cluster_turnup"' in ct_content or "target_custom_stage: cluster_turnup" in ct_content
    assert "custom_extension" in ct_content

    # Stage 7 must invoke execute_custom_stage with post_cluster
    with open(STAGE_PC_PATH, "r", encoding="utf-8") as f:
        pc_content = f.read()
    assert "execute_custom_stage.yml" in pc_content
    assert 'target_custom_stage: "post_cluster"' in pc_content or "target_custom_stage: post_cluster" in pc_content
    assert "custom_extension" in pc_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_stages_wire_custom_extensions" -v`  
Expected: FAIL with `AssertionError: assert 'name: custom_extensions' in cr_content`

- [ ] **Step 3: Modify `stage_cluster_ready.yml`, `stage_cluster_turnup.yml`, and `stage_post_cluster.yml`**

1. In `src/ansible/stages/stage_cluster_ready.yml`, run `custom_extensions` role after GSM checks, and include `custom_extension` in `cluster_ready_evidence`:
```yaml
- name: "GDC-CR-EXT | Ingest and evaluate custom extensions"
  ansible.builtin.include_role:
    name: custom_extensions
```
Combine `custom_extension: (custom_extension_evidence | default({}))` into `cluster_ready_evidence`.

2. In `src/ansible/stages/stage_cluster_turnup.yml`, invoke `execute_custom_stage.yml` after `cluster_turnup` role, and combine `custom_extension: (custom_extension_evidence | default({}))` into `cluster_turnup_evidence`:
```yaml
- name: "GDC-CT-EXT | Execute custom turnup extensions if present"
  ansible.builtin.include_tasks:
    file: "{{ playbook_dir }}/stages/execute_custom_stage.yml"
  vars:
    target_custom_stage: "cluster_turnup"
```

3. In `src/ansible/stages/stage_post_cluster.yml`, invoke `execute_custom_stage.yml` after `config_sync.yml`, and combine `custom_extension: (custom_extension_evidence | default({}))` into `post_cluster_evidence`:
```yaml
- name: "GDC-PC-EXT | Execute custom post-cluster burn-in and workload extensions"
  ansible.builtin.include_tasks:
    file: "{{ playbook_dir }}/stages/execute_custom_stage.yml"
  vars:
    target_custom_stage: "post_cluster"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_stages_wire_custom_extensions" -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/stages/stage_cluster_ready.yml src/ansible/stages/stage_cluster_turnup.yml src/ansible/stages/stage_post_cluster.yml test/test_custom_extensions.py
git commit -m "feat(ansible): wire custom extension runner and evidence into stages 5, 6, and 7"
```

---

### Task 4: Provide Reference Burn-In Bundle Example

**Files:**
- Create: `custom-data/examples/burnin-bundle/requirements.yml`
- Create: `custom-data/examples/burnin-bundle/cluster_turnup.yml`
- Create: `custom-data/examples/burnin-bundle/post_cluster.yml`
- Create: `custom-data/examples/burnin-bundle/README.md`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write test validating the reference example bundle files**

Add to `test/test_custom_extensions.py`:
```python
EXAMPLE_DIR = os.path.join(PROJECT_ROOT, "custom-data", "examples", "burnin-bundle")

def test_reference_burnin_bundle_structure():
    assert os.path.isdir(EXAMPLE_DIR), f"Missing example dir at {EXAMPLE_DIR}"
    req_file = os.path.join(EXAMPLE_DIR, "requirements.yml")
    turnup_file = os.path.join(EXAMPLE_DIR, "cluster_turnup.yml")
    post_file = os.path.join(EXAMPLE_DIR, "post_cluster.yml")
    readme_file = os.path.join(EXAMPLE_DIR, "README.md")

    for fpath in [req_file, turnup_file, post_file, readme_file]:
        assert os.path.isfile(fpath), f"Missing example file {fpath}"

    with open(post_file, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    assert isinstance(tasks, list)
    task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
    assert any("Deploy burn-in test namespace" in n for n in task_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_reference_burnin_bundle_structure" -v`  
Expected: FAIL with `Missing example dir`

- [ ] **Step 3: Create reference example burn-in bundle files**

Create `custom-data/examples/burnin-bundle/requirements.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
collections: []
roles: []
```

Create `custom-data/examples/burnin-bundle/cluster_turnup.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "BURNIN-TURNUP | Log custom cluster turnup post-hook execution"
  ansible.builtin.debug:
    msg: "Custom cluster turnup post-hook executed successfully for cluster inception."
```

Create `custom-data/examples/burnin-bundle/post_cluster.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "BURNIN-POST | Deploy burn-in test namespace"
  ansible.builtin.command:
    cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf create namespace gdc-burnin --dry-run=client -o yaml | kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f -"
  register: _burnin_ns_create
  changed_when: _burnin_ns_create.rc == 0

- name: "BURNIN-POST | Deploy lightweight nginx burn-in pod"
  ansible.builtin.command:
    cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf run burnin-smoke --image=nginx:alpine --namespace=gdc-burnin --restart=Never"
  register: _burnin_pod_run
  changed_when: _burnin_pod_run.rc == 0
  failed_when: false

- name: "BURNIN-POST | Wait for burn-in pod to reach Running condition (timeout: 120s)"
  ansible.builtin.command:
    cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf wait --for=condition=Ready pod/burnin-smoke --namespace=gdc-burnin --timeout=120s"
  register: _burnin_pod_wait
  changed_when: false

- name: "BURNIN-POST | Tear down burn-in test namespace"
  ansible.builtin.command:
    cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf delete namespace gdc-burnin --timeout=60s"
  register: _burnin_ns_delete
  changed_when: _burnin_ns_delete.rc == 0
  failed_when: false
```

Create `custom-data/examples/burnin-bundle/README.md`:
```markdown
# Sample GDC Custom Playbook Burn-In Bundle

This directory provides a functional reference example of a custom playbook bundle conforming to `GDC-SPEC-017`.

## Packaging this Bundle
To generate a `.tar.gz` bundle for sideloading or serving via `gdc-companion`:

```bash
tar -czvf /var/gdc-install/custom-bundle.tar.gz -C custom-data/examples/burnin-bundle/ .
sha256sum /var/gdc-install/custom-bundle.tar.gz
```
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_reference_burnin_bundle_structure" -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add custom-data/examples/burnin-bundle/ test/test_custom_extensions.py
git commit -m "feat(examples): add reference burn-in custom playbook bundle"
```

---

### Task 5: Operator Documentation and Cross-References

**Files:**
- Create: `docs/custom-playbook-extensions.md`
- Modify: `docs/on-device-ansible.md`
- Modify: `PROGRESS.md`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write documentation verification test**

Add to `test/test_custom_extensions.py`:
```python
DOCS_EXT_PATH = os.path.join(PROJECT_ROOT, "docs", "custom-playbook-extensions.md")
DOCS_ON_DEVICE_PATH = os.path.join(PROJECT_ROOT, "docs", "on-device-ansible.md")

def test_custom_extensions_documentation():
    assert os.path.isfile(DOCS_EXT_PATH), f"Missing docs at {DOCS_EXT_PATH}"
    with open(DOCS_EXT_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Anti-Pattern Notice: Avoid Snowflake Clusters" in content
    assert "requirements.yml" in content
    assert "custom-bundle.tar.gz" in content

    with open(DOCS_ON_DEVICE_PATH, "r", encoding="utf-8") as f:
        on_device_content = f.read()
    assert "custom-playbook-extensions.md" in on_device_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_custom_extensions_documentation" -v`  
Expected: FAIL with `Missing docs at docs/custom-playbook-extensions.md`

- [ ] **Step 3: Author `docs/custom-playbook-extensions.md` and link in `docs/on-device-ansible.md` and `PROGRESS.md`**

1. Create `docs/custom-playbook-extensions.md` documenting:
   - Lifecycle integration points (Stages 5, 6, 7).
   - Ingestion methods: `gdc-companion` / remote URL with mTLS, or sideloaded tarball.
   - Integrity checking via SHA-256.
   - Bundle structure and dependencies.
   - Troubleshooting and failure logs (`/var/log/gdc-ansible-pull.log` and `/var/gdc-install/state/<stage>.json`).
   - Anti-Pattern warning against snowflake clusters.
2. Add reference link under Section 1 in `docs/on-device-ansible.md`.
3. Update `PROGRESS.md` noting the completion of Issue #19 feature development under Stage 6 and Stage 7.

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest test/test_custom_extensions.py -k "test_custom_extensions_documentation" -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/custom-playbook-extensions.md docs/on-device-ansible.md PROGRESS.md test/test_custom_extensions.py
git commit -m "docs: add operator guide for custom playbook extensions and link in progress tracker"
```

---

### Task 6: Full Test Suite Validation & Static Verification

**Files:**
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Run full unit test suite**

Run: `./venv/bin/pytest test/test_custom_extensions.py -v`  
Expected: All tests PASS (5/5)

- [ ] **Step 2: Run lint check on YAML and Python files**

Run: `./venv/bin/black --check test/test_custom_extensions.py`  
Expected: PASS

- [ ] **Step 3: Run existing regression test suite**

Run: `./venv/bin/pytest test/test_config_sync_tasks.py test/test_cluster_turnup.py -v`  
Expected: All existing tests PASS with zero regressions

- [ ] **Step 4: Commit and finalize**

```bash
git add .
git commit -m "chore(test): finalize test coverage and verification for custom playbook extensions"
```
