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

"""Unit tests for package seeding helper fields and vulnerability rendering in build reports."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATE_REPORT_PY = os.path.join(PROJECT_ROOT, "test/bin/generate_build_report.py")
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "docs/build-report-schema.json")


class TestBuildReportPackages(unittest.TestCase):
    """Verifies package normalization, vulnerability metadata, and markdown rendering."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(PROJECT_ROOT, ".cache")
        self.packages_dir = os.path.join(self.cache_dir, "packages")
        self.pkg_meta_file = os.path.join(self.cache_dir, "packages_metadata.json")
        self.backup_cache_dir = os.path.join(PROJECT_ROOT, ".cache_test_backup")

        # Isolate existing .cache instantaneously within the same filesystem
        if os.path.exists(self.cache_dir):
            if os.path.exists(self.backup_cache_dir):
                shutil.rmtree(self.backup_cache_dir, ignore_errors=True)
            os.rename(self.cache_dir, self.backup_cache_dir)

        os.makedirs(self.packages_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        # Restore or clean up .cache instantaneously within the same filesystem
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        if os.path.exists(self.backup_cache_dir):
            os.rename(self.backup_cache_dir, self.cache_dir)

    def test_package_fields_and_markdown_rendering(self):
        """Verifies package normalization, helper fields, CVSS assistance, and markdown formatting."""
        # Create mock deb files
        # 1. Scanned with vulnerabilities (epoch notation in filename)
        deb_vuln = "tar_1%3a1.35+dfsg-3build1_amd64.deb"
        with open(os.path.join(self.packages_dir, deb_vuln), "wb") as f:
            f.write(b"mock deb content 1")

        # 2. Scanned and clean
        deb_clean = "curl_8.5.0-2ubuntu10_amd64.deb"
        with open(os.path.join(self.packages_dir, deb_clean), "wb") as f:
            f.write(b"mock deb content 2")

        # 3. Not scanned with uppercase epoch (%3A)
        deb_unscanned = "dpkg_1%3A1.22.6ubuntu6_amd64.deb"
        with open(os.path.join(self.packages_dir, deb_unscanned), "wb") as f:
            f.write(b"mock deb content 3")

        # Create mock packages_metadata.json
        metadata = {
            "cache_last_updated": "2026-11-08T12:00:00Z",
            "total_packages": 3,
            "packages": {
                deb_vuln: {
                    "package_name": "tar",
                    "version": "1:1.35+dfsg-3build1",
                    "release_date": "2026-04-01",
                    "cvss_score": 9.8,
                    "severity": "CRITICAL",
                    "cve_count": 2,
                    "primary_cve": "CVE-2024-1234",
                    "details_url": "https://osv.dev/vulnerability/CVE-2024-1234",
                    "scanned_at": "2026-11-08T12:00:00Z"
                },
                deb_clean: {
                    "package_name": "curl",
                    "version": "8.5.0-2ubuntu10",
                    "release_date": "2026-04-10",
                    "cvss_score": 0.0,
                    "severity": "CLEAN",
                    "cve_count": 0,
                    "primary_cve": "NONE",
                    "details_url": "https://osv.dev/list",
                    "scanned_at": "2026-11-08T12:00:00Z"
                },
                deb_unscanned: {
                    "release_date": "2026-03-20"
                }
            }
        }
        with open(self.pkg_meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        env = dict(os.environ)
        env["GDC_TARGET_ECOSYSTEM"] = "Ubuntu:24.04"

        cmd = [
            sys.executable,
            GENERATE_REPORT_PY,
            "--local",
            "--iso-version", "0.11.2",
            "--iso-profile", "test-profile",
            "--iso-environment", "test-profile",
            "--iso-name", "gdc-test-24.04-v0.11.2.iso",
            "--status", "SUCCESS",
            "--output-dir", self.temp_dir,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, env=env)
        self.assertEqual(res.returncode, 0, f"Generator failed: {res.stderr}\n{res.stdout}")

        report_file = os.path.join(self.temp_dir, "build-report-test-profile-v0.11.2.json")
        self.assertTrue(os.path.exists(report_file))

        with open(report_file, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        packages = report_data.get("packages_seeding", {}).get("packages", [])
        self.assertEqual(len(packages), 3)

        pkg_map = {p["filename"]: p for p in packages}

        # Check deb_vuln: epoch %3a decoded to :, all helper fields present
        p_vuln = pkg_map[deb_vuln]
        self.assertEqual(p_vuln["package_name"], "tar")
        self.assertEqual(p_vuln["version"], "1:1.35+dfsg-3build1")
        self.assertEqual(p_vuln["ecosystem"], "Ubuntu:24.04")
        self.assertEqual(p_vuln["cvss_score"], 9.8)
        self.assertEqual(p_vuln["severity"], "CRITICAL")
        self.assertEqual(p_vuln["cve_count"], 2)
        self.assertEqual(p_vuln["primary_cve"], "CVE-2024-1234")
        self.assertEqual(p_vuln["details_url"], "https://osv.dev/vulnerability/CVE-2024-1234")
        self.assertEqual(p_vuln["scanned_at"], "2026-11-08T12:00:00Z")

        # Check deb_clean: clean scan metadata
        p_clean = pkg_map[deb_clean]
        self.assertEqual(p_clean["package_name"], "curl")
        self.assertEqual(p_clean["version"], "8.5.0-2ubuntu10")
        self.assertEqual(p_clean["ecosystem"], "Ubuntu:24.04")
        self.assertEqual(p_clean["cvss_score"], 0.0)
        self.assertEqual(p_clean["severity"], "CLEAN")
        self.assertEqual(p_clean["cve_count"], 0)
        self.assertEqual(p_clean["scanned_at"], "2026-11-08T12:00:00Z")

        # Check deb_unscanned: uppercase epoch %3A decoded to :, helper fields present, scan fields omitted (not defaulted to 0.0)
        p_unscanned = pkg_map[deb_unscanned]
        self.assertEqual(p_unscanned["package_name"], "dpkg")
        self.assertEqual(p_unscanned["version"], "1:1.22.6ubuntu6")
        self.assertEqual(p_unscanned["ecosystem"], "Ubuntu:24.04")
        self.assertNotIn("cvss_score", p_unscanned)
        self.assertNotIn("severity", p_unscanned)
        self.assertNotIn("cve_count", p_unscanned)
        self.assertNotIn("primary_cve", p_unscanned)
        self.assertNotIn("details_url", p_unscanned)
        self.assertNotIn("scanned_at", p_unscanned)

        # Verify Markdown derived output
        md_file = os.path.join(self.temp_dir, "build-report-test-profile-v0.11.2.md")
        self.assertTrue(os.path.exists(md_file))
        with open(md_file, "r", encoding="utf-8") as mf:
            md_text = mf.read()

        # Check markdown table formatting
        self.assertIn("`9.8 CRITICAL` (2 CVEs)", md_text)
        self.assertIn("`Clean (0 CVEs)`", md_text)
        self.assertIn("`Not Scanned`", md_text)

        # Validate complete generated report against docs/build-report-schema.json
        try:
            import jsonschema
            with open(SCHEMA_PATH, "r", encoding="utf-8") as sf:
                schema_def = json.load(sf)
            jsonschema.validate(instance=report_data, schema=schema_def)
        except ImportError:
            pass

    def test_schema_validates_new_package_fields(self):
        """Verifies docs/build-report-schema.json validates report with new fields."""
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")

        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)

        sample_pkg = {
            "filename": "tar_1:1.35.deb",
            "package_name": "tar",
            "version": "1:1.35",
            "ecosystem": "Ubuntu:24.04",
            "expected_sha": "abc123",
            "actual_sha": "abc123",
            "verified": True,
            "size_kb": 120.5,
            "last_updated": "2026-04-01",
            "cvss_score": 9.8,
            "severity": "CRITICAL",
            "cve_count": 2,
            "primary_cve": "CVE-2024-1234",
            "details_url": "https://osv.dev/vulnerability/CVE-2024-1234",
            "scanned_at": "2026-11-08T12:00:00Z"
        }

        pkg_schema = schema["properties"]["packages_seeding"]["properties"]["packages"]["items"]
        jsonschema.validate(instance=sample_pkg, schema=pkg_schema)


if __name__ == "__main__":
    unittest.main()
