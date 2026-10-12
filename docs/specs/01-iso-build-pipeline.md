# Specification: GDC ISO Build & Lifecycle Stage-Gate Pipeline

**Spec Identifier:** `GDC-SPEC-001`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Release Engineering Team

---

## 1. Overview & Core Philosophy
The Google Distributed Cloud (GDC) Offline ISO Build and Remastering Pipeline is an automated, Infrastructure-as-Code (IaC) compilation engine. It transforms official "blessed" Ubuntu 24.04 LTS server installation media into custom, secure, fully self-contained, and bootable bootstrap ISOs.

Rather than utilizing a single monolithic compilation script, the build cycle is decomposed into distinct, idempotent, and non-interactive stages. This **Discrete Stage-Gate Software Supply Chain** architecture guarantees that all templates, environmental parameters, and local cached assets are verified for correctness before compilation begins, resulting in short feedback loops and absolute build reproducibility across local workstations and remote CI/CD systems.

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

## 3. The Stage-Gate Lifecycle Model

To enforce absolute reliability, the entire build-and-release pipeline is divided into distinct named stages and corresponding non-interactive `make` targets. Each target is idempotent, self-verifying, and guarantees a zero-interactive execution environment.

```text
                     [ PREPARATION & ACQUISITION ]
  [1. check-env] ──> [2a. core-deps] ──> [2b. pull-cust] ──> [2c. extract-cust] 
                                                                    │
  ┌─────────────────────────────────────────────────────────────────┘
  ▼
  [2d. apply-cust] ──> [3. extract-iso] ──> [4. hydrate] ──> [5. validate]
                                                                   │
  ┌────────────────────────────────────────────────────────────────┘
  ▼
  [6. assemble] ──> [7. test-static] ──> [8. test-dynamic]
                                               │
  ┌────────────────────────────────────────────┘
  ▼
  [9. deploy-gate] (FATAL) ──> [10. publish-manifest] ──> [11. compile-reports]
```

### Stage 1: Check Environment (`make check-env`)
*   **Action:** Verifies that all host tool dependencies are installed and accessible (`xorriso`, `curl`, `rsync`, `python3`, `jinja2`, `yaml`).
*   **Host Diagnostics:** Detects nested virtualization capabilities (`/dev/kvm`). If absent, writes a prominent non-blocking warning informing the host that Tier 2 QEMU tests will fallback to slow software emulation (TCG), preventing abrupt pipeline failure on restricted runners.
*   **Interactivity Check:** Asserts that all downstream commands run in a non-blocking manner (injecting `--auto-approve` / `-y` flags automatically if running without a TTY).

### Stage 2a: Acquire Core Dependencies (`make deps`)
*   **Action:** Checks `.cache/binaries/` for Gitea, Adoptium Java JRE 17, and Sonatype Nexus tarballs. If missing, downloads them and verifies their SHA-256 hashes against configured build variables.
*   **Idempotency:** Already downloaded and verified assets are retained, bypassing network fetches on subsequent runs.

### Stage 2b: Pull Customer Supplied Binaries (`make pull-customer-deps`)
*   **Action:** Checks if a customer-supplied assets tarball URI (`_CUSTOMER_ASSETS_URI`) is specified. If defined, pulls the raw asset tarball down from the GCS bucket or local network path to `.cache/customer/customer-assets.tar.gz`.

### Stage 2c: Extract Customer Supplied Binaries (`make extract-customer-deps`)
*   **Action:** Unpacks the retrieved customer tarball to the local workspace staging folder `build-workspace/customer-staging/` using non-root layers.

### Stage 2d: Apply Customer Supplied Binaries (`make apply-customer-deps`)
*   **Action:** Processes the staging area, placing custom `.deb` packages in the offline preseed directories, updating playbooks inside Gitea's staging repository, or applying customer certificates to system files.

### Stage 3: Extract Source Media (`make extract`)
*   **Action:** Performs non-root extraction of the official "blessed" Ubuntu 24.04 live-server ISO into the workspace (`build-workspace/custom-iso/`) using `xorriso`'s non-root extraction layer (`-osirrox on -indev ... -extract / ...`).
*   **Outcome:** A pristine, writable file layout of the original OS media without requiring administrative sudo mounts.

