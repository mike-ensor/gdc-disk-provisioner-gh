# GDC Node System Services & Lifecycle

This document provides a registry of the critical system-level and OS-level services, tools, and background loops that govern a deployed GDC bare-metal node. It outlines their purpose, file locations, and update/maintenance lifecycle.

## Core Management Services

### 1. `gdc-provision.timer` / `gdc-provision.service` (Ansible-Pull)

*   **Purpose:** The central decentralized orchestration engine. It triggers `ansible-pull` locally to continuously evaluate and correct the machine's state against the node's local configuration repository (pulled from Gitea or executed directly).
*   **Binaries/Dependencies:** `ansible-pull`, `git`, `/usr/bin/python3`.
*   **Configuration:**
    *   Systemd Service: `/etc/systemd/system/gdc-provision.service`
    *   Systemd Timer: `/etc/systemd/system/gdc-provision.timer` (Runs daily)
    *   Environment: `/etc/default/gdc-provision` (Contains `ANSIBLE_PULL_FLAGS`, exclude patterns)
*   **Logs:** Standard systemd journal (`journalctl -u gdc-provision.service`).
*   **Update Mechanism:** Automatically updated when new Ansible code is committed to the local Nexus/Gitea repository and the loop fires. Updates to the Ansible binaries themselves rely on the offline system upgrade path (`unattended-upgrades`).

### 2. `node-agent.service` (GDC Node Agent)

*   **Purpose:** The primary daemon responsible for interfacing between the bare-metal OS and the Kubernetes/GDC management cluster. It reports node health, network status, and hardware metrics.
*   **Binaries:** `/var/gdc-install/tools/node-agent/nodeagentd`
*   **Configuration:**
    *   Systemd Unit: `/etc/systemd/system/node-agent.service`
    *   Configuration fetched dynamically or passed via environment variables during the `CLUSTER_READY` Ansible stage.
*   **Logs:** Standard systemd journal (`journalctl -u node-agent.service`).
*   **Update Mechanism:** Manual / Scripted. A skeleton script `/var/gdc-install/scripts/update-nodeagent.sh` is provided. Future iterations will map this to an automated pull from the GDC Nexus proxy when a new version is validated.

## OS & Dependency Lifecycle

### 3. Google Cloud SDK (`gcloud`)

*   **Purpose:** Provides the CLI tools (`gcloud`, `gsutil`, `bq`, `kubectl`) required for the node to interact with GCP APIs, Secret Manager, and GCS buckets.
*   **Binaries:** Extracted to `/var/gdc-install/tools/google-cloud-sdk/bin/`. Symlinked to `/usr/local/bin/`.
*   **Configuration & State:**
    *   Global config: `/var/gdc-install/tools/google-cloud-sdk/`
    *   User config (for `gdc-admin` and `root`): `~/.config/gcloud/`
*   **Authentication:** Orchestrated by the `machine_orchestration` Ansible role, which fetches a short-lived OAuth token from the GDC Companion and applies it via `gcloud config set auth/access_token` and `gcloud config set account`.
*   **Logs:** `/var/gdc-install/logs/gcloud-update.log` (Rotated weekly).
*   **Update Mechanism:** Automated. A cron job (`/etc/cron.d/ansible_gcloud-update`) runs as the `gdc-admin` user at 4:00 AM local time every Sunday. It executes `gcloud components update -q`.

### 4. `unattended-upgrades` (Offline Package Updates)

*   **Purpose:** Ensures the underlying Ubuntu OS receives critical security patches and updates without requiring an external internet connection. It is configured to pull strictly from the local GDC Nexus proxy repository.
*   **Binaries:** `/usr/bin/unattended-upgrade`
*   **Configuration:**
    *   APT Sources: `/etc/apt/sources.list.d/gdc-nexus.sources`
    *   Unattended Config: `/etc/apt/apt.conf.d/50unattended-upgrades` (Configured to blacklist kernel updates to prevent unexpected reboots)
    *   Timers: `/etc/apt/apt.conf.d/20auto-upgrades` (enables `apt-daily.timer` and `apt-daily-upgrade.timer`)
*   **Logs:** `/var/log/unattended-upgrades/unattended-upgrades.log`
*   **Update Mechanism:** Automated by systemd timers. It silently runs in the background and applies DEB packages downloaded from the local Nexus cache.


## System Logging & Auditing

The GDC OS uses a strict, rotated logging architecture designed to balance deep auditing with strong constraints against disk pressure.

### 6. `systemd-journald` (Primary System Logger)
*   **Purpose:** The core binary logging daemon for systemd. Captures stdout/stderr from all systemd units (including `gitea`, `nexus`, and `node-agent`).
*   **Binaries:** `/lib/systemd/systemd-journald`
*   **Configuration:** `/etc/systemd/journald.conf.d/99-gdc-logging.conf`
*   **Constraints:**
    *   Maximum total disk usage is capped at **50MB**.
    *   Maximum individual file size is **10MB**.
    *   Maximum retention is **1 month**.
    *   Forwards events natively to Syslog (`rsyslog`).
*   **Logs Location:** `/var/log/journal/` (Persistent binary format, readable via `journalctl`).

### 7. `rsyslog` (Syslog Router)
*   **Purpose:** Separates and routes forwarded journal logs and native syslog streams into standard UNIX flat files.
*   **Binaries:** `/usr/sbin/rsyslogd`
*   **Configuration:** `/etc/rsyslog.d/99-gdc-syslog.conf`
*   **Logs Location:**
    *   `/var/log/syslog` (General info)
    *   `/var/log/secure` (Authentication/privilege events)
    *   `/var/log/cron` (Cron scheduling events)
    *   `/var/log/boot.log` (Local boot sequences)

### 8. `auditd` (Security Auditing)
*   **Purpose:** Deep kernel-level monitoring of system calls, file modifications, and security events based on CIS compliance rules.
*   **Binaries:** `/sbin/auditd`
*   **Configuration:** `/etc/audit/rules.d/99-gdc-audit.rules`
    *   Monitors critical system files (`/etc/passwd`, `/etc/sudoers`, `/etc/network`, etc.) for any `wa` (write/append) modifications.
*   **Logs Location:** `/var/log/audit/audit.log`

### 9. Syslog & Auditd Rotation (`logrotate`)
*   **Purpose:** A dedicated, aggressive logrotate configuration protects the OS from log spam originated by syslog or auditd.
*   **Configuration:** `/etc/logrotate.d/gdc-syslog`
    *   **Schedule:** Rotated `daily`.
    *   **Size Constraint:** If a log hits **50MB**, it rotates immediately.
    *   **Retention:** Keeps exactly **14 days** of history.
    *   **Compression:** Shards are compressed, with the active shard delayed by one cycle to prevent I/O locks.

## Additional Utilities

### 5. Logrotate

*   **Purpose:** Prevents log files from consuming all available disk space.
*   **Binaries:** `/usr/sbin/logrotate`
*   **Configuration:** 
    *   Base: `/etc/logrotate.conf`
    *   Includes: `/etc/logrotate.d/*` (e.g., `/etc/logrotate.d/gcloud-update`)
*   **Execution:** Symlinked from `/etc/cron.daily/logrotate` to `/etc/cron.hourly/logrotate` by the GDC provisioner to ensure high-frequency rotation for aggressive logs.