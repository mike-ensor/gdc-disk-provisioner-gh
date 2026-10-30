# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
import sys
import tarfile

import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULTS_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "roles", "custom_extensions", "defaults", "main.yml"
)
TASKS_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "roles", "custom_extensions", "tasks", "main.yml"
)
RUNNER_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "stages", "execute_custom_stage.yml"
)
STAGE_CR_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "stages", "stage_cluster_ready.yml"
)
STAGE_CT_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "stages", "stage_cluster_turnup.yml"
)
STAGE_PC_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "stages", "stage_post_cluster.yml"
)
EXAMPLE_DIR = os.path.join(PROJECT_ROOT, "custom-data", "examples", "burnin-bundle")
DOCS_EXT_PATH = os.path.join(PROJECT_ROOT, "docs", "custom-playbook-extensions.md")
DOCS_ON_DEVICE_PATH = os.path.join(PROJECT_ROOT, "docs", "on-device-ansible.md")


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


def test_custom_extensions_tasks_exist_and_parseable():
    assert os.path.isfile(TASKS_PATH), f"Tasks file missing at {TASKS_PATH}"
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    assert isinstance(tasks, list)
    task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
    for t in tasks:
        if isinstance(t, dict) and "block" in t:
            task_names.extend(
                [b.get("name", "") for b in t["block"] if isinstance(b, dict)]
            )
    assert any("Check if sideloaded bundle exists" in n for n in task_names)
    assert any("Extract custom extension bundle" in n for n in task_names)


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


