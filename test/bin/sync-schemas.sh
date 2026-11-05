#!/usr/bin/env bash
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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CHECK_ONLY=false
SOURCE=""
SOURCE_SET=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Synchronizes schemas (machine-schema.json, report-schema.json, build-report-schema.json)
from the upstream gdc-companion repository to docs/.

Options:
  --check               Check for divergence without modifying files (exits 1 if drifted)
  --source <SOURCE>     Upstream source: URL (http:// or https://), local path, or "none"
  --companion <PATH>    Backward-compatible alias for --source <PATH>
  -h, --help            Display this help message

Environment Variables:
  GDC_COMPANION_SOURCE  Upstream source specification (URL, local path, or "none")
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)
            CHECK_ONLY=true
            shift
            ;;
        --source)
            if [[ $# -lt 2 ]]; then
                echo "Error: --source requires an argument" >&2
                exit 1
            fi
            SOURCE="$2"
            SOURCE_SET=true
            shift 2
            ;;
        --source=*)
            SOURCE="${1#*=}"
            SOURCE_SET=true
            shift
            ;;
        --companion)
            if [[ $# -lt 2 ]]; then
                echo "Error: --companion requires an argument" >&2
                exit 1
            fi
            SOURCE="$2"
            SOURCE_SET=true
            shift 2
            ;;
        --companion=*)
            SOURCE="${1#*=}"
            SOURCE_SET=true
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        *)
            echo "Error: Unknown argument '$1'" >&2
            usage 1
            ;;
    esac
done

exec python3 - "${REPO_ROOT}" "${CHECK_ONLY}" "${SOURCE_SET}" "${SOURCE}" << 'EOF'
import json
import os
import sys

repo_root = sys.argv[1]
check_only = sys.argv[2] == "true"
source_set = sys.argv[3] == "true"
cli_source = sys.argv[4] if source_set else None

# Ensure test/lib is importable
sys.path.insert(0, os.path.join(repo_root, "test"))
try:
    from lib.companion_source import CompanionSourceResolver, CompanionMode, SCHEMA_ROUTE_MAP
except ImportError:
    from test.lib.companion_source import CompanionSourceResolver, CompanionMode, SCHEMA_ROUTE_MAP

try:
    resolver = CompanionSourceResolver(source=cli_source, timeout=15.0)
except Exception as e:
    sys.stderr.write(f"Error initializing companion resolver: {e}\n")
    sys.exit(1)

mode = resolver.get_mode()

if mode == CompanionMode.OFFLINE:
    if check_only:
        print("[-] Hermetic/offline mode: schema divergence check skipped (in sync).")
        sys.exit(0)
    else:
        print("[-] Hermetic/offline mode: companion source is offline or not configured; skipping schema synchronization.")
        sys.exit(0)

schemas = ["machine-schema.json", "report-schema.json", "build-report-schema.json"]
divergences = 0

for schema_name in schemas:
    local_path = os.path.join(repo_root, "docs", schema_name)
    if mode == CompanionMode.CLOUD_HTTP and schema_name not in SCHEMA_ROUTE_MAP:
        print(f"[-] Skipping schema '{schema_name}': not exposed via HTTP API by gdc-companion (local filesystem only).")
        continue

    if mode == CompanionMode.LOCAL_FS:
        if resolver.raw_source:
            upstream_loc = os.path.join(os.path.abspath(resolver.raw_source.strip()), "docs", schema_name)
        else:
            upstream_loc = "unknown"
    else:
        base_url = resolver.raw_source.strip().rstrip("/") if resolver.raw_source else ""
        upstream_loc = f"{base_url}{SCHEMA_ROUTE_MAP.get(schema_name, f'/v1/schema/{schema_name}')}"

    print(f"[-] Checking schema '{schema_name}'...")
    print(f"    Upstream: {upstream_loc}")
    print(f"    Local:    {local_path}")

    try:
        upstream = resolver.fetch_upstream_schema(schema_name)
    except Exception as e:
        sys.stderr.write(f"Error fetching upstream schema '{schema_name}': {e}\n")
        sys.exit(1)

    if upstream is None:
        sys.stderr.write(f"Error: Upstream schema '{schema_name}' returned empty or null\n")
        sys.exit(1)

    local = None
    if os.path.isfile(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local = json.load(f)
        except Exception as e:
            print(f"    [!] Failed to parse local schema: {e}", file=sys.stderr)
            local = None
    else:
        print("    [!] Local schema missing!")

    is_identical = False
    if local is not None:
        upstream_cmp = {k: v for k, v in upstream.items() if k != "$comment"}
        local_cmp = {k: v for k, v in local.items() if k != "$comment"}
        if upstream_cmp == local_cmp:
            is_identical = True

    if check_only:
        if is_identical:
            print("    [x] Schemas are identical (in sync).")
        else:
            print("    [!] Schemas have diverged!", file=sys.stderr)
            divergences += 1
    else:
        if not is_identical:
            print("    [!] Schemas have diverged!")
        print(f"    [-] Updating local {schema_name} with upstream definitions...")
        comment = (local.get("$comment") if local else None) or (
            f"UPSTREAM OWNER: gdc-companion (docs/{schema_name}). DO NOT EDIT DIRECTLY. "
            "This file is vendored from the gdc-companion repository to support hermetic, "
            "air-gapped CI and offline validation. Run test/bin/sync-schemas.sh to sync with upstream."
        )
        schema_ver = upstream.get("$schema") or (local.get("$schema") if local else None) or "http://json-schema.org/draft-07/schema#"
        ordered = {"$schema": schema_ver, "$comment": comment}
        for k, v in upstream.items():
            if k not in ["$schema", "$comment"]:
                ordered[k] = v

        try:
            with open(local_path, "w", encoding="utf-8") as tf:
                json.dump(ordered, tf, indent=2)
                tf.write("\n")
            print(f"    [x] Successfully synchronized docs/{schema_name} from gdc-companion.")
        except Exception as e:
            sys.stderr.write(f"Error writing schema '{local_path}': {e}\n")
            sys.exit(1)

if check_only:
    if divergences > 0:
        sys.stderr.write(f"Error: Divergence detected in {divergences} schema file(s).\n")
        sys.exit(1)
    print("[x] All schemas verified (in sync).")
else:
    print("[x] All schemas synchronized successfully.")

sys.exit(0)
EOF
