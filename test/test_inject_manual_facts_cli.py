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

"""Unit tests for bin/node-ops/inject-manual-facts.sh CLI utility."""

import os
import subprocess
import unittest

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../bin/node-ops/inject-manual-facts.sh"
)

class TestInjectManualFactsCLI(unittest.TestCase):
    def test_script_exists_and_executable(self):
        self.assertTrue(os.path.exists(SCRIPT_PATH), f"Script not found at {SCRIPT_PATH}")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), "Script is not executable")

    def test_help_flag(self):
        result = subprocess.run([SCRIPT_PATH, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--node", result.stdout)
        self.assertIn("--facts", result.stdout)

    def test_missing_arguments_fails(self):
        result = subprocess.run([SCRIPT_PATH], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error", result.stderr + result.stdout)

    def test_invalid_facts_json_fails(self):
        invalid_path = os.path.join(os.path.dirname(__file__), "fixtures/invalid-gdc-fact-manual.json")
        result = subprocess.run(
            [SCRIPT_PATH, "--node", "192.168.4.10", "--facts", invalid_path, "--dry-run"],
            capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema", (result.stderr + result.stdout).lower())

    def test_valid_facts_dry_run_succeeds(self):
        valid_path = os.path.join(os.path.dirname(__file__), "fixtures/valid-gdc-fact-manual.json")
        result = subprocess.run(
            [SCRIPT_PATH, "--node", "192.168.4.10", "--facts", valid_path, "--dry-run", "--no-follow"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("cluster-ready.json", result.stdout)

    def test_custom_schema_flag(self):
        valid_path = os.path.join(os.path.dirname(__file__), "fixtures/valid-gdc-fact-manual.json")
        schema_path = "/d/projects/google/gdc-companion/docs/machine-schema.json"
        result = subprocess.run(
            [SCRIPT_PATH, "--node", "192.168.4.10", "--facts", valid_path, "--schema", schema_path, "--dry-run"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("conforms to machine-schema.json", result.stdout)

if __name__ == "__main__":
    unittest.main()
