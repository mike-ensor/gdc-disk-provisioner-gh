# Specification: GDC Ready-Linux & Idempotent Post-Install Provisioning Plan

**Spec Identifier:** `GDC-SPEC-READY-LINUX`  
**Status:** APPROVED (Spec-Review Pass)  
**Date:** 2026-07-01  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Executive Summary & Purpose

This design specification details the construction of the **GDC Ready-Linux Post-Install and Hardening Pipeline** for offline GDC edge deployments. The pipeline is designed to be executed local-first by `ansible-pull` on first boot to transform a raw baseline Ubuntu node into a hardened, secure GDC host ready for Kubernetes bootstrapping.

Our primary paradigm is **idempotent, local-first configuration**. To ensure reliability across varying levels of air-gap connectivity, we organize the deployment into a highly streamlined list of 12 sequential tasks. For each task, we identify dependencies, parameter opportunities, strict idempotency patterns, external requirements (tagged as `[external-dependency]`), and concrete system-level verification checks.

---

## 2. Technical Architecture & Task Lifecycle

The post-install pipeline runs as a unified linear flow with strict sequence checkpoints to prevent race conditions (such as trying to update packages before local APT keyrings are fully written and Ubuntu public mirrors are masked).

```text
       Task 01: Wait for local hubs (Gitea/Nexus to bind ports)
                               │
                               ▼
       Task 02: Nexus Repository Inception (REST API configs)
                               │
                               ▼
       Task 03: Local Workspace Layout (/var/gdc-install/)
                               │
                               ▼
       Task 04: Admin & Sudoers Provisioning (gdc-admin user)
                               │
                               ▼
       Task 05: Offline APT Inception (Write DEB822 & Mask Public lists)
                               │
                               ▼
       Task 06: Package upgrade & installation loop
                               │
                               ▼
       Task 07: Kernel Tuning (Sysctl & BPF JIT)
                               │
                               ▼
       Task 08: NTP & Timezone Alignment (UTC & Chrony)
                               │
                               ▼
       Task 09: Container Engines Setup (containerd & docker-ce)
                               │
                               ▼
       Task 10: Standalone gcloud SDK Setup & Symlinking
                               │
                               ▼
       Task 11: Security Hardening (UFW disable & Unattended Upgrades)
                               │
                               ▼
       Task 12: Offline Management Utilities (Logrotate & Update Scripts)
```

---

## 3. Unified Variable Schema (`src/ansible/vars/all.yml` Specification)

We establish a single source of truth for variables used inside our local provisioning playbooks. This keeps execution tasks generic, robust, and cleanly decoupled.

