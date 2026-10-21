#!/usr/bin/env bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# GDC Full Environment Rebuild Cycle Orchestrator
# ==============================================================================
# Executes an end-to-end rebuild cycle in a single command for AI agents and operators:
#   1. Pull environment profile from GDC Companion (pull-profile)
#   2. Trigger Google Cloud Build ISO compilation with Bootimus integration (build.sh)
#   3. Verify & heal Bootimus PXE registration, kernel extraction, and parameters
#   4. Schedule one-time UEFI PXE next-boot and reboot target bare-metal nodes (reset-pxe)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Executes a complete GDC environment rebuild cycle end-to-end:
  pull-profile -> build.sh (--bootimus) -> check-bootimus -> reset-pxe

Options:
  --profile <NAME>          Environment profile name to pull and build (e.g. barn, honeywell)
  --version <SEMVER>        Target ISO version (default: reads from VERSION file)
  --companion-url <URL>     GDC Companion base URL (default: from local.env or https://gdc-companion.ensor-labs.com/)
  --api-key <KEY>           API key for GDC Companion authentication (optional)
  --nodes <IPS>             Target node IPs to reboot, comma-separated (default: TARGET_TEST_MACHINES from profile)
  --key <KEY_PATH>          SSH private key for target nodes (default: ~/.ssh/gdc-disk-provisioner or ~/.ssh/id_ed25519)
  --user <USER>             SSH user for target nodes (default: gdc-admin)
  --skip-build              Skip ISO compilation; only verify Bootimus and execute reset-pxe
  --skip-reboot             Build ISO and verify Bootimus, but skip resetting/rebooting nodes
  --skip-fleet              Skip unregistering Fleet memberships during reset-pxe
  --dry-run                 Simulate execution and print planned commands without modifying system
  -y, --yes                 Skip confirmation prompts (required for unattended agent execution)
  -h, --help                Display this help message and exit

Examples:
  # Unattended full rebuild cycle for profile 'barn':
  $(basename "$0") --profile barn --version 0.11.3 --yes

  # Rebuild with specific nodes and explicit SSH key:
  $(basename "$0") --profile barn --nodes 192.168.9.241,192.168.9.242 --key ~/.ssh/gdc-disk-provisioner --yes

  # Preview planned execution:
  $(basename "$0") --profile barn --dry-run
EOF
    exit "${1:-0}"
}

# Defaults
PROFILE="${ISO_PROFILE:-${ISO_ENVIRONMENT:-barn}}"
VERSION_ARG=""
COMPANION_URL=""
API_KEY=""
TARGET_NODES=""
SSH_KEY=""
SSH_USER="gdc-admin"
BOOTIMUS_USER="${BOOTIMUS_USER:-}"
BOOTIMUS_PASS="${BOOTIMUS_PASS:-}"
BOOTIMUS_SECRET_METHOD="${BOOTIMUS_SECRET_METHOD:-${BOOTIMUS_SECRET_PROVIDER:-env}}"
BOOTIMUS_SECRET_FILE="${BOOTIMUS_SECRET_FILE:-}"
CHECK_AUTH=true
SKIP_BUILD=false
SKIP_REBOOT=false
SKIP_FLEET=false
DRY_RUN=false
AUTO_YES=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile|--env)
            PROFILE="$2"
            shift 2
            ;;
        --version|-v)
            VERSION_ARG="$2"
            shift 2
            ;;
        --companion-url)
            COMPANION_URL="$2"
            shift 2
            ;;
        --bootimus-user|--user)
            BOOTIMUS_USER="$2"
            shift 2
            ;;
        --bootimus-pass|--pass)
            BOOTIMUS_PASS="$2"
            shift 2
            ;;
        --bootimus-secret-method|--secret-method|--secret-provider|---secret-method|--bootimus-secret-provider)
            BOOTIMUS_SECRET_METHOD="$2"
            shift 2
            ;;
        --bootimus-secret-file|--secret-file)
            BOOTIMUS_SECRET_FILE="$2"
            shift 2
            ;;
        --api-key)
            API_KEY="$2"
            shift 2
            ;;
        --nodes|--targets|--ip)
            TARGET_NODES="$2"
            shift 2
            ;;
        --key|--ssh-key)
            SSH_KEY="$2"
            shift 2
            ;;
        --ssh-user)
            SSH_USER="$2"
            shift 2
            ;;
        --user)
            # Default to bootimus-user if specified, otherwise ssh-user
            BOOTIMUS_USER="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-auth|--skip-bootimus-auth)
            CHECK_AUTH=false
            shift
            ;;
        --skip-reboot)
            SKIP_REBOOT=true
            shift
            ;;
        --skip-fleet)
            SKIP_FLEET=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -y|--yes)
            AUTO_YES=true
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

