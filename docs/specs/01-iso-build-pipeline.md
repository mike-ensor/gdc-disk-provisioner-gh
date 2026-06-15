# Specification: GDC Offline ISO Build & Remastering Pipeline

**Spec Identifier:** `GDC-SPEC-001`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Executive Summary & Purpose
The Google Distributed Cloud (GDC) Offline ISO Build and Remastering Pipeline is an automated, Infrastructure-as-Code (IaC) compilation engine. It transforms official "blessed" Ubuntu 24.04 LTS server installation media into custom, secure, fully self-contained, and bootable bootstrap ISOs. 

By embedding Gitea (for Git hosting) and Sonatype Nexus (for package and image registries), the resulting ISO operates as an offline "Local Service Hub." This allows bare metal enterprise nodes to bootstrap, partition, configure, and self-test without active internet gateways.

This specification outlines the build mechanics, performance strategies, security mitigations, cost analysis, and execution scripts for the pipeline.

---

## 2. Multi-Dimensional Scrutiny & Analysis

### 2.1. Security Analysis (Supply Chain & Runtime Protection)
* **Risk (Binary Integrity):** Pre-baking standalone binaries like Gitea, Java JVM, and Nexus presents software supply-chain vulnerabilities.
  * *Mitigation:* The build pipeline implements cryptographic checksumming. Every binary is verified against a hardcoded SHA-256 hash list during the workspace assembly stage.
* **Risk (Credential Leakage):** Hardcoding static secrets, administrative passwords, or SSH private keys inside playbooks on the ISO is highly insecure.
  * *Mitigation:* The build uses TPM-based cryptographic enrollment during boot instead of static keys. Admin passwords are encrypted with SHA-512 rounds salted hashes inside the cloud-init template.
* **Risk (Network Exposure):** Running Gitea and Nexus during the live-boot installation could expose port 3000 and 8081 to the wider provisioning LAN, risking unauthorized package injection.
  * *Mitigation:* During the Live ISO bootstrap phase, Gitea and Nexus are configured to bind strictly to the local loopback interface (`127.0.0.1`). They are only bound to public node network interfaces post-hardening in the target OS.

### 2.2. Operational Ability (Agility & Velocity)
* **Risk (Rebuild Latency):** Compiling a custom ISO traditionally requires extracting and compressing the read-only SquashFS (`filesystem.squashfs`), which takes 10 to 20 minutes and requires massive CPU overhead.
  * *Mitigation:* **SquashFS Separation Strategy.** We do not touch or compress the internal SquashFS. Gitea, Nexus, configurations, and Ansible playbooks reside in a custom, uncompressed directory (`/custom-data/`) on the *outer* ISO filesystem. Remastering only copies configuration texts and wraps them with `xorriso` which takes **less than 10 seconds** on standard compilation servers.
* **Risk (Root Permission Obstacles):** Standard ISO extraction and loopback mounting require administrative `sudo` permissions, which are blocked on secure CI/CD build runners.
  * *Mitigation:* We use `xorriso`'s non-root extraction layer (`-osirrox on -indev ... -extract / ...`) which allows full workspace isolation without root privileges.

### 2.3. Scale Analysis (Storage & Data Volume)
* **Risk (ISO Bloat):** Pre-seeding Nexus with full APT caches, private Docker images, and Hugging Face/LLM weight assets will lead to a 50GB–100GB+ ISO file size, leading to network and memory performance failures.
  * *Mitigation:* **Layered Asset Partitioning.** 
    * The *Core ISO* remains small (~3–5 GB), containing only base OS packages, Gitea, Nexus systems, and GDC-specific installer playbooks.
    * Large caches (like LLM weight models) are stored in a dedicated directory on the installation USB drive labeled `GDC-SEED-CACHE`.
    * During boot, Gitea/Nexus run a discovery task that binds the `GDC-SEED-CACHE` mount to Nexus's local store. This avoids bloating the boot ISO while keeping caching fully functional offline.

### 2.4. Frequency of Change (Velocity vs Stability)
The pipeline isolates fast-changing components from static system files:
* **High Frequency (Daily):** Ansible playbooks and cloud-init autoinstall configurations. Fast-path build target (`make build-fast`) repacks the outer ISO filesystem in <5 seconds.
* **Medium Frequency (Weekly/Monthly):** Offline APT packages, Gitea/Nexus binary versions, and Docker container base layers. Slow-path build target (`make build-all`) triggers dependency updates and repacks in ~3 minutes.
* **Low Frequency (Quarterly/Yearly):** Base Ubuntu kernel or core installation packages. Managed via upstream vendor upgrades.

### 2.5. Ease of Upkeep
By avoiding manual interactive customization tools (like Cubic or manual chroots), the entire state is represented as declarative code:
* Upkeep only requires editing plain text files: `build.env` (version increments), `user-data` (Subiquity partitions), and `local.yml` (Ansible rules).
* Code changes are fully auditable through standard Git workflows.

