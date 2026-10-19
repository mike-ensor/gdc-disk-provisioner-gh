# STORY-001: Synchronize ISO Profiles from Centralized GDC Companion

**Story ID:** `STORY-001`  
**Title:** Pull and Synchronize ISO Environment Profiles from GDC Companion  
**Status:** `Draft`  
**Priority:** High  
**Actor:** Infrastructure Engineer / Release Operator / CI Runner  
**Related Spec:** `docs/superpowers/specs/2026-10-16-sync-iso-profile-design.md`  

---

## 1. Story Statement

**As an** Infrastructure Engineer preparing bare-metal installation media,  
**I want to** pull down a designated ISO environment profile directly from `gdc-companion` using `gdc-node-ops.sh pull-profile`,  
**So that** I have a single source of truth for deployment overrides without manual copy-pasting, while preserving existing local configurations with automated versioned backups.

---

## 2. Trigger

The operator executes:
```bash
./bin/local/gdc-node-ops.sh pull-profile --name <profile_name>
```
or queries available remote profiles by executing:
```bash
./bin/local/gdc-node-ops.sh pull-profile
```

---

## 3. Acceptance Criteria (BDD / Gherkin)

### Scenario 1: Successful Pull of Existing Profile with Automated Backup (Happy Path)
```gherkin
Given a local profile file exists at "src/build/honeywell.env"
And GDC Companion has an ISO profile named "honeywell"
When the operator runs "./bin/local/gdc-node-ops.sh pull-profile --name honeywell"
Then the script fetches "https://gdc-companion.gdc-labs.com/v1/iso-profiles/honeywell?format=env"
And the HTTP response code is 200
And the previous "src/build/honeywell.env" is copied to "src/build/.backups/honeywell.env.<timestamp>"
And "src/build/honeywell.env" is atomically replaced with the fetched profile content
And the script outputs a confirmation message and exits with status 0
```

### Scenario 2: Successful Pull of a New Profile (No Prior Local File)
```gherkin
Given no file exists at "src/build/newlab.env"
And GDC Companion has an ISO profile named "newlab"
When the operator runs "./bin/local/gdc-node-ops.sh pull-profile --name newlab"
Then the script fetches the profile from GDC Companion
And the HTTP response code is 200
And "src/build/newlab.env" is created with the fetched content
And no file is created in "src/build/.backups/"
And the script exits with status 0
```

### Scenario 3: Discovery and Tabular Listing when `--name` is Omitted
```gherkin
Given GDC Companion has registered profiles ["barn", "honeywell", "local"]
When the operator runs "./bin/local/gdc-node-ops.sh pull-profile"
Then the script issues a GET request to "https://gdc-companion.gdc-labs.com/v1/iso-profiles"
And the response returns HTTP 200 with JSON profile summaries
And the script displays a formatted table listing the profile names, network segments, and update timestamps
And no files in "src/build/" or "src/build/.backups/" are created or modified
And the script exits with status 0
```

### Scenario 4: Upstream Failure or Non-200 Status Code (Error Gate)
```gherkin
Given a local profile file exists at "src/build/honeywell.env"
When the operator runs "./bin/local/gdc-node-ops.sh pull-profile --name nonexistent"
And GDC Companion returns HTTP 404 Not Found (or 401 Unauthorized / 500 Error)
Then the script writes an error message to stderr describing the failure and HTTP status code
And the local file "src/build/honeywell.env" remains completely untouched
And no file is created in "src/build/.backups/" or "src/build/"
And any temporary staging file is deleted
And the script exits with status 1
```

### Scenario 5: Input Validation & Path Traversal Prevention
```gherkin
When the operator runs "./bin/local/gdc-node-ops.sh pull-profile --name ../../../etc/passwd"
Then the script detects invalid characters in the profile name
And rejects execution immediately without sending any network request
And outputs an error indicating only alphanumeric characters, dashes, and underscores are permitted
And the script exits with status 1
```

---

## 4. System Invariants & Constraints (EARS)

- **Ubiquitous:** The `gdc-node-ops.sh pull-profile` command shall support `--companion-url` and `--api-key` flags to override default network endpoints.
- **Event-Driven:** When an existing `src/build/{name}.env` is present during an update, the system shall back up the existing file to `src/build/.backups/{name}.env.YYYYMMDD-HHMMSS` before updating the active file.
- **State-Driven:** While downloading the profile, the system shall stream the payload to an unprivileged temporary file (`mktemp`) and evaluate the HTTP response code prior to modifying any workspace file.
- **Unwanted Behavior:** If the upstream server responds with any HTTP status code other than 200, the system shall purge the temporary staging file and abort without modifying or creating any files in `src/build/`.
- **Constraint:** The system shall never expose or print API keys in stdout or console logs.

---

## 5. INVEST Assessment

| Dimension | Evaluation | Status |
|-----------|------------|--------|
| **Independent** | Can be implemented and verified directly within `gdc-node-ops.sh` using mock servers or existing companion endpoints. | PASS |
| **Negotiable** | Scoped strictly to profile retrieval and listing; future upload/push capabilities remain in backlog. | PASS |
| **Valuable** | Solves configuration drift and establishes GDC Companion as the central profile authority. | PASS |
| **Estimable** | Clear scope and well-defined API contract (`/v1/iso-profiles`). | PASS |
| **Small** | Fits cleanly in a single script subcommand and an automated test suite. | PASS |
| **Testable** | Verified with BDD scenarios via mocked curl/HTTP in Python tests. | PASS |

---

## 6. Definition of Done

- [ ] `cmd_pull_profile` implemented in `bin/local/gdc-node-ops.sh` with options `--name`, `--companion-url`, `--api-key`, `--list`.
- [ ] Usage menu in `gdc-node-ops.sh` updated to document `pull-profile`.
- [ ] Automated backup logic to `src/build/.backups/` verified with timestamps.
- [ ] Atomic file promotion via `mktemp` and HTTP 200 verification gate implemented.
- [ ] Test suite in `test/test_pull_profile_cli.py` covering all 5 BDD scenarios.
- [ ] All tests passing with `pytest`.
