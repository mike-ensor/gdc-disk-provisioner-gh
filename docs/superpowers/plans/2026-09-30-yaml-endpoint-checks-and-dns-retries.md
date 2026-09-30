# Implementation Plan: YAML-Driven Endpoint Checks & Platform DNS Retries

**Goal:** Implement a declarative YAML-driven endpoint readiness architecture with stage-based cadences and bounded DNS retries for GDC Companion and Step CA.

## Architecture
- `src/ansible/vars/endpoints.yml`: Declarative manifest organizing endpoints into `system` vs `platform` and `always` vs `once.<stage>`.
- `src/ansible/scripts/check_endpoints.py`: Engine parsing the manifest, executing checks concurrently, retrying platform DNS, and emitting `SKIPPED` for deferred checks.
- `src/ansible/stages/stage_preflight_checks.yml`: Invokes `check_endpoints.py` with stage routing and sets `dns_fallback_active`.
- `src/ansible/roles/machine_orchestration/tasks/main.yml`: Gracefully falls back to standalone mode and stamps `cluster_ready_evidence`.
- `gdc-companion/docs/report-schema.json`: Updated schema accommodating `SKIPPED` status and stage metadata.