### 2.6. Costs (Compute & Network Storage)
* **Storage Cost (GCS):** Standard Google Cloud Storage costs $0.02 per GB/month. Storing 10 versions of a 5GB core ISO costs less than $1.00/month.
* **Compute Cost (CI/CD):** By utilizing the 5-second SquashFS-separated build loop, CI/CD runtimes (e.g. GitHub Actions, Cloud Build) are minimal, reducing compute pipeline billing significantly.
* **Network Egress Fees:** To avoid cloud provider egress fees, builds should execute in the same cloud region as the GCS bucket, resulting in $0.00 network costs.

### 2.7. GCP Cloud Logging Feasibility & Architecture
The feasibility of installing the full Google Cloud SDK (`gcloud`) inside the booting Live ISO environment was analyzed, with the following outcomes:
* **Analysis of Direct `gcloud` Installation (Not Recommended):**
  * *Size Constraints:* Installing the `gcloud` CLI SDK requires Python and a large bundle of packages, consuming **300MB–500MB+** of extracted disk space. This severely bloats the Live ISO image and consumes limited live RAM overlay memory.
  * *Critical Security Vulnerability:* Direct log forwarding requires active GCP credentials. Baking a static Google Service Account Key (`key.json`) directly onto physical bootloader ISOs poses a major security hazard (`Rule 1.5 - Credential Leakage`). If the ISO media is ever misplaced or stolen, the entire GCP project is compromised.
* **The Approved High-Security Logging Pattern:**
  * **Phase 1 (Live Bootstrap Logs):** Subiquity natively supports sending autoinstall reporting logs via HTTP webhooks. Instead of talking directly to GCP, the installer is configured to stream logs to the local network's **Admin Workstation/Gateway**. The Admin Workstation (which is secured and pre-authenticated to Google Cloud) acts as the secure logging proxy, translating and forwarding the logs to GCP Cloud Logging. This completely avoids baking service account keys on the node ISO.
  * **Phase 2 (Post-Install Fluent-bit):** Once GDC is fully bootstrapped, the GDC Node Agent automatically installs and configures a secure, TPM-authenticated Fluent-bit daemon that handles log forwarding to Google Cloud Stackdriver natively.
  * **Build Variable Integrations:** The build configuration defines `PROJECT_ID` and `REGION` to allow custom script integration or dynamic API-endpoint target constructions.

---

## 3. Comprehensive Technical Architecture

```text
                                [ BUILD SYSTEM ]
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
       [ Fast-Path Compilation ]                     [ Slow-Path Pre-Seeding ]
       • Pulls playbook changes                      • Downloads Gitea & Nexus Bins
       • Updates user-data / GRUB                    • Populates offline APT/Docker caches
       • Instantly runs xorriso                      • Packs heavy binary components
                │                                             │
                └──────────────────────┬──────────────────────┘
                                       ▼
                             [ Remastered GDC ISO ]
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
       [ Local NFS Publish ]                         [ Google GCS Bucket ]
       • Copies to local network mounts              • Runs `gcloud storage cp`
```

### 3.1. Detailed ISO Layout Structure
```text
build-workspace/custom-iso/
├── nocloud/                        # Cloud-init NoCloud configuration files
│   ├── user-data                   # Automated Subiquity partition & install rules
│   └── meta-data                   # Local node identification
├── boot/grub/grub.cfg              # Modified bootloader menu specifying unattended install
└── custom-data/                    # Embedded local boundary endpoints (Hub)
    ├── gitea/                      # Standalone Gitea instance
    │   ├── gitea                   # Go binary (checksum validated)
    │   └── repos/                  # Bare repositories folder
    │       └── bootstrap-playbooks.git
    └── nexus/                      # Sonatype Nexus Repository Manager
        ├── nexus-bin/              # Standalone Nexus core & JVM
        └── blobs/                  # Pre-seeded local cache stores (APT, Docker, LLM)
```

### 3.2. Pre-Seeding Gitea & Nexus Group Repositories

#### A. Gitea Repository Pre-Seeding & Upstream Sync
During the build phase, our local configuration playbooks are pre-packaged as a **bare Git mirror repository** cloned dynamically from the configured `UPSTREAM_PLAYBOOKS_REPO` at the exact time of ISO creation.

```text
       [ Upstream Playbook Git Repo (Origin) ]
                        │
                        │ (cloned at ISO creation time)
                        ▼
       [ GGD Local Gitea Mirror (Read-Only) ]
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
   [ Direct push blocked ]   [ Local pull-only ok ]
      (pre-receive hook)       (ansible-pull fetches)
```

1. **Clone-on-Create Execution:** The remastering engine executes a bare clone during workspace assembly:
   ```bash
   git clone --bare "${UPSTREAM_PLAYBOOKS_REPO}" build-workspace/custom-iso/custom-data/gitea/repos/bootstrap-playbooks.git
   ```
