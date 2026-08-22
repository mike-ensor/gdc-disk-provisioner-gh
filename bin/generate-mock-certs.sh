#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0


# ==============================================================================
# GDC Mock mTLS Certificate Generator
# ==============================================================================
# Generates a self-signed client certificate and private key specifically for
# testing the GDC Companion API bypass/injection workflows.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/custom-data"

mkdir -p "${OUTPUT_DIR}"

CRT_FILE="${OUTPUT_DIR}/mock-client.crt"
KEY_FILE="${OUTPUT_DIR}/mock-client.key"
COMMON_NAME="${1:-gdc-mock-node}"

echo "[-] Generating 365-day self-signed mock certificates for CN: ${COMMON_NAME}..."

openssl req -x509 -newkey rsa:2048 -keyout "${KEY_FILE}" -out "${CRT_FILE}" \
    -days 365 -nodes -subj "/CN=${COMMON_NAME}" 2>/dev/null

chmod 0600 "${KEY_FILE}"
chmod 0644 "${CRT_FILE}"

echo "[x] Success! Mock certificates generated at:"
echo "    Key:  ${KEY_FILE}"
echo "    Cert: ${CRT_FILE}"
echo ""
echo "Note: These files will automatically be injected into the next ISO build if MOCK_GDC_COMPANION_DATA is set."
