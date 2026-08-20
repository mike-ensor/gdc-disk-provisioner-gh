#!/bin/bash
set -euo pipefail

# Ensure the auth RAM disk directory exists
mkdir -p /run/gdc-auth
chmod 755 /run/gdc-auth

# RENEW STEP-CA MTLS CERTIFICATE
# step ca renew will only actually renew if the certificate has passed ~2/3rds of its lifetime,
# but passing --force bypasses prompt/tty requirements.
if command -v step >/dev/null 2>&1; then
    step ca renew /var/gdc-install/keys/client.crt /var/gdc-install/keys/client.key --force >/dev/null 2>&1 || true
fi

# RENEW GCLOUD OAUTH TOKEN VIA GDC COMPANION
# Discover MAC address of the active primary interface
PHYS_IFACE=$(ip link show | awk -F': ' '/state UP/ {getline; print $0}' | awk -F': ' '/^ / {next} {print $2}' | grep -E '^e' | head -n 1 || ip link show | awk -F': ' '/state UP/ && $2 ~ /^e/ {print $2}' | head -n 1)
if [ -z "$PHYS_IFACE" ]; then PHYS_IFACE=$(ls /sys/class/net | grep -E '^e' | head -n 1 || echo "eth0"); fi
NODE_MAC=$(cat /sys/class/net/${PHYS_IFACE}/address | tr '[:upper:]' '[:lower:]')

# Fetch the token from Companion using the mTLS certificate
COMPANION_URL="https://gdc-companion.ensor-labs.com/v1/machine-credentials/gcp-token/${NODE_MAC}"
TOKEN_JSON=$(curl -s -X GET "${COMPANION_URL}" \
    --cert /var/gdc-install/keys/client.crt \
    --key /var/gdc-install/keys/client.key 2>/dev/null)

# Parse the JSON and write purely the token to the tmpfs file
if echo "${TOKEN_JSON}" | grep -q "access_token"; then
    echo "${TOKEN_JSON}" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4 > /run/gdc-auth/access_token
    # Set permissive ACLs so both root and gdc-admin can read it
    chmod 644 /run/gdc-auth/access_token
else
    echo "ERROR: Failed to fetch a valid access token from Companion." >&2
    exit 1
fi
