# Specification & Operational Guide: Docker Group Repository & OCI Sideloading

This document outlines the architecture, setup, and operations for the GDC Node **Docker Group Repository** hosted via Sonatype Nexus. It explains how container images are stored, retrieved, and updated in both offline (sideloaded) and network-connected scenarios, accommodating strict 10Mbps bandwidth constraints and GDC Bare Metal requirements.

---

## 1. Architectural Concept: Docker Group Repository

To satisfy the requirements of a **Hub-and-Spoke Sideloading Architecture**, GDC nodes run a Sonatype Nexus Repository Manager instance. To simplify container ingestion and pulling, Nexus is configured with a **Docker Group Repository** (`gdc-docker-group`) exposed on port `5001`.

The group repository acts as a single, unified loopback registry endpoint for both the host operating system, the local GDC Bare Metal Kubernetes cluster (`bmctl`/Kubelet), and user-space applications (Pods).

```
                      ┌──────────────────────────────────────────────┐
                      │            gdc-docker-group (Port 5001)       │
                      │             (Single Loopback Pull Endpoint)  │
                      └──────┬────────────────────────────────┬──────┘
                             │                                │
                             ▼ (Priority 1 Check)             ▼ (Priority 2 Fallback)
                  ┌────────────────────┐            ┌────────────────────┐
                  │ gdc-docker-hosted  │            │  gdc-docker-proxy  │
                  │  (Port 5002 Push)  │            │ (Read-Only Cache)  │
                  └──────────┬─────────┘            └─────────┬──────────┘
                             │                                │
                        [You Push]                       [Auto-Fetches]
                             │                                │
                             ▼                                ▼
                     Sideloaded Images               Upstream Registries
                  (Cluster/Platform/Apps)        (gcr.io, docker.io, etc.)
```

### 1.1. Underlying Repositories & Priorities
The Docker Group aggregates the following repositories in strict priority order:
1.  **`gdc-docker-hosted` (Hosted Registry - Priority 1):**
    *   **Type:** Hosted (Read/Write)
    *   **Port:** Port `5002` (Dedicated write endpoint)
    *   **Purpose:** Houses all localized, offline-first images. At the time of ISO compilation, all required Cluster (Kubernetes control plane, etcd, CoreDNS), Platform (MetalLB, CSI storage controllers), and core Application containers are pre-fetched, versioned, and pushed directly here.
    *   **Behavior:** When the cluster pulls an image from the Group port `5001`, Nexus checks this repository first.
2.  **`gdc-docker-proxy` (Proxy Registry - Priority 2):**
    *   **Type:** Proxy (Read-Only Cache)
    *   **Purpose:** Proxies upstream container registries (e.g., `registry-1.docker.io`, `gcr.io`, `quay.io`, `pkg.dev`).
    *   **Behavior:** If an image is not found in `gdc-docker-hosted`, and the node has active internet/intranet connectivity, this proxy automatically pulls, caches, and serves the image from the remote repository over the 10Mbps connection. Subsequent pulls are served entirely from local LVM-backed cache on the machine, saving bandwidth.

---

## 2. Ingestion Workflow A: Offline Sideloading (Sneakernet / USB)

In air-gapped, offline, or low-bandwidth environments, new images are imported via a physical storage medium (like an encrypted USB drive labeled `GDC-UPDATE-USB`) and loaded into the local hosted registry.

### 2.1. Ingestion Sequence

```
[Workstation]                     [USB Drive]                   [GDC Node / Nexus]
      │                                │                                │
      ├─ 1. Pull & docker save ───────>│                                │
      ├─ 2. Write manifest & sign ────>│                                │
      │                                │                                │
      │                                └─ 3. Insert USB into Node ─────>┤
      │                                                                 ├─ 4. Udev trigger runs
      │                                                                 ├─ 5. Verify signature
      │                                                                 ├─ 6. Load & Push directly to
      │                                                                 │    gdc-docker-hosted:5002
      │                                                                 ▼
```

