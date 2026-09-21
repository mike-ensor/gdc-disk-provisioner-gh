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

# ==============================================================================
# GDC Bootimus PXE Ingestion Wrapper
# ==============================================================================
# Validates environment configuration and wraps the Python ingestion CLI.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"

# Source environment
if [[ -f "${PROJECT_ROOT}/.envrc" ]]; then
    # shellcheck source=/dev/null
    source "${PROJECT_ROOT}/.envrc"
fi

BUILD_ENV="${PROJECT_ROOT}/src/build/build.env"
ISO_ENVIRONMENT="${ISO_ENVIRONMENT:-local}"
LOCAL_ENV="${PROJECT_ROOT}/src/build/${ISO_ENVIRONMENT}.env"

source_env_safe() {
    local env_file="$1"
    if [[ -f "${env_file}" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue
            if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                local key="${BASH_REMATCH[1]}"
                local val="${BASH_REMATCH[2]}"
                val="${val#\"}" && val="${val%\"}"
                val="${val#\'}" && val="${val%\'}"
                if [[ -z "${!key:-}" ]]; then
                    export "${key}"="${val}"
                fi
            fi
        done < "${env_file}"
    fi
}

source_env_safe "${BUILD_ENV}"
source_env_safe "${LOCAL_ENV}"

# ==========================================
# Help Menu
# ==========================================
usage() {
    cat <<HELPEOF
GDC Bootimus ISO Deployer
Usage: $0 [options] <iso_filename>

Options:
  -l, --list        List all groups and images currently on the Bootimus server
  -f, --force       Force Bootimus to re-ingest and extract the ISO even if it exists
  -h, --help        Display this help message

Environment:
  PXE_SERVER_HOST   Target Bootimus PXE Server API Host
  PXE_SERVER_PORT   Target Bootimus PXE Server API Port

Example:
  $0 gdc-bootstrap-ubuntu-24.04-v0.8.14-debug.iso
  $0 --list
HELPEOF
    exit "${1:-0}"
}

if [[ $# -eq 0 ]]; then
    usage 1
fi

ACTION="INGEST"
ISO_FILENAME=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -l|--list)
            ACTION="LIST"
            EXTRA_ARGS+=("$1")
            shift
            ;;
        -f|--force)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        -*)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        *)
            if [[ -z "${ISO_FILENAME}" ]]; then
                ISO_FILENAME="$1"
            else
                EXTRA_ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

if [[ "${ACTION}" == "INGEST" && -z "${ISO_FILENAME}" ]]; then
    echo "[!] Error: No ISO filename provided for ingestion." >&2
    usage 1
fi

# ==========================================
# Validate Environment Variables
# ==========================================
PXE_SERVER_HOST="${PXE_SERVER_HOST:-192.168.254.12}"
PXE_SERVER_PORT="${PXE_SERVER_PORT:-26000}"

echo "=============================================================================="
if [[ "${ACTION}" == "LIST" ]]; then
    echo " ACTION:           Querying Bootimus PXE Tree"
else
    echo " ACTION:           Ingesting ISO to Bootimus PXE"
    echo " TARGET ISO:       ${ISO_FILENAME}"
fi
echo " PXE SERVER:       http://${PXE_SERVER_HOST}:${PXE_SERVER_PORT}"
echo " AUTHENTICATION:   $([[ -n "${BOOTIMUS_USER:-}" ]] && echo "Environment Variables" || echo "Infisical Managed Secrets")"
echo "=============================================================================="

# ==========================================
# Execute Python Bootimus Script
# ==========================================
if [[ "${ACTION}" == "LIST" ]]; then
    python3 "${PROJECT_ROOT}/src/build/bootimus.py" "${EXTRA_ARGS[@]}"
else
    python3 "${PROJECT_ROOT}/src/build/bootimus.py" "${ISO_FILENAME}" "${EXTRA_ARGS[@]}"
fi