```yaml
# src/ansible/vars/all.yml
# ==============================================================================
# GDC Ready-Linux Central Configuration Variables
# ==============================================================================

# Core GDC OS packages from official Google package-server requirements
# (Ref: https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/installing/package-server#needed_packages_and_their_dependencies)
gdc_core_packages:
  - "python3"
  - "apt-transport-https"
  - "ca-certificates"
  - "conntrack"
  - "curl"
  - "software-properties-common"
  - "gnupg2"
  - "socat"
  - "iproute2"
  - "ebtables"
  - "ethtool"
  - "logrotate"
  - "libseccomp-dev"
  - "chrony"
  - "docker-ce"
  - "docker-ce-cli"
  - "containerd.io"
  - "tpm2-tools"
  - "libtss2-tcti-device"
  - "step-cli"
  - "auditd"
  - "audispd-plugins"
  - "unattended-upgrades" # Ensured for no-reboot security patching

# Packages to purge for OS slimming & security reduction
gdc_purge_packages:
  - "snapd"
  - "lxd"
  - "x11-common"

# Upstream Google NTP Server Sources
ntp_upstream_servers:
  - "time.google.com"
  - "time1.google.com"
  - "time2.google.com"
  - "time3.google.com"
  - "time4.google.com"

# Broad-gap step parameters for chrony
# - Allow stepping the clock on any update if the offset exceeds 1.0s (unlimited times)
chrony_makestep_threshold: "1.0"
chrony_makestep_limit: "-1"

# Target system sysctl limits for kernel parameters
gdc_sysctl_parameters:
  - { name: "fs.inotify.max_user_instances", value: "8192" }
  - { name: "fs.inotify.max_user_watches", value: "524288" }
  - { name: "net.core.bpf_jit_enable", value: "1" }

# Local Docker daemon registry-mirror address pointing to local Nexus Docker Group Port
gdc_docker_registry_mirror: "http://127.0.0.1:5001"

# Administrative user details
gdc_admin_user: "gdc-admin"
gdc_admin_group: "gdc-admin"
gdc_admin_additional_groups:
  - "sudo"
  - "docker"

# GDC Installation Artifact Directory Structure (under /var)
gdc_install_root: "/var/gdc-install"
gdc_install_directories:
  - "config-sync-configs"
  - "bmctl-workspace"
  - "external-secrets"
  - "keys"
  - "kubeconfig"
  - "scripts"
  - "sds-configs"
  - "snapshots"
  - "tools"
  - "tools/google-cloud-sdk"
  - "tools/node-agent"
  - "vmruntime-configs"

# NodeAgent Configuration Settings
gdc_nodeagent_install_dir: "/var/gdc-install/tools/node-agent"
gdc_nodeagent_version: "1.33.0"
# Local loopback GGD Nexus raw path or authenticated GCS bucket source
gdc_nodeagent_binary_source_url: "http://127.0.0.1:8081/repository/gdc-raw-hosted/nodeagent/nodeagentd"

# Google Cloud SDK Configuration (Non-apt setup)
# (Ref: https://docs.cloud.google.com/sdk/docs/install-sdk#latest-version)
gdc_gcloud_tarball_path: "/cdrom/custom-data/tools/google-cloud-cli-linux-x86_64.tar.gz"
gdc_gcloud_install_dir: "/var/gdc-install/tools/google-cloud-sdk"

# Google Cloud SDK components to install natively
gdc_gcloud_components:
  - { app: "nomos" }
  - { app: "gsutil" }
  - { app: "kubectl" }
  - { app: "kubectl-oidc" }

# Enforce system-wide UTC Timezone
gdc_system_timezone: "Etc/UTC"

# Service Update Scripts to deploy to /var/gdc-install/scripts/
gdc_service_update_scripts:
  - { name: "update-gitea.sh", service: "gitea" }
  - { name: "update-nexus.sh", service: "nexus" }
  - { name: "update-nodeagent.sh", service: "nodeagent" }
  - { name: "update-docker.sh", service: "docker" }

# Package Blacklist for Unattended Upgrades to prevent automatic node reboots
gdc_unattended_blacklist:
  - "linux-image-.*"
  - "linux-headers-.*"
  - "linux-modules-.*"
  - "linux-modules-extra-.*"
  - "intel-microcode"
  - "amd64-microcode"
  - "libc6"
  - "libc6-dev"
```

---

## 4. Streamlined Ready-Linux Activity Matrix

Below is our fully evaluated, optimized list of tasks designed to eliminate duplicate tasks, simplify variable scopes, and establish hard boundaries for offline verification.

### Task 01: Wait on Boundary Service Hub Readiness
* **Description:** Block playbook execution until local services (Gitea and Nexus), copied over during Subiquity late-commands, have successfully initialized and bound to their loopback ports.
* **Classification:** `[strictly-local]` (communicates strictly via local loopback port bindings).
* **Dependencies:**
  * *Implicit:* Gitea and Nexus binaries are copied to the disk and systemd units are enabled.
  * *Explicit:* Ports `3000` (Gitea) and `8081` (Nexus) are actively listening.
* **Variable Opportunities:** None (ports and timeouts are standard properties of node boot).
* **Idempotency Strategy:** Use Ansible's `wait_for` module with a generous timeout parameter (300s) to gracefully block execution without crashing. Since this is read-only, repeated loops are safe and generate zero side-effects.
* **Concrete Verification Method:**
  ```bash
  ss -ltun | grep -E "3000|8081"
  ```

### Task 02: Sonatype Nexus Repository Inception
* **Description:** Initialize the local Sonatype Nexus manager, rotate default credentials, and register GDC repository groups (APT Hosted/Proxy, Docker Hosted/Group/Proxy on Ports 5001/5002, and Raw Hosted/Proxy).
* **Classification:** `[strictly-local]` (communicates with local REST API, though proxy configurations define endpoints that lead to external sources).
* **Dependencies:**
  * *Implicit:* Task 01 must complete successfully.
  * *Explicit:* Nexus binary presence and initial password file `admin.password` availability.
