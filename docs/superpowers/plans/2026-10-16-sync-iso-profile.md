# Pull & Synchronize ISO Profiles from GDC Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull down and synchronize centralized ISO environment profiles from GDC Companion into `src/build/{name}.env` with automated versioned backups in `src/build/.backups/` and non-destructive atomic promotion.

**Architecture:** Implement `cmd_pull_profile` as a native subcommand in `bin/local/gdc-node-ops.sh`. Downloads are staged into an isolated temporary file via `mktemp` and strictly gated on an HTTP 200 response from GDC Companion. If verified and a local profile exists, an automated timestamped backup is generated under `src/build/.backups/` before atomically promoting the staged profile. If `--name` is omitted, the command queries `GET /v1/iso-profiles` and formats a discovery table.

**Tech Stack:** Bash (`curl`, `mktemp`, `jq`), Python 3 (`pytest`, `http.server`, `unittest`)

---

## File Structure

- **Modify:** `bin/local/gdc-node-ops.sh`
  - Register `pull-profile` in main `usage()` synopsis and command router.
  - Implement `cmd_pull_profile` with flag parsing (`--name`, `--companion-url`, `--api-key`, `--list`), remote discovery tabular formatting, input sanitization, staging download, HTTP 200 validation, backup creation, and atomic promotion.
- **Create:** `test/test_pull_profile_cli.py`
  - Mock HTTP server fixture simulating GDC Companion endpoints (`GET /v1/iso-profiles` and `GET /v1/iso-profiles/{name}?format=env`).
  - Unit and integration tests covering all 5 BDD scenarios from `docs/stories/STORY-001-sync-iso-profile-from-companion.md`.

---

## Tasks

### Task 1: CLI Synopsis & Help Integration

**Files:**
- Modify: `bin/local/gdc-node-ops.sh:21-40`
- Create: `test/test_pull_profile_cli.py`

- [ ] **Step 1: Write the failing test for help menu and command discovery**

Create `test/test_pull_profile_cli.py` with:
```python
import subprocess
import os
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLI_PATH = os.path.join(REPO_ROOT, "bin/local/gdc-node-ops.sh")

class TestPullProfileCLIHelp(unittest.TestCase):
    def test_main_help_includes_pull_profile(self):
        result = subprocess.run([CLI_PATH, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("pull-profile", result.stdout)
        self.assertIn("Pull or list ISO environment profiles from GDC Companion", result.stdout)

    def test_pull_profile_subcommand_help(self):
        result = subprocess.run([CLI_PATH, "pull-profile", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("--name", result.stdout)
        self.assertIn("--companion-url", result.stdout)
        self.assertIn("--api-key", result.stdout)
        self.assertIn("--list", result.stdout)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_pull_profile_cli.py -v`  
Expected: FAIL with `AssertionError: 'pull-profile' not found in result.stdout`

- [ ] **Step 3: Update `bin/local/gdc-node-ops.sh` usage and command dispatch**

In `bin/local/gdc-node-ops.sh`, update `usage()` to include `pull-profile`:
```bash
usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Unified GDC Node Operations CLI for managing, updating, and recovering edge nodes.

Commands:
  pull-profile       Pull or list ISO environment profiles from GDC Companion
  push-facts         Inject manual facts JSON into node, reset Stage 5, and restart provisioner
  push-playbook      Deploy local ansible playbook updates to node Gitea repository
  push-token         Push GCP bearer token into node containerd and runtime auth directories
  rotate-token       Force execution of refresh-gdc-credentials.sh and verify token rotation
  reset-pxe          Schedule one-time UEFI PXE boot and reboot target nodes
  refresh-telemetry  Force gdc-collector diagnostics refresh and push payload to Companion

Run '$(basename "$0") <command> --help' for detailed options on any command.
EOF
    exit "${1:-0}"
}
```

Add the command dispatcher in the main dispatch `case "$1"` block:
```bash
        pull-profile)
            cmd_pull_profile "$@"
            ;;
```

And define the initial skeleton of `cmd_pull_profile` with help handling:
```bash
cmd_pull_profile() {
    pull_profile_usage() {
        cat <<EOF
Usage: $(basename "$0") pull-profile [OPTIONS]

Pull down or list centralized ISO environment profiles hosted in GDC Companion.

Options:
  --name <NAME>         Name of the ISO profile to pull (e.g. honeywell, barn, local)
  --companion-url <URL> Base URL of GDC Companion (default: https://gdc-companion.gdc-labs.com/)
  --api-key <KEY>       API key for GDC Companion authentication
  --list                List available profiles without pulling
  -h, --help            Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                pull_profile_usage 0
                ;;
            *)
                shift
                ;;
        esac
    done
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test/test_pull_profile_cli.py -v`  
Expected: PASS (2 tests passing)

