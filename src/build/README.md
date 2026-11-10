# GDC ISO Remastering & Cloud Build Automation

This directory contains the orchestration files, scripts, and container assets required to build, version, and publish custom Google Distributed Cloud (GDC) offline bootstrap ISOs in a highly repeatable manner.

To support compliance, security, and velocity, the compilation pipeline can run completely in the cloud using **Google Cloud Build** and a custom, pre-packaged builder image.

---

## The Build Lifecycle: Setup, IAM, Compilation, & Cloud Build

Follow these steps to set up your custom builder registry, compile the builder container, configure build IAM permissions, and trigger automated GDC ISO remastering runs in the cloud.

### Step 1: Create your Artifact Registry (One-Time Setup)
Create a secure, private Docker registry in your Google Cloud Project to host the custom compilation builder container:

```bash
gcloud artifacts repositories create gdc-build-images \
    --repository-format=docker \
    --location="us-central1" \
    --description="GDC ISO compilation builder images" \
    --project="YOUR_PROJECT_ID"
```

### Step 2: Compile and Register the Builder Container
Build your custom `iso-builder` image using Cloud Build and push it to your newly created Artifact Registry. This container pre-installs `xorriso`, `rsync`, and other build tools, removing compilation delays and internet package dependencies on subsequent runs.

Using our pre-configured wrapper script (recommended):
```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export BUILD_VERSION="1.0.0"
export REGION="us-central1"

./src/build/build.sh
```

Or run the raw `gcloud` command directly:
```bash
gcloud builds submit src/build/ \
    --tag="${REGION}-docker.pkg.dev/${PROJECT_ID}/gdc-build-images/iso-builder:1.0.0" \
    --project="${PROJECT_ID}"
```

---

### Step 3: Configure the GCP ISO Builder Google Service Account (Least Privilege)

To adhere to the **Principle of Least Privilege (PoLP)** and enforce **Separation of Duties**, avoid executing Cloud Build runs under broad administrative or node service accounts. Instead, configure and delegate a dedicated **GCP ISO Builder Google Service Account** (e.g. `gdc-iso-builder-sa@${PROJECT_ID}.iam.gserviceaccount.com`).

#### Least Privilege Permissions Matrix

| GCP Service | Scope / Target Resource | Role Required | Why It Is Needed |
| :--- | :--- | :--- | :--- |
| **Cloud Storage** | Bucket: `gs://${GCS_BUCKET_NAME}` | `roles/storage.objectAdmin` | Uploads new ISOs, syncs package caches, and executes `gcloud storage mv` (copy + delete) for retention archiving. |
| **Cloud Storage** | Bucket: `gs://${ISO_BLESSED_GCS_BUCKET}` | `roles/storage.objectViewer` | Read-only download of the source Ubuntu 24.04 server ISO. |
| **Cloud Storage** | Bucket: `gs://${PROJECT_ID}_cloudbuild` | `roles/storage.objectViewer` | Cloud Build default staging bucket to unpack the source workspace tarball. |
| **Secret Manager** | Secret: `${FALLBACK_SUB_CA_SECRET_NAME:-gdc-fallback-sub-ca}` | `roles/secretmanager.secretAccessor` | Reads the fallback Sub-CA credentials baked into the ISO custom data (`remaster.sh`). |
| **Secret Manager** | Secret: `bootimus_creds` *(optional)* | `roles/secretmanager.secretAccessor` | Reads Bootimus credentials only if `BOOTIMUS_SECRET_METHOD=gcloud` is enabled. |
| **Artifact Registry** | Repo: `gdc-build-images` (region: `${REGION}`) | `roles/artifactregistry.reader` *(or `writer`)* | Pulls `iso-builder:${BUILD_VERSION}` (and pushes if executing `./build-builder.sh`). |
| **Cloud Logging** | Project: `${PROJECT_ID}` | `roles/logging.logWriter` | Required by Cloud Build to output step logs (`logging: CLOUD_LOGGING_ONLY`). |
| **IAM Delegation** | On the dedicated GSA itself | `roles/iam.serviceAccountUser` | Granted to the Cloud Build Service Agent (`service-${PROJECT_NUMBER}@gcp-sa-cloudbuild.iam.gserviceaccount.com`) so Cloud Build can execute as this GSA. |

---