### Stage 4: Render Configurations (`make hydrate`)
*   **Action:** Invokes `src/build/render_templates.py` to compile our base templates (`user-data.j2`, `meta-data.j2`, `storage_config.j2`, `netplan.j2`, `gitea.service.j2`, `nexus.service.j2`, `gdc-provision.service.j2`) into the extracted media workspace. Generates `nocloud/user-data`, `nocloud/meta-data`, and a minimal `nocloud/vendor-data` (`#cloud-config\n`) to satisfy `cloud-init`'s default vendor probe and prevent 11-retry HTTP 404 delays.
*   **Rule:** Standard python libraries and Jinja2 are used exclusively. Pure-string regex or sed-based manipulations on live YAML files are strictly banned to prevent spacing corruption.

### Stage 5: Validation Gate (`make validate`)
*   **Action:** Performs static validation of the hydrated configurations *before* compilation begins.
*   **Checks:**
    1. Runs syntax verification against all hydrated shell scripts.
    2. Runs `cloud-init schema --config-file user-data` to guarantee Subiquity compatibility.
    3. If any check fails, the pipeline aborts immediately, preventing broken ISO compilations.

### Stage 6: Remaster Configuration (`make assemble`)
*   **Action:** Copies Gitea, JRE, and Nexus binaries, pre-seeds the Gitea git playbooks, packages Ansible offline collections, writes the dynamic Message of the Day (MOTD) login banner, updates GRUB boot configurations, and executes `xorriso` to output the remastered ISO under `build-workspace/output/`.

### Stage 7: Static Inspection (`make test-static`)
*   **Action:** Extracts and inspects the compiled ISO file table to confirm the correct positioning, permissions, and cryptographic signatures of all injected services and payload structures.

### Stage 8: Dynamic End-to-End Boot (`make test-dynamic`)
*   **Action:** Launches `test/run_qemu_e2e.sh` which provisions dual-disk sparse blocks, maps an isolated `swtpm` daemon, boots the ISO, and polls the serial logs for the completion token. Executes SSH-based assertion queries over localhost loopback forwardings.

### Stage 9: Release Deployment Gate (`make deploy`)
*   **Action:** Pushes the finalized ISO to regional GCS buckets or NFS storage.
*   **Upload Verification [FATAL]:** Retests the uploaded file directly on GCS using `gcloud storage objects describe` or MD5/CRC32C checksum audits to guarantee the uploaded file matches the compiled artifact exactly. If mismatch occurs, the gate is failed, aborting release.

### Stage 10: Publish Provenance (`make publish`)
*   **Action:** Generates a cryptographically signed **Provenance Manifest** (`provenance.json`) and promotes atomic verified symlinks on release targets.

### Stage 11: Compile Build Reports (`make reports`)
*   **Action:** Dynamically processes stage timing, unit test details, package seeding counts, and log artifacts to produce canonical JSON reports and derived human-readable Markdown reports. Publishes both files directly to GCS under `gs://${GCS_BUCKET}/reports/build-reports/`.

---

## 4. Comprehensive Technical Architecture

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

### 4.1. Detailed ISO Layout Structure
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

### 4.2. Pre-Seeding Gitea & Nexus Group Repositories

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

---

## 5. Provenance Manifest Specification (`gdc-bootstrap-v1.x.x-provenance.json`)

To establish 100% auditable traceability, every successful build publishes a signed JSON manifest alongside the ISO. This manifest registers all compile-time variables, versions, host environment specs, and dependency checksums extracted dynamically from the build environment.

