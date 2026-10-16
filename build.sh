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
# GDC Bootloader - Unified ISO Build, Remastering & Release Orchestrator
# ==============================================================================
# Single canonical entry point for building, validating, and deploying custom
# GDC bootloader ISOs. Supports:
#   - Workstation pre-flight tests (Ansible syntax/lint + Python unit tests)
#   - Remote Cloud Build (default) or local workstation compilation (--local)
#   - Concurrent multi-target matrix builds (--concurrent "env:ver;env:ver;ver")
#   - Opt-in Bootimus PXE registration and setting verification (--bootimus)
#   - Automated build reporting and GCS publication
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# Global tracking variables for report compiling in cleanup trap
RECORDED_STATUS="FAILED"
COMPILED_TARGET_REPORTS=()

cleanup_and_report() {
    local exit_code=$?
    if [[ "${RECORDED_STATUS}" == "HELP" ]]; then
        return 0
    fi
    if [[ "${exit_code}" -eq 0 && "${RECORDED_STATUS}" == "SUCCESS" ]]; then
        echo -e "\n\033[92m[x] Build orchestrator finished successfully.\033[0m"
    elif [[ "${exit_code}" -ne 0 ]]; then
        echo -e "\n\033[91m[!] Build orchestrator exited with error code ${exit_code}.\033[0m" >&2
    fi
}
trap cleanup_and_report EXIT

# ==============================================================================
# Help Menus
# ==============================================================================
show_help() {
    RECORDED_STATUS="HELP"
    cat << 'EOF'
GDC ISO Build & Release Orchestrator

Usage: ./build.sh [OPTIONS]

Execution Modes:
  --cloud                     Build remotely using Google Cloud Build [DEFAULT]
  --local                     Build locally on this workstation using GNU Make
                              (Default: --cloud)

Target Selection:
  -c, --concurrent <matrix>   Build multiple ISO targets in parallel.
                              Syntax: "env:version;env:version;version"
                              Example: "honeywell:0.9.5;barn:0.9.1;0.8.5"
                              (Default: Single target from -e and -v)
  -e, --env <profile>         Target environment profile from src/build/<profile>.env
                              (Default: 'local' | Derived from $ISO_ENVIRONMENT)
  -v, --version <semver>      Target ISO version tag (e.g. 1.0.0)
                              (Default: current value in VERSION file | Derived from $ISO_VERSION)
  -p, --prefix <prefix>       Custom ISO name prefix string
                              (Default: from profile or 'gdc-bootstrap-ubuntu-24.04' | Derived from $ISO_NAME_PREFIX)

Testing & Pre-flight:
  --skip-tests                Skip local pre-flight checks (Ansible linting & Python tests)
                              (Default: false - tests ALWAYS run unless skipped)

PXE & Deployment:
  --bootimus                  Trigger Bootimus PXE registration and setting verification
                              (Default: false - Bootimus is NOT run unless explicitly passed)

Cloud & Storage Settings:
  -b, --bucket <name>         Destination GCS bucket name (sync/ and reports/)
                              (Default: 'gdc-disk-provisioner-isos' | Derived from $ISO_OUTPUT_BUCKET, $GCS_BUCKET)
  --source-bucket <name>      Source GCS bucket containing blessed source ISO
                              (Default: 'gdc-disk-provisioner-blessed-isos' | Derived from $ISO_BLESSED_GCS_BUCKET)
  -f, --filename <name>       Blessed source ISO filename
                              (Default: 'ubuntu-24.04.5-live-server-amd64.iso' | Derived from $SOURCE_ISO_FILENAME)
  --project <id>              Google Cloud Project ID
                              (Default: 'anthos-bare-metal-lab-1' | Derived from $PROJECT_ID)
  --region <region>           Google Cloud Region
                              (Default: 'us-west1' | Derived from $REGION)
  --builder-version <tag>     Builder container tag for Cloud Build
                              (Default: '0.0.90' | Derived from $BUILD_VERSION)

Build Modifiers:
  -s, --skip-increment        Do not auto-increment patch version in VERSION file
                              (Default: false for single builds, true for --concurrent)
  -y, --yes                   Skip interactive confirmation prompt
                              (Default: false | Derived from $AUTO_YES)
  -d, --debug                 Build with debug logging and console parameters
                              (Default: true | Derived from $GDC_DEBUG_MODE)
  -l, --companion <VAL>       GDC Companion telemetry: TRUE or FALSE
                              (Default: 'TRUE' | Derived from $GDC_COMPANION)
  -c-assets, --customer-assets <URI>
                              Customer-supplied assets tarball URI (GCS or HTTPS)
                              (Default: none | Derived from $CUSTOMER_ASSETS_URI)
  --dry-run                   Parse targets, display execution plan, and exit 0

Help:
  -h, --help                  Show this summary help menu
  --help-verbose              Show in-depth documentation and detailed workflow examples
EOF
    exit 0
}

