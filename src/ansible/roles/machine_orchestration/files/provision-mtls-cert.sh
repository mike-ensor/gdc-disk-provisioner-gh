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

MOCK_MTLS="${STEP_MOCK_MTLS:-false}"

if [[ "${MOCK_MTLS}" == "true" ]] || [[ -f "/etc/gdc/mock-mtls" ]]; then
    echo "WARN: Development mode enabled. Bypassing step-cli and TPM attestation."
    
    if [[ -f "/etc/gdc/mock-client.crt" ]] && [[ -f "/etc/gdc/mock-client.key" ]]; then
        echo "[*] Found pre-injected mock certificates. Copying to ${CERT_DIR}..."
        cp "/etc/gdc/mock-client.crt" "${CLIENT_CRT}"
        cp "/etc/gdc/mock-client.key" "${CLIENT_KEY}"
    else
        echo "[*] Generating self-signed mock certificates..."
        # Generate an ephemeral mock certificate using node_mac as the Common Name
        MOCK_HOSTNAME="${STEP_MOCK_HOSTNAME:-gdc-mock-node}"
        openssl req -x509 -newkey rsa:2048 -keyout "${CLIENT_KEY}" -out "${CLIENT_CRT}" \
            -days 365 -nodes -subj "/CN=${MOCK_HOSTNAME}" 2>/dev/null
    fi
        
    chmod 0600 "${CLIENT_KEY}"
    chmod 0644 "${CLIENT_CRT}"
    chown root:root "${CLIENT_KEY}" "${CLIENT_CRT}"
    
    echo "PASS: Mock certificates generated/copied successfully at ${CERT_DIR}."
    exit 0
fi

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
EXTRA_ARGS=""
if [[ -n "${CA_FINGERPRINT}" ]]; then
    step ca bootstrap --ca-url="${CA_URL}" --fingerprint="${CA_FINGERPRINT}" --force
else
    echo "WARN: No CA fingerprint provided. Executing insecure TOFU by downloading root CA..."
    # Download the root CA certificate securely-bypassed for lab use
    curl -sk "${CA_URL}/roots.pem" -o "${CERT_DIR}/root_ca.crt" || true
    if [[ ! -s "${CERT_DIR}/root_ca.crt" ]]; then
        echo "FAIL: Could not download root CA certificate from ${CA_URL}/roots.pem"
        # We don't exit here, we'll let step ca certificate fail naturally if it can't reach the CA
    else
        # We skip bootstrap and just pass the root directly to the certificate request
        EXTRA_ARGS="--ca-url=${CA_URL} --root=${CERT_DIR}/root_ca.crt"
    fi
fi

echo "[*] Requesting TPM-attested certificate for identity: ${NODE_MAC}..."
# Using --kms tpmkms: invokes the TPM 2.0 module for hardware attestation
step ca certificate "${NODE_MAC}" "${CLIENT_CRT}" "${CLIENT_KEY}" \
    --provisioner="${PROVISIONER_NAME}" \
    --kms="tpmkms:" \
    --force ${EXTRA_ARGS}

# Enforce strict permissions
chmod 0600 "${CLIENT_KEY}"
chmod 0644 "${CLIENT_CRT}"
chown root:root "${CLIENT_KEY}" "${CLIENT_CRT}"

echo "PASS: Successfully provisioned TPM-attested mTLS certificate."