- [ ] **Step 5: Commit changes**

```bash
git add bin/local/gdc-node-ops.sh test/test_pull_profile_cli.py
git commit -m "feat(cli): scaffold pull-profile subcommand in gdc-node-ops.sh"
```

---

### Task 2: Profile Discovery & Remote Listing (`--list` or Omitted `--name`)

**Files:**
- Modify: `bin/local/gdc-node-ops.sh`
- Modify: `test/test_pull_profile_cli.py`

- [ ] **Step 1: Write failing test with Python mock HTTP server**

Add `TestPullProfileListing` to `test/test_pull_profile_cli.py`:
```python
import http.server
import json
import threading

class MockCompanionHandler(http.server.BaseHTTPRequestHandler):
    profiles_data = [
        {
            "name": "barn",
            "network_segment": "192.168.20.0/24",
            "description": "Barn edge lab environment",
            "override_count": 14,
            "updated_at": "2026-10-14T08:22:10Z"
        },
        {
            "name": "honeywell",
            "network_segment": "192.168.9.0/24",
            "description": "Honeywell cluster profile",
            "override_count": 18,
            "updated_at": "2026-10-15T19:40:02Z"
        }
    ]

    def do_GET(self):
        if self.path == "/v1/iso-profiles":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(self.profiles_data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

class TestPullProfileListing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockCompanionHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_list_profiles_when_name_omitted(self):
        companion_url = f"http://127.0.0.1:{self.port}"
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--companion-url", companion_url],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("AVAILABLE ISO PROFILES", result.stdout)
        self.assertIn("barn", result.stdout)
        self.assertIn("192.168.20.0/24", result.stdout)
        self.assertIn("honeywell", result.stdout)
        self.assertIn("192.168.9.0/24", result.stdout)
        self.assertIn("Total profiles found: 2", result.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_pull_profile_cli.py -k test_list_profiles_when_name_omitted -v`  
Expected: FAIL with missing table and output assertions.

- [ ] **Step 3: Implement remote profile listing logic in `cmd_pull_profile`**

In `bin/local/gdc-node-ops.sh`, update `cmd_pull_profile`:
```bash
cmd_pull_profile() {
    local profile_name=""
    local companion_url=""
    local api_key=""
    local force_list=false

    if [ -f "$REPO_ROOT/src/build/local.env" ]; then
        # shellcheck disable=SC1091
        source "$REPO_ROOT/src/build/local.env"
    fi

    local default_base="${INSTALL_COMPANION_BASE:-https://gdc-companion.gdc-labs.com/}"
    [[ "${default_base}" != */ ]] && default_base="${default_base}/"
    companion_url="${default_base}"
    api_key="${INSTALL_COMPANION_API_KEY:-}"

    pull_profile_usage() {
        cat <<EOF
Usage: $(basename "$0") pull-profile [OPTIONS]

Pull down or list centralized ISO environment profiles hosted in GDC Companion.

Options:
  --name <NAME>         Name of the ISO profile to pull (e.g. honeywell, barn, local)
  --companion-url <URL> Base URL of GDC Companion (default: $companion_url)
  --api-key <KEY>       API key for GDC Companion authentication
  --list                List available profiles without pulling
  -h, --help            Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --name)
                profile_name="$2"
                shift 2
                ;;
            --companion-url)
                companion_url="$2"
                shift 2
                ;;
            --api-key)
                api_key="$2"
                shift 2
                ;;
            --list)
                force_list=true
                shift
                ;;
            -h|--help)
                pull_profile_usage 0
                ;;
            *)
                shift
                ;;
        esac
    done

    [[ "${companion_url}" != */ ]] && companion_url="${companion_url}/"

    local auth_header=()
    if [[ -n "${api_key}" ]]; then
        auth_header=(-H "X-API-Key: ${api_key}")
    fi

    if [[ -z "${profile_name}" || "${force_list}" == "true" ]]; then
        echo "[-] Fetching available ISO profiles from ${companion_url}v1/iso-profiles..."
        local response_body
        local http_code
        response_body=$(curl -sS -w "\n%{http_code}" "${auth_header[@]}" "${companion_url}v1/iso-profiles" 2>/dev/null || true)
        http_code=$(echo "${response_body}" | tail -n1)
        local json_payload
        json_payload=$(echo "${response_body}" | sed '$d')

        if [[ "${http_code}" != "200" ]]; then
            echo "[!] Error: Failed to fetch profile listing from GDC Companion (HTTP ${http_code})." >&2
            exit 1
        fi

        echo ""
        echo "AVAILABLE ISO PROFILES (${companion_url}):"
        printf "%-20s %-20s %-12s %s\n" "NAME" "NETWORK SEGMENT" "OVERRIDES" "LAST UPDATED"
        echo "--------------------------------------------------------------------------------"
        
        local count=0
        if command -v jq >/dev/null 2>&1; then
            while IFS=$'\t' read -r p_name p_segment p_count p_updated; do
                [[ -z "${p_name}" ]] && continue
                printf "%-20s %-20s %-12s %s\n" "${p_name}" "${p_segment}" "${p_count}" "${p_updated}"
                ((count++))
            done < <(echo "${json_payload}" | jq -r '.[] | [ .name, .network_segment, (.override_count|tostring), (.updated_at // "N/A") ] | @tsv')
        else
            echo "${json_payload}"
        fi

        echo ""
        echo "Total profiles found: ${count}"
        echo "To pull a profile: $(basename "$0") pull-profile --name <name>"
        return 0
    fi
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_pull_profile_cli.py -k test_list_profiles_when_name_omitted -v`  
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add bin/local/gdc-node-ops.sh test/test_pull_profile_cli.py
git commit -m "feat(cli): implement profile listing and discovery in pull-profile"
```

---

### Task 3: Profile Pull, Staging, Validation Gate, and Atomic Backup

**Files:**
- Modify: `bin/local/gdc-node-ops.sh`
- Modify: `test/test_pull_profile_cli.py`

- [ ] **Step 1: Write failing tests for download, error gating, and backup creation**

Extend `MockCompanionHandler` in `test/test_pull_profile_cli.py` to handle `/v1/iso-profiles/honeywell?format=env` returning 200, and `/v1/iso-profiles/error-profile?format=env` returning 500, plus tests:
```python
import shutil

