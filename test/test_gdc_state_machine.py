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

"""Unit tests for GDC state machine and gate resolution engine."""

import json
import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ANSIBLE_LOOKUP_DIR = os.path.join(PROJECT_ROOT, "src", "ansible", "lookup_plugins")
if ANSIBLE_LOOKUP_DIR not in sys.path:
    sys.path.insert(0, ANSIBLE_LOOKUP_DIR)

ANSIBLE_FILTER_DIR = os.path.join(PROJECT_ROOT, "src", "ansible", "filter_plugins")
if ANSIBLE_FILTER_DIR not in sys.path:
    sys.path.insert(0, ANSIBLE_FILTER_DIR)

for venv_dir in (".venv", "venv"):
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    venv_site = os.path.join(PROJECT_ROOT, venv_dir, "lib", py_ver, "site-packages")
    if os.path.isdir(venv_site) and venv_site not in sys.path:
        sys.path.insert(0, venv_site)

if "ansible" not in sys.modules:
    try:
        import ansible.plugins.lookup  # type: ignore # noqa: F401
    except (ImportError, ModuleNotFoundError):
        import types

        ansible_mod = types.ModuleType("ansible")
        plugins_mod = types.ModuleType("ansible.plugins")
        lookup_mod = types.ModuleType("ansible.plugins.lookup")

        class LookupBaseStub:  # pylint: disable=too-few-public-methods
            def __init__(self, **kwargs):
                pass

            def get_basedir(self, variables):  # pylint: disable=unused-argument
                return ""

        lookup_mod.LookupBase = LookupBaseStub  # type: ignore
        plugins_mod.lookup = lookup_mod  # type: ignore
        ansible_mod.plugins = plugins_mod  # type: ignore
        sys.modules["ansible"] = ansible_mod
        sys.modules["ansible.plugins"] = plugins_mod
        sys.modules["ansible.plugins.lookup"] = lookup_mod

from gdc_state_machine import GdcStage, get_current_stage


