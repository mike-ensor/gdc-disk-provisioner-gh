#!/usr/bin/env python3
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
import install_companion
import bootimus

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
    # TEST SUITE 2: install_companion.py (Webhook Status mapping)
    # ==========================================================================
    def test_companion_webhook_log_receiver(self):
        """Verifies install_companion.py accurately maps status codes, color-prefixes and writes logs."""
        temp_log_file = os.path.join(self.test_dir, "test-companion.log")
        
        # Instantiate a mocked request handler to isolate file-system side effects
        class DummyHandler:
            log_file_path = ""
            
        mock_handler = DummyHandler()
        mock_handler.__class__ = install_companion.SubiquityLogHandler
        mock_handler.log_file_path = temp_log_file
        
        # Test Case A: Success Event
        payload_success = {
            "type": "reporting",
            "level": "info",
            "status": "success",
            "name": "provision_nexus",
            "message": "Nexus is operational and active."
        }
        
        # Capture standard output to verify terminal printing
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            install_companion.SubiquityLogHandler.process_webhook_payload(mock_handler, payload_success)
        finally:
            sys.stdout = sys.__stdout__
            
        terminal_out = captured_stdout.getvalue()
        # Verify that green colors and GDC-INSTALL-SUCCESS indicators are used
        self.assertIn("[GDC-INSTALL-SUCCESS]", terminal_out)
        self.assertIn("Nexus is operational", terminal_out)
        
        # Verify log file outputs
        self.assertTrue(os.path.exists(temp_log_file))
        with open(temp_log_file, "r") as f:
            log_content = f.read()
        self.assertIn("[INFO] [SUCCESS] provision_nexus - Nexus is operational", log_content)

        # Test Case B: Failure Event
        payload_fail = {
            "type": "reporting",
            "level": "error",
            "status": "failed",
            "name": "tpm_sealing",
            "message": "TPM master keyslot registration rejected."
        }
        
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            install_companion.SubiquityLogHandler.process_webhook_payload(mock_handler, payload_fail)
        finally:
            sys.stdout = sys.__stdout__
            
        terminal_out = captured_stdout.getvalue()
        # Verify that error red prefix is utilized
        self.assertIn("[GDC-INSTALL-FAIL]", terminal_out)
        self.assertIn("TPM master keyslot", terminal_out)
        
        with open(temp_log_file, "r") as f:
            log_content = f.read()
        self.assertIn("[ERROR] [FAILED] tpm_sealing - TPM master keyslot", log_content)

    # ==========================================================================
    # TEST SUITE 3: bootimus.py (PXE Tree printing and exclusions)
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
