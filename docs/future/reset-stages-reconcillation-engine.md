---
title: "GDC Provisioner Auto-Retry & Stage-Scoped Reconciliation Engine"
document_id: "GDC-SPEC-FUTURE-001"
status: "Draft / Architecture Review"
target_file: "docs/future/reset-stages-reconcillation-engine.md"
target_issue: "https://gitlab.com/gcp-solutions-public/retail-edge/gdc-disk-provisioner/-/work_items/24"
related_specs:
  - "docs/specs/03-ready-linux-provisioning.md"
  - "docs/specs/05-cluster-turnup.md"
  - "docs/specs/17-custom-playbook-lifecycle-extensions.md"

goal_summary: >
  Implement an autonomous, stage-scoped self-healing engine (gdc-provision-healer)
  driven by a short-interval systemd timer (2–3 minutes). The engine fixes exit-code
  swallowing in gdc-provision.service, enforces bounded exponential backoff
  (2m -> 5m -> 10m -> 15m), archives failed state snapshots, re-fetches machine-info
  from the GDC Companion API, and executes stage-appropriate cleanup (including
  Kind container teardown and official 'bmctl reset node' routines for turnup failures)
  before re-triggering provisioning. This eliminates 24-hour node stalls caused by
  transient endpoint outages or temporary network partitions.

open_questions:
  - id: "Q1"
    question: "How should stale Google Cloud Fleet Hub memberships be handled if CLUSTER_TURNUP fails midway?"
    context: >
      local.yml has an assertion that fails fast if Fleet Hub shows the cluster membership
      is registered while the local cluster (/etc/kubernetes/admin.conf) is missing or dead.
      If bmctl registered the membership before crashing, a retry will immediately trigger this assertion.
    proposed_options:
      - option_a: "Automated Deregistration: The healer invokes 'gcloud container fleet memberships delete <cluster> --project=<proj> --quiet' during stage-scoped turnup reset."
      - option_b: "Skip Guard on Retry: The healer passes an environment variable (e.g. GDC_FORCE_TURNUP_RETRY=1) allowing bmctl to overwrite or reconcile existing memberships."
    recommendation: "Option A (Automated Deregistration): Keeps Fleet Hub clean and prevents conflicting membership resource UIDs."

  - id: "Q2"
    question: "Should the healer refresh the local Ansible playbook repository from Gitea prior to each retry?"
    context: >
      If a provisioning failure was caused by a syntax error or playbook bug that the operator
      just patched and pushed to Gitea, re-running without a git fetch/pull will repeat the exact same failure.
    proposed_options:
      - option_a: "Yes: Run 'git -C /var/gdc-install/playbooks/bootstrap pull --ff-only' before relaunching gdc-provision.service."
      - option_b: "No: Let ansible-pull handle git sync itself (relying on ansible-pull's standard clone/update flags)."
    recommendation: "Option B: ansible-pull already runs with --clean and fetches from Gitea; keeping git operations inside ansible-pull preserves lock safety."

  - id: "Q3"
    question: "How should multi-node (3-Node HA) topologies coordinate turnup retries?"
    context: >
      On secondary nodes (worker / cp-worker), turnup relies on the primary bootstrap node
      completing control plane inception and publishing endpoints/SSH keys.
    proposed_options:
      - option_a: "Autonomous with Probe: Secondary node healers probe the primary node VIP/API before restarting turnup."
      - option_b: "Strict Primary Orchestration: Only primary node runs automated turnup retries; secondary nodes wait in CLUSTER_READY."
    recommendation: "Option A: Autonomous healing with a lightweight VIP reachability probe before initiating turnup retries."

  - id: "Q4"
    question: "Should we provide an interactive CLI subcommand for operators to trigger immediate healing?"
    context: >
      During manual debugging, operators often do not want to wait for the 2–5 minute timer backoff.
    proposed_options:
      - option_a: "Provide 'gdc-node-ops.sh heal [--stage <stage>] [--force]' that clears backoff counters, executes stage cleanup, and triggers immediate restart."
      - option_b: "Rely solely on standard systemctl restart commands."
    recommendation: "Option A: Greatly improves developer velocity and crash-cart triage."

  - id: "Q5"
    question: "What retention limit should be enforced for archived failed state files?"
    context: >
      Each retry archives the failed state to /var/gdc-install/state/backups/<stage>-<timestamp>.json.
    proposed_options:
      - option_a: "Retain the last 5 snapshots per stage, pruning older ones."
      - option_b: "Retain all snapshots until the next full reboot/reinstall."
    recommendation: "Option A (Cap at 5 snapshots): Prevents disk clutter while preserving complete debugging evidence."
