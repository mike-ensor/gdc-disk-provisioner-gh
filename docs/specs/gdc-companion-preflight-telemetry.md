# Specification: Decoupled Preflight Validation Contract

**Status:** Proposed  
**Target Project:** `gdc-companion` (Collector & Backend) and `gdc-disk-provisioner` (Ansible Runner)  
**Authors:** GDC Engineering  

## 1. Overview
The GDC Bare Metal Node provisioning lifecycle (driven by Ansible via `ansible-pull`) is complex and can take significant time to execute. If critical dependencies (hardware devices, required binaries, or network routes) are missing, the installation pipeline currently fails midway through the execution, resulting in cryptic playbook stack traces that are difficult for field technicians to parse.

To solve this, we are introducing a **"Fail-Fast" Preflight Validation Stage**. This spec outlines a decoupled architecture where the execution engine (Ansible) performs the validations, but the telemetry and reporting engine (`gdc-collector`) surfaces the results back to the companion server using a shared JSON contract.

## 2. Architectural Objectives
1. **Fail-Fast Provisioning:** Detect missing prerequisites immediately (in seconds) before system state mutations occur.
2. **Decoupled Execution & Reporting:** `gdc-collector` should not need to know *how* to test an Ansible configuration; it only needs to know *what* the result was.
3. **Standardized Contract:** Use a formal JSON Schema to serialize test outcomes between the executor (Ansible/Bash) and the telemetry agent (Rust).

## 3. The Implementation Flow

1. **Test Execution (Ansible):** 
   - A new stage (`stage_preflight_checks.yml`) is injected at the start of the `local.yml` playbook.
   - Ansible runs various `stat`, `command`, and `uri` modules to assert system readiness.
   - Ansible compiles these results into a standardized JSON payload.
   - Ansible writes this payload to the disk at `/var/gdc-install/state/preflight-validation-results.json`.
   - If any `FATAL` severity test fails, Ansible gracefully halts execution with a known error.

2. **Telemetry Ingestion (`gdc-collector`):**
   - The `gdc-collector` binary runs.
   - It checks for the existence of `/var/gdc-install/state/preflight-validation-results.json`.
   - It parses the JSON payload using the standardized schema.
   - It embeds this array into the `MachineDiagnosticReportDTO` payload sent to the companion server.

## 4. The JSON Schema Contract

This JSON Schema dictates the structure of the `preflight-validation-results.json` file. 

**Location:** This schema will eventually be hosted within the `gdc-companion` repository (e.g. `crates/models/src/schemas/preflight.rs`) to automatically generate Rust structs, but is temporarily bundled within the disk provisioner.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://gdc.google.com/schemas/preflight-validation-v1.json",
  "title": "GDC Preflight Validation Results",
  "description": "Standardized contract for surfacing decoupled pre-provisioning hardware, software, and network readiness checks.",
  "type": "object",
  "required": [
    "test_suite",
    "execution_timestamp",
    "overall_status",
    "results"
  ],
  "properties": {
    "test_suite": {
      "type": "string",
      "description": "The name of the test runner or suite generating this report (e.g., 'gdc-ansible-preflight')."
    },
    "execution_timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "RFC3339 timestamp of when the test suite completed execution."
    },
    "overall_status": {
      "type": "string",
      "enum": ["PASS", "FAIL", "WARN"],
      "description": "Aggregated status of the entire test suite. FAIL indicates at least one FATAL test failed."
    },
    "total_duration_ms": {
      "type": "integer",
      "minimum": 0,
      "description": "Total execution time of the test suite in milliseconds."
    },
    "results": {
      "type": "array",
      "description": "Collection of individual test case executions.",
      "items": {
        "type": "object",
        "required": [
          "test_name",
          "category",
          "status",
          "severity",
          "notes"
        ],
        "properties": {
          "test_name": {
            "type": "string",
            "description": "Unique identifier or descriptive name for the individual test."
          },
          "category": {
            "type": "string",
            "enum": ["hardware", "network", "storage", "binary", "configuration", "service"],
            "description": "The domain of the validation check."
          },
          "status": {
            "type": "string",
            "enum": ["PASS", "FAIL", "SKIPPED", "WARN"],
            "description": "The outcome of the test execution."
          },
          "severity": {
            "type": "string",
            "enum": ["FATAL", "WARNING", "INFO"],
            "description": "The impact of a test failure. FATAL means provisioning cannot proceed."
          },
          "notes": {
            "type": "string",
            "description": "Detailed output, error messages, or context regarding the test execution."
          },
          "remediation_hint": {
            "type": "string",
            "description": "Optional actionable advice for an operator to resolve a failure."
          },
          "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "RFC3339 timestamp of when the specific test was executed."
          },
          "duration_ms": {
            "type": "integer",
            "minimum": 0,
            "description": "Execution time of the individual test in milliseconds."
          },
          "meta": {
            "type": "object",
            "description": "Optional arbitrary metadata associated with the test execution (e.g. resolved IPs, socket status)."
          }
        }
      }
    }
  }
}
```

## 5. Endpoints Connectivity Check Coordination
Both `gdc-collector` (in Rust via `crates/collector/src/endpoints.rs`) and Ansible (in Python via `src/ansible/scripts/check_endpoints.py`) validate the same 25 core Google API, GDC Edge, and Container Registry domains:
- `accounts.google.com`
- `cloudresourcemanager.googleapis.com`
- `compute.googleapis.com`
- `connectgateway.googleapis.com`
- `containerregistry.googleapis.com`
- `gkeconnect.googleapis.com`
- `gkehub.googleapis.com`
- `gkeonprem.googleapis.com`
- `iam.googleapis.com`
- `iamcredentials.googleapis.com`
- `logging.googleapis.com`
- `monitoring.googleapis.com`
- `gkeonprem.mtls.googleapis.com`
- `oauth2.googleapis.com`
- `securetoken.googleapis.com`
- `servicecontrol.googleapis.com`
- `serviceusage.googleapis.com`
- `stackdriver.googleapis.com`
- `storage.googleapis.com`
- `sts.googleapis.com`
- `www.googleapis.com`
- `gcr.io`
- `k8s.gcr.io`
- `logging.gdce.googleapis.com`
- `storage.gdce.googleapis.com`

**Ingestion Rule for `gdc-collector`:**
If `/var/gdc-install/state/preflight-validation-results.json` exists on disk (generated by Ansible), `gdc-collector` should read the pre-computed test results instead of performing redundant DNS/TCP probes, speeding up telemetry collection. If the file is absent, `gdc-collector` executes its native checks as a fallback.

## 6. Required Actions in `gdc-companion`
When this specification is implemented in the companion repository:
1. Generate the Rust `PreflightValidationDTO` structs mapping to this schema.
2. Add a `preflight_validations: Option<PreflightValidationDTO>` property to the master `MachineDiagnosticReportDTO`.
3. In `crates/collector/src/prereqs.rs` (or similar), add file ingestion logic to check `/var/gdc-install/state/preflight-validation-results.json`, deserialize it, and append it to the outgoing report payload.
