# Specification: Centralized ISO Profile Sync from GDC Companion

**Document Identifier:** `2026-10-16-sync-iso-profile-design`  
**Status:** PROPOSED  
**Author:** GDC Core Platform Engineering Team  
**Scope:** `gdc-disk-provisioner` CLI (`bin/local/gdc-node-ops.sh`) & `gdc-companion` API Integration  

---

## 1. Executive Summary & Problem Statement

### 1.1 Context
In GDC edge deployments, build-time configurations are parameterized via environment profile files (`src/build/{iso-profile}.env`, e.g., `local.env`, `honeywell.env`, `barn.env`). These files define crucial cluster network segments, temporary credentials, NTP servers, Subiquity partitioning presets, and hardware configurations.

Currently, distributing and synchronizing these profile override files across engineer workstations, remote test harnesses, and CI environments is manual and prone to configuration drift. 

### 1.2 Objective
Provide a unified, idempotent, and non-destructive CLI mechanism inside `bin/local/gdc-node-ops.sh` to:
1. Discover and list available environment profiles centrally hosted in `gdc-companion`.
2. Pull down a specified ISO profile directly in standard `.env` format from `GET /v1/iso-profiles/{name}?format=env`.
3. Safely back up existing local `.env` files into a dedicated versioned backup directory (`src/build/.backups/`) prior to mutation.
4. Atomically install or update `src/build/{iso-profile}.env` only upon a verified upstream HTTP 200 response, preventing corrupted, partial, or unauthenticated file overwrites.

---

## 2. Architectural Decisions & Principles

1. **Native Integration within `gdc-node-ops.sh`:**
   - Rather than introducing an isolated standalone utility or complex Python wrapper, the `pull-profile` functionality is introduced as a native subcommand within `bin/local/gdc-node-ops.sh` (`cmd_pull_profile`).
   - Adheres to existing CLI flag parser standards, help menus, and exit conventions.

2. **Upstream Companion API Contract:**
   - Target endpoint: `GET ${base_url}v1/iso-profiles/${profile_name}?format=env`.
   - Discovery endpoint: `GET ${base_url}v1/iso-profiles`.
   - The Companion API natively serializes key-value overrides into dotenv format with metadata headers when `?format=env` is queried.

3. **Strict Non-Destructive Transaction Boundary:**
   - Network payloads are downloaded directly to an isolated temporary file (`mktemp`).
   - The HTTP response code is evaluated via `curl -w "%{http_code}"`.
   - If the response is not `200 OK` (e.g., 401 Unauthorized, 403 Forbidden, 404 Not Found, 500 Internal Error, or connection timeout), the target local file and backups are untouched, temporary files are cleaned up, and the script exits with non-zero status.

4. **Dedicated Versioned Backups:**
   - When updating an existing profile (`src/build/{iso-profile}.env`), the existing file is preserved in `src/build/.backups/{iso-profile}.env.YYYYMMDD-HHMMSS`.
   - If no local profile file exists prior to pulling, it is created directly upon HTTP 200 without creating an empty backup.

5. **Configuration Precedence:**
   - Parameter resolution follows:
     1. Command-line flags (`--companion-url`, `--api-key`, `--name`).
     2. Environment variables (`INSTALL_COMPANION_BASE`, `INSTALL_COMPANION_API_KEY`).
     3. Auto-sourced `src/build/local.env` if present.
     4. Default fallbacks (`https://gdc-companion.gdc-labs.com/`).

---

## 3. Detailed Workflow & Data Flow

```text
 ┌──────────────────────┐
 │   Developer / CI     │
 └──────────┬───────────┘
            │
            │ ./bin/local/gdc-node-ops.sh pull-profile [--name <profile>]
            ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ gdc-node-ops.sh (cmd_pull_profile)                                     │
 │                                                                        │
 │ 1. Resolve configuration (flags > env > local.env > defaults)          │
 │ 2. Validate input parameters                                           │
 └──────────┬─────────────────────────────────────────────────────────────┘
            │
            ├─────────────────────────────────────────┐
            │ If --name omitted / --list passed       │ If --name <profile> specified
            ▼                                         ▼
 ┌──────────────────────────────┐          ┌──────────────────────────────┐
 │ GET /v1/iso-profiles         │          │ GET /v1/iso-profiles/{name}  │
 │ (Accept: application/json)   │          │     ?format=env              │
 └──────────┬───────────────────┘          └──────────┬───────────────────┘
            │                                         │ (Stream to /tmp/staging.XXXXXX)
            │ Status == 200                           │
            ▼                                         ▼
 ┌──────────────────────────────┐          ┌──────────────────────────────┐
 │ Parse JSON with jq/awk &     │          │ Check HTTP Status Code       │
 │ render tabular summary:      │          └──────────┬───────────────────┘
 │ - NAME                       │                     │
 │ - NETWORK_SEGMENT            │         ┌───────────┴───────────┐
 │ - OVERRIDES COUNT            │         │                       │
 │ - UPDATED_AT                 │         │ Status != 200         │ Status == 200
 └──────────────────────────────┘         ▼                       ▼
                                   ┌──────────────┐      ┌─────────────────────────────┐
                                   │ Abort!       │      │ Is src/build/{name}.env     │
                                   │ rm temp file │      │ already present on disk?    │
                                   │ Exit code 1  │      └──────────────┬──────────────┘
                                   └──────────────┘                     │
                                                     ┌──────────────────┴──────────────────┐
                                                     │ Yes                                 │ No
                                                     ▼                                     ▼
                                          ┌─────────────────────────────┐        ┌─────────────────────────────┐
                                          │ mkdir -p src/build/.backups │        │ Skip backup                 │
                                          │ cp target to                │        └──────────────┬──────────────┘
                                          │ .backups/{name}.env.{ts}    │                       │
                                          └──────────────┬──────────────┘                       │
                                                         └──────────────────┬───────────────────┘
                                                                            │
                                                                            ▼
                                                                 ┌─────────────────────────────┐
                                                                 │ Atomic Promotion:           │
                                                                 │ mv /tmp/staging.XXXXXX      │
                                                                 │    src/build/{name}.env     │
                                                                 │ chmod 0644                  │
                                                                 └─────────────────────────────┘
```

