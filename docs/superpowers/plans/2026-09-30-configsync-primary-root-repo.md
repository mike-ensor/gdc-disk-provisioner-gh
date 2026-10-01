# ConfigSync & PrimaryRootRepo Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement optional and default ConfigSync installation with support for `git` and `oci` Primary Root Repos, directory subfolder override (`cluster_config_name`), GCP Secret Manager (GSM) credential preflight verification and zero-disk bootstrap secret injection in GDC post-install.

**Architecture:** Extend `docs/machine-schema.json` with the structured `.cluster.primary_root_repo` object. Add pre-flight GSM secret verification in `stage_preflight_checks.yml`. Implement the complete ConfigSync fleet enablement, CRD wait loop, in-memory GSM secret injection, and `RootSync` CR application in `src/ansible/roles/post_cluster/tasks/config_sync.yml`. Align `bin/cluster/create_cluster.sh` and update documentation.

**Tech Stack:** Kubernetes (ConfigSync CRDs, RootSync v1beta1), GCP (Fleet Config Management, Secret Manager), Ansible, Bash, JSON Schema Draft-07, `glab` CLI.

---

### Task 1: Update Machine Config Schema (`docs/machine-schema.json`)

**Files:**
- Modify: `docs/machine-schema.json`
- Test: `test/test_machine_schema.py`

- [ ] **Step 1: Write schema validation test**

Create `test/test_machine_schema.py`:
```python
import json
import pytest
import jsonschema

def load_schema():
    with open("docs/machine-schema.json") as f:
        return json.load(f)

def test_schema_validates_legacy_string_primary_root_repo():
    schema = load_schema()
    with open("custom-data/machine-info-mock-net-9.json") as f:
        data = json.load(f)
    # Add minimal valid required fields if needed
    data.update({
        "bmctl_version": "1.35.300-gke.87",
        "gcp_info": {
            "project_id": "test-proj",
            "region": "us-west1",
            "primary_gsa": "sa@test-proj.iam.gserviceaccount.com"
        },
        "cluster": {
            "cluster_name": "test-cluster",
            "primary_root_repo": "us-docker.pkg.dev/test-proj/repo/config:v1.0.0",
            "primary_root_repo_auth_secret": "ext-oci-secret",
            "networking": {
                "cluster_vip": "192.168.9.100",
                "cluster_ingress": "192.168.9.101",
                "cluster_lb_range": "192.168.9.101-192.168.9.109"
            },
            "fleet_cluster_labels": ["type=test"]
        }
    })
    jsonschema.validate(instance=data, schema=schema)

def test_schema_validates_structured_git_primary_root_repo():
    schema = load_schema()
    data = {
        "hostname": "test-host",
        "bmctl_version": "1.35.300-gke.87",
        "network": {
            "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
            "cluster_network": {"vlan_id": 9, "dhcp_v4": True}
        },
        "gcp_info": {
            "project_id": "test-proj",
            "region": "us-west1",
            "primary_gsa": "sa@test-proj.iam.gserviceaccount.com"
        },
        "cluster": {
            "cluster_name": "test-cluster",
            "config_sync_enabled": True,
            "primary_root_repo": {
                "cluster_config_name": "custom-folder",
                "git": {
                    "repo_url": "https://gitlab.com/test-org/test-repo.git",
                    "branch": "main",
                    "gsm_secret_name": "git-creds"
                }
            },
            "networking": {
                "cluster_vip": "192.168.9.100",
                "cluster_ingress": "192.168.9.101",
                "cluster_lb_range": "192.168.9.101-192.168.9.109"
            },
            "fleet_cluster_labels": ["type=test"]
        },
        "peers": []
    }
    jsonschema.validate(instance=data, schema=schema)

def test_schema_validates_structured_oci_primary_root_repo():
    schema = load_schema()
    data = {
        "hostname": "test-host",
        "bmctl_version": "1.35.300-gke.87",
        "network": {
            "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
            "cluster_network": {"vlan_id": 9, "dhcp_v4": True}
        },
        "gcp_info": {
            "project_id": "test-proj",
            "region": "us-west1",
            "primary_gsa": "sa@test-proj.iam.gserviceaccount.com"
        },
        "cluster": {
            "cluster_name": "test-cluster",
            "primary_root_repo": {
                "oci": {
                    "image": "us-docker.pkg.dev/test-proj/repo/config:v1.0.0",
                    "gsa": "sa-name",
                    "gsm_secret_name": "ext-oci-secret"
                }
            },
            "networking": {
                "cluster_vip": "192.168.9.100",
                "cluster_ingress": "192.168.9.101",
                "cluster_lb_range": "192.168.9.101-192.168.9.109"
            },
            "fleet_cluster_labels": ["type=test"]
        },
        "peers": []
    }
    jsonschema.validate(instance=data, schema=schema)
```