### Step 4: Trigger a GDC ISO Cloud Build Run

To build the GDC ISO, run the top-level `./build.sh` script on your workstation. This script automatically handles variables, respects local environments, ignores heavy directories (via `.gcloudignore`), and initiates the build instantly:

#### Option A: Trigger Using Local Defaults
If you have configured `PROJECT_ID` and `GCS_BUCKET` inside `src/build/build.env`, simply run:
```bash
./build.sh
```

#### Option B: Trigger with On-the-Fly Overrides
You can dynamically override build configurations (like the target GCS bucket, version tag, or GCP Project) using CLI flags:
```bash
./build.sh \
    --bucket "gdc-disk-provisioner-isos" \
    --version "1.0.1" \
    --project "your-gcp-project-id"
```

---

## Agent Turnkey Workflow: Single-Command Full Rebuild & Fleet Reboot

For AI agents and automated pipelines, the complete lifecycle (**Profile Sync** $\rightarrow$ **Cloud Build** $\rightarrow$ **Bootimus Verification & Auto-Heal** $\rightarrow$ **UEFI PXE Next-Boot & Node Reboot**) can be triggered via a single command:

```bash
# Execute unattended full rebuild cycle for profile 'barn':
./bin/local/gdc-node-ops.sh rebuild-cycle --profile barn --version 0.11.3 --yes

# Or simulate via dry-run:
./bin/local/gdc-node-ops.sh rebuild-cycle --profile barn --dry-run
```

For complete architectural details, parameter reference, and step-by-step guidance, see:
👉 [Agent Rebuild Guide](../../docs/AGENT_REBUILD_GUIDE.md)

---

## Build Configuration & Air-Gapped Fallbacks

The build process relies heavily on environment variables defined in `src/build/build.env` (or overridden locally via `local.env`).

### Air-Gapped / Fallback Scenarios (No GDC Companion)
If the provisioning node cannot reach the GDC Companion during deployment (e.g., an entirely offline air-gapped deployment, or a network failure), the node falls back to a predefined offline configuration baked into the ISO.

During the ISO build process, variables under the **GDC COMPANION FALLBACK CONFIGURATION** group in `src/build/build.env` are baked directly into `/target/etc/gdc/fallback-config.json` on the LiveCD. If Ansible fails to receive a configuration from the GDC Companion, it parses this fallback JSON file and continues configuring the machine. 

Relevant fallback variables include:
*   `BOOTSTRAP_HOST_NAME`
*   `MACHINE_STATE_STOP_STAGE` (optional; halts provisioning after specified stage)
*   `BOOTSTRAP_BMCTL_VERSION`
*   `FALLBACK_CLUSTER_VLAN_ID`
*   `FALLBACK_PEERS_JSON`
*   `FALLBACK_GCP_PROJECT_ID`
*   `FALLBACK_GCP_REGION`
*   `FALLBACK_GCP_PRIMARY_GSA`

---

## GCS Directory Structure & Synology Cloud Sync Integration

For Bootimus or other network booting / PXE servers to access your custom-compiled GDC ISOs headlessly:

1. **Blessed Source ISO Placement:** Ensure you upload the official, "blessed" Ubuntu 24.04 server ISO to your source GCS bucket under `/source/` before running your first compilation:
   ```bash
   gcloud storage cp /path/to/ubuntu-24.04-live-server-amd64.iso gs://your-blessed-bucket-name/source/ubuntu-24.04-live-server-amd64.iso
   ```
2. **Cloud Output:** Cloud Build automatically writes the customized, remastered ISO back into your destination bucket's **`sync/`** folder (e.g., `gs://your-gcs-bucket-name/sync/gdc-bootstrap-ubuntu-24.04-v1.0.2-<timestamp>.iso`).
3. **Bucket Retention Policy:** On every build success, Cloud Build runs a cleanup sweep, moving all but the **last 5** ISO files (sorted by build number/timestamp) from the `/sync/` folder to the **`archived/`** folder of the bucket.
4. **Synology Cloud Sync Configuration:** 
   Configure Synology's native **Cloud Sync** application (or standard `rclone` config) to sync:
   * **Connection:** Create a connection to **Google Cloud Storage (GCS)**.
   * **Sync Direction:** Set to **Download remote changes only** (recommended).
   * **Local Path:** Bind to your local PXE volume: `/volume1/iso_share/sync/` (accessible by the `pxe` user).
   * **Remote Path:** Select your GCS destination bucket's **`sync/`** folder (e.g., `gs://gdc-disk-provisioner-isos/sync/`).
   This ensures that your local Synology path `/volume1/iso_share/sync/` only pulls down the 5 active, latest ready-to-boot ISOs from the GCS `/sync/` directory, while older versions moved to GCS `/archived/` are completely skipped, saving local NAS disk space.