# Load local environment defaults if present
if [[ -f "${REPO_ROOT}/src/build/local.env" ]]; then
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/src/build/local.env"
fi

COMPANION_URL="${COMPANION_URL:-${INSTALL_COMPANION_BASE:-https://gdc-companion.ensor-labs.com/}}"
API_KEY="${API_KEY:-${INSTALL_COMPANION_API_KEY:-}}"

# Resolve default SSH key path
if [[ -z "${SSH_KEY}" ]]; then
    if [[ -f "${HOME}/.ssh/gdc-disk-provisioner" ]]; then
        SSH_KEY="${HOME}/.ssh/gdc-disk-provisioner"
    elif [[ -f "${HOME}/.ssh/id_ed25519" ]]; then
        SSH_KEY="${HOME}/.ssh/id_ed25519"
    elif [[ -f "${HOME}/.ssh/id_rsa" ]]; then
        SSH_KEY="${HOME}/.ssh/id_rsa"
    fi
fi

# Resolve target ISO version
if [[ -n "${VERSION_ARG}" ]]; then
    TARGET_VERSION="${VERSION_ARG}"
elif [[ -f "${REPO_ROOT}/VERSION" ]]; then
    TARGET_VERSION="$(cat "${REPO_ROOT}/VERSION" | tr -d '[:space:]')"
else
    TARGET_VERSION="0.1.0"
fi

echo "=============================================================================="
echo " GDC FULL ENVIRONMENT REBUILD ORCHESTRATOR"
echo "=============================================================================="
printf "  %-25s %s\n" "Environment Profile:" "${PROFILE}"
printf "  %-25s %s\n" "Target ISO Version:" "${TARGET_VERSION}"
printf "  %-25s %s\n" "GDC Companion URL:" "${COMPANION_URL}"
printf "  %-25s %s\n" "SSH User:" "${SSH_USER}"
printf "  %-25s %s\n" "SSH Key:" "${SSH_KEY:-none found}"
printf "  %-25s %s\n" "Skip Build:" "${SKIP_BUILD}"
printf "  %-25s %s\n" "Skip Reboot:" "${SKIP_REBOOT}"
printf "  %-25s %s\n" "Dry-Run Mode:" "${DRY_RUN}"
echo "=============================================================================="

if [[ "${DRY_RUN}" != "true" && "${AUTO_YES}" != "true" ]]; then
    read -r -p "Are you sure you want to execute the rebuild cycle for '${PROFILE}'? (Y/n) " CONFIRM
    if [[ ! "${CONFIRM}" =~ ^([yY][eE][sS]|[yY]|"")$ ]]; then
        echo "Rebuild cycle aborted by user."
        exit 0
    fi
fi

# ==============================================================================
# PHASE 1: Pull Profile from GDC Companion
# ==============================================================================
echo -e "\n\033[1;34m[PHASE 1/4] Pulling Environment Profile from GDC Companion...\033[0m"
PROFILE_PULL_CMD=("${REPO_ROOT}/bin/local/gdc-node-ops.sh" "pull-profile" "--name" "${PROFILE}" "--companion-url" "${COMPANION_URL}")
if [[ -n "${API_KEY}" ]]; then
    PROFILE_PULL_CMD+=("--api-key" "${API_KEY}")
