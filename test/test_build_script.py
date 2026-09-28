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

"""Unit tests for the unified build.sh ISO orchestrator."""

import os
import subprocess
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_SH = os.path.join(PROJECT_ROOT, "build.sh")


class TestBuildScript(unittest.TestCase):
    """Verifies build.sh CLI options, matrix parsing, defaults, and help menus."""

    def run_build_sh(self, args):
        """Runs build.sh with the provided arguments and returns CompletedProcess."""
        cmd = [BUILD_SH] + args
        return subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)

    def test_help_output(self):
        """Verifies --help outputs usage, defaults, and derived environment variables."""
        res = self.run_build_sh(["--help"])
        self.assertEqual(res.returncode, 0, f"--help failed: {res.stderr}")
        stdout = res.stdout

        # Verify key flags are documented
        self.assertIn("--cloud", stdout)
        self.assertIn("--local", stdout)
        self.assertIn("--concurrent", stdout)
        self.assertIn("--skip-tests", stdout)
        self.assertIn("--bootimus", stdout)
        self.assertIn("--dry-run", stdout)
        self.assertIn("--help-verbose", stdout)

        # Verify defaults and derived environment variables are documented
        self.assertIn("Derived from $ISO_ENVIRONMENT", stdout)
        self.assertIn("Derived from $ISO_VERSION", stdout)
        self.assertIn("Derived from $ISO_NAME_PREFIX", stdout)
        self.assertIn("Derived from $ISO_OUTPUT_BUCKET", stdout)
        self.assertIn("Derived from $PROJECT_ID", stdout)
        self.assertIn("Derived from $REGION", stdout)
        self.assertIn("Derived from $BUILD_VERSION", stdout)
        self.assertIn("Derived from $GDC_DEBUG_MODE", stdout)
        self.assertIn("Derived from $GDC_COMPANION", stdout)

    def test_help_verbose_output(self):
        """Verifies --help-verbose documents the three primary workflow scenarios."""
        res = self.run_build_sh(["--help-verbose"])
        self.assertEqual(res.returncode, 0, f"--help-verbose failed: {res.stderr}")
        stdout = res.stdout

        self.assertIn("FLAG DERIVATION HIERARCHY", stdout)
        self.assertIn("1. DEFAULT SCENARIO", stdout)
        self.assertIn("2. NORMAL / COMMON SCENARIOS", stdout)
        self.assertIn("3. CONCURRENT / MATRIX SCENARIO", stdout)
        self.assertIn("honeywell:0.9.5;barn:0.9.1;0.8.5", stdout)

    def test_dry_run_single_target(self):
        """Verifies --dry-run prints a single target execution plan and exits 0."""
        res = self.run_build_sh(["--dry-run"])
        self.assertEqual(res.returncode, 0, f"--dry-run failed: {res.stderr}")
        stdout = res.stdout

        self.assertIn("Execution Mode:     CLOUD", stdout)
        self.assertIn("Run Pre-flight:     YES", stdout)
        self.assertIn("Deploy to Bootimus: NO", stdout)
        self.assertIn("Target Count:       1", stdout)
        self.assertIn("DRY-RUN SUCCESS", stdout)

    def test_dry_run_concurrent_matrix(self):
        """Verifies --concurrent parses multi-target matrix with environment prefixes."""
        honeywell_env = os.path.join(PROJECT_ROOT, "src/build/honeywell.env")
        barn_env = os.path.join(PROJECT_ROOT, "src/build/barn.env")
        created = []
        try:
            if not os.path.exists(honeywell_env):
                with open(honeywell_env, "w", encoding="utf-8") as f:
                    f.write('ISO_NAME_PREFIX="honeywell-24.04"\n')
                created.append(honeywell_env)
            if not os.path.exists(barn_env):
                with open(barn_env, "w", encoding="utf-8") as f:
                    f.write('ISO_NAME_PREFIX="gdc-labs-24.04"\n')
                created.append(barn_env)

            matrix = "honeywell:0.9.5;barn:0.9.1;0.8.5"
            res = self.run_build_sh(["--dry-run", "--concurrent", matrix])
            self.assertEqual(res.returncode, 0, f"--dry-run concurrent failed: {res.stderr}")
            stdout = res.stdout

            self.assertIn("Target Count:       3", stdout)
            self.assertIn("Env: honeywell | Ver: 0.9.5", stdout)
            self.assertIn("Output: honeywell-24.04-v0.9.5-debug.iso", stdout)
            self.assertIn("Env: barn | Ver: 0.9.1", stdout)
            self.assertIn("Output: gdc-labs-24.04-v0.9.1-debug.iso", stdout)
            self.assertIn("Env: base | Ver: 0.8.5", stdout)
            self.assertIn("Output: gdc-bootstrap-ubuntu-24.04-v0.8.5-debug.iso", stdout)
        finally:
            for path in created:
                if os.path.exists(path):
                    os.remove(path)

    def test_dry_run_local_mode(self):
        """Verifies --local sets execution mode to LOCAL."""
        res = self.run_build_sh(["--dry-run", "--local"])
        self.assertEqual(res.returncode, 0, f"--dry-run --local failed: {res.stderr}")
        self.assertIn("Execution Mode:     LOCAL", res.stdout)

    def test_dry_run_skip_tests(self):
        """Verifies --skip-tests updates pre-flight status."""
        res = self.run_build_sh(["--dry-run", "--skip-tests"])
        self.assertEqual(res.returncode, 0, f"--dry-run --skip-tests failed: {res.stderr}")
        self.assertIn("Run Pre-flight:     NO", res.stdout)

    def test_dry_run_bootimus(self):
        """Verifies --bootimus updates deployment status."""
        res = self.run_build_sh(["--dry-run", "--bootimus"])
        self.assertEqual(res.returncode, 0, f"--dry-run --bootimus failed: {res.stderr}")
        self.assertIn("Deploy to Bootimus: YES", res.stdout)

    def test_removed_scripts_do_not_exist(self):
        """Verifies that deprecated scripts build-iso.sh, concurrent_build.sh, and buildAll.sh are removed."""
        self.assertFalse(
            os.path.exists(os.path.join(PROJECT_ROOT, "build-iso.sh")),
            "build-iso.sh must be removed",
        )
        self.assertFalse(
            os.path.exists(os.path.join(PROJECT_ROOT, "concurrent_build.sh")),
            "concurrent_build.sh must be removed",
        )
        self.assertFalse(
            os.path.exists(os.path.join(PROJECT_ROOT, "buildAll.sh")),
            "buildAll.sh must be removed",
        )
        self.assertTrue(
            os.path.exists(os.path.join(PROJECT_ROOT, "build-builder.sh")),
            "build-builder.sh must be preserved",
        )


if __name__ == "__main__":
    unittest.main()
