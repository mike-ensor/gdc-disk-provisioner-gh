# Specification: GDC Ready-Linux Provisioning & Sideloading Interface

**Spec Identifier:** `GDC-SPEC-003`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Security Architecture Team  

---

## 1. Executive Summary & Purpose
This specification details the transition from a baseline OS installation to a fully hardened, secure "Ready-Linux" GDC node. It covers the post-install sequence of operations, persistent Gitea and Nexus service hub configurations, variable-driven system package installations, and hardware cryptography (TPM 2.0).

Additionally, it specifies the standard **GDC Offline Sideloading Interface** (for Git playbook updates, deb packages, and OCI container layers) and defines the roadmap to transition from local development to strict GPG-signed commit enforcement.

---

## 2. The First-Boot Migration & Service Transition

### 2.1. Late-Command Sync Script & Space Guardrails
During Subiquity's `late-commands`, pre-loaded configurations and caches are cloned from the read-only ISO media (`/cdrom/custom-data/`) to the persistent logical volumes mounted under `/target/`.

*   **Operational Guardrail (Sizing Caps):** In Single-Disk topologies (`GDC-SPEC-002-SEQ`), `lv_nexus` is compressed to 60 GiB. To prevent installation crashes ("No space left on device"), the Phase 1 build engine enforces a strict **40 GB maximum footprint cap** on pre-seeded ISO files inside `/custom-data/nexus/`.

```yaml
autoinstall:
  late-commands:
    # 1. Verify target directory presence (automatically mapped by Subiquity mounts)
    - mkdir -p /target/var/lib/gitea /target/var/lib/nexus
    
    # 2. Sync pre-seeded assets cleanly
    - rsync -a --sparse --info=progress2 /cdrom/custom-data/gitea/ /target/var/lib/gitea/
    - rsync -a --sparse --info=progress2 /cdrom/custom-data/nexus/ /target/var/lib/nexus/
    
    # 3. Deploy persistent systemd configurations and enable them
    - cp /cdrom/custom-data/systemd/gitea.service /target/etc/systemd/system/
    - cp /cdrom/custom-data/systemd/nexus.service /target/etc/systemd/system/
    - curtin in-target -- systemctl enable gitea.service nexus.service
```

### 2.2. Bootstrapping Ansible & Git (Offline Installation)
To avoid manual package installation hacks post-boot, the baseline Subiquity installer pre-installs `ansible` and `git` on the target root filesystem during installation.
*   **Enforcement:** We add `ansible` and `git` to the autoinstall `packages` section:
    ```yaml
    autoinstall:
      packages:
        - ansible
        - git
    ```
*   Because the installation redirects APT fetches to our local live-ISO Nexus server (`http://127.0.0.1:8081/repository/gdc-apt-proxy/`), these packages are installed cleanly and completely offline.

---

## 3. Ansible-Pull Bootstrap Execution
Upon first boot, systemd triggers `gdc-provision.service`, which launches the `ansible-pull` bootstrap sequence completely offline targeting Gitea's local loopback port `3000`.

### 3.1. Provisioner Service Unit (`gdc-provision.service`)
```ini
[Unit]
Description=GDC Ready-Linux First Boot Provisioner
After=gitea.service nexus.service network.target
Requires=gitea.service nexus.service

[Service]
Type=oneshot
EnvironmentFile=-/etc/default/gdc-provision
ExecStart=/bin/bash -c "/usr/bin/ansible-pull \
  -U http://127.0.0.1:3000/gdc/bootstrap-playbooks.git \
  -i localhost, \
  $ANSIBLE_PULL_FLAGS \
  local.yml"
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
```

### 3.2. Environmental Signed-Commits Toggle (`/etc/default/gdc-provision`)
To support frictionless initial development while enforcing absolute security in production, GPG commit verification is managed via an environment file written at build time:
* **Development Mode (`ENFORCE_SIGNED_COMMITS=false`):**
  ```text
  # /etc/default/gdc-provision
  ANSIBLE_PULL_FLAGS=""
  ```
