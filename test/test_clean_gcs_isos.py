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

"""Unit tests for GCS ISO retention & archive sweeper (src/build/clean_gcs_isos.py)."""

import os
import subprocess
import sys
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "build"))

import clean_gcs_isos


class TestCleanGcsIsos(unittest.TestCase):
    """Tests the logic, parsing, grouping, and execution handlers of clean_gcs_isos.py."""

    def test_parse_version_key(self):
        """Verifies semantic version strings are converted to numeric tuples."""
        self.assertEqual(clean_gcs_isos.parse_version_key("0.10.9"), (0, 10, 9))
        self.assertEqual(clean_gcs_isos.parse_version_key("0.8.101"), (0, 8, 101))
        self.assertEqual(clean_gcs_isos.parse_version_key("1.2"), (1, 2))
        self.assertEqual(clean_gcs_isos.parse_version_key("invalid"), (0,))

    def test_parse_iso_entry(self):
        """Verifies regex filename parsing into series, semver, and variants."""
        entry1 = clean_gcs_isos.parse_iso_entry(
            "honeywell-24.04-v0.10.9-debug.iso", size_bytes=6000000000, timestamp="2026-10-06T15:09:00Z"
        )
        self.assertEqual(entry1["series"], "honeywell-24.04-debug")
        self.assertEqual(entry1["version_str"], "0.10.9")
        self.assertEqual(entry1["version_tuple"], (0, 10, 9))
        self.assertEqual(entry1["timestamp"], "2026-10-06T15:09:00Z")

        entry2 = clean_gcs_isos.parse_iso_entry("honeywell-24.04-v0.8.34-no-comp-debug.iso")
        self.assertEqual(entry2["series"], "honeywell-24.04-no-comp-debug")
        self.assertEqual(entry2["version_str"], "0.8.34")
        self.assertEqual(entry2["version_tuple"], (0, 8, 34))

        entry3 = clean_gcs_isos.parse_iso_entry("unrecognized-name.iso")
        self.assertEqual(entry3["series"], "other")
        self.assertEqual(entry3["version_tuple"], (0,))

    def test_semver_sorting_over_lexicographical(self):
        """Ensures 0.10.2 sorts higher than 0.9.27 and 0.8.101 sorts higher than 0.8.35."""
        filenames = [
            "gdc-labs-24.04-v0.8.35-debug.iso",
            "gdc-labs-24.04-v0.10.2-debug.iso",
            "gdc-labs-24.04-v0.9.27-debug.iso",
            "gdc-labs-24.04-v0.8.101-debug.iso",
        ]
        entries = [clean_gcs_isos.parse_iso_entry(fn) for fn in filenames]
        res = clean_gcs_isos.evaluate_retention(entries, keep_count=3)

        group = res["gdc-labs-24.04-debug"]
        kept = [item["filename"] for item in group["keep"]]
        candidates = [item["filename"] for item in group["candidates"]]

        # 0.10.2, 0.9.27, 0.8.101 should be kept; 0.8.35 should be archived
        self.assertEqual(
            kept,
            [
                "gdc-labs-24.04-v0.10.2-debug.iso",
                "gdc-labs-24.04-v0.9.27-debug.iso",
                "gdc-labs-24.04-v0.8.101-debug.iso",
            ],
        )
        self.assertEqual(candidates, ["gdc-labs-24.04-v0.8.35-debug.iso"])

    def test_retention_with_version_gaps(self):
        """
        Verifies keeping 3 builds works even when intermediate version numbers are missing
        (e.g., keeping 0.10.9, 0.10.8, 0.10.6 when 0.10.7 was not produced).
        """
        filenames = [
            "honeywell-24.04-v0.10.9-debug.iso",
            "honeywell-24.04-v0.10.8-debug.iso",
            "honeywell-24.04-v0.10.6-debug.iso",
            "honeywell-24.04-v0.10.5-debug.iso",
            "honeywell-24.04-v0.10.4-debug.iso",
        ]
        entries = [clean_gcs_isos.parse_iso_entry(fn) for fn in filenames]
        res = clean_gcs_isos.evaluate_retention(entries, keep_count=3)

        group = res["honeywell-24.04-debug"]
        kept_versions = [item["version_str"] for item in group["keep"]]
        candidate_versions = [item["version_str"] for item in group["candidates"]]

        self.assertEqual(kept_versions, ["0.10.9", "0.10.8", "0.10.6"])
        self.assertEqual(candidate_versions, ["0.10.5", "0.10.4"])

    def test_multi_series_isolation(self):
        """Ensures that distinct prefix flavors maintain independent retention pools."""
        filenames = [
            "honeywell-24.04-v0.10.9-debug.iso",
            "honeywell-24.04-v0.10.8-debug.iso",
            "honeywell-24.04-v0.10.7-debug.iso",
            "honeywell-24.04-v0.10.6-debug.iso",
            "gdc-labs-24.04-v0.10.9-debug.iso",
            "gdc-labs-24.04-v0.10.8-debug.iso",
            "gdc-labs-24.04-v0.10.7-debug.iso",
            "gdc-labs-24.04-v0.10.6-debug.iso",
        ]
        entries = [clean_gcs_isos.parse_iso_entry(fn) for fn in filenames]
        res = clean_gcs_isos.evaluate_retention(entries, keep_count=3)

        self.assertEqual(len(res["honeywell-24.04-debug"]["keep"]), 3)
        self.assertEqual(len(res["honeywell-24.04-debug"]["candidates"]), 1)
        self.assertEqual(len(res["gdc-labs-24.04-debug"]["keep"]), 3)
        self.assertEqual(len(res["gdc-labs-24.04-debug"]["candidates"]), 1)

    def test_series_filter(self):
        """Verifies filtering retention evaluation by series keyword."""
        filenames = [
            "honeywell-24.04-v0.10.9-debug.iso",
            "gdc-labs-24.04-v0.10.9-debug.iso",
        ]
        entries = [clean_gcs_isos.parse_iso_entry(fn) for fn in filenames]
        res = clean_gcs_isos.evaluate_retention(entries, keep_count=3, series_filter="honeywell")

        self.assertIn("honeywell-24.04-debug", res)
        self.assertNotIn("gdc-labs-24.04-debug", res)

    def test_format_gib(self):
        """Verifies byte to GiB string formatting."""
        one_gib = 1024 * 1024 * 1024
        self.assertEqual(clean_gcs_isos.format_gib(one_gib), "1.00 GiB")
        self.assertEqual(clean_gcs_isos.format_gib(int(5.5 * one_gib)), "5.50 GiB")

    @mock.patch("subprocess.run")
    def test_list_gcs_isos_mock(self, mock_run):
        """Tests parsing gcloud storage ls -l output."""
        mock_output = (
            "         0  2026-06-17T23:37:57Z  gs://test-bucket/sync/\n"
            "6445772800  2026-09-22T19:06:46Z  gs://test-bucket/sync/gdc-bootstrap-ubuntu-24.04-v0.8.101-debug.iso\n"
            "6557036544  2026-10-06T15:09:00Z  gs://test-bucket/sync/honeywell-24.04-v0.10.9-debug.iso\n"
        )
        mock_run.return_value = mock.MagicMock(stdout=mock_output, returncode=0)

        entries = clean_gcs_isos.list_gcs_isos("gs://test-bucket", prefix="sync")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["filename"], "gdc-bootstrap-ubuntu-24.04-v0.8.101-debug.iso")
        self.assertEqual(entries[1]["filename"], "honeywell-24.04-v0.10.9-debug.iso")
        self.assertEqual(entries[1]["uri"], "gs://test-bucket/sync/honeywell-24.04-v0.10.9-debug.iso")

    @mock.patch("subprocess.run")
    def test_execute_moves_live(self, mock_run):
        """Verifies execute_moves invokes gcloud storage mv."""
        mock_run.return_value = mock.MagicMock(returncode=0)
        moves = [("gs://b/sync/iso1.iso", "gs://b/archived/iso1.iso")]
        success = clean_gcs_isos.execute_moves(moves, dry_run=False)
        self.assertTrue(success)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["gcloud", "storage", "mv", "gs://b/sync/iso1.iso", "gs://b/archived/iso1.iso"])

    @mock.patch("subprocess.run")
    def test_execute_moves_dry_run(self, mock_run):
        """Verifies execute_moves does not invoke gcloud when dry_run=True."""
        moves = [("gs://b/sync/iso1.iso", "gs://b/archived/iso1.iso")]
        success = clean_gcs_isos.execute_moves(moves, dry_run=True)
        self.assertTrue(success)
        mock_run.assert_not_called()

    @mock.patch("subprocess.run")
    def test_execute_deletions_live(self, mock_run):
        """Verifies execute_deletions invokes gcloud storage rm."""
        mock_run.return_value = mock.MagicMock(returncode=0)
        uris = ["gs://b/archived/iso1.iso", "gs://b/archived/iso2.iso"]
        success = clean_gcs_isos.execute_deletions(uris, dry_run=False)
        self.assertTrue(success)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["gcloud", "storage", "rm", "gs://b/archived/iso1.iso", "gs://b/archived/iso2.iso"])


if __name__ == "__main__":
    unittest.main()
