# Cluster Ready Networking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement network configuration dynamically from GDC Companion in the CLUSTER_READY stage, supporting DHCP/Static IP and VLANs, and persist the config via Ansible facts for the CLUSTER_TURNUP stage, with a runnable validation hook for diagnostics.

**Architecture:** The `machine_orchestration` Ansible role will extract the `networking` payload, persist it to `/etc/ansible/facts.d/gdc.fact`, and template a Netplan configuration. An executable Bash validation script will be deployed to the host and hooked into `collect-diagnostics.sh` to provide verifiable evidence of success.

**Tech Stack:** Ansible, Netplan, Bash, jq.

---

### Task 1: Store machine_config as Ansible Local Facts

**Files:**
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [x] **Step 1: Create the facts.d directory**
- [x] **Step 2: Save the machine_config payload**

### Task 2: Create the Netplan Configuration Template

**Files:**
- Create: `src/ansible/roles/machine_orchestration/templates/50-gdc-network.yaml.j2`

- [x] **Step 1: Write the Netplan template**

### Task 3: Apply the Netplan Configuration

**Files:**
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [x] **Step 1: Deploy Netplan template**
- [x] **Step 2: Apply Netplan changes**

### Task 4: Create and Deploy the Validation Script

**Files:**
- Create: `src/ansible/roles/machine_orchestration/files/validate-cluster-networking.sh`
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [x] **Step 1: Create the validation bash script**
- [x] **Step 2: Create files directory**
- [x] **Step 3: Deploy validation script in Ansible**

### Task 5: Integrate Validation with Diagnostics Collection

**Files:**
- Modify: `collect-diagnostics.sh` (Pulled from upstream via GCS cache)

- [x] **Step 1: Hook script into collect-diagnostics.sh**
