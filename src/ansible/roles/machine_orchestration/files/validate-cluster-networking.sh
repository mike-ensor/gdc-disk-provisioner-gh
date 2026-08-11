#!/usr/bin/env bash
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

MGMT_DHCP=$(jq -r '.network.management_network.dhcp_v4' "$FACTS_FILE")
MGMT_IP=$(jq -r '.network.management_network.ip_cidr // ""' "$FACTS_FILE" | cut -d'/' -f1)

# Using default vlan ID of 109 if not specified 
K8S_VLAN=$(jq -r '.network.cluster_network.vlan_id // "109"' "$FACTS_FILE")
K8S_DHCP=$(jq -r '.network.cluster_network.dhcp_v4' "$FACTS_FILE")
K8S_IP=$(jq -r '.network.cluster_network.ip_cidr // ""' "$FACTS_FILE" | cut -d'/' -f1)


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
if [ -n "$K8S_VLAN" ] && [ "$K8S_VLAN" != "null" ]; then
    if ip link show | grep -q "vlan$K8S_VLAN"; then
        echo "PASS: VLAN interface vlan$K8S_VLAN exists."
    else
        echo "FAIL: VLAN interface vlan$K8S_VLAN is missing."
        exit 1
    fi

    if [ "$K8S_DHCP" != "true" ] && [ -n "$K8S_IP" ] && [ "$K8S_IP" != "null" ]; then
        if ip -4 addr show "vlan$K8S_VLAN" | grep -q "$K8S_IP"; then
            echo "PASS: Kubernetes IP $K8S_IP is configured on vlan$K8S_VLAN."
        else
            echo "FAIL: Kubernetes IP $K8S_IP is missing from vlan$K8S_VLAN."
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