### 2.2. Step-by-Step Sneakernet (USB) Workflow

#### Step 1: At your high-bandwidth site (Export)
On an internet-connected workstation, save the required public containers to your USB drive as tarballs:
```bash
# Pull the image from public upstream registries
docker pull postgres:16

# Save the image as a compressed tar archive to your USB mount
docker save -o /mnt/usb/postgres_16.tar postgres:16
```

#### Step 2: At your limited-bandwidth site (Import via USB)
When the USB drive is plugged into the target node's chassis, the automated `gdc-usb-updater` daemon triggers. The tool runs the following operations to load, tag, and push the image into the local hosted repository:
```bash
# 1. Load the image from the USB drive into local Docker/containerd daemon
docker load -i /media/gdc-update/postgres_16.tar

# 2. Tag the image explicitly for your INTERNAL HOSTED repository port/URL
# Note: We push to Port 5002 (the dedicated Hosted push connector)
docker tag postgres:16 127.0.0.1:5002/postgres:16

# 3. Push directly to the Hosted repo (so Nexus can catalogue it)
docker push 127.0.0.1:5002/postgres:16
```

#### Step 3: Deploying in your Kubernetes Cluster
Point your Kubernetes manifests to the **GROUP** repository port/URL (`5001`) using the public image name structure:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres-db
spec:
  template:
    spec:
      containers:
      - name: db
        # Points exclusively to the GROUP endpoint (Port 5001)
        image: 127.0.0.1:5001/postgres:16
```
When Kubernetes requests this, Nexus checks `gdc-docker-hosted` first, finds your USB-loaded image on local LVM, and serves it immediately at gigabit speed without touching the limited 10Mbps uplink.

---

## 3. Ingestion Workflow B: Connected Upstream Proxying

For nodes deployed in environments with an active network gateway, container images are ingested dynamically using Nexus's passive proxying mechanism.

```
[Cluster/App Pod]                [gdc-docker-group:5001]         [Upstream Registry]
       │                                 │                                │
       ├─ 1. Pulls custom-app:1.3.0 ────>┤                                │
       │                                 ├─ [Check gdc-docker-hosted]     │
       │                                 ├─ [Not Found]                   │
       │                                 ├─ 2. Forward pull request ─────>┤
       │                                 │                                ├─ 3. Returns image layers
       │                                 ├─ 4. Cache layers locally ──────┤
       │<─ 5. Stream image layers ───────┤                                │
```

### 3.1. Dynamic Caching & Bandwidth Conservation
*   **Proxy Configuration:** The proxy repository is configured to cache OCI layers with an infinite TTL (`-1` value).
*   **The Pull Loop:** 
    1.  The pod requests an image (e.g., `127.0.0.1:5001/library/nginx:1.25.3`).
    2.  `gdc-docker-group` searches the hosted repository first; upon a miss, it forwards the query to the remote storage URL (e.g., `https://registry-1.docker.io`).
    3.  The layers are fetched across the 10Mbps link, cached locally in `/var/lib/nexus`, and streamed back to Kubelet.
    4.  Subsequent nodes or pod restarts on the same cluster resolve the pull completely off-line, conserving the 10Mbps uplink.

---

## 4. Critical Configuration Traps to Avoid

When configuring Sonatype Nexus for GDC Docker deployments, there are two major configuration traps that must be avoided to prevent system failures:

### Trap 1: Group Priority Order
Inside the Nexus Group settings, ensure your Hosted repository (`gdc-docker-hosted`) is listed on the **right-hand side (Selected)** and ordered **above** the Proxy repository (`gdc-docker-proxy`).
*   **Why:** If the Proxy repository is prioritized first, Nexus will attempt to ping external upstream registries over the 10Mbps link for *every* pull request. If the internet connection drops or lags, cluster deployments will experience severe latency or timeout failures (image pull back-off), even if the container is present in local hosted storage.

