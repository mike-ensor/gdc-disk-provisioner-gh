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

"""Unit tests for Bootimus environment precedence, variable aliasing, and defaults."""

import os
import subprocess
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBootimusEnvironment(unittest.TestCase):
    """Verifies Bootimus configuration loading, defaults, and overrides."""

    @classmethod
    def setUpClass(cls):
        """Ensure test fixture environment files exist so tests pass in clean CI checkouts."""
        cls.created_files = []
        fixture_content = (
            '# Test fixture for CI environment\n'
            'PXE_SERVER_HOST="192.168.254.12"\n'
            'PXE_SERVER_PORT="26000"\n'
            'BOOTIMUS_API_HOST="192.168.254.12"\n'
            'BOOTIMUS_API_PORT="26000"\n'
            'BOOTIMUS_HTTP_PORT="16000"\n'
        )
        for env_name in ["local.env", "honeywell.env"]:
            path = os.path.join(PROJECT_ROOT, f"src/build/{env_name}")
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(fixture_content)
                cls.created_files.append(path)

    @classmethod
    def tearDownClass(cls):
        """Clean up only files created by this test class."""
        for path in cls.created_files:
            if os.path.exists(path):
                os.remove(path)

    def test_build_env_defaults(self):
        """Verifies that src/build/build.env contains the expected generic defaults."""
        build_env_path = os.path.join(PROJECT_ROOT, "src/build/build.env")
        with open(build_env_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('PXE_SERVER_HOST="pxe.example-labs.com"', content)
        self.assertIn('PXE_SERVER_PORT="26000"', content)
        self.assertIn('BOOTIMUS_API_HOST="pxe.example-labs.com"', content)

    def test_local_and_honeywell_overrides(self):
        """Verifies local.env and honeywell.env configure the target Bootimus host/port."""
        for env_name in ["local.env", "honeywell.env"]:
            path = os.path.join(PROJECT_ROOT, f"src/build/{env_name}")
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn('PXE_SERVER_HOST="192.168.254.12"', content, f"{env_name} missing PXE_SERVER_HOST")
            self.assertIn('PXE_SERVER_PORT="26000"', content, f"{env_name} missing PXE_SERVER_PORT")
            self.assertIn('BOOTIMUS_API_HOST="192.168.254.12"', content, f"{env_name} missing BOOTIMUS_API_HOST")

    def test_bootimus_sh_local_precedence(self):
        """Verifies bootimus.sh banner and exports use local.env over build.env."""
        cmd = [
            "bash", "-c",
            """
            unset PXE_SERVER_HOST PXE_SERVER_PORT BOOTIMUS_API_HOST BOOTIMUS_API_PORT
            export ISO_ENVIRONMENT=local
            PROJECT_ROOT="."
            BUILD_ENV="./src/build/build.env"
            LOCAL_ENV="./src/build/${ISO_ENVIRONMENT}.env"
            declare -A INITIAL_ENV
            for var in $(compgen -e); do INITIAL_ENV[$var]=1; done
            load_env_file() {
                local env_file="$1"
                if [[ -f "${env_file}" ]]; then
                    while IFS= read -r line || [[ -n "$line" ]]; do
                        [[ "$line" =~ ^[[:space:]]*# ]] && continue
                        [[ -z "$line" ]] && continue
                        line="${line#"export "}"
                        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                            local key="${BASH_REMATCH[1]}"
                            local val="${BASH_REMATCH[2]}"
                            val="${val#\\"}" && val="${val%\\"}"
                            val="${val#\\'}" && val="${val%\\'}"
                            if [[ -z "${INITIAL_ENV[${key}]:-}" ]]; then
                                export "${key}"="${val}"
                            fi
                        fi
                    done < "${env_file}"
                fi
            }
            load_env_file "${BUILD_ENV}"
            load_env_file "${LOCAL_ENV}"
            echo "HOST=${PXE_SERVER_HOST}"
            echo "PORT=${PXE_SERVER_PORT}"
            """
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("HOST=192.168.254.12", res.stdout)
        self.assertIn("PORT=26000", res.stdout)

    def test_bootimus_sh_honeywell_precedence(self):
        """Verifies bootimus.sh respects honeywell.env when ISO_ENVIRONMENT=honeywell."""
        cmd = [
            "bash", "-c",
            """
            unset PXE_SERVER_HOST PXE_SERVER_PORT BOOTIMUS_API_HOST BOOTIMUS_API_PORT
            export ISO_ENVIRONMENT=honeywell
            PROJECT_ROOT="."
            BUILD_ENV="./src/build/build.env"
            LOCAL_ENV="./src/build/${ISO_ENVIRONMENT}.env"
            declare -A INITIAL_ENV
            for var in $(compgen -e); do INITIAL_ENV[$var]=1; done
            load_env_file() {
                local env_file="$1"
                if [[ -f "${env_file}" ]]; then
                    while IFS= read -r line || [[ -n "$line" ]]; do
                        [[ "$line" =~ ^[[:space:]]*# ]] && continue
                        [[ -z "$line" ]] && continue
                        line="${line#"export "}"
                        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                            local key="${BASH_REMATCH[1]}"
                            local val="${BASH_REMATCH[2]}"
                            val="${val#\\"}" && val="${val%\\"}"
                            val="${val#\\'}" && val="${val%\\'}"
                            if [[ -z "${INITIAL_ENV[${key}]:-}" ]]; then
                                export "${key}"="${val}"
                            fi
                        fi
                    done < "${env_file}"
                fi
            }
            load_env_file "${BUILD_ENV}"
            load_env_file "${LOCAL_ENV}"
            echo "HOST=${PXE_SERVER_HOST}"
            echo "PORT=${PXE_SERVER_PORT}"
            """
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("HOST=192.168.254.12", res.stdout)
        self.assertIn("PORT=26000", res.stdout)

    def test_bootimus_py_standalone_resolution(self):
        """Verifies bootimus.py resolves 192.168.254.12 when run directly with no env vars."""
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "ISO_ENVIRONMENT": "local",
        }
        cmd = [
            "python3", "-c",
            "import sys; sys.path.insert(0, 'src/build'); import bootimus; "
            "print('API_HOST:', bootimus.BOOTIMUS_API_HOST); "
            "print('API_PORT:', bootimus.BOOTIMUS_API_PORT); "
            "print('HTTP_PORT:', bootimus.BOOTIMUS_HTTP_PORT)"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, env=clean_env, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("API_HOST: 192.168.254.12", res.stdout)
        self.assertIn("API_PORT: 26000", res.stdout)
        self.assertIn("HTTP_PORT: 16000", res.stdout)

    def test_bootimus_py_fallback_when_no_profile(self):
        """Verifies bootimus.py falls back to build.env defaults when profile does not exist."""
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "ISO_ENVIRONMENT": "nonexistent_profile_xyz",
        }
        cmd = [
            "python3", "-c",
            "import sys; sys.path.insert(0, 'src/build'); import bootimus; "
            "print('API_HOST:', bootimus.BOOTIMUS_API_HOST); "
            "print('API_PORT:', bootimus.BOOTIMUS_API_PORT); "
            "print('HTTP_PORT:', bootimus.BOOTIMUS_HTTP_PORT)"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, env=clean_env, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("API_HOST: pxe.example-labs.com", res.stdout)
        self.assertIn("API_PORT: 26000", res.stdout)
        self.assertIn("HTTP_PORT: 16000", res.stdout)

    def test_bootimus_py_explicit_env_override(self):
        """Verifies active environment variables override profile and default settings."""
        override_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PXE_SERVER_HOST": "custom-pxe.domain.corp",
            "PXE_SERVER_PORT": "29999",
        }
        cmd = [
            "python3", "-c",
            "import sys; sys.path.insert(0, 'src/build'); import bootimus; "
            "print('API_HOST:', bootimus.BOOTIMUS_API_HOST); "
            "print('API_PORT:', bootimus.BOOTIMUS_API_PORT)"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, env=override_env, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("API_HOST: custom-pxe.domain.corp", res.stdout)
        self.assertIn("API_PORT: 29999", res.stdout)

    def test_check_bootimus_settings_target_validation(self):
        """Verifies check-bootimus-settings.py flags missing target images."""
        cmd = [
            "python3", "-c",
            "import sys, os, unittest.mock as mock\n"
            "sys.path.insert(0, 'src/build')\n"
            "sys.path.insert(0, 'test/bin')\n"
            "check_mod = __import__('check-bootimus-settings')\n"
            "with mock.patch.object(check_mod, 'get_bootimus_credentials', return_value=('u', 'p')):\n"
            "    with mock.patch.object(check_mod, 'api_request') as mock_req:\n"
            "        mock_req.side_effect = [\n"
            "            {'data': {'token': 'dummy'}},\n"
            "            {'data': [{'filename': 'sync/gdc-labs-24.04-v0.9.26-debug.iso', 'distro': 'ubuntu', 'boot_method': 'kernel', 'enabled': True, 'extracted': True, 'boot_params': 'autoinstall ds=nocloud-net'}]}\n"
            "        ]\n"
            "        with mock.patch.object(check_mod, 'auto_heal_boot_params'):\n"
            "            sys.argv = ['check-bootimus-settings.py', 'missing-v1.0.0.iso']\n"
            "            try:\n"
            "                check_mod.main()\n"
            "                print('UNEXPECTED_PASS')\n"
            "            except SystemExit as e:\n"
            "                print(f'EXIT_CODE_{e.code}')\n"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("EXIT_CODE_1", res.stdout)

    def test_check_bootimus_settings_target_success(self):
        """Verifies check-bootimus-settings.py succeeds when specified target image is verified."""
        cmd = [
            "python3", "-c",
            "import sys, os, unittest.mock as mock\n"
            "sys.path.insert(0, 'src/build')\n"
            "sys.path.insert(0, 'test/bin')\n"
            "check_mod = __import__('check-bootimus-settings')\n"
            "with mock.patch.object(check_mod, 'get_bootimus_credentials', return_value=('u', 'p')):\n"
            "    with mock.patch.object(check_mod, 'api_request') as mock_req:\n"
            "        mock_req.side_effect = [\n"
            "            {'data': {'token': 'dummy'}},\n"
            "            {'data': [{'filename': 'sync/gdc-labs-24.04-v0.9.26-debug.iso', 'distro': 'ubuntu', 'boot_method': 'kernel', 'enabled': True, 'extracted': True, 'boot_params': 'autoinstall ds=nocloud-net'}]}\n"
            "        ]\n"
            "        with mock.patch.object(check_mod, 'auto_heal_boot_params'):\n"
            "            sys.argv = ['check-bootimus-settings.py', 'gdc-labs-24.04-v0.9.26-debug.iso']\n"
            "            try:\n"
            "                check_mod.main()\n"
            "                print('SUCCESS')\n"
            "            except SystemExit as e:\n"
            "                print(f'EXIT_CODE_{e.code}')\n"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("EXIT_CODE_0", res.stdout)

    def test_bootimus_sh_fast_fail_python_version_older_than_3_8(self):
        """Verifies bootimus.sh fast-fails immediately if Python version is older than 3.8."""
        import tempfile
        bootimus_sh = os.path.join(PROJECT_ROOT, "bootimus.sh")
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_py = os.path.join(tmpdir, "fake_python3")
            with open(fake_py, "w") as f:
                f.write('#!/bin/sh\n'
                        'if [ "$1" = "-c" ]; then\n'
                        '    case "$2" in\n'
                        '        *">= (3, 8)"*)\n'
                        '            exit 1\n'
                        '            ;;\n'
                        '        *sys.version_info[:3]*)\n'
                        '            echo "3.6.8"\n'
                        '            exit 0\n'
                        '            ;;\n'
                        '    esac\n'
                        'fi\n'
                        'echo "Python 3.6.8"\n'
                        'exit 0\n')
            os.chmod(fake_py, 0o755)

            env = dict(os.environ)
            env["PYTHON_BIN"] = fake_py
            env.pop("VIRTUAL_ENV", None)

            res = subprocess.run([bootimus_sh, "--list"], capture_output=True, text=True, cwd=PROJECT_ROOT, env=env)
            self.assertNotEqual(res.returncode, 0, "bootimus.sh should fail when Python < 3.8")
            output = res.stderr + res.stdout
            self.assertIn("Python 3.8+", output)
            self.assertIn("3.6.8", output)



if __name__ == "__main__":
    unittest.main()
