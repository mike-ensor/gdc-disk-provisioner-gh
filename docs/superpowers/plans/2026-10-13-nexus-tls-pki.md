# Dual-Tier Nexus TLS & Enterprise Sub-CA PKI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automated host and cluster TLS termination for `nexus.internal.gdc.local`, incorporating an enterprise Sub-CA from Secret Manager, host Nginx reverse proxy on port 443, autonomous leaf certificate rotation, and cert-manager handover.

**Architecture:** During Stage 4/5, Ansible retrieves the corporate Sub-CA JSON payload from Google Cloud Secret Manager via hardware-attested mTLS with GDC Companion. The Root CA is injected into the system trust store, while `step-cli` mints a leaf TLS bundle offline for `nexus.internal.gdc.local`. A host Nginx proxy terminates TLS on port 443 (routing `/v2/` to Docker 5001 and `/` to Nexus 8081). A dedicated systemd timer (`refresh-nexus-tls.timer`) autonomously re-mints certificates within 30 days of expiry. Post-cluster turnup, the Sub-CA credentials are automatically seeded into Kubernetes as a `cert-manager` `ClusterIssuer` (type: CA) for in-cluster workloads.

**Tech Stack:** Python 3.12, Ansible, Jinja2, Nginx, Smallstep CLI (`step-cli`), OpenSSL, systemd, Kubernetes (`cert-manager`), Google Cloud Secret Manager (`gcloud`).

---

### File Structure Map

- **Schema & Authority:**
  - Modify: `/d/projects/google/gdc-companion/docs/machine-schema.json` (Canonical schema definition in upstream repo)
  - Modify: `docs/machine-schema.json` (Mirrored schema definition in provisioner repo)
  - Modify: `test/fixtures/valid-gdc-fact-manual.json` (Fixture with sample Sub-CA config)
  - Test: `test/test_manual_facts_schema.py` (Validates schema parity and sub_ca_secret validation)
- **Offline ISO Dependency Caching:**
  - Modify: `src/build/packages_config.yaml` (Add `nginx` to `platform_required`)
- **Global Configuration:**
  - Modify: `src/ansible/vars/all.yml` & `src/ansible/vars/all.yml.j2` (Add default PKI and proxy parameters)
- **Host PKI Ingestion & Minting (`machine_orchestration` & `service_hubs`):**
  - Create: `src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml` (GSM retrieval with location fallback and trust store update)
  - Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml` (Include `pki_ingest.yml`)
  - Create: `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.sh.j2` (Autonomous leaf minting script)
  - Create: `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.service.j2` (Systemd oneshot service)
  - Create: `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.timer.j2` (Systemd weekly timer)
  - Create: `src/ansible/roles/service_hubs/templates/nexus-tls.conf.j2` (Nginx port 443 reverse proxy configuration)
  - Modify: `src/ansible/roles/service_hubs/tasks/main.yml` (Deploy Nginx config, launch timer, and trigger initial mint)
- **Client Configuration & Endpoint Redirection:**
  - Modify: `src/ansible/roles/host_foundations/tasks/main.yml` (Update `gdc-nexus.sources` to HTTPS)
  - Modify: `src/build/templates/user-data.j2` (Update cloud-init sources to HTTPS)
- **Kubernetes Cluster Handover (`post_cluster`):**
  - Create: `src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml` (Seed Sub-CA Secret and apply `ClusterIssuer`)
  - Modify: `src/ansible/roles/post_cluster/tasks/main.yml` (Include `cert_manager_pki.yml`)
- **Automated Test Suite:**
  - Create: `test/test_nexus_tls_pki.py` (Full unit test suite verifying schema, templates, timer, and proxy configurations)

---

### Task 1: Canonical Machine Schema Extension (`sub_ca_secret`)

**Files:**
- Modify: `/d/projects/google/gdc-companion/docs/machine-schema.json`
- Modify: `docs/machine-schema.json`
- Modify: `test/fixtures/valid-gdc-fact-manual.json`
- Test: `test/test_manual_facts_schema.py`

- [ ] **Step 1: Write the failing test for `sub_ca_secret` schema validation**

Add test case in `test/test_manual_facts_schema.py`:
```python
    def test_sub_ca_secret_schema_validation(self):
        """Verifies sub_ca_secret validates against machine-schema.json."""
        valid_cluster = {
            "cluster_name": "gdc-test-01",
            "sub_ca_secret": {
                "gsm-name": "gdc-pki-sub-ca",
                "gsm-location": "us-central1"
            }
        }
        # Extract cluster subschema
        cluster_schema = self.schema["properties"]["cluster"]
        jsonschema.validate(instance=valid_cluster, schema=cluster_schema)

        # Assert missing gsm-name fails
        invalid_cluster = {
            "cluster_name": "gdc-test-01",
            "sub_ca_secret": {
                "gsm-location": "us-central1"
            }
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_cluster, schema=cluster_schema)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_manual_facts_schema.py`  
Expected: FAIL with `jsonschema.exceptions.ValidationError` (sub_ca_secret not allowed or unrecognized).

- [ ] **Step 3: Update upstream canonical schema and mirror locally**

Update `/d/projects/google/gdc-companion/docs/machine-schema.json` under `.properties.cluster.properties`:
```json
        "sub_ca_secret": {
          "type": "object",
          "description": "Enterprise Intermediate Sub-CA credentials stored in Google Cloud Secret Manager",
          "required": ["gsm-name"],
          "properties": {
            "gsm-name": {
              "type": "string",
              "description": "Identifier of the Secret Manager secret holding the Sub-CA JSON payload"
            },
            "gsm-location": {
              "type": "string",
              "default": "global",
              "description": "Secret Manager replication location (e.g., global, us-central1)"
            }
          }
        },
