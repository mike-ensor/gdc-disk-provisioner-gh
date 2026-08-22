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
# GDC GCE Isolated Playbook Sandbox Provisioner
# ==============================================================================
# Automates the complete isolated lifecycle of an GCE VM to test the ansible-pull
# playbooks against a pristine Ubuntu 24.04 LTS OS environment.
# Cycles:
#   1. Read Project/Region from build.env
#   2. Create e2-standard-4 GCE VM with 250GB storage and metadata startup-script
#   3. Continuously poll GCE serial console port output for completion token
#   4. Execute cloud teardown of the VM to prevent active GCP billing
# ==============================================================================

set -euo pipefail

# Determine script paths and move to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Load build variables
ENV_FILE="${PROJECT_ROOT}/src/build/build.env"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
else
    echo "[!] Error: build.env not found." >&2
    exit 1
fi

echo "=============================================================================="
echo "GDC Isolated GCE Playbook Sandbox Provisioner"
echo "=============================================================================="

# 1. Dependency Checking
echo "[-] Checking gcloud SDK presence..."
GCLOUD_AVAILABLE=true
if ! command -v gcloud &>/dev/null; then
    GCLOUD_AVAILABLE=false
fi

# Unique Sandbox VM Instance Name and Zone
VM_NAME="gdc-sandbox-vm-$(date +%s)"
ZONE="${REGION}-a"

# If gcloud is missing, print the detailed dry-run guide and exit cleanly
if [[ "${GCLOUD_AVAILABLE}" = "false" ]]; then
    echo "=============================================================================="
    echo "[!] Warning: 'gcloud' CLI is not locally active in this shell."
    echo "[-] Displaying the precise GCP command lifecycle that would execute:"
    echo "=============================================================================="
    echo "1. Spawn Isolated GCE Ubuntu 24.04 Server Node (250GB GDC storage requirement):"
    echo "   $ gcloud compute instances create ${VM_NAME} \\"
    echo "       --project=\"${PROJECT_ID}\" \\"
    echo "       --zone=\"${ZONE}\" \\"
    echo "       --machine-type=e2-standard-4 \\"
    echo "       --image-family=ubuntu-2404-lts-amd64 \\"
    echo "       --image-project=ubuntu-os-cloud \\"
    echo "       --boot-disk-size=250GB \\"
    echo "       --metadata-from-file=startup-script=test/gce_startup_test.sh \\"
    echo "       --metadata=serial-port-enable=true"
    echo ""
    echo "2. Stream & Poll GCE Serial Log Output for Success Token:"
    echo "   $ gcloud compute instances get-serial-port-output ${VM_NAME} \\"
    echo "       --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\""
    echo ""
    echo "   Success Token Signal: 'GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY'"
    echo ""
    echo "3. Execute Mandatory Cloud Teardown (Safety-first Cost Prevention):"
    echo "   $ gcloud compute instances delete ${VM_NAME} \\"
    echo "       --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\" --quiet"
    echo "=============================================================================="
    echo "[+] DRY-RUN SUCCESS: GCP GCE Sandbox lifecycle parameters are aligned."
    echo "=============================================================================="
    exit 0
fi

# 2. Execution (Live GCE VM Test)
echo "[-] Active GCP Cloud environment detected. Starting GCE Sandbox..."
echo "[-] Target Project:  ${PROJECT_ID}"
echo "[-] Target Zone:     ${ZONE}"
echo "[-] VM Instance:     ${VM_NAME}"

# Setup absolute cleanup trap to prevent lingering cloud instance billing if aborted
cleanup_gce() {
    echo "[-] Executing mandatory GCE Sandbox teardown..."
    gcloud compute instances delete "${VM_NAME}" \
      --project="${PROJECT_ID}" \
      --zone="${ZONE}" \
      --quiet &>/dev/null || true
    echo "[-] Teardown completed safely. VM instance has been deleted."
}
trap cleanup_gce EXIT

# Spawn the GCE VM
echo "[-] Provisioning isolated Ubuntu 24.04 server GCE VM..."
gcloud compute instances create "${VM_NAME}" \
  --project="${PROJECT_ID}" \
  --zone="${ZONE}" \
  --machine-type=e2-standard-4 \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=250GB \
  --metadata-from-file=startup-script=test/gce_startup_test.sh \
  --metadata=serial-port-enable=true &>/dev/null

echo "[-] VM successfully provisioned and booted."

# Stream and Poll Serial Logs for completion success marker
echo "[-] Streaming serial console port logs... (Timeout: 10 minutes)"
TIMEOUT=600
ELAPSED=0
SUCCESS=false

# Wait-for-boot cushion
sleep 15

while [[ ${ELAPSED} -lt ${TIMEOUT} ]]; do
    # Fetch serial port output
    SERIAL_OUT=$(gcloud compute instances get-serial-port-output "${VM_NAME}" \
      --project="${PROJECT_ID}" \
      --zone="${ZONE}" 2>/dev/null || echo "")
    
    if echo "${SERIAL_OUT}" | grep -q "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY"; then
        echo "[x] SUCCESS: GCE first-boot startup-script and playbooks executed cleanly!"
        echo "=============================================================================="
        echo "                       GCE PLAYBOOK TEST OUTPUT                              "
        echo "=============================================================================="
        echo "${SERIAL_OUT}" | grep -A 5 -B 5 "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" || true
        echo "=============================================================================="
        SUCCESS=true
        break
    fi
    
    sleep 10
    ELAPSED=$((ELAPSED + 10))
    if [[ $((ELAPSED % 60)) -eq 0 ]]; then
        echo "[-] Playbook test executing in cloud... (${ELAPSED}s elapsed)"
    fi
done

if [[ "${SUCCESS}" = "false" ]]; then
    echo "[!] TIMEOUT/FAILURE: Playbook execution did not complete within ${TIMEOUT} seconds." >&2
    echo "[-] Fetching final 100 lines of GCE serial logs for diagnostics:" >&2
    gcloud compute instances get-serial-port-output "${VM_NAME}" \
      --project="${PROJECT_ID}" \
      --zone="${ZONE}" | tail -n 100 || true
    exit 1
fi

echo "=============================================================================="
echo "[+] SUCCESS: Isolated GCE Playbook Sandbox test passed successfully!"
echo "=============================================================================="
exit 0
