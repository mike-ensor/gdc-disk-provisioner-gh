# Spec: YAML-Driven Endpoint Checks & Platform DNS Retries

**Feature:** `yaml-endpoint-checks-and-dns-retries`  
**Status:** Approved  
**Date:** 2026-09-30  

## Objectives
1. Migrate hardcoded endpoint checks in `check_endpoints.py` to a declarative YAML manifest `src/ansible/vars/endpoints.yml`.
2. Categorize endpoints into:
   - `system`: Outbound Google Cloud APIs and container registries.
   - `platform`: Internal lab/node control plane endpoints (Step CA, GDC Companion, NTP time servers).
3. Split execution cadences into:
   - `always`: Validated on every Ansible preflight invocation across all stages.
   - `once.<stage>`: Validated exclusively during the designated lifecycle stage.
4. Mark off-stage checks with status `SKIPPED` (severity `INFO`, `duration_ms: 0`), preventing false alarms in `gdc-companion`.
5. Implement bounded DNS retries (5 attempts, 2-3s delay) for platform endpoints. If retries fail:
   - Recommend standalone fallback (`fallback_recommended: true`).
   - Trigger Ansible standalone fallback in `machine_orchestration` without hanging.
   - Record resolution status and unresolved domains in `cluster_ready_evidence`.