---

# Specification: GDC Provisioner Auto-Retry & Stage-Scoped Reconciliation Engine

## 1. Problem Statement & Background
Under the current GDC bare-metal provisioner lifecycle, when `gdc-provision.service` encounters a transient failure during Stage 5 (`CLUSTER_READY`), Stage 6 (`CLUSTER_TURNUP`), or Stage 7 (`POST_CLUSTER`):
1. **Swallowed Exit Code:** The `ExecStart` command in `gdc-provision.service.j2` terminates with `; sync`. Even with `-o pipefail`, bash returns exit status `0` (`SUCCESS`) because `sync` succeeds. As a result, systemd's `Restart=on-failure` is never triggered.
2. **24-Hour Inaction Window:** Because `gdc-provision.timer` is scheduled daily (`OnCalendar=*-*-* 02:00:00`), a node that fails at 19:12 UTC remains idle and broken for nearly 7 to 24 hours unless manually restarted via SSH by an operator.
3. **State Lockout:** When a stage fails, its state file (e.g. `/var/gdc-install/state/cluster-ready.json`) is marked `"status": "FAILED"`. Subsequent naive reruns may not purge corrupted staging bundles or re-query updated Companion API facts, causing the node to immediately fail again for the same reason.
4. **Cluster Inception Residue:** If `CLUSTER_TURNUP` fails midway, orphaned bootstrap Kind containers (`bmctl-control-plane`) or partially initialized kubelet/etcd processes block future turnup attempts with port conflicts and `EtcdClusterNotHealthy` errors.

---

## 2. Architecture: Watchdog Healer (`gdc-provision-healer`)

Rather than overloading Ansible with complex recovery logic, we employ a **two-tier architecture**:
1. **Tier 1 (Executor):** `gdc-provision.service` runs the standard `ansible-pull` playbooks. Its exit code handling is fixed to properly propagate non-zero failure statuses.
2. **Tier 2 (Supervisor & Healer):** `gdc-provision-healer.service` and `gdc-provision-healer.timer` run independently outside of Ansible, polling the state directory every 2 minutes. When a failure is detected, it handles backoff, stage cleanup, fact refreshing, and relaunching.

### 2.1 Decision Flowchart
```
+-----------------------------------------------------------------------------------+
|                            gdc-provision-healer.timer                            |
|                            (fires every 2 minutes)                                |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                       Guard 1: Concurrency & Lock Gate                           |
|       Is gdc-provision.service active OR /var/run/gdc-provision.lock held?        |
|                                [YES] -> Exit 0                                    |
|                                 [NO] -> Proceed                                   |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                       Guard 2: Completion & Target Gate                          |
|    Have all stages up to configured stop_stage (or UPKEEP) reached completed?     |
|                                [YES] -> Exit 0                                    |
|                                 [NO] -> Proceed                                   |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                     Guard 3: Bounded Backoff Schedule                             |
|          Read /var/gdc-install/state/provision-retry-tracker.json                 |
|   Backoff sequence: 2m -> 5m -> 10m -> 15m -> 15m (max 5 retries per stage)      |
|                      Has required backoff delay elapsed?                          |
|                                 [NO] -> Exit 0                                    |
|                                [YES] -> Proceed                                   |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                         Stage-Scoped Healing & Reset                             |
|       1. Refresh machine-info from Companion & rewrite gdc.fact                   |
|       2. Execute stage-specific cleanup (e.g. bmctl reset node)                   |
|       3. Archive failed state to /var/gdc-install/state/backups/                  |
|       4. Purge failed state file so Ansible can re-evaluate                       |
|       5. Trigger: systemctl restart gdc-provision.service                         |
+-----------------------------------------------------------------------------------+
```

