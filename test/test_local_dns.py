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

"""Unit tests for dnsmasq and systemd-resolved split-DNS host configuration."""

import os
import unittest
import yaml
from jinja2 import Environment

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLocalDNS(unittest.TestCase):
    """Verifies dnsmasq package inclusion, Ansible local_dns role, configuration templates, and stage integration."""

    def test_packages_config_contains_dnsmasq(self):
        """Verifies packages_config.yaml bakes dnsmasq into the offline ISO cache."""
        config_path = os.path.join(PROJECT_ROOT, "src/build/packages_config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        platform_pkgs = set(cfg.get("packages_to_include", {}).get("platform_required", []))
        self.assertIn("dnsmasq", platform_pkgs, "Missing 'dnsmasq' in packages_config.yaml platform_required")

    def test_vars_all_dns_settings(self):
        """Verifies vars/all.yml and vars/all.yml.j2 define required domain names and dnsmasq configurations."""
        for filename in ("all.yml", "all.yml.j2"):
            vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars", filename)
            with open(vars_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("nexus.internal.gdc.local", content, f"{filename} missing 'nexus.internal.gdc.local'")
            self.assertIn("git.internal.gdc.local", content, f"{filename} missing 'git.internal.gdc.local'")
            self.assertIn("nexus.gdc.local", content, f"{filename} missing alias 'nexus.gdc.local'")
            self.assertIn("git.gdc.local", content, f"{filename} missing alias 'git.gdc.local'")
            self.assertIn("gdc_docker_registry_mirror: \"http://nexus.internal.gdc.local:5001\"", content, f"{filename} missing docker registry mirror pointing to nexus.internal.gdc.local")

    def test_local_dns_role_structure(self):
        """Verifies the local_dns role files and templates exist."""
        role_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/local_dns")
        self.assertTrue(os.path.isdir(role_dir), "Role directory src/ansible/roles/local_dns does not exist")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "defaults/main.yml")), "Missing defaults/main.yml")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "tasks/main.yml")), "Missing tasks/main.yml")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "templates/platform.conf.j2")), "Missing templates/platform.conf.j2")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "templates/internal-gdc.conf.j2")), "Missing templates/internal-gdc.conf.j2")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "templates/resolved-dnsmasq.conf.j2")), "Missing templates/resolved-dnsmasq.conf.j2")

    def test_local_dns_template_rendering(self):
        """Verifies platform.conf.j2 and internal-gdc.conf.j2 render expected directives."""
        role_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/local_dns")
        env = Environment()

        # Render platform.conf.j2
        with open(os.path.join(role_dir, "templates/platform.conf.j2"), "r", encoding="utf-8") as f:
            template = env.from_string(f.read())

        rendered_platform = template.render({
            "gdc_local_dns_loopback": "127.0.0.10",
            "gdc_service_hub_ip": "192.168.109.12",
            "gdc_local_dns_upstream_servers": ["1.1.1.1", "8.8.8.8"],
            "platform_dns_records": [
                {"name": "gdc-companion.ensor-labs.com", "ip": "192.168.20.102"},
                {"name": "step-ca.ensor-labs.com", "ip": "192.168.20.102"}
            ]
        })

        self.assertIn("listen-address=127.0.0.10,192.168.109.12", rendered_platform)
        self.assertIn("bind-interfaces", rendered_platform)
        self.assertIn("no-resolv", rendered_platform)
        self.assertIn("no-hosts", rendered_platform)
        self.assertIn("server=1.1.1.1", rendered_platform)
        self.assertIn("server=8.8.8.8", rendered_platform)
        self.assertIn("address=/gdc-companion.ensor-labs.com/192.168.20.102", rendered_platform)
        self.assertIn("address=/step-ca.ensor-labs.com/192.168.20.102", rendered_platform)

        # Render internal-gdc.conf.j2
        with open(os.path.join(role_dir, "templates/internal-gdc.conf.j2"), "r", encoding="utf-8") as f:
            template = env.from_string(f.read())

        rendered_internal = template.render({
            "gdc_nexus_domain": "nexus.internal.gdc.local",
            "gdc_nexus_alias": "nexus.gdc.local",
            "gdc_gitea_domain": "git.internal.gdc.local",
            "gdc_gitea_alias": "git.gdc.local",
            "gdc_service_hub_ip": "192.168.109.12",
            "custom_add_hosts_records": []
        })

        self.assertIn("address=/nexus.internal.gdc.local/192.168.109.12", rendered_internal)
        self.assertIn("address=/nexus.gdc.local/192.168.109.12", rendered_internal)
        self.assertIn("address=/git.internal.gdc.local/192.168.109.12", rendered_internal)
        self.assertIn("address=/git.gdc.local/192.168.109.12", rendered_internal)
        self.assertIn("local=/nexus.internal.gdc.local/", rendered_internal)
        self.assertIn("local=/internal.gdc.local/", rendered_internal)
        self.assertIn("local=/gdc.local/", rendered_internal)

        # Render resolved-dnsmasq.conf.j2
        with open(os.path.join(role_dir, "templates/resolved-dnsmasq.conf.j2"), "r", encoding="utf-8") as f:
            template = env.from_string(f.read())

        rendered_resolved = template.render({
            "gdc_local_dns_loopback": "127.0.0.10",
            "gdc_internal_dns_domains": ["~internal.gdc.local", "~gdc.local"]
        })

        self.assertIn("[Resolve]", rendered_resolved)
        self.assertIn("DNS=127.0.0.10", rendered_resolved)
        self.assertIn("Domains=~internal.gdc.local ~gdc.local", rendered_resolved)

    def test_stage_first_boot_integration(self):
        """Verifies stage_first_boot.yml invokes local_dns role before service_hubs."""
        first_boot_path = os.path.join(PROJECT_ROOT, "src/ansible/stages/stage_first_boot.yml")
        with open(first_boot_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("local_dns", content, "stage_first_boot.yml must include local_dns role")
        local_dns_idx = content.find("local_dns")
        service_hubs_idx = content.find("service_hubs")
        self.assertTrue(local_dns_idx != -1 and service_hubs_idx != -1 and local_dns_idx < service_hubs_idx,
                        "local_dns role must be executed before service_hubs role in stage_first_boot.yml")

    def test_service_hubs_and_tuning_domains(self):
        """Verifies service_hubs and system_tuning reference gdc_nexus_domain."""
        sh_tasks_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/tasks/main.yml")
        with open(sh_tasks_path, "r", encoding="utf-8") as f:
            sh_content = f.read()

        self.assertIn("gdc_nexus_domain", sh_content, "service_hubs must reference gdc_nexus_domain")
        self.assertIn("gdc_gitea_domain", sh_content, "service_hubs must reference gdc_gitea_domain")

        st_tasks_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/system_tuning/tasks/main.yml")
        with open(st_tasks_path, "r", encoding="utf-8") as f:
            st_content = f.read()

        self.assertIn("gdc_nexus_domain", st_content, "system_tuning containerd must reference gdc_nexus_domain")

    def test_stage_cluster_ready_resync(self):
        """Verifies stage_cluster_ready.yml re-syncs local_dns after machine_orchestration."""
        cluster_ready_path = os.path.join(PROJECT_ROOT, "src/ansible/stages/stage_cluster_ready.yml")
        with open(cluster_ready_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("local_dns", content, "stage_cluster_ready.yml must include local_dns role")
        orch_idx = content.find("machine_orchestration")
        local_dns_idx = content.find("local_dns")
        self.assertTrue(orch_idx != -1 and local_dns_idx != -1 and orch_idx < local_dns_idx,
                        "local_dns role must be re-synced after machine_orchestration in stage_cluster_ready.yml")

    def test_bootstrap_k8s_ip_sentinel(self):
        """Verifies build.env uses the high-numbered .253 bootstrap sentinel IP."""
        build_env_path = os.path.join(PROJECT_ROOT, "src/build/build.env")
        with open(build_env_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("BOOTSTRAP_K8S_IP_CIDR=172.31.250.253/24", content)

    def test_local_dns_ip_sanitization(self):
        """Verifies local_dns role tasks sanitize .0 network and .255 broadcast addresses."""
        tasks_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/local_dns/tasks/main.yml")
        with open(tasks_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("endswith('.0')", content)
        self.assertIn("endswith('.255')", content)
        self.assertIn("resolvectl query --type=A", content)
        self.assertIn("local_dns_effective_upstream_servers", content)


if __name__ == "__main__":
    unittest.main()
