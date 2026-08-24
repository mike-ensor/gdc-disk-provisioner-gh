# Edge Git Infrastructure: Gitea Expansion Proposal

This document compares the current Gitea implementation in the `gdc-disk-provisioner` repository against the proposed Edge Git Infrastructure Architecture (Self-Hosted Gitea via Systemd).

Currently, the implementation treats Gitea more like a static filesystem directory for hosting bare git repos rather than leveraging it as a true Git forge.

Here is the detailed comparison and contrast between the current state of the codebase and the proposed architecture:

### 1. Conceptual Architecture & Repo Ingestion (USB/Private Mode)
*   **Current:** During ISO remastering (`src/build/remaster.sh`), a bare Git repository (`bootstrap-playbooks.git`) is manually assembled and copied directly into `/custom-data/gitea/repos/gdc/` (which ends up at `/var/lib/gitea/repos/gdc/`). `ansible-pull` then accesses this directly via standard filesystem paths. This completely bypasses Gitea's internal database, HTTP stack, and webhook triggers.
*   **Proposed:** The proposal strictly forbids manual alteration of the raw filesystem behind Gitea to prevent database drift and corruption. All offline/USB ingestions must be staged (e.g., cloned to `/tmp`) and imported via a standard `git push --mirror http://127.0.0.1:3000/...` to ensure audit trails, version histories, and Gitea's internal DB are correctly maintained.

### 2. Configuration (`app.ini`) & Security Posture
*   **Current:** There is **no** `app.ini` tracked or templated anywhere in the codebase. Gitea is left to auto-generate its configuration on the first run, which leaves the instance in a vulnerable state (e.g., listening on `0.0.0.0`, open user registration, and web-installer unlocked). 
*   **Proposed:** Enforces a strictly locked-down `/etc/gitea/app.ini` owned by `root:git` (`chmod 640`). It explicitly binds to localhost (`HTTP_ADDR = 127.0.0.1:3000`) for reverse proxy/firewall isolation, sets `DISABLE_REGISTRATION = true`, `INSTALL_LOCK = true`, and sets `RUN_MODE = prod`. 

### 3. Systemd Hardening & Process Isolation
*   **Current:** The current `src/build/templates/gitea.service.j2` is extremely minimal. It runs as the `git` user but lacks any Linux security sandboxing.
*   **Proposed:** Introduces heavy systemd sandboxing. The proposal adds directives like `CapabilityBoundingSet=CAP_NET_BIND_SERVICE`, `ProtectSystem=full`, `PrivateTmp=true`, `PrivateDevices=true`, `ProtectKernelTunables=true`, and `MemoryDenyWriteExecute=true`. This effectively jails the Gitea process, drastically reducing the blast radius if the web interface is compromised.

### 4. Filesystem Structure & Binary Location
*   **Current:** The Gitea binary is dropped directly into the state directory at `/var/lib/gitea/gitea` alongside repositories and logs. 
*   **Proposed:** Adheres to standard FHS (Filesystem Hierarchy Standard). The executable goes to `/usr/local/bin/gitea`, configuration goes to `/etc/gitea/` (enforcing immutability against the `git` user), and state/data lives cleanly in `/var/lib/gitea/{custom,data,log}`.

### 5. Upstream/Cloud Synchronization 
*   **Current:** Cloud synchronization is not codified or documented in the repository. The current mechanism only focuses on the first-boot offline clone.
*   **Proposed:** Explicitly defines synchronization patterns (Pull Mirrors for read-only config distribution, Push Mirrors for upstream telemetry, Edge Forking for field work) and warns that bidirectional synchronization on shared branches is an anti-pattern that causes non-fast-forward merge lockups in edge environments.

### Summary of Required Changes
To align the current codebase with the proposal:
1.  **Systemd Hardening:** The systemd unit (`gitea.service.j2`) needs a complete overhaul to apply security constraints.
2.  **Configuration Lockdown:** An `app.ini` needs to be explicitly seeded to lock down the instance.
3.  **HTTP-based Interaction:** The `gdc-provision.service` (along with the ISO remastering process) needs to be refactored to communicate with Gitea via HTTP (`http://127.0.0.1:3000`) rather than cheating via local disk paths.
4.  **FHS Alignment:** Filesystem locations for the binary and configurations need to move to standard FHS paths (`/usr/local/bin/gitea` and `/etc/gitea`).

---

## Proposed Architecture Reference