```
Copy upstream to `docs/machine-schema.json` (or execute `./test/bin/sync-schemas.sh`).
Add `sub_ca_secret` to `test/fixtures/valid-gdc-fact-manual.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_manual_facts_schema.py`  
Expected: PASS (all 5 tests pass including `test_no_divergence_from_upstream_companion`).

- [ ] **Step 5: Commit**

```bash
git add docs/machine-schema.json test/test_manual_facts_schema.py test/fixtures/valid-gdc-fact-manual.json
git commit -m "feat(schema): add sub_ca_secret definition to machine schema"
```

---

### Task 2: Package Pre-Seeding Configuration (`nginx`)

**Files:**
- Modify: `src/build/packages_config.yaml:26-35`
- Create: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Write failing test in `test/test_nexus_tls_pki.py`**

```python
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

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: FAIL with `AssertionError: Missing 'nginx' in platform_required packages`

- [ ] **Step 3: Add `nginx` to `src/build/packages_config.yaml`**

Under `packages_to_include.platform_required`:
```yaml
    - "nginx"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/build/packages_config.yaml test/test_nexus_tls_pki.py
git commit -m "feat(build): add nginx to offline platform_required package manifest"
```

---

### Task 3: Global Ansible Variables & Configuration

**Files:**
- Modify: `src/ansible/vars/all.yml`
- Modify: `src/ansible/vars/all.yml.j2`
- Test: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Write failing test for PKI variables**

Add test to `test/test_nexus_tls_pki.py`:
```python
    def test_ansible_vars_contain_pki_parameters(self):
        """Verifies all.yml defines default PKI paths, domains, and renewal thresholds."""
        vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars/all.yml")
        with open(vars_path, "r", encoding="utf-8") as f:
            vars_data = yaml.safe_load(f)

        self.assertEqual(vars_data.get("gdc_nexus_tls_enabled"), True)
        self.assertEqual(vars_data.get("gdc_nexus_https_port"), 443)
        self.assertEqual(vars_data.get("gdc_sub_ca_dir"), "/etc/ssl/sub-ca")
        self.assertEqual(vars_data.get("gdc_nexus_cert_path"), "/etc/ssl/certs/nexus.bundle.crt")
        self.assertEqual(vars_data.get("gdc_nexus_key_path"), "/etc/ssl/private/nexus.key")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: FAIL with `AssertionError: None != True`

- [ ] **Step 3: Add PKI variables to `src/ansible/vars/all.yml` and `all.yml.j2`**

Append to `src/ansible/vars/all.yml` and `src/ansible/vars/all.yml.j2`:
```yaml
# ==============================================================================
# GDC Nexus TLS & Enterprise Sub-CA PKI Parameters
# ==============================================================================
gdc_nexus_tls_enabled: true
gdc_nexus_https_port: 443
gdc_sub_ca_dir: "/etc/ssl/sub-ca"
gdc_sub_ca_cert_path: "/etc/ssl/sub-ca/sub-ca.crt"
gdc_sub_ca_key_path: "/etc/ssl/sub-ca/sub-ca.key"
gdc_enterprise_root_cert_path: "/usr/local/share/ca-certificates/gdc-enterprise-root.crt"
gdc_nexus_cert_path: "/etc/ssl/certs/nexus.bundle.crt"
gdc_nexus_key_path: "/etc/ssl/private/nexus.key"
gdc_nexus_tls_renew_threshold_seconds: 2592000 # 30 days
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/vars/all.yml src/ansible/vars/all.yml.j2 test/test_nexus_tls_pki.py
git commit -m "feat(ansible): define default nexus tls and pki parameters in vars"
```

---

### Task 4: Sub-CA Secret Ingestion Task (`pki_ingest.yml`)

**Files:**
- Create: `src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml`
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`
- Test: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Write test verifying `pki_ingest.yml` structure and fallback handling**

