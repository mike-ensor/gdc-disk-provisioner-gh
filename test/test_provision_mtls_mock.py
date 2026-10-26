# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_PATH = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/files/provision-mtls-cert.sh")


class TestProvisionMtlsMock(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(SCRIPT_PATH), f"Script not found at {SCRIPT_PATH}")
        with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
            self.raw_script = f.read()

    def _prepare_script(self, temp_dir):
        """Prepares a hermetic version of provision-mtls-cert.sh for unprivileged execution."""
        cert_dir = os.path.join(temp_dir, "var/gdc-install/keys")
        mock_etc = os.path.join(temp_dir, "etc/gdc")
        os.makedirs(cert_dir, exist_ok=True)
        os.makedirs(mock_etc, exist_ok=True)

        patched = self.raw_script
        patched = patched.replace('CERT_DIR="/var/gdc-install/keys"', f'CERT_DIR="{cert_dir}"')
        patched = patched.replace('/etc/gdc/', f'{mock_etc}/')
        patched = patched.replace('chown root:root', '# chown root:root')

        test_script_path = os.path.join(temp_dir, "run_provision.sh")
        with open(test_script_path, "w", encoding="utf-8") as f:
            f.write(patched)
        os.chmod(test_script_path, 0o755)

        return test_script_path, cert_dir, mock_etc

    def test_mock_mtls_on_the_fly_generation(self):
        """Verifies that STEP_MOCK_MTLS=true generates self-signed cert and key without error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script, cert_dir, _ = self._prepare_script(temp_dir)
            env = os.environ.copy()
            env["STEP_MOCK_MTLS"] = "true"
            env["STEP_NODE_MAC"] = "11:22:33:44:55:66"

            res = subprocess.run([script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Script failed with stderr:\n{res.stderr}")
            self.assertIn("Development mode enabled", res.stdout)
            self.assertIn("Mock certificates generated/copied successfully", res.stdout)

            crt_path = os.path.join(cert_dir, "client.crt")
            key_path = os.path.join(cert_dir, "client.key")
            self.assertTrue(os.path.isfile(crt_path))
            self.assertTrue(os.path.isfile(key_path))

            # Inspect certificate SAN
            san_check = subprocess.run(
                ["openssl", "x509", "-in", crt_path, "-noout", "-text"],
                capture_output=True,
                text=True,
            )
            self.assertIn("DNS:11:22:33:44:55:66", san_check.stdout)

    def test_mock_mtls_touch_file_trigger(self):
        """Verifies that /etc/gdc/mock-mtls touch file triggers mock mode even if STEP_MOCK_MTLS is unset."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script, cert_dir, mock_etc = self._prepare_script(temp_dir)
            trigger_file = os.path.join(mock_etc, "mock-mtls")
            with open(trigger_file, "w") as f:
                f.write("")

            env = os.environ.copy()
            env.pop("STEP_MOCK_MTLS", None)
            env["STEP_NODE_MAC"] = "aa:bb:cc:dd:ee:ff"

            res = subprocess.run([script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Script failed with stderr:\n{res.stderr}")
            self.assertIn("Development mode enabled", res.stdout)
            self.assertTrue(os.path.isfile(os.path.join(cert_dir, "client.crt")))

    def test_mock_mtls_pre_injected_certs(self):
        """Verifies that pre-injected certificates in /etc/gdc are copied directly to /var/gdc-install/keys."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script, cert_dir, mock_etc = self._prepare_script(temp_dir)
            pre_crt = os.path.join(mock_etc, "mock-client.crt")
            pre_key = os.path.join(mock_etc, "mock-client.key")
            with open(pre_crt, "w") as f:
                f.write("-----BEGIN CERTIFICATE-----\nPRE_INJECTED_MOCK_CERT\n-----END CERTIFICATE-----\n")
            with open(pre_key, "w") as f:
                f.write("-----BEGIN PRIVATE KEY-----\nPRE_INJECTED_MOCK_KEY\n-----END PRIVATE KEY-----\n")

            env = os.environ.copy()
            env["STEP_MOCK_MTLS"] = "true"

            res = subprocess.run([script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Script failed with stderr:\n{res.stderr}")
            self.assertIn("Found pre-injected mock certificates", res.stdout)

            with open(os.path.join(cert_dir, "client.crt"), "r") as f:
                self.assertIn("PRE_INJECTED_MOCK_CERT", f.read())

    def test_mock_mtls_idempotency(self):
        """Verifies that running the script twice exits early without re-generating when certs exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script, cert_dir, _ = self._prepare_script(temp_dir)
            env = os.environ.copy()
            env["STEP_MOCK_MTLS"] = "true"
            env["STEP_NODE_MAC"] = "11:22:33:44:55:66"

            res1 = subprocess.run([script], env=env, capture_output=True, text=True)
            self.assertEqual(res1.returncode, 0)

            res2 = subprocess.run([script], env=env, capture_output=True, text=True)
            self.assertEqual(res2.returncode, 0)
            self.assertIn("already exist", res2.stdout)


if __name__ == "__main__":
    unittest.main()