show_help_verbose() {
    RECORDED_STATUS="HELP"
    cat << 'EOF'
==============================================================================
GDC ISO BUILD SYSTEM - IN-DEPTH GUIDE & WORKFLOW SCENARIOS
==============================================================================

The GDC ISO build system compiles, validates, and deploys offline-ready
remastered Ubuntu 24.04 ISOs for Google Distributed Cloud bare-metal nodes.

------------------------------------------------------------------------------
FLAG DERIVATION HIERARCHY
------------------------------------------------------------------------------
Configuration values resolve in the following priority order:
  1. Command-line flags (highest priority)
  2. Active shell environment variables
  3. Workspace '.envrc' file
  4. Selected environment file ('src/build/<profile>.env')
  5. Base defaults in 'src/build/build.env' and 'VERSION' file (lowest priority)

------------------------------------------------------------------------------
WORKFLOW SCENARIOS
------------------------------------------------------------------------------

1. DEFAULT SCENARIO (Zero-argument build)
   Command:
     $ ./build.sh

   What happens:
     a. Workstation Pre-flight Testing:
        - Runs './test/verify_ansible.sh' (static syntax & ansible-lint).
        - Runs 'python3 -m unittest discover -s test' (unit & template tests).
        - If any test fails, execution halts immediately on the workstation,
          preventing broken uploads to Cloud Build.
     b. Interactive Confirmation & Version Bump:
        - Displays build parameters and prompts: "Do you want to proceed? (yes/No)".
        - Upon confirmation, auto-increments the patch version in 'VERSION'
          and '.envrc' (e.g. 0.9.4 -> 0.9.5).
     c. Cloud Build Execution:
        - Checks GCS for collisions at 'gs://gdc-disk-provisioner-isos/sync/<ISO>'.
        - Submits Cloud Build job asynchronously using 'cloudbuild.yaml'.
        - Cloud Build compiles the ISO, runs CI/CD test gates, and uploads the ISO.
        - The local runner polls Cloud Build status every 15s until completion.
     d. Build Reports:
        - Automatically downloads canonical build reports from GCS to:
          build-workspace/output/build-report-local-v0.9.5.json (.md)
     e. Bootimus PXE:
        - SKIPPED by default (because '--bootimus' was not provided).

2. NORMAL / COMMON SCENARIOS

   Scenario A: Build a customer environment profile and deploy directly to PXE
     Command:
       $ ./build.sh --env honeywell --bootimus -y

     What happens:
       - Runs workstation pre-flight test suites.
       - Sources 'src/build/honeywell.env' (setting prefix 'honeywell-24.04'
         and Honeywell-specific network/credentials).
       - Automatically confirms (-y) and submits Cloud Build job.
       - Polls until ISO build finishes and downloads the build report.
        - Because '--bootimus' was passed, automatically triggers:
          1. './bootimus.sh honeywell-24.04-v<ver>-debug.iso'
          2. 'python3 test/bin/check-bootimus-settings.py' (verifies/locks PXE).
          3. './bootimus.sh --list' (prints boot menu tree).

   Scenario B: Rapid local workstation cycle (Offline / No Cloud Build)
     Command:
       $ ./build.sh --local --skip-tests --skip-increment

     What happens:
       - Skips pre-flight tests for fast iteration (--skip-tests).
       - Does not bump the version number (--skip-increment).
       - Runs 'make -C src/build all' locally on your workstation.
       - Generates the ISO in 'build-workspace/output/'.
       - Compiles and saves build reports.
       - Bootimus is skipped.

3. CONCURRENT / MATRIX SCENARIO (Multi-target parallel build)
   Command:
     $ ./build.sh --concurrent "honeywell:0.9.5;barn:0.9.1;0.8.5" --bootimus

   What happens:
     a. Matrix Parsing:
        - Discovers 3 distinct targets:
          Target 1: env='honeywell', version='0.9.5', prefix='honeywell-24.04'
          Target 2: env='barn',      version='0.9.1', prefix='gdc-labs-24.04'
          Target 3: env='local',     version='0.8.5', prefix='gdc-bootstrap-ubuntu-24.04'
     b. Pre-flight & Version Locks:
        - Runs pre-flight test suite ONCE for the workspace.
        - Disables auto-increment (versions 0.9.5, 0.9.1, 0.8.5 are explicitly pinned).
     c. Atomic Collision Check:
        - Checks GCS for all 3 target ISO names upfront before launching.
     d. Parallel Cloud Build Submission:
        - Evaluates each target in an isolated subshell so env variables do not leak.
        - Submits 3 independent Cloud Build jobs asynchronously in Google Cloud.
     e. Unified Concurrent Poller:
        - Monitors all 3 builds simultaneously in a single status table:
          [Attempt 12/90] honeywell(0.9.5): [WORKING] | barn(0.9.1): [WORKING] | base(0.8.5): [SUCCESS]
     f. Multi-Report Downloads:
        - Downloads build reports for each target:
          build-report-honeywell-v0.9.5.json
          build-report-barn-v0.9.1.json
          build-report-local-v0.8.5.json
     g. Multi-ISO Bootimus Ingestion:
        - Registers all 3 completed ISOs into Bootimus PXE sequentially.
        - Audits and locks PXE configurations for all three images.
        - Displays the updated Bootimus PXE boot menu.
==============================================================================
EOF
    exit 0
}

# ==============================================================================
# Helper: Environment File Sourcing
# ==============================================================================
source_env_safe() {
    local env_file="$1"
    local allow_override="${2:-false}"
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
                if [[ "${allow_override}" == "true" ]] || [[ -z "${!key:-}" ]]; then
                    export "${key}"="${val}"
                fi
            fi
        done < "${env_file}"
    fi
}

