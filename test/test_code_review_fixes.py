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

"""Regression tests for code review findings and hardening."""

import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

class TestCodeReviewFixes(unittest.TestCase):
    def test_create_cluster_auto_yes_dry_run(self):
        """create_cluster.sh -y --dry-run should not crash with unbound variable."""
        script_path = os.path.join(PROJECT_ROOT, "bin/cluster/create_cluster.sh")
        result = subprocess.run(
            [script_path, "-y", "--dry-run"],
            capture_output=True, text=True,
            env={
                **os.environ,
                "CLUSTER_NAME": "test-cluster",
                "PROJECT_ID": "anthos-bare-metal-lab-1",
                "MACHINE_IP": "192.168.9.241",
                "CLUSTER_VIP": "192.168.9.143",
                "CLUSTER_INGRESS": "192.168.9.144",
                "PRIMARY_LOAD_BALANCER": "192.168.9.144-192.168.9.150",
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertNotIn("unbound variable", result.stderr)
        self.assertIn("DRY-RUN", result.stdout)

    def test_crash_cart_scanner_point_to_point_cidr(self):
        """crash-cart-scan-subnet.py should not crash on /31 or /32 subnets."""
        script_path = os.path.join(PROJECT_ROOT, "bin/local/crash-cart-scan-subnet.py")
        result = subprocess.run(
            ["python3", script_path, "--cidr", "192.168.9.10/32", "--timeout", "0.1"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Subnet bounds", result.stdout)

    def test_bootimus_empty_env_vars(self):
        """bootimus.py should import safely when port env vars are empty strings."""
        env = os.environ.copy()
        env["BOOTIMUS_API_PORT"] = ""
        env["BOOTIMUS_HTTP_PORT"] = ""
        env["BOOTIMUS_SCAN_RETRIES"] = ""
        env["BOOTIMUS_SCAN_DELAY"] = ""
        cmd = ["python3", "-c", "import sys; sys.path.insert(0, 'src/build'); import bootimus; print('BOOTIMUS_PORT:', bootimus.BOOTIMUS_API_PORT)"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=PROJECT_ROOT)
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("BOOTIMUS_PORT: 26000", result.stdout)

    def test_gcp_auth_token_stdin(self):
        """gcp-authentication.sh --token-stdin --dry-run should read token from stdin."""
        script_path = os.path.join(PROJECT_ROOT, "bin/auth/gcp-authentication.sh")
        result = subprocess.run(
            [script_path, "--token-stdin", "--dry-run"],
            input="ya29.piped-stdin-token\n",
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("standard input", result.stdout)

    def test_scan_ips_exact_match(self):
        """scan_ips.py neighbor check must not false-positive on substring IPs."""
        import sys
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))
        import scan_ips
        from unittest.mock import patch, MagicMock

        with patch("subprocess.run") as mock_run:
            # First call is get_local_ips, then arp-scan, arping, ping, then ip neigh
            def mock_run_side_effect(cmd, *args, **kwargs):
                if cmd[0] == "ip" and cmd[1] == "neigh":
                    return MagicMock(returncode=0, stdout="192.168.1.15 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE\n")
                return MagicMock(returncode=1, stdout="")

            mock_run.side_effect = mock_run_side_effect
            self.assertFalse(scan_ips.is_ip_taken("192.168.1.1", "eth0"))

    def test_configure_netplan_eth0_with_lo(self):
        """configure_netplan.py must recognize eth0 when lo is in sys_class_net."""
        import sys
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))
        import configure_netplan
        from unittest.mock import patch

        with patch("os.listdir", return_value=["eth0", "lo"]):
            with patch("os.path.exists", return_value=False):
                ifaces = configure_netplan.get_physical_interfaces("/mock/sys/class/net")
                self.assertEqual(ifaces, ["eth0"])

if __name__ == "__main__":
    unittest.main()
