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

"""Unit tests verifying ADC environment profile and file permission requirements."""

import os
import unittest
import yaml

TASKS_PATH = os.path.join(
    os.path.dirname(__file__),
    "../src/ansible/roles/machine_orchestration/tasks/main.yml"
)


class TestAdcEnvironmentProfile(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(TASKS_PATH))
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            self.tasks = yaml.safe_load(f)

    def test_adc_environment_tasks_configured(self):
        """Verifies that GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES

        are set in /etc/environment with mode 0600 (root rw, group/user none).
        """
        env_tasks = [
            t for t in self.tasks
            if isinstance(t, dict) and (
                t.get("ansible.builtin.lineinfile", {}).get("path") == "/etc/environment"
                or t.get("ansible.builtin.lineinfile", {}).get("dest") == "/etc/environment"
                or t.get("lineinfile", {}).get("path") == "/etc/environment"
                or t.get("lineinfile", {}).get("dest") == "/etc/environment"
            )
        ]
        self.assertTrue(len(env_tasks) > 0, "Expected at least one task configuring /etc/environment")
        
        # Verify permissions: root owner, root group, mode 0600
        for task in env_tasks:
            module_args = task.get("ansible.builtin.lineinfile") or task.get("lineinfile") or {}
            self.assertEqual(module_args.get("owner"), "root")
            self.assertEqual(module_args.get("group"), "root")
            self.assertIn(str(module_args.get("mode")), ["0600", "600"])

    def test_adc_profile_and_environment_content(self):
        """Verifies that the task sets the required variable values."""
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('/etc/environment', content)
        self.assertIn('GOOGLE_APPLICATION_CREDENTIALS="/etc/gdc/application_default_credentials.json"', content)
        self.assertIn('GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES="1"', content)


if __name__ == "__main__":
    unittest.main()
