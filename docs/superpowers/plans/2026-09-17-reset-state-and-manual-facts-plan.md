# Reset Provisioning State & Manual Facts Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement upstream manual fact injection (`/var/gdc-install/state/gdc-fact-manual.json`) to bypass GDC Companion in Stage 5, provide an automated workstation injection script with schema verification, and document the complete runbook in `docs/on-device-ansible.md`.

**Architecture:** Update Ansible's `machine_orchestration` role to slurp `/var/gdc-install/state/gdc-fact-manual.json` as the highest-precedence configuration source. Implement `bin/node-ops/inject-manual-facts.sh` to validate JSON schema against `/d/projects/google/gdc-companion/docs/machine-schema.json`, transfer to the remote node, wipe `/var/gdc-install/state/cluster-ready.json`, and restart `gdc-provision.service`. Document export procedures and workflows in `docs/on-device-ansible.md`.

**Tech Stack:** Ansible (YAML/Jinja2), Bash, Python 3 (`unittest`, `jsonschema`, `yaml`).

---

### Task 1: Schema Validation Fixtures & Unit Tests

**Files:**
- Create: `test/fixtures/valid-gdc-fact-manual.json`
- Create: `test/fixtures/invalid-gdc-fact-manual.json`
- Test: `test/test_manual_facts_schema.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_manual_facts_schema.py`:
```python
import json
import os
import unittest
import jsonschema

SCHEMA_PATH = "/d/projects/google/gdc-companion/docs/machine-schema.json"
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

class TestManualFactsSchema(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(SCHEMA_PATH), f"Schema not found at {SCHEMA_PATH}")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_valid_manual_fact_fixture(self):
        valid_path = os.path.join(FIXTURES_DIR, "valid-gdc-fact-manual.json")
        self.assertTrue(os.path.exists(valid_path), f"Fixture missing: {valid_path}")
        with open(valid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Validate should not raise ValidationError
        jsonschema.validate(instance=data, schema=self.schema)

    def test_invalid_manual_fact_fixture(self):
        invalid_path = os.path.join(FIXTURES_DIR, "invalid-gdc-fact-manual.json")
        self.assertTrue(os.path.exists(invalid_path), f"Fixture missing: {invalid_path}")
        with open(invalid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=data, schema=self.schema)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_manual_facts_schema.py`
Expected: FAIL (fixture files do not exist yet)

- [ ] **Step 3: Create the fixture files**

Create `test/fixtures/valid-gdc-fact-manual.json`:
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

Create `test/fixtures/invalid-gdc-fact-manual.json`:
```json
{
  "hostname": "gdc-incomplete-node"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_manual_facts_schema.py`
Expected: PASS (2 tests passed)

- [ ] **Step 5: Commit**

```bash
git add test/fixtures/ test/test_manual_facts_schema.py
git commit -m "test: add schema validation tests for manual facts JSON"
```

---

### Task 2: Update Ansible Tasks for `gdc-fact-manual.json` Ingestion

**Files:**
- Test: `test/test_manual_facts_ansible.py`
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml:23-75`

- [ ] **Step 1: Write the failing test**

Create `test/test_manual_facts_ansible.py`:
```python
import os
import unittest
import yaml

TASKS_PATH = os.path.join(
    os.path.dirname(__file__),
    "../src/ansible/roles/machine_orchestration/tasks/main.yml"
)

class TestManualFactsAnsible(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(TASKS_PATH))
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            self.tasks = yaml.safe_load(f)

    def test_manual_fact_tasks_present(self):
        task_names = [t.get("name", "") for t in self.tasks if isinstance(t, dict)]
        self.assertTrue(
            any("gdc-fact-manual.json" in name for name in task_names),
            "Expected a task checking for /var/gdc-install/state/gdc-fact-manual.json"
        )

    def test_manual_fact_takes_precedence(self):
        # Find index of manual fact task vs mock vs companion fetch
        manual_idx = None
        mock_idx = None
        companion_idx = None

        for idx, task in enumerate(self.tasks):
            if not isinstance(task, dict):
                continue
            name = task.get("name", "")
            if "gdc-fact-manual.json" in name:
                manual_idx = idx
            elif "machine-info-mock.json" in name and "exists" in name:
                mock_idx = idx
            elif "Fetch machine-info configuration from GDC Companion" in name:
                companion_idx = idx

        self.assertIsNotNone(manual_idx, "manual_fact task not found")
        self.assertIsNotNone(mock_idx, "mock task not found")
        self.assertIsNotNone(companion_idx, "companion task not found")
        self.assertLess(manual_idx, mock_idx, "manual_fact must precede legacy mock")
        self.assertLess(mock_idx, companion_idx, "mock must precede companion fetch")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_manual_facts_ansible.py`
Expected: FAIL (no task with `gdc-fact-manual.json` found)

- [ ] **Step 3: Update `src/ansible/roles/machine_orchestration/tasks/main.yml`**

Update `src/ansible/roles/machine_orchestration/tasks/main.yml` lines 27–58 to:
```yaml
- name: "GDC-ORCH | Check if /var/gdc-install/state/gdc-fact-manual.json exists"
  ansible.builtin.stat:
    path: /var/gdc-install/state/gdc-fact-manual.json
  register: manual_fact_stat

