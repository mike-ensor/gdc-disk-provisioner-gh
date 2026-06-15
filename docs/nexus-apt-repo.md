# Specification & Operational Guide: Nexus APT Repositories & Client-Side Grouping Workaround

This document details the architecture, configuration, and operation of APT (Debian) package repository management on GDC nodes. It addresses a specific constraint of Sonatype Nexus Repository Manager—the lack of support for "Group" repositories in the APT format—and specifies the native Linux client-side workaround to achieve seamless offline sideloading alongside upstream proxy-caching, aligning directly with Google Distributed Cloud (GDC) Bare Metal private package requirements.

---

## 1. The Challenge: No APT Group Repositories in Nexus

While Sonatype Nexus allows aggregating multiple container registries under a single "Docker Group Repository" (enabling the `gdc-docker-group` to prioritize `gdc-docker-hosted` over `gdc-docker-proxy`), **Nexus does not support Group Repositories for the APT format**.

To achieve our goal—overriding public upstream repositories with cryptographically signed, USB-loaded local `.deb` packages—we must shift the "grouping" logic from the repository server to the native Linux APT package manager on the target node.

---

## 2. Architecture & Service Topology

Instead of providing a single endpoint URL to the GDC node, we configure the local Nexus instance with separate Hosted and Proxy repositories, and register both endpoints in the target operating system's APT sources lists.

```
                      ┌──────────────────────────────────────────────┐
                      │              GDC Node (Host OS)              │
                      │         (Natively Merges Metadata)           │
                      └──────┬────────────────────────────────┬──────┘
                             │ (Priority 1)                   │ (Priority 2)
                             ▼                                ▼
                  ┌────────────────────┐            ┌────────────────────┐
                  │  gdc-apt-hosted    │            │  gdc-apt-proxy     │
                  │   (Port 8081)      │            │   (Port 8081)      │
                  └──────────┬─────────┘            └─────────┬──────────┘
                             │                                │
                       [USB Sideload]                    [Auto-Fetches]
                             │                                │
                             ▼                                ▼
                    Internal deb Packages            Upstream deb Mirrors
                  (Custom Hardening / Patches)    (archive.ubuntu.com/noble)
```

### 2.1. Nexus Repository Configurations
Two separate repositories are established within Sonatype Nexus:
1.  **`gdc-apt-hosted` (Hosted APT Repository):**
    *   **Type:** Hosted (Read/Write)
    *   **Purpose:** Houses all localized, offline-first, and custom `.deb` packages sideloaded via physical USB.
    *   **Requirements:** Requires a local GPG signing key generated on the GDC node or build workstation. Nexus uses this key to automatically sign the repository metadata (`Release` files) whenever new packages are uploaded.
2.  **`gdc-apt-proxy` (Proxy APT Repository):**
    *   **Type:** Proxy (Read-Only Cache)
    *   **Purpose:** Proxies the official Ubuntu package mirrors (such as `http://archive.ubuntu.com/ubuntu/` and security sites) for dynamic pulls when online connectivity is active.
    *   **Distribution/Codename:** `noble` (Ubuntu 24.04 LTS).

---

## 3. High-Bandwidth Workstation (USB Export Workflow)

On an internet-connected workstation, operators can fetch required packages and their full transitive dependency trees to copy onto a physical `GDC-UPDATE-USB` drive.

### 3.1. Collecting Packages & Dependencies
To download a package (e.g., `nginx`) along with all required dependencies:
```bash
# Clean up target directory
mkdir -p ./packages/

# Download package and all dependencies recursively
apt-get download $(apt-rdepends nginx | grep -v "^ " | grep -v "Pre-Depends") -o Dir::Cache::archives="./packages/"
```

### 3.2. Signing the Manifest
Once the `.deb` files are copied to `/packages/` on the USB drive, a manifest is generated and signed:
```bash
# Generate manifest
find packages -name "*.deb" > manifest.txt

# Sign the manifest
openssl dgst -sha256 -sign gdc-release-key.pem -out update.sig manifest.txt
```