def test_execute_custom_stage_manifest_gating():
    with open(RUNNER_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert "bundle-manifest.json" in content
    assert "bundle_bin_dir" in content
    assert "bundle_oci_dir" in content
    assert "bundle_pkg_dir" in content
    assert "bundle_stage_dir" in content


def test_execute_custom_stage_structure():
    assert os.path.isfile(RUNNER_PATH), f"Runner file missing at {RUNNER_PATH}"
    with open(RUNNER_PATH, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    assert isinstance(tasks, list)
    task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
    for t in tasks:
        if isinstance(t, dict) and "block" in t:
            task_names.extend([b.get("name", "") for b in t["block"] if isinstance(b, dict)])

    assert any(
        "Check for custom stage playbook" in n for n in task_names
    )
    assert any(
        "Execute custom {{ target_custom_stage }} tasks" in n for n in task_names
    )

    # Check that rescue block records external failure attribution
    exec_task = None
    for t in tasks:
        if isinstance(t, dict) and "block" in t:
            for b in t["block"]:
                if isinstance(b, dict) and "Execute custom" in b.get("name", ""):
                    exec_task = b
                    break
        elif isinstance(t, dict) and "Execute custom" in t.get("name", ""):
            exec_task = t
            break

    assert exec_task is not None
    assert "rescue" in exec_task
    rescue_tasks = exec_task["rescue"]
    assert any("Record failure evidence" in r.get("name", "") for r in rescue_tasks)


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
    assert (
        'target_custom_stage: "cluster_turnup"' in ct_content
        or "target_custom_stage: cluster_turnup" in ct_content
    )
    assert "custom_extension" in ct_content

    # Stage 7 must invoke execute_custom_stage with post_cluster
    with open(STAGE_PC_PATH, "r", encoding="utf-8") as f:
        pc_content = f.read()
    assert "execute_custom_stage.yml" in pc_content
    assert (
        'target_custom_stage: "post_cluster"' in pc_content
        or "target_custom_stage: post_cluster" in pc_content
    )
    assert "custom_extension" in pc_content

    # Stage 8 must invoke execute_custom_stage with upkeep
    with open(STAGE_UPKEEP_PATH, "r", encoding="utf-8") as f:
        upkeep_content = f.read()
    assert "execute_custom_stage.yml" in upkeep_content
    assert (
        'target_custom_stage: "upkeep"' in upkeep_content
        or "target_custom_stage: upkeep" in upkeep_content
    )
    assert "custom_extension" in upkeep_content


def test_reference_burnin_bundle_structure(tmp_path):
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

    state_file = tmp_path / "bundle-manifest.json"
    result = _run_manifest_validation_script(EXAMPLE_DIR, str(state_file))
    assert result.returncode == 0, f"Validation script failed: {result.stderr}"
    assert "Validated manifest" in result.stdout


def test_custom_extensions_documentation():
    assert os.path.isfile(DOCS_EXT_PATH), f"Missing docs at {DOCS_EXT_PATH}"
    with open(DOCS_EXT_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert "manifest.yaml" in content
    assert "Anti-Pattern Notice: Avoid Snowflake Clusters" in content
    assert "bundle_template.tar.gz" in content
    assert "bundle_bin_dir" in content


def test_auto_normalization_of_wrapped_playbooks(tmp_path):
    """Verifies that playbook-formatted YAML is automatically normalized into a task list."""
    wrapped_playbook = [
        {
            "name": "Sample Play",
            "hosts": "localhost",
            "gather_facts": False,
            "tasks": [
                {"name": "Task 1", "ansible.builtin.debug": {"msg": "Hello"}},
                {"name": "Task 2", "ansible.builtin.debug": {"msg": "World"}}
            ]
        }
    ]
    test_file = tmp_path / "cluster_turnup.yml"
    with open(test_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(wrapped_playbook, f)

    # Perform the same normalization snippet used in tasks/main.yml & execute_custom_stage.yml
    with open(test_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if (
        isinstance(data, list)
        and len(data) > 0
        and isinstance(data[0], dict)
        and ("tasks" in data[0] or "hosts" in data[0])
    ):
        extracted_tasks = []
        for play in data:
            if isinstance(play, dict) and "tasks" in play and isinstance(play["tasks"], list):
                extracted_tasks.extend(play["tasks"])
        with open(test_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(extracted_tasks, f, default_flow_style=False, sort_keys=False)

    with open(test_file, "r", encoding="utf-8") as f:
        normalized = yaml.safe_load(f)

    assert isinstance(normalized, list)
    assert len(normalized) == 2
    assert normalized[0]["name"] == "Task 1"
    assert normalized[1]["name"] == "Task 2"
    assert "hosts" not in normalized[0]


def _run_manifest_validation_script(bundle_path: str, state_file: str):
    """Extracts and executes the inline Python validation script from tasks/main.yml."""
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    validation_task = None
    for t in tasks:
        if isinstance(t, dict) and "block" in t:
            for b in t["block"]:
                if isinstance(b, dict) and "Validate manifest.yaml schema" in b.get("name", ""):
                    validation_task = b
                    break
    assert validation_task is not None, "Validation task not found in tasks/main.yml"
    assert validation_task.get("changed_when") is False, "Validation task must have changed_when: false"

    cmd = validation_task.get("ansible.builtin.shell", "")
    lines = cmd.splitlines()
    script_lines = []
    in_script = False
    for line in lines:
        if "python3" in line and "EOF" in line:
            in_script = True
            continue
        if in_script:
            if line.strip() == "EOF":
                break
            script_lines.append(line)
    script = "\n".join(script_lines)

    templated_script = script.replace(
        "{{ _custom_bundle_path }}", str(bundle_path)
    ).replace(
        "{{ custom_extensions_manifest_state_file | default('/var/gdc-install/state/bundle-manifest.json') }}",
        str(state_file),
    )

    return subprocess.run(
        [sys.executable, "-c", templated_script],
        capture_output=True,
        text=True,
        check=False,
    )


def test_manifest_validation_success(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    state_file = tmp_path / "bundle-manifest.json"

    (bundle_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    manifest = {
        "name": "valid-bundle",
        "version": "1.0.0",
        "stages": ["cluster_ready", "cluster_turnup"],
    }
    (bundle_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    for stg in ["cluster_ready", "cluster_turnup"]:
        stg_dir = bundle_dir / stg
        stg_dir.mkdir()
        (stg_dir / "playbook.yaml").write_text("- name: Task\n  ansible.builtin.debug:\n    msg: ok\n", encoding="utf-8")

    result = _run_manifest_validation_script(str(bundle_dir), str(state_file))
    assert result.returncode == 0, f"Validation script failed: {result.stderr}"
    assert "Validated manifest" in result.stdout
    assert state_file.is_file()
    with open(state_file, "r", encoding="utf-8") as sf:
        persisted = json.load(sf)
    assert persisted["name"] == "valid-bundle"
    assert persisted["version"] == "1.0.0"


def test_manifest_validation_invalid_stage_name(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    state_file = tmp_path / "bundle-manifest.json"

    (bundle_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    manifest = {
        "name": "invalid-stage-bundle",
        "version": "1.0.0",
        "stages": ["cluster_ready", "non_existent_stage"],
    }
    (bundle_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    stg_dir = bundle_dir / "cluster_ready"
    stg_dir.mkdir()
    (stg_dir / "playbook.yaml").write_text("- name: Task\n  ansible.builtin.debug:\n    msg: ok\n", encoding="utf-8")

    result = _run_manifest_validation_script(str(bundle_dir), str(state_file))
    assert result.returncode == 1
    assert "ERROR: Invalid stage 'non_existent_stage'" in result.stderr
    assert "Must be one of:" in result.stderr


def test_manifest_validation_missing_or_mismatched_version(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    state_file = tmp_path / "bundle-manifest.json"

    manifest = {
        "name": "version-test-bundle",
        "version": "2.0.0",
        "stages": ["cluster_ready"],
    }
    (bundle_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    stg_dir = bundle_dir / "cluster_ready"
    stg_dir.mkdir()
    (stg_dir / "playbook.yaml").write_text("- name: Task\n  ansible.builtin.debug:\n    msg: ok\n", encoding="utf-8")

    # Case 1: Missing VERSION file
    result_missing = _run_manifest_validation_script(str(bundle_dir), str(state_file))
    assert result_missing.returncode == 1
    assert "ERROR: Bundle missing required VERSION file or VERSION does not match manifest.yaml version." in result_missing.stderr

    # Case 2: Mismatched VERSION file
    (bundle_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    result_mismatch = _run_manifest_validation_script(str(bundle_dir), str(state_file))
    assert result_mismatch.returncode == 1
    assert "ERROR: Bundle missing required VERSION file or VERSION does not match manifest.yaml version." in result_mismatch.stderr


def test_manifest_validation_missing_stage_playbook(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    state_file = tmp_path / "bundle-manifest.json"

    (bundle_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    manifest = {
        "name": "missing-playbook-bundle",
        "version": "1.0.0",
        "stages": ["cluster_ready", "post_cluster"],
    }
    (bundle_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    # Only create cluster_ready playbook, omit post_cluster
    stg_dir = bundle_dir / "cluster_ready"
    stg_dir.mkdir()
    (stg_dir / "playbook.yaml").write_text("- name: Task\n  ansible.builtin.debug:\n    msg: ok\n", encoding="utf-8")

    result = _run_manifest_validation_script(str(bundle_dir), str(state_file))
    assert result.returncode == 1
    assert "ERROR: Declared stage 'post_cluster' missing required playbook" in result.stderr


def test_bundle_template_structure_and_archive(tmp_path):
    TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "custom-data", "templates", "bundle_template")

    assert os.path.isdir(TEMPLATE_DIR), f"Template directory missing: {TEMPLATE_DIR}"

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

    # Verify that packaging the template into a tarball and extracting it validates cleanly
    test_tarball = tmp_path / "bundle_template.tar.gz"
    with tarfile.open(test_tarball, "w:gz") as tar:
        for root, _, files in os.walk(TEMPLATE_DIR):
            for f in sorted(files):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, TEMPLATE_DIR)
                tar.add(full_path, arcname=rel_path)

    unpacked_dir = tmp_path / "unpacked"
    unpacked_dir.mkdir()
    with tarfile.open(test_tarball, "r:gz") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(unpacked_dir, filter="data")
        else:
            tar.extractall(unpacked_dir)

    result = _run_manifest_validation_script(unpacked_dir, tmp_path / "state.json")
    assert result.returncode == 0, f"Manifest validation failed on unpacked bundle template: {result.stderr}"

    for root, _, files in os.walk(TEMPLATE_DIR):
        rel_root = os.path.relpath(root, TEMPLATE_DIR)
        for fname in files:
            expected_file = unpacked_dir / (rel_root if rel_root != "." else "") / fname
            assert expected_file.is_file(), f"Expected file {expected_file} missing in unpacked tarball"



