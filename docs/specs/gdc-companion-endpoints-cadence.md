# Specification: GDC Endpoint Readiness & Stage Cadence

**Status:** Approved  
**Target Projects:** `gdc-companion` (Backend, Web UI & Collector) and `gdc-disk-provisioner` (Ansible Runner)  
**Authors:** GDC Engineering  

---

## 1. Overview
Starting with ISO release `v0.9.15`, endpoint connectivity and readiness checks are partitioned into two architectural domains:
1. **`system`**: External Google Cloud APIs and container registries (`compute.googleapis.com`, `gcr.io`, `storage.googleapis.com`, etc.) used to verify outbound internet egress and NAT routing.
2. **`platform`**: Local bare-metal infrastructure (`gdc-companion`, `step-ca`, NTP time servers) used to verify local control plane availability.

Endpoints are further organized into two execution cadences:
* **`always`**: High-priority core connectivity verified on every Ansible preflight execution across all stages.
* **`once`**: Stage-specific dependencies checked exclusively when that particular lifecycle stage executes (e.g. `second-boot` checks `step-ca` and `companion` before enrollment; `cluster-turnup` checks `k8s.gcr.io`).

---

## 2. Status Definitions
The endpoint checker emits results using standardized statuses:
* **`PASS`**: DNS resolved and TCP/UDP socket connected successfully.
* **`WARN`**: Transient condition (e.g., DNS resolved but port unreachable), or non-fatal platform fallback recommended.
* **`FAIL`**: Fatal requirement unreachable.
* **`SKIPPED`**: **Not executed during this run.** The check is designated for a different lifecycle stage and was intentionally deferred. **`SKIPPED` is NOT a failure.**

---

## 3. Schema Contracts & Output Payloads

### A. Preflight Validation Payload (`/var/gdc-install/state/preflight-validation-results.json`)
```json
{
  "$schema": "https://gdc.google.com/schemas/preflight-validation-v1.json",
  "test_suite": "gdc-ansible-preflight",
  "current_stage": "second-boot",
  "execution_timestamp": "2026-09-30T04:15:00Z",
  "overall_status": "PASS",
  "total_duration_ms": 125,
  "results": [
    {
      "test_name": "endpoint_connect_compute.googleapis.com",
      "category": "network",
      "status": "PASS",
      "severity": "INFO",
      "notes": "Google API (compute.googleapis.com:443): Resolved to 142.251.45.138 and connected via TCP/443 successfully.",
      "remediation_hint": "Endpoint compute.googleapis.com:443 is reachable.",
      "timestamp": "2026-09-30T04:15:00Z",
      "duration_ms": 25,
      "meta": {
        "scope": "system",
        "cadence": "always",
        "executed": true,
        "domain": "compute.googleapis.com",
        "port": 443,
        "dns_resolved": true,
        "resolved_ip": "142.251.45.138",
        "tcp_connected": true,
        "attempts": 1
      }
    },
    {
      "test_name": "endpoint_connect_step_ca",
      "category": "network",
      "status": "PASS",
      "severity": "INFO",
      "notes": "Step CA (step-ca.ensor-labs.com:443): Resolved to 192.168.20.102 and connected via TCP/443 successfully.",
      "remediation_hint": "Endpoint step-ca.ensor-labs.com:443 is reachable.",
      "timestamp": "2026-09-30T04:15:00Z",
      "duration_ms": 20,
      "meta": {
        "scope": "platform",
        "cadence": "once",
        "executed": true,
        "domain": "step-ca.ensor-labs.com",
        "port": 443,
        "dns_resolved": true,
        "resolved_ip": "192.168.20.102",
        "tcp_connected": true,
        "attempts": 1,
        "target_stage": "second-boot"
      }
    },
    {
      "test_name": "endpoint_connect_cloudresourcemanager.googleapis.com",
      "category": "network",
      "status": "SKIPPED",
      "severity": "INFO",
      "notes": "Check deferred: designated for stage 'first-boot' (current stage: 'second-boot').",
      "remediation_hint": "No action required. This check will be evaluated during stage 'first-boot'.",
      "timestamp": "2026-09-30T04:15:00Z",
      "duration_ms": 0,
      "meta": {
        "scope": "system",
        "cadence": "once",
        "executed": false,
        "target_stage": "first-boot",
        "current_stage": "second-boot",
        "domain": "cloudresourcemanager.googleapis.com",
        "port": 443
      }
    }
  ]
}
```

### B. Machine Diagnostic Report (`report.json -> gdc_endpoints_readiness`)
In `gdc-companion/docs/report-schema.json`, each entry under `gdc_endpoints_readiness.<network>.<domain>` supports:
```json
{
  "status": "SKIPPED",
  "executed": false,
  "scope": "platform",
  "target_stage": "cluster-ready",
  "dns_resolved": null,
  "resolved_ip": null,
  "tcp_connected": null,
  "notes": "Deferred until cluster-ready stage"
}
```

### C. Stage State & Evidence File (`/var/gdc-install/state/cluster-ready.json`)
```json
{
  "stage": "CLUSTER_READY",
  "status": "completed",
  "timestamp": "2026-09-30T04:22:15Z",
  "evidence": {
    "operating_mode": "standalone",
    "dns_fallback_active": true,
    "dns_resolution": {
      "status": "FAILED",
      "attempted_retries": 5,
      "unresolved_domains": [
        "step-ca.ensor-labs.com"
      ],
      "notes": "DNS resolution could not be completed for GDC Companion / Step CA after retries. Standalone fallback configuration engaged."
    }
  }
}
```

---

## 4. Companion UI Guidelines (`index.html`)
1. **Never Flag `SKIPPED` as Red/Failed**:
   - `PASS`: Green border (`rgba(16,185,129,0.2)`), green badge `[OK]`.
   - `WARN`: Amber border (`rgba(245,158,11,0.2)`), yellow badge `[WARN]`.
   - `FAIL`: Red border (`rgba(239,68,68,0.2)`), red badge `[FAIL]`.
   - `SKIPPED`: Neutral grey border (`rgba(255,255,255,0.08)`), muted badge `[DEFERRED: <stage>]`.
2. **Summary Counter**:
   - Exclude `SKIPPED` checks from the active ratio:
     - Example: `4/4 Active Endpoints (18 Deferred)`.
