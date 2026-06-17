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

## GCS Directory Structure & Synology Pull Integration

For Bootimus or other network booting / PXE servers to access your custom-compiled GDC ISOs headlessly:

1. **Blessed Source ISO Placement:** Ensure you upload the official, "blessed" Ubuntu 24.04 server ISO to the GCS bucket under `/source/` before running your first compilation:
   ```bash
   gcloud storage cp /path/to/ubuntu-24.04-live-server-amd64.iso gs://your-gcs-bucket-name/source/ubuntu-24.04-live-server-amd64.iso
   ```
2. **Cloud Output:** Cloud Build automatically writes the customized, remastered ISO back into your destination bucket root (e.g., `gs://your-gcs-bucket-name/gdc-bootstrap-ubuntu-24.04-v1.0.1-<timestamp>.iso`).
3. **Synology Syncer:** Schedule `scripts/synology-sync.sh` to run via the **Synology Task Scheduler** to pull down finished ISOs securely and incrementally.
