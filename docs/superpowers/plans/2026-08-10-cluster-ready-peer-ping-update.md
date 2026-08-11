# Cluster Ready Peer Ping Update Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modify the `CLUSTER_READY` peer ping checks to loop and retry over 300 seconds (5 minutes) and ensure failure behavior is handled as "IN PROGRESS" instead of hard failure during peer wait times, per the user's instructions.

**Architecture:** The `machine_orchestration` Ansible role will be updated. The simple `ping -c 1` task will be wrapped in an `until` retry loop (10 retries, 30s delay). Furthermore, we need to adjust how failures in Stage 5 (`CLUSTER_READY`) are recorded in the overall playbook (`local.yml`). If the peer reachability fails (or any other step), it should record an `in_progress` state rather than a `failed` state if it's waiting on peers, or we can just let Ansible fail the task but record the state appropriately. Given the Ansible structure, we will update the `rescue` block in `local.yml` for `CLUSTER_READY` to mark it as `failed` (which `collect-diagnostics.sh` reads), but we will add a specific task to record `in_progress` before the wait, or adjust the error handling so the system understands it is waiting. The prompt says "mark a failure ONLY if any of the steps up to the peers fails... IF peers are not yet available, then the stage is PENDING or IN-PROGRESS, not FAILED". So we will implement a validation script for peer checks, and if that script fails due to peers being offline, we exit with a specific code that Ansible can rescue into an `in_progress` state, or simply use `ignore_errors` and set state based on the result.

Actually, the cleanest way in Ansible is to do the ping loop. If the loop fails, we write an `in_progress` state and `meta: end_play` so it tries again on the next cron run. If it succeeds, we write the `completed` state.

**Tech Stack:** Ansible.

---

### Task 1: Update the Peer Ping Task with Retries

**Files:**
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [ ] **Step 1: Replace the existing ping task**
Find the task:
```yaml
- name: "GDC-ORCH | Verify peer network pingability"
```
Replace it with:
```yaml
- name: "GDC-ORCH | Verify peer network pingability (Wait up to 5 mins)"
  ansible.builtin.command:
    cmd: "ping -c 1 {{ item.ipv4 }}"
  loop: "{{ machine_config.peers }}"
  register: peer_ping
  until: peer_ping.rc == 0
  retries: 10
  delay: 30
  failed_when: false
  changed_when: false
  when: machine_config.peers is defined
```
*Note: I changed `item` to `item.ipv4` based on the new JSON schema where `peers` is an array of objects.*

- [ ] **Step 2: Check for peer ping failures**
Add a task right after it to evaluate the results and fail gracefully if peers are unreachable.
```yaml
- name: "GDC-ORCH | Check if any peers are unreachable"
  ansible.builtin.set_fact:
    peers_unreachable: true
  loop: "{{ peer_ping.results }}"
  when: 
    - machine_config.peers is defined
    - item.rc is defined
    - item.rc != 0

- name: "GDC-ORCH | Gracefully halt if waiting on peers"
  ansible.builtin.fail:
    msg: "WAITING_ON_PEERS"
  when: peers_unreachable | default(false)
```

### Task 2: Update Stage 5 Rescue Block

**Files:**
- Modify: `src/ansible/local.yml`

- [ ] **Step 1: Update the rescue block for Stage 5**
In `local.yml` around line 203, modify the rescue block for `CLUSTER_READY`.
Replace the `rescue:` block for Stage 5:
```yaml
      rescue:
        - name: "GDC-STATE | Determine if failure was due to waiting on peers"
          ansible.builtin.set_fact:
            is_waiting: "{{ ansible_failed_result.msg is defined and ansible_failed_result.msg == 'WAITING_ON_PEERS' }}"

        - name: "GDC-STATE | Record ClusterReady state"
          ansible.builtin.copy:
            dest: /var/gdc-install/state/cluster-ready.json
            owner: root
            group: root
            mode: '0644'
            content: |
              {
                "stage": "cluster-ready",
                "status": "{{ 'in_progress' if is_waiting else 'failed' }}",
                "timestamp": "{{ ansible_date_time.iso8601 }}"
              }

        - name: "GDC-STATE | End play gracefully if waiting on peers"
          ansible.builtin.meta: end_play
          when: is_waiting | default(false)

        - name: "GDC-STATE | Fail the play on ClusterReady Configuration"
          ansible.builtin.fail:
            msg: "GDC ClusterReady Configuration failed!"
          when: not (is_waiting | default(false))
```

### Task 3: Update Hostname Resolution Task

**Files:**
- Modify: `src/ansible/roles/machine_orchestration/tasks/main.yml`

- [ ] **Step 1: Fix item reference in host resolution**
The JSON schema updated `peers` from an array of strings to an array of objects. Update the hostname resolution task.
Find:
```yaml
- name: "GDC-ORCH | Verify peer hostname resolution"
```
Change `{{ item }}` to `{{ item.hostname }}`.
```yaml
- name: "GDC-ORCH | Verify peer hostname resolution"
  ansible.builtin.command:
    cmd: "getent hosts {{ item.hostname }}"
  loop: "{{ machine_config.peers }}"
  register: host_resolution
  failed_when: host_resolution.rc != 0
  changed_when: false
  when: machine_config.peers is defined
```

- [ ] **Step 2: Fix /etc/hosts injection**
Find the `/etc/hosts` injection task:
```yaml
- name: "GDC-ORCH | Ensure peers list is registered in /etc/hosts"
  ansible.builtin.lineinfile:
    path: /etc/hosts
    line: "{{ item.ipv4 }} {{ item.hostname }}"
    state: present
  loop: "{{ machine_config.peers }}"
  when: machine_config.peers is defined
```
*(Removing the zip range logic since the new schema provides the IP directly via `item.ipv4`).*
