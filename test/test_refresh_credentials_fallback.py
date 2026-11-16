# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
import os
import subprocess
import tempfile
import unittest
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/templates/refresh-gdc-credentials.sh.j2")

class TestRefreshCredentialsFallback(unittest.TestCase):
    def setUp(self):
        with open(TEMPLATE_PATH, "r") as f:
            template_content = f.read()

        import jinja2
        env = jinja2.Environment()
        template = env.from_string(template_content)
        self.script_content = template.render(
            gdc_step_ca_url="https://mock-ca",
            gdc_companion_base_url="https://mock-companion/"
        )

    def run_script(self, mock_env, curl_mock=""):
        temp_dir_obj = tempfile.TemporaryDirectory()
        temp_dir = temp_dir_obj.name
        
        mock_run = os.path.join(temp_dir, "run")
        mock_var = os.path.join(temp_dir, "var")
        mock_etc = os.path.join(temp_dir, "etc")
        os.makedirs(os.path.join(mock_run, "gdc-auth"))
        os.makedirs(os.path.join(mock_var, "gdc-install/keys"))
        os.makedirs(os.path.join(mock_var, "gdc-install/state"))
        os.makedirs(os.path.join(mock_etc, "kubernetes"))

        if mock_env.get("HAS_K8S_CLUSTER"):
            with open(os.path.join(mock_etc, "kubernetes/admin.conf"), "w") as f:
                f.write("mock-kubeconfig")
        
        # Setup files based on env
        if mock_env.get("HAS_MANUAL_FACTS"):
            with open(os.path.join(mock_var, "gdc-install/state/gdc-fact-manual.json"), "w") as f:
                f.write("{}")
        
        access_token_path = os.path.join(mock_run, "gdc-auth/access_token")
        if mock_env.get("HAS_ACCESS_TOKEN"):
            token_content = "" if mock_env.get("TOKEN_IS_EMPTY") else "mock-old-token"
            with open(access_token_path, "w") as f:
                f.write(token_content)
            
            # Manipulate modification time if testing freshness
            if mock_env.get("TOKEN_IS_OLD"):
                # Set mtime to 60 minutes ago
                old_time = time.time() - 3600
                os.utime(access_token_path, (old_time, old_time))
            else:
                # Set mtime to 10 minutes ago
                recent_time = time.time() - 600
                os.utime(access_token_path, (recent_time, recent_time))

        # Modify script to use our mock paths
        test_script = self.script_content.replace("/run/", f"{mock_run}/")
        test_script = test_script.replace("/var/", f"{mock_var}/")
        test_script = test_script.replace("/etc/kubernetes/", f"{mock_etc}/kubernetes/")
        
        # Prepend mock commands
        mock_header = f"""#!/bin/bash
        set -euo pipefail
        
        cat() {{
            if [[ "$*" == *"/sys/class/net/"* ]]; then
                echo "00:11:22:33:44:55"
            else
                command cat "$@"
            fi
        }}
        
        ip() {{
            echo "state UP eeth0"
            echo "eeth0: 00:11:22:33:44:55"
        }}
        
        step() {{
            echo "mock step"
        }}

        kubectl() {{
            if [[ "$*" == *"get nodes"* ]]; then
                return 0
            elif [[ "$*" == *"create token"* ]]; then
                echo "mock-ksa-jwt-token"
            else
                return 0
            fi
        }}
        
        curl() {{
            {curl_mock}
        }}
        
        export -f cat
        export -f ip
        export -f step
        export -f kubectl
        export -f curl
        """
        
        # Remove the original hashbang and set -euo pipefail to insert our mocks
        test_script = mock_header + test_script.split("set -euo pipefail", 1)[1]
        
        script_path = os.path.join(temp_dir, "test.sh")
        with open(script_path, "w") as f:
            f.write(test_script)
        os.chmod(script_path, 0o755)
        
        # Run the script
        result = subprocess.run([script_path], capture_output=True, text=True)
        return result, mock_run, temp_dir_obj

    def test_scenario_a_companion_fails_no_fallback(self):
        # Scenario A: Companion fails, NO fallback conditions -> script exits 1
        curl_mock = 'echo "HTTP 403 Forbidden"'
        mock_env = {}
        result, _, temp_obj = self.run_script(mock_env, curl_mock)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Failed to fetch a valid access token", result.stderr)
        temp_obj.cleanup()

    def test_scenario_b_companion_fails_fresh_token(self):
        # Scenario B: Companion fails, access_token is recent (< 50m) -> script exits 0
        curl_mock = 'echo "HTTP 403 Forbidden"'
        mock_env = {"HAS_ACCESS_TOKEN": True, "TOKEN_IS_OLD": False}
        result, _, temp_obj = self.run_script(mock_env, curl_mock)
        self.assertEqual(result.returncode, 0)
        self.assertIn("WARN: Failed to fetch token from Companion, but local token is < 50 mins old", result.stdout)
        temp_obj.cleanup()

    def test_scenario_c_companion_fails_old_token_no_manual(self):
        # Scenario C: Companion fails, access_token is OLD (> 50m), NO gdc-fact-manual.json -> script exits 1
        curl_mock = 'echo "HTTP 403 Forbidden"'
        mock_env = {"HAS_ACCESS_TOKEN": True, "TOKEN_IS_OLD": True, "HAS_MANUAL_FACTS": False}
        result, _, temp_obj = self.run_script(mock_env, curl_mock)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Failed to fetch a valid access token", result.stderr)
        temp_obj.cleanup()

    def test_scenario_d_companion_fails_old_token_has_manual(self):
        # Scenario D: Companion fails, access_token is OLD (> 50m), HAS gdc-fact-manual.json -> script exits 0
        curl_mock = 'echo "HTTP 403 Forbidden"'
        mock_env = {"HAS_ACCESS_TOKEN": True, "TOKEN_IS_OLD": True, "HAS_MANUAL_FACTS": True}
        result, _, temp_obj = self.run_script(mock_env, curl_mock)
        self.assertEqual(result.returncode, 0)
        self.assertIn("WARN: Companion API unreachable, but operating in manual mode with a sideloaded token", result.stdout)
        temp_obj.cleanup()

    def test_scenario_e_companion_succeeds(self):
        # Scenario E: Companion succeeds -> writes to access_token and adc_token.json, exits 0
        curl_mock = 'echo \'{"access_token":"new-mock-token"}\''
        mock_env = {}
        result, mock_run, temp_obj = self.run_script(mock_env, curl_mock)
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
        self.assertEqual(result.returncode, 0)
        
        # Verify it wrote the token
        with open(os.path.join(mock_run, "gdc-auth/access_token"), "r") as f:
            token = f.read().strip()
        self.assertEqual(token, "new-mock-token")
        
        self.assertTrue(os.path.exists(os.path.join(mock_run, "gdc-auth/adc_token.json")))
        temp_obj.cleanup()

    def test_scenario_f_companion_fails_empty_token_file(self):
        # Scenario F: Companion fails, access_token exists but is 0-bytes -> script exits 1
        curl_mock = 'echo "HTTP 403 Forbidden"'
        mock_env = {"HAS_ACCESS_TOKEN": True, "TOKEN_IS_EMPTY": True, "TOKEN_IS_OLD": False}
        result, _, temp_obj = self.run_script(mock_env, curl_mock)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Failed to fetch a valid access token", result.stderr)
        temp_obj.cleanup()

    def test_scenario_g_k8s_sts_succeeds(self):
        # Scenario G: Cluster is up -> uses K8s Workload Identity STS exchange to write token
        curl_mock = '''
        if [[ "$*" == *"sts.googleapis.com"* ]]; then
            echo '{"access_token":"mock-sts-federated-token","token_type":"Bearer","expires_in":3600}'
        elif [[ "$*" == *"iamcredentials.googleapis.com"* ]]; then
            echo '{"accessToken":"mock-sts-gcp-token","expireTime":"2026-11-16T02:00:00Z"}'
        else
            echo "HTTP 404"
        fi
        '''
        mock_env = {"HAS_K8S_CLUSTER": True}
        result, mock_run, temp_obj = self.run_script(mock_env, curl_mock)
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Kubernetes Workload Identity & STS", result.stdout)
        
        with open(os.path.join(mock_run, "gdc-auth/access_token"), "r") as f:
            token = f.read().strip()
        self.assertEqual(token, "mock-sts-gcp-token")
        temp_obj.cleanup()

    def test_scenario_h_k8s_sts_offline_fallback(self):
        # Scenario H: Cluster is up, but STS endpoint is offline (WAN outage) -> uses fresh local token (< 50m)
        curl_mock = 'echo "curl: (6) Could not resolve host: sts.googleapis.com" >&2; return 1'
        mock_env = {"HAS_K8S_CLUSTER": True, "HAS_ACCESS_TOKEN": True, "TOKEN_IS_OLD": False}
        result, _, temp_obj = self.run_script(mock_env, curl_mock)
        self.assertEqual(result.returncode, 0)
        self.assertIn("WARN: STS token exchange unreachable (WAN offline)", result.stdout)
        temp_obj.cleanup()

if __name__ == '__main__':
    unittest.main()
