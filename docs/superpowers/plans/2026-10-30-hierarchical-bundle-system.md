# Hierarchical Bundle System & Stage Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the GDC custom playbook extension system from a flat conventions layout to a declarative, hierarchical bundle architecture with strict `manifest.yaml` stage gating, isolated stage asset folders (`bin/`, `oci/`, `pkg/`), full lifecycle stage execution (including `upkeep`), and an official `bundle_template.tar.gz`.

**Architecture:** Bundles are extracted to `/var/gdc-install/bundle/` during Stage 5 (`CLUSTER_READY`). Ingestion parses and validates `/var/gdc-install/bundle/manifest.yaml`, asserting that every declared stage has a corresponding `<stage>/playbook.yaml`, and persists `/var/gdc-install/state/bundle-manifest.json`. A reusable runner (`stages/execute_custom_stage.yml`) gates stage execution against `manifest.stages`, exposes standard asset path variables (`bundle_bin_dir`, `bundle_oci_dir`, `bundle_pkg_dir`), and executes `<stage>/playbook.yaml` with clear error attribution across Stages 5, 6, 7, and 8.

**Tech Stack:** Ansible 2.15+, Python 3.12, Pytest, YAML, Tarball/Gzip, Bash, GDC Provisioner State Machine.

---

### File Structure & Responsibilities

| File Path | Responsibility |
| :--- | :--- |
| `src/ansible/roles/custom_extensions/defaults/main.yml` | Sets defaults: `custom_extensions_bundle_dir: "/var/gdc-install/bundle"`, timeouts, and paths. |
| `src/ansible/roles/custom_extensions/tasks/main.yml` | Extracts bundle to `/var/gdc-install/bundle/`, enforces `manifest.yaml` presence and schema, writes `bundle-manifest.json`, normalizes stage playbooks. |
| `src/ansible/stages/execute_custom_stage.yml` | Gates execution against `manifest.stages`, exports context variables (`bundle_stage_dir`, `bundle_bin_dir`, etc.), executes `<stage>/playbook.yaml`, and records attribution. |
| `src/ansible/stages/stage_upkeep.yml` | Wires in `execute_custom_stage.yml` for `target_custom_stage: upkeep` and merges evidence into `update-upkeep.json`. |
| `custom-data/templates/bundle_template/manifest.yaml` | Fully-commented canonical manifest template with version `0.0.1`. |
| `custom-data/templates/bundle_template/VERSION` | Semantic version file (`0.0.1`). |
| `custom-data/templates/bundle_template/<stage>/playbook.yaml` | Skeleton playbooks for `cluster_ready`, `cluster_turnup`, `post_cluster`, and `upkeep`. |
| `custom-data/templates/bundle_template.tar.gz` | Packaged reference bundle archive for distribution and `gdc-companion` integration. |
| `custom-data/examples/burnin-bundle/` | Migrated reference burn-in bundle using the new hierarchical layout with `manifest.yaml` and `VERSION`. |
| `docs/custom-playbook-extensions.md` | Operator guide updated with the hierarchical layout, manifest reference, and asset directory usage. |
| `docs/specs/17-custom-playbook-lifecycle-extensions.md` | Specification updated to reflect hierarchical directory layout and `manifest.yaml` schema authority. |
| `docs/specs/18-gdc-companion-bundle-service-spec.md` | Specification updated to document manifest inspection and stage identification. |
| `test/test_custom_extensions.py` | Pytest suite testing manifest gating, asset variables, Upkeep wiring, and template integrity. |

---

### Task 1: Update Role Defaults and Unit Tests for Hierarchical Ingestion

**Files:**
- Modify: `src/ansible/roles/custom_extensions/defaults/main.yml`
- Modify: `test/test_custom_extensions.py`

- [ ] **Step 1: Update unit tests in `test/test_custom_extensions.py` to expect `/var/gdc-install/bundle`**

Update `test_custom_extensions_defaults_exist_and_valid` in `test/test_custom_extensions.py`:
```python
def test_custom_extensions_defaults_exist_and_valid():
    assert os.path.isfile(DEFAULTS_PATH), f"Defaults file missing at {DEFAULTS_PATH}"
    with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data is not None
    assert data.get("custom_extensions_base_dir") == "/var/gdc-install"
    assert (
        data.get("custom_extensions_bundle_dir")
        == "/var/gdc-install/bundle"
    )
    assert (
        data.get("custom_extensions_sideload_tarball")
        == "/var/gdc-install/custom-bundle.tar.gz"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_custom_extensions.py -k "test_custom_extensions_defaults" -v`  
