#!/usr/bin/env bash

# ==============================================================================
# GDC Installer Log Extractor
# ==============================================================================
# Usage: ./bin/extract-installer-logs.sh <IP> <private_key_path>
# ==============================================================================

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <IP> <private_key_path>"
    exit 1
fi

IP=$1
KEY=$2
OUTPUT_DIR="installer-logs-${IP}-$(date +%Y%m%d%H%M%S)"

echo "[-] Creating output directory: ${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

echo "[-] Fetching logs from ${IP}..."
# Using scp to recursively pull the installer log directory
scp -i "${KEY}" -r root@${IP}:/var/log/installer "${OUTPUT_DIR}/"
scp -i "${KEY}" -r root@${IP}:/var/log/cloud-init.log "${OUTPUT_DIR}/"

echo "[-] Logs extracted successfully into ${OUTPUT_DIR}"
echo "[-] Summary:"
ls -R "${OUTPUT_DIR}"