---

## 3. Systemd Unit Definitions

### 3.1 Executor Fix: `src/build/templates/gdc-provision.service.j2`
```ini
[Unit]
Description=GDC Ready-Linux First Boot Provisioner
After=network.target network-online.target systemd-networkd-wait-online.service gitea.service
Wants=network-online.target
RequiresMountsFor=/var/lib/gitea /var/gdc-install /var/lib/nexus
StartLimitIntervalSec=0

[Service]
Type=oneshot
Environment=HOME=/root
Environment=PYTHONUNBUFFERED=1
Environment=ANSIBLE_FORCE_COLOR=1
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile=-/etc/default/gdc-provision
StandardOutput=journal
StandardError=journal
ExecStart=/bin/bash -o pipefail -c ' \
  mkdir -p /var/gdc-install/logs; \
  ln -sf /var/gdc-install/logs/gdc-ansible-pull.log /var/log/gdc-ansible-pull.log; \
  if ! command -v ansible-pull &>/dev/null; then \
    until curl -s -I --connect-timeout 1 http://127.0.0.1:8081/ &>/dev/null; do sleep 3; done; \
    apt-get update && apt-get install -y --no-install-recommends ansible git; \
  fi; \
  git config --system --add safe.directory /var/lib/gitea/repos/gdc/bootstrap-playbooks.git || true; \
  git config --system --add safe.directory "*" || true; \
  flock -n /var/run/gdc-provision.lock /usr/bin/ansible-pull \
    --clean \
    -d /var/gdc-install/playbooks/bootstrap \
    -U /var/lib/gitea/repos/gdc/bootstrap-playbooks.git \
    -C {{ git_branch | default("main") }} \
    -i localhost, \
    $ANSIBLE_PULL_FLAGS \
    local.yml 2>&1 | tee /var/gdc-install/logs/gdc-ansible-pull.log; \
  RC=${PIPESTATUS[0]}; \
  sync; \
  exit $RC'
RemainAfterExit=true
```

### 3.2 Supervisor Timer: `src/build/templates/gdc-provision-healer.timer.j2`
```ini
[Unit]
Description=GDC Provisioner Autonomous Self-Healing & Retry Watchdog
After=network.target

[Timer]
OnBootSec=3m
OnUnitActiveSec=2m
Persistent=true

[Install]
WantedBy=timers.target
```

### 3.3 Supervisor Service: `src/build/templates/gdc-provision-healer.service.j2`
```ini
[Unit]
Description=GDC Provisioner Autonomous State Reconciliation & Healing
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/gdc-provision-healer.py
StandardOutput=journal
StandardError=journal
```

---

## 4. Stage-Scoped Cleanup & Reset Matrix

Cleaning must be targeted to the specific failed stage to avoid destroying valid work:

| Failed Stage | Identified Failure Signature | Stage-Scoped Cleanup Actions |
| :--- | :--- | :--- |
| **Stage 4: `LINUX_READY`** | CIS benchmark failure, APT package lock, NTP sync drop | • Kill rogue `apt` or `dpkg` processes.<br>• Purge `/var/lib/apt/lists/lock` and `/var/cache/apt/archives/lock`.<br>• Purge failed `linux-ready.json`. |
| **Stage 5: `CLUSTER_READY`** | Bundle download failure (`[Errno 111]`), mTLS cert drop, Nexus TLS syntax error | • Delete partial/corrupt `/var/gdc-install/custom-bundle.tar.gz`.<br>• Re-verify mTLS client certificate validity via `provision-mtls-cert.sh`.<br>• Purge failed `cluster-ready.json`. |
| **Stage 6: `CLUSTER_TURNUP`** | Bootstrap Kind freeze, VIP bind error, `EtcdClusterNotHealthy`, preflight check failure | • Kill and remove orphaned Kind container: `docker rm -f bmctl-control-plane`.<br>• Remove rogue containerd/docker network bridges.<br>• If node was partially joined, run official GDC reset:<br>  `bmctl reset node --cluster <name> --workspace-dir <dir>` ([GDC Reset Docs](https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/how-to/reset-nodes)).<br>• If stale Fleet membership exists without local cluster, deregister from Fleet Hub.<br>• Clear workspace lock files in `/var/gdc-install/bmctl-workspace/`.<br>• Purge failed `cluster-turnup.json`. |
| **Stage 7: `POST_CLUSTER`** | CoreDNS rollout timeout, missing RootSync credentials (`KNV1061`, `KNV2004`) | • Delete failed temporary RootSync/RepoSync manifests.<br>• Do NOT reset the Kubernetes control plane or etcd.<br>• Purge failed `post-validation.json` and compatibility symlink `post-cluster.json`. |

