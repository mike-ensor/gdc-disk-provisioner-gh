# Multi-Mode Companion Source Resolution Design

## Overview
This design specifies a robust, multi-mode configuration for resolving schemas between `gdc-disk-provisioner` and `gdc-companion`. Controlled exclusively by the `GDC_COMPANION_SOURCE` environment variable, it prevents unexpected unit test failures during offline or hermetic CI/CD builds while allowing seamless synchronization when a local repository or remote cloud companion endpoint is provided.

## Motivation & Requirements
Currently, `test/test_manual_facts_schema.py` and `test/bin/sync-schemas.sh` contain hardcoded paths pointing to `/d/projects/google/gdc-companion/docs/machine-schema.json`. When the sibling directory exists on disk but schemas diverge before synchronization, pre-flight checks in `./build.sh` fail. Furthermore, the provisioner lacks standard HTTP schema resolution against live GDC Companion endpoints (e.g. `https://gdc-companion.ensor-labs.com/v1/schema/machine`).

The solution must support three distinct scenarios:
1. **Local Filesystem:** Both projects exist on disk; an environment variable points to the base path of the `gdc-companion` repository.
2. **Cloud HTTP Endpoint:** Remote companion service is accessible over HTTP/HTTPS; schemas are retrieved from `/v1/schema/{name}`.
3. **Hermetic Offline / CI/CD:** No companion is available; the variable is empty or `"none"`. Tests fall back to vendored local schemas and skip upstream divergence checks. When the variable is completely unset or empty, a display-only `[ERROR]` log is emitted for visibility without failing tests or the build.

## Specification

### 1. Environment Variable Definition: `GDC_COMPANION_SOURCE`

`GDC_COMPANION_SOURCE` is the single authoritative environment variable governing companion resolution:

| Value Pattern | Resolved Mode | Logging Action | Behavior |
| :--- | :--- | :--- | :--- |
| **Unset or Empty (`""`)** | `OFFLINE` | Emits display-only `[ERROR]` log to stderr/stdout. | Uses local vendored schemas; skips upstream divergence assertions. Exits 0 / tests pass. |
| **`"none"` or `"disabled"`** | `OFFLINE` | Emits informational `[INFO]` log. | Uses local vendored schemas; skips upstream divergence assertions. Exits 0 / tests pass. |
| **`http://*` or `https://*`** | `CLOUD_HTTP` | Emits `[INFO]` with target endpoint. | Fetches schemas via HTTP GET from `${GDC_COMPANION_SOURCE}/v1/schema/{name}`. Divergence fails if mismatched; connectivity failures raise explicit errors. |
| **Any directory path** | `LOCAL_FS` | Emits `[INFO]` with directory path. | Reads schemas from `${GDC_COMPANION_SOURCE}/docs/${file}`. Divergence fails if mismatched; missing directory raises explicit errors. |

### 2. Architecture & Shared Resolver (`test/lib/companion_source.py`)

A shared Python module encapsulates mode detection, logging, and schema fetching.

#### Schema Route Mapping (Cloud HTTP Mode)
* `machine-schema.json` &rarr; `${GDC_COMPANION_SOURCE}/v1/schema/machine`
* `report-schema.json` &rarr; `${GDC_COMPANION_SOURCE}/v1/schema/report`
* `build-report-schema.json` &rarr; `${GDC_COMPANION_SOURCE}/v1/schema/build-report` (falls back to `${GDC_COMPANION_SOURCE}/docs/build-report-schema.json`)

#### Display-Only ERROR Log Semantics
When `GDC_COMPANION_SOURCE` is unset or empty:
```text
[ERROR] GDC_COMPANION_SOURCE environment variable is not defined. Defaulting to hermetic/offline mode (skipping upstream schema synchronization).
```
* **Critical Rule:** This message is purely visual. It does **not** raise an exception, does **not** cause unit tests to fail, and does **not** return a non-zero exit code.

#### Explicit Failure Semantics
If `GDC_COMPANION_SOURCE` is explicitly configured to a path that does not exist or a URL that fails network connectivity or HTTP response, the resolver raises an explicit `FileNotFoundError` or `urllib.error.URLError` to ensure broken configurations fail fast.

### 3. Tooling Integration

#### A. `test/test_manual_facts_schema.py`
* Remove hardcoded `DEFAULT_SCHEMA_PATH = "/d/projects/google/gdc-companion/..."` and `FALLBACK_SCHEMA_PATH`.
* Update `test_no_divergence_from_upstream_companion`:
  * If `CompanionSourceResolver.get_mode() == CompanionMode.OFFLINE`:
    * Calls `self.skipTest("Upstream gdc-companion not configured (offline mode); skipping divergence check.")`.
  * If mode is `LOCAL_FS` or `CLOUD_HTTP`:
    * Fetches upstream schema and asserts equality against local `docs/machine-schema.json` (ignoring `$comment`).
* Update `test_sync_schemas_script`:
  * Verifies `--help`.
  * Only runs `--check` if mode is `LOCAL_FS` or `CLOUD_HTTP`.

#### B. `test/bin/sync-schemas.sh`
* Accepts `--source <PATH|URL|none>` or reads `$GDC_COMPANION_SOURCE`.
* When mode is `OFFLINE`:
  * If `--check`: exits 0 with notice that offline mode skips divergence checks.
  * If sync: exits 0 with notice that no remote source is configured.
* When mode is `LOCAL_FS` or `CLOUD_HTTP`:
  * Retrieves latest schemas and writes them to `docs/` with the standard vendored header comment.

### 4. Unit Testing & Verification
* Dedicated test suite: `test/test_companion_source.py`:
  1. Unset `GDC_COMPANION_SOURCE` logs display `[ERROR]` and returns mode `OFFLINE`.
  2. `GDC_COMPANION_SOURCE="none"` logs `[INFO]` and returns mode `OFFLINE`.
  3. `GDC_COMPANION_SOURCE="https://..."` returns mode `CLOUD_HTTP` and queries mapped endpoints.
  4. `GDC_COMPANION_SOURCE="/dir"` returns mode `LOCAL_FS` and reads schema files.
  5. Missing explicit directory raises `FileNotFoundError`.
  6. Broken explicit URL raises error.
* Integration test: `test_manual_facts_schema.py` passes under all modes.
* Full preflight build: `./build.sh --env honeywell` passes cleanly.
