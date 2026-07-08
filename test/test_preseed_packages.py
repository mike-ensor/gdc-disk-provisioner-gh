#!/usr/bin/env python3
# ==============================================================================
# GDC Unit Test Suite - Packages Pre-seeding Logic
# ==============================================================================

import os
import sys
import unittest
import tempfile
import shutil
import yaml

# Set up paths so we can import src/build modules cleanly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))

import preseed_packages

class TestPreseedPackages(unittest.TestCase):

    def setUp(self):
        # Create a clean, isolated temporary workspace
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "packages_config.yaml")
        self.env_path = os.path.join(self.test_dir, "build.env")

    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.test_dir)

    def write_mock_config(self, ubuntu_version="24.04", platform=None, customer=None, excludes=None):
        """Helper to serialize structured test package configurations to YAML."""
        config = {
            "ubuntu_version": ubuntu_version,
            "packages_to_include": {
                "platform_required": platform if platform is not None else ["ansible", "git"],
                "customer_added": customer if customer is not None else []
            },
            "exclude_from_dependency_resolution": excludes if excludes is not None else ["^libc6$", "^libsystemd.*"]
        }
        with open(self.config_path, 'w') as f:
            yaml.safe_dump(config, f)

    # ==========================================================================
    # TEST SUITE 1: Environmental File Parsing
    # ==========================================================================
    def test_parse_env_file_success(self):
        """Verifies parse_env_file correctly parses key=val and exports from files."""
        with open(self.env_path, 'w') as f:
            f.write("# This is a comment\n")
            f.write("GCS_BUCKET=gs://test-bucket\n")
            f.write("export ENABLE_GCS=\"true\"\n")
            f.write("export _UBUNTU_VERSION='22.04'\n")
            
        parsed = preseed_packages.parse_env_file(self.env_path)
        
        self.assertEqual(parsed.get("GCS_BUCKET"), "gs://test-bucket")
        self.assertEqual(parsed.get("ENABLE_GCS"), "true")
        self.assertEqual(parsed.get("_UBUNTU_VERSION"), "22.04")

    # ==========================================================================
    # TEST SUITE 2: Configuration Ingestion
    # ==========================================================================
    def test_load_config_merging(self):
        """Verifies load_config correctly digests YAML configurations and merges targets."""
        self.write_mock_config(
            ubuntu_version="24.04",
            platform=["socat", "chrony"],
            customer=["vim", "socat"], # 'socat' is duplicate to verify deduping
            excludes=["^libc6$", "^libudev.*"]
        )
        
        cfg = preseed_packages.load_config(self.config_path)
        
        self.assertEqual(cfg["ubuntu_version"], "24.04")
        # Assert duplicate was deduped and both sets are merged
        self.assertEqual(cfg["packages"], ["chrony", "socat", "vim"])
        self.assertEqual(cfg["excludes"], ["^libc6$", "^libudev.*"])

    # ==========================================================================
    # TEST SUITE 3: Host-to-Target Compatibility Verification
    # ==========================================================================
    def test_verify_compatibility_valid(self):
        """Asserts verify_compatibility passes on matching target-to-host inputs."""
        # Standard match should not raise ValueError
        try:
            preseed_packages.verify_compatibility("24.04", "24.04.1")
            preseed_packages.verify_compatibility("22.04", "22.04.4 LTS")
            preseed_packages.verify_compatibility("24.04", "Unknown") # Bypass on Unknown (non-linux testing)
        except ValueError as e:
            self.fail(f"Compatibility verification raised ValueError unexpectedly on matching versions: {e}")

    def test_verify_compatibility_mismatch_fails(self):
        """Asserts verify_compatibility throws ValueError on mismatched target-to-host inputs."""
        # Target is 24.04 but running host is 22.04
        with self.assertRaises(ValueError) as ctx:
            preseed_packages.verify_compatibility("24.04", "22.04.3")
        self.assertIn("GDC OS Package Target Mismatch!", str(ctx.exception))
        
        # Target is 22.04 but running host is 24.04
        with self.assertRaises(ValueError) as ctx:
            preseed_packages.verify_compatibility("22.04", "24.04")
        self.assertIn("GDC OS Package Target Mismatch!", str(ctx.exception))

    # ==========================================================================
    # TEST SUITE 4: Regex-based Dependency Exclusion Filtering
    # ==========================================================================
    def test_should_exclude_matching_patterns(self):
        """Asserts should_exclude correctly matches package names against regex patterns."""
        excludes = [
            "^libc6$",
            "^libsystemd.*",
            "^gcc-.*-base$",
            "openssh-.*"
        ]
        
        # Positive Match Cases (Should Exclude)
        self.assertTrue(preseed_packages.should_exclude("libc6", excludes))
        self.assertTrue(preseed_packages.should_exclude("libsystemd0", excludes))
        self.assertTrue(preseed_packages.should_exclude("libsystemd-shared", excludes))
        self.assertTrue(preseed_packages.should_exclude("gcc-14-base", excludes))
        self.assertTrue(preseed_packages.should_exclude("openssh-client", excludes))
        self.assertTrue(preseed_packages.should_exclude("openssh-sftp-server", excludes))
        
        # Negative Match Cases (Should Include)
        self.assertFalse(preseed_packages.should_exclude("python3-yaml", excludes))
        self.assertFalse(preseed_packages.should_exclude("ansible-core", excludes))
        self.assertFalse(preseed_packages.should_exclude("git", excludes))
        self.assertFalse(preseed_packages.should_exclude("libcap2", excludes))

if __name__ == "__main__":
    unittest.main()
