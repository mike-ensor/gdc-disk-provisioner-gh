# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Unit tests verifying read-only GSM secret readability check at the start of the CLUSTER_TURNUP stage."""

import os
import unittest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLUSTER_TURNUP_STAGE_FILE = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_cluster_turnup.yml")
CLUSTER_READY_STAGE_FILE = os.path.join(PROJECT_ROOT, "src", "ansible", "stages", "stage_cluster_ready.yml")


class TestClusterTurnupGsmCheck(unittest.TestCase):
    """Verifies that stage_cluster_turnup.yml enforces read-only GSM secret check for ConfigSync."""

    @classmethod
    def setUpClass(cls):
        with open(CLUSTER_TURNUP_STAGE_FILE, "r") as f:
            cls.turnup_raw = f.read()
            cls.turnup_tasks = yaml.safe_load(cls.turnup_raw)
        with open(CLUSTER_READY_STAGE_FILE, "r") as f:
            cls.ready_raw = f.read()
            cls.ready_tasks = yaml.safe_load(cls.ready_raw)

    def test_cluster_ready_does_not_block_on_gsm_secret(self):
        """Verifies stage_cluster_ready.yml does NOT contain GSM secret validation tasks."""
        self.assertNotIn("GDC-CR-GSM", self.ready_raw)
        self.assertNotIn("gcloud secrets versions access", self.ready_raw)
        self.assertNotIn("config_sync_secret", self.ready_raw)

    def test_turnup_file_is_valid_yaml_and_has_tasks(self):
        """Verifies stage_cluster_turnup.yml is valid YAML containing a list of tasks."""
        self.assertIsInstance(self.turnup_tasks, list)
        self.assertGreater(len(self.turnup_tasks), 0)

    def test_lookup_gdc_config_sync_task_present_in_turnup(self):
        """Verifies lookup('gdc_config_sync', ...) is called in stage_cluster_turnup.yml."""
        self.assertIn("lookup('gdc_config_sync'", self.turnup_raw)

    def test_gsm_check_placed_before_cluster_turnup_role(self):
        """Verifies GSM secret check runs before cluster_turnup role execution."""
        task_names = [t.get("name", "") for t in self.turnup_tasks if isinstance(t, dict)]
        gsm_task_idx = next(
            (i for i, name in enumerate(task_names) if "Verify GSM secret readability" in name),
            -1,
        )
        role_task_idx = next(
            (i for i, name in enumerate(task_names) if "Run cluster_turnup role" in name),
            -1,
        )
        self.assertGreater(gsm_task_idx, -1, "GSM check task not found")
        self.assertGreater(role_task_idx, -1, "cluster_turnup role task not found")
        self.assertLess(gsm_task_idx, role_task_idx, "GSM check must precede cluster_turnup role")

    def test_check_gsm_secret_block_conditions(self):
        """Verifies the GSM secret check is guarded by config_sync_enabled and requires_secret."""
        gsm_check_task = next(
            (t for t in self.turnup_tasks if "Verify GSM secret readability" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(gsm_check_task, "GSM check block task not found")
        assert gsm_check_task is not None
        conditions = gsm_check_task.get("when", [])
        cond_str = " ".join(conditions)
        self.assertIn("_ct_config_sync_enabled", cond_str)
        self.assertIn("requires_secret", cond_str)

    def test_gcloud_secret_access_command_and_location_support(self):
        """Verifies gcloud secrets versions access latest includes --location conditionally."""
        gsm_check_task = next(
            (t for t in self.turnup_tasks if "Verify GSM secret readability" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(gsm_check_task)
        assert gsm_check_task is not None
        block = gsm_check_task.get("block", [])
        access_task = next(
            (t for t in block if "Access GSM secret via gcloud" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(access_task)
        assert access_task is not None
        cmd = access_task["ansible.builtin.command"]
        self.assertIn("gcloud secrets versions access latest", cmd)
        self.assertIn("--secret={{ _ct_repo_info.gsm_secret_name }}", cmd)
        self.assertIn("--project={{ _ct_target_project_id }}", cmd)
        self.assertIn("--location={{ _ct_repo_info.gsm_location }}", cmd)

    def test_gsm_secret_assertion_is_read_only_with_no_create_instructions(self):
        """Verifies assert fails fast if not readable, without prescribing secret creation."""
        gsm_check_task = next(
            (t for t in self.turnup_tasks if "Verify GSM secret readability" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(gsm_check_task)
        assert gsm_check_task is not None
        block = gsm_check_task.get("block", [])
        assert_task = next(
            (t for t in block if "Assert GSM secret exists and is readable" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(assert_task)
        assert assert_task is not None
        that = assert_task["ansible.builtin.assert"]["that"]
        self.assertIn("_ct_gsm_check.rc == 0", " ".join(that))

        fail_msg = assert_task["ansible.builtin.assert"]["fail_msg"]
        self.assertIn("Secret was not found or is not readable", fail_msg)
        # MUST NOT instruct creating secrets
        self.assertNotIn("gcloud secrets create", fail_msg)
        self.assertNotIn("gcloud secrets versions add", fail_msg)

    def test_evidence_includes_config_sync_secret_in_turnup(self):
        """Verifies cluster_turnup_evidence incorporates config_sync_secret telemetry."""
        self.assertIn("'config_sync_secret': (_ct_secret_evidence | default({}))", self.turnup_raw)

    def test_skipped_evidence_task_present(self):
        """Verifies skipped secret evidence is recorded when ConfigSync or secret is not required."""
        skipped_task = next(
            (t for t in self.turnup_tasks if "Record skipped secret evidence when secret not required" in t.get("name", "")),
            None,
        )
        self.assertIsNotNone(skipped_task)
        assert skipped_task is not None
        evidence = skipped_task["ansible.builtin.set_fact"]["_ct_secret_evidence"]
        self.assertEqual(evidence["status"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
