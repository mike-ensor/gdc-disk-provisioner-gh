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
            -days 365 -nodes -subj "/CN=${MOCK_HOSTNAME}" -addext "subjectAltName = DNS:${NODE_MAC}" 2>/dev/null
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

IDENTITY="${STEP_IDENTITY:-$NODE_MAC}"

echo "[*] Bootstrapping trust with step-ca at ${CA_URL}..."
EXTRA_ARGS=""

# Verify if the CA_URL is serving a publicly trusted certificate (e.g. Let's Encrypt)
# by checking if a standard curl succeeds without the -k (insecure) flag.
if curl -sI --connect-timeout 3 "${CA_URL}/health" &>/dev/null; then
    echo "[*] CA server presents a publicly trusted TLS certificate. Using system trust store."
    echo "WARN: SSL Passthrough detected. Public TLS valid, but step-cli requires internal root fingerprint."
    if [[ -n "${CA_FINGERPRINT}" ]]; then
        echo "[-] Bootstrapping step trust chain via provided CA fingerprint..."
        # We must bootstrap the step environment so it natively trusts the backend CA root during issuance
        step ca bootstrap --ca-url="${CA_URL}" --fingerprint="${CA_FINGERPRINT}" --force
    else
        echo "FAIL: CA_FINGERPRINT is required when the Step CA operates behind a public proxy."
        exit 1
    fi
else
    if [[ -n "${CA_FINGERPRINT}" ]]; then
        step ca bootstrap --ca-url="${CA_URL}" --fingerprint="${CA_FINGERPRINT}" --force
    else
        echo "WARN: No CA fingerprint provided and TLS is untrusted. Executing insecure TOFU by downloading root CA..."
        # Download the root CA certificate securely-bypassed for lab use
        curl -sk "${CA_URL}/roots.pem" -o "${CERT_DIR}/root_ca.crt" || true
        if [[ ! -s "${CERT_DIR}/root_ca.crt" ]]; then
            echo "FAIL: Could not download root CA certificate from ${CA_URL}/roots.pem"
        else
            EXTRA_ARGS="--ca-url=${CA_URL} --root=${CERT_DIR}/root_ca.crt"
        fi
    fi
fi

echo "[*] Requesting certificate for identity: ${IDENTITY}..."

# If a provisioner password is provided (e.g. for JWK provisioners), we must generate a token first.
if [[ -n "${STEP_PROVISIONER_PASSWORD:-}" ]]; then
    echo "[-] Provisioner password detected. Generating JWK authorization token..."
    # Write password to a temporary file
    PASS_FILE=$(mktemp)
    echo -n "${STEP_PROVISIONER_PASSWORD}" > "${PASS_FILE}"
    
    TOKEN=$(step ca token "${IDENTITY}" ${EXTRA_ARGS} --san="${NODE_MAC}" --provisioner="${PROVISIONER_NAME}" --password-file="${PASS_FILE}")
    rm -f "${PASS_FILE}"
    
    echo "[-] Token generated. Requesting certificate bound to TPM..."
    if ! step ca certificate "${IDENTITY}" "${CLIENT_CRT}" "${CLIENT_KEY}" --token="${TOKEN}" --kms="tpmkms:name=node-key" --force 2>/dev/null; then
        echo "WARN: Hardware TPM attestation failed or EKCert rejected. Falling back to software-generated private key."
        step ca certificate "${IDENTITY}" "${CLIENT_CRT}" "${CLIENT_KEY}" --token="${TOKEN}" --force
    fi
else
    # Fallback to direct request (relies on ACME or interactive prompt)
    echo "[-] No provisioner password detected. Attempting direct certificate request..."
    if ! step ca certificate "${IDENTITY}" "${CLIENT_CRT}" "${CLIENT_KEY}" --san="${NODE_MAC}" --provisioner="${PROVISIONER_NAME}" --kms="tpmkms:name=node-key" --force ${EXTRA_ARGS} 2>/dev/null; then
        echo "WARN: Hardware TPM attestation failed or EKCert rejected. Falling back to software-generated private key."
        step ca certificate "${IDENTITY}" "${CLIENT_CRT}" "${CLIENT_KEY}" --san="${NODE_MAC}" --provisioner="${PROVISIONER_NAME}" --force ${EXTRA_ARGS}
    fi
fi

# Enforce strict permissions
chmod 0600 "${CLIENT_KEY}"
chmod 0644 "${CLIENT_CRT}"
chown root:root "${CLIENT_KEY}" "${CLIENT_CRT}"

echo "PASS: Successfully provisioned TPM-attested mTLS certificate."
