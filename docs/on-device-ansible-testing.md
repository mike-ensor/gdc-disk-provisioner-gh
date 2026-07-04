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

You can use our automated **Playbook Sync & Run Tool** to seamlessly push playbooks and run them on both local QEMU sandboxes and remote physical hardware targets.

### Target QEMU Guest Sandbox (Localport 2222)
```bash
./test/sync_and_run_ansible.sh
```

### Target Physical Hardware Node (via IP & Password)
To target your physical machine, pass the coordinates and password via environment variables:
```bash
GDC_TARGET_HOST=192.168.9.236 GDC_SSH_PORT=22 GDC_PASSWORD="troubled-marble-150" ./test/sync_and_run_ansible.sh
```

You can pass standard Ansible CLI arguments straight through the utility to test specific roles, tags, or check-modes:
```bash
# Run a dry-run check-mode simulation of the changes on the physical device
GDC_TARGET_HOST=192.168.9.236 GDC_SSH_PORT=22 GDC_PASSWORD="troubled-marble-150" ./test/sync_and_run_ansible.sh --check

# Run only the sysctl kernel tunings task on the physical device
GDC_TARGET_HOST=192.168.9.236 GDC_SSH_PORT=22 GDC_PASSWORD="troubled-marble-150" ./test/sync_and_run_ansible.sh --tags kernel_tuning
```

---

## 3. On-Device Re-Image Need Diagnosis

The synchronization utility executes **automated state health checks** on the target node before pushing playbooks. It evaluates the device's state and prints a prominent notification recommending a **PXE Re-Image** of the node when:

1. **LUKS Passcode File is Missing (`/etc/keys/temp_key.key`):**
   * **Indicator:** Stage 7 (TPM Sealing) has already successfully run and shredded the temporary passcode file.
   * **Consequence:** You can no longer test the clean LUKS key-enrollment or passcode slot wiping flows without re-imaging.
2. **gdc-admin Sudoers are Active (`/etc/sudoers.d/gdc-admin`):**
   * **Indicator:** Sudo administrative user accounts have already been fully deployed and configured on the node.
3. **Ubuntu Sources are Deactivated (`/etc/apt/sources.list.bak`):**
   * **Indicator:** Normal public APT repositories have already been deactivated and locked exclusively to local loopback mirrors.

If any of these conditions are met, the tool will warn you:
```text
==============================================================================
💡 [DIAGNOSTIC ADVICE] RE-IMAGE OF THE NODE IS HIGHLY RECOMMENDED!
------------------------------------------------------------------------------
This device is already in a fully-provisioned, hardened 'Ready-Linux' state:
   -> The temporary master-key passcode '/etc/keys/temp_key.key' is MISSING.
   -> The administrative account 'gdc-admin' has already been provisioned.
   -> Standard public APT repositories have already been deactivated.

To test a clean first-boot deployment loop from a raw baseline OS state,
it is highly beneficial to RE-IMAGE the device via PXE/Bootimus now.
==============================================================================
```

---

## 4. Post-Execution Verification Checklist

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

## 5. Troubleshooting & Logging

If a playbook run stalls or throws errors, inspect the on-device system logs:

* **Systemd Timer logs:** `journalctl -u gdc-provision -f`
* **Ansible-Pull logs:** `cat /var/log/gdc-ansible-pull.log`
* **Local Gitea Logs:** `journalctl -u gitea -n 100`
* **Local Nexus Logs:** `journalctl -u nexus -n 100`
