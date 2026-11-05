# Multi-Mode Companion Source Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement resilient multi-mode companion schema resolution supporting local filesystem, cloud HTTP, and hermetic offline modes controlled by `GDC_COMPANION_SOURCE`.

**Architecture:** A unified helper module `test/lib/companion_source.py` determines mode, emits display-only warnings when unconfigured, and manages schema retrieval via local files or `/v1/schema/{name}` endpoints. Unit tests in `test/test_manual_facts_schema.py` and `test/bin/sync-schemas.sh` consume this helper.

**Tech Stack:** Python 3.8+, `urllib.request`, `unittest`, Bash.

---

### File Structure Map
- Create: `test/lib/companion_source.py` — Central mode resolver, display logger, and schema fetcher.
- Create: `test/lib/__init__.py` — Package initialization for test libraries.
- Create: `test/test_companion_source.py` — Unit test suite verifying all resolver modes and logging behaviors.
- Modify: `test/test_manual_facts_schema.py` — Refactor divergence test and sync script test to consume `CompanionSourceResolver`.
- Modify: `test/bin/sync-schemas.sh` — Add `--source` flag and wire into `companion_source.py`.

---

### Task 1: Create `test/lib/companion_source.py` with Test-Driven Development

**Files:**
- Create: `test/lib/__init__.py`
- Create: `test/test_companion_source.py`
- Create: `test/lib/companion_source.py`

- [x] **Step 1: Create `test/lib/__init__.py`**

```python
# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
```

- [x] **Step 2: Write failing tests in `test/test_companion_source.py`**

```python
# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Ensure test/lib is on path
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)

from lib.companion_source import (
    CompanionMode,
    CompanionSourceResolver,
    SCHEMA_ROUTE_MAP,
)

class TestCompanionSourceResolver(unittest.TestCase):
    def test_mode_unset_emits_display_error_and_returns_offline(self):
        with patch.dict(os.environ, {}, clear=True):
            stderr_capture = io.StringIO()
            with patch("sys.stderr", stderr_capture):
                resolver = CompanionSourceResolver()
                mode = resolver.get_mode()
            self.assertEqual(mode, CompanionMode.OFFLINE)
            self.assertIn("[ERROR]", stderr_capture.getvalue())
            self.assertIn("GDC_COMPANION_SOURCE environment variable is not defined", stderr_capture.getvalue())

    def test_mode_none_emits_info_and_returns_offline(self):
        for val in ["none", "disabled", "offline"]:
            with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": val}, clear=True):
                stdout_capture = io.StringIO()
                with patch("sys.stdout", stdout_capture):
                    resolver = CompanionSourceResolver()
                    mode = resolver.get_mode()
                self.assertEqual(mode, CompanionMode.OFFLINE)
                self.assertIn("[INFO]", stdout_capture.getvalue())
                self.assertIn("Operating in hermetic/offline mode", stdout_capture.getvalue())

    def test_mode_local_fs_valid_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = os.path.join(tmpdir, "docs")
            os.makedirs(docs_dir)
            with open(os.path.join(docs_dir, "machine-schema.json"), "w") as f:
                json.dump({"title": "MachineSchema"}, f)

            with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": tmpdir}, clear=True):
                resolver = CompanionSourceResolver()
                self.assertEqual(resolver.get_mode(), CompanionMode.LOCAL_FS)
                schema = resolver.fetch_upstream_schema("machine-schema.json")
                self.assertEqual(schema.get("title"), "MachineSchema")

    def test_mode_local_fs_missing_dir_raises_error(self):
        with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": "/nonexistent/path/gdc-companion"}, clear=True):
            resolver = CompanionSourceResolver()
            self.assertEqual(resolver.get_mode(), CompanionMode.LOCAL_FS)
            with self.assertRaises(FileNotFoundError):
                resolver.fetch_upstream_schema("machine-schema.json")

    @patch("urllib.request.urlopen")
    def test_mode_cloud_http_valid_endpoint(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"title": "RemoteMachineSchema"}).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": "https://gdc-companion.ensor-labs.com"}, clear=True):
            resolver = CompanionSourceResolver()
            self.assertEqual(resolver.get_mode(), CompanionMode.CLOUD_HTTP)
            schema = resolver.fetch_upstream_schema("machine-schema.json")
            self.assertEqual(schema.get("title"), "RemoteMachineSchema")
            # Verify called url
            called_url = mock_urlopen.call_args[0][0].full_url
            self.assertEqual(called_url, "https://gdc-companion.ensor-labs.com/v1/schema/machine")

if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest test/test_companion_source.py`
Expected: `ModuleNotFoundError: No module named 'lib.companion_source'`

