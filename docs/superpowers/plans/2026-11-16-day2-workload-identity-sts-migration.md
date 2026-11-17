# Day-2 Workload Identity STS Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Day-2 edge host authentication from Step CA + GDC Companion mTLS to Google Cloud Security Token Service (STS) and Workload Identity Federation (WIF), eliminating the 24-hour mTLS certificate expiration deadlock on edge bare metal nodes while keeping Step CA strictly for Day-0/Day-1 cluster inception.

**Architecture:** 
1. **Pre-Cluster (Day-0/Day-1):** The node uses hardware TPM 2.0 EK attestation -> Step CA mTLS client certificate -> GDC Companion to broker the initial temporary GCP Bearer token needed to pull early assets and run `bmctl create cluster`.
2. **Post-Cluster (Day-2):** Once Kubernetes turns up, the cluster's non-expiring asymmetric private key (`/etc/kubernetes/pki/sa.key`) becomes the local cryptographic root of trust. A dedicated Kubernetes Service Account (`gdc-host-ksa`) with zero cluster RBAC permissions issues local OIDC tokens, which the host exchanges directly with `https://sts.googleapis.com/v1/token` to mint short-lived GCP OAuth Bearer tokens into `/run/gdc-auth/access_token`.
3. **Resilience & Fallback:** `/usr/local/bin/refresh-gdc-credentials.sh` becomes state-aware: it uses Google STS when Kubernetes is online, falling back to Step CA/Companion if pre-cluster, and exiting gracefully during WAN outages without breaking systemd or cron. `gdc-node-ops.sh push-token` is preserved as the universal out-of-band sideloading fallback.

**Tech Stack:** Bash, Kubernetes ServiceAccount Tokens (`kubectl create token`), Google Cloud Security Token Service (STS), Google Cloud IAM Credentials API (`generateAccessToken`), Ansible, Python (`pytest`).

---

### File Structure Map

| File | Responsibility |
|---|---|
| `src/ansible/roles/machine_orchestration/templates/refresh-gdc-credentials.sh.j2` | State-aware credential refresher: auto-detects running cluster, requests `gdc-host-ksa` token, exchanges via STS + IAM, and writes `/run/gdc-auth/access_token`. |
| `src/ansible/roles/post_cluster/tasks/workload_identity.yml` | Ensures `gdc-host-ksa` exists in the cluster with zero cluster RBAC roles, verified labels, and secret suppression. |
| `src/ansible/roles/post_cluster/tasks/main.yml` | Includes `workload_identity.yml` during PostCluster stage and triggers immediate Day-2 STS credential refresh. |
| `bin/local/gdc-node-ops.sh` | Updates `rotate-token` subcommand to recognize and verify post-cluster STS authentication mode alongside pre-cluster mTLS mode. |
| `test/test_refresh_credentials_fallback.py` | Unit tests for template rendering and STS vs. Companion branch execution logic. |
| `test/test_push_token_cli.py` | Unit tests for `gdc-node-ops.sh rotate-token` CLI options and help consistency. |

---

## Tasks

### Task 1: Create Unit Tests for State-Aware Credential Refresh Logic

**Files:**
- Modify: `test/test_refresh_credentials_fallback.py`

- [ ] **Step 1: Write tests for Kubernetes cluster detection and STS token exchange**

Add test cases verifying:
1. When `/etc/kubernetes/admin.conf` does NOT exist or `kubectl` fails, the script continues to the Step CA + Companion mTLS flow.
2. When `/etc/kubernetes/admin.conf` exists and `kubectl get nodes` succeeds, the script routes to the STS token exchange function (`refresh_via_k8s_sts`), mints a `gdc-host-ksa` token, exchanges it via STS, and updates `/run/gdc-auth/access_token`.
3. When WAN is offline in STS mode, the script exits gracefully (`0`) if a fallback token is present or outputs a clear warning without fatal exit.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_refresh_credentials_fallback.py -v`
Expected: FAIL (new STS test assertions fail because template does not yet contain STS branch).

- [ ] **Step 3: Commit test additions**

```bash
git add test/test_refresh_credentials_fallback.py
git commit -m "test(auth): add unit test coverage for state-aware K8s STS credential refresh"
```

---

### Task 2: Implement STS Workload Identity Branch in `refresh-gdc-credentials.sh.j2`

**Files:**
- Modify: `src/ansible/roles/machine_orchestration/templates/refresh-gdc-credentials.sh.j2`

- [ ] **Step 1: Implement `refresh_via_k8s_sts` function and state check**

In `refresh-gdc-credentials.sh.j2`:
1. Check if `/etc/kubernetes/admin.conf` exists and `kubectl --kubeconfig=/etc/kubernetes/admin.conf get nodes` exits `0`.
2. Extract cluster identity facts:
   - `PROJECT_ID`: `{{ machine_config.gcp_info.project_id }}` (fallback to `/var/gdc-install/state/gdc.fact` or `gcloud config get-value project`)
   - `CLUSTER_NAME`: `{{ machine_config.cluster.cluster_name | default(node_hostname) }}`
   - `PRIMARY_GSA`: `{{ machine_config.gcp_info.primary_gsa }}`
   - `MEMBERSHIP_LOCATION`: `{{ machine_config.gcp_info.membership_location | default('us-central1') }}`
3. Mint short-lived KSA token:
   ```bash
   AUDIENCE="${PROJECT_ID}.svc.id.goog"
   KSA_TOKEN=$(kubectl --kubeconfig=/etc/kubernetes/admin.conf create token gdc-host-ksa \
       --namespace="gdc" \
       --audience="${AUDIENCE}" \
       --duration=3600s 2>/dev/null || true)
   ```
4. Perform 2-step Google STS + IAM exchange:
   - Step A: POST to `https://sts.googleapis.com/v1/token` with audience `identitynamespace:${PROJECT_ID}.svc.id.goog:https://gkehub.googleapis.com/projects/${PROJECT_ID}/locations/${MEMBERSHIP_LOCATION}/memberships/${CLUSTER_NAME}`.
   - Step B: POST to `https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${PRIMARY_GSA}:generateAccessToken` using the federated Bearer token.
