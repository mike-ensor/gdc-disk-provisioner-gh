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
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class CompanionMode(enum.Enum):
    """Enumeration of supported companion source resolution modes."""

    OFFLINE = "offline"
    LOCAL_FS = "local_fs"
    CLOUD_HTTP = "cloud_http"


class SchemaParsingError(ValueError):
    """Raised when an upstream schema contains invalid JSON."""


SCHEMA_ROUTE_MAP = {
    "machine-schema.json": "/v1/schema/machine",
    "report-schema.json": "/v1/schema/report",
    "build-report-schema.json": "/v1/schema/build-report",
}


class CompanionSourceResolver:
    """Resolves and fetches schemas from local filesystem, cloud HTTP, or offline modes."""

    def __init__(self, source: Optional[str] = None, timeout: float = 5.0):
        """Initialize resolver with explicit source string or GDC_COMPANION_SOURCE env var.

        Args:
            source: Source specification (file path, URL, or mode keyword).
            timeout: Network timeout in seconds for HTTP operations (defaults to 5.0).
        """
        if source is None:
            source = os.environ.get("GDC_COMPANION_SOURCE")
        self.raw_source = source
        self.timeout = timeout
        self.mode = self._determine_mode()

    def _determine_mode(self) -> CompanionMode:
        """Inspect configured source and determine active CompanionMode."""
        if self.raw_source is None or self.raw_source.strip() == "":
            msg = (
                "[ERROR] GDC_COMPANION_SOURCE environment variable is not defined. "
                "Defaulting to hermetic/offline mode (skipping upstream schema synchronization)."
            )
            is_tty = getattr(sys.stderr, "isatty", lambda: False)()
            if is_tty:
                sys.stderr.write(f"\033[91m{msg}\033[0m\n")
            else:
                sys.stderr.write(f"{msg}\n")
            return CompanionMode.OFFLINE

        normalized = self.raw_source.strip()
        if normalized.lower() in ("none", "disabled", "offline"):
            sys.stdout.write(
                f"[INFO] GDC_COMPANION_SOURCE is set to '{normalized}'. Operating in hermetic/offline mode.\n"
            )
            return CompanionMode.OFFLINE

        if normalized.startswith(("http://", "https://")):
            sys.stdout.write(
                f"[INFO] Companion source resolved to cloud HTTP endpoint: {normalized}\n"
            )
            return CompanionMode.CLOUD_HTTP

        sys.stdout.write(
            f"[INFO] Companion source resolved to local filesystem: {normalized}\n"
        )
        return CompanionMode.LOCAL_FS

    def get_mode(self) -> CompanionMode:
        """Return the resolved CompanionMode."""
        return self.mode

    def fetch_upstream_schema(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """Fetch upstream schema dictionary based on active resolution mode.

        Args:
            schema_name: The filename of the schema (e.g. 'machine-schema.json').

        Returns:
            Dictionary containing the parsed JSON schema, or None if in OFFLINE mode.

        Raises:
            FileNotFoundError: In LOCAL_FS mode if directory or schema file does not exist.
            SchemaParsingError: If schema file or HTTP response contains invalid JSON.
            urllib.error.HTTPError / URLError: In CLOUD_HTTP mode if request fails.
        """
        if self.mode == CompanionMode.OFFLINE:
            return None

        if self.mode == CompanionMode.LOCAL_FS:
            if self.raw_source is None:
                raise FileNotFoundError("Local companion directory is not specified.")
            base_dir = os.path.abspath(self.raw_source.strip())
            if not os.path.isdir(base_dir):
                raise FileNotFoundError(f"Configured companion directory '{base_dir}' does not exist.")
            schema_path = os.path.join(base_dir, "docs", schema_name)
            if not os.path.isfile(schema_path):
                raise FileNotFoundError(f"Upstream schema '{schema_path}' not found.")
            with open(schema_path, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError as e:
                    raise SchemaParsingError(f"Invalid JSON in schema '{schema_name}': {e}") from e

        if self.mode == CompanionMode.CLOUD_HTTP:
            if self.raw_source is None:
                raise ValueError("Cloud HTTP companion endpoint is not specified.")
            base_url = self.raw_source.strip().rstrip("/")
            endpoint = SCHEMA_ROUTE_MAP.get(schema_name, f"/v1/schema/{schema_name.replace('.json', '')}")
            target_url = f"{base_url}{endpoint}"
            req = urllib.request.Request(
                target_url,
                headers={"Accept": "application/json", "User-Agent": "gdc-disk-provisioner-sync/1.0"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw_data = resp.read().decode("utf-8")
                try:
                    return json.loads(raw_data)
                except json.JSONDecodeError as e:
                    raise SchemaParsingError(f"Invalid JSON in schema '{schema_name}': {e}") from e
            except urllib.error.HTTPError as e:
                # If /v1/schema/{name} gives 404, fall back to /docs/{schema_name}
                if e.code == 404:
                    fallback_url = f"{base_url}/docs/{schema_name}"
                    req_fallback = urllib.request.Request(
                        fallback_url,
                        headers={"Accept": "application/json", "User-Agent": "gdc-disk-provisioner-sync/1.0"},
                    )
                    try:
                        with urllib.request.urlopen(req_fallback, timeout=self.timeout) as resp_fallback:
                            raw_fallback = resp_fallback.read().decode("utf-8")
                        try:
                            return json.loads(raw_fallback)
                        except json.JSONDecodeError as e_fallback_json:
                            raise SchemaParsingError(
                                f"Invalid JSON in schema '{schema_name}': {e_fallback_json}"
                            ) from e_fallback_json
                    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as fallback_err:
                        raise urllib.error.URLError(
                            f"Failed to fetch schema '{schema_name}' from fallback endpoint '{fallback_url}': {fallback_err}"
                        ) from fallback_err
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                raise urllib.error.URLError(
                    f"Failed to fetch schema '{schema_name}' from endpoint '{target_url}': {e}"
                ) from e

        return None