5. **PXE / Bootimus Triggering & Ingestion:**
   Once synchronized, Bootimus can serve bootable custom GDC images locally from `/volume1/iso_share/sync/`.

---

## Bootimus Automation CLI (`bootimus.py`)

If you are actively developing the custom ISO or require automated bare-metal PXE ingestion, a running Bootimus instance is highly recommended. 

The helper CLI `src/build/bootimus.py` completely automates the Bootimus pipeline, enforces synchronous non-interactive parameter locking across the Bootimus API, and provides tree-based image audits headlessly:

1. **Authentication:** Securely retrieves login credentials from active environment variables (`BOOTIMUS_USER` and `BOOTIMUS_PASS`) or dynamically queries **Infisical** for the secure `bootimus_creds` secret.
2. **Storage Scan & Ingestion:** Sends a `POST /api/scan` request to trigger Bootimus to scan your `/volume1/iso_share/sync/` folder for the newly arrived ISO.
3. **Async Extraction:** Triggers and monitors the asynchronous kernel/initrd extraction from the ISO (`POST /api/images/extract`), polling `/api/images/extract-progress` until fully extracted (100%).
4. **Dynamic Configuration:**
   * Updates the boot method to **`Kernel/Initrd`**.
   * Sets the distro profile to **`ubuntu`**.
   * Activates/Enables the image for client booting.
   * Automatically formats and inserts the custom kernel **Boot Parameters** pointing to the local GCS-sync ISO file and your extracted `nocloud/user-data` location!
5. **Interactive Group Tree Audits:** Lists all registered ISO files inside Bootimus in a beautiful tree structure grouped by folder/group with optional filtering.

**How to Execute:**
```bash
# Optional: Set credentials (or leave empty to pull dynamically from Infisical!)
export BOOTIMUS_USER="admin"
export BOOTIMUS_PASS="your-bootimus-password"

# Ingest and configure a customized GDC ISO
./src/build/bootimus.py gdc-bootstrap-ubuntu-24.04-v0.0.1-20260617-223226.iso

# Render the beautiful groups and images tree
./src/build/bootimus.py --list

# Filter the image tree to show only a specific group/folder
./src/build/bootimus.py --list --filter sync
```

---

## GCS ISO Retention & Archive Sweeper (`clean_gcs_isos.py`)

When repeatedly building and publishing ISOs, the GCS release bucket's `sync/` directory can become crowded. The helper CLI `src/build/clean_gcs_isos.py` (also available via `bin/clean-gcs-isos.py` or `bin/local/clean-gcs-isos.py`) provides automated series-aware retention management:

1. **Series-Aware Retention:** Groups ISOs by prefix and build variant (e.g. `honeywell-24.04-debug`, `gdc-labs-24.04-debug`), sorting them by semantic version (`vX.Y.Z`).
2. **Deterministic Retention:** Retains the newest $N$ builds (default: **3**) per series, even if version numbers contain gaps (e.g., retaining `0.10.9`, `0.10.8`, and `0.10.6` when `0.10.7` was not built).
3. **Safe Archiving:** Moves older ISOs out of `sync/` into `archived/` using `gcloud storage mv`, ensuring local PXE/Synology syncs only pull the latest active images.
4. **Dry-Run & Confirmation Gates:** Supports `--dry-run` to preview actions and requires user confirmation before issuing operations unless `--yes` is specified.

**Usage Examples:**
```bash
# Preview retention cleanup in sync/ (keeping 3 newest per series)
./bin/clean-gcs-isos.py --dry-run

# Execute archiving with interactive confirmation
./bin/clean-gcs-isos.py

# Non-interactive execution keeping top 3 per series
./bin/clean-gcs-isos.py --yes

# Keep top 5 per series for honeywell builds only
./bin/clean-gcs-isos.py --keep 5 --series-filter honeywell --dry-run
```