*Reference source: [Edge Git Infrastructure Architecture](https://docs.google.com/document/d/177iuhriOyoWmgykeHxqju0M4gHLjxPSL5uRHmWEuroA/edit?pli=1&tab=t.nnad1myn1wyk)*

```yaml
title: "Edge Git Infrastructure Architecture: Self-Hosted Gitea via Systemd"
problem_statement: |
  Edge, disconnected, and air-gapped operating environments cannot rely on continuous access to centralized, cloud-hosted Git providers (e.g., GitHub, GitLab) for code deployment, runtime configuration, or local debugging.
  
  Standard cloud-dependent pipelines break down due to:
  - Intermittent or Zero WAN Connectivity: Deployments block indefinitely.
  - Latency & Bandwidth Constraints: Repeatedly pulling multi-megabyte repositories wastes edge bandwidth.
  - Ad-hoc Sneakernet Failure Modes: Unmanaged USB file transfers or manual file copies introduce drift, bypass audit trails, and destroy version histories.
business_justification: |
  Operating a native, enterprise-grade Git forge directly on edge compute nodes provides a reliable single source of truth regardless of upstream network status.
  
  Benefits:
  - Deterministic Local Workflows: Standard Git tooling works locally over low-latency LAN/loopback interfaces.
  - Controlled Upstream Synchronization: Selective pull/push updates without risking repository corruption when WAN is available.
  - Integrity & Auditing in Air-Gapped Scenarios: Physical updates (USB) follow standard Git ingestion pathways (cryptographically verifiable).
  - Minimal Resource Footprint: Bare-metal Go binary managed via systemd avoids heavy container orchestration overhead (<200MB idle memory).
implementation_strategy:
  overview: "Deploy Gitea as a standalone binary managed via a hardened systemd service with SQLite/PostgreSQL, using host-level reverse proxying and firewall rules."
  workflows:
    air_gapped_ingest:
      description: "The raw filesystem behind Gitea must never be manually altered. All external repositories are staged and pushed via the standard Git protocol."
      example_commands: |
        git clone --bare /mnt/usb/project.git /tmp/project.git
        cd /tmp/project.git
        git remote add gitea http://127.0.0.1:3000/org/project.git
        git push --mirror gitea
    upstream_synchronization:
      warning: "True bidirectional synchronization on a shared branch is an anti-pattern. Concurrent writes cause non-fast-forward merge conflicts."
      patterns:
        - name: "Pull Mirror"
          mechanism: "Cron-based fetching; local writes rejected."
          conflict_risk: "None"
          best_used_for: "Read-only code distribution."
        - name: "Push Mirror"
          mechanism: "Edge commits synced upstream when WAN live."
          conflict_risk: "Low"
          best_used_for: "Diagnostics and telemetry."
        - name: "Edge Forking"
          mechanism: "Local forks of mirrors for field work."
          conflict_risk: "Minimal"
          best_used_for: "Local field development."
  production_deployment:
    setup_commands: |
      # Create service user and group
      sudo adduser \
        --system --group --disabled-password \
        --shell /bin/bash \
        --home /var/lib/gitea --gecos 'Gitea Git Service' git

      # Create directory tree
      sudo mkdir -p /var/lib/gitea/{custom,data,log}
      sudo mkdir -p /etc/gitea
      sudo chown -R git:git /var/lib/gitea
      sudo chown -R root:git /etc/gitea
      sudo chmod 770 /etc/gitea
      
      # Install Binary
      sudo wget -O /usr/local/bin/gitea https://dl.gitea.com/gitea/1.22.0/gitea-1.22.0-linux-amd64
      sudo chmod +x /usr/local/bin/gitea
    systemd_unit: |
      [Unit]
      Description=Gitea (Git with a cup of tea)
      After=network.target syslog.target
      Wants=network-online.target

      [Service]
      Type=simple
      User=git
      Group=git
      WorkingDirectory=/var/lib/gitea/
      ExecStart=/usr/local/bin/gitea web --config /etc/gitea/app.ini
      Restart=always
      RestartSec=5s
      Environment=USER=git HOME=/var/lib/gitea GITEA_WORK_DIR=/var/lib/gitea

      # Security and Sandboxing
      CapabilityBoundingSet=CAP_NET_BIND_SERVICE
      AmbientCapabilities=CAP_NET_BIND_SERVICE
      NoNewPrivileges=true
      PrivateTmp=true
      ProtectSystem=full
      ProtectHome=read-only
      ReadWritePaths=/var/lib/gitea /etc/gitea
      PrivateDevices=true
      ProtectKernelTunables=true
      ProtectKernelModules=true
      ProtectControlGroups=true
      MemoryDenyWriteExecute=true

      [Install]
      WantedBy=multi-user.target
    app_ini_configuration: |
      APP_NAME = Edge Git Infrastructure
      RUN_USER = git
      WORK_PATH = /var/lib/gitea
      RUN_MODE = prod

      [server]
      PROTOCOL = http
      HTTP_ADDR = 127.0.0.1
      HTTP_PORT = 3000
      DOMAIN = localhost
      ROOT_URL = http://127.0.0.1:3000/
      DISABLE_SSH = false
      SSH_PORT = 2222
      SSH_LISTEN_PORT = 2222

      [database]
      DB_TYPE = sqlite3
      PATH = /var/lib/gitea/data/gitea.db

      [service]
      DISABLE_REGISTRATION = true
      REQUIRE_SIGNIN_VIEW = true
      ENABLE_NOTIFY_MAIL = false

      [security]
      INSTALL_LOCK = true
      SECRET_KEY = <generated_random_secret>
      INTERNAL_TOKEN = <generated_random_token>
    post_configuration_commands: |
      # Lock down configuration permissions
      sudo chmod 750 /etc/gitea
      sudo chmod 640 /etc/gitea/app.ini

      # Reload and start service
      sudo systemctl daemon-reload
      sudo systemctl enable --now gitea 
```