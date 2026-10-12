# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Unit tests for ConfigSync RootSync and RepoSync operational readiness audit."""

import os
import sys
import unittest
from unittest.mock import patch
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AUDIT_SCRIPT_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "roles", "post_cluster", "files", "check_config_sync_operational.py"
)
CONFIG_SYNC_TASKS_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "roles", "post_cluster", "tasks", "config_sync.yml"
)

# Add files dir to sys.path to import check_config_sync_operational directly
FILES_DIR = os.path.dirname(AUDIT_SCRIPT_PATH)
if FILES_DIR not in sys.path:
    sys.path.insert(0, FILES_DIR)

import check_config_sync_operational as auditor  # pylint: disable=wrong-import-position,import-error # type: ignore[import-not-found]


class TestConfigSyncOperationalAudit(unittest.TestCase):
    """Tests for check_config_sync_operational.py logic and status evaluation."""

    def test_extract_sync_info_healthy_rootsync(self):
        item = {
            "metadata": {"name": "root-sync", "namespace": "config-management-system"},
            "status": {
                "conditions": [
                    {"type": "Reconciling", "status": "False"},
                    {"type": "Syncing", "status": "False", "message": "Sync Completed", "reason": "Sync"},
                ],
                "sync": {
                    "commit": "aa59c32f90adf343fc7071de7cbc703816e720b8",
                    "errorSummary": {},
                },
                "source": {
                    "commit": "aa59c32f90adf343fc7071de7cbc703816e720b8",
                    "errorSummary": {},
                },
                "rendering": {
                    "commit": "aa59c32f90adf343fc7071de7cbc703816e720b8",
                    "errorSummary": {},
                },
            },
        }
        res = auditor.extract_sync_info(item, "RootSync")
        self.assertEqual(res["type"], "RootSync")
        self.assertEqual(res["name"], "root-sync")
        self.assertEqual(res["namespace"], "config-management-system")
        self.assertEqual(res["status"], "SYNCED")
        self.assertEqual(res["short_commit"], "aa59c32")
        self.assertEqual(res["error_count"], 0)
        self.assertEqual(res["errors"], [])

    def test_extract_sync_info_stalled_rootsync(self):
        item = {
            "metadata": {"name": "primary-rs-embed", "namespace": "config-management-system"},
            "status": {
                "conditions": [
                    {
                        "type": "Stalled",
                        "status": "True",
                        "message": "KNV1061: Secret git-creds not found: create one to allow client authentication",
                    },
                ],
                "sync": {"errorSummary": {}},
            },
        }
        res = auditor.extract_sync_info(item, "RootSync")
        self.assertEqual(res["name"], "primary-rs-embed")
        self.assertEqual(res["status"], "STALLED")
        self.assertGreater(res["error_count"], 0)
        self.assertTrue(any("KNV1061" in err for err in res["errors"]))

    def test_extract_sync_info_rendering_error(self):
        item = {
            "metadata": {"name": "custom-repo", "namespace": "default"},
            "status": {
                "conditions": [],
                "rendering": {
                    "errorSummary": {"totalCount": 1},
                    "errors": [{"errorMessage": "Kustomization file missing"}],
                },
            },
        }
        res = auditor.extract_sync_info(item, "RepoSync")
        self.assertEqual(res["type"], "RepoSync")
        self.assertEqual(res["status"], "ERROR")
        self.assertGreater(res["error_count"], 0)
        self.assertTrue(any("Kustomization" in err for err in res["errors"]))

    def test_format_audit_table_output(self):
        sync_list = [
            {
                "type": "RootSync",
                "namespace": "config-management-system",
                "name": "root-sync",
                "status": "SYNCED",
                "short_commit": "aa59c32",
                "error_count": 0,
                "errors": [],
            }
        ]
        table = auditor.format_audit_table(sync_list, "2026-10-09T12:00:00Z", 15, 600)
        self.assertIn("CONFIGSYNC OPERATIONAL READINESS & R*SYNC AUDIT", table)
        self.assertIn("root-sync", table)
        self.assertIn("SYNCED", table)
        self.assertIn("aa59c32", table)

    @patch("check_config_sync_operational.run_kubectl_get_json")
    def test_audit_config_sync_success_immediate(self, mock_kubectl):
        mock_kubectl.side_effect = [
            (
                0,
                {
                    "items": [
                        {
                            "metadata": {"name": "root-sync", "namespace": "config-management-system"},
                            "status": {
                                "conditions": [
                                    {"type": "Syncing", "status": "False", "message": "Sync Completed", "reason": "Sync"}
                                ],
                                "sync": {"commit": "aa59c32f90adf343fc7071de7cbc703816e720b8", "errorSummary": {}},
                            },
                        }
                    ]
                },
                "",
            ),
            (0, {"items": []}, ""),
        ]

        success, evidence, formatted_output = auditor.audit_config_sync(
            kubeconfig="/etc/kubernetes/admin.conf", timeout_sec=10, interval_sec=1
        )
        self.assertTrue(success)
        self.assertEqual(evidence["status"], "PASS")
        self.assertFalse(evidence["timing"]["timed_out"])
        self.assertEqual(evidence["summary"]["synced_count"], 1)
        self.assertEqual(evidence["summary"]["stalled_count"], 0)
        self.assertIn("All 1 R*Sync objects successfully reconciled", formatted_output)

    @patch("check_config_sync_operational.run_kubectl_get_json")
    def test_audit_config_sync_timeout_stalled(self, mock_kubectl):
        mock_kubectl.side_effect = lambda kb, kind: (
            0,
            {
                "items": [
                    {
                        "metadata": {"name": "root-sync", "namespace": "config-management-system"},
                        "status": {
                            "conditions": [{"type": "Stalled", "status": "True", "message": "Secret not found"}],
                            "sync": {"errorSummary": {}},
                        },
                    }
                ]
            }
            if kind == "rootsync"
            else {"items": []},
            "",
        )

        success, evidence, formatted_output = auditor.audit_config_sync(
            kubeconfig="/etc/kubernetes/admin.conf", timeout_sec=1, interval_sec=1
        )
        self.assertFalse(success)
        self.assertEqual(evidence["status"], "FAIL")
        self.assertTrue(evidence["timing"]["timed_out"])
        self.assertEqual(evidence["summary"]["stalled_count"], 1)
        self.assertIn("TIMEOUT: ConfigSync operational audit timed out", formatted_output)


class TestConfigSyncAnsibleIntegration(unittest.TestCase):
    """Verifies that config_sync.yml integrates the operational audit task and fails appropriately."""

    def setUp(self):
        with open(CONFIG_SYNC_TASKS_PATH, "r", encoding="utf-8") as f:
            self.raw_content = f.read()
            self.tasks = yaml.safe_load(self.raw_content)

    def test_operational_audit_task_present(self):
        self.assertIn("Execute ConfigSync operational audit across all RootSyncs and RepoSyncs", self.raw_content)
        self.assertIn("check_config_sync_operational.py", self.raw_content)
        self.assertIn("--timeout=600", self.raw_content)
        self.assertIn("/var/gdc-install/state/config-sync-audit.json", self.raw_content)

    def test_audit_evidence_fact_ingested(self):
        self.assertIn('operational_audit: "{{ config_sync_operational_audit', self.raw_content)

    def test_fail_task_when_audit_fails(self):
        self.assertIn("Fail if operational audit failed or timed out", self.raw_content)
        self.assertIn("config_sync_audit_res.rc | default(0) != 0", self.raw_content)


if __name__ == "__main__":
    unittest.main()