- [x] **Step 4: Implement `test/lib/companion_source.py`**

```python
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Resolver and fetcher for multi-mode gdc-companion schema integration."""

import enum
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, Tuple, List

class CompanionMode(enum.Enum):
    OFFLINE = "offline"
    LOCAL_FS = "local_fs"
    CLOUD_HTTP = "cloud_http"

SCHEMA_ROUTE_MAP = {
    "machine-schema.json": "/v1/schema/machine",
    "report-schema.json": "/v1/schema/report",
    "build-report-schema.json": "/v1/schema/build-report",
}

class CompanionSourceResolver:
    """Resolves and fetches schemas from local filesystem, cloud HTTP, or offline modes."""

    def __init__(self, source: Optional[str] = None):
        if source is None:
            source = os.environ.get("GDC_COMPANION_SOURCE")
        self.raw_source = source
        self.mode = self._determine_mode()

    def _determine_mode(self) -> CompanionMode:
        if self.raw_source is None or self.raw_source.strip() == "":
            sys.stderr.write(
                "\033[91m[ERROR] GDC_COMPANION_SOURCE environment variable is not defined. "
                "Defaulting to hermetic/offline mode (skipping upstream schema synchronization).\033[0m\n"
            )
            return CompanionMode.OFFLINE

        normalized = self.raw_source.strip()
        if normalized.lower() in ("none", "disabled", "offline"):
            sys.stdout.write(
                f"[INFO] GDC_COMPANION_SOURCE is set to '{normalized}'. Operating in hermetic/offline mode.\n"
            )
            return CompanionMode.OFFLINE

        if normalized.startswith("http://") or normalized.startswith("https://"):
            sys.stdout.write(
                f"[INFO] Companion source resolved to cloud HTTP endpoint: {normalized}\n"
            )
            return CompanionMode.CLOUD_HTTP

        sys.stdout.write(
            f"[INFO] Companion source resolved to local filesystem: {normalized}\n"
        )
        return CompanionMode.LOCAL_FS

    def get_mode(self) -> CompanionMode:
        return self.mode

    def fetch_upstream_schema(self, schema_name: str) -> Optional[Dict[str, Any]]:
        if self.mode == CompanionMode.OFFLINE:
            return None

        if self.mode == CompanionMode.LOCAL_FS:
            base_dir = os.path.abspath(self.raw_source.strip())
            if not os.path.isdir(base_dir):
                raise FileNotFoundError(f"Configured companion directory '{base_dir}' does not exist.")
            schema_path = os.path.join(base_dir, "docs", schema_name)
            if not os.path.isfile(schema_path):
                raise FileNotFoundError(f"Upstream schema '{schema_path}' not found.")
            with open(schema_path, "r", encoding="utf-8") as f:
                return json.load(f)

        if self.mode == CompanionMode.CLOUD_HTTP:
            base_url = self.raw_source.strip().rstrip("/")
            endpoint = SCHEMA_ROUTE_MAP.get(schema_name, f"/v1/schema/{schema_name.replace('.json', '')}")
            target_url = f"{base_url}{endpoint}"
            req = urllib.request.Request(
                target_url,
                headers={"Accept": "application/json", "User-Agent": "gdc-disk-provisioner-sync/1.0"}
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                # If /v1/schema/{name} gives 404, fallback to /docs/{schema_name}
                if e.code == 404:
                    fallback_url = f"{base_url}/docs/{schema_name}"
                    req_fallback = urllib.request.Request(
                        fallback_url,
                        headers={"Accept": "application/json", "User-Agent": "gdc-disk-provisioner-sync/1.0"}
                    )
                    with urllib.request.urlopen(req_fallback, timeout=5) as resp_fallback:
                        return json.loads(resp_fallback.read().decode("utf-8"))
                raise
```

