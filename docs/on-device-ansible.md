# GDC On-Device Ansible Architecture & Execution Guide

This document provides the architectural theory, stage execution commands, and repeatable verification procedures for interacting with GDC Post-Install Ansible Playbooks directly on an active physical edge node.

---

## 1. Architecture & How It Works

GDC Bare-Metal relies on a 100% air-gapped, offline-first provisioning model. To eliminate external network dependencies, the ISO embeds its own infrastructure-as-code automation engines directly inside the host OS during installation.

### 1.1. Air-Gapped Service Hubs
Before the node fully boots, `cloud-init` extracts two critical background services into systemd:
1. **Local Gitea Server (Port `3000`):** Hosts the central `bootstrap-playbooks.git` repository holding the entire Ansible codebase.
2. **Local Nexus Server (Port `8081`):** Hosts the isolated `gdc-apt-proxy` holding all pre-seeded Debian packages.

Ansible pulls its instructions directly from the internal Gitea instance on `localhost`, preventing the need to access the internet.

### 1.2. Playbook Filesystem Locations on the Target OS
*   **Source of Truth (Bare Git Repository):**
    *   **Path:** `/var/lib/gitea/repos/gdc/bootstrap-playbooks.git`
    *   **Partition:** Mounted on dedicated LVM volume `/var/lib/gitea`
    *   **Purpose:** The persistent, air-gapped bare repository served locally by Gitea.
*   **Active Execution Workspace (Working Tree):**
    *   **Path:** `/root/.ansible/pull/localhost/`
    *   **Purpose:** The local uncompressed checkout where `ansible-pull` unpacks `local.yml`, `stages/`, `roles/`, and `vars/` before execution.
*   **Offline Dependency Collections:**
    *   **Path:** `/usr/share/ansible/collections/`
    *   **Purpose:** Pre-seeded collections (such as `community.general`) extracted during ISO late-commands.

### 1.3. Persistent State Machine
Ansible executes idempotently through a five-stage state machine driven by `/var/gdc-install/state/*.json` tracker files:
*   `first-boot`: Establishes service hubs and schedules the initial security reboot.
*   `second-boot`: Unseals LUKS using TPM and validates network reachability.
*   `linux-ready`: Executes core Linux hardening, kernel tuning, and security baseline controls.
*   `cluster-ready`: Orchestrates multi-node Kubernetes networking and generates cluster certificates.

Whenever a stage completes, its start/end timings and evidence metrics are committed to its corresponding JSON file. If the playbook runs again, it automatically **skips** any stage that has marked itself as `completed`.

### 1.4. Execution Lifecycle & Timers
Playbook executions are **not** triggered by cron. Instead, they are orchestrated by native `systemd` components:
*   **`gdc-provision.service`:** A `oneshot` systemd unit that runs `ansible-pull` against the local Gitea instance. It is automatically triggered during system boot (`multi-user.target`).
*   **`gdc-provision.timer`:** A persistent `systemd` timer configured to periodically trigger `gdc-provision.service` (by default, daily at `02:00:00` UTC) to synchronize configuration drift.

### 1.5. Step-by-Step Sequence of Operations
The `gdc-provision.service` enforces the following execution sequence during every invocation:

1. **Trigger Event:** Triggered during boot (`multi-user.target`), via the daily timer (`gdc-provision.timer`), or manually (`sudo systemctl restart gdc-provision.service`).
2. **Log Environment Setup:** Creates `/var/gdc-install/logs/` and symlinks `/var/log/gdc-ansible-pull.log` to pipe all stdout/stderr directly to disk and journald.
3. **Offline Nexus Health Check:** If `ansible-pull` is not yet installed on first boot, it polls `http://127.0.0.1:8081/` until the local Nexus mirror is active, then installs `ansible` and `git` offline.
4. **Git Workspace Synchronization:** `ansible-pull` clones or pulls the latest revision from `/var/lib/gitea/repos/gdc/bootstrap-playbooks.git` directly into `/root/.ansible/pull/localhost/`.
5. **State-Driven Execution (`local.yml`):**
   * Reads `/var/gdc-install/state/provisioning-timing.json` to preserve global provisioning start time.
   * Checks `/var/gdc-install/state/*.json` to skip any stages already marked `completed`.
   * Executes the next pending stage (`first-boot` $\rightarrow$ `second-boot` $\rightarrow$ `linux-ready` $\rightarrow$ `cluster-ready`).
   * Writes the completion state, error details (if failed), and start/end timing metrics to `/var/gdc-install/state/<stage>.json`.
   * Calls `/usr/local/bin/gdc-collector` in the `always` block to compile `report.json` and upload diagnostic telemetry.