---

## 4. Limited-Bandwidth Site (USB Import to Hosted Workflow)

When the USB drive is inserted, the node's `gdc-usb-updater` automated script verifies the signature and uploads all sideloaded `.deb` files directly to the hosted repository using the Nexus REST API.

```bash
# Upload packages automatically via curl
for deb in /media/gdc-update/packages/*.deb; do
    logger -t gdc-apt-updater "[GOAL] Uploading ${deb} to local Nexus gdc-apt-hosted..."
    curl -s -u admin:password -X POST \
      "http://127.0.0.1:8081/service/rest/v1/components?repository=gdc-apt-hosted" \
      -F "apt.asset=@${deb}"
done
```

---

## 5. Linux Client Configuration (Target GDC Node)

For Ubuntu 24.04 (Noble Numbat), the client configuration should support both the classic `/etc/apt/sources.list.d/` format and the modern, recommended **DEB822** format.

### 5.1. Trusted GPG Key Registration
The public GPG key corresponding to the Nexus hosted signing key must be deployed to the node's keyring folder:
```bash
# Copy the public keyring to the standard location
cp /etc/gpg/gdc-apt-signing.gpg /etc/apt/keyrings/gdc-nexus.gpg
```

### 5.2. Option A: Classic Format (`/etc/apt/sources.list.d/gdc-nexus.list`)
Write both sources into the target list. This forces APT on the client to poll and merge metadata indexes from both endpoints:

```text
# Local Sideloaded Hosted Repository (Priority 1)
deb [signed-by=/etc/apt/keyrings/gdc-nexus.gpg] http://127.0.0.1:8081/repository/gdc-apt-hosted/ noble main restricted universe multiverse

# Local Upstream Proxy Cache Repository (Priority 2)
deb [signed-by=/etc/apt/keyrings/ubuntu-archive-keyring.gpg] http://127.0.0.1:8081/repository/gdc-apt-proxy/ noble main restricted universe multiverse
```

### 5.3. Option B: DEB822 Format (`/etc/apt/sources.list.d/gdc-nexus.sources`)
The standardized, structured format utilized natively by Ubuntu 24.04:

```ini
# Local GDC Hosted (Sideloaded) Repository
Enabled: yes
Types: deb
URIs: http://127.0.0.1:8081/repository/gdc-apt-hosted/
Suites: noble
Components: main restricted universe multiverse
Signed-By: /etc/apt/keyrings/gdc-nexus.gpg

# Local GDC Proxy (Upstream) Cache Repository
Enabled: yes
Types: deb
URIs: http://127.0.0.1:8081/repository/gdc-apt-proxy/
Suites: noble
Components: main restricted universe multiverse
Signed-By: /etc/apt/keyrings/ubuntu-archive-keyring.gpg
```

---

## 6. Resolving Priority & Bandwidth-Saving via APT Pinning

When multiple APT repositories provide the same package, APT uses native reconciliation loops to decide which source package to install.

### 6.1. Native Version Matching
By default, APT selects the candidate package with the **highest version number**:
*   If you sideload a newer security patch (e.g., `nginx 1.24.0-gdc.2`) into `gdc-apt-hosted`, and the proxy only holds `1.24.0-gdc.1`, APT automatically pulls the sideloaded hosted package.
*   If versions are identical, APT defaults to the first repository declared or matches randomly.

### 6.2. Enforcing Local Sideload Priority (APT Pinning)
To ensure the target machine always pulls from the local USB-loaded `gdc-apt-hosted` registry to conserve restricted external link bandwidth (even if a newer version is indexed in `gdc-apt-proxy`), we enforce a strict **APT Pin Preference**.

Create the pinning configuration file: `/etc/apt/preferences.d/gdc-nexus-pin`

```text
Package: *
Pin: release o=gdc-apt-hosted
Pin-Priority: 1001
```

