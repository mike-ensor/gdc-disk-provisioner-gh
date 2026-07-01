# Project Plan: Unified Nexus-First Ready-Linux & Enhanced Diagnostics

## 1. Executive Summary & Objectives
This project plan establishes the **Unified Nexus-First Ready-Linux** post-install and hardening pipeline for Google Distributed Cloud (GDC) offline installations. 

Prior to this implementation (under `v0.0.x` and `v0.1.1` candidates), Sonatype Nexus booted up completely empty with standard default templates. This caused a critical architectural gap where target hosts attempted to query non-existent local mirrors during their first boot, resulting in **`404 Repository not found`** failures and blocking offline package installations.

With the new **`v0.1.2`** architecture, we automate the complete programmatic bootstrapping, parameter pass-throughs, custom user configurations, OS slimming, and dual-format diagnostics collection directly at early boot, establishing a 100% self-contained offline system.

---

## 2. Dynamic Architecture & Repositories Mapped

Under `v0.1.2`, the local Sonatype Nexus instance is programmatically configured on first boot with the following logical repositories:

| Repository Name | Format | Type | Port | Upstream Source / Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `gdc-apt-hosted` | APT | Hosted | `8081` | Direct upload target for offline custom system/security `.deb` packages. |
| `gdc-apt-proxy` | APT | Proxy | `8081` | Proxy mirror caching upstream `http://archive.ubuntu.com/ubuntu/` (VLAN 109 / Flat network). |
| `gdc-docker-hosted` | Docker | Hosted | `5002` | Local private registry hosting pre-seeded/sideloaded system control plane OCI container images. |
| `gdc-docker-proxy` | Docker | Proxy | `5001` | Proxy mirror caching public container registries (`gcr.io`, `registry.k8s.io`, etc.). |
| `gdc-docker-group` | Docker | Group | **5001** | Unified pull endpoint merging Hosted and Proxy lines (prioritizes local Hosted). |
| `gdc-raw-hosted` | Raw | Hosted | `8081` | Offline storage for local Hugging-Face GGUF weights, configs, and large binaries. |
| `gdc-raw-proxy` | Raw | Proxy | `8081` | Proxy mirror caching raw datasets/models (`https://huggingface.co`). |

---

## 3. Scope of Activities Completed

The implementation span of this project consists of four completed phases:

### Phase 1: Installation-Time Parameter Ingestion
*   **Action**: Updated Subiquity autoinstall late-commands (`src/build/templates/user-data.j2`) to securely dump deployment parameters.
*   **Result**: Renders `/target/etc/gdc/provision.yml` containing `nexus_admin_password` (derived from `{{ TEMPORARY_INSTALLER_PASSWORD }}`) and `ssh_pub_key` (derived from `{{ ADMIN_SSH_PUB_KEYS }}`).

### Phase 2: Sonatype Nexus Automated Initialization (Stage 1b)
*   **Action**: Integrated Stage 1b into `src/ansible/local.yml`.
*   **Result**: 
    *   Detects if Nexus binary resides on disk (gracefully bypasses on GCE sandbox mock environments).
    *   Reads initial admin credentials from `/var/lib/nexus/sonatype-work/nexus3/admin.password` if present.
    *   Resets `admin` account password via REST PUT endpoints.
    *   Idempotently registers and provisions all 7 GDC repositories (Docker, APT, Raw) with specific HTTP connectors and priorities.

### Phase 3: Administrative Configuration & OS Slimming (Stage 8)
*   **Action**: Added Stage 8 user setup and OS slimming into `src/ansible/local.yml`.
*   **Result**:
    *   Creates system-level `gdc-admin` user and group.
    *   Drops secure passwordless visudo permissions under `/etc/sudoers.d/gdc-admin`.
    *   Injects administrative public keys to `.ssh/authorized_keys`.
    *   Saves disk space and reduces attack surface by purging heavy redundant server modules (`snapd`, `lxd`, `x11-common`).

### Phase 4: Dual-Format Diagnostics Engine
*   **Action**: Rewrote `src/build/collect-diagnostics.sh`.
*   **Result**:
    *   Incorporated active checking of systemd unit run-states (Gitea, Nexus, ssh).
    *   Added probe checks on listening socket ports (`3000`, `8081`, `5001`, `5002`).
    *   Added HTTP loopback curls to verify service responsiveness.
    *   Constructed an inline Python-driven JSON compiler to output both highly descriptive ASCII `report.txt` (Human) and nested structured `report.json` (Machine).

---

## 4. Operational Release Handoff & Troubleshooting

In the event that the `404 Repository not found` or general `apt-get update` errors persist on node turnup, follow this standard operational checklist:

```text
                  [ NODETurnup: RUN apt-get update ]
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
         [ HTTP 200 SUCCESS ]            [ HTTP 404 FAILURE ]
                  │                               │
                  ▼                               ▼
       All mirrors functional.         1. Run `ss -ltun` (Confirm 8081).
       Dynamic proxy caching active.   2. Query Nexus API to list repos:
                                          `curl -u admin:<pass> http://127.0.0.1:8081/service/rest/v1/repositories`
                                       3. Inspect `/etc/apt/sources.list.d/gdc-nexus.sources`.
                                       4. View `/var/lib/nexus/sonatype-work/nexus3/log/nexus.log` for DB lockups.
```

---

## 5. Suggested Skills Reference
For subsequent debugging, optimization, or extension loops, the following specialist profiles are recommended:
1.  **`gdc-iso-build-deploy`**: Active release controller.
2.  **`systematic-debugging` / `diagnose`**: Direct triage of any REST API authentication or APT handshake failures.
3.  **`clean-code`**: Maintaining robust shell structures.