class TestPullProfileDownload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/v1/iso-profiles/honeywell?format=env":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"# ISO Build Profile: honeywell\nBOOTSTRAP_MACHINE_IP_CIDR=192.168.9.11/24\n")
                elif self.path == "/v1/iso-profiles/notfound?format=env":
                    self.send_response(404)
                    self.end_headers()
                elif self.path == "/v1/iso-profiles/unauth?format=env":
                    self.send_response(401)
                    self.end_headers()
                else:
                    self.send_response(500)
                    self.end_headers()
            def log_message(self, format, *args):
                pass

        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.test_build_dir = os.path.join(REPO_ROOT, "src/build")
        self.honeywell_file = os.path.join(self.test_build_dir, "test_dummy.env")
        self.backup_dir = os.path.join(self.test_build_dir, ".backups")

    def tearDown(self):
        if os.path.exists(self.honeywell_file):
            os.remove(self.honeywell_file)
        if os.path.exists(self.backup_dir):
            shutil.rmtree(self.backup_dir)

    def test_invalid_profile_name_traversal_rejected(self):
        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "../etc/passwd"],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid profile name", result.stderr)

    def test_pull_existing_creates_backup_and_updates(self):
        with open(self.honeywell_file, "w") as f:
            f.write("OLD_CONFIG=true\n")

        companion_url = f"http://127.0.0.1:{self.port}"
        # We query honeywell upstream but target test_dummy profile by using test_dummy name with mock routing
        # Or test pull-profile --name honeywell:
        target_file = os.path.join(self.test_build_dir, "honeywell.env")
        orig_content = None
        if os.path.exists(target_file):
            with open(target_file, "r") as f:
                orig_content = f.read()

        try:
            with open(target_file, "w") as f:
                f.write("ORIGINAL_HONEYWELL=1\n")

            result = subprocess.run(
                [CLI_PATH, "pull-profile", "--name", "honeywell", "--companion-url", companion_url],
                capture_output=True,
                text=True
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("Backed up to: src/build/.backups/honeywell.env.", result.stdout)
            self.assertIn("Successfully synchronized profile to: src/build/honeywell.env", result.stdout)

            with open(target_file, "r") as f:
                new_content = f.read()
            self.assertIn("BOOTSTRAP_MACHINE_IP_CIDR=192.168.9.11/24", new_content)

            backups = os.listdir(self.backup_dir)
            self.assertTrue(any(b.startswith("honeywell.env.") for b in backups))
        finally:
            if orig_content is not None:
                with open(target_file, "w") as f:
                    f.write(orig_content)
            elif os.path.exists(target_file):
                os.remove(target_file)

    def test_pull_nonexistent_upstream_aborts_without_modifying_local(self):
        companion_url = f"http://127.0.0.1:{self.port}"
        target_file = os.path.join(self.test_build_dir, "notfound.env")
        if os.path.exists(target_file):
            os.remove(target_file)

        result = subprocess.run(
            [CLI_PATH, "pull-profile", "--name", "notfound", "--companion-url", companion_url],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP 404", result.stderr)
        self.assertFalse(os.path.exists(target_file))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_pull_profile_cli.py -k TestPullProfileDownload -v`  
Expected: FAIL

- [ ] **Step 3: Implement validation, staging, backup, and atomic promotion**

In `bin/local/gdc-node-ops.sh`, append download handling to `cmd_pull_profile`:
```bash
    # Input validation: only alphanumeric, dashes, and underscores
    if [[ ! "${profile_name}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        echo "[!] Error: Invalid profile name '${profile_name}'. Must contain only alphanumeric characters, dashes, and underscores." >&2
        exit 1
    fi

    local target_file="${REPO_ROOT}/src/build/${profile_name}.env"
    local fetch_url="${companion_url}v1/iso-profiles/${profile_name}?format=env"
    echo "[-] Fetching profile '${profile_name}' from ${fetch_url}..."

    local staging_tmp
    staging_tmp=$(mktemp "/tmp/iso-profile.XXXXXX")
    trap 'rm -f "${staging_tmp}" 2>/dev/null || true' EXIT

    local http_code
    http_code=$(curl -sS -w "%{http_code}" "${auth_header[@]}" -o "${staging_tmp}" "${fetch_url}" 2>/dev/null || echo "000")

    if [[ "${http_code}" != "200" ]]; then
        rm -f "${staging_tmp}"
        case "${http_code}" in
            401|403)
                echo "[!] Error: Authentication failed with GDC Companion (HTTP ${http_code}). Check your API key." >&2
                ;;
            404)
                echo "[!] Error: ISO profile '${profile_name}' not found on GDC Companion (HTTP 404)." >&2
                ;;
            000)
                echo "[!] Error: Failed to connect to GDC Companion at ${companion_url} (network timeout or connection refused)." >&2
                ;;
            *)
                echo "[!] Error: Upstream request failed with HTTP ${http_code}." >&2
                ;;
        esac
        exit 1
    fi

    # Backup existing profile if present
    if [[ -f "${target_file}" ]]; then
        local backup_dir="${REPO_ROOT}/src/build/.backups"
        mkdir -p "${backup_dir}"
        local ts
        ts=$(date +%Y%m%d-%H%M%S)
        local backup_file="${backup_dir}/${profile_name}.env.${ts}"
        cp "${target_file}" "${backup_file}"
        echo "[x] Existing profile detected. Backed up to: src/build/.backups/${profile_name}.env.${ts}"
    fi

    # Atomically install fetched profile
    mv "${staging_tmp}" "${target_file}"
    chmod 0644 "${target_file}"
    echo "[x] Successfully synchronized profile to: src/build/${profile_name}.env"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_pull_profile_cli.py -v`  
Expected: PASS (all tests passing)

- [ ] **Step 5: Commit changes**

```bash
git add bin/local/gdc-node-ops.sh test/test_pull_profile_cli.py
git commit -m "feat(cli): complete pull-profile atomic download and backup pipeline"
```

---

### Task 4: Complete Suite Verification & Regression Check

**Files:**
- Modify: `bin/local/gdc-node-ops.sh` (if any syntax/shellcheck issues arise)
- Test: All tests in `test/`

- [ ] **Step 1: Run ShellCheck on `gdc-node-ops.sh`**

Run: `shellcheck -e SC1091 bin/local/gdc-node-ops.sh`  
Expected: Clean exit (0 errors/warnings)

- [ ] **Step 2: Run all CLI regression tests**

Run: `pytest test/test_cli_help_consistency.py test/test_pull_profile_cli.py -v`  
Expected: PASS

- [ ] **Step 3: End-to-end dry run verification**

Execute:
```bash
./bin/local/gdc-node-ops.sh pull-profile --help
```
Verify output is properly aligned and clean.

- [ ] **Step 4: Final commit**

```bash
git add bin/local/gdc-node-ops.sh docs/
git commit -m "docs: finalize pull-profile design, story, and implementation plan"
```