# ==============================================================================
# Step 1: Base Environment Loading
# ==============================================================================
ENVRC_FILE="${PROJECT_ROOT}/.envrc"
BUILD_ENV="${PROJECT_ROOT}/src/build/build.env"
DEPS_ENV="${PROJECT_ROOT}/src/dependencies.env"

[[ -f "${ENVRC_FILE}" ]] && source_env_safe "${ENVRC_FILE}" false
[[ -f "${DEPS_ENV}" ]] && source_env_safe "${DEPS_ENV}" false
[[ -f "${BUILD_ENV}" ]] && source_env_safe "${BUILD_ENV}" false

# Active baseline version from VERSION file
DEFAULT_FILE_VERSION=""
if [[ -f "${PROJECT_ROOT}/VERSION" ]]; then
    DEFAULT_FILE_VERSION=$(tr -d '[:space:]' < "${PROJECT_ROOT}/VERSION")
fi
BASE_ISO_VERSION="${DEFAULT_FILE_VERSION:-${ISO_VERSION:-1.0.0}}"

# ==============================================================================
# Step 2: Command-Line Argument Parsing
# ==============================================================================
BUILD_MODE="cloud"          # default to cloud
CONCURRENT_MATRIX=""
TARGET_ENV_ARG=""
TARGET_VERSION_ARG=""
TARGET_PREFIX_ARG=""
SKIP_TESTS=false
RUN_BOOTIMUS=false
SKIP_INCREMENT=false
AUTO_YES="${AUTO_YES:-false}"
DRY_RUN=false

CLI_BUCKET=""
CLI_SOURCE_BUCKET=""
CLI_FILENAME=""
CLI_PROJECT_ID=""
CLI_REGION=""
CLI_BUILD_VERSION=""
CLI_DEBUG=""
CLI_COMPANION=""
CLI_CUSTOMER_ASSETS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cloud)
            BUILD_MODE="cloud"
            shift
            ;;
        --local)
            BUILD_MODE="local"
            shift
            ;;
        -c|--concurrent)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --concurrent requires a target matrix argument." >&2
                exit 1
            fi
            CONCURRENT_MATRIX="$2"
            shift 2
            ;;
        -e|--env)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --env requires an environment profile name." >&2
                exit 1
            fi
            TARGET_ENV_ARG="$2"
            shift 2
            ;;
        -v|--version)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --version requires a version argument." >&2
                exit 1
            fi
            TARGET_VERSION_ARG="$2"
            shift 2
            ;;
        -p|--prefix)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --prefix requires a prefix value." >&2
                exit 1
            fi
            TARGET_PREFIX_ARG="$2"
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --bootimus)
            RUN_BOOTIMUS=true
            shift
            ;;
        -s|--skip-increment)
            SKIP_INCREMENT=true
            shift
            ;;
        -y|--yes)
            AUTO_YES=true
            shift
            ;;
        -d|--debug)
            CLI_DEBUG="true"
            shift
            ;;
        -l|--companion)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --companion requires TRUE or FALSE." >&2
                exit 1
            fi
            CLI_COMPANION="$2"
            shift 2
            ;;
        -b|--bucket)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --bucket requires a bucket name." >&2
                exit 1
            fi
            CLI_BUCKET="$2"
            shift 2
            ;;
        --source-bucket)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --source-bucket requires a bucket name." >&2
                exit 1
            fi
            CLI_SOURCE_BUCKET="$2"
            shift 2
            ;;
        -f|--filename)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --filename requires an ISO filename." >&2
                exit 1
            fi
            CLI_FILENAME="$2"
            shift 2
            ;;
        --project)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --project requires a project ID." >&2
                exit 1
            fi
            CLI_PROJECT_ID="$2"
            shift 2
            ;;
        --region)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --region requires a region." >&2
                exit 1
            fi
            CLI_REGION="$2"
            shift 2
            ;;
        --builder-version)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --builder-version requires a tag." >&2
                exit 1
            fi
            CLI_BUILD_VERSION="$2"
            shift 2
            ;;
        -c-assets|--customer-assets)
            if [[ $# -lt 2 ]]; then
                echo "[!] Error: --customer-assets requires a URI." >&2
                exit 1
            fi
            CLI_CUSTOMER_ASSETS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            ;;
        --help-verbose)
            show_help_verbose
            ;;
        *)
            echo "[!] Error: Unknown argument '$1'. Use --help for usage." >&2
            exit 1
            ;;
    esac
done

# ==============================================================================
# Step 3: Resolve Common Infrastructure Configurations
# ==============================================================================
PROJECT_ID="${CLI_PROJECT_ID:-${PROJECT_ID:-anthos-bare-metal-lab-1}}"
REGION="${CLI_REGION:-${REGION:-us-west1}}"
BUILD_VERSION="${CLI_BUILD_VERSION:-${BUILD_VERSION:-0.0.90}}"

RAW_BUCKET="${CLI_BUCKET:-${ISO_OUTPUT_BUCKET:-${GCS_BUCKET:-gdc-disk-provisioner-isos}}}"
GCS_BUCKET_NAME="${RAW_BUCKET#gs://}"