---

## 4. CLI Specification

### 4.1 Synopsis
```bash
./bin/local/gdc-node-ops.sh pull-profile [OPTIONS]
```

### 4.2 Flags & Options
| Flag | Description | Default |
|------|-------------|---------|
| `--name <name>` | Name of the ISO profile to pull (e.g., `honeywell`, `barn`, `local`). If omitted, lists remote profiles. | None (triggers listing) |
| `--companion-url <url>` | Base URL of GDC Companion API. | `INSTALL_COMPANION_BASE` or `https://gdc-companion.gdc-labs.com/` |
| `--api-key <key>` | API key for authenticating with Companion API. | `INSTALL_COMPANION_API_KEY` or empty |
| `--list` | Force profile listing even if `--name` was supplied. | `false` |
| `-h`, `--help` | Display command usage and help. | N/A |

### 4.3 Output Formats

#### Profile Listing Output:
```text
AVAILABLE ISO PROFILES (https://gdc-companion.gdc-labs.com/):
NAME                 NETWORK SEGMENT      OVERRIDES    LAST UPDATED
--------------------------------------------------------------------------------
barn                 192.168.20.0/24      14           2026-10-14T08:22:10Z
honeywell            192.168.9.0/24       18           2026-10-15T19:40:02Z
local                default              8            2026-10-12T11:05:44Z

Total profiles found: 3
To pull a profile: ./bin/local/gdc-node-ops.sh pull-profile --name <name>
```

#### Pull & Backup Output:
```text
[-] Fetching profile 'honeywell' from https://gdc-companion.gdc-labs.com/v1/iso-profiles/honeywell?format=env...
[x] Existing profile detected. Backed up to: src/build/.backups/honeywell.env.20261016-143022
[x] Successfully synchronized profile to: src/build/honeywell.env
```

---

## 5. Security & Invariant Guarantees (EARS Constraints)

- **Input Sanitization (EARS-1):** When `--name` is provided, the script shall validate that the string matches `^[a-zA-Z0-9_-]+$`. If any path-traversal character (`/`, `\`, `..`) is present, the script shall reject execution and exit with returncode `1`.
- **Atomic Mutation (EARS-2):** While downloading upstream payloads, the script shall write exclusively to an unprivileged temporary staging file in `/tmp`.
- **Pre-condition Verification (EARS-3):** If the upstream HTTP response status code is not `200`, then the script shall purge the temporary staging file without altering or creating any file in `src/build/`.
- **Backup Integrity (EARS-4):** When `src/build/{name}.env` already exists and HTTP status is `200`, the script shall create a non-destructive timestamped snapshot in `src/build/.backups/{name}.env.$(date +%Y%m%d-%H%M%S)` before replacing the active file.
- **Credential Protection (EARS-5):** The script shall never log the `INSTALL_COMPANION_API_KEY` or `--api-key` value to stdout or stderr.

---

## 6. Verification & Test Plan

1. **Unit / Integration Tests (`test/test_pull_profile_cli.py`):**
   - Test profile discovery listing when `--name` is omitted.
   - Test successful pull and atomic creation when target file does not exist locally.
   - Test backup creation in `src/build/.backups/` when target file already exists locally.
   - Test abort and zero-mutation when upstream server returns `404 Not Found`.
   - Test abort and zero-mutation when upstream server returns `401 Unauthorized`.
   - Test abort when invalid characters or path traversal strings (`../evil`) are supplied to `--name`.
   - Test precedence of CLI flags over environment variables and `local.env`.
2. **End-to-End Compatibility:**
   - Sourcing the pulled `.env` file into `build.sh -e <profile>` operates cleanly without syntax errors or unexpected variable contamination.
