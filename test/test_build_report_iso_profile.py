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

"""Unit tests for ISO Profile association in build reports and build.sh."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATE_REPORT_PY = os.path.join(PROJECT_ROOT, "test/bin/generate_build_report.py")
BUILD_SH = os.path.join(PROJECT_ROOT, "build.sh")
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "docs/build-report-schema.json")


class TestBuildReportIsoProfile(unittest.TestCase):
    """Verifies iso_profile field behaviors across generator, schema, and build.sh."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_schema_allows_iso_profile_and_deprecated_comment(self):
        """Verifies schema contains iso_profile and deprecated indication for iso_environment."""
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)

        properties = schema.get("properties", {})
        self.assertIn("iso_profile", properties)
        self.assertEqual(properties["iso_profile"]["type"], "string")

        self.assertIn("iso_environment", properties)
        self.assertTrue(
            properties["iso_environment"].get("deprecated") is True
            or "deprecated" in properties["iso_environment"].get("description", "").lower()
        )

    def test_generate_report_with_iso_profile(self):
        """Verifies report generation with explicit --iso-profile."""
        cmd = [
            sys.executable,
            GENERATE_REPORT_PY,
            "--local",
            "--iso-version", "0.11.2",
            "--iso-profile", "barn",
            "--iso-environment", "barn",
            "--iso-name", "gdc-labs-24.04-v0.11.2-debug.iso",
            "--status", "SUCCESS",
            "--output-dir", self.temp_dir,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, f"Generator failed: {res.stderr}\n{res.stdout}")

        report_file = os.path.join(self.temp_dir, "build-report-barn-v0.11.2.json")
        self.assertTrue(os.path.exists(report_file), f"Report not found at {report_file}")

        with open(report_file, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        self.assertIn("iso_profile", report_data)
        self.assertEqual(report_data["iso_profile"], "barn")
        self.assertEqual(report_data["iso_environment"], "barn")

        # Verify Markdown derived output
        md_file = os.path.join(self.temp_dir, "build-report-barn-v0.11.2.md")
        self.assertTrue(os.path.exists(md_file), f"Markdown report not found at {md_file}")
        with open(md_file, "r", encoding="utf-8") as mf:
            md_text = mf.read()
        self.assertIn("* **ISO Profile:** `barn`", md_text)

    def test_generate_report_without_iso_profile_omits_field(self):
        """Verifies report generation without --iso-profile completely omits iso_profile key."""
        env = dict(os.environ)
        env.pop("ISO_PROFILE", None)

        cmd = [
            sys.executable,
            GENERATE_REPORT_PY,
            "--local",
            "--iso-version", "0.11.2",
            "--iso-environment", "local",
            "--iso-name", "gdc-bootstrap-ubuntu-24.04-v0.11.2-debug.iso",
            "--status", "SUCCESS",
            "--output-dir", self.temp_dir,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, env=env)
        self.assertEqual(res.returncode, 0, f"Generator failed: {res.stderr}\n{res.stdout}")

        report_file = os.path.join(self.temp_dir, "build-report-local-v0.11.2.json")
        self.assertTrue(os.path.exists(report_file), f"Report not found at {report_file}")

        with open(report_file, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        self.assertNotIn("iso_profile", report_data)
        self.assertEqual(report_data["iso_environment"], "local")

        # Verify Markdown derived output
        md_file = os.path.join(self.temp_dir, "build-report-local-v0.11.2.md")
        with open(md_file, "r", encoding="utf-8") as mf:
            md_text = mf.read()
        self.assertNotIn("* **ISO Profile:**", md_text)

    def test_build_sh_dry_run_profile_resolution(self):
        """Verifies build.sh banners accurately identify profiles when --env is set or omitted."""
        # Case A: Omitted --env
        res_default = subprocess.run(
            [BUILD_SH, "--dry-run"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        self.assertEqual(res_default.returncode, 0)
        self.assertIn("Profile: none", res_default.stdout)

        # Case B: Explicit --env barn (ensure env file exists for hermetic test environments like CI)
        barn_env = os.path.join(PROJECT_ROOT, "src/build/barn.env")
        created = False
        try:
            if not os.path.exists(barn_env):
                with open(barn_env, "w", encoding="utf-8") as f:
                    f.write('ISO_NAME_PREFIX="gdc-labs-24.04"\n')
                created = True

            res_barn = subprocess.run(
                [BUILD_SH, "--dry-run", "--env", "barn"],
                capture_output=True, text=True, cwd=PROJECT_ROOT
            )
            self.assertEqual(res_barn.returncode, 0, f"build.sh --dry-run --env barn failed: {res_barn.stderr}")
            self.assertIn("Profile: barn", res_barn.stdout)
        finally:
            if created and os.path.exists(barn_env):
                os.remove(barn_env)


if __name__ == "__main__":
    unittest.main()
