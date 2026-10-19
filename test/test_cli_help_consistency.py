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

"""Unit tests asserting --help and -h availability and consistency across all repository CLIs."""

import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

class TestCLIHelpConsistency(unittest.TestCase):
    def assert_help_succeeds(self, cmd_args, expected_strings):
        """Runs a CLI command with help flags and asserts exit code 0 and keyword presence."""
        for help_flag in ["--help", "-h"]:
            args = list(cmd_args) + [help_flag]
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            self.assertEqual(
                result.returncode, 0,
                f"Command '{' '.join(args)}' failed with returncode {result.returncode}. Stderr: {result.stderr}"
            )
            output = result.stdout.lower()
            for expected in expected_strings:
                self.assertIn(
                    expected.lower(), output,
                    f"Expected '{expected}' in output of '{' '.join(args)}'. Got: {result.stdout}"
                )

    # 1. gdc-node-ops.sh
    def test_node_ops_main_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh"],
            ["usage:", "push-facts", "push-playbook", "push-token", "rotate-token", "reset-pxe", "refresh-telemetry", "pull-profile"]
        )

    def test_node_ops_push_facts_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh", "push-facts"],
            ["usage:", "--node", "--facts", "--user", "--key", "--schema", "--dry-run", "--no-follow"]
        )

    def test_node_ops_push_playbook_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh", "push-playbook"],
            ["usage:", "--nodes", "--user", "--key", "--resume-from"]
        )

    def test_node_ops_push_token_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh", "push-token"],
            ["usage:", "--nodes", "--user", "--key", "--token", "--account", "--test-rotation", "--dry-run"]
        )

    def test_node_ops_rotate_token_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh", "rotate-token"],
            ["usage:", "--nodes", "--user", "--key", "--dry-run"]
        )

    def test_node_ops_reset_pxe_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh", "reset-pxe"],
            ["usage:", "--nodes", "--user", "--key", "--yes"]
        )

    def test_node_ops_refresh_telemetry_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh", "refresh-telemetry"],
            ["usage:", "--nodes", "--user", "--password", "--key", "--companion-url"]
        )

    def test_node_ops_pull_profile_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-node-ops.sh", "pull-profile"],
            ["usage:", "--name", "--companion-url", "--api-key", "--list"]
        )

    # 2. gdc-forensics.sh
    def test_forensics_main_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-forensics.sh"],
            ["usage:", "fetch", "collect", "inspect"]
        )

    def test_forensics_fetch_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-forensics.sh", "fetch"],
            ["usage:", "--node", "--user", "--key", "--output-dir", "--inspect"]
        )

    def test_forensics_collect_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-forensics.sh", "collect"],
            ["usage:", "--dest"]
        )

    def test_forensics_inspect_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-forensics.sh", "inspect"],
            ["usage:", "--archive"]
        )

    # 3. gdc-crash-cart.sh
    def test_crash_cart_main_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-crash-cart.sh"],
            ["usage:", "snippet", "scan-subnet", "recover-tpm"]
        )

    def test_crash_cart_snippet_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-crash-cart.sh", "snippet"],
            ["usage:", "--password"]
        )

    def test_crash_cart_scan_subnet_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-crash-cart.sh", "scan-subnet"],
            ["usage:", "--cidr", "--exclude", "--workers", "--timeout", "--ssh-user", "--ssh-pass"]
        )

    def test_crash_cart_recover_tpm_help(self):
        self.assert_help_succeeds(
            ["bin/local/gdc-crash-cart.sh", "recover-tpm"],
            ["usage:", "recover-tpm"]
        )

    # 4. Standalone and cluster tools
    def test_gcp_authentication_help(self):
        self.assert_help_succeeds(
            ["bin/auth/gcp-authentication.sh"],
            ["usage:", "containerd", "--token", "--dry-run"]
        )

    def test_create_cluster_help(self):
        self.assert_help_succeeds(
            ["bin/cluster/create_cluster.sh"],
            ["usage:", "--name", "--ip", "--project", "--vip", "--ingress", "--lb-range"]
        )

    def test_verify_upgrade_readiness_help(self):
        self.assert_help_succeeds(
            ["bin/cluster/verify-upgrade-readiness.sh"],
            ["usage:", "upgrade readiness", "dracut", "grub", "cryptsetup"]
        )

    def test_run_storage_benchmark_help(self):
        self.assert_help_succeeds(
            ["bin/cluster/run-storage-benchmark.py"],
            ["usage:", "--storage-class", "--volume-size", "--dry-run", "--skip-guard", "--state-file"]
        )

    def test_sync_schemas_help(self):
        self.assert_help_succeeds(
            ["test/bin/sync-schemas.sh"],
            ["usage:", "--check", "--companion"]
        )

    def test_update_dependencies_help(self):
        self.assert_help_succeeds(
            ["bin/local/update-dependencies.sh"],
            ["usage:", "check", "update-binaries", "update-packages", "sync-gcs"]
        )

if __name__ == "__main__":
    unittest.main()