* **Variable Opportunities:** Parameterize using `nexus_admin_password` (temporary bootstrap password).
* **Idempotency Strategy:** Read the existing repositories list via the GET API `/service/rest/v1/repositories` and conditionalize repository creations (using `when: "'gdc-apt-hosted' not in existing_repos"`) to prevent duplicate creation failures (HTTP 400).
* **Concrete Verification Method:**
  ```bash
  curl -s -u admin:<password> http://127.0.0.1:8081/service/rest/v1/repositories | jq -r '.[].name'
  ```

### Task 03: Local Workspace Layout Provisioning
* **Description:** Recursively configure the root folder `/var/gdc-install/` and its required subdirectories, ensuring absolute ownership is granted to `gdc-admin:gdc-admin` with mode `0755` permissions.
* **Classification:** `[strictly-local]` (fully local folder creation).
* **Dependencies:** None.
* **Variable Opportunities:** Parameterize using `gdc_install_root: "/var/gdc-install"` and `gdc_install_directories` (list of subfolders).
* **Idempotency Strategy:** Leverage Ansible's `ansible.builtin.file` with `state: directory`. This natively asserts path state, ownership, and mode, skipping operations if directories are already present with correct descriptors.
* **Concrete Verification Method:**
  ```bash
  ls -la /var/gdc-install && find /var/gdc-install -type d -printf "%p -> %u:%g (%m)\n"
  ```

### Task 04: Administrator & Sudoers Provisioning
* **Description:** Create the system-level administrator user `gdc-admin` and its group, enroll in supplementary namespaces (`sudo`, `docker`), and drop secure passwordless sudo permissions.
* **Classification:** `[strictly-local]` (local user, group, and PAM management).
* **Dependencies:**
  * *Implicit:* Task 03 must execute first (so `gdc-admin` exists before directories ownership is assigned).
* **Variable Opportunities:** Parameterize using `gdc_admin_user`, `gdc_admin_group`, and `gdc_admin_additional_groups` list.
* **Idempotency Strategy:** Use `ansible.builtin.user` and `ansible.builtin.copy` to write `/etc/sudoers.d/gdc-admin` with mode `0440`. Sudoers content will overwrite identically, generating zero state drift.
* **Concrete Verification Method:**
  ```bash
  id gdc-admin && sudo -U gdc-admin -l | grep -q "NOPASSWD:ALL"
  ```

### Task 05: Offline APT Repository Inception
* **Description:** Register local loopback Nexus repositories in DEB822 sources list (`/etc/apt/sources.list.d/gdc-nexus.sources`), register Nexus trusted GPG keys, and deactivate default public Ubuntu repository files.
* **Classification:** `[strictly-local]` (local filesystem and sources layout manipulation).
* **Dependencies:**
  * *Implicit:* Task 02 must complete successfully so repositories are listening in Nexus.
* **Variable Opportunities:** None (sources and components are tied to Ubuntu release `noble`).
* **Idempotency Strategy:** Use `copy` to overwrite `gdc-nexus.sources`. Move default public sources using `ansible-builtin.stat` coupled with conditional renaming (`when: public_sources_stat.stat.exists`), preventing repeated commands from throwing "No such file or directory" exceptions.
* **Concrete Verification Method:**
  ```bash
  apt-get update -o Dir::Etc::sourcelist="sources.list.d/gdc-nexus.sources" -q
  ```

### Task 06: Package Upgrade & Dependency Installation
* **Description:** Execute safe offline system-wide upgrades and loop-install GDC core dependencies (Chrony, Docker-CE, containerd, step-cli, etc.) completely offline.
* **Classification:** `[external-dependency]` (needs to pull packages, which requires either an active internet connection in Connected mode or a pre-seeded, synced local Nexus blob cache in Private modes).
* **Dependencies:**
  * *Explicit:* Task 05 must execute first to ensure APT pulls exclusively from the local mirror.
* **Variable Opportunities:** Parameterize utilizing `gdc_core_packages` (list of 22 dependencies extracted from Google requirements).
* **Idempotency Strategy:** Query package status using `dpkg -s` before calling `apt`, registering the list of uninstalled packages. Execute `apt` only on the filtered list of missing dependencies, saving significant execution time.
* **Concrete Verification Method:**
  ```bash
  dpkg -l | grep -E "chrony|docker-ce|containerd|step-cli"
  ```

