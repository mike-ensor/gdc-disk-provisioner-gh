# GDC ISO Remastering & Cloud Build Automation

This directory contains the orchestration files, scripts, and container assets required to build, version, and publish custom Google Distributed Cloud (GDC) offline bootstrap ISOs in a highly repeatable manner.

To support compliance, security, and velocity, the compilation pipeline can run completely in the cloud using **Google Cloud Build** and a custom, pre-packaged builder image.

---

## The 3-Step Lifecycle: Containerization, Compilation, & Cloud Build

Follow these steps to set up your custom builder registry, compile the builder container, and trigger automated GDC ISO remastering runs in the cloud.

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

### Step 3: Trigger a GDC ISO Cloud Build Run

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