Add test to `test/test_nexus_tls_pki.py`:
```python
    def test_pki_ingest_tasks_structure(self):
        """Verifies pki_ingest.yml parses cleanly and includes gcloud location fallback logic."""
        pki_task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml")
        self.assertTrue(os.path.exists(pki_task_path), "pki_ingest.yml does not exist")
        with open(pki_task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        task_names = [t.get("name", "") for t in tasks]
        self.assertTrue(any("Access Sub-CA Secret payload via gcloud" in name for name in task_names))
        self.assertTrue(any("Fallback: Access Sub-CA Secret payload as global resource" in name for name in task_names))
        self.assertTrue(any("Write Corporate Root CA" in name for name in task_names))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: FAIL with `AssertionError: pki_ingest.yml does not exist`

- [ ] **Step 3: Implement `pki_ingest.yml` and include in `machine_orchestration`**

Create `src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-PKI | Ingest Enterprise Sub-CA from Secret Manager"
  when:
    - cluster_config is defined
    - cluster_config.sub_ca_secret is defined
    - cluster_config.sub_ca_secret['gsm-name'] is defined
    - cluster_config.sub_ca_secret['gsm-name'] | trim | length > 0
  block:
    - name: "GDC-PKI | Access Sub-CA Secret payload via gcloud"
      ansible.builtin.command: >-
        gcloud secrets versions access latest
        --secret={{ cluster_config.sub_ca_secret['gsm-name'] }}
        --project={{ gcp_project_id }}
        {% if cluster_config.sub_ca_secret['gsm-location'] is defined and cluster_config.sub_ca_secret['gsm-location'] | trim | length > 0 and cluster_config.sub_ca_secret['gsm-location'] != 'global' %}
        --location={{ cluster_config.sub_ca_secret['gsm-location'] }}
        {% endif %}
      register: gsm_sub_ca_res
      changed_when: false
      failed_when: false
      no_log: true

    - name: "GDC-PKI | Fallback: Access Sub-CA Secret payload as global resource"
      ansible.builtin.command: >-
        gcloud secrets versions access latest
        --secret={{ cluster_config.sub_ca_secret['gsm-name'] }}
        --project={{ gcp_project_id }}
      register: gsm_sub_ca_res_fallback
      when:
        - gsm_sub_ca_res.rc != 0
        - cluster_config.sub_ca_secret['gsm-location'] is defined
        - cluster_config.sub_ca_secret['gsm-location'] != 'global'
      changed_when: false
      failed_when: false
      no_log: true

    - name: "GDC-PKI | Adopt fallback Sub-CA payload if successful"
      ansible.builtin.set_fact:
        gsm_sub_ca_res: "{{ gsm_sub_ca_res_fallback }}"
      when:
        - gsm_sub_ca_res.rc != 0
        - gsm_sub_ca_res_fallback is defined
        - gsm_sub_ca_res_fallback.rc == 0

    - name: "GDC-PKI | Write Sub-CA credentials and register Root CA trust"
      when: gsm_sub_ca_res.rc == 0
      block:
        - name: "GDC-PKI | Ensure Sub-CA and private key directories exist"
          ansible.builtin.file:
            path: "{{ item }}"
            state: directory
            owner: root
            group: root
            mode: '0700'
          loop:
            - "{{ gdc_sub_ca_dir }}"
            - "/etc/ssl/private"

        - name: "GDC-PKI | Write Corporate Root CA to system trust store"
          ansible.builtin.copy:
            dest: "{{ gdc_enterprise_root_cert_path }}"
            content: "{{ (gsm_sub_ca_res.stdout | from_json)['root.crt'] }}"
            owner: root
            group: root
            mode: '0644'
          register: root_ca_write_res

        - name: "GDC-PKI | Update OS System CA Certificates"
          ansible.builtin.command: update-ca-certificates
          when: root_ca_write_res.changed

        - name: "GDC-PKI | Write Sub-CA Certificate"
          ansible.builtin.copy:
            dest: "{{ gdc_sub_ca_cert_path }}"
            content: "{{ (gsm_sub_ca_res.stdout | from_json)['ca.crt'] }}"
            owner: root
            group: root
            mode: '0644'

        - name: "GDC-PKI | Write Sub-CA Private Key"
          ansible.builtin.copy:
            dest: "{{ gdc_sub_ca_key_path }}"
            content: "{{ (gsm_sub_ca_res.stdout | from_json)['ca.key'] }}"
            owner: root
            group: root
            mode: '0400'
            no_log: true
