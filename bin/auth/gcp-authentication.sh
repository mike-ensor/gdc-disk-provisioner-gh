#!/bin/bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

set -euo pipefail

# ==============================================================================
# GDC GCP Authentication & Container Registry Bridge Script
# ==============================================================================
# Seeds GCP credentials from gcloud into containerd (certs.d) and GDC auth (tmpfs)
# to allow pulling Anthos bare-metal container images from Google Container Registry (gcr.io).
# ==============================================================================

show_help() {
    cat << 'EOF'
Usage: sudo gcp-authentication.sh [OPTIONS]

Description:
  Seeds Google Cloud (GCP) credentials from gcloud into containerd (certs.d)
  and GDC's runtime auth directories (/run/gdc-auth/) to allow pulling Anthos
  bare-metal container images from Google Container Registry (gcr.io) and
  authenticate bmctl with Google Cloud APIs.

When to Use:
  - When the ISO was built with GDC_COMPANION=FALSE (bypassing the Companion mTLS flow).
  - When the GDC Companion Server is offline or unreachable during machine turnup.
  - Whenever gcloud authentication was performed manually in user space and needs
    to be propagated to containerd and the GDC ADC runtime environment.

Prerequisites:
  You must first authenticate gcloud using one of the following:
    1) User Login:            sudo -u gdc-admin gcloud auth login --no-launch-browser
    2) Root Login:            sudo gcloud auth login --no-launch-browser
    3) Service Account Key:   sudo gcloud auth activate-service-account --key-file=/path/to/key.json

Options:
  -h, --help    Show this help message and exit.
EOF
}

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            show_help
            exit 0
            ;;
    esac
done

if [[ $(id -u) -ne 0 ]]; then
    echo "ERROR: This script must be run as root (or with sudo)." >&2
    exit 1
fi

echo "==> Checking for gcloud installation..."
if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud command not found in PATH." >&2
    exit 1
fi

echo "==> Checking gcloud authentication state..."
GCP_TOKEN=""
ACTIVE_ACCOUNT=""

# Check in order: current user (root), gdc-admin, and calling SUDO_USER
for user_candidate in "" "gdc-admin" "${SUDO_USER:-}"; do
    [[ -z "${user_candidate}" && $(id -u) -eq 0 ]] || [[ -z "${user_candidate}" ]] && CMD_PREFIX="" || CMD_PREFIX="sudo -u ${user_candidate}"
    
    if id "${user_candidate}" >/dev/null 2>&1 || [[ -z "${user_candidate}" ]]; then
        candidate_account=$(${CMD_PREFIX} gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
        if [[ -n "${candidate_account}" ]]; then
            candidate_token=$(${CMD_PREFIX} gcloud auth print-access-token 2>/dev/null || true)
            if [[ -n "${candidate_token}" ]]; then
                ACTIVE_ACCOUNT="${candidate_account}"
                GCP_TOKEN="${candidate_token}"
                AUTH_USER="${user_candidate:-root}"
                break
            fi
        fi
    fi
done

if [[ -z "${GCP_TOKEN}" ]]; then
    echo "====================================================================" >&2
    echo "ERROR: No active gcloud credentials found!" >&2
    echo "" >&2
    echo "Please authenticate gcloud as 'gdc-admin' or 'root':" >&2
    echo "  1) As gdc-admin:   sudo -u gdc-admin gcloud auth login --no-launch-browser" >&2
    echo "  2) As root:        sudo gcloud auth login --no-launch-browser" >&2
    echo "  3) Service Account: sudo gcloud auth activate-service-account --key-file=/path/to/key.json" >&2
    echo "====================================================================" >&2
    exit 1
fi

echo "==> Active account detected: ${ACTIVE_ACCOUNT} (via user: ${AUTH_USER})"
echo "==> Valid access token generated successfully."

AUTH_HEADER=$(printf "oauth2accesstoken:%s" "${GCP_TOKEN}" | base64 -w 0)

echo "==> Seeding GDC auth runtime directory (/run/gdc-auth)..."
mkdir -p /run/gdc-auth
echo "${GCP_TOKEN}" > /run/gdc-auth/access_token
chmod 644 /run/gdc-auth/access_token

cat <<EOF > /run/gdc-auth/adc_token.json
{
  "version": 1,
  "success": true,
  "token_type": "Bearer",
  "access_token": "${GCP_TOKEN}",
  "expiration_time": $(date -d '+55 minutes' +%s)
}
EOF
chmod 644 /run/gdc-auth/adc_token.json

echo "==> Configuring containerd registry credentials for gcr.io..."
mkdir -p /etc/containerd/certs.d/gcr.io
cat <<EOF > /etc/containerd/certs.d/gcr.io/hosts.toml
server = 'https://gcr.io'

[host]
[host.'https://gcr.io']
capabilities = ['pull', 'resolve']

[host.'https://gcr.io'.header]
authorization = 'Basic ${AUTH_HEADER}'
EOF
chmod 644 /etc/containerd/certs.d/gcr.io/hosts.toml

echo "==> Updating containerd configuration with GDC pause image..."
cat <<EOF > /etc/containerd/config.toml
version = 2
[plugins]
  [plugins."io.containerd.grpc.v1.cri"]
    sandbox_image = "gcr.io/anthos-baremetal-release/pause-amd64:3.3-gke.14@sha256:1f1fd3dd1b064ba0a8a88094ac6f648902a6c00e07b3e02a6b72cb34c9a12d1e"
    [plugins."io.containerd.grpc.v1.cri".containerd]
      default_runtime_name = "runc"
      [plugins."io.containerd.grpc.v1.cri".containerd.runtimes]
        [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
          runtime_type = "io.containerd.runc.v2"
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
            SystemdCgroup = true
    [plugins."io.containerd.grpc.v1.cri".registry]
      config_path = "/etc/containerd/certs.d"
EOF
chmod 644 /etc/containerd/config.toml

echo "==> Restarting containerd service..."
systemctl restart containerd

if systemctl list-unit-files kubelet.service >/dev/null 2>&1 || systemctl cat kubelet.service >/dev/null 2>&1; then
    echo "==> Restarting kubelet service..."
    systemctl restart kubelet
else
    echo "==> kubelet.service not found (cluster not yet deployed); skipping kubelet restart."
fi

echo "==> containerd authentication configured successfully."
