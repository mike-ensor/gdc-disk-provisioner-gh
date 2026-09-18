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

"""Unit tests for bin/local/gdc-forensics.sh CLI utility."""

import glob
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../bin/local/gdc-forensics.sh"
)

class TestForensicsCLI(unittest.TestCase):
    def test_script_exists_and_executable(self):
        self.assertTrue(os.path.exists(SCRIPT_PATH), f"Script not found at {SCRIPT_PATH}")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), "Script is not executable")

    def test_main_help_flag(self):
        result = subprocess.run([SCRIPT_PATH, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("fetch", result.stdout)
        self.assertIn("collect", result.stdout)
        self.assertIn("inspect", result.stdout)

    def test_subcommand_helps(self):
        for subcmd in ["fetch", "collect", "inspect"]:
            result = subprocess.run([SCRIPT_PATH, subcmd, "--help"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{subcmd} --help failed")
            self.assertIn("Usage:", result.stdout)

    def test_missing_subcommand_fails(self):
        result = subprocess.run([SCRIPT_PATH], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_fetch_missing_node_fails(self):
        result = subprocess.run([SCRIPT_PATH, "fetch"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error", result.stderr)

    def test_collect_and_inspect_e2e(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            # 1. Collect
            collect_res = subprocess.run(
                [SCRIPT_PATH, "collect", "--dest", tmp_dir],
                capture_output=True, text=True
            )
            self.assertEqual(collect_res.returncode, 0)
            tarballs = glob.glob(os.path.join(tmp_dir, "gdc-installer-forensics-*.tar.gz"))
            self.assertEqual(len(tarballs), 1)

            # 2. Inspect
            inspect_res = subprocess.run(
                [SCRIPT_PATH, "inspect", "--archive", tarballs[0]],
                capture_output=True, text=True
            )
            self.assertEqual(inspect_res.returncode, 0)
            self.assertIn("Inspection complete", inspect_res.stdout)
        finally:
            shutil.rmtree(tmp_dir)

if __name__ == "__main__":
    unittest.main()