* **Production Mode (`ENFORCE_SIGNED_COMMITS=true`):**
  ```text
  # /etc/default/gdc-provision
  ANSIBLE_PULL_FLAGS="--verify-commit"
  ```

---

## 4. Cryptographic Sideload Verification Standards
Because the node operates in air-gapped or low-internet environments, standard online certificate revocation lists (CRLs) and public notary servers are unavailable. We enforce strict local cryptographic verification on all sideloaded code, packages, and container images.

```text
               SIDELOADED ASSET PAYLOAD
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
   [ Git commit ]   [ APT Package ]   [ Docker OCI ]
         │                │                │
   (GPG Signed)     (GPG Signed)     (Cosign Signed)
         │                │                │
         ▼                ▼                ▼
  Verify Commit    Verify Release   Verify Signature
  against GDC      against Local    against GDC Node
  GPG Ring         APT GPG Ring     Public Key Store
```

### 4.1. GPG Commit Verification for `ansible-pull`
To prevent unauthorized playbook execution, `ansible-pull` is executed with the `--verify-commit` flag in Production Mode.
*   **Enforcement:** The local Git configuration inside the target OS is locked to verify commit signatures against GDC's pre-loaded GPG public keyring stored in `/etc/gpg/gdc-release.gpg`.
*   Unsigned commits or commits signed by untrusted keys are instantly rejected, aborting playbook runs before host modifications can execute.

### 4.2. Cosign OCI Image Verification & Docker Group Repository Structure
All container images—whether sideloaded/pre-seeded into Nexus or dynamically cached from upstream—are managed via a **Docker Group Repository** (`gdc-docker-group` on port 5001). This aggregates two underlying repositories:
1. **Hosted Repository (`gdc-docker-hosted`):** A read-write storage area for local and sideloaded images. During the ISO build process (Phase 1), every OCI image required for **Cluster** bootstrapping, **Platform** operations, and initial **Applications** (along with their exact semantic version tags) is fetched and pushed directly into this hosted registry. This establishes the absolute offline source of truth.
2. **Proxy Repository (`gdc-docker-proxy`):** A read-only cache configuration that proxies upstream registries (such as `gcr.io` or `docker.io`) for dynamic pulls when online connectivity is active.

Before the local Kubernetes Kubelet or containerd runtime extracts and deploys any OCI container image from the unified group port `5001`, its layers are cryptographically verified using **Sigstore/Cosign**:
*   **Enforcement:** An admission webhook (e.g., Policy Controller or Kyverno) intercepts the pod scheduling request and asserts image signature validity against the GDC node's public key store:
    ```bash
    cosign verify --key /etc/cosign/gdc-k8s-signing.pub localhost:5001/gdc/my-image:1.24.0-gdc.1
    ```
*   Unsigned container layers or signature mismatches instantly abort the Pod deployment, block container creation, and prevent execution of arbitrary images.

---

## 5. Playbook Tasks: Ready-Linux Configuration
To maximize idempotence and declarative engineering standards, the entire GDC post-install setup is handled as a structured Ansible playbook (`local.yml`) executed via the local `ansible-pull` cron cycles.

### 5.1. Persistent Local Hub Configuration (Gitea & Nexus)
*   **Action:** Validates Gitea and Nexus are running permanently on the host backed by the high-capacity, persistent LVM storage mounts `/var/lib/gitea` and `/var/lib/nexus`.
*   **Enforcement:** Configures target OS systemd units to permanently `enable` and `start` the local boundary service hubs, ready to serve package, repository, and OCI requests locally.

### 5.2. Offline Safe Package Upgrades (System Upgrade)
*   **Action:** Performs a safe system upgrade (`apt-get upgrade`) using the localized APT mirror running on the node.
*   **Enforcement:** Points the node's APT configuration exclusively to the local GDC Nexus proxy server on port 8081, satisfying all package, kernel-patch, or dependency upgrades completely offline without outside internet connections.