- [ ] **Step 2: Run test to verify failure on structured data**

Run: `pytest test/test_machine_schema.py -v`  
Expected: FAIL on `test_schema_validates_structured_git_primary_root_repo` (string expected).

- [ ] **Step 3: Update `docs/machine-schema.json`**

Update `docs/machine-schema.json`:
- Allow `primary_root_repo` to be string OR object with `git` and `oci` definitions.
- Make `primary_root_repo_auth_secret` optional for backward compatibility.
- Add `config_sync_enabled` boolean property.

- [ ] **Step 4: Run test to verify schema tests pass**

Run: `pytest test/test_machine_schema.py -v`  
Expected: PASS (all 3 tests pass).

- [ ] **Step 5: Commit schema updates**

```bash
git add docs/machine-schema.json test/test_machine_schema.py
git commit -m "feat(schema): add structured git and oci primary_root_repo support"
```

---

### Task 2: Implement Early Pre-flight Fail-Fast Secret Check

**Files:**
- Modify: `src/ansible/stages/stage_preflight_checks.yml`
- Test: `test/test_preflight_gsm_secret.py`

- [ ] **Step 1: Write unit test for GSM secret verification logic**

Create `test/test_preflight_gsm_secret.py` testing secret verification command formatting and JSON parsing for both `git` and `oci` payloads.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest test/test_preflight_gsm_secret.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement preflight checks in `src/ansible/stages/stage_preflight_checks.yml`**

Add tasks to:
1. Detect if `primary_root_repo` has `git.gsm_secret_name` or `oci.gsm_secret_name`.
2. Execute `gcloud secrets describe` and `gcloud secrets versions access latest` via `command` module.
3. Validate payload keys (`token`/`password`/`ssh-privatekey` for git; `username`/`password` for oci).
4. Assert with clear error messages if secret is missing or misformatted.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_preflight_gsm_secret.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit preflight checks**

```bash
git add src/ansible/stages/stage_preflight_checks.yml test/test_preflight_gsm_secret.py
git commit -m "feat(preflight): fail fast if primary_root_repo GSM secret is missing"
```

---

### Task 3: Create Post-Cluster ConfigSync Tasks (`src/ansible/roles/post_cluster/tasks/config_sync.yml`)

**Files:**
- Create: `src/ansible/roles/post_cluster/tasks/config_sync.yml`
- Modify: `src/ansible/roles/post_cluster/tasks/main.yml`
- Test: `test/test_config_sync_tasks.py`

- [ ] **Step 1: Write test for RootSync YAML generation and dir path computation**

Create `test/test_config_sync_tasks.py` verifying template output for:
- Default cluster name path (`config/clusters/{{ cluster_name }}`)
- Overridden path (`config/clusters/{{ cluster_config_name }}`)
- Git source type with `auth: token` and `secretRef`
- OCI source type with `auth: gcpserviceaccount` (when GSA) vs `auth: token` (when secret)
- Omission of `primary_root_repo` (ConfigSync enabled, RootSync skipped).

- [ ] **Step 2: Run test to verify failure**

