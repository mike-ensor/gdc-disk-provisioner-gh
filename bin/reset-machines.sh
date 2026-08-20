#!/usr/bin/env bash
# ==============================================================================
# GDC PXE Auto-Boot and Reset Orchestrator
# ==============================================================================
# Iterates over target machines, identifies their active network interface, 
# matches its MAC address to the corresponding UEFI PXE boot option inside 
# efibootmgr, schedules a one-time PXE boot (BootNext), and triggers a reboot.
# ==============================================================================

set -euo pipefail

# Ensure TARGET_TEST_MACHINES is set
if [[ -z "${TARGET_TEST_MACHINES:-}" ]]; then
    echo "[!] Error: Environment variable 'TARGET_TEST_MACHINES' is not defined or is empty."
    echo "    Format: ['192.168.9.10', '192.168.9.11'] or '192.168.9.10,192.168.9.11'"
    exit 1
fi

# Clean up python list notation, brackets, quotes, and commas
RAW_IPS=$(echo "${TARGET_TEST_MACHINES}" | tr -d "[]'\"" | tr ',' ' ')

# Split into a clean array
read -ra TARGETS <<< "$RAW_IPS"

echo "=============================================================================="
echo " GDC REMOTE REBOOT TO PXE PROTOCOL (Active Interface MAC Matching)"
echo "=============================================================================="

for IP in "${TARGETS[@]}"; do
    # Strip any leading/trailing whitespace from IP
    IP=$(echo "$IP" | xargs)
    if [[ -z "$IP" ]]; then
        continue
    fi

    echo "[-] Targeting node: $IP"

    # 1. Connectivity Check
    echo "  [-] Verifying gdc-admin SSH access..."
    if ! ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "gdc-admin@$IP" "echo 'OK'" &>/dev/null; then
        echo "  [!] ERROR: Cannot connect to $IP as gdc-admin. Skipping node."
        echo "      Ensure the node is fully booted and your SSH keys are deployed."
        echo "------------------------------------------------------------------------------"
        continue
    fi
    echo "  [+] SSH access verified."

    # 2. Dynamic MAC-based PXE Detection, BootNext configuration, and Reboot
    echo "  [-] Querying network interfaces and scheduling PXE boot on $IP..."
    
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "gdc-admin@$IP" bash -s << 'EOF'
        set -euo pipefail

        # Find active interface using default route
        active_iface=$(ip route show | grep '^default' | awk '{print $5}' | head -n 1 || true)
        
        # Fallback to interface associated with the SSH connection
        if [ -z "$active_iface" ] && [ -n "${SSH_CONNECTION:-}" ]; then
            read -r _ _ server_ip _ <<< "$SSH_CONNECTION"
            active_iface=$(ip -o addr show to "$server_ip" | awk '{print $2}' || true)
        fi
        
        # Fallback to first non-loopback UP interface
        if [ -z "$active_iface" ]; then
            active_iface=$(ip -o link show | grep -v 'LOOPBACK' | grep 'state UP' | awk -F': ' '{print $2}' | head -n 1 || true)
        fi

        BOOT_NUM=""
        if [ -n "$active_iface" ] && [ -f "/sys/class/net/$active_iface/address" ]; then
            active_mac=$(cat "/sys/class/net/$active_iface/address" | tr -d ':' | tr '[:upper:]' '[:lower:]')
            echo "  [+] Active interface on host: $active_iface (MAC: $active_mac)"
            
            # Match the cleaned MAC address against efibootmgr entries
            BOOT_NUM=$(efibootmgr | grep -i "MAC(${active_mac}" | head -n 1 | sed -E -n 's/^Boot([0-9A-Fa-f]{4})\*?.*/\1/p' || true)
        fi

        # Fallback to first general PXE IPv4 or Network entry if MAC matching failed
        if [ -z "$BOOT_NUM" ]; then
            echo "  [!] MAC-based PXE boot detection failed. Falling back to pattern-based detection..."
            EFIOUT=$(efibootmgr)
            BOOT_NUM=$(echo "$EFIOUT" | grep -i 'pxe ipv4' | head -n 1 | sed -E -n 's/^Boot([0-9A-Fa-f]{4})\*?.*/\1/p' || true)
            
            if [ -z "$BOOT_NUM" ]; then
                BOOT_NUM=$(echo "$EFIOUT" | grep -iE 'network|netboot|ipv4|lan' | head -n 1 | sed -E -n 's/^Boot([0-9A-Fa-f]{4})\*?.*/\1/p' || true)
            fi
        fi

        if [ -z "$BOOT_NUM" ]; then
            echo "  [!] ERROR: No UEFI PXE or Network boot option detected."
            exit 1
        fi

        echo "  [+] Selected PXE boot option: Boot$BOOT_NUM"
        echo "  [-] Setting BootNext to $BOOT_NUM..."
        sudo efibootmgr -n "$BOOT_NUM" > /dev/null

        echo "  [-] Rebooting machine..."
        sudo reboot
EOF
    
    echo "  [+] Remote command sequence dispatched successfully to $IP."
    echo "------------------------------------------------------------------------------"
done

echo "[x] Finished processing all targeted nodes."
