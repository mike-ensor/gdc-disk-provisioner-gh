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

"""Unit tests for GDC Endpoint Connectivity and DNS Preflight Checker."""

import json
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "scripts", "check_endpoints.py")
STAGE_YML_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_preflight_checks.yml")

sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "ansible", "scripts"))
from check_endpoints import parse_endpoint_url, check_target, DEFAULT_DOMAINS


class TestCheckEndpoints(unittest.TestCase):
    def test_parse_endpoint_url(self):
        """Verifies URL parsing for default and custom ports across HTTP/HTTPS."""
        res_ca = parse_endpoint_url("https://step-ca.ensor-labs.com", "Step CA", "endpoint_connect_step_ca")
        self.assertIsNotNone(res_ca)
        self.assertEqual(res_ca["domain"], "step-ca.ensor-labs.com")
        self.assertEqual(res_ca["port"], 443)
        self.assertEqual(res_ca["test_name"], "endpoint_connect_step_ca")
        self.assertEqual(res_ca["service"], "step_ca")

        res_custom_port = parse_endpoint_url("http://192.168.254.12:26000/api", "PXE", "endpoint_connect_pxe")
        self.assertIsNotNone(res_custom_port)
        self.assertEqual(res_custom_port["domain"], "192.168.254.12")
        self.assertEqual(res_custom_port["port"], 26000)

        # Empty and invalid cases
        self.assertIsNone(parse_endpoint_url("", "Empty", "test_empty"))
        self.assertIsNone(parse_endpoint_url("   ", "Empty", "test_empty"))
        self.assertIsNone(parse_endpoint_url("not a url", "Invalid", "test_inv"))

    def test_check_target_dns_failure(self):
        """Verifies that unresolvable hostnames report DNS resolution failure clearly."""
        target = {
            "test_name": "endpoint_connect_step_ca",
            "service_label": "Step CA",
            "domain": "this-hostname-definitely-does-not-exist.invalid",
            "port": 443,
            "url": "https://this-hostname-definitely-does-not-exist.invalid"
        }
        res = check_target(target, timeout=0.5)
        self.assertEqual(res["status"], "WARN")
        self.assertFalse(res["meta"]["dns_resolved"])
        self.assertFalse(res["meta"]["tcp_connected"])
        self.assertIn("DNS resolution failed", res["notes"])
        self.assertIn("could not be resolved", res["notes"])
        self.assertIn("add-hosts", res["remediation_hint"])

    def test_check_target_tcp_unreachable(self):
        """Verifies that resolved host with closed/unreachable port clearly reports TCP failure."""
        target = {
            "test_name": "endpoint_connect_companion",
            "service_label": "GDC Companion",
            "domain": "127.0.0.1",
            "port": 54321,
            "url": "http://127.0.0.1:54321"
        }
        res = check_target(target, timeout=0.5)
        self.assertEqual(res["status"], "WARN")
        self.assertTrue(res["meta"]["dns_resolved"])
        self.assertFalse(res["meta"]["tcp_connected"])
        self.assertIn("DNS resolved to 127.0.0.1", res["notes"])
        self.assertIn("TCP/54321 connection failed", res["notes"])
        self.assertIn("Check network routing", res["remediation_hint"])

    def test_cli_execution_with_companion_and_step_ca(self):
        """Verifies check_endpoints.py CLI correctly includes step-ca and companion tests in output."""
        cmd = [
            sys.executable,
            SCRIPT_PATH,
            "--companion-url", "https://gdc-companion.example.com",
            "--step-ca-url", "https://step-ca.example.com",
            "--timeout", "0.2"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        results = json.loads(proc.stdout)
        
        test_names = {r["test_name"] for r in results}
        self.assertIn("endpoint_connect_companion", test_names)
        self.assertIn("endpoint_connect_step_ca", test_names)
        self.assertIn("endpoint_connect_accounts.google.com", test_names)
        self.assertEqual(len(results), len(DEFAULT_DOMAINS) + 2)

    def test_stage_preflight_checks_passes_both_urls(self):
        """Verifies stage_preflight_checks.yml invokes check_endpoints.py with both companion and step-ca URLs."""
        with open(STAGE_YML_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("--companion-url", content)
        self.assertIn("gdc_companion_reports_url", content)
        self.assertIn("--step-ca-url", content)
        self.assertIn("gdc_step_ca_url", content)


if __name__ == "__main__":
    unittest.main()
