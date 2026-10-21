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

# Locate active or local virtual environment Python if not explicitly provided
if [[ -z "${PYTHON_BIN:-}" ]]; then
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
        PYTHON_BIN="${VIRTUAL_ENV}/bin/python3"
    elif [[ -x "${PROJECT_ROOT}/venv/bin/python3" ]]; then
        PYTHON_BIN="${PROJECT_ROOT}/venv/bin/python3"
    elif [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
        PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
    elif [[ -x "${PROJECT_ROOT}/src/build/.venv/bin/python3" ]]; then
        PYTHON_BIN="${PROJECT_ROOT}/src/build/.venv/bin/python3"
    else
        PYTHON_BIN="python3"
    fi
fi

# Fast-fail if Python is missing or older than 3.8
if ! command -v "${PYTHON_BIN}" &>/dev/null; then
    echo -e "\033[91m[!] Error: Python interpreter '${PYTHON_BIN}' not found on PATH or in virtualenvs.\033[0m" >&2
    exit 1
fi

if ! "${PYTHON_BIN}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' &>/dev/null; then
    py_ver=$("${PYTHON_BIN}" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo "unknown")
    echo -e "\033[91m[!] Error: Python 3.8+ is required. Found Python ${py_ver} at '${PYTHON_BIN}'.\033[0m" >&2
    exit 1
fi

# Capture caller-provided environment variables so file sourcing does not overwrite them
declare -A INITIAL_ENV
for var in $(compgen -e); do
    INITIAL_ENV[$var]=1
done

BUILD_ENV="${PROJECT_ROOT}/src/build/build.env"
ISO_ENVIRONMENT="${ISO_ENVIRONMENT:-local}"
LOCAL_ENV="${PROJECT_ROOT}/src/build/${ISO_ENVIRONMENT}.env"

# Safe environment file loader: defaults from build.env, overrides from local.env,
# and initial caller environment takes absolute precedence.
load_env_file() {
    local env_file="$1"
    if [[ -f "${env_file}" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue
            line="${line#"export "}"
            if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                local key="${BASH_REMATCH[1]}"
                local val="${BASH_REMATCH[2]}"
                val="${val#\"}" && val="${val%\"}"
                val="${val#\'}" && val="${val%\'}"
                if [[ -z "${INITIAL_ENV[${key}]:-}" ]]; then
                    export "${key}"="${val}"
                fi
            fi
        done < "${env_file}"
    fi
}

load_env_file "${BUILD_ENV}"
load_env_file "${LOCAL_ENV}"

# ==========================================
# Help Menu
# ==========================================
usage() {
    cat <<HELPEOF
GDC Bootimus ISO Deployer
Usage: $0 [options] [iso_filename]

Options:
  -l, --list                  List all groups and images currently on the Bootimus server
  --next-boot <iso> [options] Set one-time next-boot image for target client(s)
  --clear-next-boot [options] Clear one-time next-boot override for target client(s)
  --targets, --nodes <IPs>    Target node IPs, hostnames, or MACs (defaults to TARGET_TEST_MACHINES)
                              Supports space-separated ("10.0.0.1 10.0.0.2") or CSV ("10.0.0.1,10.0.0.2")
  --mac <mac_address>         Target client MAC address
  --all-targets               Target all registered clients
  -f, --force                 Force Bootimus to re-ingest and extract the ISO even if it exists
  --user <user>               Bootimus API username (or export BOOTIMUS_USER)
  --pass <password>           Bootimus API password (or export BOOTIMUS_PASS)
  --secret-method <method>    Secret provider to query: env (default), file, infisical, gcloud
  --secret-file <path>        Path to secret file containing JSON or raw password
  -h, --help                  Display this help message

Environment:
  TARGET_TEST_MACHINES        Space or comma-separated target node IPs (e.g. "10.0.0.1 10.0.0.2")
  PXE_SERVER_HOST             Target Bootimus PXE Server API Host
  PXE_SERVER_PORT             Target Bootimus PXE Server API Port

Example:
  $0 gdc-bootstrap-ubuntu-24.04-v0.8.14-debug.iso
  $0 --list
  $0 --next-boot sync/gdc-labs-24.04-v0.10.19-debug.iso --all-targets
  $0 --next-boot sync/gdc-labs-24.04-v0.10.19-debug.iso --targets "192.168.9.241 192.168.9.242"
  $0 --clear-next-boot --all-targets
HELPEOF
    exit "${1:-0}"
}

if [[ $# -eq 0 ]]; then
    usage 1
fi

ALL_ARGS=("$@")
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
        --next-boot|--set-next-boot)
            ACTION="NEXT_BOOT"
            EXTRA_ARGS+=("$1")
            if [[ $# -gt 1 && ! "$2" =~ ^- ]]; then
                NEXT_BOOT_ISO="$2"
                EXTRA_ARGS+=("$2")
                shift
            fi
            shift
            ;;
        --clear-next-boot)
            ACTION="CLEAR_NEXT_BOOT"
            EXTRA_ARGS+=("$1")
            shift
            ;;
        --check-auth|--test-creds)
            ACTION="CHECK_AUTH"
            EXTRA_ARGS+=("$1")
            shift
            ;;
        -f|--force)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        --user|--bootimus-user)
            EXTRA_ARGS+=("--user" "$2")
            export BOOTIMUS_USER="$2"
            shift 2
            ;;
        --pass|--bootimus-pass|--password|--bootimus-password)
            EXTRA_ARGS+=("--pass" "$2")
            export BOOTIMUS_PASS="$2"
            shift 2
            ;;
        --env|--profile)
            ISO_ENVIRONMENT="$2"
            load_env_file "${PROJECT_ROOT}/src/build/${ISO_ENVIRONMENT}.env"
            shift 2
            ;;
        --secret-method|--secret-provider|---secret-method|--bootimus-secret-method|--bootimus-secret-provider)
            EXTRA_ARGS+=("--secret-method" "$2")
            export BOOTIMUS_SECRET_METHOD="$2"
            shift 2
            ;;
        --secret-file|--bootimus-secret-file)
            EXTRA_ARGS+=("--secret-file" "$2")
            export BOOTIMUS_SECRET_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage 0
            ;;
        -*)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        *)
            if [[ -z "${ISO_FILENAME}" && "${ACTION}" == "INGEST" ]]; then
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