- name: "GDC-ORCH | Read /var/gdc-install/state/gdc-fact-manual.json if present"
  ansible.builtin.slurp:
    src: /var/gdc-install/state/gdc-fact-manual.json
  register: slurped_manual_fact
  when: manual_fact_stat.stat.exists

- name: "GDC-ORCH | Check if local machine-info-mock.json exists"
  ansible.builtin.stat:
    path: /etc/gdc/machine-info-mock.json
  register: mock_file_stat
  when: not manual_fact_stat.stat.exists

- name: "GDC-ORCH | Fetch machine-info configuration from GDC Companion"
  ansible.builtin.uri:
    url: "{{ gdc_companion_base_url }}v1/machine-info/{{ node_mac }}"
    method: GET
    headers:
      Authorization: "Bearer {{ gdc_companion_api_key }}"
    status_code: 200
    validate_certs: false
  register: api_response
  ignore_errors: true
  when: not manual_fact_stat.stat.exists and not (mock_file_stat.stat.exists | default(false))

- name: "GDC-ORCH | Read local machine-info-mock.json if present"
  ansible.builtin.slurp:
    src: /etc/gdc/machine-info-mock.json
  register: slurped_mock
  when: not manual_fact_stat.stat.exists and (mock_file_stat.stat.exists | default(false))

- name: "GDC-ORCH | Parse and register configuration facts"
  ansible.builtin.set_fact:
    machine_config: >-
      {{
        (slurped_manual_fact.content | b64decode | from_json | combine({'is_fallback': false}))
        if (manual_fact_stat.stat.exists | default(false))
        else (
          (slurped_mock.content | b64decode | from_json | combine({'is_fallback': false}))
          if (mock_file_stat.stat.exists | default(false))
          else (api_response.json.variables | default(api_response.json | default({})) | combine({'is_fallback': false}))
        )
      }}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_manual_facts_ansible.py`
Expected: PASS (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/ansible/roles/machine_orchestration/tasks/main.yml test/test_manual_facts_ansible.py
git commit -m "feat: support manual fact override in machine_orchestration"
```

---

### Task 3: Implement `bin/node-ops/inject-manual-facts.sh` Workstation Script

**Files:**
- Test: `test/test_inject_manual_facts_cli.py`
- Create: `bin/node-ops/inject-manual-facts.sh`

- [ ] **Step 1: Write the failing test**

Create `test/test_inject_manual_facts_cli.py`:
```python
import os
import subprocess
import unittest

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../bin/node-ops/inject-manual-facts.sh"
)

class TestInjectManualFactsCLI(unittest.TestCase):
    def test_script_exists_and_executable(self):
        self.assertTrue(os.path.exists(SCRIPT_PATH), f"Script not found at {SCRIPT_PATH}")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), "Script is not executable")

    def test_help_flag(self):
        result = subprocess.run([SCRIPT_PATH, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--node", result.stdout)
        self.assertIn("--facts", result.stdout)

    def test_missing_arguments_fails(self):
        result = subprocess.run([SCRIPT_PATH], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error", result.stderr + result.stdout)

    def test_invalid_facts_json_fails(self):
        invalid_path = os.path.join(os.path.dirname(__file__), "fixtures/invalid-gdc-fact-manual.json")
        result = subprocess.run(
            [SCRIPT_PATH, "--node", "192.168.4.10", "--facts", invalid_path, "--dry-run"],
            capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema", (result.stderr + result.stdout).lower())

    def test_valid_facts_dry_run_succeeds(self):
        valid_path = os.path.join(os.path.dirname(__file__), "fixtures/valid-gdc-fact-manual.json")
        result = subprocess.run(
            [SCRIPT_PATH, "--node", "192.168.4.10", "--facts", valid_path, "--dry-run"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("cluster-ready.json", result.stdout)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_inject_manual_facts_cli.py`
Expected: FAIL (script does not exist yet)

- [ ] **Step 3: Implement `bin/node-ops/inject-manual-facts.sh`**

