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
            "gdc_fallback_sub_ca_path": "/var/gdc-install/pki/fallback-sub-ca.json",
            "gdc_fallback_sub_ca_gsm_name": "gdc-fallback-sub-ca",
            "gdc_fallback_sub_ca_gsm_location": "us-east4",
            "gdc_fallback_sub_ca_gsm_project": "anthos-bare-metal-lab-1",
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
        self.assertTrue(any("Access Central Fallback Sub-CA Secret payload via gcloud" in name for name in task_names))
        self.assertTrue(any("Adopt Central Fallback Sub-CA payload if successful" in name for name in task_names))
        self.assertTrue(any("Fail stage if neither primary nor fallback Sub-CA was resolved" in name for name in task_names))
        self.assertTrue(any("Write Corporate Root CA" in name for name in task_names))
        self.assertTrue(any("Write Sub-CA Private Key" in name for name in task_names))

        # Assert no_log is enabled on sensitive tasks to prevent secret exposure
        sensitive_keywords = [
            "Access Sub-CA Secret payload via gcloud",
            "Fallback: Access Sub-CA Secret payload as global resource",
            "Adopt fallback Sub-CA payload if successful",
            "Access Central Fallback Sub-CA Secret payload via gcloud",
            "Adopt Central Fallback Sub-CA payload if successful",
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

        guard_snippet = "{% if sub_ca_gsm_project is defined and sub_ca_gsm_project | trim | length > 0 %}--project={{ sub_ca_gsm_project }}{% endif %}"
        self.assertIn(guard_snippet, content, "pki_ingest.yml must guard --project flag")

        env = Environment()
        template = env.from_string(guard_snippet)
        self.assertEqual(template.render(sub_ca_gsm_project="").strip(), "")
        self.assertEqual(template.render(sub_ca_gsm_project="   ").strip(), "")
        self.assertEqual(template.render(sub_ca_gsm_project="my-project").strip(), "--project=my-project")

    def test_pki_ingest_sub_ca_secret_resolution(self):
        """Verifies pki_ingest.yml resolves sub_ca_secret from cluster_config or top-level machine_config."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        resolve_task = next(
            (t for t in tasks if "Resolve Nexus TLS requirements & Sub-CA GSM configuration" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(resolve_task, "Resolve Nexus TLS requirements task not found")
        assert resolve_task is not None
        set_facts = resolve_task.get("ansible.builtin.set_fact", {})

        env = Environment()
        name_tmpl = env.from_string(set_facts["sub_ca_gsm_name"])
        loc_tmpl = env.from_string(set_facts["sub_ca_gsm_location"])
        proj_tmpl = env.from_string(set_facts["sub_ca_gsm_project"])

        # 1. Cluster-assigned machine: cluster_config has sub_ca_secret
        cluster_ctx = {
            "cluster_config": {
                "sub_ca_secret": {
                    "gsm-name": "cluster-sub-ca",
                    "gsm-location": "us-central1",
                    "gsm-project": "cluster-pki-proj",
                }
            },
            "machine_config": {},
            "gcp_project_id": "default-node-proj",
        }
        self.assertEqual(name_tmpl.render(**cluster_ctx).strip(), "cluster-sub-ca")
        self.assertEqual(loc_tmpl.render(**cluster_ctx).strip(), "us-central1")
        self.assertEqual(proj_tmpl.render(**cluster_ctx).strip(), "cluster-pki-proj")

        # 2. Unassigned machine: cluster_config is {} (cluster: null) and machine_config has top-level sub_ca_secret
        unassigned_ctx = {
            "cluster_config": {},
            "machine_config": {
                "cluster": None,
                "sub_ca_secret": {
                    "gsm-name": "machine-warm-spare-sub-ca",
                    "gsm-location": "us-east4",
                    "gsm-project": "machine-pki-proj",
                },
            },
            "gcp_project_id": "default-node-proj",
        }
        self.assertEqual(name_tmpl.render(**unassigned_ctx).strip(), "machine-warm-spare-sub-ca")
        self.assertEqual(loc_tmpl.render(**unassigned_ctx).strip(), "us-east4")
        self.assertEqual(proj_tmpl.render(**unassigned_ctx).strip(), "machine-pki-proj")

        # 3. Precedence: when both are present, cluster_config.sub_ca_secret takes precedence
        both_ctx = {
            "cluster_config": {
                "sub_ca_secret": {
                    "gsm-name": "cluster-sub-ca",
                    "gsm-location": "us-west1",
                    "gsm-project": "cluster-pki-proj",
                }
            },
            "machine_config": {
                "sub_ca_secret": {
                    "gsm-name": "machine-sub-ca",
                    "gsm-location": "us-east1",
                    "gsm-project": "machine-pki-proj",
                }
            },
            "gcp_project_id": "default-node-proj",
        }
        self.assertEqual(name_tmpl.render(**both_ctx).strip(), "cluster-sub-ca")
        self.assertEqual(loc_tmpl.render(**both_ctx).strip(), "us-west1")
        self.assertEqual(proj_tmpl.render(**both_ctx).strip(), "cluster-pki-proj")

        # 4. Null cluster and null sub_ca_secret fall back cleanly to defaults without error
        null_ctx = {
            "cluster_config": None,
            "machine_config": {"cluster": None, "sub_ca_secret": None},
            "gcp_project_id": "default-node-proj",
        }
        self.assertEqual(name_tmpl.render(**null_ctx).strip(), "")
        self.assertEqual(loc_tmpl.render(**null_ctx).strip(), "global")
        self.assertEqual(proj_tmpl.render(**null_ctx).strip(), "default-node-proj")

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

        # Assert kubeconfig is specified on all kubectl tasks
        k8s_tasks = [t for t in all_tasks if "kubectl" in str(t.get("ansible.builtin.command", {}).get("cmd", ""))]
        self.assertGreaterEqual(len(k8s_tasks), 3, "Expected at least 3 kubectl tasks")
        expected_kubeconfig = "{{ gdc_admin_kubeconfig | default('/etc/kubernetes/admin.conf') }}"
        for t in k8s_tasks:
            cmd = t.get("ansible.builtin.command", {}).get("cmd", "")
            self.assertIn(expected_kubeconfig, cmd, f"Task '{t.get('name')}' must specify kubeconfig")

        # Assert no_log: true is set on secret seeding task
        secret_task = next(
            (t for t in all_tasks if "Seed Sub-CA TLS secret into cert-manager" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(secret_task, "Secret seeding task not found")
        assert secret_task is not None
        self.assertTrue(secret_task.get("no_log") is True, "Secret seeding task must have no_log: true")

        # Assert namespace is cert-manager and type is kubernetes.io/tls in stdin
        secret_stdin = secret_task.get("ansible.builtin.command", {}).get("stdin", "")
        self.assertIn("namespace: cert-manager", secret_stdin)
        self.assertIn("type: kubernetes.io/tls", secret_stdin)
        self.assertIn("tls.key: \"{{ slurped_sub_ca_key.content }}\"", secret_stdin)
        self.assertIn("slurped_sub_ca_cert.content", secret_stdin)
        self.assertIn("slurped_enterprise_root_cert.content", secret_stdin)
        self.assertIn("b64decode", secret_stdin)
        self.assertIn("trim", secret_stdin)
        self.assertIn("b64encode", secret_stdin)

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
        issuer_stdin = issuer_task.get("ansible.builtin.command", {}).get("stdin", "")
        self.assertIn("kind: ClusterIssuer", issuer_stdin)
        self.assertIn("name: gdc-ca-issuer", issuer_stdin)
        self.assertIn("secretName: gdc-sub-ca-keypair", issuer_stdin)

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

    def test_stage_cluster_ready_nexus_tls_resync(self):
        """Verifies stage_cluster_ready.yml re-syncs nexus-tls.conf and reloads Nginx after network reconfiguration."""
        stage_path = os.path.join(PROJECT_ROOT, "src/ansible/stages/stage_cluster_ready.yml")
        self.assertTrue(os.path.exists(stage_path), "stage_cluster_ready.yml does not exist")
        with open(stage_path, "r", encoding="utf-8") as f:
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
        self.assertTrue(
            any("Re-sync nexus-tls.conf with active cluster network IP" in name for name in task_names),
            "Missing task to re-sync nexus-tls.conf in stage_cluster_ready"
        )
        self.assertTrue(
            any("Reload Nginx after cluster IP re-sync" in name for name in task_names),
            "Missing task to reload Nginx in stage_cluster_ready"
        )

    def test_pki_ingest_cert_and_config_presence_evidence(self):
        """Verifies pki_ingest.yml checks cert & config presence, builds evidence, and asserts existence."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        all_tasks = []
        def extract_tasks(task_list):
            for t in task_list:
                if isinstance(t, dict):
                    all_tasks.append(t)
                    if "block" in t:
                        extract_tasks(t["block"])
        extract_tasks(tasks)

        task_names = [t.get("name", "") for t in all_tasks]
        self.assertTrue(
            any("Check if Nexus TLS certificate exists" in name for name in task_names),
            "Missing task checking Nexus TLS certificate existence"
        )
        self.assertTrue(
            any("Check if Nexus TLS site configuration exists" in name for name in task_names),
            "Missing task checking Nexus TLS site configuration existence"
        )
        self.assertTrue(
            any("Record Nexus TLS evidence" in name for name in task_names),
            "Missing task to record Nexus TLS evidence"
        )
        self.assertTrue(
            any("Assert Nexus TLS certificate and configuration exist" in name for name in task_names),
            "Missing assertion task for Nexus TLS cert and config presence"
        )

        # Verify evidence structure
        evidence_task = next(
            (t for t in all_tasks if "Record Nexus TLS evidence" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(evidence_task, "Record Nexus TLS evidence task not found")
        assert evidence_task is not None
        set_fact_data = evidence_task.get("ansible.builtin.set_fact", {})
        evidence = set_fact_data.get("nexus_tls_evidence", {})
        self.assertIn("should_exist", evidence)
        self.assertIn("cert_exists", evidence)
        self.assertIn("config_exists", evidence)
        self.assertIn("gsm_secret_name", evidence)
        self.assertIn("gsm_secret_location", evidence)

    def test_cluster_ready_evidence_includes_nexus_tls(self):
        """Verifies machine_orchestration/tasks/main.yml includes nexus_tls in cluster_ready_evidence."""
        main_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/main.yml")
        with open(main_task_path, "r", encoding="utf-8") as f:
            main_tasks = yaml.safe_load(f)

        evidence_task = next(
            (t for t in main_tasks if t.get("name") == "GDC-EVIDENCE | Structure Evidence Facts"),
            None
        )
        self.assertIsNotNone(evidence_task, "Structure Evidence Facts task not found")
        assert evidence_task is not None
        evidence_dict = evidence_task.get("ansible.builtin.set_fact", {}).get("cluster_ready_evidence", {})
        self.assertIn("nexus_tls", evidence_dict, "cluster_ready_evidence must include 'nexus_tls'")

    def test_stage_cluster_ready_guards_by_cert_presence(self):
        """Verifies stage_cluster_ready.yml checks certificate existence before enabling site and reloading Nginx."""
        stage_path = os.path.join(PROJECT_ROOT, "src/ansible/stages/stage_cluster_ready.yml")
        with open(stage_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        self.assertTrue(
            any("Check if Nexus TLS certificate exists" in name for name in task_names),
            "Missing task checking Nexus TLS certificate existence in stage_cluster_ready"
        )

        # Block enclosing site activation must require certificate and config existence
        block_task = next(
            (t for t in tasks if isinstance(t, dict) and "Activate Nexus TLS reverse proxy site" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(block_task, "Block activating Nexus TLS site not found")
        assert block_task is not None
        when_conds = str(block_task.get("when", []))
        self.assertIn("nexus_cert_stat", when_conds)
        self.assertIn("nexus_tls_site_conf_stat", when_conds)

    def test_corp_cert_tags_present(self):
        """Verifies 'corp-cert' tag is applied across pki_ingest, service_hubs, cert_manager_pki, and stage_cluster_ready."""
        files_to_check = [
            "src/ansible/roles/service_hubs/tasks/main.yml",
            "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml",
            "src/ansible/roles/machine_orchestration/tasks/main.yml",
            "src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml",
            "src/ansible/roles/post_cluster/tasks/main.yml",
            "src/ansible/stages/stage_cluster_ready.yml",
            "src/ansible/roles/host_foundations/tasks/main.yml"
        ]
        for rel_path in files_to_check:
            full_path = os.path.join(PROJECT_ROOT, rel_path)
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("corp-cert", content, f"File {rel_path} must contain 'corp-cert' tag")

    def test_fallback_sub_ca_tasks_and_purge(self):
        """Verifies pki_ingest.yml includes fallback Sub-CA check, ingestion, and ephemeral purge."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        all_tasks = []
        def extract_tasks(task_list):
            for t in task_list:
                if isinstance(t, dict):
                    all_tasks.append(t)
                    if "block" in t:
                        extract_tasks(t["block"])
        extract_tasks(tasks)

        task_names = [t.get("name", "") for t in all_tasks]
        self.assertTrue(
            any("Check for pre-baked fallback Sub-CA credentials" in name for name in task_names),
            "Missing task checking for pre-baked fallback Sub-CA credentials"
        )
        self.assertTrue(
            any("Ingest Pre-Baked Fallback Sub-CA credentials" in name for name in task_names),
            "Missing task ingesting pre-baked fallback Sub-CA credentials"
        )
        self.assertTrue(
            any("Securely purge temporary fallback Sub-CA payload" in name for name in task_names),
            "Missing task to securely purge temporary fallback Sub-CA payload"
        )

        purge_task = next(
            (t for t in all_tasks if "Securely purge temporary fallback Sub-CA payload" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(purge_task)
        assert purge_task is not None
        file_args = purge_task.get("ansible.builtin.file", {})
        self.assertEqual(file_args.get("state"), "absent")

    def test_remaster_stages_fallback_sub_ca(self):
        """Verifies remaster.sh stages fallback Sub-CA credentials into /custom-data/pki/ without location."""
        remaster_path = os.path.join(PROJECT_ROOT, "src/build/remaster.sh")
        with open(remaster_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("custom-data/pki", content)
        self.assertIn("fallback-sub-ca.json", content)
        self.assertIn("gdc-fallback-sub-ca", content)
        # Pulling latest version must not pass location
        self.assertNotIn("--location=", content[content.find("Staging fallback Sub-CA credentials"):content.find("Smallstep CLI package")])

    def test_fallback_sub_ca_pull_omits_location(self):
        """Verifies pki_ingest.yml accesses fallback Sub-CA latest version without --location."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        all_tasks = []
        def extract_tasks(task_list):
            for t in task_list:
                if isinstance(t, dict):
                    all_tasks.append(t)
                    if "block" in t:
                        extract_tasks(t["block"])
        extract_tasks(tasks)

        fallback_task = next(
            (t for t in all_tasks if "Access Central Fallback Sub-CA Secret payload via gcloud" in t.get("name", "")),
            None
        )
        self.assertIsNotNone(fallback_task, "Access Central Fallback Sub-CA task not found")
        assert fallback_task is not None
        cmd = fallback_task.get("ansible.builtin.command", "")
        self.assertNotIn("--location", cmd, "Fallback Sub-CA command must not include --location")

    def test_refresh_nexus_tls_sans_strictly_local(self):
        """Verifies refresh-nexus-tls.sh.j2 mints leaf cert for internal domains without public demo domain."""
        template_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/refresh-nexus-tls.sh.j2")
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("gdc_nexus_domain", content)
        self.assertIn("gdc_nexus_alias", content)
        self.assertNotIn("gdc_nexus_demo_domain", content)
        self.assertNotIn("gdc-labs.com", content)

    def test_local_dns_authoritative_internal_domains(self):
        """Verifies internal-gdc.conf.j2 resolves internal domains without public demo domain."""
        dns_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/local_dns/templates/internal-gdc.conf.j2")
        with open(dns_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("gdc_nexus_domain", content)
        self.assertNotIn("gdc_nexus_demo_domain", content)
        self.assertNotIn("demo.gdc-labs.com", content)

if __name__ == "__main__":
    unittest.main()
