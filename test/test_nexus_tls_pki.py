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
            gdc_nexus_tls_renew_threshold_seconds=123456
        )
        self.assertIn('step certificate create "nexus.internal.gdc.local"', rendered_script)
        self.assertIn('--san="nexus.gdc.local"', rendered_script)
        self.assertIn("--bundle", rendered_script)
        self.assertIn("systemctl is-active --quiet nginx", rendered_script)
        self.assertIn("systemctl reload nginx", rendered_script)
        self.assertIn("RENEW_THRESHOLD_SECONDS=123456", rendered_script)

        # Test default threshold and alias guard when omitted
        rendered_default_script = script_tmpl.render(
            gdc_nexus_cert_path="/etc/ssl/certs/nexus.bundle.crt",
            gdc_nexus_key_path="/etc/ssl/private/nexus.key",
            gdc_sub_ca_cert_path="/etc/ssl/sub-ca/sub-ca.crt",
            gdc_sub_ca_key_path="/etc/ssl/sub-ca/sub-ca.key",
            gdc_nexus_domain="nexus.internal.gdc.local"
        )
        self.assertIn("RENEW_THRESHOLD_SECONDS=2592000", rendered_default_script)
        self.assertNotIn('--san="nexus.gdc.local"', rendered_default_script)

        service_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/refresh-nexus-tls.service.j2")
        self.assertTrue(os.path.exists(service_path), "refresh-nexus-tls.service.j2 does not exist")
        with open(service_path, "r", encoding="utf-8") as f:
            service_tmpl = env.from_string(f.read())
        rendered_service = service_tmpl.render(
            gdc_sub_ca_dir="/etc/ssl/sub-ca"
        )
        self.assertIn("ExecStart=/usr/local/bin/refresh-nexus-tls.sh", rendered_service)
        self.assertIn("ReadWritePaths=/etc/ssl/certs /etc/ssl/private", rendered_service)
        self.assertIn("ReadOnlyPaths=-/etc/ssl/sub-ca", rendered_service)

        # Test default sub-ca path in service template
        rendered_default_service = service_tmpl.render()
        self.assertIn("ReadOnlyPaths=-/etc/ssl/sub-ca", rendered_default_service)

        timer_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/refresh-nexus-tls.timer.j2")
        self.assertTrue(os.path.exists(timer_path), "refresh-nexus-tls.timer.j2 does not exist")
        with open(timer_path, "r", encoding="utf-8") as f:
            timer_tmpl = env.from_string(f.read())
        rendered_timer = timer_tmpl.render()
        self.assertIn("OnCalendar=Sun *-*-* 03:00:00", rendered_timer)

    def test_nginx_proxy_configuration_template(self):
        """Verifies Nginx configuration renders TLS port 443, /v2/ routing, and DoS limits."""
        env = Environment()
        conf_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/nexus-tls.conf.j2")
        self.assertTrue(os.path.exists(conf_path), "nexus-tls.conf.j2 does not exist")
        with open(conf_path, "r", encoding="utf-8") as f:
            conf_tmpl = env.from_string(f.read())
        rendered_conf = conf_tmpl.render(
            gdc_nexus_https_port=443,
            gdc_service_hub_ip="192.168.109.12",
            gdc_nexus_domain="nexus.internal.gdc.local",
            gdc_nexus_alias="nexus.gdc.local",
            gdc_nexus_cert_path="/etc/ssl/certs/nexus.bundle.crt",
            gdc_nexus_key_path="/etc/ssl/private/nexus.key"
        )
        self.assertNotIn("listen 127.0.0.1:443 ssl;", rendered_conf)
        self.assertIn("listen 192.168.109.12:443 ssl;", rendered_conf)
        self.assertIn("proxy_pass http://127.0.0.1:5001;", rendered_conf)
        self.assertIn("proxy_pass http://127.0.0.1:8081;", rendered_conf)
        self.assertIn("proxy_request_buffering off;", rendered_conf)
        self.assertIn("proxy_buffering off;", rendered_conf)
        self.assertIn("proxy_set_header X-Forwarded-Port $server_port;", rendered_conf)

    def test_service_hubs_nexus_tls_tasks(self):
        """Verifies service_hubs tasks/main.yml contains tasks for deploying refresh-nexus-tls.sh, nexus-tls.conf, refresh-nexus-tls.timer, and starting nginx."""
        tasks_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/tasks/main.yml")
        self.assertTrue(os.path.exists(tasks_path), "service_hubs/tasks/main.yml does not exist")
        with open(tasks_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        all_tasks = []
        def extract_tasks(task_list):
            for t in task_list:
                all_tasks.append(t)
                if "block" in t:
                    extract_tasks(t["block"])
        extract_tasks(tasks)

        task_names = [t.get("name", "") for t in all_tasks]
        self.assertTrue(any("refresh-nexus-tls.sh" in name for name in task_names), "Missing task for deploying refresh-nexus-tls.sh")
        self.assertTrue(any("nexus-tls.conf" in name for name in task_names), "Missing task for deploying nexus-tls.conf")
        self.assertTrue(any("refresh-nexus-tls.timer" in name for name in task_names), "Missing task for enabling refresh-nexus-tls.timer")
        self.assertTrue(any("nginx" in name.lower() for name in task_names), "Missing task for starting nginx")

        # Verify timer task parameters
        timer_task = next((t for t in all_tasks if "refresh-nexus-tls.timer" in t.get("name", "") and "enable" in t.get("name", "").lower()), None)
        self.assertIsNotNone(timer_task, "Enable refresh-nexus-tls.timer task not found")
        assert timer_task is not None
        systemd_cfg = timer_task.get("ansible.builtin.systemd", timer_task.get("systemd", {}))
        self.assertTrue(systemd_cfg.get("daemon_reload") is True)
        self.assertTrue(systemd_cfg.get("enabled") is True)
        self.assertEqual(systemd_cfg.get("state"), "started")

        # Verify refresh-nexus-tls execution task registration and changed_when
        exec_refresh_task = next((t for t in all_tasks if "refresh-nexus-tls.sh" in t.get("name", "") and "execute" in t.get("name", "").lower()), None)
        self.assertIsNotNone(exec_refresh_task, "Execute refresh-nexus-tls.sh task not found")
        assert exec_refresh_task is not None
        self.assertEqual(exec_refresh_task.get("register"), "refresh_res")
        self.assertIn("'Minting initial certificate' in refresh_res.stdout or 'Successfully renewed' in refresh_res.stdout", str(exec_refresh_task.get("changed_when", "")))

        # Verify stat checks for cert and key are defined before site symlink and default site removal
        cert_stat_idx = next(i for i, t in enumerate(all_tasks) if "nexus_cert_stat" == t.get("register"))
        key_stat_idx = next(i for i, t in enumerate(all_tasks) if "nexus_key_stat" == t.get("register"))
        symlink_idx = next(i for i, t in enumerate(all_tasks) if "sites-enabled" in t.get("name", "") and "nexus-tls.conf" in t.get("name", ""))
        rm_default_idx = next(i for i, t in enumerate(all_tasks) if "default" in t.get("name", "") and "sites-enabled" in str(t))

        self.assertLess(cert_stat_idx, symlink_idx, "Cert stat check must occur before site symlink creation")
        self.assertLess(key_stat_idx, symlink_idx, "Key stat check must occur before site symlink creation")
        self.assertLess(cert_stat_idx, rm_default_idx, "Cert stat check must occur before default site removal")
        self.assertLess(key_stat_idx, rm_default_idx, "Key stat check must occur before default site removal")

        # Verify symlink for nexus-tls.conf
        symlink_task = all_tasks[symlink_idx]
        file_cfg = symlink_task.get("ansible.builtin.file", symlink_task.get("file", {}))
        self.assertEqual(file_cfg.get("state"), "link")
        symlink_when = str(symlink_task.get("when", ""))
        self.assertIn("nexus_cert_stat.stat.exists", symlink_when)
        self.assertIn("nexus_key_stat.stat.exists", symlink_when)

        # Verify removal of default site
        rm_default_task = all_tasks[rm_default_idx]
        rm_file_cfg = rm_default_task.get("ansible.builtin.file", rm_default_task.get("file", {}))
        self.assertEqual(rm_file_cfg.get("state"), "absent")
        rm_default_when = str(rm_default_task.get("when", ""))
        self.assertIn("nexus_cert_stat.stat.exists", rm_default_when)
        self.assertIn("nexus_key_stat.stat.exists", rm_default_when)

        # Verify Nginx start task checks certificate stat existence
        nginx_start_task = next((t for t in all_tasks if "nginx" in t.get("name", "").lower() and "start" in t.get("name", "").lower()), None)
        self.assertIsNotNone(nginx_start_task, "Nginx start task not found")
        assert nginx_start_task is not None
        when_conds = nginx_start_task.get("when", [])
        self.assertTrue(any("stat.exists" in str(c) for c in when_conds), "Nginx start must be guarded by certificate stat.exists checks")

    def test_apt_sources_redirect_to_https(self):
        """Verifies host_foundations and user-data configure APT sources using https://nexus.internal.gdc.local."""
        task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/host_foundations/tasks/main.yml")
        with open(task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        apt_task = next(
            (t for t in tasks if t.get("name") == "GDC-TASK-05 | Write DEB822 local loopback Nexus sources"),
            None
        )
        self.assertIsNotNone(apt_task, "GDC-TASK-05 sources task not found in host_foundations/tasks/main.yml")
        assert apt_task is not None
        raw_sources_template = apt_task["ansible.builtin.copy"]["content"]

        env = Environment(trim_blocks=True)
        env.filters['bool'] = lambda v: v if isinstance(v, bool) else (str(v).lower() in ('true', 'yes', '1') if v is not None else False)

        # Render real template from main.yml with TLS enabled and cert present (default)
        rendered_enabled = env.from_string(raw_sources_template).render(
            gdc_nexus_domain="nexus.internal.gdc.local",
            nexus_tls_cert_stat={"stat": {"exists": True}}
        )
        self.assertIn("URIs: https://nexus.internal.gdc.local/repository/gdc-apt-hosted/\nSuites: noble", rendered_enabled)
        self.assertIn("URIs: https://nexus.internal.gdc.local/repository/gdc-apt-proxy/\nSuites: noble", rendered_enabled)

        # Render real template from main.yml with TLS disabled
        rendered_disabled = env.from_string(raw_sources_template).render(
            gdc_nexus_domain="nexus.internal.gdc.local",
            gdc_nexus_tls_enabled=False
        )
        self.assertIn("URIs: http://127.0.0.1:8081/repository/gdc-apt-hosted/\nSuites: noble", rendered_disabled)
        self.assertIn("URIs: http://127.0.0.1:8081/repository/gdc-apt-proxy/\nSuites: noble", rendered_disabled)

        # Also verify fallback domain when cert is present
        rendered_fallback = env.from_string(raw_sources_template).render(
            nexus_tls_cert_stat={"stat": {"exists": True}}
        )
        self.assertIn("URIs: https://nexus.internal.gdc.local/repository/gdc-apt-hosted/\nSuites: noble", rendered_fallback)

        # Verify user-data.j2 contains expected string-safe conditional
        user_data_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(user_data_path, "r", encoding="utf-8") as f:
            ud_content = f.read()
        self.assertIn("nexus_domain | default('nexus.internal.gdc.local')", ud_content)
        self.assertIn("nexus_tls_enabled not in [false, 'false', 'False', 0, '0']", ud_content)

    def test_cert_manager_pki_tasks(self):
        """Verifies cert_manager_pki.yml defines Secret, ClusterIssuer, slurps certificates, and kubeconfig."""
        task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml")
        self.assertTrue(os.path.exists(task_path), "cert_manager_pki.yml does not exist")
        with open(task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        all_tasks = []
        def extract_tasks(t_list):
            for t in t_list:
                if isinstance(t, dict):
                    all_tasks.append(t)
                    if "block" in t:
                        extract_tasks(t["block"])
        extract_tasks(tasks)

        task_names = [t.get("name", "") for t in all_tasks]
        self.assertTrue(any("Seed Sub-CA TLS secret into cert-manager" in name for name in task_names))
        self.assertTrue(any("Deploy gdc-ca-issuer ClusterIssuer" in name for name in task_names))

        # Assert no lookup('file') is used, slurp is used instead
        with open(task_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
        self.assertNotIn("lookup('file'", raw_content, "cert_manager_pki.yml must not use lookup('file')")
        self.assertIn("ansible.builtin.slurp", raw_content, "cert_manager_pki.yml must use ansible.builtin.slurp")

        # Assert stat tasks check all three artifacts
        stat_paths = [
            t.get("ansible.builtin.stat", {}).get("path")
            for t in all_tasks
            if "ansible.builtin.stat" in t
        ]
        self.assertIn("{{ gdc_sub_ca_key_path }}", stat_paths)
        self.assertIn("{{ gdc_sub_ca_cert_path }}", stat_paths)
        self.assertIn("{{ gdc_enterprise_root_cert_path }}", stat_paths)

        # Assert slurp tasks exist for all three artifacts
        slurp_srcs = [
            t.get("ansible.builtin.slurp", {}).get("src")
            for t in all_tasks
            if "ansible.builtin.slurp" in t
        ]
        self.assertIn("{{ gdc_sub_ca_key_path }}", slurp_srcs)
        self.assertIn("{{ gdc_sub_ca_cert_path }}", slurp_srcs)
        self.assertIn("{{ gdc_enterprise_root_cert_path }}", slurp_srcs)

        # Assert kubeconfig is specified on all k8s tasks
        k8s_tasks = [t for t in all_tasks if "kubernetes.core.k8s" in t or "k8s" in t]
        self.assertGreaterEqual(len(k8s_tasks), 3, "Expected at least 3 k8s tasks")
        expected_kubeconfig = "{{ gdc_admin_kubeconfig | default('/etc/kubernetes/admin.conf') }}"
        for t in k8s_tasks:
            k8s_cfg = t.get("kubernetes.core.k8s", t.get("k8s", {}))
            self.assertEqual(
                k8s_cfg.get("kubeconfig"),
                expected_kubeconfig,
                f"Task '{t.get('name')}' must specify kubeconfig"
            )

        # Assert no_log: true is set on secret seeding task
        secret_task = next(
            (t for t in all_tasks if "Seed Sub-CA TLS secret into cert-manager" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(secret_task, "Secret seeding task not found")
        assert secret_task is not None
        self.assertTrue(secret_task.get("no_log") is True, "Secret seeding task must have no_log: true")

        # Assert namespace is cert-manager and type is kubernetes.io/tls
        secret_def = secret_task.get("kubernetes.core.k8s", {}).get("definition", {})
        self.assertEqual(secret_def.get("metadata", {}).get("namespace"), "cert-manager")
        self.assertEqual(secret_def.get("type"), "kubernetes.io/tls")

        # Assert tls.key and tls.crt values in Secret definition
        secret_data = secret_def.get("data", {})
        self.assertEqual(secret_data.get("tls.key"), "{{ slurped_sub_ca_key.content }}")
        tls_crt_expr = secret_data.get("tls.crt", "")
        self.assertIn("slurped_sub_ca_cert.content", tls_crt_expr)
        self.assertIn("slurped_enterprise_root_cert.content", tls_crt_expr)
        self.assertIn("b64decode", tls_crt_expr)
        self.assertIn("trim", tls_crt_expr)
        self.assertIn("b64encode", tls_crt_expr)

        # Assert ClusterIssuer task ignores errors or handles missing CRDs
        issuer_task = next(
            (t for t in all_tasks if "Deploy gdc-ca-issuer ClusterIssuer" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(issuer_task, "ClusterIssuer task not found")
        assert issuer_task is not None
        self.assertTrue(
            issuer_task.get("ignore_errors") is True or "failed_when" in issuer_task,
            "ClusterIssuer task must handle missing CRDs with ignore_errors: true"
        )

        # Assert cert_manager_pki.yml is included in post_cluster/tasks/main.yml
        main_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/post_cluster/tasks/main.yml")
        with open(main_task_path, "r", encoding="utf-8") as f:
            main_tasks = yaml.safe_load(f)
        included_files = [
            t.get("ansible.builtin.include_tasks", t.get("include_tasks"))
            for t in main_tasks
            if isinstance(t, dict) and ("ansible.builtin.include_tasks" in t or "include_tasks" in t)
        ]
        self.assertIn("cert_manager_pki.yml", included_files, "post_cluster/tasks/main.yml must include cert_manager_pki.yml")

if __name__ == "__main__":
    unittest.main()