### 5.3. Variable-Driven Core Package Installation
*   **Action:** Dynamically parses and installs the specific list of critical system packages and explicit versions configured during the Phase 1 build.
*   **Config Reference:** The package list and version matrix is declared inside the central build configuration `src/build/build.env` under the `POST_INSTALL_PACKAGES` list.
*   **Loop Execution:** The Ansible playbook loops through the list dynamically, running `apt-get install` to install them (e.g. `git`, `python3-pip`, `wireguard`).

### 5.4. Administrative User Setup
* Creates the system user `gdc-admin`.
* Drops administrative sudo permissions securely under `/etc/sudoers.d/gdc-admin` utilizing passwordless parameters:
  ```text
  gdc-admin ALL=(ALL) NOPASSWD:ALL
  ```

### 5.5. TPM 2.0 Cryptographic Binding & Automated Boot-Unlocking
*   **Action:** Registers and seals LUKS storage decryption keys to the hardware TPM 2.0 chip using Platform Configuration Registers (PCRs) `0` (Firmware), `2` (PCI Configurations), and `7` (Secure Boot State).
*   **Unlocking Config:** Writes target `/etc/crypttab` pointing to `tpm2-device=auto,discard`.
*   **Cleanup:** Generates an escrow LVM recovery passphrase, wipes the temporary bootstrap password from metadata keyslots, and purges temporary files.

### 5.6. Remote Attestation & Cloud-Validated Device Identity
*   **Handshake:** Generates an Attestation Key (AK) and takes a TPM PCR boot quote signed with a dynamic cloud-challenge nonce.
*   **TLS Enrollment:** Requests GDC Device TLS identity certificates from GCP Cloud CAs using an un-extractable RSA private key generated inside the TPM's secure PKCS#11 enclave.

### 5.7. CIS Hardening and OS Slimming
*   Applies CIS Benchmark Level 2 controls (SSH limits, FIPS ciphers, auditd, and sysctl controls).
*   Purges `snapd`, compiler runtimes, and unnecessary baseline GUI tools.

### 5.8. GDC NodeAgent Pre-Installation & mTLS Trust Pre-Seeding (Zero-SSH ISO Strategy)
To enable on-node health monitoring and automated lifecycle management right after cluster turnup, the **GDC NodeAgent** is pre-installed/staged during the Ready-Linux phase.

If GGD's automated provisioning process (such as our custom ISO, Kickstart, or Cloud-Init) injects the NodeAgent binary, configures its systemd unit file, and starts the service automatically, **the deployment process can completely avoid SSH bootstrapping, but with one critical catch: Trust.**

The GDC orchestration engine (`bmctl` or the cluster controller) does not strictly care *how* NodeAgent got onto the machine; it only cares that it can talk to it over port `9192`. However, because NodeAgent communicates strictly via **mutual TLS (mTLS)**, we must solve the **initial trust problem** during ISO provisioning.

#### A. The Strict Requirement: The mTLS Pre-Seed
For NodeAgent to accept commands from the deployment workstation or local standalone control plane, it requires specific cryptographic identities *at the exact moment it boots*. If our ISO just drops a generic NodeAgent binary onto the disk, it will sit there failing to initialize because it lacks credentials.

If we want a **100% Zero-SSH** deployment pipeline, GGD's automated Ready-Linux provisioning playbook must inject the following files into the node's local storage:
1.  **The Server CA Certificate:** So NodeAgent can validate that incoming cluster controller requests are authentic.
2.  **The Node's Local Server Certificate & Private Key:** So the node can identify itself securely to the controller.
3.  **The Client CA Certificate:** To enforce authorization on incoming gRPC connections.

These paths must match exactly what you declare in the top section of your `CLUSTER_NAME.yaml` file (e.g., `nodeAgentServerCACertificatePath`, etc.).

#### B. Architectural Comparison: Legacy SSH vs. Zero-SSH ISO

```
[Legacy SSH Method]
bmctl Workstation ----( SSH / Port 22 )----> Blank Target OS (Pushes Binary + Certs)
                                                    │
                                                    ▼
                                           NodeAgent Running

[Zero-SSH ISO Method]
Custom ISO / Pre-seed ----( Installs Binary + Valid mTLS Certs )----> Active Target OS
                                                                            │
                                                                            ▼
bmctl Workstation <---( Secure mTLS gRPC / Port 9192 )------------ NodeAgent Listening
```