### Task 07: Kernel Tuning (Sysctl & BPF JIT)
* **Description:** Apply system-level GDC performance limits (`fs.inotify` user instances and user watches) and enable the BPF JIT compiler in the kernel.
* **Classification:** `[strictly-local]` (modifies system kernel runtime configurations).
* **Dependencies:** None.
* **Variable Opportunities:** Parameterize using `gdc_sysctl_parameters` list of structures.
* **Idempotency Strategy:** Deploy configurations to `/etc/sysctl.d/99-gdc.conf` using a copy block. Register the file state and run `/sbin/sysctl -p /etc/sysctl.d/99-gdc.conf` only if modifications to the configuration file are detected (`when: sysctl_deploy.changed`).
* **Concrete Verification Method:**
  ```bash
  sysctl fs.inotify.max_user_watches fs.inotify.max_user_instances net.core.bpf_jit_enable
  ```

### Task 08: NTP Time Alignment & UTC Timezone Enforcements
* **Description:** Stopped and mask `systemd-timesyncd`, configure UTC system timezone, and configure `chrony` with Google NTP pools and wide-gap stepping capabilities.
* **Classification:** `[external-dependency]` (requires outbound network connectivity to Google NTP pools to perform real-time clock synchronization, though Chrony itself installs and initializes offline).
* **Dependencies:**
  * *Explicit:* Chrony package must be installed via Task 06.
* **Variable Opportunities:** Parameterize utilizing `ntp_upstream_servers` list and `gdc_system_timezone: "Etc/UTC"`.
* **Idempotency Strategy:** Disable `systemd-timesyncd` using masked parameters in `systemd` module. Use `ansible.builtin.template` to output `/etc/chrony/chrony.conf` and restart the `chrony` service only if the configuration changes. Enforce UTC timezone using `ansible.builtin.timezone`.
* **Concrete Verification Method:**
  ```bash
  timedatectl | grep -E "Time zone|System clock synchronized"
  ```

### Task 09: Container Engines Setup & Loopback Redirects
* **Description:** Configure `docker-ce` and `containerd` to use systemd-cgroup drivers, map offline registry mirror translations under `/etc/containerd/certs.d/`, and point daemon pulling requests to loopback Port `5001`.
* **Classification:** `[strictly-local]` (modifies local JSON/TOML configuration maps and local services).
* **Dependencies:**
  * *Explicit:* Docker and containerd packages must be installed via Task 06.
* **Variable Opportunities:** Parameterize utilizing `gdc_docker_registry_mirror: "http://127.0.0.1:5001"`.
* **Idempotency Strategy:** Overwrite `/etc/docker/daemon.json` and `/etc/containerd/config.toml` directly. Restart `docker` and `containerd` services only if their respective configuration files were modified.
* **Concrete Verification Method:**
  ```bash
  systemctl is-active containerd docker && docker info --format '{{json .RegistryConfig.IndexConfigs}}' | grep "127.0.0.1:5001"
  ```

### Task 10: Standalone Google Cloud SDK Inception
* **Description:** Extract pre-seeded standalone Google Cloud SDK archive, quietly run install script, download and install components (`nomos`, `gsutil`, `kubectl`, `kubectl-oidc`), and establish global symlinks under `/usr/local/bin/`.
* **Classification:** `[external-dependency]` (running `gcloud components install` requires internet access in Connected mode, or a preloaded, synced Google SDK raw cache in Private modes).
* **Dependencies:**
  * *Implicit:* Core Python3 runtime must be installed via Task 06.
  * *Explicit:* Standalone tarball must be cached under `/cdrom/custom-data/tools/`.
* **Variable Opportunities:** Parameterize using `gdc_gcloud_tarball_path`, `gdc_gcloud_install_dir`, and `gdc_gcloud_components` list.
* **Idempotency Strategy:** Leverage `unarchive` with a `creates` check to prevent repeated extractions. Verify the presence of component binaries inside `/var/gdc-install/tools/google-cloud-sdk/bin/` before executing component installs to prevent slow, redundant network calls.
* **Concrete Verification Method:**
  ```bash
  gcloud --version && kubectl version --client && nomos version
  ```

### Task 11: Security & Firewall Hardening (UFW & Unattended Upgrades)
* **Description:** Disable, stop, and mask Uncomplicated Firewall (`ufw`) to prevent loopback blocks. Configure daily reboot-free unattended upgrades with kernel package blacklists.
* **Classification:** `[strictly-local]` (reboot-free upgrades run locally, though the upgrade execution relies on APT dependencies mapped in Task 06).
* **Dependencies:**
  * *Explicit:* `unattended-upgrades` must be installed via Task 06.