class TestGdcStateMachine(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()
        os.environ.pop("MACHINE_STATE_STOP_STAGE", None)
        os.environ.pop("STOP_STAGE", None)
        self.test_dir = tempfile.mkdtemp()
        self.state_dir = os.path.join(self.test_dir, "state")
        os.makedirs(self.state_dir, exist_ok=True)
        self.fallback_config = os.path.join(self.test_dir, "fallback-config.json")

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        os.environ.clear()
        os.environ.update(self.orig_env)

    def write_state(self, stage_file, status="completed"):
        path = os.path.join(self.state_dir, stage_file)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"stage": stage_file.split(".")[0], "status": status}, f)

    def test_clean_filesystem_returns_first_boot(self):
        """Clean host filesystem (with fstab present) starts at first-boot."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w", encoding="utf-8") as f:
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
        with open(fstab, "w", encoding="utf-8") as f:
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

    def test_sequential_transitions_alternative_filenames(self):
        """Validates post-cluster.json and upkeep.json aliases satisfy gates."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w", encoding="utf-8") as f:
            f.write("# dummy fstab")

        self.write_state("first-boot.json")
        self.write_state("second-boot.json")
        self.write_state("linux-ready.json")
        self.write_state("cluster-ready.json")
        self.write_state("cluster-turnup.json")

        # Verify post-cluster stage reached
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.POST_CLUSTER)
        # Using post-cluster.json alias instead of post-validation.json
        self.write_state("post-cluster.json")

        # Verify upkeep stage reached
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.UPKEEP)
        # Using upkeep.json alias instead of update-upkeep.json
        self.write_state("upkeep.json")

        # Complete
        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.COMPLETE)

    def test_failed_state_retains_current_stage(self):
        """A stage with status=failed must remain active for retry."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w", encoding="utf-8") as f:
            f.write("# dummy fstab")
        self.write_state("first-boot.json", status="completed")
        self.write_state("second-boot.json", status="failed")

        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.SECOND_BOOT)

    def test_corrupted_json_retains_current_stage(self):
        """Corrupted/truncated state file is treated as incomplete."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w", encoding="utf-8") as f:
            f.write("# dummy fstab")
        self.write_state("first-boot.json", status="completed")
        bad_json = os.path.join(self.state_dir, "second-boot.json")
        with open(bad_json, "w", encoding="utf-8") as f:
            f.write("{invalid json...")

        self.assertEqual(get_current_stage(self.state_dir, fstab_path=fstab), GdcStage.SECOND_BOOT)

    def test_stop_stage_respected(self):
        """If machine_state_stop_stage is reached and completed, return COMPLETE."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w", encoding="utf-8") as f:
            f.write("# dummy fstab")
        self.write_state("first-boot.json", status="completed")
        self.write_state("second-boot.json", status="completed")

        with open(self.fallback_config, "w", encoding="utf-8") as f:
            json.dump({"machine_state_stop_stage": "SECOND_BOOT"}, f)

        stage = get_current_stage(self.state_dir, fallback_config_path=self.fallback_config, fstab_path=fstab)
        self.assertEqual(stage, GdcStage.COMPLETE)

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

    def test_get_stop_stage_from_env_var(self):
        """Verifies stop_stage resolves from environment variable when configs absent."""
        os.environ["MACHINE_STATE_STOP_STAGE"] = "CLUSTER_READY"
        from gdc_state_machine import get_stop_stage
        self.assertEqual(get_stop_stage(), "CLUSTER_READY")

    def test_get_stop_stage_from_manual_fact_file(self):
        """Verifies stop_stage resolves from candidate config file on disk."""
        manual_fact = os.path.join(self.test_dir, "gdc-fact-manual.json")
        with open(manual_fact, "w", encoding="utf-8") as f:
            json.dump({"machine_state_stop_stage": "LINUX_READY"}, f)

        from gdc_state_machine import get_stop_stage
        self.assertEqual(get_stop_stage(candidate_config_paths=[manual_fact]), "LINUX_READY")

    def test_get_stop_stage_normalization(self):
        """Verifies hyphenated or lowercase stop stages are normalized."""
        from gdc_state_machine import get_stop_stage
        self.assertEqual(get_stop_stage(explicit_stop_stage="cluster-ready"), "CLUSTER_READY")
        self.assertEqual(get_stop_stage(explicit_stop_stage="  linux-ready  "), "LINUX_READY")
        self.assertEqual(get_stop_stage(explicit_stop_stage="invalid_stage"), "")

    def test_gdc_stop_stage_lookup_plugin(self):
        """Verifies the gdc_stop_stage LookupModule returns resolved stop stage."""
        from gdc_stop_stage import LookupModule as StopStageLookup
        lookup = StopStageLookup()
        # Case 1: explicit term
        self.assertEqual(lookup.run(["CLUSTER_READY"]), ["CLUSTER_READY"])
        # Case 2: from variables
        self.assertEqual(lookup.run([], variables={"stop_stage": "SECOND_BOOT"}), ["SECOND_BOOT"])
        # Case 3: from machine_config in variables
        self.assertEqual(lookup.run([], variables={"machine_config": {"machine_state_stop_stage": "FIRST_BOOT"}}), ["FIRST_BOOT"])
        # Case 4: default empty
        self.assertEqual(lookup.run([]), [""])

    def test_stop_stage_halts_at_cluster_ready(self):
        """Verifies state machine halts at COMPLETE when cluster-ready completes with CLUSTER_READY stop stage."""
        fstab = os.path.join(self.test_dir, "fstab")
        with open(fstab, "w", encoding="utf-8") as f:
            f.write("# dummy fstab")
        self.write_state("first-boot.json", status="completed")
        self.write_state("second-boot.json", status="completed")
        self.write_state("linux-ready.json", status="completed")

        # Before cluster-ready completes
        stage = get_current_stage(
            self.state_dir,
            fstab_path=fstab,
            stop_stage="CLUSTER_READY",
        )
        self.assertEqual(stage, GdcStage.CLUSTER_READY)

        # After cluster-ready completes
        self.write_state("cluster-ready.json", status="completed")
        stage = get_current_stage(
            self.state_dir,
            fstab_path=fstab,
            stop_stage="CLUSTER_READY",
        )
        self.assertEqual(stage, GdcStage.COMPLETE)

    def test_stage_seeds_manifest_with_stop_stage_cluster_turnup(self):
        """Validates that stage seeds mark POST_CLUSTER and UPKEEP as bypassed when stop_stage is CLUSTER_TURNUP."""
        from gdc_state_machine import get_stage_seed_manifest
        manifest = get_stage_seed_manifest("CLUSTER_TURNUP")
        status_map = {m["stage_name"]: m["default_status"] for m in manifest}

        self.assertEqual(status_map["FIRST_BOOT"], "pending")
        self.assertEqual(status_map["SECOND_BOOT"], "pending")
        self.assertEqual(status_map["LINUX_READY"], "pending")
        self.assertEqual(status_map["CLUSTER_READY"], "pending")
        self.assertEqual(status_map["CLUSTER_TURNUP"], "pending")
        self.assertEqual(status_map["POST_CLUSTER"], "bypassed")
        self.assertEqual(status_map["UPKEEP"], "bypassed")

    def test_stage_seeds_manifest_with_no_stop_stage(self):
        """Validates that all stages are pending when no stop_stage is set."""
        from gdc_state_machine import get_stage_seed_manifest
        manifest = get_stage_seed_manifest(None)
        status_map = {m["stage_name"]: m["default_status"] for m in manifest}

        for stage_name, status in status_map.items():
            self.assertEqual(status, "pending", f"{stage_name} should be pending")

    def test_error_details_truncation_under_100k(self):
        """Validates that local.yml failure sanitization keeps evidence strictly under 100k."""
        import yaml
        from jinja2 import Environment

        local_yml_path = os.path.join(PROJECT_ROOT, "src", "ansible", "local.yml")
        with open(local_yml_path, "r", encoding="utf-8") as f:
            plays = yaml.safe_load(f)
        tasks = plays[0]["tasks"]

        # Extract the ClusterTurnup copy task template
        turnup_block = next(t for t in tasks if t.get("name") == "CLUSTER_TURNUP | GDC-STATE | Run Stage 6")
        rescue_copy = next(t for t in turnup_block["rescue"] if "Record ClusterTurnup Failure state" in t.get("name", ""))
        tmpl_content = rescue_copy["ansible.builtin.copy"]["content"]

        from gdc_log_filters import clean_terminal_output
        env = Environment()
        import datetime
        env.filters["to_json"] = lambda v: json.dumps(v, indent=2)
        env.filters["from_json"] = json.loads
        env.filters["clean_terminal_output"] = clean_terminal_output
        env.globals["now"] = lambda utc=True, fmt=None: datetime.datetime.now(datetime.timezone.utc) if fmt is None else datetime.datetime.now(datetime.timezone.utc).strftime(fmt)
        template = env.from_string(tmpl_content)

        # Generate a massive failure result mimicking bmctl spinner blowup
        huge_stdout = "".join(f"Waiting for preflight check job to finish: 1/4 spinner frame {i}\r" for i in range(3000))
        huge_stdout += "\nFinal error: gdc-admin@192.168.109.13: Permission denied (publickey,password).\n"
        huge_stderr = "Error line in stderr: something broke\n" * 1000

        failed_result = {
            "failed": True,
            "cmd": ["/usr/local/bin/cluster/create_cluster.sh", "--yes"],
            "rc": 1,
            "msg": "non-zero return code",
            "stdout": huge_stdout,
            "stdout_lines": huge_stdout.splitlines(),
            "stderr": huge_stderr,
            "stderr_lines": huge_stderr.splitlines(),
            "invocation": {"module_args": {"foo": "bar" * 500}},
        }

        rendered = template.render(
            ansible_failed_result=failed_result,
            cluster_turnup_evidence={"cluster_turnup_verified": False},
            cluster_turnup_start_time="2026-11-01T18:00:00Z",
            cluster_turnup_start_epoch=1793556000,
            provisioning_start_time="2026-11-01T17:00:00Z",
        )

        state_doc = json.loads(rendered)
        evidence = state_doc["evidence"]
        evidence_bytes = len(json.dumps(evidence).encode("utf-8"))

        # Strict assertion: evidence must be under 100,000 bytes
        self.assertLess(evidence_bytes, 100000, f"Evidence size ({evidence_bytes} bytes) exceeded 100k limit")

        # Verify key error content preserved
        error_details = evidence["error_details"]
        self.assertIsInstance(error_details["stdout"], list, "stdout should be formatted as an array of lines")
        self.assertLessEqual(len(error_details["stdout"]), 50, "stdout should contain at most the last 50 lines")
        combined_stdout = "\n".join(error_details["stdout"])
        self.assertIn("Permission denied", combined_stdout)
        self.assertNotIn("stdout_lines", error_details, "stdout_lines should be omitted to prevent duplication")
        self.assertNotIn("stderr_lines", error_details, "stderr_lines should be omitted to prevent duplication")
        self.assertNotIn("invocation", error_details, "invocation should be omitted to prevent duplication")

        # Verify terminal control characters are thoroughly cleaned
        self.assertNotIn("\b", combined_stdout, "Backspaces (\\b) must be stripped")
        self.assertNotIn("\r", combined_stdout, "Carriage returns (\\r) must be normalized")
        self.assertNotIn("\x1b", combined_stdout, "ANSI escape codes must be stripped")


if __name__ == "__main__":
    unittest.main()
