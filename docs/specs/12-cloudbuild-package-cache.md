# Specification: Automated GCS Package Cache Updates via Cloud Build

## Overview

Currently, the `update-packages-cache` routine (which resolves, downloads, and caches the offline `.deb` packages required for the GDC ISO) runs inside a local, ephemeral Docker container launched via `make update-packages-cache`. This process has `ENABLE_GCS="false"` hardcoded in the `Makefile`, preventing local executions from syncing updated packages to the remote GCS dependency bucket.

This specification details a new workflow to shift this caching responsibility to **Google Cloud Build**, enabling automated, secure, and authenticated synchronization of Debian packages to the remote `DEPENDENCY_CACHE_GCS_BUCKET`.

## Objectives

1.  **Cloud-Native Execution:** Provide a dedicated Cloud Build pipeline specifically for updating the offline package cache.
2.  **IAM Integration:** Leverage Cloud Build's native Service Account for seamless authentication to GCS, avoiding the need to map local developer credentials into Docker containers.
3.  **Makefile Parameterization:** Remove the hardcoded `ENABLE_GCS="false"` restriction in the local `Makefile` to allow explicit overrides.

## Implementation Details

### 1. Dedicated Cloud Build Configuration (`cloudbuild-packages.yaml`)

A new file, `cloudbuild-packages.yaml`, will be created at the root of the repository. This pipeline isolates the package synchronization from the main ISO compilation pipeline (`cloudbuild.yaml`).

**Key Steps:**
*   **Base Image:** Use the official `ubuntu:24.04` image to guarantee host-to-target compatibility (preventing the `GDC OS Package Target Mismatch!` fatal error).
*   **Dependencies:** Install `curl`, `python3`, `python3-yaml`, and the `google-cloud-cli` (required for `gcloud storage cp`).
*   **Environment:** Explicitly set `ENABLE_GCS="true"` and define `DEPENDENCY_CACHE_GCS_BUCKET` using Cloud Build substitutions.
*   **Execution:** Run the existing `./src/build/preseed_packages.sh` wrapper script.

**YAML Definition:**

```yaml
# cloudbuild-packages.yaml
steps:
  - name: 'ubuntu:24.04'
    id: 'refresh-packages-cache'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        echo "[-] Refreshing and uploading Debian package caches..."
        
        # Install required utilities and the gcloud CLI natively
        apt-get update -qq
        apt-get install -y -qq curl python3 python3-yaml sudo apt-transport-https ca-certificates gnupg
        echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
        curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add -
        apt-get update -qq && apt-get install -y -qq google-cloud-cli

        # Force the environment variables needed to push back to GCS
        export ENABLE_GCS="true"
        export DEPENDENCY_CACHE_GCS_BUCKET="gs://${_GCS_BUCKET_NAME}"
        
        # Execute the python pre-seeding engine natively
        ./src/build/preseed_packages.sh

substitutions:
  _GCS_BUCKET_NAME: 'gdc-disk-provisioner-isos'
```

### 2. Parameterizing the Local `Makefile`

To ensure future flexibility, the hardcoded `ENABLE_GCS` flag in `src/build/Makefile` must be parameterized.

**File:** `src/build/Makefile`
**Target:** `update-packages-cache`

**Changes Required:**

```diff
  update-packages-cache:
      @echo "[-] [Stage: update-packages] Spinning up isolated Ubuntu 24.04 container to pull fresh .deb caches..."
      @mkdir -p $(CACHE_DIR)/packages
      @docker run --rm -v $(shell pwd)/../../.cache:/workspace/.cache \
          -v $(shell pwd)/../../src:/workspace/src \
          -w /workspace \
-         -e ENABLE_GCS="false" \
+         -e ENABLE_GCS="$(if $(UPDATE_CACHE_ENABLE_GCS),$(UPDATE_CACHE_ENABLE_GCS),false)" \
          -e TEST_ONLY="false" \
          -e CACHE_SYSTEM_UPGRADES="true" \
          ubuntu:24.04 bash -c "apt-get update -qq && apt-get install -y -qq curl python3 python3-yaml sudo && ./src/build/preseed_packages.sh"
```

*This allows local developers to explicitly trigger a cache upload by passing `UPDATE_CACHE_ENABLE_GCS="true"` via the `make` invocation if they have configured their local Docker environment with GCS credentials.*

## Execution & Usage

Once implemented, operators can trigger a full cache refresh and synchronization to GCS by submitting the dedicated build configuration:

```bash
gcloud builds submit --config cloudbuild-packages.yaml --substitutions=_GCS_BUCKET_NAME="<target-bucket-name>"
```

### IAM Requirements

The Cloud Build Service Account executing this pipeline must possess the **Storage Object Admin** (`roles/storage.objectAdmin`) role on the destination bucket defined by `${_GCS_BUCKET_NAME}` to successfully execute the `gcloud storage cp` command.