#!/usr/bin/env bash

# ==============================================================================
# GDC ISO Build - Pre-flight Hydrated Configuration Static Validator
# ==============================================================================
# Syntactically parses and lints all hydrated configs (cloud-init, netplan, systemd)
# and validates their schema alignment before assembly begins.
# ==============================================================================

set -euo pipefail

# Check for argument input
if [[ $# -lt 1 ]]; then
    echo "[!] Usage: $0 <EXTRACT_DIR>" >&2
    exit 1
fi

EXTRACT_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Locate virtual environment Python bin for library access (PyYAML, Jinja2)
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="python3"
fi

echo "=============================================================================="
echo "GDC Pre-flight Hydrated Config Static Validator (Upgraded)"
echo "=============================================================================="
echo "[-] Validating target workspace: ${EXTRACT_DIR}"
echo "[-] Using Python interpreter: ${PYTHON_BIN}"

SUCCESS=true

# ------------------------------------------------------------------------------
# 1. Validate YAML Syntax and Cloud-Init Schema of user-data
# ------------------------------------------------------------------------------
USER_DATA="${EXTRACT_DIR}/nocloud/user-data"
if [[ -f "${USER_DATA}" ]]; then
    echo "[-] Checking Cloud-Init Autoinstall user-data syntax & schema..."
    
    # Check basic YAML loading first
    if ! "${PYTHON_BIN}" -c "import yaml; yaml.safe_load(open('${USER_DATA}'))" &>/dev/null; then
        echo "[GDC-VALIDATE-FAIL] Critical: user-data is not a valid YAML file!" >&2
        "${PYTHON_BIN}" -c "import yaml; yaml.safe_load(open('${USER_DATA}'))" || true
        SUCCESS=false
    else
        echo "  [x] user-data YAML parsing successful."
    fi
    
    # Run official cloud-init schema validation with annotations if available
    if command -v cloud-init &>/dev/null; then
        # Use annotated schema validation as requested
        if ! cloud-init schema -c "${USER_DATA}" --annotate &>/dev/null; then
            echo "[GDC-VALIDATE-FAIL] Critical: user-data fails official Cloud-Init autoinstall schema checks!" >&2
            echo "[-] Detailed Annotated Schema Log:" >&2
            cloud-init schema -c "${USER_DATA}" --annotate || true
            SUCCESS=false
        else
            echo "  [x] user-data Cloud-Init autoinstall schema verified."
        fi
    else
        echo "  [!] Note: 'cloud-init' tool is not installed on the build host. Skipping schema check."
    fi
else
    echo "[GDC-VALIDATE-FAIL] Critical: Hydrated user-data file is missing at ${USER_DATA}!" >&2
    SUCCESS=false
fi

# ------------------------------------------------------------------------------
# 2. Validate YAML Syntax of Netplan template
# ------------------------------------------------------------------------------
NETPLAN_TEMPLATE="${EXTRACT_DIR}/custom-data/network-template.yaml"
if [[ -f "${NETPLAN_TEMPLATE}" ]]; then
    echo "[-] Checking Netplan network template YAML..."
    if ! "${PYTHON_BIN}" -c "import yaml; yaml.safe_load(open('${NETPLAN_TEMPLATE}'))" &>/dev/null; then
        echo "[GDC-VALIDATE-FAIL] Critical: Netplan network template has invalid YAML syntax!" >&2
        "${PYTHON_BIN}" -c "import yaml; yaml.safe_load(open('${NETPLAN_TEMPLATE}'))" || true
        SUCCESS=false
    else
        echo "  [x] Netplan network template syntax verified."
    fi
else
    echo "[GDC-VALIDATE-FAIL] Critical: Hydrated Netplan network template is missing at ${NETPLAN_TEMPLATE}!" >&2
    SUCCESS=false
fi

# ------------------------------------------------------------------------------
# 3. Validate Systemd Service Unit correctness using systemd-analyze
# ------------------------------------------------------------------------------
SYSTEMD_DIR="${EXTRACT_DIR}/custom-data/systemd"
echo "[-] Checking injected systemd service units with systemd-analyze..."
for service in gitea.service nexus.service gdc-provision.service gdc-provision.timer; do
    service_path="${SYSTEMD_DIR}/${service}"
    if [[ -f "${service_path}" ]]; then
        # Check that it contains standard systemd headers
        if ! grep -q "\[Unit\]" "${service_path}"; then
            echo "[GDC-VALIDATE-FAIL] Warning: Systemd unit ${service} is missing [Unit] section!" >&2
            SUCCESS=false
        else
            # Verify correctness using systemd-analyze if available
            if command -v systemd-analyze &>/dev/null; then
                if ! systemd-analyze verify "${service_path}" &>/dev/null; then
                    echo "[GDC-VALIDATE-FAIL] Warning: systemd-analyze verify flagged warnings for ${service}!" >&2
                    systemd-analyze verify "${service_path}" || true
                    # We make this a non-blocking check since some systems complain about missing dependencies in chroots
                else
                    echo "  [x] Verified systemd unit syntax: ${service}"
                fi
            else
                echo "  [x] Verified systemd unit headers: ${service}"
            fi
        fi
    else
        echo "[GDC-VALIDATE-FAIL] Critical: Required systemd unit ${service} is missing from ${SYSTEMD_DIR}!" >&2
        SUCCESS=false
    fi
done

# ------------------------------------------------------------------------------
# 4. Run Pylint on python build files
# ------------------------------------------------------------------------------
echo "[-] Checking Python build files using Pylint..."
if "${PYTHON_BIN}" -m pylint --version &>/dev/null; then
    # Validate render_templates.py and generate_banner.py with errors-only mode to prevent stylistic failures
    if ! "${PYTHON_BIN}" -m pylint --errors-only "${PROJECT_ROOT}/src/build/render_templates.py" "${PROJECT_ROOT}/src/build/generate_banner.py" &>/dev/null; then
        echo "[GDC-VALIDATE-FAIL] Critical: Pylint discovered errors in Python build scripts!" >&2
        "${PYTHON_BIN}" -m pylint --errors-only "${PROJECT_ROOT}/src/build/render_templates.py" "${PROJECT_ROOT}/src/build/generate_banner.py" || true
        SUCCESS=false
    else
        echo "  [x] Python files pylint validation passed successfully."
    fi
elif command -v pylint &>/dev/null; then
    # Validate render_templates.py and generate_banner.py with errors-only mode to prevent stylistic failures
    if ! pylint --errors-only "${PROJECT_ROOT}/src/build/render_templates.py" "${PROJECT_ROOT}/src/build/generate_banner.py" &>/dev/null; then
        echo "[GDC-VALIDATE-FAIL] Critical: Pylint discovered errors in Python build scripts!" >&2
        pylint --errors-only "${PROJECT_ROOT}/src/build/render_templates.py" "${PROJECT_ROOT}/src/build/generate_banner.py" || true
        SUCCESS=false
    else
        echo "  [x] Python files pylint validation passed successfully."
    fi
else
    echo "  [!] Note: 'pylint' is not installed locally. Skipping pylint verification."
fi

# ------------------------------------------------------------------------------
# 5. Run any custom extensible test files matching test/build-test/[stage-X]/*.py
# ------------------------------------------------------------------------------
BUILD_TEST_DIR="${PROJECT_ROOT}/test/build-test"
if [[ -d "${BUILD_TEST_DIR}" ]]; then
    echo "[-] Checking and executing custom stage test extensions under test/build-test/..."
    # Find all python test scripts recursively
    mapfile -t stage_tests < <(find "${BUILD_TEST_DIR}" -name "*.py" -type f 2>/dev/null)
    if [[ ${#stage_tests[@]} -gt 0 ]]; then
        for test_script in "${stage_tests[@]}"; do
            echo "  [-] Executing test extension: $(basename "${test_script}")..."
            if ! "${PYTHON_BIN}" "${test_script}" &>/dev/null; then
                echo "[GDC-VALIDATE-FAIL] Critical: Test extension ${test_script} failed!" >&2
                "${PYTHON_BIN}" "${test_script}" || true
                SUCCESS=false
            else
                echo "    [x] Passed."
            fi
        done
    else
        echo "  [-] No custom test extensions (*.py) found under ${BUILD_TEST_DIR}."
    fi
fi

# ==============================================================================
# Final Evaluation Gate
# ==============================================================================
if [[ "${SUCCESS}" = "false" ]]; then
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "[GDC-VALIDATE-FAIL] Validation gate failed! Compilation aborted."
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    exit 1
else
    echo "[GDC-VALIDATE-SUCCESS] All hydrated configuration validation gates passed cleanly."
    exit 0
fi
