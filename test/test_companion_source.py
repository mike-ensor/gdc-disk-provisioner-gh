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

"""Unit tests verifying multi-mode CompanionSourceResolver functionality and routing."""

import email.message
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

# Ensure test directory and repository root are on sys.path
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TEST_DIR, ".."))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from test.lib.companion_source import (
        CompanionMode,
        CompanionSourceResolver,
        SCHEMA_ROUTE_MAP,
        SchemaParsingError,
    )
except ImportError:
    from lib.companion_source import (
        CompanionMode,
        CompanionSourceResolver,
        SCHEMA_ROUTE_MAP,
        SchemaParsingError,
    )


class TestCompanionSourceResolver(unittest.TestCase):
    """Test suite covering CompanionSourceResolver resolution modes and schema fetching."""

    def test_mode_unset_emits_display_error_and_returns_offline(self):
        """When GDC_COMPANION_SOURCE is unset, emit display-only ERROR and return OFFLINE."""
        with patch.dict(os.environ, {}, clear=True):
            stderr_capture = io.StringIO()
            with patch("sys.stderr", stderr_capture):
                resolver = CompanionSourceResolver()
                mode = resolver.get_mode()
            self.assertEqual(mode, CompanionMode.OFFLINE)
            captured = stderr_capture.getvalue()
            self.assertIn("[ERROR]", captured)
            self.assertIn(
                "[ERROR] GDC_COMPANION_SOURCE environment variable is not defined. "
                "Defaulting to hermetic/offline mode (skipping upstream schema synchronization).",
                captured,
            )
            self.assertIsNone(resolver.fetch_upstream_schema("machine-schema.json"))

    def test_mode_empty_string_emits_display_error_and_returns_offline(self):
        """When GDC_COMPANION_SOURCE is empty or whitespace, emit display-only ERROR and return OFFLINE."""
        for empty_val in ["", "   "]:
            with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": empty_val}, clear=True):
                stderr_capture = io.StringIO()
                with patch("sys.stderr", stderr_capture):
                    resolver = CompanionSourceResolver()
                    mode = resolver.get_mode()
                self.assertEqual(mode, CompanionMode.OFFLINE)
                captured = stderr_capture.getvalue()
                self.assertIn("[ERROR]", captured)
                self.assertIn(
                    "[ERROR] GDC_COMPANION_SOURCE environment variable is not defined. "
                    "Defaulting to hermetic/offline mode (skipping upstream schema synchronization).",
                    captured,
                )

    def test_mode_offline_keywords_emit_info_and_return_offline(self):
        """When GDC_COMPANION_SOURCE is 'none', 'disabled', or 'offline', return OFFLINE."""
        for val in ["none", "disabled", "offline", "NONE", "Offline"]:
            with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": val}, clear=True):
                stdout_capture = io.StringIO()
                with patch("sys.stdout", stdout_capture):
                    resolver = CompanionSourceResolver()
                    mode = resolver.get_mode()
                self.assertEqual(mode, CompanionMode.OFFLINE)
                captured = stdout_capture.getvalue()
                self.assertIn(
                    f"[INFO] GDC_COMPANION_SOURCE is set to '{val.strip()}'. Operating in hermetic/offline mode.",
                    captured,
                )
                self.assertIsNone(resolver.fetch_upstream_schema("machine-schema.json"))

    def test_mode_local_fs_valid_dir(self):
        """When GDC_COMPANION_SOURCE is a valid directory, return LOCAL_FS and read schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = os.path.join(tmpdir, "docs")
            os.makedirs(docs_dir)
            expected_schema = {"$schema": "http://json-schema.org/draft-07/schema#", "title": "TestSchema"}
            with open(os.path.join(docs_dir, "machine-schema.json"), "w", encoding="utf-8") as f:
                json.dump(expected_schema, f)

            with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": tmpdir}, clear=True):
                stdout_capture = io.StringIO()
                with patch("sys.stdout", stdout_capture):
                    resolver = CompanionSourceResolver()
                self.assertEqual(resolver.get_mode(), CompanionMode.LOCAL_FS)
                self.assertIn(
                    f"[INFO] Companion source resolved to local filesystem: {tmpdir}",
                    stdout_capture.getvalue(),
                )
                schema = resolver.fetch_upstream_schema("machine-schema.json")
                self.assertEqual(schema, expected_schema)

    def test_mode_local_fs_missing_dir_raises_file_not_found(self):
        """When GDC_COMPANION_SOURCE points to a non-existent dir, raise FileNotFoundError on fetch."""
        nonexistent_path = "/nonexistent/test/path/gdc-companion"
        with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": nonexistent_path}, clear=True):
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                resolver = CompanionSourceResolver()
            self.assertEqual(resolver.get_mode(), CompanionMode.LOCAL_FS)
            with self.assertRaises(FileNotFoundError):
                resolver.fetch_upstream_schema("machine-schema.json")

    def test_mode_local_fs_missing_schema_file_raises_file_not_found(self):
        """When GDC_COMPANION_SOURCE directory exists but schema file does not, raise FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = os.path.join(tmpdir, "docs")
            os.makedirs(docs_dir)
            with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": tmpdir}, clear=True):
                stdout_capture = io.StringIO()
                with patch("sys.stdout", stdout_capture):
                    resolver = CompanionSourceResolver()
                self.assertEqual(resolver.get_mode(), CompanionMode.LOCAL_FS)
                with self.assertRaises(FileNotFoundError):
                    resolver.fetch_upstream_schema("nonexistent-schema.json")

    @patch("urllib.request.urlopen")
    def test_mode_cloud_http_endpoints_and_routing(self, mock_urlopen):
        """When GDC_COMPANION_SOURCE is HTTP/HTTPS, return CLOUD_HTTP and query mapped routes."""
        test_routes = [
            ("machine-schema.json", "https://companion.example.com/v1/schema/machine"),
            ("report-schema.json", "https://companion.example.com/v1/schema/report"),
        ]

        for schema_file, expected_url in test_routes:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"schema": schema_file}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": "https://companion.example.com"}, clear=True):
                stdout_capture = io.StringIO()
                with patch("sys.stdout", stdout_capture):
                    resolver = CompanionSourceResolver()
                self.assertEqual(resolver.get_mode(), CompanionMode.CLOUD_HTTP)
                self.assertIn(
                    "[INFO] Companion source resolved to cloud HTTP endpoint: https://companion.example.com",
                    stdout_capture.getvalue(),
                )

                data = resolver.fetch_upstream_schema(schema_file)
                self.assertEqual(data, {"schema": schema_file})

                called_req = mock_urlopen.call_args[0][0]
                self.assertEqual(called_req.full_url, expected_url)

    @patch("urllib.request.urlopen")
    def test_mode_cloud_http_404_fallback_to_docs(self, mock_urlopen):
        """When /v1/schema/{name} returns 404, fallback to /docs/{schema_name}."""
        err_404 = urllib.error.HTTPError(
            url="https://companion.example.com/v1/schema/machine",
            code=404,
            msg="Not Found",
            hdrs=email.message.Message(),
            fp=None,
        )

        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps({"schema": "fallback-machine"}).encode("utf-8")
        success_resp.__enter__.return_value = success_resp

        mock_urlopen.side_effect = [err_404, success_resp]

        with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": "https://companion.example.com"}, clear=True):
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                resolver = CompanionSourceResolver()
            self.assertEqual(resolver.get_mode(), CompanionMode.CLOUD_HTTP)
            data = resolver.fetch_upstream_schema("machine-schema.json")
            self.assertEqual(data, {"schema": "fallback-machine"})

            self.assertEqual(mock_urlopen.call_count, 2)
            first_url = mock_urlopen.call_args_list[0][0][0].full_url
            second_url = mock_urlopen.call_args_list[1][0][0].full_url
            self.assertEqual(first_url, "https://companion.example.com/v1/schema/machine")
            self.assertEqual(second_url, "https://companion.example.com/docs/machine-schema.json")

    def test_mode_cloud_http_unmapped_schema_raises_error(self):
        """When an unmapped schema (e.g. build-report-schema.json) is requested via HTTP, raise ValueError."""
        with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": "https://companion.example.com"}, clear=True):
            resolver = CompanionSourceResolver()
            self.assertEqual(resolver.get_mode(), CompanionMode.CLOUD_HTTP)
            with self.assertRaises(ValueError) as ctx:
                resolver.fetch_upstream_schema("build-report-schema.json")
            self.assertIn("not exposed via HTTP API in gdc-companion", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_mode_cloud_http_non_404_raises_error(self, mock_urlopen):
        """When cloud HTTP encounters a 500 error or URLError, raise exception."""
        err_500 = urllib.error.HTTPError(
            url="https://companion.example.com/v1/schema/machine",
            code=500,
            msg="Internal Server Error",
            hdrs=email.message.Message(),
            fp=None,
        )
        mock_urlopen.side_effect = err_500

        with patch.dict(os.environ, {"GDC_COMPANION_SOURCE": "https://companion.example.com"}, clear=True):
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                resolver = CompanionSourceResolver()
            with self.assertRaises(urllib.error.HTTPError):
                resolver.fetch_upstream_schema("machine-schema.json")

    def test_explicit_source_argument_overrides_env(self):
        """Passing explicit source argument overrides environment variable."""
        with (
            patch.dict(os.environ, {"GDC_COMPANION_SOURCE": "none"}, clear=True),
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                resolver = CompanionSourceResolver(source=tmpdir)
            self.assertEqual(resolver.get_mode(), CompanionMode.LOCAL_FS)

    def test_mode_unset_ansi_tty_vs_plain_non_tty(self):
        """Verify ANSI red formatting on TTY and plain text on non-TTY."""
        with patch.dict(os.environ, {}, clear=True):
            # Test when stderr.isatty() returns True
            tty_mock = io.StringIO()
            tty_mock.isatty = lambda: True
            with patch("sys.stderr", tty_mock):
                CompanionSourceResolver()
            output_tty = tty_mock.getvalue()
            self.assertTrue(output_tty.startswith("\033[91m[ERROR]"))
            self.assertTrue(output_tty.endswith("\033[0m\n"))

            # Test when stderr.isatty() returns False
            nontty_mock = io.StringIO()
            nontty_mock.isatty = lambda: False
            with patch("sys.stderr", nontty_mock):
                CompanionSourceResolver()
            output_nontty = nontty_mock.getvalue()
            self.assertFalse(output_nontty.startswith("\033[91m"))
            self.assertTrue(output_nontty.startswith("[ERROR]"))

    def test_configurable_timeout_and_defaults(self):
        """CompanionSourceResolver respects default and user-configured timeout."""
        with patch("sys.stdout", io.StringIO()):
            default_resolver = CompanionSourceResolver(source="https://companion.example.com")
            self.assertEqual(default_resolver.timeout, 5.0)

            custom_resolver = CompanionSourceResolver(source="https://companion.example.com", timeout=12.5)
            self.assertEqual(custom_resolver.timeout, 12.5)

    @patch("urllib.request.urlopen")
    def test_configurable_timeout_propagates_to_urlopen(self, mock_urlopen):
        """Configured timeout is passed to urllib urlopen calls."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"schema": "test"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch("sys.stdout", io.StringIO()):
            resolver = CompanionSourceResolver(source="https://companion.example.com", timeout=8.0)
            resolver.fetch_upstream_schema("machine-schema.json")

        self.assertEqual(mock_urlopen.call_count, 1)
        _, kwargs = mock_urlopen.call_args
        self.assertEqual(kwargs.get("timeout"), 8.0)

    def test_local_fs_malformed_json_raises_schema_parsing_error(self):
        """When local schema file has malformed JSON, raise SchemaParsingError / ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = os.path.join(tmpdir, "docs")
            os.makedirs(docs_dir)
            with open(os.path.join(docs_dir, "machine-schema.json"), "w", encoding="utf-8") as f:
                f.write("{ invalid json: missing quotes and braces")

            with patch("sys.stdout", io.StringIO()):
                resolver = CompanionSourceResolver(source=tmpdir)
                with self.assertRaises(SchemaParsingError) as ctx:
                    resolver.fetch_upstream_schema("machine-schema.json")
                self.assertIn("Invalid JSON in schema 'machine-schema.json'", str(ctx.exception))
                self.assertIsInstance(ctx.exception, ValueError)

    @patch("urllib.request.urlopen")
    def test_cloud_http_malformed_json_raises_schema_parsing_error(self, mock_urlopen):
        """When cloud HTTP response has malformed JSON, raise SchemaParsingError / ValueError."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<!DOCTYPE html><html><body>Not JSON</body></html>"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch("sys.stdout", io.StringIO()):
            resolver = CompanionSourceResolver(source="https://companion.example.com")
            with self.assertRaises(SchemaParsingError) as ctx:
                resolver.fetch_upstream_schema("machine-schema.json")
            self.assertIn("Invalid JSON in schema 'machine-schema.json'", str(ctx.exception))
            self.assertIsInstance(ctx.exception, ValueError)

    @patch("urllib.request.urlopen")
    def test_cloud_http_fallback_malformed_json_raises_schema_parsing_error(self, mock_urlopen):
        """When cloud HTTP fallback response has malformed JSON, raise SchemaParsingError."""
        err_404 = urllib.error.HTTPError(
            url="https://companion.example.com/v1/schema/machine",
            code=404,
            msg="Not Found",
            hdrs=email.message.Message(),
            fp=None,
        )
        mock_resp_fallback = MagicMock()
        mock_resp_fallback.read.return_value = b"{ truncated json"
        mock_resp_fallback.__enter__.return_value = mock_resp_fallback
        mock_urlopen.side_effect = [err_404, mock_resp_fallback]

        with patch("sys.stdout", io.StringIO()):
            resolver = CompanionSourceResolver(source="https://companion.example.com")
            with self.assertRaises(SchemaParsingError) as ctx:
                resolver.fetch_upstream_schema("machine-schema.json")
            self.assertIn("Invalid JSON in schema 'machine-schema.json'", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_cloud_http_url_error_raises_descriptive_url_error(self, mock_urlopen):
        """When primary HTTP connection encounters URLError, raise descriptive URLError."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        with patch("sys.stdout", io.StringIO()):
            resolver = CompanionSourceResolver(source="https://companion.example.com")
            with self.assertRaises(urllib.error.URLError) as ctx:
                resolver.fetch_upstream_schema("machine-schema.json")
            self.assertIn("Failed to fetch schema 'machine-schema.json'", str(ctx.exception))
            self.assertIn("Connection refused", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_cloud_http_timeout_raises_url_error(self, mock_urlopen):
        """When primary HTTP connection times out, raise descriptive URLError."""
        mock_urlopen.side_effect = TimeoutError("Connection timed out")

        with patch("sys.stdout", io.StringIO()):
            resolver = CompanionSourceResolver(source="https://companion.example.com")
            with self.assertRaises(urllib.error.URLError) as ctx:
                resolver.fetch_upstream_schema("machine-schema.json")
            self.assertIn("Failed to fetch schema 'machine-schema.json'", str(ctx.exception))
            self.assertIn("timed out", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_cloud_http_fallback_404_raises_clean_url_error(self, mock_urlopen):
        """When both primary route and fallback URL fail with 404, raise descriptive URLError."""
        err_404_primary = urllib.error.HTTPError(
            url="https://companion.example.com/v1/schema/machine",
            code=404,
            msg="Not Found",
            hdrs=email.message.Message(),
            fp=None,
        )
        err_404_fallback = urllib.error.HTTPError(
            url="https://companion.example.com/docs/machine-schema.json",
            code=404,
            msg="Not Found",
            hdrs=email.message.Message(),
            fp=None,
        )
        mock_urlopen.side_effect = [err_404_primary, err_404_fallback]

        with patch("sys.stdout", io.StringIO()):
            resolver = CompanionSourceResolver(source="https://companion.example.com")
            with self.assertRaises(urllib.error.URLError) as ctx:
                resolver.fetch_upstream_schema("machine-schema.json")
            self.assertIn("fallback endpoint", str(ctx.exception))
            self.assertIn("machine-schema.json", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_cloud_http_fallback_timeout_raises_clean_url_error(self, mock_urlopen):
        """When fallback request encounters a timeout, raise clean descriptive URLError."""
        err_404_primary = urllib.error.HTTPError(
            url="https://companion.example.com/v1/schema/machine",
            code=404,
            msg="Not Found",
            hdrs=email.message.Message(),
            fp=None,
        )
        mock_urlopen.side_effect = [err_404_primary, TimeoutError("Fallback timed out")]

        with patch("sys.stdout", io.StringIO()):
            resolver = CompanionSourceResolver(source="https://companion.example.com")
            with self.assertRaises(urllib.error.URLError) as ctx:
                resolver.fetch_upstream_schema("machine-schema.json")
            self.assertIn("fallback endpoint", str(ctx.exception))
            self.assertIn("Fallback timed out", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
