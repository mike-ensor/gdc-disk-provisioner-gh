# Data Flow and Caching Analysis Report: GDC Debian & Container Packages

This document defines the architecture, data flow, and standard operating procedures for managing offline dependencies (Debian `.deb` packages, OCI container images, and standalone service binaries) used across Google Distributed Cloud (GDC) bare-metal installations and ISO remastering.

All dependency additions, upstream audits, and cache refreshes are managed canonically using the unified script:
```bash
bin/local/update-dependencies.sh
```

---

## 1. Debian Packages (`.deb`)

### 1.1. How Debian Packages are Cached in the GCS Bucket
The central Google Cloud Storage (GCS) bucket (e.g., `gs://${DEPENDENCY_CACHE_GCS_BUCKET}/packages/`) serves as the unified remote cache for offline Debian packages.
*   **Trigger / Frequency:** Updated out-of-band whenever packages are added or upstream dependencies need to be refreshed.
*   **Engine & Tooling:** Managed via `bin/local/update-dependencies.sh update-packages` (which invokes `src/build/preseed_packages.py` either natively on Ubuntu 24.04 or inside an isolated `ubuntu:24.04` Docker container).
*   **Resolution:** Uses `apt-cache depends --recurse --no-recommends` against `src/build/packages_config.yaml` (including core platform requirements and Longhorn v2 / SPDK dependencies like `open-iscsi`, `nfs-common`, `cryptsetup`, `dmsetup`, `util-linux`, `libnvme1`, `nvme-cli`, while excluding base-OS libraries like `^libc6$`).
*   **Storage & Sync:** Packages are downloaded into `.cache/packages/*.deb` and synchronized to `gs://${DEPENDENCY_CACHE_GCS_BUCKET}/packages/`.

### 1.2. Usage During the ISO Build Process
1.  **Fetch:** During Step 1 of `cloudbuild.yaml` (or local ISO build), the pipeline pulls pre-cached `.deb` packages from `gs://${DEPENDENCY_CACHE_GCS_BUCKET}/packages/` down to `.cache/packages/`.
2.  **Injection:** `src/build/remaster.sh` copies these `.deb` files into the extracted read-only ISO filesystem under `/custom-data/packages/`.
3.  **Post-Install Propagation:** During first boot, Ansible (`stage_first_boot.yml` / `user-data.j2`) `rsync`s the `/cdrom/custom-data/` directory to persistent LVM storage at `/var/gdc-install/iso-cache/`.
4.  **Local Nexus Seeding:** An Ansible task (`roles/service_hubs/tasks/main.yml`) uploads the `.deb` files directly into the node's offline Sonatype Nexus Hosted repository (`gdc-apt-hosted` on port `8081`).

### 1.3. Runtime Package Updates on Nodes
*   **Connected Mode:** Local `apt-get upgrade` hits the Nexus Proxy (`gdc-apt-proxy`). Nexus fetches newer packages from Ubuntu mirrors, writes them to persistent storage (`/var/lib/nexus`), and streams them to the node.
*   **Air-Gapped / Offline Mode:** Operators insert an update USB labeled `GDC-UPDATE-USB` or download an update bundle. The `udev`-triggered `gdc-headless-update.sh` script ingests new `.deb` files via the Nexus REST API into the `gdc-apt-hosted` repository.

### 1.4. Vulnerability Auditing (OSV API) & Package Cache Metadata
During package pre-seeding and cache generation:
*   **Vulnerability Auditing:** The pre-seeding engine queries **Google's OSV API** batch endpoint (`POST https://api.osv.dev/v1/querybatch`) for each resolved package under ecosystem `Ubuntu:24.04`. Batching prevents HTTP 429 rate-limiting by consolidating up to 500 packages per request.
*   **CVSS Scoring:** Extracted CVSS v3 vectors are evaluated to determine the base vulnerability score for each package (defaulting to `0.0 / Clear` when no CVEs exist).
*   **Release Dates & Cache Timestamp:** Each `.deb` package's release date is derived from its control metadata (`dpkg-deb -f <deb> Date` or archive timestamp), and the overall run records `cache_last_updated` in `.cache/packages_metadata.json`.
*   **Reporting:** Build reports (`build-report-*.json`) and After Action Reports (AARs) include `cache_last_updated`, `last_updated`, and `cvss_score` per package, rendered directly on the `gdc-companion` dashboard.