*   **Scenario A: Unique Certificates Pre-Seeding via ISO (GGD Standard):**
    *   **Result:** **No SSH required at all.**
    *   When you run `bmctl create cluster`, the workstation will skip trying to connect over port 22 and immediately initiate the secure gRPC handshake over port `9192`.
*   **Scenario B: ISO installs the agent WITHOUT unique certificates (Fallback):**
    *   **Result:** **SSH bootstrap is still required.**
    *   If the ISO only provisions a generic base image, you must still provide `bmctl` with temporary SSH credentials. You would then run `bmctl nodeagent deploy --cluster CLUSTER_NAME`. This command connects via SSH purely to generate, securely transfer, and apply the initial cryptographic certificates to the asset, after which SSH can be disabled.

*   **Image Caching:** The NodeAgent OCI container image layers (e.g., `gcr.io/gke-release/node-agent-amd64`) are verified and pre-seeded directly into the local `gdc-docker-hosted` repository on Nexus Port `5002` to support 100% offline retrieval.
*   **Host Helpers:** Any required administrative configurations, host validation utilities, or environment parameters used by NodeAgent are pre-staged in `/etc/gdc/nodeagent/` by the post-install Ansible playbook.

### 5.9. Core GDC OCI Image Ingestion
To guarantee that GDC standalone cluster turnup can be executed completely offline, all required GDC system, control plane, and platform container images are populated into the persistent local registry mirror.
*   **Image Sources:** The specific GDC Bare Metal release container images (e.g., control plane, CNI, storage drivers, MetalLB)—whose versions are pinned at ISO compilation time—are bundled inside the ISO file structure (`/custom-data/nexus/`).
*   **Ready-Linux Ingestion:** During first boot, the automated `gdc-provision.service` Ansible playbook triggers an import task. It loads the bundled images into the host container engine, retags them, and pushes them directly into the local `gdc-docker-hosted` repository on loopback Port `5002` (authenticated via internal bootstrap credentials). This populates the local registry mirror ahead of cluster turnup.

---

## 6. Headless USB "Sneakernet" Sideloading Automation
For nodes operating on remote edge sites without direct administration networks, updates are delivered by inserting a physical USB drive containing signed updates. We automate this workflow cleanly and headlessly.

```text
  [ Operator inserts USB ]
             │
             ▼
    (Udev Rule Triggers)
             │
             ▼
  [ gdc-usb-updater.service ]
             │
             ├── 1. Verify USB crypt-signature file
             ├── 2. Mount USB to /media/gdc-update/
             ├── 3. Execute Gitea git-bundle sync
             ├── 4. Upload APT debs & OCI tars to local Nexus API
             ├── 5. Unmount USB
             │
             ▼
   [ Play Sound / Beep ] ---> (Operator removes USB safely)
```

### 6.1. The Udev Auto-Trigger Rule
A custom rule `/etc/udev/rules.d/99-gdc-usb-update.rules` detects physical storage insertion:
```text
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="GDC-UPDATE-USB", RUN+="/usr/bin/systemctl start gdc-usb-updater.service"
```

### 6.2. Headless Updater Service (`gdc-usb-updater.service`)
The triggered systemd service manages mounting, verification, synchronization, and operator signaling:

```ini
[Unit]
Description=GDC Headless USB Sideload Updater
After=gitea.service nexus.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/gdc-headless-update.sh
```