# Auto-detect profile from ISO filename if default local was used
target_iso_detect="${ISO_FILENAME:-${NEXT_BOOT_ISO:-}}"
if [[ "${ISO_ENVIRONMENT}" == "local" && -n "${target_iso_detect}" ]]; then
    if [[ "${target_iso_detect}" == *gdc-labs* || "${target_iso_detect}" == *barn* ]] && [[ -f "${PROJECT_ROOT}/src/build/barn.env" ]]; then
        ISO_ENVIRONMENT="barn"
        load_env_file "${PROJECT_ROOT}/src/build/barn.env"
    elif [[ "${target_iso_detect}" == *honeywell* ]] && [[ -f "${PROJECT_ROOT}/src/build/honeywell.env" ]]; then
        ISO_ENVIRONMENT="honeywell"
        load_env_file "${PROJECT_ROOT}/src/build/honeywell.env"
    fi
fi

export BOOTIMUS_SECRET_METHOD="${BOOTIMUS_SECRET_METHOD:-${BOOTIMUS_SECRET_PROVIDER:-infisical}}"

# ==========================================
# Validate Environment Variables
# ==========================================
PXE_SERVER_HOST="${PXE_SERVER_HOST:-192.168.254.12}"
PXE_SERVER_PORT="${PXE_SERVER_PORT:-26000}"
BOOTIMUS_HTTP_PORT="${BOOTIMUS_HTTP_PORT:-16000}"

# Export aligned variables for downstream Python engine
export PXE_SERVER_HOST
export PXE_SERVER_PORT
export BOOTIMUS_API_HOST="${BOOTIMUS_API_HOST:-${PXE_SERVER_HOST}}"
export BOOTIMUS_API_PORT="${BOOTIMUS_API_PORT:-${PXE_SERVER_PORT}}"
export BOOTIMUS_HTTP_PORT
export ISO_ENVIRONMENT
if [[ -n "${TARGET_TEST_MACHINES:-}" ]]; then
    export TARGET_TEST_MACHINES
fi

echo "=============================================================================="
if [[ "${ACTION}" == "LIST" ]]; then
    echo " ACTION:           Querying Bootimus PXE Tree"
elif [[ "${ACTION}" == "CHECK_AUTH" ]]; then
    echo " ACTION:           Testing Bootimus Authentication Credentials"
elif [[ "${ACTION}" == "NEXT_BOOT" || "${ACTION}" == "CLEAR_NEXT_BOOT" ]]; then
    echo " ACTION:           Bootimus Next-Boot Automation"
else
    echo " ACTION:           Ingesting ISO to Bootimus PXE"
    echo " TARGET ISO:       ${ISO_FILENAME}"
fi
echo " PXE SERVER:       http://${PXE_SERVER_HOST}:${PXE_SERVER_PORT}"
echo " AUTHENTICATION:   $([[ -n "${BOOTIMUS_USER:-}" && -n "${BOOTIMUS_PASS:-}" ]] && echo "Environment Variables" || echo "Provider (${BOOTIMUS_SECRET_METHOD:-none})")"
echo "=============================================================================="

# ==========================================
# Execute Python Bootimus Script
# ==========================================
if [[ "${ACTION}" == "LIST" || "${ACTION}" == "CHECK_AUTH" ]]; then
    exec "${PYTHON_BIN}" "${PROJECT_ROOT}/src/build/bootimus.py" "${EXTRA_ARGS[@]}"
elif [[ "${ACTION}" == "NEXT_BOOT" || "${ACTION}" == "CLEAR_NEXT_BOOT" ]]; then
    exec "${PYTHON_BIN}" "${PROJECT_ROOT}/src/build/bootimus.py" "${ALL_ARGS[@]}"
else
    exec "${PYTHON_BIN}" "${PROJECT_ROOT}/src/build/bootimus.py" "${ISO_FILENAME}" "${EXTRA_ARGS[@]}"
fi
