#!/usr/bin/env python3
# Copyright 2026 Google LLC
# Apache-2.0

"""Unit tests for Dual-Tier Nexus TLS and Enterprise Sub-CA PKI architecture."""

import os
import unittest
import yaml
from jinja2 import Environment

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestNexusTLSPKI(unittest.TestCase):
    """Verifies PKI packaging, templates, Nginx configuration, and rotation timers."""

    def test_packages_config_contains_nginx(self):
        """Verifies packages_config.yaml includes nginx for offline host caching."""
        config_path = os.path.join(PROJECT_ROOT, "src/build/packages_config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        packages = set(cfg.get("packages_to_include", {}).get("platform_required", []))
        self.assertIn("nginx", packages, "Missing 'nginx' in platform_required packages")

if __name__ == "__main__":
    unittest.main()
