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
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET_SCHEMA="${REPO_ROOT}/docs/machine-schema.json"

DEFAULT_COMPANION="/d/projects/google/gdc-companion"
SIBLING_COMPANION="$(cd "${REPO_ROOT}/../gdc-companion" 2>/dev/null && pwd || true)"

COMPANION_DIR="${GDC_COMPANION_DIR:-$([[ -d "${DEFAULT_COMPANION}" ]] && echo "${DEFAULT_COMPANION}" || echo "${SIBLING_COMPANION}")}"
SOURCE_SCHEMA="${COMPANION_DIR}/docs/machine-schema.json"

CHECK_ONLY=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Synchronizes docs/machine-schema.json from the upstream gdc-companion repository.

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
            SOURCE_SCHEMA="${COMPANION_DIR}/docs/machine-schema.json"
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

if [[ ! -f "${SOURCE_SCHEMA}" ]]; then
    echo "Error: Upstream schema not found at '${SOURCE_SCHEMA}'" >&2
    echo "Set GDC_COMPANION_DIR or pass --companion <PATH>" >&2
    exit 1
fi

echo "[-] Upstream schema: ${SOURCE_SCHEMA}"
echo "[-] Local target:    ${TARGET_SCHEMA}"

python3 -c "
import json, sys

with open(sys.argv[1], 'r', encoding='utf-8') as sf, open(sys.argv[2], 'r', encoding='utf-8') as tf:
    upstream = json.load(sf)
    local = json.load(tf)

upstream_cmp = {k: v for k, v in upstream.items() if k != '\$comment'}
local_cmp = {k: v for k, v in local.items() if k != '\$comment'}

if upstream_cmp == local_cmp:
    print('  [x] Schemas are identical (in sync).')
    sys.exit(0)
else:
    print('[!] Schemas have diverged!', file=sys.stderr)
    sys.exit(2)
" "${SOURCE_SCHEMA}" "${TARGET_SCHEMA}" && STATUS=$? || STATUS=$?

if [[ "${STATUS}" -eq 0 ]]; then
    exit 0
fi

if [[ "${CHECK_ONLY}" == "true" ]]; then
    echo "Error: Divergence detected between local and upstream schema." >&2
    exit 1
fi

echo "[-] Updating local schema with upstream definitions..."
python3 -c "
import json, sys

with open(sys.argv[1], 'r', encoding='utf-8') as sf:
    upstream = json.load(sf)

comment = 'UPSTREAM OWNER: gdc-companion (docs/machine-schema.json). DO NOT EDIT DIRECTLY. This file is vendored from the gdc-companion repository to support hermetic, air-gapped CI and offline validation. Run bin/sync-schemas.sh to sync with upstream.'

ordered = {'\$schema': upstream.get('\$schema', 'http://json-schema.org/draft-07/schema#'), '\$comment': comment}
for k, v in upstream.items():
    if k not in ['\$schema', '\$comment']:
        ordered[k] = v

with open(sys.argv[2], 'w', encoding='utf-8') as tf:
    json.dump(ordered, tf, indent=2)
    tf.write('\n')

print('  [x] Successfully synchronized docs/machine-schema.json from gdc-companion.')
" "${SOURCE_SCHEMA}" "${TARGET_SCHEMA}"