---

## 2. Container Packages (OCI Images)

### 2.1. How Container Images are Cached (GCS & ISO Footprint)
OCI container image layers (Kubernetes system images, MetalLB, CSI provisioners, LLMs) are **not** bundled directly into the base ISO to prevent ISO bloat.
*   **Remote Storage:** OCI images are stored in GCS sideload buckets or customer asset bundles (e.g., `baremetal/bmpackages_$VERSION`).
*   **Local Node Architecture:** Managed entirely by the **Sonatype Nexus Docker Group Repository** (`gdc-docker-group` on port `5001`), aggregating a read-write Hosted repository (`gdc-docker-hosted`) and a caching Proxy repository (`gdc-docker-proxy`).

### 2.2. Usage During Cluster Setup
1.  Container runtimes (Kubelet, containerd in `/etc/containerd/config.toml`, Docker in `/etc/docker/daemon.json`) route all image pulls through `http://nexus.gdc.local:5001`.
2.  Before `bmctl create cluster` runs, images are seeded into the local Nexus repository to ensure an offline cluster turnup.

---

## 3. Standalone Offline Service Binaries & CLI Tools

### 3.1. How Binaries are Cached in GCS
Offline binaries (`gitea`, `nexus`, `jre`, `google-cloud-sdk`, `step-cli`, `helm`, `kubestr`, `oras`, and `gdc-collector`) are declared in `src/dependencies.env` with pinned cryptographic SHA-256 signatures.
*   **GCS Prefix:** `gs://${DEPENDENCY_CACHE_GCS_BUCKET}/binaries/`
*   **Integrity Verification:** Every downloaded binary is verified against its pinned SHA-256 digest before being injected into the ISO or uploaded to GCS.

### 3.2. Usage During the ISO Build Process
1.  **Extraction & Staging:** During `src/build/remaster.sh`, standalone binaries are unpacked or copied into target paths on the ISO (e.g. `/custom-data/tools/helm/helm`, `/custom-data/tools/kubestr/kubestr`, `/custom-data/tools/oras/oras`, `/custom-data/gitea/gitea`).
2.  **Subiquity / Cloud-Init Propagation:** `user-data.j2` copies all tools from `/cdrom/custom-data/tools/` directly into `/target/var/gdc-install/tools/` and `/target/var/gdc-install/iso-cache/tools/`.
3.  **Ansible Symlink:** In `roles/system_tuning`, the Ansible playbook verifies permissions and symlinks executables into `/usr/local/bin/` (`helm`, `kubestr`, `oras`, `bmctl`, `gcloud`).

---

## 4. Standard Operating Procedures: Adding & Updating Dependencies

All modifications to dependencies and packages must be performed using `bin/local/update-dependencies.sh`. Do not edit configuration files or recalculate checksums manually.

```text
                               ┌────────────────────────────────────────────────────────┐
                               │           bin/local/update-dependencies.sh             │
                               └──────────────────────────┬─────────────────────────────┘
                                                          │
                                         ┌────────────────┴────────────────┐
                                         ▼                                 ▼
                                    [ Packages ]                      [ Binaries ]
                                         │                                 │
                         1. Validates in Ubuntu archive          1. Downloads upstream archive
                         2. Updates packages_config.yaml         2. Computes SHA-256 on the fly
                         3. Resolves recursive .deb tree         3. Updates src/dependencies.env
                         4. Optionally wires boot install        4. Adds to CACHED_BINARY_FILES
```

### 4.1. Auditing Upstream Releases
Check if newer versions or security patches exist for the pinned binaries:
```bash
# Display human-readable audit table:
bin/local/update-dependencies.sh check

# Display Markdown-formatted table (ideal for GitLab MRs or CI logs):
bin/local/update-dependencies.sh check --markdown

# Output structured JSON:
bin/local/update-dependencies.sh check --json

# CI Gate mode (exits 0 if all up to date, exits 2 if updates available):
bin/local/update-dependencies.sh check --ci
```

