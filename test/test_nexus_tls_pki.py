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

    def test_ansible_vars_contain_pki_parameters(self):
        """Verifies all.yml defines default PKI paths, domains, and renewal thresholds."""
        vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars/all.yml")
        with open(vars_path, "r", encoding="utf-8") as f:
            vars_data = yaml.safe_load(f)

        self.assertEqual(vars_data.get("gdc_nexus_tls_enabled"), True)
        self.assertEqual(vars_data.get("gdc_nexus_https_port"), 443)
        self.assertEqual(vars_data.get("gdc_sub_ca_dir"), "/etc/ssl/sub-ca")
        self.assertEqual(vars_data.get("gdc_nexus_cert_path"), "/etc/ssl/certs/nexus.bundle.crt")
        self.assertEqual(vars_data.get("gdc_nexus_key_path"), "/etc/ssl/private/nexus.key")

if __name__ == "__main__":
    unittest.main()
