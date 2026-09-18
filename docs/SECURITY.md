# Google Distributed Cloud (GDC) Hardware & Software Security Architecture

This document specifies the multi-layered security protections, cryptographic signing verification standards, and hardware-bound root of trust configurations implemented across GDC provisioning nodes.

---

## 1. Supply Chain & Compilation Protection

Security begins at the ISO compilation stage to prevent malicious payload injections:

* **Cryptographic Checksumming:** To secure third-party binary dependencies (such as Gitea and Sonatype Nexus), the build pipeline (`remaster.sh`) implements strict SHA-256 cryptographic verification. Every binary is matched against a hardcoded list of verified hashes before workspace staging:
  ```bash
  GITEA_EXPECTED_SHA="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  GITEA_ACTUAL_SHA=$(sha256sum "${CACHE_DIR}/gitea" | cut -d' ' -f1)
  if [[ "${GITEA_ACTUAL_SHA}" != "${GITEA_EXPECTED_SHA}" ]]; then
      exit 1 # Abort immediately on mismatched hash
  fi
  ```
* **Non-Root Workspace Assembly:** Standard loopback mounting requires root administrative `sudo` privileges, which are highly restricted on secure CI/CD runners. We isolate our build environment by using `xorriso`'s non-privileged extraction and repackaging layer (`-osirrox on -extract`), eliminating the need for system privileges.
* **SquashFS Isolation:** To ensure rapid and secure repackaging cycles, the base system SquashFS (`filesystem.squashfs`) is left completely untouched. Custom configurations, Gitea repositories, and Nexus package bundles reside on the uncompressed *outer* ISO directory (`/custom-data/`), keeping the boot kernel isolated from customization tasks.

---

## 2. Dynamic Secret Protection & TPM 2.0 Binding

Baking static credentials, admin passwords, or private key pairs onto a bootloader ISO is a major vulnerability. We enforce a dynamic, hardware-sealed secret lifecycle:

### A. One-Time Passcode & Key Transition (Gap 2.1)
* **Installation Stage:** The disk layout is encrypted with dm-crypt LUKS using a baseline temporary passcode.
* **Late-Commands Stage:** The installer generates a one-time random transition key file `/target/etc/keys/temp_key.key` (permission `400`), registers it into a free LUKS slot on the physical device, and configures `/target/etc/crypttab` to read this key file to allow a passwordless first reboot.
* **Reboot Stage:** The target operating system boots passwordlessly, unlocks the volume group, and launches the first-boot `ansible-pull` provisioner.

### B. Hardware TPM 2.0 Sealing (Secure Boot)
Once booted, the Ansible playbook executes `systemd-cryptenroll` to permanently seal the storage decryption keys directly to the host's physical motherboard TPM 2.0 chip:
1. **PCR Register Sealing:** The LUKS keyslot is sealed to PCR registers `0` (Firmware) and `7` (Secure Boot State) to ensure boot stability while retaining robust cryptographic verification:
   ```bash
   systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=0+7 /dev/nvme0n1p3
   ```
2. **Insecure Slot Purge:** The playbook updates `/etc/crypttab` with the flag `tpm2-device=auto,discard`, **permanently deletes the temporary key `/etc/keys/temp_key.key`**, and runs `systemd-cryptenroll --wipe-slot=password` to wipe the baseline installation password.
3. **Security Outcome:** The system can now only boot on the original motherboard with an unmodified, untampered Secure Boot configuration. If the drive is stolen or Secure Boot is bypassed, the disk remains cryptographically locked.

*(For a comprehensive, non-technical and technical walkthrough of TPM 2.0 hardware attestation, EKCert verification, and mTLS integration with GDC Companion, refer to [`docs/TPM_ATTESTATION_AND_MTLS.md`](TPM_ATTESTATION_AND_MTLS.md).)*

---

## 3. Cryptographic Sideload Verification

In air-gapped environments, standard online certificate revocation lists (CRLs) are unavailable. We enforce strict, localized cryptographic verification on all sideloaded payloads:

