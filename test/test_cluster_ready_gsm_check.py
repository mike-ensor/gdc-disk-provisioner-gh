# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Unit tests verifying GSM secret check during the CLUSTER_READY stage."""

import os
import unittest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STAGE_FILE = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_cluster_ready.yml")


class TestClusterReadyGsmCheck(unittest.TestCase):
    """Verifies that stage_cluster_ready.yml enforces GSM secret check for ConfigSync."""

    @classmethod
    def setUpClass(cls):
        with open(STAGE_FILE, "r") as f:
            cls.raw_content = f.read()
            cls.tasks = yaml.safe_load(cls.raw_content)

    def test_file_is_valid_yaml_and_has_tasks(self):
        """Verifies stage_cluster_ready.yml is valid YAML containing a list of tasks."""
        self.assertIsInstance(self.tasks, list)
        self.assertGreater(len(self.tasks), 0)

    def test_lookup_gdc_config_sync_task_present(self):
        """Verifies lookup('gdc_config_sync', ...) is called to resolve repo requirements."""
        self.assertIn("lookup('gdc_config_sync'", self.raw_content)

    def test_check_gsm_secret_block_conditions(self):
        """Verifies the GSM secret check is guarded by config_sync_enabled and requires_secret."""
        gsm_check_task = next(
            (t for t in self.tasks if "Check GSM Secret presence when ConfigSync is enabled" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(gsm_check_task, "GSM check block task not found")
        assert gsm_check_task is not None
        conditions = gsm_check_task.get("when", [])
        cond_str = " ".join(conditions)
        self.assertIn("_cr_config_sync_enabled", cond_str)
        self.assertIn("requires_secret", cond_str)

    def test_gcloud_secret_access_command_and_location_support(self):
        """Verifies gcloud secrets versions access latest includes --location conditionally."""
        gsm_check_task = next(
            (t for t in self.tasks if "Check GSM Secret presence when ConfigSync is enabled" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(gsm_check_task)
        assert gsm_check_task is not None
        block = gsm_check_task.get("block", [])
        access_task = next(
            (t for t in block if "Verify secret accessibility via gcloud" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(access_task)
        assert access_task is not None
        cmd = access_task["ansible.builtin.command"]
        self.assertIn("gcloud secrets versions access latest", cmd)
        self.assertIn("--secret={{ _cr_repo_info.gsm_secret_name }}", cmd)
        self.assertIn("--project={{ _cr_target_project_id }}", cmd)
        self.assertIn("--location={{ _cr_repo_info.gsm_location }}", cmd)

    def test_gsm_secret_assertion_and_remediation_hint(self):
        """Verifies that an assert task fails fast with clear remediation hints."""
        gsm_check_task = next(
            (t for t in self.tasks if "Check GSM Secret presence when ConfigSync is enabled" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(gsm_check_task)
        assert gsm_check_task is not None
        block = gsm_check_task.get("block", [])
        assert_task = next(
            (t for t in block if "Assert GSM secret exists and is accessible" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(assert_task)
        assert assert_task is not None
        that = assert_task["ansible.builtin.assert"]["that"]
        self.assertIn("_cr_gsm_check.rc == 0", " ".join(that))

        fail_msg = assert_task["ansible.builtin.assert"]["fail_msg"]
        self.assertIn("Remediation:", fail_msg)
        self.assertIn("gcloud secrets create", fail_msg)
        self.assertIn("gcloud secrets versions add", fail_msg)
        self.assertIn("roles/secretmanager.secretAccessor", fail_msg)

    def test_evidence_includes_config_sync_secret(self):
        """Verifies cluster_ready_evidence incorporates config_sync_secret telemetry."""
        self.assertIn("'config_sync_secret': (_cr_secret_evidence | default({}))", self.raw_content)

    def test_skipped_evidence_task_present(self):
        """Verifies skipped secret evidence is recorded when ConfigSync or secret is not required."""
        skipped_task = next(
            (t for t in self.tasks if "Record skipped secret evidence when secret not required" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(skipped_task)
        assert skipped_task is not None
        evidence = skipped_task["ansible.builtin.set_fact"]["_cr_secret_evidence"]
        self.assertEqual(evidence["status"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