Create `bin/node-ops/inject-manual-facts.sh`:
```bash
#!/usr/bin/env bash
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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SCHEMA_PATH="/d/projects/google/gdc-companion/docs/machine-schema.json"

NODE_IP=""
FACTS_FILE=""
SSH_USER="gdc-admin"
SSH_KEY=""
DRY_RUN=false

usage() {
    cat <<EOF
Usage: $(basename "$0") --node <NODE_IP> --facts <FACTS_JSON> [OPTIONS]

Injects a manual fact override file into a GDC target node, resets Stage 5
(Cluster Ready), and triggers gdc-provision.service.

Required Arguments:
  --node <IP>        Target node IP address
  --facts <FILE>     Path to local JSON file adhering to machine-schema.json

Optional Arguments:
  --user <USER>      SSH user (default: gdc-admin)
  --key <KEY_PATH>   Path to SSH private key
  --dry-run          Validate facts and display actions without running SSH
  -h, --help         Display this help message
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --node)
            NODE_IP="$2"
            shift 2
            ;;
        --facts)
            FACTS_FILE="$2"
            shift 2
            ;;
        --user)
            SSH_USER="$2"
            shift 2
            ;;
        --key)
            SSH_KEY="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        *)
            echo "Error: Unknown argument '$1'" >&2
            usage 1
            ;;
    esac
done

if [[ -z "${NODE_IP}" || -z "${FACTS_FILE}" ]]; then
    echo "Error: Missing required arguments --node and --facts" >&2
    usage 1
fi

if [[ ! -f "${FACTS_FILE}" ]]; then
    echo "Error: Facts file '${FACTS_FILE}' does not exist." >&2
    exit 1
fi

echo "[-] Validating '${FACTS_FILE}' syntax..."
if ! jq . "${FACTS_FILE}" >/dev/null 2>&1; then
    echo "Error: Facts file is not valid JSON." >&2
    exit 1
fi

# Schema validation if schema file exists and python3 jsonschema is available
if [[ -f "${SCHEMA_PATH}" ]]; then
    echo "[-] Validating facts file against '${SCHEMA_PATH}'..."
    if ! python3 -c "
import json, sys, jsonschema
with open('${SCHEMA_PATH}', 'r') as sf, open('${FACTS_FILE}', 'r') as df:
    schema = json.load(sf)
    data = json.load(df)
    jsonschema.validate(instance=data, schema=schema)
" 2>&1; then
        echo "Error: Facts file failed schema validation against ${SCHEMA_PATH}" >&2
        exit 1
    fi
    echo "  [x] Facts JSON conforms to machine-schema.json."
fi

SSH_OPTS=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
if [[ -n "${SSH_KEY}" ]]; then
    SSH_OPTS+=(-i "${SSH_KEY}")
fi

REMOTE_TMP="/tmp/gdc-fact-manual.json"
TARGET_FILE="/var/gdc-install/state/gdc-fact-manual.json"
TARGET_STATE="/var/gdc-install/state/cluster-ready.json"

if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[!] DRY RUN MODE: No remote commands will be executed."
    echo "Would execute:"
    echo "  1. scp ${FACTS_FILE} ${SSH_USER}@${NODE_IP}:${REMOTE_TMP}"
    echo "  2. ssh ${SSH_USER}@${NODE_IP} 'sudo mkdir -p /var/gdc-install/state && sudo mv ${REMOTE_TMP} ${TARGET_FILE} && sudo chown root:root ${TARGET_FILE} && sudo chmod 0644 ${TARGET_FILE}'"
    echo "  3. ssh ${SSH_USER}@${NODE_IP} 'sudo rm -f ${TARGET_STATE}'"
    echo "  4. ssh ${SSH_USER}@${NODE_IP} 'sudo systemctl restart gdc-provision.service'"
    echo "  5. ssh -t ${SSH_USER}@${NODE_IP} 'sudo journalctl -u gdc-provision.service -f'"
    exit 0
fi

echo "[-] Uploading facts file to ${NODE_IP}:${REMOTE_TMP}..."
scp "${SSH_OPTS[@]}" "${FACTS_FILE}" "${SSH_USER}@${NODE_IP}:${REMOTE_TMP}"

echo "[-] Staging manual fact file and resetting cluster-ready state..."
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${NODE_IP}" "
    sudo mkdir -p /var/gdc-install/state
    sudo mv '${REMOTE_TMP}' '${TARGET_FILE}'
    sudo chown root:root '${TARGET_FILE}'
    sudo chmod 0644 '${TARGET_FILE}'
    sudo rm -f '${TARGET_STATE}'
"

echo "[-] Restarting gdc-provision.service..."
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${NODE_IP}" "sudo systemctl restart gdc-provision.service"

echo "[-] Following gdc-provision.service logs (Ctrl+C to stop)..."
ssh "${SSH_OPTS[@]}" -t "${SSH_USER}@${NODE_IP}" "sudo journalctl -u gdc-provision.service -f"
```