Expected: FAIL with `AssertionError: assert None == '/var/gdc-install/bundle'`

- [ ] **Step 3: Update `src/ansible/roles/custom_extensions/defaults/main.yml`**

```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
custom_extensions_base_dir: "/var/gdc-install"
custom_extensions_bundle_dir: "/var/gdc-install/bundle"
custom_extensions_playbooks_dir: "/var/gdc-install/bundle"
custom_extensions_sideload_tarball: "/var/gdc-install/custom-bundle.tar.gz"
custom_extensions_manifest_state_file: "/var/gdc-install/state/bundle-manifest.json"
custom_extensions_download_timeout: 300
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_custom_extensions.py -k "test_custom_extensions_defaults" -v`  
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ansible/roles/custom_extensions/defaults/main.yml test/test_custom_extensions.py
git commit -m "feat(ansible): configure custom_extensions bundle_dir default to /var/gdc-install/bundle"
```

---

### Task 2: Implement Strict Manifest Validation & Ingestion

**Files:**
- Modify: `src/ansible/roles/custom_extensions/tasks/main.yml`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Add unit test in `test/test_custom_extensions.py` for manifest ingestion and validation tasks**

Add test to `test/test_custom_extensions.py`:
```python
def test_custom_extensions_tasks_enforce_manifest():
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
    for t in tasks:
        if isinstance(t, dict) and "block" in t:
            task_names.extend(
                [b.get("name", "") for b in t["block"] if isinstance(b, dict)]
            )
    assert any("manifest.yaml" in n for n in task_names)
    assert any("bundle-manifest.json" in n or "manifest" in n.lower() for n in task_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_custom_extensions.py -k "test_custom_extensions_tasks_enforce_manifest" -v`  
Expected: FAIL

- [ ] **Step 3: Update `src/ansible/roles/custom_extensions/tasks/main.yml`**

Replace `src/ansible/roles/custom_extensions/tasks/main.yml` with:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-EXTENSION | Resolve custom extension configuration from machine_config"
  ansible.builtin.set_fact:
    _custom_ext_config: "{{ (machine_config | default({})).custom_extensions | default({}) }}"
    _custom_bundle_tarball: "{{ custom_extensions_sideload_tarball }}"
    _custom_bundle_path: "{{ custom_extensions_bundle_dir | default('/var/gdc-install/bundle') }}"

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

    - name: "GDC-EXTENSION | Resolve normalized bundle URL"
      ansible.builtin.set_fact:
        _resolved_bundle_url: >-
          {{
            (_custom_ext_config.bundle_url | trim)
            if (_custom_ext_config.bundle_url | trim is match('^https?://'))
            else (
              ((gdc_companion_base_url | default('https://gdc-companion.internal/')) | trim('/')) + '/' + ((_custom_ext_config.bundle_url | trim) | regex_replace('^/+', ''))
            )
          }}

    - name: "GDC-EXTENSION | Fetch bundle tarball from configured URL"
      ansible.builtin.get_url:
        url: "{{ _resolved_bundle_url }}"
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
    - name: "GDC-EXTENSION | Ensure destination bundle directory exists"
      ansible.builtin.file:
        path: "{{ _custom_bundle_path }}"
        state: directory
        owner: root
        group: root
        mode: '0750'

    - name: "GDC-EXTENSION | Extract custom extension bundle into bundle directory"
      ansible.builtin.unarchive:
        src: "{{ _custom_bundle_tarball }}"
        dest: "{{ _custom_bundle_path }}"
        remote_src: true
        owner: root
        group: root
        mode: 'u=rwX,g=rX,o='

    - name: "GDC-EXTENSION | Verify manifest.yaml exists in unpacked bundle"
      ansible.builtin.stat:
        path: "{{ _custom_bundle_path }}/manifest.yaml"
      register: _bundle_manifest_stat

    - name: "GDC-EXTENSION | Assert bundle contains mandatory manifest.yaml"
      ansible.builtin.assert:
        that:
          - _bundle_manifest_stat.stat.exists
        fail_msg: "Security Alert: Custom extension bundle {{ _custom_bundle_tarball }} is invalid: missing mandatory manifest.yaml!"
        success_msg: "Bundle manifest.yaml presence confirmed."

    - name: "GDC-EXTENSION | Validate manifest.yaml schema and persist bundle-manifest.json"
      ansible.builtin.shell: |
        python3 - << 'EOF'
        import os, sys, json, yaml

        bundle_path = "{{ _custom_bundle_path }}"
        manifest_file = os.path.join(bundle_path, "manifest.yaml")
        state_file = "{{ custom_extensions_manifest_state_file | default('/var/gdc-install/state/bundle-manifest.json') }}"

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = yaml.safe_load(f)
        except Exception as e:
            print(f"ERROR: Cannot parse manifest.yaml: {e}", file=sys.stderr)
            sys.exit(1)

        if not isinstance(manifest, dict):
            print("ERROR: manifest.yaml must be a YAML dictionary.", file=sys.stderr)
            sys.exit(1)

        for req in ["name", "version", "stages"]:
            if req not in manifest or not manifest[req]:
                print(f"ERROR: manifest.yaml is missing required field '{req}'.", file=sys.stderr)
                sys.exit(1)

        if not isinstance(manifest["stages"], list) or len(manifest["stages"]) == 0:
            print("ERROR: manifest.yaml 'stages' must be a non-empty list.", file=sys.stderr)
            sys.exit(1)

        # Validate that each declared stage has a corresponding <stage>/playbook.yaml
        for stage in manifest["stages"]:
            playbook_path = os.path.join(bundle_path, stage, "playbook.yaml")
            if not os.path.isfile(playbook_path):
                print(f"ERROR: Declared stage '{stage}' missing required playbook at {playbook_path}", file=sys.stderr)
                sys.exit(1)

        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as sf:
            json.dump(manifest, sf, indent=2)

        print(f"Validated manifest for bundle '{manifest['name']}' v{manifest['version']} with stages: {manifest['stages']}")
        EOF
      args:
        executable: /bin/bash
      register: _manifest_validation_result

    - name: "GDC-EXTENSION | Auto-normalize custom stage playbooks into task lists if wrapped in plays"
      ansible.builtin.shell: |
        python3 - << 'EOF'
        import os, sys, json, yaml

        bundle_path = "{{ _custom_bundle_path }}"
        state_file = "{{ custom_extensions_manifest_state_file | default('/var/gdc-install/state/bundle-manifest.json') }}"

        if not os.path.isfile(state_file):
            sys.exit(0)

        with open(state_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        for stage in manifest.get("stages", []):
            fpath = os.path.join(bundle_path, stage, "playbook.yaml")
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as pf:
                    data = yaml.safe_load(pf)
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    if "tasks" in data[0] or "hosts" in data[0]:
                        extracted_tasks = []
                        for play in data:
                            if isinstance(play, dict) and "tasks" in play and isinstance(play["tasks"], list):
                                extracted_tasks.extend(play["tasks"])
                        if extracted_tasks:
                            with open(fpath, "w", encoding="utf-8") as out_f:
                                yaml.safe_dump(extracted_tasks, out_f, default_flow_style=False, sort_keys=False)
                            print(f"Normalized {stage}/playbook.yaml from playbook to task list.")
            except Exception as e:
                print(f"Warning: could not normalize {stage}/playbook.yaml: {e}", file=sys.stderr)
        EOF
      args:
        executable: /bin/bash
      changed_when: false

    - name: "GDC-EXTENSION | Check for requirements.yml in unpacked bundle"
      ansible.builtin.stat:
        path: "{{ _custom_bundle_path }}/requirements.yml"
      register: _requirements_stat

    - name: "GDC-EXTENSION | Install Ansible dependencies via galaxy if requirements.yml present"
      ansible.builtin.command:
        cmd: "ansible-galaxy install -r {{ _custom_bundle_path }}/requirements.yml"
      when: _requirements_stat.stat.exists
      register: _galaxy_install_result
      changed_when: _galaxy_install_result.rc == 0

- name: "GDC-EXTENSION | Execute Stage 5 post-hook if cluster_ready is declared"
  ansible.builtin.include_tasks:
    file: "{{ playbook_dir }}/stages/execute_custom_stage.yml"
  vars:
    target_custom_stage: "cluster_ready"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_custom_extensions.py -k "test_custom_extensions_tasks_enforce_manifest" -v`  
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ansible/roles/custom_extensions/tasks/main.yml test/test_custom_extensions.py
git commit -m "feat(ansible): enforce manifest.yaml validation and per-stage playbook checks during bundle ingestion"
```

---

### Task 3: Upgrade Reusable Stage Runner for Manifest Gating & Asset Context Variables

**Files:**
- Modify: `src/ansible/stages/execute_custom_stage.yml`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write failing unit test in `test/test_custom_extensions.py` for runner manifest gating**

Add test to `test/test_custom_extensions.py`:
```python
def test_execute_custom_stage_manifest_gating():
    with open(RUNNER_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert "bundle-manifest.json" in content
    assert "bundle_bin_dir" in content
    assert "bundle_oci_dir" in content
    assert "bundle_pkg_dir" in content
    assert "bundle_stage_dir" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_custom_extensions.py -k "test_execute_custom_stage_manifest_gating" -v`  
Expected: FAIL

- [ ] **Step 3: Update `src/ansible/stages/execute_custom_stage.yml`**

Replace `src/ansible/stages/execute_custom_stage.yml` with:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-EXTENSION | Reset custom extension evidence for {{ target_custom_stage | default('unknown') }}"
  ansible.builtin.set_fact:
    custom_extension_evidence: {}
    _custom_bundle_root: "{{ custom_extensions_bundle_dir | default('/var/gdc-install/bundle') }}"
    _custom_manifest_file: "{{ custom_extensions_manifest_state_file | default('/var/gdc-install/state/bundle-manifest.json') }}"

- name: "GDC-EXTENSION | Check if bundle-manifest.json exists"
  ansible.builtin.stat:
    path: "{{ _custom_manifest_file }}"
  register: _active_manifest_stat

- name: "GDC-EXTENSION | Evaluate bundle manifest and gate stage {{ target_custom_stage }}"
  when: _active_manifest_stat.stat.exists
  block:
    - name: "GDC-EXTENSION | Slurp bundle manifest state"
      ansible.builtin.slurp:
        src: "{{ _custom_manifest_file }}"
      register: _slurped_manifest_state

    - name: "GDC-EXTENSION | Parse active bundle manifest"
      ansible.builtin.set_fact:
        _active_bundle_manifest: "{{ _slurped_manifest_state.content | b64decode | from_json }}"

    - name: "GDC-EXTENSION | Check if stage {{ target_custom_stage }} is declared in manifest"
      ansible.builtin.set_fact:
        _stage_enabled_in_manifest: "{{ target_custom_stage in (_active_bundle_manifest.stages | default([])) }}"
        _custom_stage_dir: "{{ _custom_bundle_root }}/{{ target_custom_stage }}"
        _custom_stage_playbook_file: "{{ _custom_bundle_root }}/{{ target_custom_stage }}/playbook.yaml"

    - name: "GDC-EXTENSION | Notice: Stage not declared in bundle manifest"
      ansible.builtin.debug:
        msg: >-
          [GDC-EXTENSION] Stage '{{ target_custom_stage }}' is not declared in bundle manifest ({{ _active_bundle_manifest.name | default('unknown') }}).
          Active stages: {{ _active_bundle_manifest.stages | default([]) }}. Skipping execution.
      when: not _stage_enabled_in_manifest | bool

    - name: "GDC-EXTENSION | Check for custom stage playbook: {{ _custom_stage_playbook_file }}"
      ansible.builtin.stat:
        path: "{{ _custom_stage_playbook_file }}"
      register: _custom_stage_file_stat
      when: _stage_enabled_in_manifest | bool

    - name: "GDC-EXTENSION | Execute custom {{ target_custom_stage }} tasks"
      when:
        - _stage_enabled_in_manifest | bool
        - _custom_stage_file_stat.stat.exists
      block:
        - name: "GDC-EXTENSION | Validate and normalize {{ target_custom_stage }}/playbook.yaml if wrapped in play"
          ansible.builtin.shell: |
            python3 - << 'EOF'
            import sys, yaml
            fpath = "{{ _custom_stage_playbook_file }}"
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    if "hosts" in data[0] or "gather_facts" in data[0]:
                        extracted_tasks = []
                        for play in data:
                            if isinstance(play, dict) and "tasks" in play and isinstance(play["tasks"], list):
                                extracted_tasks.extend(play["tasks"])
                        if extracted_tasks:
                            with open(fpath, "w", encoding="utf-8") as out_f:
                                yaml.safe_dump(extracted_tasks, out_f, default_flow_style=False, sort_keys=False)
                            print("NORMALIZED")
                            sys.exit(0)
                        else:
                            print("INVALID_PLAYBOOK_NO_TASKS", file=sys.stderr)
                            sys.exit(1)
                print("VALID")
                sys.exit(0)
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)
                sys.exit(2)
            EOF
          args:
            executable: /bin/bash
          register: _custom_stage_normalize_res
          changed_when: "'NORMALIZED' in _custom_stage_normalize_res.stdout"

        - name: "GDC-EXTENSION | Run {{ target_custom_stage }}/playbook.yaml with asset context"
          ansible.builtin.include_tasks:
            file: "{{ _custom_stage_playbook_file }}"
          vars:
            bundle_root_dir: "{{ _custom_bundle_root }}"
            bundle_stage_dir: "{{ _custom_stage_dir }}"
            bundle_bin_dir: "{{ _custom_stage_dir }}/bin"
            bundle_oci_dir: "{{ _custom_stage_dir }}/oci"
            bundle_pkg_dir: "{{ _custom_stage_dir }}/pkg"

        - name: "GDC-EXTENSION | Record successful custom extension execution in evidence"
          ansible.builtin.set_fact:
            custom_extension_evidence:
              executed: true
              custom_stage: "{{ target_custom_stage }}"
              custom_file: "{{ _custom_stage_playbook_file }}"
              bundle_name: "{{ _active_bundle_manifest.name | default('unknown') }}"
              bundle_version: "{{ _active_bundle_manifest.version | default('unknown') }}"
              status: "SUCCESS"
      rescue:
        - name: "GDC-EXTENSION | Record failure evidence attributing external playbook"
          ansible.builtin.set_fact:
            custom_extension_evidence:
              failed_in_custom_extension: true
              executed: true
              custom_stage: "{{ target_custom_stage }}"
              custom_file: "{{ _custom_stage_playbook_file }}"
              bundle_name: "{{ _active_bundle_manifest.name | default('unknown') }}"
              bundle_version: "{{ _active_bundle_manifest.version | default('unknown') }}"
              message: "Execution failed within external custom playbook ({{ target_custom_stage }}/playbook.yaml). Inspect /var/log/gdc-ansible-pull.log for details."
              error_detail: "{{ ansible_failed_result | default({}) }}"

        - name: "GDC-EXTENSION | Fail stage due to external playbook failure"
          ansible.builtin.fail:
            msg: "Execution failed within external custom playbook ({{ target_custom_stage }}/playbook.yaml). Inspect /var/log/gdc-ansible-pull.log for details."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_custom_extensions.py -k "test_execute_custom_stage" -v`  
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ansible/stages/execute_custom_stage.yml test/test_custom_extensions.py
git commit -m "feat(ansible): add manifest stage gating and standard asset context variables to stage runner"
```

---

### Task 4: Wire Stage 8 (`UPKEEP`) Lifecycle Extension Hook

**Files:**
- Modify: `src/ansible/stages/stage_upkeep.yml`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write failing unit test in `test/test_custom_extensions.py` asserting all 4 stages wire custom extensions**

Update `test_stages_wire_custom_extensions` in `test/test_custom_extensions.py`:
```python
def test_stages_wire_custom_extensions():
    STAGE_UPKEEP_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_upkeep.yml")

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

    # Stage 8 must invoke execute_custom_stage with upkeep
    with open(STAGE_UPKEEP_PATH, "r", encoding="utf-8") as f:
        upkeep_content = f.read()
    assert "execute_custom_stage.yml" in upkeep_content
    assert 'target_custom_stage: "upkeep"' in upkeep_content or "target_custom_stage: upkeep" in upkeep_content
    assert "custom_extension" in upkeep_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_custom_extensions.py -k "test_stages_wire_custom_extensions" -v`  
Expected: FAIL on Stage 8 assertions

- [ ] **Step 3: Modify `src/ansible/stages/stage_upkeep.yml` to wire in custom extension execution**

In `src/ansible/stages/stage_upkeep.yml`, add the custom extension call after the core `upkeep` role and merge `custom_extension` into `upkeep_evidence`:
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

- name: "GDC-UPKEEP-EXT | Execute custom upkeep extensions if declared in manifest"
  ansible.builtin.include_tasks:
    file: execute_custom_stage.yml
  vars:
    target_custom_stage: "upkeep"

- name: "GDC-TIMING | Calculate Upkeep timing facts"
  ansible.builtin.set_fact:
    upkeep_end_time: "{{ now(utc=true, fmt='%Y-%m-%dT%H:%M:%SZ') }}"
    upkeep_duration_seconds: "{{ [(now(utc=true).strftime('%s') | int) - (upkeep_start_epoch | int), 0] | max }}"

- name: "GDC-EVIDENCE | Update Upkeep Evidence Timing and Custom Extension"
  ansible.builtin.set_fact:
    upkeep_evidence: >-
      {{
        (upkeep_evidence | default({}))
        | combine({
            'timing': {
              'start_time': upkeep_start_time,
              'end_time': upkeep_end_time,
              'duration_seconds': upkeep_duration_seconds | int,
              'overall_provisioning_start_time': provisioning_start_time | default(upkeep_start_time)
            },
            'custom_extension': (custom_extension_evidence | default({}))
          })
      }}

- name: "GDC-STATE | Write Upkeep completion state"
  ansible.builtin.copy:
    dest: /var/gdc-install/state/update-upkeep.json
    owner: root
    group: root
    mode: '0644'
    content: |
      {
        "stage": "UPDATE_UPKEEP",
        "status": "{{ 'completed' if (upkeep_evidence.provision_timer_configured and upkeep_evidence.desired_state_timer_configured) else 'failed' }}",
        "timestamp": "{{ upkeep_end_time }}",
        "evidence": {{ upkeep_evidence | to_json }}
      }

- name: "GDC-STATE | Create upkeep.json compatibility symlink"
  ansible.builtin.file:
    src: /var/gdc-install/state/update-upkeep.json
    dest: /var/gdc-install/state/upkeep.json
    state: link
    force: true

- name: "GDC-STATE | Update Upkeep fact in-memory"
  ansible.builtin.set_fact:
    upkeep_state: { "status": "{{ 'completed' if (upkeep_evidence.provision_timer_configured and upkeep_evidence.desired_state_timer_configured) else 'failed' }}" }

- name: "GDC-STATE | Trigger Post-Stage Telemetry"
  ansible.builtin.shell: |
    if [ -x /usr/local/bin/gdc-collector ]; then
      /usr/local/bin/gdc-collector --stage upkeep --companion-url="{{ gdc_companion_reports_url | default('') }}"
    fi
  changed_when: false
  failed_when: false

- name: "GDC-UPKEEP | Assert Upkeep configuration criteria met"
  ansible.builtin.assert:
    that:
      - upkeep_evidence.provision_timer_configured | bool
      - upkeep_evidence.desired_state_timer_configured | bool
    fail_msg: "Upkeep configuration failed: Systemd timers not configured."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_custom_extensions.py -k "test_stages_wire_custom_extensions" -v`  
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ansible/stages/stage_upkeep.yml test/test_custom_extensions.py
git commit -m "feat(ansible): wire custom lifecycle extension runner and evidence into Stage 8 upkeep"
```

---

### Task 5: Scaffold Reusable `bundle_template` Directory and `bundle_template.tar.gz`

**Files:**
- Create: `custom-data/templates/bundle_template/manifest.yaml`
- Create: `custom-data/templates/bundle_template/VERSION`
- Create: `custom-data/templates/bundle_template/cluster_ready/playbook.yaml`
- Create: `custom-data/templates/bundle_template/cluster_ready/bin/.gitkeep`
- Create: `custom-data/templates/bundle_template/cluster_ready/oci/.gitkeep`
- Create: `custom-data/templates/bundle_template/cluster_ready/pkg/.gitkeep`
- Create: `custom-data/templates/bundle_template/cluster_turnup/playbook.yaml`
- Create: `custom-data/templates/bundle_template/cluster_turnup/bin/.gitkeep`
- Create: `custom-data/templates/bundle_template/cluster_turnup/oci/.gitkeep`
- Create: `custom-data/templates/bundle_template/cluster_turnup/pkg/.gitkeep`
- Create: `custom-data/templates/bundle_template/post_cluster/playbook.yaml`
- Create: `custom-data/templates/bundle_template/post_cluster/bin/.gitkeep`
- Create: `custom-data/templates/bundle_template/post_cluster/oci/.gitkeep`
- Create: `custom-data/templates/bundle_template/post_cluster/pkg/.gitkeep`
- Create: `custom-data/templates/bundle_template/upkeep/playbook.yaml`
- Create: `custom-data/templates/bundle_template/upkeep/bin/.gitkeep`
- Create: `custom-data/templates/bundle_template/upkeep/oci/.gitkeep`
- Create: `custom-data/templates/bundle_template/upkeep/pkg/.gitkeep`
- Create: `custom-data/templates/bundle_template.tar.gz`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Write failing unit test in `test/test_custom_extensions.py` for template existence and archive structure**

Add test to `test/test_custom_extensions.py`:
```python
def test_bundle_template_structure_and_archive():
    TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "custom-data", "templates", "bundle_template")
    TEMPLATE_TARBALL = os.path.join(PROJECT_ROOT, "custom-data", "templates", "bundle_template.tar.gz")

    assert os.path.isdir(TEMPLATE_DIR), f"Template directory missing: {TEMPLATE_DIR}"
    assert os.path.isfile(TEMPLATE_TARBALL), f"Template tarball missing: {TEMPLATE_TARBALL}"

    manifest_file = os.path.join(TEMPLATE_DIR, "manifest.yaml")
    version_file = os.path.join(TEMPLATE_DIR, "VERSION")
    assert os.path.isfile(manifest_file), "Missing manifest.yaml in template"
    assert os.path.isfile(version_file), "Missing VERSION in template"

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    assert manifest.get("version") == "0.0.1"
    with open(version_file, "r", encoding="utf-8") as f:
        assert f.read().strip() == "0.0.1"

    for stage in ["cluster_ready", "cluster_turnup", "post_cluster", "upkeep"]:
        stage_dir = os.path.join(TEMPLATE_DIR, stage)
        assert os.path.isdir(stage_dir), f"Missing stage directory {stage_dir}"
        assert os.path.isfile(os.path.join(stage_dir, "playbook.yaml")), f"Missing playbook.yaml in {stage}"
        for folder in ["bin", "oci", "pkg"]:
            assert os.path.isdir(os.path.join(stage_dir, folder)), f"Missing folder {folder} in {stage}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_custom_extensions.py -k "test_bundle_template_structure_and_archive" -v`  
Expected: FAIL with `AssertionError: Template directory missing`

- [ ] **Step 3: Create files for `bundle_template/`**

Create `custom-data/templates/bundle_template/manifest.yaml`:
```yaml
# ==============================================================================
# GDC Custom Playbook Lifecycle Extension Manifest
# Specification: GDC-SPEC-017 & GDC-SPEC-018
# ==============================================================================

# Human-readable identifier for this extension bundle
name: "bundle-template"

# Upstream origin / CI-CD pipeline source tracking URI
origin: "https://git.internal/gdc/platform/bundles/bundle-template"

# Detailed description of the purpose, hardening, or tests run by this bundle
description: |
  Canonical reference template for GDC lifecycle playbook extension bundles.
  Demonstrates modular per-stage tasks and convention folders (bin, oci, pkg).

# Semantic version matching the VERSION file
version: "0.0.1"

# Ordered list of lifecycle stages enabled for execution.
# Valid options: cluster_ready, cluster_turnup, post_cluster, upkeep.
# Only stages listed below will execute, even if stage directories exist on disk.
stages:
  - cluster_ready
  - cluster_turnup
  - post_cluster
  - upkeep
```

Create `custom-data/templates/bundle_template/VERSION`:
```text
0.0.1
```

Create skeleton `playbook.yaml` in each stage directory (`cluster_ready`, `cluster_turnup`, `post_cluster`, `upkeep`) showing usage of `bundle_bin_dir`, `bundle_oci_dir`, `bundle_pkg_dir`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "TEMPLATE-STAGE | Log custom lifecycle extension hook start"
  ansible.builtin.debug:
    msg: "Executing custom lifecycle hook for stage from {{ bundle_stage_dir }}"

# Convention folders:
# - {{ bundle_bin_dir }}: Binaries & scripts to chmod +x or execute
# - {{ bundle_oci_dir }}: Container images (*.tar) to load via nerdctl/crictl
# - {{ bundle_pkg_dir }}: Debian packages (*.deb) to install via dpkg/apt
```

And `.gitkeep` in each `bin/`, `oci/`, `pkg/` subdirectory.

- [ ] **Step 4: Package `bundle_template.tar.gz`**

Run:
```bash
tar -czvf custom-data/templates/bundle_template.tar.gz -C custom-data/templates/bundle_template .
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest test/test_custom_extensions.py -k "test_bundle_template_structure_and_archive" -v`  
Expected: PASS

- [ ] **Step 6: Commit changes**

```bash
git add custom-data/templates/ test/test_custom_extensions.py
git commit -m "feat(bundle): scaffold canonical bundle_template and bundle_template.tar.gz"
```

---

### Task 6: Migrate Reference Burn-In Bundle to Hierarchical Layout

**Files:**
- Modify: `custom-data/examples/burnin-bundle/`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Update unit tests in `test/test_custom_extensions.py` for burnin bundle layout**

Update `test_reference_burnin_bundle_structure` in `test/test_custom_extensions.py`:
```python
def test_reference_burnin_bundle_structure():
    assert os.path.isdir(EXAMPLE_DIR), f"Missing example dir at {EXAMPLE_DIR}"
    manifest_file = os.path.join(EXAMPLE_DIR, "manifest.yaml")
    version_file = os.path.join(EXAMPLE_DIR, "VERSION")
    req_file = os.path.join(EXAMPLE_DIR, "requirements.yml")
    readme_file = os.path.join(EXAMPLE_DIR, "README.md")
    turnup_file = os.path.join(EXAMPLE_DIR, "cluster_turnup", "playbook.yaml")
    post_file = os.path.join(EXAMPLE_DIR, "post_cluster", "playbook.yaml")

    for fpath in [manifest_file, version_file, req_file, turnup_file, post_file, readme_file]:
        assert os.path.isfile(fpath), f"Missing example file {fpath}"

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    assert "cluster_turnup" in manifest.get("stages", [])
    assert "post_cluster" in manifest.get("stages", [])

    with open(post_file, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    assert isinstance(tasks, list)
    task_names = []
    for t in tasks:
        if isinstance(t, dict):
            task_names.append(t.get("name", ""))
            for sub in t.get("block", []) + t.get("always", []):
                if isinstance(sub, dict):
                    task_names.append(sub.get("name", ""))
    assert any("Deploy burn-in test namespace" in n for n in task_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_custom_extensions.py -k "test_reference_burnin_bundle_structure" -v`  
Expected: FAIL

- [ ] **Step 3: Restructure `custom-data/examples/burnin-bundle/`**

1. Create `custom-data/examples/burnin-bundle/manifest.yaml`:
```yaml
# ==============================================================================
# GDC Custom Playbook Lifecycle Extension Manifest - Burn-In Suite Reference
# ==============================================================================
name: "burnin-suite"
origin: "https://git.internal/gdc/platform/bundles/burnin-suite"
description: |
  Reference hardware burn-in and workload validation bundle for GDC Bare Metal.
version: "1.0.0"
stages:
  - cluster_turnup
  - post_cluster
```
2. Create `custom-data/examples/burnin-bundle/VERSION`:
```text
1.0.0
```
3. Move `custom-data/examples/burnin-bundle/cluster_turnup.yml` to `custom-data/examples/burnin-bundle/cluster_turnup/playbook.yaml`.
4. Move `custom-data/examples/burnin-bundle/post_cluster.yml` to `custom-data/examples/burnin-bundle/post_cluster/playbook.yaml`.
5. Create empty convention directories `bin/`, `oci/`, `pkg/` with `.gitkeep` in each stage directory.
6. Update `custom-data/examples/burnin-bundle/README.md`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_custom_extensions.py -k "test_reference_burnin_bundle_structure" -v`  
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add custom-data/examples/burnin-bundle/ test/test_custom_extensions.py
git commit -m "refactor(bundle): migrate burnin-bundle reference example to hierarchical layout with manifest.yaml"
```

---

### Task 7: Update Documentation and Specification References

**Files:**
- Modify: `docs/specs/17-custom-playbook-lifecycle-extensions.md`
- Modify: `docs/specs/18-gdc-companion-bundle-service-spec.md`
- Modify: `docs/custom-playbook-extensions.md`
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Update documentation test in `test/test_custom_extensions.py`**

Ensure `test_custom_extensions_documentation` verifies that `manifest.yaml` and the hierarchical structure are documented.
```python
def test_custom_extensions_documentation():
    assert os.path.isfile(DOCS_EXT_PATH), f"Missing docs at {DOCS_EXT_PATH}"
    with open(DOCS_EXT_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert "manifest.yaml" in content
    assert "Anti-Pattern Notice: Avoid Snowflake Clusters" in content
    assert "bundle_template.tar.gz" in content
```

- [ ] **Step 2: Update `docs/custom-playbook-extensions.md`**

Document:
- Hierarchical structure with `<stage>/playbook.yaml`, `bin/`, `oci/`, `pkg/`.
- `manifest.yaml` schema and rules.
- Context variables (`bundle_bin_dir`, `bundle_oci_dir`, `bundle_pkg_dir`).
- Use of `bundle_template.tar.gz`.

- [ ] **Step 3: Update `docs/specs/17-custom-playbook-lifecycle-extensions.md` and `docs/specs/18-gdc-companion-bundle-service-spec.md`**

Update specifications to formalize `manifest.yaml` as the schema authority and document stage gating.

- [ ] **Step 4: Run all unit tests**

Run: `pytest test/test_custom_extensions.py -v`  
Expected: All tests PASS

- [ ] **Step 5: Commit documentation updates**

```bash
git add docs/custom-playbook-extensions.md docs/specs/17-custom-playbook-lifecycle-extensions.md docs/specs/18-gdc-companion-bundle-service-spec.md test/test_custom_extensions.py
git commit -m "docs(bundle): update lifecycle extension and companion specs to hierarchical bundle format"
```

---

### Task 8: End-to-End Test Suite Run and Verification

**Files:**
- Test: `test/test_custom_extensions.py`

- [ ] **Step 1: Run full pytest suite for custom extensions**

Run: `pytest test/test_custom_extensions.py -v`  
Expected: All tests pass

- [ ] **Step 2: Run git status and diff check to verify clean state**

Run: `git status`  
Expected: Clean working tree

---