* **Variable Opportunities:** Parameterize using `gdc_unattended_blacklist` list.
* **Idempotency Strategy:** Disable and mask `ufw` using the `systemd` module. Use standard `copy` blocks to persistently overwrite `/etc/apt/apt.conf.d/20auto-upgrades` and `/etc/apt/apt.conf.d/50unattended-upgrades`, rendering changes only on modifications.
* **Concrete Verification Method:**
  ```bash
  ufw status && cat /etc/apt/apt.conf.d/50unattended-upgrades | grep -E "Package-Blacklist|Automatic-Reboot"
  ```

### Task 12: Offline Management Utilities (Logrotate & Update Scripts)
* **Description:** Configure weekly cron to update `gcloud` components (`gcloud components update -q`). Deploy skeleton update scripts to `scripts/` with TODO comments and execute-rights. Enable high-frequency hourly log rotation by establishing an executable symlink from `/etc/cron.daily/logrotate` to `/etc/cron.hourly/logrotate`.
* **Classification:** `[strictly-local]` (except for the weekly gcloud crontab update job, which is explicitly tagged as `[external-dependency]`).
* **Dependencies:**
  * *Implicit:* Task 03 and Task 07 must complete successfully.
* **Variable Opportunities:** Parameterize using `gdc_service_update_scripts` list of configurations.
* **Idempotency Strategy:** Use `ansible.builtin.cron` and `ansible.builtin.copy` directly. Create the logrotate symlink using `ansible.builtin.file` with `force: yes` and `state: link`, assuring path alignments.
* **Concrete Verification Method:**
  ```bash
  ls -la /etc/cron.hourly/logrotate && ls -la /var/gdc-install/scripts/
  ```

---

## 5. Playbook Task Mapping & Tagging Schema

The Ansible tasks inside `src/ansible/local.yml` are tagged systematically to allow running specific sub-segments of the provisioning suite depending on node topologies and connectivity constraints:

### 5.1. Core Tags Taxonomy:
1. `machine: connected` — Task requires full, unrestricted outbound public internet access (e.g., DNS pings, public component updating).
2. `machine: private-mode-normal` — Task requires offline operations but integrates with the node's local Sonatype Nexus/Gitea repositories (e.g., system upgrades or package installations using local proxies). Will fail if mirrors are not pre-seeded.
3. `machine: private-mode-strict` — Task can execute in a 100% disconnected state without contacting any remote network, local caches, or automated update loops.
4. `external-dependency` — Task requires internet-facing downloads or real-time connectivity to successfully complete its provisioning step (used directly during Phase 1 pre-seeding compilations).

### 5.2. Streamlined Task Matrix & Tag Assignments:

| Task ID & Name | Compatibility Tag | External Dependency Tag | Verification Command |
| :--- | :--- | :--- | :--- |
| **Task 01: Wait on boundary hubs** | All Modes | `strictly-local` | `ss -ltun \| grep -E "3000\|8081"` |
| **Task 02: Sonatype Nexus setup** | All Modes | `strictly-local` | `curl -s http://127.0.0.1:8081/...` |
| **Task 03: Workspace folder setup** | All Modes | `strictly-local` | `ls -la /var/gdc-install` |
| **Task 04: Admin & Sudoers Setup** | All Modes | `strictly-local` | `sudo -U gdc-admin -l` |
| **Task 05: Offline APT setup** | All Modes | `strictly-local` | `cat /etc/apt/sources.list.d/...` |
| **Task 06: Package installation loop** | Connected, Private Normal | **`external-dependency`** | `dpkg -l \| grep -E "chrony\|docker-ce"` |
| **Task 07: Kernel Tuning (sysctl)** | All Modes | `strictly-local` | `sysctl net.core.bpf_jit_enable` |
| **Task 08: NTP Alignment & Timezone**| Connected, Private Normal | **`external-dependency`** | `timedatectl` |
| **Task 09: Container Engines Setup** | All Modes | `strictly-local` | `systemctl is-active containerd` |
| **Task 10: Standalone gcloud SDK** | Connected, Private Normal | **`external-dependency`** | `gcloud --version` |
| **Task 11: Security (UFW & Upgrades)**| All Modes | `strictly-local` | `ufw status` |
| **Task 12: Offline Update Scripts** | All Modes | `strictly-local` | `ls -la /var/gdc-install/scripts` |
| **gcloud weekly update cron job** | Connected | **`external-dependency`** | `cat /etc/cron.weekly/gcloud-update` |

