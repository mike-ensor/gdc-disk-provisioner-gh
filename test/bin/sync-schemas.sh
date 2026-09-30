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

DEFAULT_COMPANION="/d/projects/google/gdc-companion"
SIBLING_COMPANION="$(cd "${REPO_ROOT}/../gdc-companion" 2>/dev/null && pwd || true)"

COMPANION_DIR="${GDC_COMPANION_DIR:-$([[ -d "${DEFAULT_COMPANION}" ]] && echo "${DEFAULT_COMPANION}" || echo "${SIBLING_COMPANION}")}"

CHECK_ONLY=false
SCHEMAS=("machine-schema.json" "report-schema.json" "build-report-schema.json")

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Synchronizes schemas (machine-schema.json, report-schema.json, build-report-schema.json)
from the upstream gdc-companion repository to docs/.

Options:
  --check       Check for divergence without modifying files (exits 1 if drifted)
  --companion   Path to gdc-companion repository root
  -h, --help    Display this help message
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)
            CHECK_ONLY=true
            shift
            ;;
        --companion)
            COMPANION_DIR="$2"
            shift 2
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

if [[ ! -d "${COMPANION_DIR}" ]]; then
    echo "Error: Upstream gdc-companion directory not found at '${COMPANION_DIR}'" >&2
    echo "Set GDC_COMPANION_DIR or pass --companion <PATH>" >&2
    exit 1
fi

TOTAL_DIVERGENCES=0

for schema_file in "${SCHEMAS[@]}"; do
    SOURCE_SCHEMA="${COMPANION_DIR}/docs/${schema_file}"
    TARGET_SCHEMA="${REPO_ROOT}/docs/${schema_file}"

    if [[ ! -f "${SOURCE_SCHEMA}" ]]; then
        echo "[-] Skipping '${schema_file}': not found in upstream '${COMPANION_DIR}/docs/'"
        continue
    fi

    echo "[-] Checking schema '${schema_file}'..."
    echo "    Upstream: ${SOURCE_SCHEMA}"
    echo "    Local:    ${TARGET_SCHEMA}"

    if [[ ! -f "${TARGET_SCHEMA}" ]]; then
        echo "    [!] Local schema missing!"
        STATUS=2
    else
        python3 -c "
import json, sys

with open(sys.argv[1], 'r', encoding='utf-8') as sf, open(sys.argv[2], 'r', encoding='utf-8') as tf:
    upstream = json.load(sf)
    local = json.load(tf)

upstream_cmp = {k: v for k, v in upstream.items() if k != '\$comment'}
local_cmp = {k: v for k, v in local.items() if k != '\$comment'}

if upstream_cmp == local_cmp:
    print('    [x] Schemas are identical (in sync).')
    sys.exit(0)
else:
    print('    [!] Schemas have diverged!', file=sys.stderr)
    sys.exit(2)
" "${SOURCE_SCHEMA}" "${TARGET_SCHEMA}" 2>/dev/null && STATUS=$? || STATUS=$?
    fi

    if [[ "${STATUS}" -ne 0 ]]; then
        TOTAL_DIVERGENCES=$((TOTAL_DIVERGENCES + 1))
        if [[ "${CHECK_ONLY}" == "false" ]]; then
            echo "    [-] Updating local ${schema_file} with upstream definitions..."
            python3 -c "
import json, sys

with open(sys.argv[1], 'r', encoding='utf-8') as sf:
    upstream = json.load(sf)

comment = f'UPSTREAM OWNER: gdc-companion (docs/{sys.argv[3]}). DO NOT EDIT DIRECTLY. This file is vendored from the gdc-companion repository to support hermetic, air-gapped CI and offline validation. Run bin/sync-schemas.sh to sync with upstream.'

ordered = {'\$schema': upstream.get('\$schema', 'http://json-schema.org/draft-07/schema#'), '\$comment': comment}
for k, v in upstream.items():
    if k not in ['\$schema', '\$comment']:
        ordered[k] = v

with open(sys.argv[2], 'w', encoding='utf-8') as tf:
    json.dump(ordered, tf, indent=2)
    tf.write('\n')

print(f'    [x] Successfully synchronized docs/{sys.argv[3]} from gdc-companion.')
" "${SOURCE_SCHEMA}" "${TARGET_SCHEMA}" "${schema_file}"
        fi
    fi
done

if [[ "${TOTAL_DIVERGENCES}" -gt 0 && "${CHECK_ONLY}" == "true" ]]; then
    echo "Error: Divergence detected in ${TOTAL_DIVERGENCES} schema file(s)." >&2
    exit 1
fi

echo "[x] All schemas verified."