2. **Read-Only Enforcement (Push Prohibitions):** To maintain local node configuration stability and prevent untracked drift, pushing directly to Gitea's local copy is strictly disabled. We enforce this at the filesystem level via a local Git `pre-receive` hook inside Gitea's repository folder:
   ```bash
   cat <<'EOF' > build-workspace/custom-iso/custom-data/gitea/repos/bootstrap-playbooks.git/hooks/pre-receive
   #!/usr/bin/env bash
   echo "[!] [GGD SECURITY ERROR] Direct pushing to Gitea's local bootstrap repository is strictly forbidden." >&2
   echo "[-] This repository is READ-ONLY. It can only pull updates from the upstream origin." >&2
   exit 1
   EOF
   chmod +x build-workspace/custom-iso/custom-data/gitea/repos/bootstrap-playbooks.git/hooks/pre-receive
   ```
3. **Future Goal (Automated Upstream Pulls):** To fetch updates once the node is deployed, a future development milestone is logged to establish background sync checks. This will run a local cron task or systemd timer executing a localized pull operation:
   ```bash
   # Concept under investigation for future target-OS sync triggers:
   git -C /var/lib/gitea/repos/bootstrap-playbooks.git fetch origin main:main
   ```

#### B. Nexus Group Repositories & OCI Registry Strategy
Sonatype Nexus is configured utilizing **Repository Groups** (formerly known as Virtual Repositories). This pattern merges multiple physical repositories (Hosted, Proxy, and Cache) into a single unified endpoint.

```text
                                 [ NEXUS GROUP ENDPOINT ]
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    ▼                                               ▼
       [ Local Hosted Repository ]                    [ Proxy/Cache Repository ]
       • Destination for OCI `docker push`            • Pulls-through from public upstream
       • Stores custom localized images               • Caches pulled images offline
```

* **The OCI/Docker Group Registry & Build-Time Pinning:**
  * We configure a Nexus Repository Group `gdc-docker-group` bound to local port `5001`.
  * **Hosted Member (`gdc-docker-hosted`):** Bound to port `5002`. Allows administrative tools, GDC utilities, and deployment scripts to execute direct, fully-tagged image pushes:
    ```bash
    docker tag my-image:1.0 localhost:5002/gdc/my-image:1.0
    docker push localhost:5002/gdc/my-image:1.0
    ```
  * **Build-Time Version Pinning & Pre-fetching:** The GDC Bare Metal release version is a critical variable specified in `build.env` (e.g., `GDC_BM_VERSION=1.32.400-gke.68`). During Phase 1 ISO compilation, the workstation downloads GDC's package bundle `bmpackages_$VERSION.tar.xz`, extracts the container images, pulls them, and bakes them directly into the ISO's local staging folder (`/custom-data/nexus/`).
  * **First-Boot Ingestion:** On target OS first boot (the `ready-linux` phase), the local Ansible playbook takes these pre-packed container layers from the ISO mount, authenticates, and pushes them directly into the local `gdc-docker-hosted` repository (on Port `5002`). This populates the offline cache for subsequent standalone cluster turnup.
  * **Proxy Member (`gdc-docker-proxy`):** Points to upstream public OCI registries (e.g. Docker Hub, Google Artifact Registry). When a node requests an image, Nexus fetches it from upstream, caches it in the local blob store, and serves it. Subsequent offline pulls fetch entirely from Nexus's cache.
* **The APT and LLM Groups:**
  * **APT Group (`gdc-apt-group`):** Group of `gdc-apt-hosted` (local updates) and `gdc-apt-proxy` (mirroring upstream Ubuntu security archives).
  * **LLM Group (`gdc-llm-group`):** Group of `gdc-llm-hosted` (local GGUF weights) and `gdc-llm-proxy` (caching Hugging Face model requests).
  * Inference engines pulling GGUF models directly query the local Nexus port, satisfying requests instantly from the proxy cache.

---

## 4. Execution & Implementation Plan

### 4.1. Core Pipeline Targets
The build pipeline is designed as a standard `Makefile` that handles the entire lifecycle:

```make
# Fast path compilation (Only updates playbooks & configs)
build-fast:
	@./remaster.sh --fast

# Full path compilation (Updates heavy packages & pre-seeds caches)
build-all:
	@./remaster.sh --full

# Publishes output to GCS and NFS based on build.env options
deploy:
	@make -f src/build/Makefile deploy
```

### 4.2. Workspace Setup and Cryptographic Verification
During a `build-all` operation, the `remaster.sh` script executes the following cryptographic verify:
```bash
# Example verification block in build scripts
GITEA_EXPECTED_SHA="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
GITEA_ACTUAL_SHA=$(sha256sum "${CACHE_DIR}/gitea" | cut -d' ' -f1)

if [[ "${GITEA_ACTUAL_SHA}" != "${GITEA_EXPECTED_SHA}" ]]; then
    echo "[!] Supply Chain Integrity Check Failed: Gitea binary hash mismatch!" >&2
    exit 1
fi
```

### 4.3. Expected Outcomes
* **Speed:** Core ISO configuration repacking finishes in `<10 seconds`.
* **Reproducibility:** Two builds executed on identical code generate an ISO with an identical cryptographic SHA-256 hash (supporting standard reproducible builds).
* **Zero Root Dependencies:** Build executes cleanly on unprivileged Kubernetes/Cloud Build nodes.
* **Storage Footprint:** Master ISO size remains below **5 GB**, with optional support for multi-gigabyte LLM caches appended on separate offline USB media.