- [x] **Step 5: Run unit tests to verify they pass**

Run: `python3 -m unittest test/test_companion_source.py`
Expected: `Ran 5 tests in ...s - OK`

---

### Task 2: Refactor `test/test_manual_facts_schema.py`

**Files:**
- Modify: `test/test_manual_facts_schema.py`

- [x] **Step 1: Update imports and schema path constants in `test/test_manual_facts_schema.py`**
  - Import `CompanionSourceResolver` and `CompanionMode`.
  - Remove hardcoded `DEFAULT_SCHEMA_PATH = "/d/projects/google/gdc-companion/docs/machine-schema.json"`.
  - Remove hardcoded `FALLBACK_SCHEMA_PATH`.
  - Set `SCHEMA_PATH = REPO_SCHEMA_PATH` (or env `GDC_SCHEMA_PATH`).

- [x] **Step 2: Update `test_no_divergence_from_upstream_companion`**
  - Use `resolver = CompanionSourceResolver()`.
  - If `resolver.get_mode() == CompanionMode.OFFLINE`: call `self.skipTest(...)`.
  - Else: fetch upstream with `resolver.fetch_upstream_schema("machine-schema.json")` and compare.

- [x] **Step 3: Update `test_sync_schemas_script`**
  - If `resolver.get_mode() in (CompanionMode.LOCAL_FS, CompanionMode.CLOUD_HTTP)`: run `--check`.
  - In `OFFLINE` mode: skip `--check`.

- [x] **Step 4: Run unit tests in test_manual_facts_schema.py**

Run: `env -u GDC_COMPANION_SOURCE python3 -m unittest test/test_manual_facts_schema.py`
Expected: Displays `[ERROR]` banner, `test_no_divergence_from_upstream_companion` skips, all 6 tests pass.

---

### Task 3: Refactor `test/bin/sync-schemas.sh`

**Files:**
- Modify: `test/bin/sync-schemas.sh`

- [x] **Step 1: Wire `--source <SOURCE>` and `$GDC_COMPANION_SOURCE`**
  - Support `--source <PATH|URL|none>`.
  - When mode is `OFFLINE`:
    - If `--check`: exit 0 with notice that divergence check is skipped.
    - If sync: exit 0 with notice that no remote companion is configured.
  - When mode is `LOCAL_FS` or `CLOUD_HTTP`:
    - Call helper python command using `CompanionSourceResolver` to fetch schemas and write to `docs/*.json`.

- [x] **Step 2: Verify `sync-schemas.sh` with `--help` and `--check`**

Run:
```bash
./test/bin/sync-schemas.sh --help
./test/bin/sync-schemas.sh --check --source none
```
Expected:
`--help` outputs help. `--check --source none` outputs offline notice and exits 0.

---

### Task 4: End-to-End Verification Across All 3 Scenarios

- [x] **Step 1: Test Scenario 3A (Unset / Hermetic)**
Run: `env -u GDC_COMPANION_SOURCE python3 -m unittest test/test_manual_facts_schema.py`
Expected: Visual `[ERROR]` log shown, tests pass cleanly.

- [x] **Step 2: Test Scenario 3B (Explicit none)**
Run: `GDC_COMPANION_SOURCE=none python3 -m unittest test/test_manual_facts_schema.py`
Expected: `[INFO]` log shown, tests pass cleanly.

- [x] **Step 3: Test Scenario 1 (Local filesystem)**
Run: `GDC_COMPANION_SOURCE=/d/projects/google/gdc-companion ./test/bin/sync-schemas.sh`
Run: `GDC_COMPANION_SOURCE=/d/projects/google/gdc-companion python3 -m unittest test/test_manual_facts_schema.py`
Expected: Schemas synchronize from local folder, tests pass with 0 divergence.

- [x] **Step 4: Run full project unit test suite**
Run: `python3 -m unittest discover -s test`
Expected: All tests pass.

- [x] **Step 5: Run `./build.sh --env honeywell` pre-flight**
Run: `./build.sh --env honeywell --skip-increment` (or ctrl-c before cloud build)
Expected: Pre-flight gates 1/2 and 2/2 pass without failure.
