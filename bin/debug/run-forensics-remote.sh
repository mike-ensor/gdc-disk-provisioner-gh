#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0


# ==============================================================================
# GDC Remote Forensics Orchestrator
# ==============================================================================
# Usage: ./bin/run-forensics-remote.sh <IP> <private_key_path>
# This script copies the forensics collector to the target, executes it,
# and pulls the resulting archive back to your local machine.
# ==============================================================================

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <IP> <private_key_path>"
    exit 1
fi

IP=$1
KEY=$2
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REMOTE_COLLECTOR="/tmp/collect-forensics.sh"
LOCAL_COLLECTOR="${SCRIPT_DIR}/collect-forensics.sh"

if [ ! -f "${LOCAL_COLLECTOR}" ]; then
    echo "[!] Error: Local collector script ${LOCAL_COLLECTOR} not found."
    exit 1
fi

echo "[-] Deploying forensics collector to ${IP}..."
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "${KEY}" "${LOCAL_COLLECTOR}" root@${IP}:"${REMOTE_COLLECTOR}"
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "${KEY}" root@${IP} "chmod +x ${REMOTE_COLLECTOR}"

echo "[-] Executing forensics collection on ${IP}..."
# Run the collector remotely
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "${KEY}" root@${IP} "${REMOTE_COLLECTOR}"

echo "[-] Pulling forensics archive back to local machine..."
# Pull the generated tar.gz
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "${KEY}" root@${IP}:/tmp/gdc-installer-forensics-*.tar.gz ./

echo "[-] Cleanup remote artifacts..."
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "${KEY}" root@${IP} "rm ${REMOTE_COLLECTOR} /tmp/gdc-installer-forensics-*.tar.gz"

echo "[x] Forensics collected successfully."