---

## 6. containerd configuration.toml Layout
The `/etc/containerd/config.toml` file is written out as:
```toml
version = 2
[plugins]
  [plugins."io.containerd.grpc.v1.cri"]
    sandbox_image = "127.0.0.1:5001/pause:3.9"
    [plugins."io.containerd.grpc.v1.cri".containerd]
      default_runtime_name = "runc"
      [plugins."io.containerd.grpc.v1.cri".containerd.runtimes]
        [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
          runtime_type = "io.containerd.runc.v2"
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
            SystemdCgroup = true
    [plugins."io.containerd.grpc.v1.cri".registry]
      config_path = "/etc/containerd/certs.d"
```

---

## 7. NodeAgent Sequence and Dependencies

Due to how `bmctl` manages the lifecycle of GDC NodeAgent, there is a strict path dependency in the installation sequence:

1. **Ready-Linux Phase (This Playbook):** Pre-stages the target directory structure (`/var/gdc-install/tools/node-agent/`) and installs system dependencies (`docker-ce`, `containerd`). The `nodeagentd` binary and mTLS certificates are **not yet active** on the system unless the ISO is pre-seeded.
2. **Workstation Orchestration Phase (Fallback):** The operator runs `bmctl nodeagent deploy` from the admin workstation. This command connects via SSH to the `gdc-admin` user, downloads/transfers the correct GDC-release version of `nodeagentd` into `/var/gdc-install/tools/node-agent/`, generates client/server mTLS credentials, signs them with the Cluster CA, and registers `/usr/local/bin/nodeagentd`.
3. **Zero-SSH Pre-Seeded ISO Path (Standard GGD):** In pre-seeded GGD environments, the ISO installs the `nodeagentd` binary, registers `/usr/local/bin/nodeagentd`, pre-seeds unique server/client mTLS certificates on first boot, and immediately runs `nodeagentd.service` on Port `9192`.
4. **Cluster Turnup Phase:** When cluster turnup executes, `bmctl` transitions operations entirely to secure mTLS gRPC over Port `9192`, disabling further SSH access.

---

## 8. Defensive Security Audit & Approved Mitigations

The GDC post-install and hardening pipeline has been reviewed by our Cybersecurity Architecture Team. Below are the approved mitigations and active security postures integrated natively within our configurations:

### GDC-SEC-001: Broad Privilege Boundary via Sudoers
* **Status: APPROVED (Risk Mitigated)**
* **Mitigation Strategy:** While root-level passwordless sudo is an explicit requirement for `bmctl` node turnup and lifecycle operations, the administrative login surface is heavily hardened:
  1. Enforced SSH-Key-Only Public Authentication inside `/etc/ssh/sshd_config.d/gdc.conf` to block all password-based logins.
  2. Complete disabling of keyboard-interactive and password mechanisms.
  3. Deploying active `auditd` kernel rules to monitor `/etc/sudoers.d/gdc-admin` and track all execution runs.

### GDC-SEC-002: Residual Plaintext LUKS Key Remnants (SSD Block Carving)
* **Status: APPROVED (Remediated)**
* **Remediation Strategy:** To eliminate the physical presence of bootstrap encryption keys in raw SSD sectors, the temporary passcode `/etc/keys/temp_key.key` is securely shredded before file deletion. Rather than a simple index unlink, the system executes:
  ```bash
  shred -u -n 3 /etc/keys/temp_key.key
  ```
  This overwrites the physical SSD storage blocks with multiple random passes, rendering recovery via SSD carving impossible.

### GDC-SEC-003: Low-Level Kernel & glibc Patching Gaps
* **Status: IGNORED (Updates Managed by Future Feature Set)**
* **Current Posture:** To protect node workloads and maintain maximum cluster uptime, automatic reboots are disabled and kernel packages are blacklisted from unattended upgrades. Live patch integrations and planned maintenance rolling reboots will be managed dynamically via subsequent feature releases.

### GDC-SEC-004: Symlink Target Permission Hijacking (cron.hourly)
* **Status: APPROVED (Remediated)**
* **Remediation Strategy:** To block local escalation vectors via cron execution hijacking, strict root ownership and mode `0755` write limits are enforced on both the hourly logrotate symlink (`/etc/cron.hourly/logrotate`) and its target script (`/etc/cron.daily/logrotate`). This prevents non-root users from altering the executable script.

