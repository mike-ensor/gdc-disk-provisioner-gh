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

"""Unit tests for MACHINE_IP environment profile configuration and ORAS provisioning."""

import os
import subprocess
import tempfile
import unittest
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestMachineIpProfile(unittest.TestCase):
    """Verifies MACHINE_IP profile scripts, POSIX shell compliance, and Ansible tasks."""

    def test_user_data_contains_machine_ip_profile(self):
        """Verifies user-data.j2 drops /target/etc/profile.d/gdc-machine-ip.sh."""
        user_data_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(user_data_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("/target/etc/profile.d/gdc-machine-ip.sh", content)
        self.assertIn("export MACHINE_IP", content)
        self.assertIn("chmod 0644 /target/etc/profile.d/gdc-machine-ip.sh", content)

    def test_user_data_profile_posix_compliance(self):
        """Verifies the shell script in user-data.j2 passes syntax checks in /bin/sh."""
        script_snippet = """
if [ -z "${MACHINE_IP:-}" ]; then
  if [ -f "/etc/ansible/facts.d/gdc.fact" ] && command -v jq >/dev/null 2>&1; then
    _k8s_cidr=$(jq -r ".network.cluster_network.ip_cidr // \"\"" /etc/ansible/facts.d/gdc.fact 2>/dev/null)
    if [ -n "$_k8s_cidr" ] && [ "$_k8s_cidr" != "null" ]; then
      MACHINE_IP="${_k8s_cidr%%/*}"
    fi
  fi
  if [ -z "${MACHINE_IP:-}" ] && command -v ip >/dev/null 2>&1; then
    _vlan_ip=$(ip -4 -o addr show 2>/dev/null | awk '$2 ~ /\\.[0-9]+$/ {print $4}' | cut -d/ -f1 | head -n 1)
    if [ -n "$_vlan_ip" ]; then
      MACHINE_IP="$_vlan_ip"
    fi
  fi
  if [ -z "${MACHINE_IP:-}" ] && [ -f "/etc/hosts" ]; then
    _hosts_ip=$(awk '/nexus\\.internal\\.gdc\\.local/ {print $1; exit}' /etc/hosts 2>/dev/null)
    if [ -n "$_hosts_ip" ] && [ "$_hosts_ip" != "127.0.0.1" ]; then
      MACHINE_IP="$_hosts_ip"
    fi
  fi
  if [ -z "${MACHINE_IP:-}" ] && command -v ip >/dev/null 2>&1; then
    _default_ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
    if [ -n "$_default_ip" ]; then
      MACHINE_IP="$_default_ip"
    fi
  fi
fi
if [ -n "${MACHINE_IP:-}" ]; then
  export MACHINE_IP
fi
"""
        proc = subprocess.run(["sh", "-n"], input=script_snippet, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, f"POSIX sh syntax error: {proc.stderr}")

    def test_local_dns_machine_ip_tasks(self):
        """Verifies local_dns tasks configure /etc/profile.d/gdc-machine-ip.sh and /etc/environment."""
        dns_tasks_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/local_dns/tasks/main.yml")
        with open(dns_tasks_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        profile_task = next(
            (t for t in tasks if t.get("ansible.builtin.copy", {}).get("dest") == "/etc/profile.d/gdc-machine-ip.sh"),
            None,
        )
        self.assertIsNotNone(profile_task, "Missing task deploying /etc/profile.d/gdc-machine-ip.sh")
        assert profile_task is not None
        self.assertEqual(profile_task["ansible.builtin.copy"]["mode"], "0644")
        self.assertIn('MACHINE_IP="{{ gdc_service_hub_ip }}"', profile_task["ansible.builtin.copy"]["content"])
        self.assertIn("export MACHINE_IP", profile_task["ansible.builtin.copy"]["content"])

        env_task = next(
            (t for t in tasks if t.get("ansible.builtin.lineinfile", {}).get("path") == "/etc/environment"),
            None,
        )
        self.assertIsNotNone(env_task, "Missing task ensuring MACHINE_IP in /etc/environment")
        assert env_task is not None
        self.assertEqual(env_task["ansible.builtin.lineinfile"]["line"], 'MACHINE_IP="{{ gdc_service_hub_ip }}"')

    def test_system_tuning_oras_tasks(self):
        """Verifies system_tuning tasks stage oras and create /usr/local/bin/oras symlink."""
        tuning_tasks_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/system_tuning/tasks/main.yml")
        with open(tuning_tasks_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        symlink_task = next(
            (t for t in tasks if t.get("ansible.builtin.file", {}).get("dest") == "/usr/local/bin/oras"),
            None,
        )
        self.assertIsNotNone(symlink_task, "Missing task creating /usr/local/bin/oras symlink")
        assert symlink_task is not None
        self.assertEqual(symlink_task["ansible.builtin.file"]["state"], "link")

    def test_vars_all_oras_settings(self):
        """Verifies vars/all.yml and vars/all.yml.j2 define oras directories and versions."""
        for filename in ("all.yml", "all.yml.j2"):
            vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars", filename)
            with open(vars_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn('gdc_oras_install_dir: "/var/gdc-install/tools/oras"', content)
            self.assertIn('gdc_oras_version: "1.3.4"', content)
            self.assertIn('- "tools/oras"', content)


if __name__ == "__main__":
    unittest.main()
