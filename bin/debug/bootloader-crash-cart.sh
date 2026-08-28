#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# GDC Bootloader - Crash Cart Diagnostic and SSH Restorer
# ==============================================================================

echo "=============================================================================="
echo "GDC BOOTLOADER CRASH CART CONFIGURATION BLOCK"
echo "  -- Use this when the ISO does not boot fully BEFORE cloud-init starts --"
echo "=============================================================================="
echo "Copy and paste the following block directly into the remote root console to enable password-based SSH:"
echo ""

echo "echo \"root:gdc-password-123\" | chpasswd"
echo "mkdir -p /etc/ssh/sshd_config.d"
echo "echo \"PermitRootLogin yes\" > /etc/ssh/sshd_config.d/99-root-ssh.conf"
echo "echo \"PasswordAuthentication yes\" >> /etc/ssh/sshd_config.d/99-root-ssh.conf"
echo "systemctl restart ssh || systemctl restart sshd"

echo ""
echo "=============================================================================="
echo "[-] Optional: Creating a localized offline helper script at /tmp/crash-cart-setup.sh..."
