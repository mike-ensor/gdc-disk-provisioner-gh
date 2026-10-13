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
        """Verifies all.yml and all.yml.j2 define default PKI paths, domains, and renewal thresholds."""
        vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars/all.yml")
        with open(vars_path, "r", encoding="utf-8") as f:
            vars_data = yaml.safe_load(f)

        expected_vars = {
            "gdc_nexus_tls_enabled": True,
            "gdc_nexus_https_port": 443,
            "gdc_sub_ca_dir": "/etc/ssl/sub-ca",
            "gdc_sub_ca_cert_path": "/etc/ssl/sub-ca/sub-ca.crt",
            "gdc_sub_ca_key_path": "/etc/ssl/sub-ca/sub-ca.key",
            "gdc_enterprise_root_cert_path": "/usr/local/share/ca-certificates/gdc-enterprise-root.crt",
            "gdc_nexus_cert_path": "/etc/ssl/certs/nexus.bundle.crt",
            "gdc_nexus_key_path": "/etc/ssl/private/nexus.key",
            "gdc_nexus_tls_renew_threshold_seconds": 2592000,
        }

        for var_name, expected_val in expected_vars.items():
            self.assertEqual(vars_data.get(var_name), expected_val, f"all.yml missing or incorrect {var_name}")

        j2_path = os.path.join(PROJECT_ROOT, "src/ansible/vars/all.yml.j2")
        with open(j2_path, "r", encoding="utf-8") as f:
            j2_content = f.read()

        for var_name in expected_vars:
            self.assertIn(var_name, j2_content, f"all.yml.j2 missing {var_name}")

    def test_pki_ingest_tasks_structure(self):
        """Verifies pki_ingest.yml parses cleanly and includes gcloud location fallback logic."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        self.assertTrue(os.path.exists(pki_task_path), "pki_ingest.yml does not exist")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        task_names = []
        def extract_names(task_list):
            for t in task_list:
                if "name" in t:
                    task_names.append(t["name"])
                if "block" in t:
                    extract_names(t["block"])
        extract_names(tasks)

        self.assertTrue(any("Access Sub-CA Secret payload via gcloud" in name for name in task_names))
        self.assertTrue(any("Fallback: Access Sub-CA Secret payload as global resource" in name for name in task_names))
        self.assertTrue(any("Write Corporate Root CA" in name for name in task_names))

if __name__ == "__main__":
    unittest.main()
