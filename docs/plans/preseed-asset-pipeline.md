# Project Plan: GDC Offline Pre-seeding Asset Pipeline & GCS Caching (Unified Bucket Model)

## 1. Executive Summary & Objectives
This project plan details the design and implementation of the **GDC Offline Pre-seeding Asset Pipeline & GCS Caching** strategy under a **Unified Bucket Model**.

In high-security, air-gapped, or low-internet environments, GDC Bare Metal nodes cannot retrieve packages or container images from public public mirrors. To guarantee a 100% self-contained offline bootstrap, all core OS packages, dependencies, container layers, and administrative utilities must be pre-packaged directly onto the outer filesystem of the custom GDC bootloader ISO.

Additionally, to prevent excessive rebuild latency and bandwidth throttling in Cloud Build or local CI/CD runners, this plan leverages our existing Google Cloud Storage (GCS) release bucket (`gs://gdc-disk-provisioner-isos`) as a unified cache and distribution endpoint. By organizing the bucket into distinct prefixes, we centralize base OS media, binary dependencies, pre-resolved packages, and output release images under a single set of IAM security credentials.

---

## 2. Target OS Analysis (`192.168.9.243`)

A forensic analysis of the physical/virtual target environment on `192.168.9.243` confirms:
*   **Operating System:** Ubuntu 24.04.4 LTS (Noble Numbat).
*   **Hardware Security:** TPM 2.0 cryptochip active and accessible under `/sys/class/tpm/tpm0/`, validating compatibility with hardware-bound LUKS `systemd-cryptenroll` bindings.
*   **Active Package Audit:**
    *   *Installed (Satisfied):* `python3` (3.12.3-0ubuntu2.1), `ca-certificates` (20240203), `cryptsetup-initramfs` (2:2.7.0-1ubuntu4.2), `curl` (8.5.0-2ubuntu10.6), `ethtool` (1:6.7-1build1), `iproute2` (6.1.0-1ubuntu6.2), `libtss2-tcti-device0t64` (4.0.1-7.1ubuntu5.1), `logrotate` (3.21.0-2build1), `software-properties-common` (0.99.49.3), and `unattended-upgrades` (2.9.1+nmu4ubuntu1).
    *   *Missing (Needs Pre-seeding):* `conntrack`, `socat`, `libseccomp-dev`, `docker-ce`, `docker-ce-cli`, `containerd.io`, `tpm2-tools`, `step-cli`, `auditd`, `audispd-plugins`, `net-tools`, `arp-scan`, `apt-transport-https`, `chrony`, `ebtables`, and `gnupg2`.
*   **Apt Mirror Architecture:** Target node is configured to route package fetches via local loopback Nexus portals (`http://127.0.0.1:8081/repository/gdc-apt-hosted/` and `gdc-apt-proxy/`), matching `GDC-SPEC-003` specifications.

---

## 3. Dependency Release & Version Matrix

To achieve absolute determinism and eliminate environmental version drift, the pipeline will pre-seed the following exact version boundaries:

### 3.1. Local Service Hub Binaries
*   **Gitea Core Engine:** `v1.22.1` (checksummed Go binary)
*   **Java JRE Headless:** OpenJDK JRE `17.0.11+9` (adoptium JRE for Sonatype Nexus)
*   **Sonatype Nexus Repository Manager:** `v3.96.4-01` (H2 DB backend configuration for Java 21 compatibility)

### 3.2. Administrative Tools
*   **Google Cloud SDK (gcloud CLI):** `v481.0.0` (google-cloud-cli-linux-x86_64.tar.gz standalone archive)
*   **Smallstep CLI (`step-cli`):** `v0.26.1` (standalone deb/binary for TPM-backed CSR certificate generation)

