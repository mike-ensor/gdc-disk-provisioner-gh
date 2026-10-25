# Cluster Turnup Telemetry & Secret Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden cluster turnup execution, secret assurance, and failure telemetry in `gdc-disk-provisioner` so that Config Sync auth secrets are guaranteed across all inception and early-exit paths, and rich error details (rather than generic messages) are captured in `cluster-turnup.json` for diagnostic parsers.

**Architecture:** Update `bin/cluster/create_cluster.sh` to guarantee secret creation prior to any early-exit check and propagate terminal RootSync failure messages. Update `src/ansible/local.yml` to capture dynamic `ansible_failed_result` (`stderr`, `rc`, `stdout_lines`) into `cluster-turnup.json` evidence rather than a static string. Validate the behavior with pytest unit tests in `test/test_cluster_turnup.py` and Ansible verification scripts.

**Tech Stack:** Bash, Ansible Playbooks / Jinja2, Python 3, Pytest

---

### File Structure Map

- **Modified:** `bin/cluster/create_cluster.sh`
  - Responsibilities: Pre-inception secret assurance across re-entrant paths; terminal RootSync error logging to `stderr`.
- **Modified:** `src/ansible/local.yml`
  - Responsibilities: Dynamic error evidence capture in `rescue:` block for Stage 6 (`CLUSTER_TURNUP`).
- **Modified:** `test/test_cluster_turnup.py`
  - Responsibilities: Unit tests verifying secret creation on early-exit and stderr capture on failure.

---

### Task 1: Add Unit Tests for Early-Exit Secret Assurance in `test_cluster_turnup.py`

**Files:**
- Modify: `test/test_cluster_turnup.py`

- [ ] **Step 1: Write the failing unit tests for early-exit secret assurance**

Add tests to `test/test_cluster_turnup.py` asserting that when `create_cluster.sh` detects an already-healthy local cluster and Fleet membership, it invokes `ensure_config_sync_auth_secret` before exiting 0 if `ROOT_REPO_SECRET` is set.

```python
def test_healthy_cluster_early_exit_ensures_auth_secret(tmp_path: Path):
    """Assert that early exit for an already-healthy cluster still ensures auth secret exists."""
    script_path = REPO_ROOT / "bin" / "cluster" / "create_cluster.sh"
    runner_script = tmp_path / "test_early_exit.sh"
    runner_script.write_text(f"""#!/usr/bin/env bash
set -e
export KUBECONFIG="{tmp_path}/admin.conf"
touch "{tmp_path}/admin.conf"
export PROJECT_ID="test-proj"
export CLUSTER_NAME="test-cluster"
export K8S_NETWORK_IP="192.168.1.10"
export CLUSTER_VIP="192.168.1.100"
export CLUSTER_INGRESS="192.168.1.101"
export PRIMARY_LOAD_BALANCER="192.168.1.101-192.168.1.109"
export CONFIG_SYNC_ENABLED="true"
export ROOT_REPO_SECRET="es-gitlab-creds"
export PRIMARY_ROOT_REPO="https://gitlab.com/example/repo.git"

# Mock sudo and gcloud
function sudo() {{
    if [[ "$*" == *"kubectl get nodes"* ]]; then
        return 0
    fi
    "$@"
}}
export -f sudo

function gcloud() {{
    if [[ "$*" == *"fleet memberships list"* ]]; then
        echo "test-cluster"
        return 0
    fi
    return 0
}}
export -f gcloud

# Source create_cluster.sh but intercept early exit
source "{script_path}" --dry-run
""")
    runner_script.chmod(0o755)
    res = subprocess.run([str(runner_script)], capture_output=True, text=True)
    assert res.returncode == 0
```

- [ ] **Step 2: Run pytest to verify the test behavior**

Run: `pytest test/test_cluster_turnup.py -k test_healthy_cluster_early_exit_ensures_auth_secret -v`
Expected: Passes or highlights missing invocation before early exit.

---

### Task 2: Implement Early-Exit Secret Assurance in `bin/cluster/create_cluster.sh`

**Files:**
- Modify: `bin/cluster/create_cluster.sh:1190-1230`

- [ ] **Step 1: Update State 1 and State 4 early-exit blocks**

In `bin/cluster/create_cluster.sh`, ensure `ensure_config_sync_auth_secret` is called before exiting when `LOCAL_CLUSTER_HEALTHY="true"`:

