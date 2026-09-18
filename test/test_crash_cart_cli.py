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

"""Unit tests for bin/local/gdc-crash-cart.sh CLI utility."""

import os
import subprocess
import unittest

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../bin/local/gdc-crash-cart.sh"
)

class TestCrashCartCLI(unittest.TestCase):
    def test_script_exists_and_executable(self):
        self.assertTrue(os.path.exists(SCRIPT_PATH), f"Script not found at {SCRIPT_PATH}")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), "Script is not executable")

    def test_main_help_flag(self):
        result = subprocess.run([SCRIPT_PATH, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("snippet", result.stdout)
        self.assertIn("scan-subnet", result.stdout)
        self.assertIn("recover-tpm", result.stdout)

    def test_subcommand_helps(self):
        for subcmd in ["snippet", "recover-tpm"]:
            result = subprocess.run([SCRIPT_PATH, subcmd, "--help"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{subcmd} --help failed")
            self.assertIn("Usage:", result.stdout)

    def test_snippet_command(self):
        result = subprocess.run([SCRIPT_PATH, "snippet", "--password", "custom-secret"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("custom-secret", result.stdout)
        self.assertIn("PermitRootLogin yes", result.stdout)

    def test_scan_subnet_help(self):
        result = subprocess.run([SCRIPT_PATH, "scan-subnet", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--cidr", result.stdout)

    def test_missing_subcommand_fails(self):
        result = subprocess.run([SCRIPT_PATH], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

if __name__ == "__main__":
    unittest.main()