RAW_SOURCE_BUCKET="${CLI_SOURCE_BUCKET:-${ISO_BLESSED_GCS_BUCKET:-gdc-disk-provisioner-blessed-isos}}"
SOURCE_GCS_BUCKET_NAME="${RAW_SOURCE_BUCKET#gs://}"

SOURCE_ISO_FILENAME="${CLI_FILENAME:-${SOURCE_ISO_FILENAME:-ubuntu-24.04.5-live-server-amd64.iso}}"
GDC_DEBUG_MODE="${CLI_DEBUG:-${GDC_DEBUG_MODE:-true}}"
GDC_COMPANION_DEFAULT="${CLI_COMPANION:-${GDC_COMPANION:-TRUE}}"
CUSTOMER_ASSETS_URI="${CLI_CUSTOMER_ASSETS:-${CUSTOMER_ASSETS_URI:-}}"

# ==============================================================================
# Step 4: Parse Build Target Matrix
# ==============================================================================
# A build target structure holds:
#   env | version | prefix | companion | iso_name
declare -a TARGET_ENVS=()
declare -a TARGET_VERSIONS=()
declare -a TARGET_PREFIXES=()
declare -a TARGET_COMPANIONS=()
declare -a TARGET_ISO_NAMES=()

resolve_target_details() {
    local t_env="$1"
    local t_ver="$2"
    local t_comp="${3:-${GDC_COMPANION_DEFAULT}}"

    # Execute in subshell to guarantee zero environment leakage between targets
    (
        # If target env is 'base' or 'build' or 'default', do not load custom profile env
        if [[ "${t_env}" != "base" && "${t_env}" != "build" && "${t_env}" != "default" ]]; then
            env_file="${PROJECT_ROOT}/src/build/${t_env}.env"
            # shellcheck source=/dev/null
            [[ -f "${env_file}" ]] && source "${env_file}"
        else
            # Ensure base prefix is restored from build.env
            ISO_NAME_PREFIX="gdc-bootstrap-ubuntu-24.04"
        fi

        # Resolve prefix
        prefix="${TARGET_PREFIX_ARG:-${ISO_NAME_PREFIX:-gdc-bootstrap-ubuntu-24.04}}"
        
        # Companion suffix
        comp_suffix=""
        if [[ "${t_comp^^}" =~ ^(FALSE|0|NO)$ ]]; then
            comp_suffix="-no-comp"
        fi

        # Debug suffix
        debug_suffix=""
        if [[ "${GDC_DEBUG_MODE}" == "true" ]]; then
            debug_suffix="-debug"
        fi

        iso_name="${prefix}-v${t_ver}${comp_suffix}${debug_suffix}.iso"

        # Output tab-separated tuple
        printf "%s\t%s\t%s\t%s\t%s\n" "${t_env}" "${t_ver}" "${prefix}" "${t_comp}" "${iso_name}"
    )
}

