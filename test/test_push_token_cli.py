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

"""Unit tests for bin/local/gdc-node-ops.sh push-token and bin/auth/gcp-authentication.sh."""

import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NODE_OPS_SCRIPT = os.path.join(PROJECT_ROOT, "bin/local/gdc-node-ops.sh")
GCP_AUTH_SCRIPT = os.path.join(PROJECT_ROOT, "bin/auth/gcp-authentication.sh")

class TestPushTokenCLI(unittest.TestCase):
    def test_scripts_exist_and_executable(self):
        self.assertTrue(os.path.exists(NODE_OPS_SCRIPT), f"Script not found: {NODE_OPS_SCRIPT}")
        self.assertTrue(os.access(NODE_OPS_SCRIPT, os.X_OK), "Script is not executable")
        self.assertTrue(os.path.exists(GCP_AUTH_SCRIPT), f"Script not found: {GCP_AUTH_SCRIPT}")
        self.assertTrue(os.access(GCP_AUTH_SCRIPT, os.X_OK), "Script is not executable")

    def test_gcp_auth_help(self):
        result = subprocess.run([GCP_AUTH_SCRIPT, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--token", result.stdout)
        self.assertIn("--dry-run", result.stdout)

    def test_gcp_auth_dry_run_with_token(self):
        result = subprocess.run(
            [GCP_AUTH_SCRIPT, "--token", "ya29.sample-test-bearer-token", "--dry-run"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("DRY-RUN", result.stdout)
        self.assertIn("/run/gdc-auth", result.stdout)
        self.assertIn("/etc/containerd/certs.d/gcr.io/hosts.toml", result.stdout)

    def test_node_ops_push_token_help(self):
        result = subprocess.run([NODE_OPS_SCRIPT, "push-token", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("push-token", result.stdout)
        self.assertIn("--nodes", result.stdout)
        self.assertIn("--token", result.stdout)
        self.assertIn("--test-rotation", result.stdout)
        self.assertIn("--dry-run", result.stdout)

    def test_node_ops_rotate_token_help(self):
        result = subprocess.run([NODE_OPS_SCRIPT, "rotate-token", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("rotate-token", result.stdout)
        self.assertIn("--nodes", result.stdout)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("--reissue-cert", result.stdout)

    def test_node_ops_rotate_token_dry_run_reissue_cert(self):
        result = subprocess.run(
            [NODE_OPS_SCRIPT, "rotate-token", "--nodes", "192.168.4.10", "--reissue-cert", "--dry-run"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")
        self.assertIn("DRY RUN MODE: rotate-token", result.stdout)
        self.assertIn("192.168.4.10", result.stdout)
        self.assertIn("Re-issue cert: true", result.stdout)
        self.assertIn("step ca certificate", result.stdout)

    def test_node_ops_push_token_missing_nodes(self):
        env = os.environ.copy()
        env.pop("TARGET_TEST_MACHINES", None)
        result = subprocess.run(
            [NODE_OPS_SCRIPT, "push-token"],
            capture_output=True, text=True, env=env
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error", result.stderr + result.stdout)

    def test_node_ops_push_token_dry_run_with_custom_token(self):
        result = subprocess.run(
            [NODE_OPS_SCRIPT, "push-token", "--nodes", "192.168.4.10", "--token", "ya29.custom-token-xyz", "--dry-run"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("192.168.4.10", result.stdout)
        self.assertIn("gcp-authentication.sh", result.stdout)

    def test_node_ops_push_token_dry_run_with_test_rotation(self):
        result = subprocess.run(
            [NODE_OPS_SCRIPT, "push-token", "--nodes", "192.168.4.10", "--token", "ya29.custom-token-xyz", "--test-rotation", "--dry-run"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")
        self.assertIn("refresh-gdc-credentials.sh", result.stdout)

if __name__ == "__main__":
    unittest.main()