### 3.3. System Container Engine & Core Packages
*   **Docker CE Engine:** `5:26.1.4-1~ubuntu.24.04~noble`
*   **Docker CE CLI:** `5:26.1.4-1~ubuntu.24.04~noble`
*   **containerd.io:** `1.7.13-1`
*   **Chrony NTP Server:** `4.5-1ubuntu4.2`
*   **Conntrack Utility:** `1:1.4.8-1ubuntu1`
*   **Socat Relay:** `1.8.0.0-4ubuntu0.1`
*   **TPM2 tools Suite:** `5.6-1build4`
*   **Auditd Daemon:** `1:3.1.2-2.1build1.1`
*   **Audispd Plugins:** `1:3.1.2-2.1build1.1`
*   **Net-tools Utility:** `2.10-0.1ubuntu4.4`
*   **Arp-scan Utility:** `1.10.0-2build2`

---

## 4. Unified GCS Caching & Folder Layout

Instead of provisioning a separate GCS bucket, we leverage the central GCS bucket `gs://gdc-disk-provisioner-isos` (customizable via `_GCS_BUCKET_NAME` substitution). 

### 4.1. Directory Structure

```text
gs://gdc-disk-provisioner-isos/              <-- Existing central bucket (e.g., _GCS_BUCKET_NAME)
├── source/
│   └── ubuntu-24.04-live-server-amd64.iso   <-- [EXISTING] Official Ubuntu Noble base OS (3.7 GB)
├── binaries/                                <-- [NEW] High-performance build caching folder
│   ├── gitea-1.22.1-linux-amd64             <-- Gitea engine (Go binary)
│   ├── OpenJDK17U-jre_x64_linux_hotspot...  <-- JVM headless runtime for Nexus
│   ├── nexus-3.96.4-01-linux-x86_64.tar.gz  <-- Sonatype Nexus binary
│   └── google-cloud-cli-481.0.0-linux-...   <-- Standalone gcloud CLI tool
├── packages/                                <-- [NEW] Pre-resolved/cached GDC APT packages
│   └── *.deb                                <-- Offline Chrony, Docker, TPM, Step-cli suite
├── images/                                  <-- [NEW] Pre-seeded platform container layers
│   └── *.tar                                <-- Control plane, CNI, MetalLB, and NodeAgent
├── sync/
│   └── gdc-bootstrap-u24-v1.0.0-debug.iso   <-- [EXISTING] Last 5 compiled output ISO releases
└── archived/
    └── gdc-bootstrap-u24-v0.0.85-debug.iso  <-- [EXISTING] Rotated older output ISO releases
```

---

## 5. Implementation Roadmap (Tasks Ahead)

Once this plan is reviewed and approved, the following tasks will be executed sequentially:

### Task 5.1: Upload Base ISO and Binaries to GCS
*   Ensure `ubuntu-24.04-live-server-amd64.iso` is loaded into `/source/`.
*   Upload Gitea, JRE, and Nexus Unix tarballs into `/binaries/` with corresponding SHA-256 metadata tags.

### Task 5.2: Integrate Caching Logic in `src/build/Makefile`
*   Refactor the `deps` stage in `Makefile` to pull directly from `gs://$(GCS_BUCKET)/binaries/` via `gcloud storage cp` if `ENABLE_GCS=true`.
*   Establish auto-fallback to public HTTPS mirror endpoints on cache miss, with automatic GCS upload following successful validation.

### Task 5.3: Automated Package Fetcher & Pre-seeding Script
*   Develop `src/build/preseed_packages.sh` to download the specific GDC deb dependencies listed in Group 3 using an isolated chroot/apt-download layout.
*   Enforce the 40GB space limit check on `/custom-data/nexus/` inside `remaster.sh`.

### Task 5.4: Integrate Standalone Google Cloud SDK Extraction
*   Modify `src/build/remaster.sh` to download `google-cloud-cli-481.0.0-linux-x86_64.tar.gz`, verify its checksum, and copy it to `build-workspace/custom-iso/custom-data/tools/`.