### Trap 2: Distinct HTTP Ports Requirement
Nexus requires unique, independent HTTP/HTTPS connectors for Docker repositories to correctly process CLI-level authentication (`docker login`) and routing boundaries. 
*   **Why:** Unlike standard Maven or APT repositories where paths differentiate actions, the Docker CLI sends requests directly to the base URL and port. You must allocate separate ports:
    *   **Port `5001` (Group):** Bound to `gdc-docker-group`. Configure Kubernetes and the target host system to *pull* exclusively from this port.
    *   **Port `5002` (Hosted):** Bound to `gdc-docker-hosted`. Configure your build tools, sideloading scripts, and CLI push actions to *authenticate and push* exclusively to this port.
    *   *Warning:* If you map both to the same port, pushes will fail with immediate authorization or routing conflicts (e.g., `Method Not Allowed` errors).

---

## 5. Architectural Alignment: GDC Bare Metal Registry Mirror vs. Nexus Group Repository

In Google Distributed Cloud (GDC) Bare Metal, a native **Registry Mirror** feature is available (documented in the [GDC Bare Metal Installing Registry Mirror Guide](https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/installing/registry-mirror)). It is critical to analyze how GDC's Registry Mirror and Nexus's Docker Group Repository align to understand whether they compete or cooperate.

### 5.1. Do they cooperate or compete?
**They work together in perfect synergy.** They represent two complementary halves of GDC's offline-first container retrieval solution:
1.  **GDC Registry Mirror (The Client-Side Redirector):**
    *   **Layer:** Client-side orchestration runtime (`containerd` configuration on the node).
    *   **Purpose:** Intercepts pull requests targetting standard public container registries (like `gcr.io`, `registry.k8s.io`, `docker.io`, and `quay.io`) and dynamically translates/redirects them to query our local endpoint (`http://127.0.0.1:5001`) instead.
    *   **Benefit:** Eliminates the need to manually rewrite image string names inside third-party manifests, Helm charts, and system definitions. A pod manifest requesting `gcr.io/gke-release/coredns:v1.10.1` pulls from local loopback automatically without edits.
2.  **Nexus Docker Group Repository (The Server-Side Aggregator):**
    *   **Layer:** Server-side repository storage (Sonatype Nexus on port `5001`).
    *   **Purpose:** Receives the redirected pulls from `containerd` and intelligently serves them. It looks into `gdc-docker-hosted` first to fetch local, signed, USB-sideloaded system and platform components. If absent and the link is connected, it relies on `gdc-docker-proxy` to lazily fetch the layers over the 10Mbps link, caching them persistently on the node's LVM disk partition `/var/lib/nexus` for subsequent offline requests.

By combining the two, you get **100% transparent local overriding and caching**:
*   *Without Registry Mirroring:* Developers would be forced to modify thousands of image strings in standard GDC system yaml templates to point to `127.0.0.1:5001/...`, which is highly error-prone.
*   *Without Docker Group Repositories:* The registry mirror would point to a single static registry. You would lose the ability to easily merge your pre-loaded offline repository and your on-demand internet proxy, resulting in severe bandwidth waste or an inability to fetch uncached dependencies dynamically.

### 5.2. GDC Bare Metal Configuration Example
To tie GDC Bare Metal's client-side runtime to our local Nexus Server, GDC's `cluster-config.yaml` is configured with the `registryMirror` endpoint:

```yaml
apiVersion: baremetal.cluster.gke.io/v1
kind: Cluster
metadata:
  name: gdc-edge-cluster
  namespace: cluster-gdc-edge-cluster
spec:
  type: standalone
  # --- ENABLE CLIENT-SIDE CONTAINERD REDIRECTION TO PORT 5001 ---
  registryMirror:
    endpoint: http://127.0.0.1:5001
```

*Note: When GDC Bare Metal provisions the node, it automatically configures `/etc/containerd/certs.d/` or `/etc/containerd/config.toml` (depending on the GDC Bare Metal release) with the local endpoint. The local loopback `127.0.0.1:5001` serves as the target for all public container registries.*