```
Include `pki_ingest.yml` in `src/ansible/roles/machine_orchestration/tasks/main.yml`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml src/ansible/roles/machine_orchestration/tasks/main.yml test/test_nexus_tls_pki.py
git commit -m "feat(pki): implement sub-ca secret ingestion with location fallback"
```

---

### Task 5: Autonomous Rotation Script & Systemd Timer

**Files:**
- Create: `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.sh.j2`
- Create: `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.service.j2`
- Create: `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.timer.j2`
- Test: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Write test verifying template rendering of rotation units**

Add test to `test/test_nexus_tls_pki.py`:
```python
    def test_rotation_script_and_systemd_templates(self):
        """Verifies refresh-nexus-tls script, service, and timer templates render valid syntax."""
        env = Environment()
        script_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/refresh-nexus-tls.sh.j2")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: FAIL (file not found)

- [ ] **Step 3: Implement templates**

1. Create `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.sh.j2`:
```bash
#!/usr/bin/env bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
set -euo pipefail

CERT_PATH="{{ gdc_nexus_cert_path }}"
KEY_PATH="{{ gdc_nexus_key_path }}"
SUB_CA_CERT="{{ gdc_sub_ca_cert_path }}"
SUB_CA_KEY="{{ gdc_sub_ca_key_path }}"
RENEW_THRESHOLD_SECONDS={{ gdc_nexus_tls_renew_threshold_seconds | default(2592000) }}

needs_renewal=false

if [[ ! -f "${CERT_PATH}" ]] || [[ ! -f "${KEY_PATH}" ]]; then
    echo "[*] Nexus TLS certificates not found. Minting initial certificate..."
    needs_renewal=true
elif ! openssl x509 -checkend "${RENEW_THRESHOLD_SECONDS}" -noout -in "${CERT_PATH}" &>/dev/null; then
    echo "[*] Nexus TLS certificate is expiring within ${RENEW_THRESHOLD_SECONDS} seconds. Initiating renewal..."
    needs_renewal=true
else
    echo "[+] Nexus TLS certificate is valid. No action required."
    exit 0
fi

if [[ "${needs_renewal}" == "true" ]]; then
    if [[ ! -f "${SUB_CA_CERT}" ]] || [[ ! -f "${SUB_CA_KEY}" ]]; then
        echo "[!] Error: Sub-CA credentials missing at ${SUB_CA_CERT} or ${SUB_CA_KEY}." >&2
        exit 1
    fi

    step certificate create {{ gdc_nexus_domain }} \
        "${CERT_PATH}" \
        "${KEY_PATH}" \
        --ca="${SUB_CA_CERT}" \
        --ca-key="${SUB_CA_KEY}" \
        --san="{{ gdc_nexus_domain }}" \
        --san="{{ gdc_nexus_alias }}" \
        --bundle \
        --not-after=8760h \
        --no-password --insecure --force

    chmod 0644 "${CERT_PATH}"
    chmod 0600 "${KEY_PATH}"
    chown root:root "${CERT_PATH}" "${KEY_PATH}"

    if command -v nginx &>/dev/null && nginx -t &>/dev/null; then
        systemctl reload nginx
        echo "[+] Successfully renewed Nexus TLS certificate and reloaded Nginx."
    fi