### 4.2. Updating Existing Binaries
When an update is identified by `check`, update the pinned entry in `src/dependencies.env` with the new version, URL, and freshly calculated SHA-256 checksum:
```bash
# Update a single binary (e.g. kubestr):
bin/local/update-dependencies.sh update-binary kubestr

# Update all outdated binaries in one pass:
bin/local/update-dependencies.sh update-binaries
```

### 4.3. Updating & Pre-Seeding Debian Packages
Re-resolve all package dependencies defined in `src/build/packages_config.yaml` and download fresh `.deb` files into `.cache/packages/`:
```bash
# Run locally (when executing on an Ubuntu 24.04 host):
bin/local/update-dependencies.sh update-packages

# Run inside an isolated Docker container (recommended on macOS or non-Ubuntu hosts):
bin/local/update-dependencies.sh update-packages --docker
```

### 4.4. Adding a New Debian Package (`pkg`)
Debian packages do not require manual download URLs or SHA-256 hashes; Ubuntu repository metadata (`InRelease`) cryptographically verifies packages. The script handles dependency registration and optional boot-time installation.

```bash
# 1. Bake package into the offline ISO cache (available in offline Nexus, but not auto-installed):
bin/local/update-dependencies.sh add-pkg dnsmasq

# 2. Bake package into ISO cache AND configure Ansible to auto-install it on First Boot:
bin/local/update-dependencies.sh add-pkg dnsmasq --install

# 3. Add package and immediately trigger recursive .deb resolution:
bin/local/update-dependencies.sh add-pkg dnsmasq --install --preseed
```

*What the script does:*
1. Validates the package name syntax.
2. Idempotently registers the package in `src/build/packages_config.yaml` under `packages_to_include.customer_added`.
3. If `--install` is passed, appends the package to `customer_install_packages` in `src/ansible/vars/all.yml` and `all.yml.j2`, where task `GDC-TASK-10E` in `roles/system_tuning` installs it via `apt` at boot.
4. If `--preseed` is passed, immediately downloads the `.deb` files and recursive dependencies into `.cache/packages/`.

### 4.5. Adding a New Standalone Binary (`binary`)
When adding a standalone executable, the script downloads the asset into a temporary stream, computes its cryptographic SHA-256 hash on the fly, and registers it in `src/dependencies.env`.

```bash
# Add a binary dependency (SHA-256 automatically computed from URL):
bin/local/update-dependencies.sh add-binary \
  --name mytool \
  --version 1.2.0 \
  --url https://github.com/example-org/mytool/releases/download/v1.2.0/mytool-linux-amd64.tar.gz

# Add a binary with pre-computed SHA-256:
bin/local/update-dependencies.sh add-binary \
  --name mytool \
  --version 1.2.0 \
  --url https://github.com/example-org/mytool/releases/download/v1.2.0/mytool-linux-amd64.tar.gz \
  --sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

*What the script does:*
1. Downloads the remote asset to calculate `hashlib.sha256()` (if `--sha256` not provided).
2. Appends `<NAME>_VERSION`, `<NAME>_PACKAGE_URL`, `<NAME>_PACKAGE_FILENAME`, `<NAME>_PACKAGE_SHA256`, and `<NAME>_ISO_DEST_DIR` to `src/dependencies.env`.
3. Appends `${<NAME>_PACKAGE_FILENAME}` to `CACHED_BINARY_FILES`.

### 4.6. Synchronizing Local Cache to GCS
Upload local `.cache/binaries/*` and `.cache/packages/*.deb` to the remote GCS dependency bucket:
```bash
bin/local/update-dependencies.sh sync-gcs

# Override destination GCS bucket:
bin/local/update-dependencies.sh sync-gcs --gcs-bucket my-custom-cache-bucket
```

### 4.7. Complete Full-Cycle Maintenance Workflow
To run a complete maintenance pass (audit binaries, update outdated binaries, re-resolve Debian packages, and upload everything to GCS):
```bash
bin/local/update-dependencies.sh all --docker
```