fi

echo "[-] Executing: ${PROFILE_PULL_CMD[*]}"
if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[DRY-RUN] Would fetch profile '${PROFILE}' into src/build/${PROFILE}.env"
else
    "${PROFILE_PULL_CMD[@]}"
fi

# Ingest pulled profile to resolve image prefixes and node IPs dynamically
PROFILE_ENV_FILE="${REPO_ROOT}/src/build/${PROFILE}.env"
if [[ -f "${PROFILE_ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${PROFILE_ENV_FILE}"
fi

# ==============================================================================
# PRE-FLIGHT GATE: Bootimus Authentication & Credential Verification
# ==============================================================================
if [[ "${CHECK_AUTH}" == "true" ]]; then
    echo -e "\n\033[1;34m[PRE-FLIGHT GATE] Verifying Bootimus PXE Credentials & Connectivity...\033[0m"
    BOOTIMUS_PREFLIGHT_ARGS=(--check-auth)
    [[ -n "${BOOTIMUS_USER}" ]] && BOOTIMUS_PREFLIGHT_ARGS+=(--user "${BOOTIMUS_USER}")
    [[ -n "${BOOTIMUS_PASS}" ]] && BOOTIMUS_PREFLIGHT_ARGS+=(--pass "${BOOTIMUS_PASS}")
    [[ -n "${BOOTIMUS_SECRET_METHOD}" ]] && BOOTIMUS_PREFLIGHT_ARGS+=(--secret-method "${BOOTIMUS_SECRET_METHOD}")
    [[ -n "${BOOTIMUS_SECRET_FILE}" ]] && BOOTIMUS_PREFLIGHT_ARGS+=(--secret-file "${BOOTIMUS_SECRET_FILE}")

    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "[DRY-RUN] Would test Bootimus authentication against '${PROFILE}' environment"
    else
        if ! ISO_ENVIRONMENT="${PROFILE}" "${REPO_ROOT}/bootimus.sh" "${BOOTIMUS_PREFLIGHT_ARGS[@]}"; then
            echo -e "\033[1;31m[!] PRE-FLIGHT ERROR: Bootimus authentication failed! Halting before Cloud Build.\033[0m" >&2
            echo "    Check BOOTIMUS_USER / BOOTIMUS_PASS, --secret-method, or pass --skip-auth to bypass." >&2
            exit 1
        fi
        echo -e "\033[1;32m[x] Bootimus credentials and endpoint connectivity verified.\033[0m"
    fi
else
    echo -e "\n\033[1;33m[PRE-FLIGHT GATE] Skipped Bootimus authentication check (--skip-auth active).\033[0m"
fi

ISO_PREFIX="${ISO_NAME_PREFIX:-gdc-bootstrap-ubuntu-24.04}"
IS_DEBUG="${GDC_DEBUG_MODE:-true}"
DEBUG_SUFFIX=""
if [[ "${IS_DEBUG}" == "true" ]]; then
    DEBUG_SUFFIX="-debug"
fi
TARGET_ISO_NAME="${ISO_PREFIX}-v${TARGET_VERSION}${DEBUG_SUFFIX}.iso"

# Resolve target nodes (precedence: CLI argument > profile TARGET_TEST_MACHINES > fallback)
if [[ -z "${TARGET_NODES}" && -n "${TARGET_TEST_MACHINES:-}" ]]; then
    TARGET_NODES="${TARGET_TEST_MACHINES}"
fi
TARGET_NODES_CSV="${TARGET_NODES// /,}"

echo "[-] Resolved Target ISO Name:  ${TARGET_ISO_NAME}"
echo "[-] Resolved Target Node Fleet: ${TARGET_NODES_CSV:-none specified}"

# ==============================================================================
# PHASE 2: Cloud Build ISO & Bootimus Deployment
# ==============================================================================
BOOTIMUS_PASSTHRU=()
[[ -n "${BOOTIMUS_USER}" ]] && BOOTIMUS_PASSTHRU+=(--bootimus-user "${BOOTIMUS_USER}")
[[ -n "${BOOTIMUS_PASS}" ]] && BOOTIMUS_PASSTHRU+=(--bootimus-pass "${BOOTIMUS_PASS}")
[[ -n "${BOOTIMUS_SECRET_METHOD}" ]] && BOOTIMUS_PASSTHRU+=(--bootimus-secret-method "${BOOTIMUS_SECRET_METHOD}")
[[ -n "${BOOTIMUS_SECRET_FILE}" ]] && BOOTIMUS_PASSTHRU+=(--bootimus-secret-file "${BOOTIMUS_SECRET_FILE}")
[[ "${CHECK_AUTH}" == "false" ]] && BOOTIMUS_PASSTHRU+=(--skip-auth)

if [[ "${SKIP_BUILD}" == "true" ]]; then
    echo -e "\n\033[1;33m[PHASE 2/4] Skipped (--skip-build specified).\033[0m"
else
    echo -e "\n\033[1;34m[PHASE 2/4] Compiling GDC ISO via Cloud Build with Bootimus Trigger...\033[0m"
    BUILD_CMD=("${REPO_ROOT}/build.sh" "--env" "${PROFILE}" "--version" "${TARGET_VERSION}" "--bootimus" "--yes" "--skip-increment" "${BOOTIMUS_PASSTHRU[@]}")
    echo "[-] Executing: ${BUILD_CMD[*]}"
    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "[DRY-RUN] Would trigger Cloud Build and await Bootimus extraction"
    else
        "${BUILD_CMD[@]}"
    fi
fi

# ==============================================================================
# PHASE 3: Bootimus Settlement & Verification Gate
# ==============================================================================
echo -e "\n\033[1;34m[PHASE 3/4] Verifying Bootimus PXE Registration & Extraction Gate...\033[0m"
BOOTIMUS_CHECK_ARGS=("${TARGET_ISO_NAME}")
[[ -n "${BOOTIMUS_USER}" ]] && BOOTIMUS_CHECK_ARGS+=(--user "${BOOTIMUS_USER}")
[[ -n "${BOOTIMUS_PASS}" ]] && BOOTIMUS_CHECK_ARGS+=(--pass "${BOOTIMUS_PASS}")
[[ -n "${BOOTIMUS_SECRET_METHOD}" ]] && BOOTIMUS_CHECK_ARGS+=(--secret-method "${BOOTIMUS_SECRET_METHOD}")
[[ -n "${BOOTIMUS_SECRET_FILE}" ]] && BOOTIMUS_CHECK_ARGS+=(--secret-file "${BOOTIMUS_SECRET_FILE}")

if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[DRY-RUN] Would verify '${TARGET_ISO_NAME}' via check-bootimus-settings.py and heal via bootimus.sh if required."
else
    BOOTIMUS_HEALTHY=false
    PYTHON_EXEC="python3"
    CHECK_SCRIPT="${REPO_ROOT}/test/bin/check-bootimus-settings.py"

    for attempt in {1..10}; do
        echo "[-] Running Bootimus verification audit (attempt ${attempt}/10)..."
        if ISO_ENVIRONMENT="${PROFILE}" "${PYTHON_EXEC}" "${CHECK_SCRIPT}" "${BOOTIMUS_CHECK_ARGS[@]}"; then
            echo -e "\033[1;32m[x] Bootimus settings verified and locked for ${TARGET_ISO_NAME}.\033[0m"
            BOOTIMUS_HEALTHY=true
            break
        fi

        echo "  [!] Bootimus verification not fully locked. Triggering explicit heal via bootimus.sh..."
        ISO_ENVIRONMENT="${PROFILE}" timeout 600s "${REPO_ROOT}/bootimus.sh" "${BOOTIMUS_CHECK_ARGS[@]}" || true
        sleep 15
    done

    if [[ "${BOOTIMUS_HEALTHY}" != "true" ]]; then
        echo -e "\033[1;31m[!] ERROR: Bootimus failed to verify extraction/settings for ${TARGET_ISO_NAME} after multiple attempts.\033[0m" >&2
        echo "    Aborting reset-pxe to prevent node boot loops." >&2
        exit 1
    fi
fi

# ==============================================================================
# PHASE 4: Schedule PXE Next-Boot and Reboot Nodes
# ==============================================================================
if [[ "${SKIP_REBOOT}" == "true" ]]; then
    echo -e "\n\033[1;33m[PHASE 4/4] Skipped node reboot (--skip-reboot specified).\033[0m"
elif [[ -z "${TARGET_NODES_CSV}" ]]; then
    echo -e "\n\033[1;33m[PHASE 4/4] Notice: No target nodes specified (TARGET_TEST_MACHINES empty). Skipping node reboot.\033[0m"
else
    echo -e "\n\033[1;34m[PHASE 4/4] Scheduling UEFI PXE Next-Boot and Rebooting Node Fleet...\033[0m"
    export ISO_ENVIRONMENT="${PROFILE}"
    [[ -n "${BOOTIMUS_SECRET_METHOD}" ]] && export BOOTIMUS_SECRET_METHOD="${BOOTIMUS_SECRET_METHOD}"
    [[ -n "${BOOTIMUS_USER}" ]] && export BOOTIMUS_USER="${BOOTIMUS_USER}"
    [[ -n "${BOOTIMUS_PASS}" ]] && export BOOTIMUS_PASS="${BOOTIMUS_PASS}"
    RESET_PXE_CMD=(
        "${REPO_ROOT}/bin/local/gdc-node-ops.sh" "reset-pxe"
        "--next-boot" "${TARGET_ISO_NAME}"
        "--nodes" "${TARGET_NODES_CSV}"
        "--user" "${SSH_USER}"
        "--yes"
    )
    if [[ -n "${SSH_KEY}" ]]; then
        RESET_PXE_CMD+=("--key" "${SSH_KEY}")
    fi
    if [[ "${SKIP_FLEET}" == "true" ]]; then
        RESET_PXE_CMD+=("--skip-fleet")
    fi
    [[ -n "${BOOTIMUS_SECRET_METHOD:-}" ]] && RESET_PXE_CMD+=(--secret-method "${BOOTIMUS_SECRET_METHOD}")
    [[ -n "${BOOTIMUS_USER:-}" ]] && RESET_PXE_CMD+=(--bootimus-user "${BOOTIMUS_USER}")
    [[ -n "${BOOTIMUS_PASS:-}" ]] && RESET_PXE_CMD+=(--bootimus-pass "${BOOTIMUS_PASS}")
    [[ -n "${BOOTIMUS_SECRET_FILE:-}" ]] && RESET_PXE_CMD+=(--secret-file "${BOOTIMUS_SECRET_FILE}")

    echo "[-] Executing: ${RESET_PXE_CMD[*]}"
    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "[DRY-RUN] Would execute reset-pxe across nodes: ${TARGET_NODES_CSV}"
    else
        "${RESET_PXE_CMD[@]}"
    fi
fi

echo -e "\n=============================================================================="
echo -e "\033[1;32m[SUCCESS] Full rebuild and redeploy cycle completed successfully!\033[0m"
echo "  ISO:   ${TARGET_ISO_NAME}"
echo "  Nodes: ${TARGET_NODES_CSV:-none}"
echo "=============================================================================="
exit 0
