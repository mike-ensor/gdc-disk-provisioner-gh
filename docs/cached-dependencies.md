# Data Flow and Caching Analysis Report: GDC Debian & Container Packages

## 1. Debian Packages (`.deb`)

### 1.1. How Debian Packages are Cached in the GCS Bucket
The central Google Cloud Storage (GCS) bucket (e.g., `gs://gdc-disk-provisioner-isos`) serves as the unified cache for offline dependencies.
*   **Trigger/Frequency:** The GCS cache is populated by executing the `cloudbuild-cache.yaml` pipeline ("GDC Bootloader - GCS Cache Pre-Seeding & Fill Pipeline"). This is executed out-of-band (independent of the ISO build) whenever upstream dependencies need to be refreshed.
*   **Tools Used:**
    *   **Python/Shell:** `src/build/preseed_packages.py` (wrapped by `preseed_packages.sh`).
    *   **APT Utilities:** Uses `apt-cache depends --recurse --no-recommends` to resolve the full dependency tree of items listed in `src/build/packages_config.yaml` (while actively filtering out base-OS libraries like `^libc6$`).
    *   **Download:** Uses `apt-get download` to fetch `.deb` files into a local `.cache/packages` directory.
    *   **Upload:** Uses `gcloud storage cp` to synchronize all `.deb` files to the `gs://${GCS_BUCKET}/packages/` prefix.

### 1.2. Usage During the ISO Build Process
*   **Tools Used:** Google Cloud Build (`cloudbuild.yaml`) or local `Makefile` / `build.sh`.
*   **Data Flow:**
    1.  **Fetch:** During Step 1 of `cloudbuild.yaml` (or via `make deps`), the pipeline pulls all pre-cached `.deb` packages from `gs://${GCS_BUCKET}/packages/` down to the local worker workspace (`.cache/packages/`).
    2.  **Injection:** The `src/build/remaster.sh` script executes `cp` to inject these `.deb` files into the extracted read-only ISO filesystem under `/custom-data/packages/`.
    3.  **Post-Install Propagation:** During the node's first boot, Ansible (`stage_first_boot.yml` / `user-data.j2`) `rsync`s the `/cdrom/custom-data/` directory to persistent LVM storage at `/var/gdc-install/iso-cache/`.
    4.  **Local Nexus Seeding:** An Ansible playbook (`roles/service_hubs/tasks/main.yml`) iterates over these `.deb` files, executing `curl -X POST` requests to upload them directly into the node's offline Sonatype Nexus Hosted repository (`gdc-apt-hosted` on port `8081`).

### 1.3. How and When Debian Packages are Updated on the Nodes
*   **Connected Mode:** 
    *   *Frequency:* Controlled by the local systemd `ansible-pull` cron schedules.
    *   *Data Flow:* When `apt-get upgrade` runs, the local APT client hits the Nexus Proxy (`gdc-apt-proxy`). Nexus fetches newer versions from public Ubuntu mirrors, writes the `.deb` to its local offline blob storage (`/var/lib/nexus`), and streams it to the node.
*   **Air-Gapped / Offline Mode (Sideloading):** 
    *   *Frequency:* Operator-driven (Stage 6A offline update flow).
    *   *Data Flow:* Operators place new `.deb` files onto a USB labeled `GDC-UPDATE-USB` or download them from an authenticated edge GCS bucket. The `udev`-triggered `gdc-headless-update.sh` script ingests the new `.deb` files via the Nexus REST API into the `gdc-apt-hosted` repository.

---

## 2. Container Packages (OCI Images)

### 2.1. How Container Images are Cached (GCS & ISO Footprint)
Unlike Debian packages, massive OCI container image layers (for Kubernetes, Platform Operations, and LLMs) are **not** bundled directly into the base ISO by `remaster.sh`. This architectural decision explicitly prevents "ISO Bloat" (which would result in 50GB–100GB+ ISO files causing network and memory failures during PXE/bootloader execution). 
*   **GCS Sideloading Cache:** Instead of living inside the ISO build, OCI images are stored in GCS sideload buckets or bundled as customer assets (e.g., `baremetal/bmpackages_$VERSION`).
*   **Tools Used for Local Node Architecture:** Containers are managed entirely by a **Sonatype Nexus Docker Group Repository** (`gdc-docker-group` on port `5001`), which aggregates a read-write Hosted repository (`gdc-docker-hosted`) and a caching Proxy repository (`gdc-docker-proxy`).

### 2.2. Usage and Propagation During Cluster Setup
*   **Data Flow:**
    1.  The node's container runtimes (Kubelet, containerd in `/etc/containerd/config.toml`, and Docker in `/etc/docker/daemon.json`) are configured to route all pulls through `http://nexus.gdc.local:5001`.
    2.  Before `bmctl create cluster` executes, required images must be seeded into the local Nexus repository to ensure a 100% offline cluster bootstrapping process.

### 2.3. How and When Container Images are Updated on the Nodes
*   **Connected Mode (Proxy Caching):**
    *   *Frequency:* Dynamic / On-Demand.
    *   *Data Flow:* When Kubelet requests an image (e.g., `gcr.io/gke-release/node-agent-amd64`), it pulls from Nexus Port `5001`. If the image is not in the local cache, the `gdc-docker-proxy` repository fetches it from the upstream internet registry. 
    *   *Caching:* Nexus is configured with an infinite TTL (`-1`). It caches the image layers persistently to the `lv_nexus` volume (`/var/lib/nexus`), serving subsequent pulls from the local disk at high speeds.
*   **Air-Gapped / Offline Mode (Sideloading):**
    *   *Frequency:* Operator-driven (Stage 6A offline update flow or First-Boot Ingestion).
    *   *Data Flow:* Container images are exported as `*.tar` bundles. They are imported to the node via physical USB or internal network file transfer. 
    *   *Tools Used:* The node executes `docker load -i <bundle>.tar`, tags the image for localhost, and performs a `docker push 127.0.0.1:5002/<image>` (Port `5002` is the dedicated write-port for the Nexus Hosted registry). Alternatively, GDC provides a native tool executed as `bmctl push images --private-registry 127.0.0.1:5002/...` to bulk-load registry endpoints.