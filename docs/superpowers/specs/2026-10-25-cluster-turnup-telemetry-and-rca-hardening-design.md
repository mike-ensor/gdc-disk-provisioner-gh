# Design Spec: Cluster Turnup Telemetry & RCA Hardening

**Date:** 2026-10-25  
**Component:** `gdc-companion` (`rca-runner`, `skills/08-cluster-turnup`), `gdc-disk-provisioner` (`create_cluster.sh`)  
**Status:** Draft / Ready for Implementation  

---

## 1. Problem Statement & Executive Summary

During automated diagnostic analysis and RCA generation for cluster provisioning (`CLUSTER_TURNUP`), recent reports generated for node `192.168.9.242` produced conflicting and misleading conclusions:
1. **Conflicting Lifecycle Status:** The report reported `status: "active"` alongside `failed_stage: "CLUSTER_TURNUP"`, leading the LLM to hallucinate that the management plane was desynchronized from the workload status.
2. **Telemetry Gap (`last_milestone: null` and `total_checks: 0`):** The diagnostic tool `audit_cluster_turnup.py` searched for obsolete Anthos regex patterns and summary text. Because modern `bmctl` logs structured Go/klog entries and categorized check results without a summary line, the tool returned empty stats. The LLM deduced that preflight checks were bypassed and the bootstrap cluster never transitioned to the control plane (even though the control plane had booted and was fully `Ready`).
3. **Misattributed Failure Cause (`IPV6_DUALSTACK`):** The LLM saw benign Go template warnings in `stderr` (`well-defined vars that were never replaced: IPV6_DUALSTACK`) and asserted that dual-stack networking configuration broke cluster inception. The actual root cause was a missing Git authentication secret in Kubernetes (`KNV1061: Secret es-gitlab-creds not found`).

This specification hardens telemetry injection, diagnostic log parsing, and prompt instructions to eliminate false positives and conflicting states.

---

## 2. Architectural Root Cause Analysis

### A. The "Active" Status Desynchronization
* **Root Cause:** In the GDC Companion database, `status` on `machine_reports` is an archival lifecycle indicator (`"active"` vs `"archived"`).
* **Defect:** In `docker/rca-runner/runner.py` (lines 458–460), the runner blindly copies `metadata["status"]` into `evidence["status"]`.
* **Impact:** The LLM receives `{"status": "active", "failed_stage": "CLUSTER_TURNUP"}`. The model misinterprets database archival status as cluster health status.

### B. Milestone & Preflight Regex Drift
* In `skills/08-cluster-turnup/tools/audit_cluster_turnup.py`:
  - `MILESTONE_PATTERNS` matches strings like `Initializing KinD bootstrap cluster`, but modern `bmctl` logs `Start: create a KIND cluster bmctl`, `Moving admin cluster resources...`, and `Deleting bootstrap cluster... OK`.
  - `preflight_summary` regex matches `Preflight summary:\s*(\d+)\s+passed,\s*(\d+)\s+failed`. In GDC bare-metal `check-preflight.log`, checks are logged line-by-line as `\t- [PASSED] <check>` without an aggregated summary banner.

---

## 3. Required Changes & Technical Specification

### Specification 1: Disambiguate Database Record Status in `rca-runner`
**Target File:** `gdc-companion/docker/rca-runner/runner.py`

1. When injecting metadata into `evidence` for machine reports, do NOT copy `metadata["status"]` directly to `evidence["status"]`.
2. Map database record status to `evidence["db_report_record_status"]` (`active` or `archived`).
3. Set `evidence["machine_provisioning_state"]` based on the latest stage result:
   - If `failed_stage` is present: `"FAILED"`
   - If `failed_stage` is null and stage 8 is complete: `"COMPLETED"`
   - Else: `"IN_PROGRESS"`

```python
# runner.py refactor
for field in ("hostname", "ip_address", "failed_stage", "report_id"):
    if not evidence.get(field) and metadata.get(field):
        evidence[field] = metadata.get(field)

if metadata.get("status"):
    evidence["db_report_record_status"] = metadata.get("status")

evidence["machine_lifecycle_status"] = (
    "FAILED" if evidence.get("failed_stage") else "HEALTHY"
)
```

---

### Specification 2: Update `MILESTONE_PATTERNS` for Modern `bmctl`
**Target File:** `gdc-companion/docker/rca-runner/skills/08-cluster-turnup/tools/audit_cluster_turnup.py`

Add support for modern Go klog milestone lines in `MILESTONE_PATTERNS`:

```python
MILESTONE_PATTERNS = [
    # Modern bmctl klog lines
    (re.compile(r"Start:\s*create a KIND cluster", re.IGNORECASE), "KinD Bootstrap Started"),
    (re.compile(r"Creating cluster\s+\"bmctl\"", re.IGNORECASE), "KinD Bootstrap Container Created"),
    (re.compile(r"Waiting for cluster to become ready", re.IGNORECASE), "Waiting for Control Plane Ready"),
    (re.compile(r"Waiting for node pools to become ready", re.IGNORECASE), "Node Pools Ready"),
    (re.compile(r"Moving admin cluster resources to the created admin cluster", re.IGNORECASE), "Control Plane Pivoted"),
    (re.compile(r"Deleting bootstrap cluster", re.IGNORECASE), "Bootstrap Cluster Torn Down"),
    (re.compile(r"\[OK\] Cluster creation complete", re.IGNORECASE), "Cluster Created"),
    
    # Fallback legacy patterns
    (re.compile(r"Initializing KinD bootstrap cluster", re.IGNORECASE), "KinD Bootstrap Initialized"),
    (re.compile(r"Deploying Anthos management components", re.IGNORECASE), "Deploying Management Components"),
    (re.compile(r"Pivoting objects to target bare-metal control plane", re.IGNORECASE), "Pivoting Objects to Target Control Plane"),
    (re.compile(r"(?:Cluster creation complete|Successfully created cluster)", re.IGNORECASE), "Cluster Created"),
]
```

---

### Specification 3: Parse Categorized Preflight Results
**Target File:** `gdc-companion/docker/rca-runner/skills/08-cluster-turnup/tools/audit_cluster_turnup.py`

When `Preflight summary:` is not matched, parse `[PASSED]`, `[FAILED]`, and `[SKIPPED]` check lines directly from `check-preflight.log` and per-node logs:

```python
passed_checks = len(re.findall(r"\[PASSED\]", content))
failed_checks = len(re.findall(r"\[FAILED\]", content))
skipped_checks = len(re.findall(r"\[SKIPPED\]", content))
total = passed_checks + failed_checks + skipped_checks

if total > 0 and preflight_summary["total_checks"] == 0:
    preflight_summary = {
        "total_checks": total,
        "failed_checks": failed_checks,
        "passed_checks": passed_checks,
        "skipped_checks": skipped_checks,
        "log_source": rel_p,
    }
```

---

### Specification 4: Filter Benign Warnings & Stderr Sanitization
**Target File:** `gdc-companion/docker/rca-runner/skills/08-cluster-turnup/tools/audit_cluster_turnup.py`

Before classifying or presenting `stderr` or error messages from Ansible / `create_cluster.sh`, filter out known non-fatal warnings:
1. `well-defined vars that were never replaced: IPV6_DUALSTACK`
2. `well-defined vars that were never replaced: DISTRIBUTION,KUBE_RBAC_PROXY_IMAGE_TAG`
3. `schema.go:.* unexpected field validation directive: validator, skipping validation`
4. `warnings.go:.* spec.privateKey.rotationPolicy`
5. `warnings.go:.* metadata.name: this is used in Pod names and hostnames`

---

### Specification 5: Diagnostic Prompt Hardening
**Target File:** `gdc-companion/docker/rca-runner/skills/08-cluster-turnup/prompt.md`

Add explicit guardrails to the LLM system prompt:
1. **No Phantom State Desyncs:**
   *"The field `db_report_record_status: 'active'` indicates that the database report row is active (not archived). It does NOT imply the machine or cluster is operational. If `failed_stage` is present, evaluate the machine as FAILED."*
2. **Require Fatal Evidence for Root Cause:**
   *"Do NOT attribute failures to templating warnings (such as IPV6_DUALSTACK), DNS warnings, or unreplaced variable notices unless there is a fatal non-zero exit code directly attributed to that task."*
3. **Verify GitOps / ACM Reconcilers:**
   *"If the logs indicate that the cluster was created successfully (`[OK] Cluster creation complete`), check whether the failure occurred during RootSync verification, Git authentication, or secret retrieval (e.g. KNV1061, KNV2004)."*

---

## 4. Verification Plan

1. **Unit Tests:**
   Add unit tests in `gdc-companion/docker/rca-runner/tests/test_audit_cluster_turnup.py`:
   - Assert modern `bmctl` logs populate `last_milestone` with `"Cluster Created"` or `"Control Plane Pivoted"`.
   - Assert `[PASSED]` lines in `check-preflight.log` yield `total_checks > 0` and `failed_checks == 0`.
   - Assert `IPV6_DUALSTACK` stderr is filtered and not classified as a turnup failure.
2. **Re-run RCA Simulation:**
   Run `runner.py --skill 08-cluster-turnup` against report archive for `gdc-extreme-242` and verify:
   - No conflicting status hallucination in section 1 or 3.
   - Root cause accurately highlights `KNV1061: Secret es-gitlab-creds not found`.
   - Preflight checks correctly report 4 passed.