6. **Transition / Reboot Handshake:** If the stage completed an unsealing phase or installed an HWE kernel requiring a reboot, it initiates a clean system restart before continuing to the subsequent stage.

---

## 2. On-Device Execution & Stage Management

### 2.1. Manual Trigger
To manually trigger the Ansible playbook immediately on the node:
```bash
sudo systemctl restart gdc-provision.service
```

### 2.2. Live Log Streaming
To monitor the live execution output of the playbook:
```bash
# View live Ansible stdout via the systemd journal
sudo journalctl -u gdc-provision.service -f

# Or tail the raw persistent log file
tail -f /var/log/gdc-ansible-pull.log
```

### 2.3. Selective Stage Re-runs
Because the playbook uses a persistent state machine, restarting the service will silently skip stages that previously completed. If you want Ansible to re-execute a stage:

```bash
# Wipe the specific stage state you want to re-run
sudo rm -f /var/gdc-install/state/linux-ready.json

# Restart the provisioner service to re-evaluate the stage
sudo systemctl restart gdc-provision.service
```

### 2.4. Bypassing GDC Companion with Manual Facts (`gdc-fact-manual.json`)

During testing, network isolation, or when GDC Companion is unavailable, you can manually inject machine configuration facts for **Stage 5 (Cluster Ready)**. When `/var/gdc-install/state/gdc-fact-manual.json` is present on the node, Ansible slurps it directly, bypassing the Companion API lookup (`GET /v1/machine-info/{mac}`).

#### Sourcing / Exporting Facts from GDC Companion
You can obtain a valid JSON configuration directly from `gdc-companion`:
* **Web UI:** Navigate to the Machine Inventory view, select your target machine, and click **"Share / Download JSON"** to export the exact JSON configuration.
* **API / CLI:**
  ```bash
  curl -s -H "Authorization: Bearer <API_KEY>" \
    "https://<companion-host>/v1/machine-info/<MAC_ADDRESS>" > gdc-fact-manual.json
  ```
All manual fact files must strictly adhere to the official schema:
`/d/projects/google/gdc-companion/docs/machine-schema.json`.

#### Method A: Automated Injection via Workstation Tool (Recommended)
From your local workstation, run:
```bash
./bin/node-ops/inject-manual-facts.sh --node 192.168.4.236 --facts path/to/gdc-fact-manual.json
```
This script validates the JSON against `machine-schema.json`, uploads it to `/var/gdc-install/state/gdc-fact-manual.json`, deletes `/var/gdc-install/state/cluster-ready.json`, restarts `gdc-provision.service`, and tails the live journal.

#### Method B: Manual Injection on the Target Node
If executing commands directly on the target machine:
```bash
# 1. Place the facts file in the state directory
sudo mkdir -p /var/gdc-install/state
sudo cp gdc-fact-manual.json /var/gdc-install/state/gdc-fact-manual.json
sudo chown root:root /var/gdc-install/state/gdc-fact-manual.json
sudo chmod 0644 /var/gdc-install/state/gdc-fact-manual.json

# 2. Wipe the cluster-ready state to force re-evaluation
sudo rm -f /var/gdc-install/state/cluster-ready.json

# 3. Restart the provisioner service
sudo systemctl restart gdc-provision.service

# 4. Monitor live progress
sudo journalctl -u gdc-provision.service -f
```

---

## 3. Workstation Operations & Remote Push Tools

