# GDC On-Device Ansible Playbooks Testing & Verification Guide

This document provides consistent, concise, and repeatable procedures for human operators and AI agents to sync, execute, and verify GDC Post-Install Ansible Playbooks directly on an active physical edge node.

---

## 1. Environment & Credentials Reference

* **Target GDC Node IP:** `192.168.9.236`
* **Default Active User:** `temporary-installer` (Fallback to `gdc-admin` once Task 04 completes)
* **Default Password:** `troubled-marble-150`
* **Default SSH Private Key:** `test/test-keys/id_ed25519`
* **Target Node Ansible Path:** `/etc/gdc/ansible/`

---

## 2. On-Device Push & Execution Commands

Run these commands from your local compiler workstation to synchronize the playbooks and execute the roles.

### Step 1: Copy Local Playbooks to Remote Temp Folder
```bash
# Compress and copy the src/ansible directory to the remote node
tar -czf - -C src ansible | sshpass -p "troubled-marble-150" ssh -o StrictHostKeyChecking=no temporary-installer@192.168.9.236 "tar -xzf - -C /tmp/"
```

### Step 2: Overwrite the On-Device Configuration Directory
```bash
# Overwrite the production Ansible configuration path with the new files
sshpass -p "troubled-marble-150" ssh -o StrictHostKeyChecking=no temporary-installer@192.168.9.236 "
  sudo rm -rf /etc/gdc/ansible && \
  sudo mkdir -p /etc/gdc/ansible && \
  sudo cp -r /tmp/ansible/* /etc/gdc/ansible/ && \
  rm -rf /tmp/ansible
"
```

### Step 3: Run the Playbook Manually
Execute the newly updated playbooks in check/dry-run mode first, then run them for real:

* **Simulation (Check-mode / Dry-Run):**
  ```bash
  sshpass -p "troubled-marble-150" ssh -t -o StrictHostKeyChecking=no temporary-installer@192.168.9.236 "
    sudo ansible-playbook -i localhost, -c local --check --diff /etc/gdc/ansible/local.yml
  "
  ```

* **Active Real Run (Applies Changes):**
  ```bash
  sshpass -p "troubled-marble-150" ssh -t -o StrictHostKeyChecking=no temporary-installer@192.168.9.236 "
    sudo ansible-playbook -i localhost, -c local /etc/gdc/ansible/local.yml
  "
  ```

* **Selective Role Run (by tag):**
  ```bash
  sshpass -p "troubled-marble-150" ssh -t -o StrictHostKeyChecking=no temporary-installer@192.168.9.236 "
    sudo ansible-playbook -i localhost, -c local --tags kernel_tuning /etc/gdc/ansible/local.yml
  "
  ```

---

## 3. Post-Execution Verification Checklist

Log in to the remote machine over SSH and run the following commands to confirm successful post-install state transitions:

| Task / Feature | Verification Command | Expected Output |
| :--- | :--- | :--- |
| **Task 00: DNS** | `cat /etc/hosts \| grep gdc.local` | `127.0.0.1 nexus.gdc.local` & `git.gdc.local` |
| **Task 01: Hubs** | `ss -ltun \| grep -E "3000\|8081"` | Local Port bindings on `3000` (Gitea) & `8081` (Nexus) |
| **Task 03: Workspace** | `find /var/gdc-install -type d -printf "%p -> %u:%g (%m)\n"` | Owned by `gdc-admin:gdc-admin` with `0755` permissions |
| **Task 04: Admin** | `id gdc-admin && sudo -U gdc-admin -l` | Returns supplementary groups and `(ALL) NOPASSWD: ALL` |
| **Task 05: APT Sources** | `cat /etc/apt/sources.list.d/gdc-nexus.sources` | Only `nexus.gdc.local` sources configured and active |
| **Task 06: Core Packages** | `dpkg -l \| grep -E "docker-ce\|containerd.io\|chrony"` | Lists core dependencies as installed (`ii`) |
| **Task 07: Kernel** | `sysctl fs.inotify.max_user_instances net.core.bpf_jit_enable` | Match GDC standard performance tuning constraints |
| **Task 08: NTP Time** | `timedatectl` | Timezone: `Etc/UTC`, NTP Service: active |
| **Task 09: Engines** | `systemctl is-active docker containerd` | Both return `active` |
| **Task 10: Standalone SDK** | `gcloud --version && kubectl version --client` | Executable from shell and pointing to symlinks |
| **Task 11: Hardening** | `sudo ufw status && cat /etc/apt/apt.conf.d/20auto-upgrades` | UFW `inactive (dead)`, auto-upgrades active |
| **Task 12: Utilities** | `ls -la /etc/cron.hourly/logrotate` | Symlinked and executable with `0755` permissions |

---

## 4. Troubleshooting & Logging

If a playbook run stalls or throws errors, inspect the on-device system logs:

* **Systemd Timer logs:** `journalctl -u gdc-provision -f`
* **Ansible-Pull logs:** `cat /var/log/gdc-ansible-pull.log`
* **Local Gitea Logs:** `journalctl -u gitea -n 100`
* **Local Nexus Logs:** `journalctl -u nexus -n 100`
