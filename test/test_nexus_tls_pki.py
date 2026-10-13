#!/usr/bin/env python3
# Copyright 2026 Google LLC
# Apache-2.0

"""Unit tests for Dual-Tier Nexus TLS and Enterprise Sub-CA PKI architecture."""

import os
import unittest
import yaml
from jinja2 import Environment

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestNexusTLSPKI(unittest.TestCase):
    """Verifies PKI packaging, templates, Nginx configuration, and rotation timers."""

    def test_packages_config_contains_nginx(self):
        """Verifies packages_config.yaml includes nginx for offline host caching."""
        config_path = os.path.join(PROJECT_ROOT, "src/build/packages_config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        packages = set(cfg.get("packages_to_include", {}).get("platform_required", []))
        self.assertIn("nginx", packages, "Missing 'nginx' in platform_required packages")

    def test_ansible_vars_contain_pki_parameters(self):
        """Verifies all.yml and all.yml.j2 define default PKI paths, domains, and renewal thresholds."""
        vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars/all.yml")
        with open(vars_path, "r", encoding="utf-8") as f:
            vars_data = yaml.safe_load(f)

        expected_vars = {
            "gdc_nexus_tls_enabled": True,
            "gdc_nexus_https_port": 443,
            "gdc_sub_ca_dir": "/etc/ssl/sub-ca",
            "gdc_sub_ca_cert_path": "/etc/ssl/sub-ca/sub-ca.crt",
            "gdc_sub_ca_key_path": "/etc/ssl/sub-ca/sub-ca.key",
            "gdc_enterprise_root_cert_path": "/usr/local/share/ca-certificates/gdc-enterprise-root.crt",
            "gdc_nexus_cert_path": "/etc/ssl/certs/nexus.bundle.crt",
            "gdc_nexus_key_path": "/etc/ssl/private/nexus.key",
            "gdc_nexus_tls_renew_threshold_seconds": 2592000,
        }

        for var_name, expected_val in expected_vars.items():
            self.assertEqual(vars_data.get(var_name), expected_val, f"all.yml missing or incorrect {var_name}")

        j2_path = os.path.join(PROJECT_ROOT, "src/ansible/vars/all.yml.j2")
        with open(j2_path, "r", encoding="utf-8") as f:
            j2_content = f.read()

        for var_name in expected_vars:
            self.assertIn(var_name, j2_content, f"all.yml.j2 missing {var_name}")

    def test_pki_ingest_tasks_structure(self):
        """Verifies pki_ingest.yml parses cleanly, includes fallback logic, security guards, and mode 0400."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        self.assertTrue(os.path.exists(pki_task_path), "pki_ingest.yml does not exist")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        all_tasks = []
        def extract_tasks(task_list):
            for t in task_list:
                all_tasks.append(t)
                if "block" in t:
                    extract_tasks(t["block"])
        extract_tasks(tasks)

        task_names = [t.get("name", "") for t in all_tasks]

        self.assertTrue(any("Access Sub-CA Secret payload via gcloud" in name for name in task_names))
        self.assertTrue(any("Fallback: Access Sub-CA Secret payload as global resource" in name for name in task_names))
        self.assertTrue(any("Adopt fallback Sub-CA payload if successful" in name for name in task_names))
        self.assertTrue(any("Fail if Sub-CA secret retrieval failed" in name for name in task_names))
        self.assertTrue(any("Write Corporate Root CA" in name for name in task_names))
        self.assertTrue(any("Write Sub-CA Private Key" in name for name in task_names))

        # Assert no_log is enabled on sensitive tasks to prevent secret exposure
        sensitive_keywords = [
            "Access Sub-CA Secret payload via gcloud",
            "Fallback: Access Sub-CA Secret payload as global resource",
            "Adopt fallback Sub-CA payload if successful",
            "Write Sub-CA Private Key",
        ]
        for kw in sensitive_keywords:
            matching = [t for t in all_tasks if kw in t.get("name", "")]
            self.assertTrue(len(matching) > 0, f"Task matching '{kw}' not found")
            for t in matching:
                self.assertTrue(t.get("no_log") is True, f"Task '{t.get('name')}' must have no_log: true")

        # Assert sub-ca.key copy task has mode: '0400'
        key_tasks = [t for t in all_tasks if "Write Sub-CA Private Key" in t.get("name", "")]
        self.assertTrue(len(key_tasks) > 0, "Write Sub-CA Private Key task not found")
        for t in key_tasks:
            copy_cfg = t.get("ansible.builtin.copy", t.get("copy", {}))
            self.assertEqual(copy_cfg.get("mode"), "0400", "Sub-CA private key must have mode '0400'")

        # Assert fallback adopt condition checks that rc is defined and equals 0
        adopt_task = next((t for t in all_tasks if "Adopt fallback Sub-CA payload" in t.get("name", "")), None)
        self.assertIsNotNone(adopt_task, "Adopt fallback task not found")
        assert adopt_task is not None
        when_conds = adopt_task.get("when", [])
        self.assertTrue(
            any("gsm_sub_ca_res_fallback.rc is defined and gsm_sub_ca_res_fallback.rc == 0" in str(cond) for cond in when_conds),
            "Adopt fallback condition must verify 'rc is defined and rc == 0'"
        )

        # Assert clean fail task exists when secret retrieval fails
        fail_task = next((t for t in all_tasks if "Fail if Sub-CA secret retrieval failed" in t.get("name", "")), None)
        self.assertIsNotNone(fail_task, "Fail task not found")
        assert fail_task is not None
        self.assertIn("ansible.builtin.fail", fail_task)
        fail_action = fail_task.get("ansible.builtin.fail")
        self.assertIsInstance(fail_action, dict)
        assert isinstance(fail_action, dict)
        self.assertIn("Failed to retrieve Sub-CA secret", fail_action.get("msg", ""))

    def test_pki_ingest_project_flag_guard(self):
        """Verifies --project flag is guarded so empty project ID does not emit --project=."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            content = f.read()

        guard_snippet = "{% if gcp_project_id is defined and gcp_project_id | trim | length > 0 %}--project={{ gcp_project_id }}{% endif %}"
        self.assertIn(guard_snippet, content, "pki_ingest.yml must guard --project flag")

        env = Environment()
        template = env.from_string(guard_snippet)
        self.assertEqual(template.render(gcp_project_id="").strip(), "")
        self.assertEqual(template.render(gcp_project_id="   ").strip(), "")
        self.assertEqual(template.render(gcp_project_id="my-project").strip(), "--project=my-project")

    def test_rotation_script_and_systemd_templates(self):
        """Verifies refresh-nexus-tls script, service, and timer templates render valid syntax."""
        env = Environment()
        script_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/refresh-nexus-tls.sh.j2")
        self.assertTrue(os.path.exists(script_path), "refresh-nexus-tls.sh.j2 does not exist")
        with open(script_path, "r", encoding="utf-8") as f:
            script_tmpl = env.from_string(f.read())
        rendered_script = script_tmpl.render(
            gdc_nexus_cert_path="/etc/ssl/certs/nexus.bundle.crt",
            gdc_nexus_key_path="/etc/ssl/private/nexus.key",
            gdc_sub_ca_cert_path="/etc/ssl/sub-ca/sub-ca.crt",
            gdc_sub_ca_key_path="/etc/ssl/sub-ca/sub-ca.key",
            gdc_nexus_domain="nexus.internal.gdc.local",
            gdc_nexus_alias="nexus.gdc.local",
            gdc_nexus_tls_renew_threshold_seconds=2592000
        )
        self.assertIn("step certificate create nexus.internal.gdc.local", rendered_script)
        self.assertIn("--bundle", rendered_script)
        self.assertIn("systemctl reload nginx", rendered_script)

        service_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/refresh-nexus-tls.service.j2")
        self.assertTrue(os.path.exists(service_path), "refresh-nexus-tls.service.j2 does not exist")
        with open(service_path, "r", encoding="utf-8") as f:
            service_content = f.read()
        self.assertIn("ExecStart=/usr/local/bin/refresh-nexus-tls.sh", service_content)

        timer_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/refresh-nexus-tls.timer.j2")
        self.assertTrue(os.path.exists(timer_path), "refresh-nexus-tls.timer.j2 does not exist")
        with open(timer_path, "r", encoding="utf-8") as f:
            timer_content = f.read()
        self.assertIn("OnCalendar=Sun *-*-* 03:00:00", timer_content)

if __name__ == "__main__":
    unittest.main()
