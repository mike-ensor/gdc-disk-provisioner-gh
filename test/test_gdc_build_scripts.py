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

import os
import sys
import unittest
import tempfile
import shutil
import io
from datetime import datetime

# Set up paths so we can import src/build modules cleanly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))

import generate_banner
import bootimus

# Test file paths are modified; append test/ to sys.path to find the mock companion
sys.path.insert(0, os.path.join(PROJECT_ROOT, "test"))
import install_companion_mock

class TestGgdBuildScripts(unittest.TestCase):

    def setUp(self):
        # Create a clean, isolated temporary workspace
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.test_dir)

    # ==========================================================================
    # TEST SUITE 1: generate_banner.py (ASCII Art & Alignments)
    # ==========================================================================
    def test_boot_banner_generation_alignment(self):
        """Verifies generate_banner.py perfectly generates, aligns and centers build details."""
        mock_version = "v3.14.15-gdc"
        mock_time = datetime(2026, 6, 29, 12, 34, 56)
        
        # Call the core functional logic
        banner = generate_banner.generate_boot_text(mock_version, timestamp=mock_time)
        
        # Verify both dynamic values are embedded in the output
        self.assertIn("v3.14.15-gdc", banner)
        self.assertIn("2026-06-29 12:34", banner)
        
        # Verify frame boundaries are preserved (lines are exactly 76 chars wide)
        lines = banner.splitlines()
        for idx, line in enumerate(lines):
            # Check length of normal frame rows (76 characters)
            self.assertEqual(len(line), 76, f"Line {idx} does not have expected length 76. Content: '{line}'")
            # Verify frame vertical columns are placed symmetrically
            self.assertTrue(line.startswith("  | |") or line.startswith("__") or line.startswith("__|"), 
                            f"Line {idx} frame boundary violation: '{line}'")
            self.assertTrue(line.endswith("| |  ") or line.endswith("__") or line.endswith("| |__"), 
                            f"Line {idx} frame boundary violation: '{line}'")

    # ==========================================================================
    # TEST SUITE 2: install_companion_mock.py (Webhook Status mapping)
    # ==========================================================================
    def test_companion_log_status_colors(self):
        """Verifies install_companion_mock.py accurately maps status codes, color-prefixes and writes logs."""
        payload_success = {
            "name": "subiquity/test-success",
            "description": "Task completed successfully",
            "status": "SUCCESS"
        }
        
        # Override the log file path dynamically for tests
        mock_log = os.path.join(self.test_dir, "gdc-installer-receiver.log")
        
        # Suppress prints and capture standard output
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            # Create a class instance bypassing the constructor to avoid HTTPServer requirements
            mock_handler = install_companion_mock.SubiquityLogHandler.__new__(install_companion_mock.SubiquityLogHandler)
            install_companion_mock.SubiquityLogHandler.log_file_path = mock_log
            mock_handler.process_webhook_payload(payload_success)
        finally:
            sys.stdout = sys.__stdout__
            
        success_out = captured_stdout.getvalue()
        
        # Verify Success string colors and prefixes
        self.assertIn("[GDC-INSTALL-SUCCESS]", success_out)
        self.assertIn("\033[92m", success_out) # OKGREEN color
        self.assertIn("Task completed successfully", success_out)
        
        # Test 2: Verify Log File writes correctly
        self.assertTrue(os.path.exists(mock_log))
        with open(mock_log, "r") as f:
            log_content = f.read()
        self.assertIn("[SUCCESS] subiquity/test-success - Task completed successfully", log_content)

        # Test 3: Failure scenario (Testing Warning vs Error thresholds)
        payload_fail = {
            "name": "subiquity/critical-failure",
            "description": "Network timeout threshold exceeded",
            "status": "FAIL",
            "level": "ERROR"
        }
        
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            mock_handler.process_webhook_payload(payload_fail)
        finally:
            sys.stdout = sys.__stdout__
            
        fail_out = captured_stdout.getvalue()
        self.assertIn("[GDC-INSTALL-FAIL]", fail_out)
        self.assertIn("\033[91m", fail_out) # FAIL color

    # ==========================================================================
    def test_bootimus_pxe_unicode_tree_list(self):
        """Verifies bootimus.py renders, sorts, and filters the image tree cleanly."""
        mock_grouped_images = {
            "GDC-Staging": [
                {"filename": "gdc-v1.0.1.iso", "extracted": True},
                {"filename": "gdc-v1.0.0.iso", "extracted": True}
            ],
            "Retail-Edge": [
                {"filename": "retail-noble.iso", "extracted": False}
            ]
        }
        
        # Capture tree-print standard output
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            bootimus.print_tree(mock_grouped_images)
        finally:
            sys.stdout = sys.__stdout__
            
        tree_out = captured_stdout.getvalue()
        
        # Verify tree groups are listed alphabetically
        lines = [l.strip() for l in tree_out.splitlines() if l.strip()]
        
        self.assertIn("├── GDC-Staging", lines[0], "Groups must be printed sequentially.")
        # Verifies alphabetical sort of files under group (v1.0.0.iso should be before v1.0.1.iso)
        self.assertIn("gdc-v1.0.0.iso", lines[1])
        self.assertIn("gdc-v1.0.1.iso", lines[2])
        self.assertIn("└── Retail-Edge", lines[3])
        # Unextracted indicator (🚧) must be printed for unextracted images
        self.assertIn("retail-noble.iso 🚧", lines[4])

        # Test Filter Option
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            bootimus.print_tree(mock_grouped_images, group_filter="Retail")
        finally:
            sys.stdout = sys.__stdout__
            
        filter_out = captured_stdout.getvalue()
        self.assertNotIn("GDC-Staging", filter_out, "Filtered group must be completely excluded.")
        self.assertIn("Retail-Edge", filter_out, "Matched group must be included.")

if __name__ == "__main__":
    unittest.main()