fi
```

2. Create `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.service.j2`:
```ini
[Unit]
Description=Autonomous Nexus TLS Certificate Renewal
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/refresh-nexus-tls.sh
User=root
Group=root
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/etc/ssl/certs /etc/ssl/private
ReadOnlyPaths=/etc/ssl/sub-ca
```

3. Create `src/ansible/roles/service_hubs/templates/refresh-nexus-tls.timer.j2`:
```ini
[Unit]
Description=Weekly Check for Nexus TLS Certificate Expiration
After=time-sync.target

[Timer]
OnCalendar=Sun *-*-* 03:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/service_hubs/templates/refresh-nexus-tls.* test/test_nexus_tls_pki.py
git commit -m "feat(pki): add refresh-nexus-tls script, service, and timer templates"
```

---

### Task 6: Nginx Reverse Proxy Configuration & Role Deployment

**Files:**
- Create: `src/ansible/roles/service_hubs/templates/nexus-tls.conf.j2`
- Modify: `src/ansible/roles/service_hubs/tasks/main.yml`
- Test: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Write test verifying Nginx proxy template rules and headers**

Add test to `test/test_nexus_tls_pki.py`:
```python
    def test_nginx_proxy_configuration_template(self):
        """Verifies Nginx configuration renders TLS port 443, /v2/ routing, and DoS limits."""
        env = Environment()
        conf_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/service_hubs/templates/nexus-tls.conf.j2")
        with open(conf_path, "r", encoding="utf-8") as f:
            conf_tmpl = env.from_string(f.read())
        rendered_conf = conf_tmpl.render(
            gdc_nexus_https_port=443,
            gdc_nexus_domain="nexus.internal.gdc.local",
            gdc_nexus_alias="nexus.gdc.local",
            gdc_nexus_cert_path="/etc/ssl/certs/nexus.bundle.crt",
            gdc_nexus_key_path="/etc/ssl/private/nexus.key"
        )
        self.assertIn("listen 443 ssl default_server;", rendered_conf)
        self.assertIn("proxy_pass http://127.0.0.1:5001;", rendered_conf)
        self.assertIn("proxy_pass http://127.0.0.1:8081;", rendered_conf)
        self.assertIn("proxy_request_buffering off;", rendered_conf)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: FAIL (file not found)

- [ ] **Step 3: Create `nexus-tls.conf.j2` and wire deployment into `service_hubs` tasks**

1. Create `src/ansible/roles/service_hubs/templates/nexus-tls.conf.j2` with standard port 443, `/v2/` ➔ 5001, `/` ➔ 8081, TLS 1.2/1.3, security headers, and path-segmented upload body caps.
2. In `src/ansible/roles/service_hubs/tasks/main.yml`:
   * Deploy `/usr/local/bin/refresh-nexus-tls.sh` (mode `0755`).
   * Trigger `/usr/local/bin/refresh-nexus-tls.sh` to mint initial certificates if Sub-CA is present.
   * Deploy `refresh-nexus-tls.service` and `refresh-nexus-tls.timer` to `/etc/systemd/system/`.
   * Enable and start `refresh-nexus-tls.timer`.
   * Deploy `/etc/nginx/sites-available/nexus-tls.conf` and symlink to `sites-enabled`.
   * Remove default site `/etc/nginx/sites-enabled/default` if present.
   * Enable and restart `nginx.service`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/service_hubs/templates/nexus-tls.conf.j2 src/ansible/roles/service_hubs/tasks/main.yml test/test_nexus_tls_pki.py
