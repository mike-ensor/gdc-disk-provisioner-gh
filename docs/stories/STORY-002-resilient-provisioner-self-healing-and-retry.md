# STORY-002: Resilient Provisioner Exit Code Propagation and Self-Healing Retries

**Story ID:** `STORY-002`  
**Title:** Propagate Provisioner Failure Exit Codes and Implement Active Self-Healing Retries  
**Status:** `Draft`  
**Priority:** High  
**Actor:** GDC Node Provisioner / Systemd Runner / Infrastructure Engineer  
**Related Spec:** `docs/specs/03-ready-linux-provisioning.md`  

---

## 1. Story Statement

**As an** Infrastructure Engineer deploying bare-metal GDC nodes,  
**I want** `gdc-provision.service` to accurately propagate Ansible failure exit codes and actively retry provisioning on failure with a short backoff,  
**So that** transient network drops, service restarts (such as GDC Companion reboots), and temporary dependency unavailability recover automatically without leaving nodes stranded in failed states for 24 hours.

---

## 2. Background & Problem Analysis

In the current service definition (`src/build/templates/gdc-provision.service.j2`):
```ini
[Service]
Type=oneshot
Restart=on-failure
RestartSec=30s
ExecStart=/bin/bash -o pipefail -c " ... \
  flock -n /var/run/gdc-provision.lock /usr/bin/ansible-pull ... 2>&1 | tee /var/gdc-install/logs/gdc-ansible-pull.log; \
  sync"
RemainAfterExit=true
```

Two major defects prevent the intended self-healing behavior:
1. **Exit Code Masking via Semicolon:** In `ExecStart`, `; sync` follows the pipeline. Even with `-o pipefail`, the semicolon executes `sync` regardless of pipeline status. Because `sync` succeeds with code 0, bash exits with `0 (SUCCESS)`. Systemd records `status=0/SUCCESS`, meaning `Restart=on-failure` is **never triggered**.
2. **`Type=oneshot` + `RemainAfterExit=true` Freeze:** Because systemd marks the unit as `Active: active (exited)` on code 0, it never attempts to restart. The accompanying `gdc-provision.timer` is scheduled daily (`OnCalendar=*-*-* 02:00:00`), so a node failing provisioning sits completely idle for up to 24 hours until the next calendar day.

---

## 3. Trigger

A bare-metal node boots or reboots, launching `gdc-provision.service` during Stage 2 (`FIRST_BOOT`), or the node encounters a transient outage (e.g. Companion server rebooting, temporary DNS hiccup, or transient network partition).

---

## 4. Acceptance Criteria (BDD / Gherkin)

### Scenario 1: Exact Exit Code Propagation on Playbook Failure
```gherkin
Given a node executing "gdc-provision.service"
When "ansible-pull" exits with a non-zero return code (e.g. code 2 on fatal task error)
Then the shell command in "ExecStart" must exit with that same non-zero return code
And "sync" must still be called to flush disk buffers before exiting
And "systemctl is-failed gdc-provision.service" evaluates to true
```

### Scenario 2: Automatic Short-Interval Self-Healing Retry
```gherkin
Given "gdc-provision.service" failed due to a transient network or endpoint error
When the service enters the failed state
Then systemd automatically retries execution after a configured backoff (e.g. 30 seconds to 2 minutes)
And retries continue up to a bounded maximum or until reaching stage completion
And if the downstream endpoint (Companion API) recovers, the subsequent retry passes and advances provisioning
```

### Scenario 3: Clean Deactivation on Legitimate Completion
```gherkin
Given a node executing "gdc-provision.service"
When "ansible-pull" completes all required stages up to "stop_stage" or "UPKEEP"
Then the service exits with status code 0
And "RemainAfterExit=true" maintains the unit in "active (exited)" state
And no further retry loops are triggered until the scheduled daily upkeep timer or manual invocation
```

### Scenario 4: Locking and Concurrency Guard
```gherkin
Given an ongoing "gdc-provision.service" run holding "/var/run/gdc-provision.lock"
When a timer or manual trigger attempts a concurrent execution
Then "flock -n" prevents overlapping executions
And logs an informative message without corrupting the active playbook run
```

---

## 5. System Invariants & Constraints (EARS)

- **Ubiquitous:** The system shall preserve pipeline logs in `/var/gdc-install/logs/gdc-ansible-pull.log` regardless of whether execution succeeds or fails.
- **Event-Driven:** When `ansible-pull` terminates with a non-zero exit code, the wrapper shell shall capture the pipeline exit status and exit with that exact non-zero status.
- **State-Driven:** While provisioning is incomplete and failed, the system shall re-attempt execution on a short interval (e.g., 1–5 minutes) rather than waiting 24 hours for the daily maintenance window.
- **Unwanted Behavior:** If an execution fails, the system shall not report `status=0/SUCCESS` to systemd.

---

## 6. Implementation Notes & Recommendations

1. **Fix `ExecStart` exit trap in `src/build/templates/gdc-provision.service.j2`:**
   ```bash
   ExecStart=/bin/bash -o pipefail -c ' \
     mkdir -p /var/gdc-install/logs; \
     ... \
     flock -n /var/run/gdc-provision.lock /usr/bin/ansible-pull ... 2>&1 | tee /var/gdc-install/logs/gdc-ansible-pull.log; \
     RC=${PIPESTATUS[0]}; \
     sync; \
     exit $RC'
   ```
2. **Systemd Service Restructure:**
   - For `Type=oneshot`, change `RemainAfterExit=no` on failure, or pair `gdc-provision.service` with an active watchdog timer (e.g. `gdc-provision-retry.timer` with `OnUnitInactiveSec=3m` while state is not completed).
3. **Guard against rapid reboot thrashing:**
   - Include `StartLimitIntervalSec=10m` and `StartLimitBurst=5` to prevent infinite tight CPU spin if a failure is permanently unrecoverable (e.g. invalid syntax in playbooks).