5. Write the resulting OAuth token to `/run/gdc-auth/access_token` and `/run/gdc-auth/adc_token.json`.
6. Enforce file permissions: `0644` on token files, `0755` on `/run/gdc-auth`.

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest test/test_refresh_credentials_fallback.py -v`
Expected: PASS

- [ ] **Step 3: Commit implementation**

```bash
git add src/ansible/roles/machine_orchestration/templates/refresh-gdc-credentials.sh.j2
git commit -m "feat(auth): implement K8s Workload Identity STS refresh in refresh-gdc-credentials"
```

---

### Task 3: Provision `gdc-host-ksa` in PostCluster Ansible Stage

**Files:**
- Create: `src/ansible/roles/post_cluster/tasks/workload_identity.yml`
- Modify: `src/ansible/roles/post_cluster/tasks/main.yml`

- [ ] **Step 1: Author `workload_identity.yml`**

1. Ensure target namespace (`gdc`) exists:
   ```yaml
   - name: "GDC-WIF | Ensure gdc namespace exists for host workload identity"
     ansible.builtin.command:
       cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf get ns gdc"
     register: _gdc_ns_check
     failed_when: false
     changed_when: false

   - name: "GDC-WIF | Create gdc namespace"
     ansible.builtin.command:
       cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf create ns gdc"
     when: _gdc_ns_check.rc != 0
   ```
2. Ensure `gdc-host-ksa` ServiceAccount exists with NO RBAC permissions:
   ```yaml
   - name: "GDC-WIF | Check if gdc-host-ksa ServiceAccount exists"
     ansible.builtin.command:
       cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf get sa gdc-host-ksa -n gdc"
     register: _gdc_sa_check
     failed_when: false
     changed_when: false

   - name: "GDC-WIF | Create gdc-host-ksa ServiceAccount"
     ansible.builtin.command:
       cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf create sa gdc-host-ksa -n gdc"
     when: _gdc_sa_check.rc != 0
   ```
3. Trigger immediate execution of `/usr/local/bin/refresh-gdc-credentials.sh` to transition `/run/gdc-auth/access_token` to STS-minted token.
4. Verify `gcloud auth print-access-token` succeeds.

- [ ] **Step 2: Include `workload_identity.yml` in `post_cluster/tasks/main.yml`**

Include the task early in `post_cluster` before ConfigSync and Fleet feature tasks.

- [ ] **Step 3: Run project linter and validation tests**

Run: `pytest test/ -q`
Expected: PASS

- [ ] **Step 4: Commit PostCluster changes**

```bash
git add src/ansible/roles/post_cluster/tasks/workload_identity.yml src/ansible/roles/post_cluster/tasks/main.yml
git commit -m "feat(post-cluster): provision gdc-host-ksa ServiceAccount and transition auth to STS"
```

---

### Task 4: Update `bin/local/gdc-node-ops.sh rotate-token` for STS Detection

**Files:**
- Modify: `bin/local/gdc-node-ops.sh`
- Modify: `test/test_push_token_cli.py`

- [ ] **Step 1: Update `cmd_rotate_token` in `gdc-node-ops.sh`**

In `cmd_rotate_token()`:
1. Detect node lifecycle state:
   - Check if `/etc/kubernetes/admin.conf` is present and active on target node.
   - If cluster is active: Inform user that token rotation is using Day-2 K8s STS Workload Identity.
   - If pre-cluster: Inform user that token rotation is using Day-0 Step CA + Companion mTLS.
2. In dry-run mode: Display the detected branch and expected actions.

- [ ] **Step 2: Add test assertion in `test/test_push_token_cli.py`**

Test that dry-run outputs clear mode information.

- [ ] **Step 3: Run tests**

Run: `pytest test/test_push_token_cli.py test/test_cli_help_consistency.py -v`
Expected: PASS

- [ ] **Step 4: Commit CLI updates**

```bash
git add bin/local/gdc-node-ops.sh test/test_push_token_cli.py
git commit -m "feat(cli): enhance rotate-token to display Day-2 STS vs Day-0 mTLS mode"
```

---

### Task 5: Live Verification on Lab Node (`192.168.9.242`)

- [ ] **Step 1: Deploy updated `refresh-gdc-credentials.sh` to `192.168.9.242`**
- [ ] **Step 2: Execute `/usr/local/bin/refresh-gdc-credentials.sh` as `gdc-admin`**
  - Verify it detects running Kubernetes.
  - Verify it mints `gdc-host-ksa` token.
  - Verify STS + IAM exchange succeeds with HTTP 200.
  - Verify `/run/gdc-auth/access_token` is updated.
- [ ] **Step 3: Verify `gcloud auth print-access-token` works cleanly**
- [ ] **Step 4: Test simulated offline recovery (run script with mocked Step CA failure to prove complete independence)**
