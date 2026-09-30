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

for venv_dir in (".venv", "venv"):
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    venv_site = os.path.join(PROJECT_ROOT, venv_dir, "lib", py_ver, "site-packages")
    if os.path.isdir(venv_site) and venv_site not in sys.path:
        sys.path.insert(0, venv_site)

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


if __name__ == "__main__":
    unittest.main()