---

## 5. Dynamic Machine-Info Refresh Sequence

Before retrying any failed stage, the healer refreshes the node's desired state:
1. Query active MAC from the primary network interface (`ip link`).
2. Query the GDC Companion API:
   ```bash
   curl -s -k --cert /var/gdc-install/keys/client.crt --key /var/gdc-install/keys/client.key \
     -H "Authorization: Bearer <API_KEY>" \
     "https://<COMPANION_URL>/v1/machine-info/<MAC>"
   ```
3. If the Companion API responds with HTTP 200:
   * Perform recursive dictionary merge with base facts.
   * Atomically replace `/etc/ansible/facts.d/gdc.fact`.
   * Update `/etc/gdc/api-lookup-status.json` (`api_lookup_successful: true`).
4. If the Companion API is still unreachable (`Connection refused` or HTTP 5xx):
   * Do **not** abort the retry.
   * Keep the existing `/etc/ansible/facts.d/gdc.fact` intact.
   * Log warning: `Companion API unreachable; using cached machine facts for retry attempt N`.

---

## 6. Bounded Exponential Backoff & State Archival

To avoid tight CPU loops and hammering upstream services, retry attempts are tracked in `/var/gdc-install/state/provision-retry-tracker.json`:

```json
{
  "stage": "CLUSTER_READY",
  "attempts": 2,
  "max_attempts": 5,
  "first_failure_time": "2026-10-20T19:12:22Z",
  "last_attempt_time": "2026-10-20T19:14:22Z",
  "next_retry_time": "2026-10-20T19:19:22Z",
  "backoff_interval_seconds": 300,
  "status": "RETRY_SCHEDULED"
}
```

### Backoff Schedule per Stage
* **Attempt 1:** Wait 2 minutes (`120s`)
* **Attempt 2:** Wait 5 minutes (`300s`)
* **Attempt 3:** Wait 10 minutes (`600s`)
* **Attempt 4:** Wait 15 minutes (`900s`)
* **Attempt 5:** Wait 15 minutes (`900s`)
* **Exhausted (> 5 attempts):** Mark `status: "PERMANENT_FAILURE"`. Halt automated retries and trigger `gdc-collector --stage <stage>` with alert flag to notify Companion dashboard.

### State Archival
Before removing any failed state file from `/var/gdc-install/state/`, the healer copies it to `/var/gdc-install/state/backups/<stage>-<timestamp>.json` (capped at the 5 most recent snapshots) so that historical debugging evidence is never destroyed.

---

## 7. Implementation Deliverables

1. **`src/build/templates/gdc-provision.service.j2`:** Fix exit code propagation (`RC=${PIPESTATUS[0]}; sync; exit $RC`).
2. **`src/build/templates/gdc-provision-healer.py.j2`:** The standalone reconciliation engine implementing guards, stage-scoped cleaners, `machine-info` re-fetch, and backoff tracking.
3. **`src/build/templates/gdc-provision-healer.service.j2` & `.timer.j2`:** Systemd supervisor units.
4. **`src/build/templates/user-data.j2`:** Enable `gdc-provision-healer.timer` alongside `gdc-provision.service`.
5. **CLI Extension:** Add `gdc-node-ops.sh heal [--stage <stage>] [--force]` to allow operator-driven manual re-healing.
6. **Unit Tests:** `test/test_provision_healer.py` validating:
   * Exit code propagation.
   * Backoff interval calculation.
   * Stage cleanup routing (verifying `bmctl reset node` invocation on turnup failure).
   * Safe archival and machine-info merge.