Run: `pytest test/test_config_sync_tasks.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement `src/ansible/roles/post_cluster/tasks/config_sync.yml`**

Add tasks:
1. Check `machine_config.cluster.config_sync_enabled | default(true)` guard.
2. Enable Fleet `config-management` feature idempotently:
   `gcloud beta container fleet config-management enable --project={{ gcp_project_id }}`.
3. Write `/var/gdc-install/state/acm-config.yaml` with `configSync.enabled: true`.
4. Apply ACM config to cluster membership using `gcloud beta container fleet config-management apply`.
5. Wait for `crd/rootsyncs.configsync.gke.io` to be established (`kubectl wait --for=condition=Established crd/rootsyncs.configsync.gke.io --timeout=180s`).
6. If `primary_root_repo` is defined:
   - If `gsm_secret_name` is present: fetch secret via `gcloud secrets versions access latest` and apply directly via `kubectl create secret generic {{ gsm_secret_name }} -n config-management-system --dry-run=client -o yaml | kubectl apply -f -`.
   - Render `primary-root-repo.yaml` and apply via `kubectl apply -f /var/gdc-install/state/primary-root-repo.yaml`.
7. Record status in `post_cluster_evidence.config_sync`.

- [ ] **Step 4: Update `src/ansible/roles/post_cluster/tasks/main.yml`**

Include `config_sync.yml` in `post_cluster/tasks/main.yml` and add `config_sync` verification facts to `post_cluster_evidence`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest test/test_config_sync_tasks.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit post-cluster ConfigSync tasks**

```bash
git add src/ansible/roles/post_cluster/tasks/config_sync.yml src/ansible/roles/post_cluster/tasks/main.yml test/test_config_sync_tasks.py
git commit -m "feat(post-cluster): implement ConfigSync and RootSync provisioning in post_cluster role"
```

---

### Task 4: Align Standalone `bin/cluster/create_cluster.sh`

**Files:**
- Modify: `bin/cluster/create_cluster.sh`
- Test: `test/test_create_cluster_params.sh`

- [ ] **Step 1: Write test for create_cluster.sh parameter parsing**

Create/update `test/test_create_cluster_params.sh` verifying that both string and dictionary representations of `.cluster.primary_root_repo` are parsed gracefully without syntax errors.

- [ ] **Step 2: Run test to verify current behavior**

Run: `bash test/test_create_cluster_params.sh`  
Expected: Exposes limitation on dictionary parsing.

- [ ] **Step 3: Update `bin/cluster/create_cluster.sh`**

Update `FACT_PRIMARY_ROOT_REPO` extraction in `create_cluster.sh` to safely inspect whether `primary_root_repo` is an object (extracting `oci.image` or `git.repo_url`) or a legacy string.

- [ ] **Step 4: Run test to verify it passes**

Run: `bash test/test_create_cluster_params.sh`  
Expected: PASS.

- [ ] **Step 5: Commit script changes**

```bash
git add bin/cluster/create_cluster.sh test/test_create_cluster_params.sh
git commit -m "fix(cluster): align create_cluster.sh with structured primary_root_repo facts"
```

---

### Task 5: Update Documentation & Quick Start Guides

**Files:**
- Modify: `docs/CREATE_CLUSTER.md`
- Modify: `docs/POST-INSTALL.md`

- [ ] **Step 1: Update `docs/CREATE_CLUSTER.md`**

Add clear prerequisites and quick-start instructions:
- Google Secret Manager secret creation format for OCI and Git.
- GSA Workload Identity binding commands when using OCI with GSA (`roles/iam.workloadIdentityUser` bound to `config-management-system/root-reconciler-primary-root-repo`).
- Secret Manager accessor role requirement for the node's primary GSA.

- [ ] **Step 2: Update `docs/POST-INSTALL.md`**

Document the Stage 7 post-cluster ConfigSync lifecycle, including secret bootstrapping without disk persistence and directory resolution rules (`config/clusters/<cluster-name>`).

- [ ] **Step 3: Commit documentation updates**

```bash
git add docs/CREATE_CLUSTER.md docs/POST-INSTALL.md
git commit -m "docs: document ConfigSync primary root repo setup, GSM secrets, and IAM prerequisites"
```

---

### Task 6: Comprehensive Verification & Merge Request Creation

**Files:**
- Test files: all unit tests (`pytest test/ -v`)
- Git repository

- [ ] **Step 1: Run complete test suite**

Run: `pytest test/ -v`  
Expected: All tests pass.

- [ ] **Step 2: Validate Ansible syntax**

Run: `ansible-playbook --syntax-check src/ansible/local.yml`  
Expected: Syntax OK.

- [ ] **Step 3: Push feature branch to origin**

```bash
git push -u origin feature/configsync-primary-root-repo
```

- [ ] **Step 4: Create Merge Request via glab**

```bash
glab mr create \
  --title "feat(configsync): add primary root repo support with GSM secret injection" \
  --description "Implements optional/default ConfigSync installation with support for Git and OCI Primary Root Repos, directory subfolder override (cluster_config_name), GSM credential preflight verification and zero-disk secret injection in Stage 7 post_cluster." \
  --target-branch main \
  --squash-before-merge
```

- [ ] **Step 5: Notify user with MR link for testing and approval**
