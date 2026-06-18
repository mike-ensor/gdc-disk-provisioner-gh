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
   
   To fully automate the ingestion, kernel extraction, and boot parameter configuration of these newly synced images in Bootimus, use our helper script: **`src/build/bootimus_ingest.py`**.

---

## Bootimus Ingestion Automation Script (`bootimus_ingest.py`)

The helper script `src/build/bootimus_ingest.py` completely automates the Bootimus pipeline headlessly:
1. **Authentication:** Securely retrieves login credentials from active environment variables (`BOOTIMUS_USER` and `BOOTIMUS_PASS`) or dynamically queries **Infisical** for the secure `bootimus_creds` secret.
2. **Storage Scan:** Sends a `POST /api/scan` request to trigger Bootimus to scan your `/volume1/iso_share/sync/` folder for the newly arrived ISO.
3. **Async Extraction:** Triggers and monitors the asynchronous kernel/initrd extraction from the ISO (`POST /api/images/extract`), polling `/api/images/extract-progress` until fully extracted (100%).
4. **Dynamic Configuration:**
   * Updates the boot method to **`Kernel/Initrd`**.
   * Activates/Enables the image for client booting.
   * Automatically formats and inserts the custom kernel **Boot Parameters** pointing to the local GCS-sync ISO file and your extracted `nocloud/user-data` location!

**How to Execute:**
```bash
# Optional: Set credentials (or leave empty to pull dynamically from Infisical!)
export BOOTIMUS_USER="admin"
export BOOTIMUS_PASS="your-bootimus-password"

# Run passing the customized ISO filename (can also read from build_meta.env automatically!)
./src/build/bootimus_ingest.py gdc-bootstrap-ubuntu-24.04-v0.0.1-20260617-223226.iso
```