---

## 6. Security & Signatures (Sigstore/Cosign)

All container images pulled via GDC loopbacks are cryptographically verified:
*   An admission controller webhook intercepts image schedules.
*   The layers are checked against GDC's local node verification key:
    ```bash
    cosign verify --key /etc/cosign/gdc-k8s-signing.pub 127.0.0.1:5001/gdc/my-app:1.0.0
    ```
*   Unsigned images or signature mismatches abort deployment with a `CreateContainerConfigError`.

---

## 7. Practical Reference: Deploying Nexus Mirror Registry for GDC Bare Metal

An essential industry implementation resource is detailed in the technical blog post: [Deploying a Nexus Mirror Registry for GDC Bare Metal by Patrick Simonian](https://www.linkedin.com/pulse/deploying-nexus-mirror-registry-gdc-bare-metal-patrick-simonian-7k4yc/).

The following summarizes the critical operational parameters and optimization guidelines derived from real-world GDC Bare Metal deployments outlined in the reference:

### 7.1. Utilizing the GDC Native Push Tool (`bmctl push images`)
Instead of executing manual `docker load`, `docker tag`, and `docker push` loops for hundreds of GDC system container images, GDC Bare Metal provides a native utility package and command to automate loading and seeding (aligned with the official [GDC Bare Metal Upload Container Images Guide](https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/installing/registry-mirror#upload_container_images_to_your_registry_server)):
```bash
# 1. Choose and define GDC Bare Metal version target
export VERSION=1.32.400-gke.68

# 2. Acquire GDC BM packages and CLI tool (on high-bandwidth workstation)
gcloud storage cp gs://anthos-baremetal-release/bmctl/$VERSION/linux-amd64/bmctl .
gcloud storage cp gs://anthos-baremetal-release/bmctl/$VERSION/linux-amd64/bmpackages_$VERSION.tar.xz .
chmod +x ./bmctl

# 3. Authenticate Docker CLI to local Nexus Hosted repository
docker login 127.0.0.1:5002

# 4. Automate pushing all GDC system images directly into Nexus Hosted repository
# (Utilizing multi-threaded options to optimize extraction and ingestion bandwidth)
./bmctl push images \
    --source bmpackages_$VERSION.tar.xz \
    --private-registry 127.0.0.1:5002/baremetal/bmpackages_$VERSION \
    --threads=20
```

### 7.2. Critical Nginx Proxy Constraints (Body Size & Timeouts)
Because GDC Bare Metal package bundles are exceptionally large, any Nginx reverse proxy routing traffic to Sonatype Nexus (on ports `8081` and `8082` / `5001` and `5002`) MUST be configured to accommodate massive file chunks and prolonged stream times to prevent immediate gateway timeouts:

```nginx
server {
    listen 443 ssl;
    server_name nexus.local;

    # Mandatory configurations for GDC Bare Metal package transfers
    client_max_body_size 10G;
    proxy_read_timeout 3600s;
    proxy_connect_timeout 3600s;
    proxy_send_timeout 3600s;
    send_timeout 3600s;

    location / {
        proxy_pass http://127.0.0.1:8081/;
        # ... standard proxy headers ...
    }

    # Docker registry configuration (Hosted Write endpoint mapping)
    location /v2/ {
        proxy_pass http://127.0.0.1:5002/v2/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 7.3. VM & Disk Scaling
*   **The Constraint:** The GDC Bare Metal container image suite contains upwards of 129 distinct heavy images. Decompressing and writing layers sequentially causes massive disk queue wait latency.
*   **The Recommendation:** The virtual machine hosting Nexus during testing or staging should be provisioned with high-performance solid-state drives (e.g., GCP `pd-ssd` or local NVMe storage) and standard scaling parameters (such as `c2-standard-8` compute tiers) to avoid throttling extraction and index generation pipelines.