```json
{
  "$schema": "https://gdc.google.com/schemas/provenance-v1.json",
  "build_identity": {
    "build_id": "gdc-iso-2026-06-25-t143022z",
    "build_version": "1.0.0",
    "git_commit": "08c29a5ec9cfb823f990a4be356881c62f267c7e",
    "git_branch": "main",
    "timestamp": "2026-06-25T14:30:22Z"
  },
  "host_build_environment": {
    "host_os": "Ubuntu 24.04 LTS (Noble Numbat)",
    "host_kernel": "6.8.0-100-generic",
    "host_arch": "x86_64",
    "kvm_available": true
  },
  "compilation_and_iso_tools": {
    "xorriso": "xorriso 1.5.6-1.1ubuntu3",
    "rsync": "rsync  version 3.2.7  protocol version 31",
    "python": "Python 3.12.3",
    "jinja2": "Jinja2 3.1.4"
  },
  "target_dependencies_and_binaries": {
    "gitea": {
      "version": "1.22.1",
      "filename": "gitea-1.22.1-linux-amd64",
      "source_url": "https://github.com/go-gitea/gitea/releases/download/v1.22.1/gitea-1.22.1-linux-amd64",
      "sha256": "b8043324545eec269fc8f18c22b49fc365ed367e0dd41e081b79832de2570f9c"
    },
    "nexus": {
      "version": "3.96.4-01",
      "filename": "nexus-3.96.4-01-linux-x86_64.tar.gz",
      "source_url": "https://download.sonatype.com/nexus/3/nexus-3.96.4-01-linux-x86_64.tar.gz",
      "sha256": "b4be574def830eeef97ca13fe206c458ba0a60631af441e8b128231ad7e002d0"
    },
    "java_jre": {
      "version": "17.0.11+9",
      "filename": "OpenJDK17U-jre_x64_linux_hotspot_17.0.11_9.tar.gz",
      "source_url": "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.11%2B9/OpenJDK17U-jre_x64_linux_hotspot_17.0.11_9.tar.gz",
      "sha256": "bcb1b7b8ad68c93093f09b591b7cb17161d39891f7d29d33a586f5a328603707"
    },
    "target_installed_packages": [
      "git=1:2.43.0-1ubuntu7",
      "python3-pip=24.0+dfsg-1ubuntu1",
      "wireguard=1.0.20210914-1ubuntu1"
    ]
  },
  "pipeline_configuration_parameters": {
    "upstream_playbooks_repo": "https://gitlab.com/gcp-solutions-public/retail-edge/gdc-disk-provisioner.git",
    "ansible_pull_schedule": "02:00:00",
    "enforce_signed_commits": false,
    "machine_vlan_id": 0,
    "k8s_vlan_id": 0,
    "install_companion_url": "http://gdc-companion.ensor-labs.com/v1/install-logs"
  },
  "verification_certification": {
    "static_validation": {
      "status": "PASSED",
      "cloud_init_schema_check": "VALID",
      "validator": "test/bin/validate-hydrated-files.sh"
    },
    "dynamic_integration_test": {
      "status": "PASSED",
      "qemu_headless_boot": "SUCCESS_TOKEN_DETECTED",
      "swtpm_v2_status": "SECURED_PCR_0_2_7",
      "post_install_assertions": "ALL_PASSED",
      "runtime_seconds": 962,
      "test_runner": "test/run_qemu_e2e.sh"
    }
  },
  "output_cryptographic_signatures": {
    "iso_filename": "gdc-bootstrap-ubuntu-24.04-v1.0.0.iso",
    "iso_sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
  }
}
```

## 6. Bootimus PXE Bootloader Integration Constraints

To guarantee the reliability of automated E2E and lab deployment testing, the build pipeline strictly governs the integration with the **Bootimus PXE Infrastructure**. 

At **NO TIME** should there be a built ISO deployed that does not fully complete inside Bootimus. Specifically, the pipeline enforces the following mandatory constraints:

1. **Extraction Completeness:** The ISO must finish background extraction on the PXE server. A status of `PENDING` or `EXTRACTING` is unacceptable; the final state must be explicitly `COMPLETE`.
2. **Distribution Classification:** Bootimus must correctly recognize the ISO as an `ubuntu` distribution family.
3. **Autoinstall Boot Parameters:** The kernel boot parameters must be explicitly locked and injected with the non-interactive unattended installation string (`ds=nocloud;s=/cdrom/nocloud/`).

These constraints are automatically enforced via the programmatic auditor script `test/bin/check-bootimus-settings.py`. Builds must not be declared successful until this script returns a clean `SUCCESS` exit code.
