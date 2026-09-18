# Specification: Reset Provisioning State & Manual Facts Injection

## 1. Overview
During bare-metal provisioning and local edge testing, operators frequently need to test or recover Stage 5 (`CLUSTER_READY`) without relying on an active, network-reachable GDC Companion service. 

Currently, `gdc-provision.service` checks persistent JSON tracker files in `/var/gdc-install/state/` to skip previously completed stages. Furthermore, the `machine_orchestration` role in Stage 5 attempts to query `GET /v1/machine-info/{mac}` from GDC Companion and only falls back to `/etc/gdc/machine-info-mock.json` or `/etc/gdc/fallback-config.json`.

This specification formalizes:
1. **Manual Fact Injection:** Upstream ingestion of a manual fact file placed directly at `/var/gdc-install/state/gdc-fact-manual.json`.
2. **State Reset:** Deletion of `/var/gdc-install/state/cluster-ready.json` to allow `gdc-provision.service` to re-execute Stage 5.
3. **Automated Workstation Script:** `bin/node-ops/inject-manual-facts.sh` to execute the full upload, state reset, service restart, and journal streaming flow in a single command.
4. **Runbook Documentation:** Clear instructions and schema definitions in `docs/on-device-ansible.md`.

---

## 2. Architecture & Components

### 2.1 Fact Ingestion Precedence in Ansible (`machine_orchestration`)
In `src/ansible/roles/machine_orchestration/tasks/main.yml`, the machine configuration lookup will be updated to respect the following order of precedence:

1. **Manual State Override:** `/var/gdc-install/state/gdc-fact-manual.json`
   - If present, slurp and parse into `machine_config` with `'is_fallback': false`. Bypasses GDC Companion API.
2. **Legacy Mock Override:** `/etc/gdc/machine-info-mock.json`
   - Preserved for backwards compatibility with existing test rigs.
3. **GDC Companion API:** `GET /v1/machine-info/{{ node_mac }}`
   - Executed only if neither manual fact file nor legacy mock file exists.
4. **Emergency Static Fallback:** `/etc/gdc/fallback-config.json`
   - Used if the Companion API call fails or returns an empty/error payload.

Once `machine_config` is established, the role will naturally validate, configure `/etc/hosts` and Netplan, and persist the config downstream to `/etc/ansible/facts.d/gdc.fact`.

### 2.2 Expected Schema & Sourcing from GDC Companion
The manual fact file represents the machine's desired network, identity, and peer topologies.

#### Exporting from GDC Companion
Operators can obtain a valid fact file directly from `gdc-companion`:
* **Via Web UI:** Navigate to the Machine Inventory view, select the target machine, and click **"Share / Download JSON"** (or use the download link) to save the exact JSON configuration.
* **Via API / CLI:**
  ```bash
  curl -s -H "Authorization: Bearer <API_KEY>" \
    "https://<companion-host>/v1/machine-info/<MAC_ADDRESS>" > gdc-fact-manual.json
  ```

#### Schema Compliance
The generated or authored `gdc-fact-manual.json` must strictly conform to `/d/projects/google/gdc-companion/docs/machine-schema.json`. It requires:
- `hostname` (string)
- `bmctl_version` (string)
- `network` (object with `management_network` and `cluster_network`)
- `gcp_info` (object with `project_id`, `region`, and `primary_gsa`)
- `cluster` (object with `cluster_name`, `primary_root_repo`, `primary_root_repo_auth_secret`, `networking`, `fleet_cluster_labels`)
- `peers` (array of peer objects with `hostname` and `ipv4`)

Example schema-compliant payload:
```json
{
  "hostname": "gdc-node-01",
  "bmctl_version": "1.29.0",
  "network": {
    "management_network": {
      "dhcp_v4": true,
      "gateway": "192.168.4.1",
      "dns_servers": ["192.168.4.1", "8.8.8.8"]
    },
    "cluster_network": {
      "vlan_id": 109,
      "dhcp_v4": false,
      "ip_cidr": "192.168.109.10/24",
      "gateway": "192.168.109.1",
      "dns_servers": ["192.168.109.1"]
    }
  },
  "gcp_info": {
    "project_id": "gdc-edge-lab",
    "region": "us-east1",
    "primary_gsa": "gdc-node-sa@gdc-edge-lab.iam.gserviceaccount.com"
  },
  "cluster": {
    "cluster_name": "edge-cluster-01",
    "primary_root_repo": "git@github.com:example/repo.git",
    "primary_root_repo_auth_secret": "repo-secret",
    "networking": {
      "cluster_vip": "192.168.109.100",
      "cluster_ingress": "192.168.109.101",
      "cluster_lb_range": "192.168.109.100-192.168.109.110"
    },
    "fleet_cluster_labels": ["env=lab", "location=edge"]
  },
  "peers": [
    {
      "hostname": "gdc-node-02",
      "ipv4": "192.168.109.11"
    }
  ]
}
```

### 2.3 Automated Script: `bin/node-ops/inject-manual-facts.sh`
A workstation CLI script written in Bash:
* **Arguments:**
  - `--node <IP>` (Required): Target GDC node IP address.
  - `--facts <FILE>` (Required): Path to the local JSON fact file to upload.
  - `--user <USER>` (Optional, default: `gdc-admin`, fallback: `temporary-installer`).
  - `--key <KEY>` (Optional): Path to SSH private key.
* **Execution Workflow:**
  1. Validates local facts file exists and is valid JSON (`jq . <file>`).
  2. Copies the file to remote `/tmp/gdc-fact-manual.json` via `scp`.
  3. Executes remote commands via `ssh`:
     ```bash
     sudo mkdir -p /var/gdc-install/state
     sudo mv /tmp/gdc-fact-manual.json /var/gdc-install/state/gdc-fact-manual.json
     sudo chown root:root /var/gdc-install/state/gdc-fact-manual.json
     sudo chmod 0644 /var/gdc-install/state/gdc-fact-manual.json
     sudo rm -f /var/gdc-install/state/cluster-ready.json
     sudo systemctl restart gdc-provision.service
     ```
  4. Follows journal logs:
     ```bash
     sudo journalctl -u gdc-provision.service -f
     ```

### 2.4 Documentation: `docs/on-device-ansible.md`
Update Section 2 ("On-Device Execution & Stage Management"):
* Add Section 2.4: "Bypassing GDC Companion with Manual Facts (`gdc-fact-manual.json`)".
* Document the file location, payload schema, manual terminal instructions, and workstation script usage.

---

## 3. Verification & Testing Plan (Test-Driven Development)

All functionality will be implemented following strict **Test-Driven Development (TDD)**:
1. **Schema Validation Test (Python):**
   - Create a test suite validating that example fixture `gdc-fact-manual.json` strictly adheres to `/d/projects/google/gdc-companion/docs/machine-schema.json` using `jsonschema`.
2. **Workstation Helper Script Unit Tests (Bash/BATS or Python):**
   - Write tests verifying argument parsing, `--help`, missing argument errors, and pre-validation failure when facts JSON is invalid or missing.
3. **Ansible Task Precedence & Slurp Tests:**
   - Add unit test in `test/test_manual_facts.py` or equivalent test suite verifying the template and task logic correctly prioritizes `/var/gdc-install/state/gdc-fact-manual.json`.
4. **Syntax & Linting:**
   - Run `ansible-lint` on `src/ansible/roles/machine_orchestration/tasks/main.yml`.
   - Run `shellcheck` or `bash -n` on `bin/node-ops/inject-manual-facts.sh`.
