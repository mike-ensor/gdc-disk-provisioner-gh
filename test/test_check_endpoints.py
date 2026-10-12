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

"""Unit tests for GDC Endpoint Connectivity, YAML Manifest, and DNS Preflight Checker."""

import json
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "scripts", "check_endpoints.py")
STAGE_YML_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_preflight_checks.yml")
MANIFEST_PATH = os.path.join(PROJECT_ROOT, "src", "ansible", "vars", "endpoints.yml")

sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "ansible", "scripts"))
from check_endpoints import (  # noqa: E402
    clean_raw_target_string,
    parse_endpoint_url,
    check_target,
    load_manifest,
    build_targets_from_manifest,
    DEFAULT_DOMAINS,
)


class TestCheckEndpoints(unittest.TestCase):
    def test_clean_raw_target_string(self):
        """Verifies cleaning of raw strings and extraction of Jinja default values."""
        self.assertEqual(clean_raw_target_string("accounts.google.com"), "accounts.google.com")
        self.assertEqual(
            clean_raw_target_string("{{ gdc_step_ca_url | default('https://step-ca.example.com') }}"),
            "https://step-ca.example.com",
        )
        self.assertEqual(
            clean_raw_target_string("{{ ntp_servers | default(['time.google.com']) }}"),
            "time.google.com",
        )

    def test_parse_endpoint_url(self):
        """Verifies URL parsing for default and custom ports across HTTP/HTTPS/NTP."""
        res_ca = parse_endpoint_url("https://step-ca.ensor-labs.com", "Step CA", "endpoint_connect_step_ca")
        self.assertIsNotNone(res_ca)
        self.assertEqual(res_ca["domain"], "step-ca.ensor-labs.com")
        self.assertEqual(res_ca["port"], 443)
        self.assertEqual(res_ca["test_name"], "endpoint_connect_step_ca")
        self.assertEqual(res_ca["service"], "step_ca")
        self.assertFalse(res_ca["is_ntp"])

        res_custom_port = parse_endpoint_url("http://192.168.254.12:26000/api", "PXE", "endpoint_connect_pxe")
        self.assertIsNotNone(res_custom_port)
        self.assertEqual(res_custom_port["domain"], "192.168.254.12")
        self.assertEqual(res_custom_port["port"], 26000)

        res_ntp = parse_endpoint_url("time.google.com", "NTP", "endpoint_connect_time")
        self.assertIsNotNone(res_ntp)
        self.assertEqual(res_ntp["port"], 123)
        self.assertTrue(res_ntp["is_ntp"])

        # Empty and invalid cases
        self.assertIsNone(parse_endpoint_url("", "Empty", "test_empty"))
        self.assertIsNone(parse_endpoint_url("   ", "Empty", "test_empty"))
        self.assertIsNone(parse_endpoint_url("not a url", "Invalid", "test_inv"))

    def test_check_target_dns_failure_with_retries(self):
        """Verifies that unresolvable hostnames report DNS resolution failure with fallback recommendation."""
        target = {
            "test_name": "endpoint_connect_step_ca",
            "service_label": "Step CA",
            "domain": "this-hostname-definitely-does-not-exist.invalid",
            "port": 443,
            "url": "https://this-hostname-definitely-does-not-exist.invalid",
            "scope": "platform",
            "cadence": "once",
            "target_stage": "second-boot",
            "current_stage": "second-boot",
            "skip_execution": False,
        }
        res = check_target(target, timeout=0.1, dns_retries=2, dns_retry_delay=0.05)
        self.assertEqual(res["status"], "WARN")
        self.assertFalse(res["meta"]["dns_resolved"])
        self.assertFalse(res["meta"]["tcp_connected"])
        self.assertTrue(res["meta"]["fallback_recommended"])
        self.assertEqual(res["meta"]["attempts"], 2)
        self.assertIn("DNS resolution failed after 2 attempts", res["notes"])
        self.assertIn("add-hosts", res["remediation_hint"])

    def test_check_target_skipped_for_other_stage(self):
        """Verifies that targets designated for other stages emit SKIPPED with 0 duration."""
        target = {
            "test_name": "endpoint_connect_logging.googleapis.com",
            "service_label": "Google API",
            "domain": "logging.googleapis.com",
            "port": 443,
            "scope": "system",
            "cadence": "once",
            "target_stage": "linux-ready",
            "current_stage": "first-boot",
            "skip_execution": True,
        }
        res = check_target(target)
        self.assertEqual(res["status"], "SKIPPED")
        self.assertEqual(res["severity"], "INFO")
        self.assertEqual(res["duration_ms"], 0)
        self.assertFalse(res["meta"]["executed"])
        self.assertEqual(res["meta"]["target_stage"], "linux-ready")
        self.assertIn("Check deferred: designated for stage 'linux-ready'", res["notes"])

    def test_check_target_tcp_unreachable(self):
        """Verifies that resolved host with closed/unreachable port clearly reports TCP failure."""
        target = {
            "test_name": "endpoint_connect_companion",
            "service_label": "GDC Companion",
            "domain": "127.0.0.1",
            "port": 54321,
            "url": "http://127.0.0.1:54321",
            "scope": "platform",
            "skip_execution": False,
        }
        res = check_target(target, timeout=0.2)
        self.assertEqual(res["status"], "WARN")
        self.assertTrue(res["meta"]["dns_resolved"])
        self.assertFalse(res["meta"]["tcp_connected"])
        self.assertTrue(res["meta"]["fallback_recommended"])
        self.assertIn("DNS resolved to 127.0.0.1", res["notes"])
        self.assertIn("TCP/54321 connection failed", res["notes"])
        self.assertIn("Check network routing", res["remediation_hint"])

    def test_manifest_loading_and_stage_cadence(self):
        """Verifies loading the YAML manifest and routing checks based on stage."""
        manifest = load_manifest(MANIFEST_PATH)
        self.assertIn("system", manifest)
        self.assertIn("platform", manifest)

        # Stage 'first-boot'
        targets_fb = build_targets_from_manifest(manifest, current_stage="first-boot")
        executed_fb = [t for t in targets_fb if not t.get("skip_execution")]
        skipped_fb = [t for t in targets_fb if t.get("skip_execution")]

        executed_domains_fb = {t["domain"] for t in executed_fb}
        # 'always' domains must be executed
        self.assertIn("accounts.google.com", executed_domains_fb)
        self.assertIn("compute.googleapis.com", executed_domains_fb)
        # first-boot 'once' domains must be executed
        self.assertIn("iam.googleapis.com", executed_domains_fb)
        # second-boot 'once' domains must be skipped
        skipped_domains_fb = {t["domain"] for t in skipped_fb}
        self.assertIn("gkeconnect.googleapis.com", skipped_domains_fb)

        # Stage 'all'
        targets_all = build_targets_from_manifest(manifest, current_stage="all")
        self.assertTrue(all(not t.get("skip_execution") for t in targets_all))

        # Stage 'upkeep' should execute all prior stages (e.g. cluster-turnup containerregistry, first-boot iam)
        targets_upkeep = build_targets_from_manifest(manifest, current_stage="upkeep")
        executed_upkeep = [t for t in targets_upkeep if not t.get("skip_execution")]
        executed_domains_upkeep = {t["domain"] for t in executed_upkeep}
        self.assertIn("containerregistry.googleapis.com", executed_domains_upkeep)
        self.assertIn("iam.googleapis.com", executed_domains_upkeep)
        self.assertIn("gkeconnect.googleapis.com", executed_domains_upkeep)
        self.assertIn("logging.googleapis.com", executed_domains_upkeep)

    def test_cli_execution_with_manifest_and_stage(self):
        """Verifies check_endpoints.py CLI runs against manifest and outputs valid JSON with stage tagging."""
        cmd = [
            sys.executable,
            SCRIPT_PATH,
            "--config", MANIFEST_PATH,
            "--stage", "second-boot",
            "--timeout", "0.2",
            "--dns-retries", "1",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        results = json.loads(proc.stdout)

        test_names = {r["test_name"] for r in results}
        self.assertIn("endpoint_connect_accounts.google.com", test_names)
        self.assertIn("endpoint_connect_step_ca", test_names)

        # Confirm some are PASS and some are SKIPPED
        statuses = {r["status"] for r in results}
        self.assertIn("SKIPPED", statuses)

        # Ensure skipped tests have duration_ms == 0
        for r in results:
            if r["status"] == "SKIPPED":
                self.assertEqual(r["duration_ms"], 0)
                self.assertFalse(r["meta"]["executed"])

    def test_stage_preflight_checks_passes_config_and_stage(self):
        """Verifies stage_preflight_checks.yml invokes check_endpoints.py with config and stage."""
        with open(STAGE_YML_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("--config", content)
        self.assertIn("endpoints.yml", content)
        self.assertIn("--stage", content)
        self.assertIn("dns_fallback_active", content)


if __name__ == "__main__":
    unittest.main()
