#!/usr/bin/env bash

# ==============================================================================
# GDC mTLS Provisioner (TPM Hardware Attestation)
# ==============================================================================
# Bootstraps trust with the central Certificate Authority and requests an mTLS
# certificate using the physical TPM 2.0 Endorsement Key (EK) for zero-touch
# hardware attestation.
# ==============================================================================

set -euo pipefail

CERT_DIR="/var/gdc-install/keys"
CLIENT_CRT="${CERT_DIR}/client.crt"
CLIENT_KEY="${CERT_DIR}/client.key"
CA_URL="${STEP_CA_URL:-https://step-ca.ensor-labs.com}"
CA_FINGERPRINT="${STEP_CA_FINGERPRINT:-}" # Must be injected via Ansible environment if not using system roots
PROVISIONER_NAME="${STEP_PROVISIONER_NAME:-tpm}"

# Idempotency check
if [[ -f "${CLIENT_CRT}" ]] && [[ -f "${CLIENT_KEY}" ]]; then
    echo "PASS: mTLS certificates already exist at ${CLIENT_CRT}."
    exit 0
fi

mkdir -p "${CERT_DIR}"
chmod 0700 "${CERT_DIR}"

# Ensure step-cli is available
if ! command -v step &> /dev/null; then
    echo "FAIL: step-cli binary not found in PATH."
    exit 1
fi

NODE_MAC=$(ip -br link | awk '$1 !~ "lo|vir|wl" { print $3 }' | head -n 1 | tr '[:upper:]' '[:lower:]')
if [[ -z "${NODE_MAC}" ]]; then
    echo "FAIL: Could not determine primary MAC address for identity."
    exit 1
fi

echo "[*] Bootstrapping trust with step-ca at ${CA_URL}..."
if [[ -n "${CA_FINGERPRINT}" ]]; then
    step ca bootstrap --ca-url="${CA_URL}" --fingerprint="${CA_FINGERPRINT}" --force
else
    echo "WARN: No CA fingerprint provided. Executing insecure TOFU by downloading root CA..."
    # Download the root CA certificate securely-bypassed for lab use
    curl -sk "${CA_URL}/roots.pem" -o "${CERT_DIR}/root_ca.crt"
    if [[ ! -s "${CERT_DIR}/root_ca.crt" ]]; then
        echo "FAIL: Could not download root CA certificate from ${CA_URL}/roots.pem"
        exit 1
    fi
    step ca bootstrap --ca-url="${CA_URL}" --root="${CERT_DIR}/root_ca.crt" --install --force
fi

echo "[*] Requesting TPM-attested certificate for identity: ${NODE_MAC}..."
# Using --kms tpmkms: invokes the TPM 2.0 module for hardware attestation
step ca certificate "${NODE_MAC}" "${CLIENT_CRT}" "${CLIENT_KEY}" \
    --provisioner="${PROVISIONER_NAME}" \
    --kms="tpmkms:" \
    --force

# Enforce strict permissions
chmod 0600 "${CLIENT_KEY}"
chmod 0644 "${CLIENT_CRT}"
chown root:root "${CLIENT_KEY}" "${CLIENT_CRT}"

echo "PASS: Successfully provisioned TPM-attested mTLS certificate."
