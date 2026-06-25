# Hermetic Agent Playbook: Performing GitLab Merge Request Reviews

This document defines the strict, mathematically isolated guidelines and operational rules for an AI Agent assigned to perform a code review on a GitLab Merge Request. These steps guarantee that the review is hermetic, reproducible, and completely free of cross-talk or taint from the parent workspace.

---

## 1. Sandbox Initialization Workflow

To prevent local workspace files (such as non-checked-in `.envrc` variables or active development caches) from contaminating the review, the reviewing Agent must clone and initialize an isolated workspace.

Execute these commands from the parent repository directory:

```bash
# 1. Clone the parent repository locally into the git-ignored review sandbox
git clone . .review/

# 2. Enter the isolated sandbox directory
cd .review/

# 3. Pull the exact, un-tainted candidates and branch state from GitLab using the MR ID
glab mr checkout <MERGE_REQUEST_ID>
```

---

## 2. Hard Isolation Boundaries

To maintain absolute cryptographic and filesystem boundaries, the reviewing Agent must strictly adhere to the following rules:

1. **Universe Boundary:** The reviewing Agent must treat `.review/` as the absolute system root folder of its workspace. File system operations (reading, writing, editing, or finding files) outside of `.review/` are strictly prohibited.
2. **Independence of Caches:** The sandbox must not reuse, symlink, or reference any existing parent directories like `.venv/` or `.cache/` (e.g. cached ISOs or third-party packages). 
3. **Hermetic Environment Sourcing:** All scripts, dependencies, build environments, and test suites must be initialized and run completely from within `.review/`.

---

## 3. Systematic Review Checklist

Once inside the sandbox and checked out on the Merge Request branch, the Agent must perform the following validation gates:

### Gate A: Static Pre-Flight Validations
Verify that all static checks, YAML parsers, and schema validation gates compile and pass cleanly on their own merits:
```bash
# Run the core validation suite inside the sandbox
./test/validate_iso_static.sh
```
*The Agent must assert that both the Cloud-Init user-data schema and Netplan configuration layout pass verification without any syntax errors.*

### Gate B: Dynamic LVM and Dependency Checks
Verify that the `Makefile` validation pipeline compiled successfully:
```bash
make -C src/build validate
```
This target verifies:
1. Shell script integrity via `shellcheck`.
2. Python compilation checks on `render_templates.py`.
3. Systemd service header boundaries via `systemd-analyze`.

### Gate C: Diff Inspection
Identify all files modified as part of the Merge Request. Analyze changed lines for:
* **Conventional Conformance:** Do change patterns match existing codebase layouts and architectural guidelines?
* **Resource Leaks or Security Risks:** Ensure no private credentials, keys, or endpoints are exposed.
* **Variable Hardcodings:** Verify that no dynamic properties are hardcoded (for example, assuring dynamic physical interface placeholders are used instead of assuming static interfaces like `eth0`).

---

## 4. Report Generation & Sign-off

Upon completing the verification, the reviewing Agent must write a structured report with its findings containing:

1. **Workspace Proof:** Conformation that the review was run headlessly inside `.review/` and successfully validated.
2. **Gate Results Table:** A checklist showing the status (PASS/FAIL) of all validation gates.
3. **Change Log Assessment:** Verification of Conventional Commits conformance in the commit log of the MR.
4. **Approval Recommendation:** A clear binary recommendation (Approve/Reject) with direct action points if any corrective steps are needed.