```text
                [ SIDELOADED PAYLOAD ]
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   [ Git Commits ]   [ APT Packages ]   [ Docker Images ]
    • GPG Keyring     • GPG Signature    • Cosign Keys
         │                 │                 │
         ▼                 ▼                 ▼
   Verify Commit     Verify Release     Verify cosign
    Against Node      Against Local      Against GDC
    GPG Keyring       Apt Keyring        Public Key
```

### A. GPG Commit Signatures (`ansible-pull`)
To prevent malicious playbook injection on edge nodes, GPG commit signing is enforced in production mode (`ENFORCE_SIGNED_COMMITS=true` in `build.env`):
* `ansible-pull` is executed with the `--verify-commit` flag.
* The local Git engine on the target OS is locked to verify commit signatures against GDC's pre-loaded GPG public keyring stored in `/etc/gpg/gdc-release.gpg`. Unsigned commits are immediately rejected, aborting playbook runs.

### B. Cosign OCI Container Verification
All container images cached or pushed to the local Nexus Docker registry (Port `5001`) are cryptographically verified using **Sigstore/Cosign** before extraction:
* An admission webhook intercepts Kubernetes container creation requests and asserts image signature validity against the GDC node's public key store:
  ```bash
  cosign verify --key /etc/cosign/gdc-k8s-signing.pub localhost:5001/gdc/my-image:latest
  ```
* Unsigned layers or signature mismatches abort deployment instantly, blocking execution of arbitrary binaries.

---

## 4. Operating System Hardening & Slimming

Once the post-install Ansible playbook executes successfully, the node transitions to an immutable, hardened state:

* **CIS Level 2 Benchmark Controls:** Applies rigorous operating system policies, including SSH connection limits, FIPS-compliant cryptographic ciphers, systemd audit rules (`auditd`), and strict `sysctl` kernel parameters.
* **Snapd & Bloat Purging:** Explicitly purges Ubuntu's package daemon (`snapd`), unneeded compilers, development environments, and standard display interfaces, reducing the system attack surface and storage footprint.
* **TPM SSH Host Keys:** Enslaves host SSH keys to the motherboard's secure cryptoprocessor using `ssh-tpm-agent`, ensuring the node's private SSH identity keys can never be cloned or exported.

## 5. Keyless Profile Authentication (GCP / gcloud)

To prevent baking static GCP Service Account JSON keys to disk (where they could be extracted from a compromised node), the GDC node uses a **Keyless Profile** for `gcloud` and Application Default Credentials (ADC). 

During cluster turnup, the node securely requests a short-lived OAuth 2.0 access token from the GDC Companion over mTLS. A local STS (Security Token Service) Proxy running as a background service (`gdc-sts-proxy.service`) serves this volatile token to the GCP SDKs.

### Manual Authentication (Disconnected Node)

If a node does **not** have access to the GDC Companion to receive the dynamic bearer token (e.g., in an air-gapped lab or during a network outage), the automated STS proxy will fail, and GCP commands will return `403 Access Denied` or `No credentialed accounts`.

To bypass the STS proxy and manually authenticate the machine using standard credentials, you must temporarily override the custom external account environment variables set in `/etc/profile.d/gdc-adc.sh`:

1.  **Unset the custom ADC variables in your current shell:**
    You can use the built-in alias to instantly unset them for your current session:
    ```bash
    gdc-adc-disable
    ```
    *(Alternatively, manually run `unset GOOGLE_APPLICATION_CREDENTIALS GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES`).*

    **Permanent Override (Optional):** If you want to disable the STS proxy injection permanently across all logins, you can touch a flag file:
    ```bash
    sudo touch /etc/gdc/manual_adc_override
    ```

2.  **Authenticate the gcloud CLI (headless):**
    ```bash
    gcloud auth login --no-browser
    ```
    *(Follow the on-screen instructions to paste the verification URL into a local browser, authenticate, and paste the code back into the terminal).*

3.  **Authenticate Application Default Credentials (ADC):**
    ```bash
    gcloud auth application-default login --no-browser
    ```

*(Note: The custom `GOOGLE_APPLICATION_CREDENTIALS` environment variables will be restored automatically upon the next SSH login or reboot, but your manual `~/.config/gcloud/` credentials will persist until explicitly revoked or wiped).*