if [[ -n "${CONCURRENT_MATRIX}" ]]; then
    # Concurrent matrix build specified: disable auto-increment on disk
    SKIP_INCREMENT=true

    # Normalize delimiters: replace commas with semicolons
    NORMALIZED_MATRIX="${CONCURRENT_MATRIX//,/;}"
    IFS=';' read -ra TOKENS <<< "${NORMALIZED_MATRIX}"

    for token in "${TOKENS[@]}"; do
        # Trim leading/trailing whitespace
        item=$(echo "${token}" | xargs)
        [[ -z "${item}" ]] && continue

        if [[ "${item}" =~ ^([^:]+):([^:]+)$ ]]; then
            m_env="${BASH_REMATCH[1]}"
            m_ver="${BASH_REMATCH[2]}"
        elif [[ "${item}" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
            m_env="base"
            m_ver="${item}"
        else
            m_env="${item}"
            m_ver="${BASE_ISO_VERSION}"
        fi

        # Verify environment file exists if not base/build
        if [[ "${m_env}" != "base" && "${m_env}" != "build" && "${m_env}" != "default" && "${m_env}" != "local" && ! -f "${PROJECT_ROOT}/src/build/${m_env}.env" ]]; then
            echo "[!] Error: Environment file '${PROJECT_ROOT}/src/build/${m_env}.env' not found for target '${item}'" >&2
            exit 1
        fi

        resolved=$(resolve_target_details "${m_env}" "${m_ver}")
        IFS=$'\t' read -r r_env r_ver r_pref r_comp r_isoname <<< "${resolved}"

        TARGET_ENVS+=("${r_env}")
        TARGET_VERSIONS+=("${r_ver}")
        TARGET_PREFIXES+=("${r_pref}")
        TARGET_COMPANIONS+=("${r_comp}")
        TARGET_ISO_NAMES+=("${r_isoname}")
    done
else
    # Single target build
    s_env="${TARGET_ENV_ARG:-${ISO_ENVIRONMENT:-local}}"
    s_ver="${TARGET_VERSION_ARG:-${BASE_ISO_VERSION}}"

    if [[ "${s_env}" != "local" && ! -f "${PROJECT_ROOT}/src/build/${s_env}.env" ]]; then
        echo "[!] Error: Environment file '${PROJECT_ROOT}/src/build/${s_env}.env' not found." >&2
        exit 1
    fi

    # Handle single-target auto-increment if allowed and no custom version given
    if [[ "${SKIP_INCREMENT}" != "true" && -z "${TARGET_VERSION_ARG}" ]]; then
        if [[ "${s_ver}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
            major="${BASH_REMATCH[1]}"
            minor="${BASH_REMATCH[2]}"
            patch="${BASH_REMATCH[3]}"
            s_ver="${major}.${minor}.$((patch + 1))"
            NEXT_INCREMENTED_VERSION="${s_ver}"
        fi
    fi

    resolved=$(resolve_target_details "${s_env}" "${s_ver}")
    IFS=$'\t' read -r r_env r_ver r_pref r_comp r_isoname <<< "${resolved}"

    TARGET_ENVS+=("${r_env}")
    TARGET_VERSIONS+=("${r_ver}")
    TARGET_PREFIXES+=("${r_pref}")
    TARGET_COMPANIONS+=("${r_comp}")
    TARGET_ISO_NAMES+=("${r_isoname}")
fi

if [[ ${#TARGET_ENVS[@]} -eq 0 ]]; then
    echo "[!] Error: No valid build targets were resolved." >&2
    exit 1
fi

# ==============================================================================
# Step 5: Summary Banner & Interactive Confirmation
# ==============================================================================
echo "=============================================================================="
echo -e "\033[93m\033[1mGDC ISO BUILD & RELEASE ORCHESTRATOR\033[0m"
echo "=============================================================================="
echo "  Execution Mode:     ${BUILD_MODE^^}"
echo "  Run Pre-flight:     $([[ "${SKIP_TESTS}" == "true" ]] && echo "NO (--skip-tests)" || echo "YES")"
echo "  Deploy to Bootimus: $([[ "${RUN_BOOTIMUS}" == "true" ]] && echo "YES (--bootimus active)" || echo "NO")"
echo "  GCP Project ID:     ${PROJECT_ID}"
echo "  GCP Region:         ${REGION}"
echo "  Builder Container:  ${BUILD_VERSION}"
echo "  Destination Bucket: gs://${GCS_BUCKET_NAME}"
echo "  Source Bucket:      gs://${SOURCE_GCS_BUCKET_NAME}"
echo "  Source ISO Name:    ${SOURCE_ISO_FILENAME}"
echo "  Debug ISO Mode:     ${GDC_DEBUG_MODE}"
echo "------------------------------------------------------------------------------"
echo "  Target Count:       ${#TARGET_ENVS[@]}"
for i in "${!TARGET_ENVS[@]}"; do
    echo "  [Target $((i + 1))] Env: ${TARGET_ENVS[$i]} | Ver: ${TARGET_VERSIONS[$i]} | Companion: ${TARGET_COMPANIONS[$i]} | Output: ${TARGET_ISO_NAMES[$i]}"
done
echo "=============================================================================="

if [[ "${DRY_RUN}" == "true" ]]; then
    echo -e "\033[92m[x] DRY-RUN SUCCESS: Build plan parsed cleanly. Exiting without execution.\033[0m"
    RECORDED_STATUS="SUCCESS"
    exit 0
fi

# ==============================================================================
# Step 6: Workstation Pre-flight Testing Gate
# ==============================================================================
if [[ "${SKIP_TESTS}" != "true" ]]; then
    echo -e "\n\033[93m\033[1m[STAGE: PRE-FLIGHT] RUNNING WORKSTATION VALIDATION & TEST SUITES...\033[0m"
    echo "------------------------------------------------------------------------------"
    
    echo "[-] Gate 1/2: Validating Ansible playbooks & roles (verify_ansible.sh)..."
    if ! "${PROJECT_ROOT}/test/verify_ansible.sh"; then
        echo -e "\033[91m[!] Pre-flight failure: Ansible verification failed! Halting build.\033[0m" >&2
        exit 1
    fi
    echo "  [x] Ansible playbooks and roles passed linting and syntax checks."

    echo "[-] Gate 2/2: Executing Python test suite (unittest discover -s test)..."
    if ! "${PYTHON_BIN}" -m unittest discover -s "${PROJECT_ROOT}/test"; then
        echo -e "\033[91m[!] Pre-flight failure: Unit tests failed! Halting build.\033[0m" >&2
        exit 1
    fi
    echo "  [x] Python test suites passed cleanly."
    echo -e "\033[92m[x] All pre-flight gates passed successfully.\033[0m\n"
else
    echo -e "\n\033[93m[!] NOTICE: Skipping local pre-flight checks (--skip-tests active).\033[0m\n"
fi

# ==============================================================================
# Step 7: GCS Collision Checks
# ==============================================================================
if [[ "${BUILD_MODE}" == "cloud" ]]; then
    echo "[-] Verifying destination GCS bucket for filename collisions..."
    for iso_name in "${TARGET_ISO_NAMES[@]}"; do
        if gcloud storage objects describe "gs://${GCS_BUCKET_NAME}/sync/${iso_name}" --project="${PROJECT_ID}" &>/dev/null; then
            echo -e "\033[91m[!] Collision Error: GCS target 'gs://${GCS_BUCKET_NAME}/sync/${iso_name}' already exists!\033[0m" >&2
            echo "[!] Please increment version or check GCS state." >&2
            exit 1
        fi
        echo "  [x] No collision: '${iso_name}' is unique."
    done
fi

# ==============================================================================
# Step 8: User Confirmation & Version File Update
# ==============================================================================
if [[ "${AUTO_YES}" != "true" && -t 0 ]]; then
    read -r -p "Do you want to proceed with the build? (yes/No) " CONFIRM_PROCEED
    case "${CONFIRM_PROCEED}" in
        [yY][eE][sS]|[yY])
            echo "[-] Proceeding with build..."
            ;;
        *)
            echo "Build aborted by user."
            RECORDED_STATUS="ABORTED"
            exit 0
            ;;
    esac
fi

# Update VERSION and .envrc if single target auto-increment occurred
if [[ -n "${NEXT_INCREMENTED_VERSION:-}" ]]; then
    echo "${NEXT_INCREMENTED_VERSION}" > "${PROJECT_ROOT}/VERSION"
    echo "[-] Updated VERSION file to ${NEXT_INCREMENTED_VERSION}."
    if [[ -f "${ENVRC_FILE}" ]]; then
        sed -i "s/export ISO_VERSION=.*/export ISO_VERSION=\"${NEXT_INCREMENTED_VERSION}\"/g" "${ENVRC_FILE}"
        echo "[-] Updated ${ENVRC_FILE}."
    fi
fi

# ==============================================================================
# Step 9: Build Execution (Cloud Build OR Local Make)
# ==============================================================================
declare -a RUNNING_BUILD_IDS=()
declare -a FAILED_TARGETS=()
declare -a SUCCESSFUL_ISOS=()

GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "N/A")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "N/A")

if [[ "${BUILD_MODE}" == "cloud" ]]; then
    echo -e "\n\033[93m\033[1m[STAGE: CLOUD BUILD] SUBMITTING JOBS TO GOOGLE CLOUD BUILD...\033[0m"
    echo "------------------------------------------------------------------------------"

    for i in "${!TARGET_ENVS[@]}"; do
        t_env="${TARGET_ENVS[$i]}"
        t_ver="${TARGET_VERSIONS[$i]}"
        t_pref="${TARGET_PREFIXES[$i]}"
        t_comp="${TARGET_COMPANIONS[$i]}"
        t_iso="${TARGET_ISO_NAMES[$i]}"

        echo "[-] Submitting Cloud Build for Target $((i + 1)): [${t_env} | v${t_ver} | ${t_iso}]..."

        # Extract environment variables in a subshell for substitutions
        sub_vars=$(
            (
                # shellcheck source=/dev/null
                [[ -f "${PROJECT_ROOT}/src/dependencies.env" ]] && source "${PROJECT_ROOT}/src/dependencies.env"
                # shellcheck source=/dev/null
                [[ -f "${PROJECT_ROOT}/src/build/build.env" ]] && source "${PROJECT_ROOT}/src/build/build.env"
                # shellcheck source=/dev/null
                [[ -f "${PROJECT_ROOT}/src/build/${t_env}.env" ]] && source "${PROJECT_ROOT}/src/build/${t_env}.env"
                
                printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
                    "${INSTALL_COMPANION_URL:-}" \
                    "${ADMIN_SSH_PUB_KEYS:-}" \
                    "${TEMPORARY_INSTALLER_SSH_PUB_KEYS:-}" \
                    "${TEMPORARY_INSTALLER_PASSWORD:-}" \
                    "${DEBUG_EXTRA_USER:-}" \
                    "${DEBUG_EXTRA_PASSWORD:-}"
            )
        )
        IFS=$'\t' read -r s_comp_url s_admin_ssh s_temp_ssh s_temp_pass s_dbg_usr s_dbg_pass <<< "${sub_vars}"

        b_id=$(gcloud builds submit "${PROJECT_ROOT}" \
            --config="${PROJECT_ROOT}/cloudbuild.yaml" \
            --project="${PROJECT_ID}" \
            --substitutions="^@@^_GCS_BUCKET_NAME=${GCS_BUCKET_NAME}@@_ISO_VERSION=${t_ver}@@_SOURCE_ISO_FILENAME=${SOURCE_ISO_FILENAME}@@_BUILD_VERSION=${BUILD_VERSION}@@_REGION=${REGION}@@_PROJECT_ID=${PROJECT_ID}@@_ISO_BLESSED_GCS_BUCKET=${SOURCE_GCS_BUCKET_NAME}@@_GDC_DEBUG_MODE=${GDC_DEBUG_MODE}@@_CUSTOMER_ASSETS_URI=${CUSTOMER_ASSETS_URI}@@_GIT_BRANCH=${GIT_BRANCH}@@_GIT_COMMIT=${GIT_COMMIT}@@_INSTALL_COMPANION_URL=${s_comp_url}@@_ADMIN_SSH_PUB_KEYS=${s_admin_ssh}@@_TEMPORARY_INSTALLER_SSH_PUB_KEYS=${s_temp_ssh}@@_TEMPORARY_INSTALLER_PASSWORD=${s_temp_pass}@@_GDC_COMPANION=${t_comp}@@_DEBUG_EXTRA_USER=${s_dbg_usr}@@_DEBUG_EXTRA_PASSWORD=${s_dbg_pass}@@_ISO_ENVIRONMENT=${t_env}@@_ISO_NAME_PREFIX=${t_pref}" \
            --async --format="value(id)")

        echo "  [+] Launched! Build ID: ${b_id}"
        RUNNING_BUILD_IDS+=("${b_id}")
    done

    # Save tracking file to .cache/build-state.json
    mkdir -p "${PROJECT_ROOT}/.cache"
    "${PYTHON_BIN}" -c '
import json, sys
data = {
    "project_id": sys.argv[1],
    "builds": []
}
envs = sys.argv[2].split(";")
vers = sys.argv[3].split(";")
isos = sys.argv[4].split(";")
bids = sys.argv[5].split(";")
for i in range(len(bids)):
    data["builds"].append({
        "env": envs[i],
        "version": vers[i],
        "iso_name": isos[i],
        "build_id": bids[i],
        "status": "WORKING"
    })
with open(sys.argv[6], "w") as f:
    json.dump(data, f, indent=2)
' "${PROJECT_ID}" \
  "$(IFS=';'; echo "${TARGET_ENVS[*]}")" \
  "$(IFS=';'; echo "${TARGET_VERSIONS[*]}")" \
  "$(IFS=';'; echo "${TARGET_ISO_NAMES[*]}")" \
  "$(IFS=';'; echo "${RUNNING_BUILD_IDS[*]}")" \
  "${PROJECT_ROOT}/.cache/build-state.json"

    echo -e "\n[-] Monitoring active Cloud Build jobs concurrently..."
    echo "=============================================================================="

    # Tracking arrays for poller
    declare -a JOB_STATUSES=()
    for _ in "${RUNNING_BUILD_IDS[@]}"; do
        JOB_STATUSES+=("WORKING")
    done

    ALL_COMPLETED=false
    for attempt in {1..90}; do
        STATUS_SUMMARY=""
        ALL_COMPLETED=true

        for i in "${!RUNNING_BUILD_IDS[@]}"; do
            b_id="${RUNNING_BUILD_IDS[$i]}"
            cur_stat="${JOB_STATUSES[$i]}"

            if [[ "${cur_stat}" != "SUCCESS" && ! "${cur_stat}" =~ ^(FAILURE|TIMEOUT|CANCELLED)$ ]]; then
                new_stat=$(gcloud builds describe "${b_id}" --project="${PROJECT_ID}" --format="value(status)" 2>/dev/null || echo "UNKNOWN")
                JOB_STATUSES[$i]="${new_stat}"
                cur_stat="${new_stat}"
            fi

            STATUS_SUMMARY+="${TARGET_ENVS[$i]}[${TARGET_VERSIONS[$i]}]: ${cur_stat} | "

            if [[ "${cur_stat}" != "SUCCESS" && ! "${cur_stat}" =~ ^(FAILURE|TIMEOUT|CANCELLED)$ ]]; then
                ALL_COMPLETED=false
            fi
        done

        STATUS_SUMMARY="${STATUS_SUMMARY% | }"
        echo "  [Poll ${attempt}/90] ${STATUS_SUMMARY}"

        if [[ "${ALL_COMPLETED}" == "true" ]]; then
            break
        fi
        sleep 15
    done

    echo "=============================================================================="

    # Inspect results
    mkdir -p "${PROJECT_ROOT}/build-workspace/output"
    for i in "${!RUNNING_BUILD_IDS[@]}"; do
        t_env="${TARGET_ENVS[$i]}"
        t_ver="${TARGET_VERSIONS[$i]}"
        t_iso="${TARGET_ISO_NAMES[$i]}"
        b_id="${RUNNING_BUILD_IDS[$i]}"
        status="${JOB_STATUSES[$i]}"

        report_base="build-report-${t_env}-v${t_ver}"

        if [[ "${status}" == "SUCCESS" ]]; then
            echo -e "\033[92m  [x] Target $((i + 1)) [${t_env} | v${t_ver}]: SUCCESS\033[0m"
            SUCCESSFUL_ISOS+=("${t_iso}")

            # Download canonical build reports from GCS
            echo "      Downloading reports for ${report_base}..."
            gcloud storage cp "gs://${GCS_BUCKET_NAME}/reports/build-reports/${report_base}.json" "${PROJECT_ROOT}/build-workspace/output/" 2>/dev/null || true
            gcloud storage cp "gs://${GCS_BUCKET_NAME}/reports/build-reports/${report_base}.md" "${PROJECT_ROOT}/build-workspace/output/" 2>/dev/null || true
        else
            echo -e "\033[91m  [!] Target $((i + 1)) [${t_env} | v${t_ver}]: FAILED (${status})\033[0m" >&2
            FAILED_TARGETS+=("${t_iso}")

            # Stream failure log
            echo "[-] Streaming Cloud Build failure logs for ${b_id}..." >&2
            gcloud builds log "${b_id}" --project="${PROJECT_ID}" 2>&1 | tail -n 60 >&2 || true

            # Compile failure report
            "${PYTHON_BIN}" "${PROJECT_ROOT}/test/bin/generate_build_report.py" \
                --build-id "${b_id}" \
                --project-id "${PROJECT_ID}" \
                --gcs-bucket "gs://${GCS_BUCKET_NAME}" \
                --iso-version "${t_ver}" \
                --iso-environment "${t_env}" \
                --iso-name "${t_iso}" \
                --status "FAILED" \
                --output-dir "${PROJECT_ROOT}/build-workspace/output" \
                --upload 2>/dev/null || true
        fi
    done

    if [[ ${#FAILED_TARGETS[@]} -gt 0 ]]; then
        echo -e "\033[91m[!] Build pipeline failed for ${#FAILED_TARGETS[@]} target(s).\033[0m" >&2
        exit 1
    fi

else
    # Local Workstation Build via Make
    echo -e "\n\033[93m\033[1m[STAGE: LOCAL BUILD] EXECUTING MAKE TARGETS SEQUENTIALLY...\033[0m"
    echo "------------------------------------------------------------------------------"

    for i in "${!TARGET_ENVS[@]}"; do
        t_env="${TARGET_ENVS[$i]}"
        t_ver="${TARGET_VERSIONS[$i]}"
        t_iso="${TARGET_ISO_NAMES[$i]}"
        t_comp="${TARGET_COMPANIONS[$i]}"

        echo -e "\n[-] [Local Build $((i + 1))/${#TARGET_ENVS[@]}] Starting Make for ${t_env} (v${t_ver})..."

        # Clean prior extraction workspace to ensure no file clobbering
        make -C "${PROJECT_ROOT}/src/build" clean

        if make -C "${PROJECT_ROOT}/src/build" all \
            ISO_VERSION="${t_ver}" \
            ISO_ENVIRONMENT="${t_env}" \
            GDC_DEBUG_MODE="${GDC_DEBUG_MODE}" \
            GDC_COMPANION="${t_comp}" \
            ENABLE_GCS="false"; then
            
            echo -e "\033[92m  [x] Local Make succeeded for ${t_iso}\033[0m"
            SUCCESSFUL_ISOS+=("${t_iso}")

            # Compile local report
            "${PYTHON_BIN}" "${PROJECT_ROOT}/test/bin/generate_build_report.py" \
                --local \
                --iso-version "${t_ver}" \
                --iso-environment "${t_env}" \
                --iso-name "${t_iso}" \
                --status "SUCCESS" \
                --gcs-bucket "gs://${GCS_BUCKET_NAME}" 2>/dev/null || true
        else
            echo -e "\033[91m  [!] Local Make failed for ${t_iso}\033[0m" >&2
            FAILED_TARGETS+=("${t_iso}")

            "${PYTHON_BIN}" "${PROJECT_ROOT}/test/bin/generate_build_report.py" \
                --local \
                --iso-version "${t_ver}" \
                --iso-environment "${t_env}" \
                --iso-name "${t_iso}" \
                --status "FAILED" \
                --gcs-bucket "gs://${GCS_BUCKET_NAME}" 2>/dev/null || true
            exit 1
        fi
    done
fi

RECORDED_STATUS="SUCCESS"

# ==============================================================================
# Step 10: Bootimus PXE Registration (Opt-In via --bootimus)
# ==============================================================================
if [[ "${RUN_BOOTIMUS}" == "true" ]]; then
    echo -e "\n=============================================================================="
    echo -e "\033[93m\033[1m[STAGE: BOOTIMUS] INGESTING & PROVISIONING ISO(S) IN BOOTIMUS PXE...\033[0m"
    echo "=============================================================================="

    for i in "${!SUCCESSFUL_ISOS[@]}"; do
        iso_name="${SUCCESSFUL_ISOS[$i]}"
        # Find corresponding environment profile
        t_env="local"
        for j in "${!TARGET_ISO_NAMES[@]}"; do
            if [[ "${TARGET_ISO_NAMES[$j]}" == "${iso_name}" ]]; then
                t_env="${TARGET_ENVS[$j]}"
                break
            fi
        done
        echo "[-] Deploying to Bootimus: ${iso_name} (profile: ${t_env})..."
        ISO_ENVIRONMENT="${t_env}" PYTHON_BIN="${PYTHON_BIN}" timeout 1200s "${PROJECT_ROOT}/bootimus.sh" "${iso_name}" || true
    done

    echo "[-] Running Bootimus stability auditor & settings healer..."
    BOOTIMUS_VERIFIED=false
    for i in {1..80}; do
        if "${PYTHON_BIN}" "${PROJECT_ROOT}/test/bin/check-bootimus-settings.py" "${SUCCESSFUL_ISOS[@]}"; then
            echo -e "\033[92m[x] Bootimus configuration locked and verified successfully.\033[0m"
            BOOTIMUS_VERIFIED=true
            break
        fi
        echo "    Waiting 15s for backend extraction to settle... ($i/80)"
        sleep 15
    done

    if [[ "${BOOTIMUS_VERIFIED}" != "true" ]]; then
        echo -e "\033[91m[!] Error: Bootimus failed to lock boot parameters for target ISOs within allotted timeout.\033[0m" >&2
        exit 1
    fi

    echo "[-] Querying current Bootimus boot menu tree:"
    PYTHON_BIN="${PYTHON_BIN}" "${PROJECT_ROOT}/bootimus.sh" --list || true
    echo -e "\033[92m[x] Bootimus deployment complete for all targets.\033[0m"
else
    echo -e "\n[-] Notice: Bootimus deployment skipped (pass --bootimus to enable)."
fi

echo -e "\n=============================================================================="
echo -e "\033[92m\033[1m[x] GDC ISO PIPELINE COMPLETED SUCCESSFULLY FOR ALL TARGETS!\033[0m"
echo "=============================================================================="
exit 0