### 6.3. Headless Update Execution Script (`gdc-headless-update.sh`)
```bash
#!/usr/bin/env bash
set -euo pipefail

USB_DEV=$(blkid -L "GDC-UPDATE-USB")
MOUNT_POINT="/media/gdc-update"
logger -t gdc-usb-updater "[GOAL] Headless USB update insertion detected on ${USB_DEV}."

# 1. Mount the USB Drive
mkdir -p "${MOUNT_POINT}"
mount -o ro "${USB_DEV}" "${MOUNT_POINT}"

# 2. Cryptographic USB Integrity Check
# Verify the USB update signature against GDC's local public key
if ! openssl dgst -sha256 -verify /etc/ssl/certs/gdc-usb-signing.pem \
  -signature "${MOUNT_POINT}/update.sig" \
  "${MOUNT_POINT}/manifest.txt"; then
    logger -p user.err -t gdc-usb-updater "[FAILURE] USB update signature verification failed! Untrusted media."
    umount "${MOUNT_POINT}"
    # Sound rapid warning system beeps (Error Signal)
    echo -e "\a" > /dev/console; sleep 0.2; echo -e "\a" > /dev/console
    exit 1
fi

# 3. Synchronize Gitea Code (Git Bundle Sync)
if [[ -f "${MOUNT_POINT}/code/bootstrap-playbooks.bundle" ]]; then
    logger -t gdc-usb-updater "[GOAL] Sideloading updated Ansible playbooks to local Gitea..."
    # Local sync commands to push git bundle to localhost:3000
    git -C /tmp clone "${MOUNT_POINT}/code/bootstrap-playbooks.bundle" gdc-tmp-pull
    git -C /tmp/gdc-tmp-pull push http://127.0.0.1:3000/gdc/bootstrap-playbooks.git main:main
    rm -rf /tmp/gdc-tmp-pull
fi

# 4. Synchronize Nexus Assets (API Sideloading)
# Sideload new deb packages
if [[ -d "${MOUNT_POINT}/packages" ]]; then
    logger -t gdc-usb-updater "[GOAL] Sideloading updated APT packages to local Nexus..."
    for deb in "${MOUNT_POINT}"/packages/*.deb; do
        curl -s -u admin:password -X POST "http://127.0.0.1:8081/service/rest/v1/components?repository=gdc-apt-hosted" \
          -F "apt.asset=@${deb}"
    done
fi

# 5. Clean Unmount & Signal Operator
umount "${MOUNT_POINT}"
logger -t gdc-usb-updater "[GOAL] Headless USB update finished successfully. Safe to extract."

# Sound a single long system beep (Success Signal)
echo -e "\a" > /dev/console
exit 0
```

---

## 7. Lifecycle Update Flows (Low-Internet vs. Connected Pathways)
To maintain the node's long-term health after Stage 5 Cluster Turnup, the GDC platform supports an on-going update and maintenance loop. Operators can execute updates via two separate, standardized pathways: the **Low-Internet (Sideloaded)** option or the **Connected (Tunnel-Sync)** option. Both converge on the exact same endpoint: a fully updated host operating system and GDC platform.

```text
                                [ POST-STAGE 5 COMPLETED NODE ]
                                               │
                    ┌──────────────────────────┴──────────────────────────┐
                    ▼                                                     ▼
     [ Option A: Low-Internet Sideload ]                   [ Option B: Connected Tunnel ]
     • Acquire updated assets on workstation               • Establish secure reverse WireGuard tunnel
     • Load assets to GCS or GDC-UPDATE-USB                • Push/Pull playbooks from upstream Git
     • Sideload assets to node (Udev auto-run)             • Execute "ansible-pull" locally on node
     • Run "ansible-pull" locally on node                  • Complete safe system packages upgrade
                    │                                                     │
                    └──────────────────────────┬──────────────────────────┘
                                               ▼
                                 [ UPDATED OS & PLATFORM ]
```

### 7.1. Option A: The Low-Internet Sideload update Pathway
Designed for completely isolated, air-gapped, or bandwidth-starved edge systems. It relies on the local Service Hub (Gitea and Nexus) boundaries to ingest assets offline.

1.  **Download/Acquire Updated Assets:**
    On an internet-connected workstation, the build pipeline is executed (`remaster.sh --full`) to compile updated Ansible playbook Git bundles, latest APT `.deb` package revisions, and patched OCI container image layers.
2.  **Load Assets:**
    The generated update assets are copied onto a physical USB drive formatted with the filesystem label `GDC-UPDATE-USB` and cryptographically signed (generating `update.sig` via private GDC deployment keys), or uploaded to an authenticated Google Cloud Storage (GCS) bucket.