You can seamlessly sync code from your local development workstation and force remote nodes to execute updates. There are two primary workflows depending on whether you want to test the full systemd integration or run interactive debugging.

### 3.1. Hotfix Playbook Sync (Full Lifecycle Run)
If you have modified playbooks locally and want to test them completely integrated with the target node's `gdc-provision.service` systemd unit, use the hotfix push script. This script perfectly mimics a production update.

**What it does:**
1. Temporarily bypasses Gitea pre-receive hooks.
2. Performs a `git push` of your local code directly into the node's local `/var/lib/gitea/repos/gdc/bootstrap-playbooks.git` bare repository.
3. Wipes the requested stage's state JSON (e.g., `linux-ready.json`).
4. Executes `systemctl restart gdc-provision.service`.
5. Tails the journald logs back to your terminal.

```bash
# Push updates and re-run linux-ready stage on target node
./bin/node-ops/push-hotfix-playbook.sh --stage linux-ready 192.168.4.236
```

### 3.2. Direct Test Runner (Interactive Debugging)
If you need interactive visibility or want to run dry-run simulations, use the direct test runner. This bypasses the node's Gitea server and systemd timer entirely.

**What it does:**
1. Packages your local `src/ansible` directory.
2. Copies it over SSH/SCP to a temporary workspace on the node.
3. Runs `ansible-playbook` directly with real-time colored output streamed back to your terminal.

```bash
# Target physical node
GDC_TARGET_HOST=192.168.4.236 GDC_SSH_PORT=22 GDC_PASSWORD="troubled-marble-150" ./test/sync_and_run_ansible.sh

# Target QEMU sandbox
./test/sync_and_run_ansible.sh
```

You can append standard Ansible CLI arguments to test specific roles, tags, or check-modes:
```bash
# Run a dry-run check-mode simulation of the changes
GDC_TARGET_HOST=192.168.4.236 GDC_PASSWORD="..." ./test/sync_and_run_ansible.sh --check

# Run only the sysctl kernel tunings task
GDC_TARGET_HOST=192.168.4.236 GDC_PASSWORD="..." ./test/sync_and_run_ansible.sh --tags kernel_tuning
```

---

## 4. Node Credentials & Environment Reference

* **Target GDC Node IP:** e.g., `192.168.4.236`
* **Default Active User:** `temporary-installer` (Fallback to `gdc-admin` once Task 04 completes)
* **Default Password:** `troubled-marble-150`
* **Default SSH Private Key:** `test/test-keys/id_ed25519`
* **Target Node Ansible Path:** `/etc/gdc/ansible/`

---

## 5. State Health & Re-Image Decision Matrix

The synchronization utilities execute **automated state health checks** on the target node before pushing playbooks. You should execute a full **PXE Re-Image** of the node rather than a playbook-only sync when:

1. **LUKS Passcode File is Missing (`/etc/keys/temp_key.key`):**
   * **Indicator:** Stage 7 (TPM Sealing) has already successfully run and shredded the temporary passcode file.
   * **Consequence:** You can no longer test the clean LUKS key-enrollment or passcode slot wiping flows without re-imaging.
2. **gdc-admin Sudoers are Active (`/etc/sudoers.d/gdc-admin`):**
   * **Indicator:** Sudo administrative user accounts have already been fully deployed and configured on the node.
3. **Ubuntu Sources are Deactivated (`/etc/apt/sources.list.bak`):**
   * **Indicator:** Normal public APT repositories have already been deactivated and locked exclusively to local loopback mirrors.

---

## 6. Post-Execution Verification Checklist

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

## 7. Diagnostics & Troubleshooting

If a playbook run stalls or throws errors, inspect the on-device system logs:

* **Central Ansible Logs:** `journalctl -u gdc-provision -f` or `cat /var/log/gdc-ansible-pull.log`
* **Local Gitea Logs:** `journalctl -u gitea -n 100`
* **Local Nexus Logs:** `journalctl -u nexus -n 100`
* **System Diagnostic Compiler:** Trigger `/usr/local/bin/gdc-collector` to force an immediate full-state diagnostics compilation and upload to GDC Companion.
