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

"""Unit tests for bin/local/gdc-node-ops.sh pull-profile subcommand."""

import http.server
import json
import os
import shutil
import subprocess
import threading
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLI_PATH = os.path.join(REPO_ROOT, "bin/local/gdc-node-ops.sh")


class MockCompanionHandler(http.server.BaseHTTPRequestHandler):
    profiles_data = [
        {
            "name": "barn",
            "network_segment": "192.168.20.0/24",
            "description": "Barn edge lab environment",
            "override_count": 14,
            "updated_at": "2026-10-14T08:22:10Z",
        },
        {
            "name": "honeywell",
            "network_segment": "192.168.9.0/24",
            "description": "Honeywell cluster profile",
            "override_count": 18,
            "updated_at": "2026-10-15T19:40:02Z",
        },
    ]

    def do_GET(self):
        if self.path == "/v1/iso-profiles":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(self.profiles_data).encode("utf-8"))
        elif self.path == "/v1/iso-profiles/honeywell?format=env":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"# ISO Build Profile: honeywell\nBOOTSTRAP_MACHINE_IP_CIDR=192.168.9.11/24\n")
        elif self.path == "/v1/iso-profiles/testexisting?format=env":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"# ISO Build Profile: testexisting\nFOO=BAR\n")
        elif self.path == "/v1/iso-profiles/newlab?format=env":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"# ISO Build Profile: newlab\nBOOTSTRAP_MACHINE_IP_CIDR=10.0.0.10/24\n")
        elif self.path == "/v1/iso-profiles/notfound?format=env":
            self.send_response(404)
            self.end_headers()
        elif self.path == "/v1/iso-profiles/unauth?format=env":
            self.send_response(401)
            self.end_headers()
        elif self.path == "/v1/iso-profiles/servererror?format=env":
            self.send_response(500)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class TestPullProfileCLIHelp(unittest.TestCase):
    def test_main_help_includes_pull_profile(self):
        result = subprocess.run([CLI_PATH, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("pull-profile", result.stdout)
        self.assertIn("Pull or list ISO environment profiles from GDC Companion", result.stdout)

    def test_pull_profile_subcommand_help(self):
        result = subprocess.run([CLI_PATH, "pull-profile", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("--name", result.stdout)
        self.assertIn("--companion-url", result.stdout)
        self.assertIn("--api-key", result.stdout)
        self.assertIn("--list", result.stdout)


class TestPullProfileListing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockCompanionHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_list_profiles_when_name_omitted(self):
        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("AVAILABLE ISO PROFILES", result.stdout)
        self.assertIn("barn", result.stdout)
        self.assertIn("192.168.20.0/24", result.stdout)
        self.assertIn("honeywell", result.stdout)
        self.assertIn("192.168.9.0/24", result.stdout)
        self.assertIn("Total profiles found: 2", result.stdout)

    def test_list_profiles_with_explicit_list_flag(self):
        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--list", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("AVAILABLE ISO PROFILES", result.stdout)

    def test_list_profiles_with_api_key(self):
        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--companion-url", companion_url, "--api-key", "secret-key-123"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("AVAILABLE ISO PROFILES", result.stdout)

    def test_list_profiles_http_error(self):
        companion_url = f"http://127.0.0.1:{self.port}/nonexistent"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to fetch profile listing", result.stderr)


class TestPullProfileDownload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockCompanionHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.build_dir = os.path.join(REPO_ROOT, "src/build")
        self.testexisting_file = os.path.join(self.build_dir, "testexisting.env")
        self.newlab_file = os.path.join(self.build_dir, "newlab.env")
        self.notfound_file = os.path.join(self.build_dir, "notfound.env")
        self.unauth_file = os.path.join(self.build_dir, "unauth.env")
        self.backup_dir = os.path.join(self.build_dir, ".backups")

        # Save original states to prevent data loss
        self.orig_testexisting = None
        if os.path.exists(self.testexisting_file):
            with open(self.testexisting_file, "r") as f:
                self.orig_testexisting = f.read()

        self.orig_newlab = None
        if os.path.exists(self.newlab_file):
            with open(self.newlab_file, "r") as f:
                self.orig_newlab = f.read()

        self.orig_notfound = None
        if os.path.exists(self.notfound_file):
            with open(self.notfound_file, "r") as f:
                self.orig_notfound = f.read()

        self.orig_unauth = None
        if os.path.exists(self.unauth_file):
            with open(self.unauth_file, "r") as f:
                self.orig_unauth = f.read()

        self.backups_dir_existed = os.path.exists(self.backup_dir)
        self.initial_backups = set(os.listdir(self.backup_dir)) if self.backups_dir_existed else set()

    def tearDown(self):
        # Restore testexisting.env
        if self.orig_testexisting is not None:
            with open(self.testexisting_file, "w") as f:
                f.write(self.orig_testexisting)
        elif os.path.exists(self.testexisting_file):
            os.remove(self.testexisting_file)

        # Restore newlab.env
        if self.orig_newlab is not None:
            with open(self.newlab_file, "w") as f:
                f.write(self.orig_newlab)
        elif os.path.exists(self.newlab_file):
            os.remove(self.newlab_file)

        # Restore notfound.env
        if self.orig_notfound is not None:
            with open(self.notfound_file, "w") as f:
                f.write(self.orig_notfound)
        elif os.path.exists(self.notfound_file):
            os.remove(self.notfound_file)

        # Restore unauth.env
        if self.orig_unauth is not None:
            with open(self.unauth_file, "w") as f:
                f.write(self.orig_unauth)
        elif os.path.exists(self.unauth_file):
            os.remove(self.unauth_file)

        # Restore .backups
        if not self.backups_dir_existed and os.path.exists(self.backup_dir):
            shutil.rmtree(self.backup_dir, ignore_errors=True)
        elif os.path.exists(self.backup_dir):
            current_backups = set(os.listdir(self.backup_dir))
            for b in current_backups - self.initial_backups:
                b_path = os.path.join(self.backup_dir, b)
                if os.path.isfile(b_path):
                    os.remove(b_path)

    def test_invalid_profile_name_traversal_rejected(self):
        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "../etc/passwd", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid profile name", result.stderr.lower())

    def test_pull_existing_creates_backup_and_updates(self):
        with open(self.testexisting_file, "w") as f:
            f.write("# INITIAL TEST DUMMY\nFOO=OLD\n")

        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "testexisting", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Backed up to: src/build/.backups/testexisting.env.", result.stdout)
        self.assertIn("Successfully synchronized profile to: src/build/testexisting.env", result.stdout)

        with open(self.testexisting_file, "r") as f:
            content = f.read()
        self.assertIn("FOO=BAR", content)

        # Verify permissions are 0644
        self.assertEqual(oct(os.stat(self.testexisting_file).st_mode & 0o777), "0o644")

        self.assertTrue(os.path.exists(self.backup_dir))
        backups = [b for b in os.listdir(self.backup_dir) if b.startswith("testexisting.env.")]
        self.assertTrue(len(backups) >= 1)
        latest_backup = sorted(backups)[-1]
        with open(os.path.join(self.backup_dir, latest_backup), "r") as f:
            backup_content = f.read()
        self.assertIn("# INITIAL TEST DUMMY", backup_content)

    def test_network_failure_shows_friendly_network_error(self):
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "testexisting", "--companion-url", "http://127.0.0.1:1"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to connect to GDC Companion", result.stderr)
        self.assertNotIn("000000", result.stderr)

    def test_pull_new_profile_creates_file_without_backup(self):
        if os.path.exists(self.newlab_file):
            os.remove(self.newlab_file)

        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "newlab", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Successfully synchronized profile to: src/build/newlab.env", result.stdout)

        with open(self.newlab_file, "r") as f:
            content = f.read()
        self.assertIn("BOOTSTRAP_MACHINE_IP_CIDR=10.0.0.10/24", content)

        if os.path.exists(self.backup_dir):
            backups = [b for b in os.listdir(self.backup_dir) if b.startswith("newlab.env.")]
            self.assertEqual(len(backups), 0)

    def test_upstream_404_aborts_without_modifying_or_creating_files(self):
        if os.path.exists(self.notfound_file):
            os.remove(self.notfound_file)

        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "notfound", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP 404", result.stderr)
        self.assertFalse(os.path.exists(self.notfound_file))

    def test_upstream_401_aborts_without_modifying_files(self):
        if os.path.exists(self.unauth_file):
            os.remove(self.unauth_file)

        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "unauth", "--companion-url", companion_url],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP 401", result.stderr)
        self.assertFalse(os.path.exists(self.unauth_file))

    def test_missing_argument_values_clean_error(self):
        for flag in ["--name", "--companion-url", "--api-key"]:
            result = subprocess.run(
                [CLI_PATH, "pull-profile", flag],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, f"Expected returncode 1 for {flag} without value")
            self.assertNotIn("shift", result.stderr, f"Raw bash shift error detected for {flag}")
            self.assertIn("Error:", result.stderr, f"Clean Error prefix expected for {flag}")


if __name__ == "__main__":
    unittest.main()
