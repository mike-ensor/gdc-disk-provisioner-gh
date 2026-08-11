# Cluster Ready Networking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement network configuration dynamically from GDC Companion in the CLUSTER_READY stage, supporting DHCP/Static IP and VLANs, and persist the config via Ansible facts for the CLUSTER_TURNUP stage, with a runnable validation hook for diagnostics.

**Architecture:** The `machine_orchestration` Ansible role will extract the `networking` payload, persist it to `/etc/ansible/facts.d/gdc.fact`, and template a Netplan configuration. An executable Bash validation script will be deployed to the host and hooked into `collect-diagnostics.sh` to provide verifiable evidence of success.

**Tech Stack:** Ansible, Netplan, Bash, jq.

---

### Task 1: Store machine_config as Ansible Local Facts

**Files:**
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [ ] **Step 1: Create the facts.d directory**
Add task to `main.yml` (append to the end of the file):
```yaml
- name: "GDC-ORCH | Ensure Ansible facts.d directory exists"
  ansible.builtin.file:
    path: /etc/ansible/facts.d
    state: directory
    owner: root
    group: root
    mode: '0755'
```

- [ ] **Step 2: Save the machine_config payload**
Add task to `main.yml`:
```yaml
- name: "GDC-ORCH | Persist machine_config to local facts for CLUSTER_TURNUP"
  ansible.builtin.copy:
    dest: /etc/ansible/facts.d/gdc.fact
    owner: root
    group: root
    mode: '0644'
    content: "{{ machine_config | to_nice_json }}"
```

### Task 2: Create the Netplan Configuration Template

**Files:**
- Create: `src/ansible/roles/machine_orchestration/templates/50-gdc-network.yaml.j2`

- [ ] **Step 1: Write the Netplan template**
Create the file with the following content to handle DHCP, Static IP, and VLAN configurations based on the updated `machine_config.networking`. Note that since the VLAN uses the same subnet for testing the secondary network, we use the values appropriately. The user specified adding a second K8s network for VLAN.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    # We dynamically select the default management interface
    {{ ansible_default_ipv4.interface | default('enp1s0') }}:
{% if machine_config.networking.dhcp_v4 | default(false) %}
      dhcp4: true
{% else %}
      dhcp4: false
      addresses:
        - {{ machine_config.networking.ip_cidr }}
      routes:
        - to: default
          via: {{ machine_config.networking.gateway }}
      nameservers:
        addresses:
{% for dns in machine_config.networking.dns_servers %}
          - {{ dns }}
{% endfor %}
{% endif %}

  vlans:
    vlan{{ machine_config.networking.vlan_id | default(109) }}:
      id: {{ machine_config.networking.vlan_id | default(109) }}
      link: {{ ansible_default_ipv4.interface | default('enp1s0') }}
{% if machine_config.networking.dhcp_v4 | default(false) %}
      dhcp4: true
{% else %}
      dhcp4: false
      addresses:
        - {{ machine_config.networking.ip_cidr }}
      routes:
        - to: default
          via: {{ machine_config.networking.gateway }}
          table: 20
      routing-policy:
        - from: {{ machine_config.networking.ip_cidr | split('/') | first }}
          table: 20
{% endif %}
```

### Task 3: Apply the Netplan Configuration

**Files:**
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [ ] **Step 1: Deploy Netplan template**
Add task to `main.yml`:
```yaml
- name: "GDC-ORCH | Deploy GDC Netplan configuration"
  ansible.builtin.template:
    src: 50-gdc-network.yaml.j2
    dest: /etc/netplan/50-gdc-network.yaml
    owner: root
    group: root
    mode: '0600'
  when: machine_config.networking is defined
```

- [ ] **Step 2: Apply Netplan changes**
Add task to `main.yml`:
```yaml
- name: "GDC-ORCH | Apply Netplan configuration"
  ansible.builtin.command: netplan apply
  when: machine_config.networking is defined
