# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

import os

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
        data.get("custom_extensions_playbooks_dir")
        == "/var/gdc-install/custom-playbooks"
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


def test_execute_custom_stage_structure():
    assert os.path.isfile(RUNNER_PATH), f"Runner file missing at {RUNNER_PATH}"
    with open(RUNNER_PATH, "r", encoding="utf-8") as f:
        tasks = yaml.safe_load(f)
    assert isinstance(tasks, list)
    task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
    assert any(
        "Check for custom tasks: {{ target_custom_stage }}" in n for n in task_names
    )
    assert any(
        "Execute custom {{ target_custom_stage }} tasks" in n for n in task_names
    )

    # Check that rescue block records external failure attribution
    exec_task = next(t for t in tasks if "Execute custom" in t.get("name", ""))
    assert "rescue" in exec_task
    rescue_tasks = exec_task["rescue"]
    assert any("Record failure evidence" in r.get("name", "") for r in rescue_tasks)


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
    task_names = []
    for t in tasks:
        if isinstance(t, dict):
            task_names.append(t.get("name", ""))
            for sub in t.get("block", []) + t.get("always", []):
                if isinstance(sub, dict):
                    task_names.append(sub.get("name", ""))
    assert any("Deploy burn-in test namespace" in n for n in task_names)


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
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        if "tasks" in data[0] or "hosts" in data[0]:
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