Make it executable: `chmod +x bin/node-ops/inject-manual-facts.sh`

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_inject_manual_facts_cli.py`
Expected: PASS (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add bin/node-ops/inject-manual-facts.sh test/test_inject_manual_facts_cli.py
git commit -m "feat: add inject-manual-facts.sh workstation operator script"
```

---

### Task 4: Documentation Updates in `docs/on-device-ansible.md`

**Files:**
- Modify: `docs/on-device-ansible.md:80-92`
- Test: `test/test_manual_facts_docs.py`

- [ ] **Step 1: Write the failing documentation test**

Create `test/test_manual_facts_docs.py`:
```python
import os
import unittest

DOC_PATH = os.path.join(
    os.path.dirname(__file__),
    "../docs/on-device-ansible.md"
)

class TestManualFactsDocs(unittest.TestCase):
    def test_doc_mentions_manual_facts_and_companion_export(self):
        self.assertTrue(os.path.exists(DOC_PATH))
        with open(DOC_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("gdc-fact-manual.json", content)
        self.assertIn("inject-manual-facts.sh", content)
        self.assertIn("Share / Download JSON", content)
        self.assertIn("machine-schema.json", content)
        self.assertIn("/var/gdc-install/state/cluster-ready.json", content)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_manual_facts_docs.py`
Expected: FAIL (missing references in doc)

- [ ] **Step 3: Update `docs/on-device-ansible.md`**

In `docs/on-device-ansible.md`, add Section 2.4:
```markdown
### 2.4. Bypassing GDC Companion with Manual Facts (`gdc-fact-manual.json`)

During testing, network isolation, or when GDC Companion is unavailable, you can manually inject machine configuration facts for **Stage 5 (Cluster Ready)**. When `/var/gdc-install/state/gdc-fact-manual.json` is present, Ansible slurps it directly, bypassing the Companion API lookup (`GET /v1/machine-info/{mac}`).

#### Sourcing / Exporting Facts from GDC Companion
You can obtain a valid JSON configuration from `gdc-companion`:
* **Web UI:** Navigate to the Machine Inventory view, select your machine, and click **"Share / Download JSON"** to export the exact JSON configuration.
* **API / CLI:**
  ```bash
  curl -s -H "Authorization: Bearer <API_KEY>" \
    "https://<companion-host>/v1/machine-info/<MAC_ADDRESS>" > gdc-fact-manual.json
  ```
All manual fact files must adhere to the official schema:
`/d/projects/google/gdc-companion/docs/machine-schema.json`.

#### Method A: Automated Injection via Workstation Tool (Recommended)
From your workstation, run:
```bash
./bin/node-ops/inject-manual-facts.sh --node 192.168.4.236 --facts path/to/gdc-fact-manual.json
```
This script validates the JSON against `machine-schema.json`, uploads it to `/var/gdc-install/state/gdc-fact-manual.json`, deletes `/var/gdc-install/state/cluster-ready.json`, and restarts `gdc-provision.service`.

#### Method B: Manual Injection on the Target Node
If executing directly on the target machine:
```bash
# 1. Place the facts file in the state directory
sudo mkdir -p /var/gdc-install/state
sudo cp gdc-fact-manual.json /var/gdc-install/state/gdc-fact-manual.json
sudo chown root:root /var/gdc-install/state/gdc-fact-manual.json
sudo chmod 0644 /var/gdc-install/state/gdc-fact-manual.json

# 2. Wipe the cluster-ready state to force re-evaluation
sudo rm -f /var/gdc-install/state/cluster-ready.json

# 3. Restart the provisioner service
sudo systemctl restart gdc-provision.service

# 4. Monitor live progress
sudo journalctl -u gdc-provision.service -f
```
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_manual_facts_docs.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/on-device-ansible.md test/test_manual_facts_docs.py
git commit -m "docs: add manual facts injection runbook and companion export guide"
```

---

### Task 5: Run Full Test Suite & Validation

**Files:**
- Test all created and modified files

- [ ] **Step 1: Run all unit tests**

Run:
```bash
python3 -m unittest discover -s test -p 'test_*.py'
```
Expected: All tests pass.

- [ ] **Step 2: Syntax and bash lint check**

Run:
```bash
bash -n bin/node-ops/inject-manual-facts.sh
```
Expected: Returncode 0 with no syntax errors.

- [ ] **Step 3: Update PROGRESS.md and commit**

Update `PROGRESS.md` to record the completion of the manual fact injection feature and runbook.
```bash
git add PROGRESS.md
git commit -m "docs: update PROGRESS.md with manual fact injection and state reset runbook"
```
