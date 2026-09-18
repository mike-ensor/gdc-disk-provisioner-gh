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

"""Unit tests validating manual facts fixture against GDC machine schema."""

import json
import os
import unittest
import jsonschema

REPO_SCHEMA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../docs/machine-schema.json")
)
DEFAULT_SCHEMA_PATH = "/d/projects/google/gdc-companion/docs/machine-schema.json"
FALLBACK_SCHEMA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../gdc-companion/docs/machine-schema.json")
)
SCHEMA_PATH = os.environ.get(
    "GDC_SCHEMA_PATH",
    REPO_SCHEMA_PATH if os.path.exists(REPO_SCHEMA_PATH) else (
        DEFAULT_SCHEMA_PATH if os.path.exists(DEFAULT_SCHEMA_PATH) else FALLBACK_SCHEMA_PATH
    )
)
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

class TestManualFactsSchema(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(SCHEMA_PATH), f"Schema not found at {SCHEMA_PATH}")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_valid_manual_fact_fixture(self):
        valid_path = os.path.join(FIXTURES_DIR, "valid-gdc-fact-manual.json")
        self.assertTrue(os.path.exists(valid_path), f"Fixture missing: {valid_path}")
        with open(valid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Validate should not raise ValidationError
        jsonschema.validate(instance=data, schema=self.schema)

    def test_invalid_manual_fact_fixture(self):
        invalid_path = os.path.join(FIXTURES_DIR, "invalid-gdc-fact-manual.json")
        self.assertTrue(os.path.exists(invalid_path), f"Fixture missing: {invalid_path}")
        with open(invalid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=data, schema=self.schema)

    def test_no_divergence_from_upstream_companion(self):
        """Verifies local docs/machine-schema.json has not diverged from gdc-companion."""
        companion_schema = None
        for candidate in [
            os.environ.get("GDC_COMPANION_SCHEMA"),
            DEFAULT_SCHEMA_PATH,
            FALLBACK_SCHEMA_PATH,
        ]:
            if candidate and os.path.exists(candidate) and os.path.abspath(candidate) != REPO_SCHEMA_PATH:
                companion_schema = candidate
                break

        if not companion_schema:
            self.skipTest("Upstream gdc-companion not found on this system; skipping divergence check.")

        with open(companion_schema, "r", encoding="utf-8") as f:
            upstream_data = json.load(f)

        with open(REPO_SCHEMA_PATH, "r", encoding="utf-8") as f:
            local_data = json.load(f)

        # Ignore $comment if present
        upstream_cmp = {k: v for k, v in upstream_data.items() if k != "$comment"}
        local_cmp = {k: v for k, v in local_data.items() if k != "$comment"}

        self.assertEqual(
            local_cmp,
            upstream_cmp,
            f"Local schema '{REPO_SCHEMA_PATH}' has diverged from upstream '{companion_schema}'! "
            f"Run ./test/bin/sync-schemas.sh to synchronize."
        )

    def test_sync_schemas_script(self):
        """Tests test/bin/sync-schemas.sh --help and --check execution."""
        sync_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "bin/sync-schemas.sh"))
        self.assertTrue(os.path.exists(sync_script))
        self.assertTrue(os.access(sync_script, os.X_OK))

        import subprocess
        help_res = subprocess.run([sync_script, "--help"], capture_output=True, text=True)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn("--check", help_res.stdout)

        if os.path.exists(DEFAULT_SCHEMA_PATH) or os.path.exists(FALLBACK_SCHEMA_PATH):
            check_res = subprocess.run([sync_script, "--check"], capture_output=True, text=True)
            self.assertEqual(check_res.returncode, 0)
            self.assertIn("in sync", check_res.stdout)

if __name__ == "__main__":
    unittest.main()