```

### Task 4: Create and Deploy the Validation Script

**Files:**
- Create: `src/ansible/roles/machine_orchestration/files/validate-cluster-networking.sh`
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [ ] **Step 1: Create the validation bash script**
Create `src/ansible/roles/machine_orchestration/files/validate-cluster-networking.sh` updated for the new payload structure:

```bash
#!/usr/bin/env bash
set -e

echo "=== GDC Cluster Networking Validation ==="

FACTS_FILE="/etc/ansible/facts.d/gdc.fact"
if [ ! -f "$FACTS_FILE" ]; then
    echo "FAIL: Facts file $FACTS_FILE not found."
    exit 1
fi

# We use jq to parse out the expected values
HAS_NETWORKING=$(jq -r '.networking | length' "$FACTS_FILE")
if [ "$HAS_NETWORKING" -eq 0 ] || [ "$HAS_NETWORKING" == "null" ]; then
    echo "SKIP: No networking configuration found in GDC Companion payload."
    exit 0
fi

MGMT_DHCP=$(jq -r '.networking.dhcp_v4' "$FACTS_FILE")
MGMT_IP=$(jq -r '.networking.ip_cidr // ""' "$FACTS_FILE" | cut -d'/' -f1)

# Using default vlan ID of 109 if not specified 
K8S_VLAN=$(jq -r '.networking.vlan_id // "109"' "$FACTS_FILE")
K8S_IP=$(jq -r '.networking.ip_cidr // ""' "$FACTS_FILE" | cut -d'/' -f1)

echo "[*] Checking Management Network..."
if [ "$MGMT_DHCP" != "true" ] && [ -n "$MGMT_IP" ]; then
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

    if [ -n "$K8S_IP" ]; then
        if ip -4 addr show "vlan$K8S_VLAN" | grep -q "$K8S_IP"; then
            echo "PASS: Kubernetes IP $K8S_IP is configured on vlan$K8S_VLAN."
        else
            echo "FAIL: Kubernetes IP $K8S_IP is missing from vlan$K8S_VLAN."
            exit 1
        fi
    fi
else
    echo "SKIP: No Kubernetes VLAN configuration defined."
fi

echo "=== Validation Successful ==="
exit 0
```

- [ ] **Step 2: Create files directory**
Run: `mkdir -p src/ansible/roles/machine_orchestration/files`

- [ ] **Step 3: Deploy validation script in Ansible**
Add task to `main.yml`:
```yaml
- name: "GDC-ORCH | Deploy cluster networking validation script"
  ansible.builtin.copy:
    src: validate-cluster-networking.sh
    dest: /usr/local/bin/validate-cluster-networking.sh
    owner: root
    group: root
    mode: '0755'
```

### Task 5: Integrate Validation with Diagnostics Collection

**Files:**
- Modify: `build-workspace/custom-iso/custom-data/collect-diagnostics.sh`

- [ ] **Step 1: Hook script into collect-diagnostics.sh**
Add the following lines into `collect-diagnostics.sh` right before `SECTION 16: TARBALL PACKAGING & DUP`:

```bash
# ------------------------------------------------------------------------------
# SECTION 15c: CLUSTER READY NETWORK VALIDATION
# ------------------------------------------------------------------------------
echo "[-] Executing Cluster Networking Validation..."
if [ -x /usr/local/bin/validate-cluster-networking.sh ]; then
  echo "--- CLUSTER NETWORKING VALIDATION ---" >> "${OUT_DIR}/report.txt"
  if /usr/local/bin/validate-cluster-networking.sh > "${OUT_DIR}/logs/network-validation.log" 2>&1; then
    echo "     [+] Network Validation: PASSED"
    echo "Validation: PASSED" >> "${OUT_DIR}/report.txt"
  else
    echo "     [-] Network Validation: FAILED (Check logs/network-validation.log)"
    echo "Validation: FAILED" >> "${OUT_DIR}/report.txt"
  fi
else
  echo "     [!] Network Validation Script not found or not executable."
fi
```
