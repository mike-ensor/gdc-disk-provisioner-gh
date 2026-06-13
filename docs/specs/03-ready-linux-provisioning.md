# Specification: GDC Ready-Linux Provisioning & Sideloading Interface

**Spec Identifier:** `GDC-SPEC-003`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Security Architecture Team  

---

## 1. Executive Summary & Purpose
This specification details the transition from a freshly installed baseline OS to a fully hardened, secure "Ready-Linux" node. It governs administrative profiles, persistent Service Hub boundaries (Gitea and Nexus), and advanced hardware security (TPM 2.0). 

Additionally, it specifies the standard **GDC Offline Sideloading Interface**, detailing how operators apply offline code, binary, and container updates via local API pushes or headless USB "Sneakernet" media syncs. This is backed by cryptographic verification standards (GPG and Sigstore/Cosign) to prevent rogue code execution.

---

## 2. The First-Boot Migration & Service Transition

### 2.1. Late-Command Sync Script & Space Guardrails
During Subiquity's `late-commands`, the pre-loaded Gitea repositories, systemd units, and Nexus cache directories are cloned from the read-only ISO media (`/cdrom/custom-data/`) to the persistent logical volumes mounted under `/target/`.

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
ExecStart=/usr/bin/ansible-pull \
  -U http://127.0.0.1:3000/gdc/bootstrap-playbooks.git \
  -i localhost, \
  --verify-commit \
  local.yml
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
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
To prevent unauthorized playbook execution, `ansible-pull` is executed with the `--verify-commit` flag.
*   **Enforcement:** The local Git configuration inside the target OS is locked to verify commit signatures against GDC's pre-loaded GPG public keyring stored in `/etc/gpg/gdc-release.gpg`.
*   Unsigned commits or commits signed by untrusted keys are instantly rejected, aborting playbook runs before host modifications can execute.

### 4.2. Cosign OCI Image Verification (Nexus Proxy)
Container images sideloaded into Nexus (`gdc-docker-hosted`) or cached via proxy are signed using **Sigstore/Cosign**.
*   **Enforcement:** Before the local Kubernetes Kubelet or containerd runtime extracts and deploys an OCI container image, a admission webhook (e.g. Policy Controller / Kyverno) intercepts the request and verifies the signature using the local GDC public key:
    ```bash
    cosign verify --key /etc/cosign/gdc-k8s-signing.pub localhost:5001/gdc/my-image:latest
    ```
*   Unsigned container layers or signature mismatches abort the Pod deployment, preventing arbitrary image executions.

---

## 5. Playbook Tasks: Ready-Linux Configuration

### 5.1. Administrative User Setup
* Creates the system user `gdc-admin`.
* Drops administrative sudo permissions securely under `/etc/sudoers.d/gdc-admin` utilizing passwordless parameters:
  ```text
  gdc-admin ALL=(ALL) NOPASSWD:ALL
  ```

### 5.2. TPM 2.0 Cryptographic Binding & Automated Boot-Unlocking
*   **Action:** Registers and seals LUKS storage decryption keys to the hardware TPM 2.0 chip using Platform Configuration Registers (PCRs) `0` (Firmware), `2` (PCI Configurations), and `7` (Secure Boot State).
*   **Unlocking Config:** Writes target `/etc/crypttab` pointing to `tpm2-device=auto,discard`.
*   **Cleanup:** Generates an escrow LVM recovery passphrase, wipes the temporary bootstrap password from metadata keyslots, and purges temporary files.

### 5.3. Remote Attestation & Cloud-Validated Device Identity
*   **Handshake:** Generates an Attestation Key (AK) and takes a TPM PCR boot quote signed with a dynamic cloud-challenge nonce.
*   **TLS Enrollment:** Requests GDC Device TLS identity certificates from GCP Cloud CAs using an un-extractable RSA private key generated inside the TPM's secure PKCS#11 enclave.

### 5.4. CIS Hardening and OS Slimming
*   Applies CIS Benchmark Level 2 controls (SSH limits, FIPS ciphers, auditd, and sysctl controls).
*   Purges `snapd`, compiler runtimes, and unnecessary baseline GUI tools.

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