### GDC-SEC-005: Workspace Path Pollution and Execution Hijacking
* **Status: APPROVED (Remediated)**
* **Remediation Strategy:** All global symlink destinations registered under `/usr/local/bin/` (including `nodeagentd`, `gcloud`, `gsutil`, and `bq`) are fully owned by `root:root` with strict mode `0755` execution boundaries. Even if `gdc-admin`'s user space under `/var/gdc-install/` is compromised, they cannot modify the symlink pointers executing inside the global PATH.

---

## 9. Future GPG Signed-Commit Enforcement for Ansible-Pull

To protect edge devices from unauthorized playbook manipulations, we design a 100% secure **Future GPG Signed-Commit Enforcement** pathway. The local git execution client inside `ansible-pull` can be configured to reject any playbook updates that are not cryptographically signed by authorized GGD keys.

### 9.1. Proactive Architectural Accommodations

To make this future transition seamless and frictionless, we implement three core structural scaffolds on Day 1:

1. **Environmental Decoupling (Systemd Env File):**  
   The execution flags for `ansible-pull` are not hardcoded inside systemd service units. Instead, they are resolved from the environment file `/etc/default/gdc-provision`:
   * **Dev/Stage Mode:** `ANSIBLE_PULL_FLAGS=""`
   * **Prod Enforced Mode:** `ANSIBLE_PULL_FLAGS="--verify-commit"`
   This allows enabling signed commits simply by changing a single variable in `build.env` at compile-time without touching system code.

2. **Pre-Seeded GPG Release Keyring:**  
   During Phase 1 (ISO generation), the GGD release trusted public GPG keys are imported and saved as a system-wide keyring under `/etc/gpg/gdc-release.gpg` (copied over by the post-install Ansible-Pull playbooks). This ensures that the trust anchor is physically on disk and ready to serve verification requests.

3. **Gitea Commit Verification Prep:**  
   The local Gitea instance on Port `3000` is pre-configured to store and index GGD signature profiles.

---

## 10. Ansible Housekeeping & Verification Standards

All playbooks, variables files, and execution play scripts inside this project adhere to GDC's structural housekeeping standards:

1. **Strict Linter Adherence (`ansible-lint`):** All written YAML tasks must pass `ansible-lint` static analysis with zero fatal violations to enforce enterprise code quality and secure modules definitions.
2. **YAML Format Standardisation:** Adhere to clean standard indent formatting (2-space nested indent bounds) to maintain structural consistency.
3. **Least Code Necessary Principle:** Focus on declarative and minimal implementations. Leverage native Ansible modules over shell/command tasks whenever possible to maximize execution idempotency and performance footprints.

---

## 11. Local Verification & Diagnostics

Verification of the post-install configurations is executed continuously via our static test suite:
1. **Playbook Validation (`test/verify_ansible.sh`):**
   * Static syntax validation check (`ansible-playbook --syntax-check`).
   * Dry-run simulation modes checking state changes without host mutations.
   * Automated best-practice checkups using `ansible-lint`.
2. **Post-Provision Host Verification Checks:**
   * Assert UFW is completely inactive and masked.
   * Assert `fs.inotify` limits are active and persistent in sysctl.
   * Assert local Docker daemon redirects pulls to loopback Port 5001.
   * Confirm system clock status is active and synchronized (`timedatectl`).
   * Assert system timezone matches `Etc/UTC`.
   * Assert folder structure `/var/gdc-install/` exists and is owned by `gdc-admin:gdc-admin` with `0755` mode.
   * Confirm passwordless sudo rules for `gdc-admin` are functional.
   * Confirm `/usr/local/bin/nodeagentd` symlink exists and points to `/var/gdc-install/tools/node-agent/nodeagentd`.
   * Assert `containerd` service is enabled and running under systemd manager.
   * Confirm `/etc/cron.hourly/logrotate` exists as an executable symlink pointing to `/etc/cron.daily/logrotate`.
   * Confirm `/usr/local/bin/gcloud`, `/usr/local/bin/gsutil`, and `/usr/local/bin/bq` exist as symlinks.
   * Confirm all specified gcloud components (`nomos`, `kubectl`, `kubectl-oidc`) exist as symlinks in `/usr/local/bin/`.
   * Confirm `unattended-upgrades` is active and configured for reboot-free operations.
   * Confirm `gcloud` weekly update cron task is registered in `/etc/cron.weekly/`.