### 6.3. Pinning Mechanics
*   **Pin-Priority 1001 (Target override):** A priority over `1000` tells the Linux system to always favor packages from `gdc-apt-hosted`, even if a newer version exists in the proxy repository. This mathematically guarantees zero external link bandwidth consumption for any packages present locally.
*   **Result:** APT only falls back to fetching through the `gdc-apt-proxy` repository over the limited-bandwidth uplink if a package is completely absent from the local `gdc-apt-hosted` inventory.

---

## 7. GDC Bare Metal Private Package Repository Alignment

In Google Distributed Cloud (GDC) Bare Metal, node creation and bootstrapping procedures connect to target nodes and verify/install system-level package pre-requisites. Under standard online environments, GDC attempts to inject external repository servers directly into the operating system.

### 7.1. Disabling Default Package Repository injection
To operate in a strictly offline environment, GDC Bare Metal's cluster configuration supports disabling public package injection. This forces GDC BM's orchestration daemon (`bmctl`) to rely exclusively on the OS-level APT configurations we have registered on the node, leveraging the local Nexus Proxy and Hosted endpoints.

Within GDC Bare Metal's `cluster-config.yaml`, set the `addPackageRepo` field under `osEnvironmentConfig` to `false`:

```yaml
apiVersion: baremetal.cluster.gke.io/v1
kind: Cluster
metadata:
  name: gdc-edge-cluster
  namespace: cluster-gdc-edge-cluster
spec:
  # --- DISABLE EXTERNAL PACKAGE REPOSITORY OVERWRITES ---
  osEnvironmentConfig:
    addPackageRepo: false
```

*   **Impact:** Setting `addPackageRepo: false` prevents GDC BM from writing docker-ce or generic package sources to `/etc/apt/sources.list.d/`, ensuring the target client preserves our optimized and secure client-side GPG keyrings and APT pinning configurations.

### 7.2. Required Packages List for GDC Bare Metal
Because the cluster is installed offline, all mandatory Ubuntu dependencies required by GDC Bare Metal must be pre-loaded into the local `gdc-apt-hosted` repository. The build pipeline workstation (during Phase 1 ISO compilation) or operators (during USB maintenance cycles) must download and seed the following package matrices along with their deep recursive dependencies:

| Mandatory Package | Role / GDC Requirement |
| :--- | :--- |
| `python3` (>= 3.6.7) | Core script runtime for internal orchestrator scripts |
| `apt-transport-https` | Enforces HTTPS communication standard |
| `ca-certificates` | Standard security authorities (SSL verification) |
| `conntrack` (>= 1.4.4) | Connection tracking state manager for kube-proxy |
| `curl` | Raw HTTP API operations |
| `software-properties-common` | APT repository path management utilities |
| `gnupg2` | Package cryptographic signature validation |
| `socat` | Port-forwarding utility for Kubernetes API |
| `iproute2` | Advanced system-level Linux routing controller |
| `ebtables` | Bridge packet filtering controller |
| `ethtool` | Network device configuration controller |
| `logrotate` | Container and log segment rotation guard |
| `libseccomp-dev` (>= 2.5) | Container runtime system call sandboxing security |

### 7.3. Standard Dependency Harvesting on the Workstation
To harvest these exact requirements recursively at the high-bandwidth site to prepare the offline USB sideload:
```bash
# Create directory
mkdir -p ./gdc-dependencies/

# Use apt-rdepends to query and download the deep GDC Bare Metal requirements list
apt-get download $(apt-rdepends \
  python3 apt-transport-https ca-certificates conntrack curl software-properties-common gnupg2 socat iproute2 ebtables ethtool logrotate libseccomp-dev \
  | grep -v "^ " | grep -v "Pre-Depends") -o Dir::Cache::archives="./gdc-dependencies/"
```
These gathered `.deb` packages can then be sideloaded directly into `gdc-apt-hosted` via the USB import script.
