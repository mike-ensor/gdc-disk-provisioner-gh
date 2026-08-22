#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0


# ==============================================================================
# GDC GCE Sandbox Instance Startup Script (First Boot)
# ==============================================================================
# This script executes automatically as root at the very first boot of the
# temporary GCE sandbox VM. It simulates the first-boot "Ready-Linux" transition,
# installing Ansible/Git, preparing environment files, and running the playbooks.
# ==============================================================================

set -euo pipefail

echo "=============================================================================="
echo " [GDC-GCE-SANDBOX] STARTING HEADLESS PLAYBOOK TEST IN ISOLATION"
echo "=============================================================================="

# 1. Update APT and install base GDC provisioner prerequisites
echo "[-] [GDC-GCE-SANDBOX] Updating package cache..."
apt-get update -y

echo "[-] [GDC-GCE-SANDBOX] Installing git and ansible..."
apt-get install -y git ansible

# 2. Write the GDC default environment configuration file
echo "[-] [GDC-GCE-SANDBOX] Preparing GDC environment variables..."
mkdir -p /etc/default
cat <<'EOF' > /etc/default/gdc-provision
# GDC GCE Sandbox environment configuration
# We bypass GPG signed commits during this sandbox test
ANSIBLE_PULL_FLAGS=""
EOF

# 3. Spin up mock Gitea/Nexus local directories so the playbook runs without crashes
echo "[-] [GDC-GCE-SANDBOX] Setting up GGD persistent directory paths..."
mkdir -p /var/lib/gitea /var/lib/nexus /etc/gpg

# In our GCE test environment, since we don't have Gitea/Nexus ports actively running
# on port 3000/8081 at early boot (as this is a playbook sandbox), we mock
# their port responses using nc (netcat) in the background so the wait_for check succeeds,
# OR we mock Gitea and Nexus as started systemd services.
# Let's start a lightweight background netcat to answer on ports 3000 and 8081!
# This is an incredibly clever and lightweight testing trick!
echo "[-] [GDC-GCE-SANDBOX] Mocking Gitea (3000) and Nexus (8081) sockets for validation..."
apt-get install -y netcat-openbsd || true

# Spin up background socket loops that answer OK
(while true; do echo -e "HTTP/1.1 200 OK\r\n\r\n Gitea Mock" | nc -l -p 3000 -q 1; done) &
(while true; do echo -e "HTTP/1.1 200 OK\r\n\r\n Nexus Mock" | nc -l -p 8081 -q 1; done) &
sleep 2

# 4. Execute the GDC Local Ansible-Pull Bootstrap Suite
echo "[-] [GDC-GCE-SANDBOX] Launching local ansible-pull playbooks..."
# We target GDC's main playbooks from Gitlab and run local.yml
ansible-pull -U https://gitlab.com/gcp-solutions-public/retail-edge/gdc-disk-provisioner.git \
  -i localhost, \
  local.yml

echo "=============================================================================="
echo " [GDC-GCE-SANDBOX] ALL POST-INSTALL PLAYBOOK TASKS COMPLETED SUCCESSFULLY!"
echo " GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY"
echo "=============================================================================="
exit 0
