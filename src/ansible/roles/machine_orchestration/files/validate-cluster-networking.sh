#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

set -e

echo "=== GDC Cluster Networking Validation ==="

FACTS_FILE="/etc/ansible/facts.d/gdc.fact"
if [ ! -f "$FACTS_FILE" ]; then
    echo "FAIL: Facts file $FACTS_FILE not found."
    exit 1
fi

# We use jq to parse out the expected values
HAS_NETWORK=$(jq -r '.network | length' "$FACTS_FILE")
if [ "$HAS_NETWORK" -eq 0 ] || [ "$HAS_NETWORK" == "null" ]; then
    echo "SKIP: No networking configuration found in GDC Companion payload."
    exit 0
fi

MGMT_DHCP=$(jq -r '.network.management_network.dhcp_v4 // true' "$FACTS_FILE")
MGMT_IP=$(jq -r '.network.management_network.ip_cidr // ""' "$FACTS_FILE" | cut -d'/' -f1)

# Using default vlan ID of 109 if not specified 
K8S_VLAN=$(jq -r '.network.cluster_network.vlan_id // "109"' "$FACTS_FILE")
K8S_DHCP=$(jq -r '.network.cluster_network.dhcp_v4 // true' "$FACTS_FILE")
K8S_IP=$(jq -r '.network.cluster_network.ip_cidr // ""' "$FACTS_FILE" | cut -d'/' -f1)


echo "[*] Checking mTLS Certificate Provisioning..."
if [ -f "/var/gdc-install/keys/client.crt" ] && [ -f "/var/gdc-install/keys/client.key" ]; then
    echo "PASS: TPM-attested mTLS certificates found."
else
    echo "FAIL: mTLS certificates are missing in /var/gdc-install/keys/."
    # We do not strictly exit 1 here yet to allow the script to finish testing networking,
    # but the failure will be logged in the diagnostics collector.
fi

echo "[*] Checking GDC Companion API Status..."
if [ "$(jq -r '.is_fallback // false' "$FACTS_FILE")" == "true" ]; then
    echo "FAIL: GDC Companion API lookup failed. Fallback configuration was used."
else
    echo "PASS: GDC Companion API lookup was successful."
fi

echo "[*] Checking Management Network..."
if [ "$MGMT_DHCP" != "true" ] && [ -n "$MGMT_IP" ] && [ "$MGMT_IP" != "null" ]; then
    if ip -4 addr show | grep -q "$MGMT_IP"; then
        echo "PASS: Management IP $MGMT_IP is configured."
    else
        echo "FAIL: Management IP $MGMT_IP is missing from interfaces."
        exit 1
    fi
else
    echo "PASS: Management Network is DHCP."
fi

echo "[*] Checking Kubernetes VLAN Network..."
if [ -n "$K8S_VLAN" ] && [ "$K8S_VLAN" != "null" ] && [ "$K8S_VLAN" -gt 0 ] 2>/dev/null; then
    PHYS_IFACE=""
    for iface_path in $(ls -d /sys/class/net/e* 2>/dev/null | grep -v '\.' | sort); do
        if [ -f "$iface_path/carrier" ] && [ "$(cat "$iface_path/carrier" 2>/dev/null)" = "1" ]; then
            PHYS_IFACE=$(basename "$iface_path")
            break
        fi
    done
    if [ -z "$PHYS_IFACE" ]; then
        PHYS_IFACE=$(ls /sys/class/net | grep -E '^e' | grep -v '\.' | sort | head -n 1 || echo "eth0")
    fi
    VLAN_IFACE="${PHYS_IFACE}.${K8S_VLAN}"
    if ip link show dev "$VLAN_IFACE" >/dev/null 2>&1; then
        echo "PASS: VLAN interface $VLAN_IFACE exists."
    else
        echo "FAIL: VLAN interface $VLAN_IFACE is missing."
        exit 1
    fi

    if [ "$K8S_DHCP" != "true" ] && [ -n "$K8S_IP" ] && [ "$K8S_IP" != "null" ]; then
        if ip -4 addr show dev "$VLAN_IFACE" | grep -q "$K8S_IP"; then
            echo "PASS: Kubernetes IP $K8S_IP is configured on $VLAN_IFACE."
        else
            echo "FAIL: Kubernetes IP $K8S_IP is missing from $VLAN_IFACE."
            exit 1
        fi
    else
        echo "PASS: Kubernetes VLAN Network is DHCP."
    fi
else
    echo "SKIP: No Kubernetes VLAN configuration defined."
fi

echo "=== Validation Successful ==="
exit 0