3.  **Sideload Assets to Machine(s):**
    *   *Physical USB Sideload:* The operator plugs the USB drive into the node's chassis. The `udev` daemon automatically triggers our headless script (`gdc-headless-update.sh`), verifying the signature and running local REST API transfers to push git bundles, OCI layers, and debs into local Gitea and Nexus.
    *   *GCS Bucket Sideload:* If the local network has restricted outbound GCS endpoints allowed, the node queries GCS directly, copying the updated assets into Gitea and Nexus.
4.  **Run Updates via Ansible Pull:**
    The local system cron triggers the `ansible-pull` executor. It connects to the updated Gitea mirror locally on port `3000`, pulls the verified playbook changes, and executes the updates on the node. Packages and containers are pulled directly from local Nexus caches on port `8081` and `5001`.

### 7.2. Option B: The Connected Tunnel Update Pathway
Designed for edge environments where a secure outbound network route exists, allowing centralized management.

1.  **Acquire Reverse Connection Tunnel:**
    The GDC node initiates a secure, outbound-only **Reverse VPN Connection Tunnel** (using WireGuard, standard GDC Connect Tunnel, or an SSH reverse socket) to the central Google Cloud / administrative gateway. This establishes a secure, private, bi-directional loopback path.
2.  **Update Ansible Repository (git pull):**
    The local Gitea service on the node leverages the reverse tunnel to execute a secure `git fetch` or `git pull` from the `UPSTREAM_PLAYBOOKS_REPO` origin, syncing the local bare repository (`bootstrap-playbooks.git`) with the latest production-approved playbook revision.
3.  **Run Updates via Ansible Pull:**
    Just as in Option A, the local `ansible-pull` cron cycles detect the new commits in the Gitea repo, execute the updated playbooks, pull packages/images through the proxy pass-thru of Nexus, and apply OS/Platform upgrades to the node.

---

## 8. Automated "Unified Nexus-First" Roadmap & Activities TODO

To implement the complete "Unified Nexus-First Ready-Linux" integration, the following activities must be completed:

- [ ] **Subiquity Bootstrap Variable Ingestion:**
  - [ ] Update `src/build/templates/user-data.j2` to write target environment parameters (including `TEMPORARY_INSTALLER_PASSWORD` and `ADMIN_SSH_PUB_KEYS`) into `/target/etc/gdc/provision.yml` during the `late-commands` stage.

- [ ] **Sonatype Nexus Dynamic Repository Bootstrapping:**
  - [ ] Implement early playbook tasks in `src/ansible/local.yml` to slurp the initial admin password from `/var/lib/nexus/sonatype-work/nexus3/admin.password` if present.
  - [ ] Reset the admin password via the Nexus REST API `PUT /service/rest/v1/security/users/admin/change-password` using the value loaded from `/etc/gdc/provision.yml`.
  - [ ] Query and record existing repositories from the GET endpoint `/service/rest/v1/repositories`.
  - [ ] Idempotently create APT hosted and proxy repositories: `gdc-apt-hosted` and `gdc-apt-proxy`.
  - [ ] Idempotently create Docker hosted (Port `5002`), proxy, and group (Port `5001`) repositories to support 100% offline cluster bootstrapping.
  - [ ] Idempotently create Raw hosted and proxy repositories for heavy ML model weights.

- [ ] **Ready-Linux Provisioning & System Hardening Expansion:**
  - [ ] Configure the local `gdc-admin` user, assign secure passwordless sudo privileges under `/etc/sudoers.d/gdc-admin`, and authorize configured administrative SSH public keys.
  - [ ] Purge redundant, heavy server packages (such as `snapd`, `lxd`, and `x11-common`) to reduce security footprint and disk utilization.
  - [ ] Run systemic offline package upgrades and installations cleanly over local Nexus proxies.

- [ ] **End-to-End QEMU Integration Verification:**
  - [ ] Run the headless E2E verification test harness `test/run_qemu_e2e.sh` to confirm the complete unattended boot, Nexus configuration, and SSH administrative assertions pass successfully.