git commit -m "feat(proxy): deploy nginx reverse proxy and refresh timer in service_hubs"
```

---

### Task 7: Client Redirections to HTTPS

**Files:**
- Modify: `src/ansible/roles/host_foundations/tasks/main.yml`
- Modify: `src/build/templates/user-data.j2`
- Test: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Write test verifying APT sources point to HTTPS `nexus.internal.gdc.local`**

Add test to `test/test_nexus_tls_pki.py`:
```python
    def test_apt_sources_redirect_to_https(self):
        """Verifies host_foundations configures APT sources using https://nexus.internal.gdc.local."""
        task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/host_foundations/tasks/main.yml")
        with open(task_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("https://{{ gdc_nexus_domain }}/repository/", content)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: FAIL

- [ ] **Step 3: Update APT sources tasks and cloud-init template**

Update `src/ansible/roles/host_foundations/tasks/main.yml` to set `URIs: https://{{ gdc_nexus_domain }}/repository/...`.
Update `src/build/templates/user-data.j2` to use `https://nexus.internal.gdc.local/repository/...`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/host_foundations/tasks/main.yml src/build/templates/user-data.j2 test/test_nexus_tls_pki.py
git commit -m "feat(apt): update apt repositories to point to https nexus endpoint"
```

---

### Task 6: In-Cluster `cert-manager` Handover (`cert_manager_pki.yml`)

**Files:**
- Create: `src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml`
- Modify: `src/ansible/roles/post_cluster/tasks/main.yml`
- Test: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Write test verifying `cert_manager_pki.yml` task definitions**

Add test to `test/test_nexus_tls_pki.py`:
```python
    def test_cert_manager_pki_tasks(self):
        """Verifies cert_manager_pki.yml defines Secret and ClusterIssuer resources."""
        task_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml")
        self.assertTrue(os.path.exists(task_path), "cert_manager_pki.yml does not exist")
        with open(task_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)
        task_names = [t.get("name", "") for t in tasks]
        self.assertTrue(any("Seed Sub-CA TLS secret into cert-manager" in name for name in task_names))
        self.assertTrue(any("Deploy gdc-ca-issuer ClusterIssuer" in name for name in task_names))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: FAIL (file not found)

- [ ] **Step 3: Implement `cert_manager_pki.yml`**

Create `src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml`:
```yaml
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
---
- name: "GDC-K8S-PKI | Ingest and Handover Sub-CA to In-Cluster cert-manager"
  when:
    - gdc_nexus_tls_enabled | default(true) | bool
  block:
    - name: "GDC-K8S-PKI | Check if Sub-CA credentials exist on host"
      ansible.builtin.stat:
        path: "{{ gdc_sub_ca_key_path }}"
      register: sub_ca_key_stat

    - name: "GDC-K8S-PKI | Seed Sub-CA and configure ClusterIssuer"
      when: sub_ca_key_stat.stat.exists
      block:
        - name: "GDC-K8S-PKI | Ensure cert-manager namespace exists"
          kubernetes.core.k8s:
            api_version: v1
            kind: Namespace
            name: cert-manager
            state: present

        - name: "GDC-K8S-PKI | Seed Sub-CA TLS secret into cert-manager"
          kubernetes.core.k8s:
            state: present
            definition:
              apiVersion: v1
              kind: Secret
              metadata:
                name: gdc-sub-ca-keypair
                namespace: cert-manager
              type: kubernetes.io/tls
              data:
                tls.crt: "{{ (lookup('file', gdc_sub_ca_cert_path) + '\n' + lookup('file', gdc_enterprise_root_cert_path)) | b64encode }}"
                tls.key: "{{ lookup('file', gdc_sub_ca_key_path) | b64encode }}"

        - name: "GDC-K8S-PKI | Deploy gdc-ca-issuer ClusterIssuer"
          kubernetes.core.k8s:
            state: present
            definition:
              apiVersion: cert-manager.io/v1
              kind: ClusterIssuer
              metadata:
                name: gdc-ca-issuer
              spec:
                ca:
                  secretName: gdc-sub-ca-keypair
```
Include `cert_manager_pki.yml` in `src/ansible/roles/post_cluster/tasks/main.yml`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_nexus_tls_pki.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml src/ansible/roles/post_cluster/tasks/main.yml test/test_nexus_tls_pki.py
git commit -m "feat(k8s): add cert-manager secret seeding and clusterissuer handover"
```

---

### Task 9: Full Test Suite Execution & Integration Verification

**Files:**
- Modify: `test/test_nexus_tls_pki.py`

- [ ] **Step 1: Execute all unit tests**

Run: `python3 -m unittest discover test/`  
Expected: All test suites PASS (including `test_local_dns.py`, `test_manual_facts_schema.py`, and `test_nexus_tls_pki.py`).

- [ ] **Step 2: Commit any remaining test refinements**

```bash
git add test/test_nexus_tls_pki.py
git commit -m "test(pki): complete comprehensive test suite for dual-tier nexus tls"
```
