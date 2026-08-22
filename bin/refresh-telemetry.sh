#!/usr/bin/env bash
# ==============================================================================
# GDC Node Telemetry Refresher
# ==============================================================================
# Forces a refresh of the gdc-collector telemetry on target nodes and pushes
# the updated payload to the GDC Companion App.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")
INSTALLER_USER="temporary-installer"
INSTALLER_PASS="gdc-password-123"

# Load environment configuration for Companion URL
if [ -f "$REPO_ROOT/src/build/local.env" ]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/src/build/local.env"
fi

# Fallback Companion URL if not found in local.env
COMPANION_BASE="${INSTALL_COMPANION_BASE:-https://gdc-companion.ensor-labs.com/}"
# Ensure trailing slash
[[ "${COMPANION_BASE}" != */ ]] && COMPANION_BASE="${COMPANION_BASE}/"
COMPANION_INGEST_URL="${COMPANION_BASE}v1/machine-reports/ingest"

# Determine target IPs
TARGET_IPS=()

if [ $# -eq 0 ]; then
    # Fallback to TARGET_TEST_MACHINES if no args provided
    if [[ -n "${TARGET_TEST_MACHINES:-}" ]]; then
        echo "[-] No IPs provided. Using TARGET_TEST_MACHINES..."
        # Clean up python list notation, brackets, quotes, and commas
        RAW_IPS=$(echo "${TARGET_TEST_MACHINES}" | tr -d "[]'\"" | tr ',' ' ')
        read -r -a TARGET_IPS <<< "$RAW_IPS"

        echo "=============================================================================="
        echo " Target machines in scope (from TARGET_TEST_MACHINES):"
        for ip in "${TARGET_IPS[@]}"; do
            echo "  - $ip"
        done
        echo "=============================================================================="
        read -p "Are you sure you want to proceed? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "[-] Aborted by user."
            exit 1
        fi
    else
        echo "Usage: $0 <ip-address> [ip-address-2] ..."
        echo "       Or set TARGET_TEST_MACHINES environment variable."
        exit 1
    fi
else
    TARGET_IPS=("$@")
fi

echo "====================================================="
echo "GDC Telemetry Refresher"
echo "Target Companion: $COMPANION_INGEST_URL"
echo "Target Nodes: ${TARGET_IPS[*]}"
echo "====================================================="

for IP in "${TARGET_IPS[@]}"; do
    echo -n "[-] Checking $IP... "
    
    # Fast ICMP check to prevent SSH hangs
    if ! ping -c 1 -W 1 "$IP" &>/dev/null; then
        echo -e "\e[31m[OFFLINE]\e[0m (Unreachable via ping)"
        continue
    fi

    # SSH into node and trigger collector
    if sshpass -p "$INSTALLER_PASS" ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no -o LogLevel=ERROR "${INSTALLER_USER}@${IP}" \
        "sudo /usr/local/bin/gdc-collector --companion-url='${COMPANION_INGEST_URL}'" > /dev/null 2>&1; then
        echo -e "\e[32m[SUCCESS]\e[0m Telemetry Refreshed"
    else
        echo -e "\e[31m[FAILED]\e[0m (SSH or execution error)"
    fi
done

echo "====================================================="
echo "Refresh cycle complete."