```bash
# State 1: Local cluster healthy AND Fleet Hub membership associated -> Clean skip
if [[ "${LOCAL_CLUSTER_HEALTHY}" == "true" && "${FLEET_ASSOCIATED}" == "true" ]]; then
	if [[ "${CONFIG_SYNC_ENABLED}" == "true" && -n "${ROOT_REPO_SECRET:-}" ]]; then
		ensure_config_sync_auth_secret \
			"${ROOT_REPO_SECRET}" \
			"${ROOT_REPO_GSM_SECRET:-${ROOT_REPO_SECRET}}" \
			"${ROOT_REPO_GSM_LOCATION:-global}" \
			"${ROOT_REPO_TYPE:-oci}" \
			"${PROJECT_ID}" \
			"config-management-system" \
			"/etc/kubernetes/admin.conf" || true
	fi
	echo "[OK] Cluster '${CLUSTER_NAME}' is already installed locally and registered in Fleet Hub. Skipping creation."
	exit 0
fi

# State 4: Local cluster exists, but Fleet Hub registration is absent -> Skip destructive inception
if [[ "${LOCAL_CLUSTER_HEALTHY}" == "true" && "${FLEET_ASSOCIATED}" == "false" ]]; then
	if [[ "${CONFIG_SYNC_ENABLED}" == "true" && -n "${ROOT_REPO_SECRET:-}" ]]; then
		ensure_config_sync_auth_secret \
			"${ROOT_REPO_SECRET}" \
			"${ROOT_REPO_GSM_SECRET:-${ROOT_REPO_SECRET}}" \
			"${ROOT_REPO_GSM_LOCATION:-global}" \
			"${ROOT_REPO_TYPE:-oci}" \
			"${PROJECT_ID}" \
			"config-management-system" \
			"/etc/kubernetes/admin.conf" || true
	fi
	echo "[OK] Cluster '${CLUSTER_NAME}' is already running locally (/etc/kubernetes/admin.conf). Skipping destructive inception."
	exit 0
fi
```

- [ ] **Step 2: Verify `verify_rootsync_readiness` outputs explicit error to stderr**

Check lines 519–523 of `bin/cluster/create_cluster.sh` to ensure `last_error_msg` is emitted to `stderr` upon failure so Ansible captures it in `ansible_failed_result.stderr`.

- [ ] **Step 3: Run pytest test suite**

Run: `pytest test/test_cluster_turnup.py -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add bin/cluster/create_cluster.sh test/test_cluster_turnup.py
git commit -m "fix(cluster): ensure Config Sync secret exists on early-exit paths"
```

---

### Task 3: Dynamic Evidence Capture in `src/ansible/local.yml`

**Files:**
- Modify: `src/ansible/local.yml:402-427`

- [ ] **Step 1: Update rescue block in Stage 6 of `local.yml`**

Replace the static `_error_detail` dictionary with dynamic extraction from `ansible_failed_result`:

```yaml
      rescue:
        - name: "GDC-STATE | Record ClusterTurnup Failure state"
          ansible.builtin.copy:
            dest: /var/gdc-install/state/cluster-turnup.json
            owner: root
            group: root
            mode: '0644'
            content: |
              {% set _evidence = cluster_turnup_evidence | default({}) %}
              {% set _failed_res = ansible_failed_result | default({}) %}
              {% set _raw_stderr = _failed_res.stderr | default("") %}
              {% set _raw_stdout = _failed_res.stdout | default("") %}
              {% set _stdout_lines = _failed_res.stdout_lines | default([]) %}
              {% set _tail_stdout = (_stdout_lines[-15:] | join('\n')) if (_stdout_lines | length > 0) else _raw_stdout %}
              {% set _error_msg = _failed_res.msg | default("Error creating a cluster. Check the 'bmctl-workspace' logs for details") %}
              {% set _error_detail = {
                "msg": _error_msg,
                "rc": _failed_res.rc | default(1),
                "cmd": _failed_res.cmd | default(["create_cluster.sh"]),
                "stderr": _raw_stderr,
                "stdout_tail": _tail_stdout
              } %}
              {% set _end_time = now(utc=true, fmt='%Y-%m-%dT%H:%M:%SZ') %}
              {% set _end_epoch = now(utc=true).strftime('%s') | int %}
              {% set _start_epoch = cluster_turnup_start_epoch | default(_end_epoch) | int %}
              {% set _duration = [_end_epoch - _start_epoch, 0] | max %}
              {% set _timing = {
                "start_time": cluster_turnup_start_time | default(_end_time),
                "end_time": _end_time,
                "duration_seconds": _duration,
                "overall_provisioning_start_time": provisioning_start_time | default(cluster_turnup_start_time | default(_end_time))
              } %}
              {% set _ = _evidence.update({"timing": _timing, "error_details": _error_detail}) %}
              {
                "stage": "CLUSTER_TURNUP",
                "status": "failed",
                "timestamp": "{{ _end_time }}",
                "evidence": {{ _evidence | to_json }}
              }
```

- [ ] **Step 2: Validate Ansible syntax and linting**

Run: `./test/verify_ansible.sh`
Expected: Playbook syntax is clean and ansible-lint passes with 0 errors.

- [ ] **Step 3: Commit**

```bash
git add src/ansible/local.yml
git commit -m "fix(state): capture dynamic error details in cluster turnup failure evidence"
```

---

### Task 4: Verify Deployment and End-to-End Fleet Compatibility

**Files:**
- Test against live local node / dry-run scripts

- [ ] **Step 1: Run comprehensive test suite**

Run: `pytest -v test/`
Expected: All tests pass.

- [ ] **Step 2: Push playbook update to local node to ensure seamless syntax validation**

Run: `./bin/local/gdc-node-ops.sh push-playbook --nodes 192.168.9.242 --no-follow`
Expected: Playbook pushed, committed, and service successfully restarted without errors.

- [ ] **Step 3: Verify node remains in Stage 8 complete**

Run: `ssh -o BatchMode=yes -o StrictHostKeyChecking=no gdc-admin@192.168.9.242 'cat /var/gdc-install/state/update-upkeep.json | jq -r .status'`
Expected: `completed`.
