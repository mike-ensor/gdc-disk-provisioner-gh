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

"""Unit tests verifying manual fact tasks and precedence in Ansible tasks."""

import os
import unittest
import yaml

TASKS_PATH = os.path.join(
    os.path.dirname(__file__),
    "../src/ansible/roles/machine_orchestration/tasks/main.yml"
)

class TestManualFactsAnsible(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(TASKS_PATH))
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            self.tasks = yaml.safe_load(f)

    def test_manual_fact_tasks_present(self):
        task_names = [t.get("name", "") for t in self.tasks if isinstance(t, dict)]
        self.assertTrue(
            any("gdc-fact-manual.json" in name for name in task_names),
            "Expected a task checking for /var/gdc-install/state/gdc-fact-manual.json"
        )

    def test_manual_fact_takes_precedence(self):
        # Find index of manual fact task vs mock vs companion fetch
        manual_idx = None
        mock_idx = None
        companion_idx = None

        for idx, task in enumerate(self.tasks):
            if not isinstance(task, dict):
                continue
            name = task.get("name", "")
            if "gdc-fact-manual.json" in name and manual_idx is None:
                manual_idx = idx
            elif "machine-info-mock.json" in name and "exists" in name:
                mock_idx = idx
            elif "Fetch machine-info configuration from GDC Companion" in name:
                companion_idx = idx

        self.assertIsNotNone(manual_idx, "manual_fact task not found")
        self.assertIsNotNone(mock_idx, "mock task not found")
        self.assertIsNotNone(companion_idx, "companion task not found")
        assert manual_idx is not None and mock_idx is not None and companion_idx is not None
        self.assertLess(manual_idx, mock_idx, "manual_fact must precede legacy mock")
        self.assertLess(mock_idx, companion_idx, "mock must precede companion fetch")

if __name__ == "__main__":
    unittest.main()
