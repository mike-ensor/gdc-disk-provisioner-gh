# Specification: GDC Installation Sequence, Timeline, & Transition Gaps

**Spec Identifier:** `GDC-SPEC-002-SEQ`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Security Architecture Team  

---

## 1. Step-by-Step Sequence of Operations & Timeline
The entire bootstrapping lifecycle spans approximately **16 minutes** from bare-metal cold boot to fully hardened Ready-Linux state. Below is the precise operational timeline:

```text
TIME (MIN)   PHASE                         ACTIONS EXECUTED
─────────────────────────────────────────────────────────────────────────────────────────────
T = 0.0m     BIOS/UEFI Boot Phase         • Node powers on, reads custom GRUB EFI boot loader.
                                          • Custom Kernel & Initramfs load with parameters:
                                            "autoinstall ds=nocloud;s=/cdrom/nocloud/ ip=dhcp"
                                          • systemd initializes RAM tmpfs filesystem.

T = 1.0m     Live Service Hub Phase       • systemd starts live Gitea (port 3000) & Nexus (8081)
                                            listening on loopback 127.0.0.1 in RAM overlayfs.
                                          • Nexus initializes pre-seeded repositories, including the
                                            Docker Group Repository aggregating hosted (local versioned
                                            OCI images) and proxy-cache endpoints.
                                          • Subiquity installer launches.

T = 2.0m     LVM Partitioning Phase       • Subiquity matches the largest SSD (e.g. /dev/nvme0n1).
                                          • Allocates physical efi (1G), boot (2G), & lvm (remainder) partitions.
                                          • Runs `cryptsetup luksFormat /dev/nvme0n1p3` using the
                                            temporary bootstrap passcode.
                                          • Creates Volume Group vg_system and formats logical volumes.

T = 5.0m     OS Writing Phase             • Subiquity writes core Ubuntu 24.04 image into /dev/mapper/lv_root.
                                          • Sets target's /etc/fstab with optimized mount barriers (commit=1).
                                          • APT pulls standard updates offline from live Nexus proxy port 8081.

T = 12.0m    Late-Command Migration       • Subiquity late-commands copy persistent configurations, Gitea
                                            repositories, and Nexus caches to their respective persistent
                                            LVM partitions (lv_gitea and lv_nexus).
                                          • The Nexus cache holds the entire pre-seeded OCI library:
                                            all Cluster (Kubernetes), Platform, and Application container
                                            images with their exact version tags defined at ISO creation.
                                          • Copies Gitea, Nexus, and `gdc-provision.service` systemd units.
                                          • Writes a temporary, un-checked keyfile /boot/temp_key.key and
                                            maps it in /etc/crypttab to allow one-time passwordless boot.
                                          • Rebuilds target ramdisks: `update-initramfs -u -k all`.
                                          • Installation completes, node restarts.

T = 14.5m    Target OS First Boot         • Node boots on physical target drive.
                                          • target initramfs reads /boot/temp_key.key, unlocks LUKS, maps vg_system.
                                          • Gitea & Nexus persistent daemons launch on localhost.
                                          • `gdc-provision.service` executes `ansible-pull`.

T = 15.0m    Ansible Self-Test & Sync     • Playbooklocal.yml blocks until Gitea (3000) & Nexus (8081) are up.
                                          • Runs Hello World, prints lsblk partitions, and logs ping 8.8.8.8.
                                          • Pulls GDC deployment playbooks.

T = 16.0m    TPM-Sealing & Finalization   • Ansible executes `systemd-cryptenroll --tpm2-device=auto`
                                            to seal LUKS to hardware registers PCR 0+2+7 (Secure Boot).
                                          • Rewrites /etc/crypttab to "tpm2-device=auto,discard" and
                                            erases temporary key /boot/temp_key.key and password slots.
                                          • Generates TPM-bound SSH host keys and requests Device Identity CA Certs.
                                          • Performs CIS Level 2 hardening and purges snapd bloat.
                                          • Writes "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" to ttyS0.
                                          • Node enters immutable Ready-Linux state.
─────────────────────────────────────────────────────────────────────────────────────────────
```

---

## 2. Analysis of Overlapping Issues & Transition Gaps

### Gap 2.1: The Boot-Unlock "Chicken-and-Egg" Transition
*   **The Threat:** You cannot enroll a LUKS partition to the TPM 2.0 chip during the Subiquity installation phase because Subiquity executes in a generic chroot environment without active access to the physical TPM device drivers and systemd-cryptenroll services on the target.
*   **The Overlap:** The disk must be encrypted during install, but it must boot once passwordlessly to run the first-boot Ansible playbook which does the TPM enrollment.
*   **The Resolution:** 
    1. During installation, Subiquity encrypts the drive using a baseline temporary passcode.
    2. In `late-commands`, the installer creates a one-time keyfile `/target/boot/temp_key.key` and configures `/target/etc/crypttab` to read this keyfile during early boot.
    3. The node reboots, automatically decrypting via the local file, and launches the first-boot `ansible-pull` service.
    4. The Ansible playbook executes `systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=0+2+7`, sealing the LUKS slot to the hardware TPM chip.
    5. The playbook rewrites `/etc/crypttab` with the `tpm2-device=auto` flag, **deletes `/boot/temp_key.key`**, and runs `systemd-cryptenroll --wipe-slot=password` to erase the temporary password.
    6. *Vulnerability Closed:* The node can now only boot on the physical motherboard with an un-tampered Secure Boot configuration.

### Gap 2.2: Race Conditions between Gitea/Nexus Start and `ansible-pull`
*   **The Threat:** On first boot, the systemd process manager launches `gdc-provision.service` (which executes `ansible-pull`) in parallel with the Gitea and Nexus startup scripts. Since Nexus (Java JVM-based) takes 30-45 seconds to initialize its database and bind to port 8081, `ansible-pull` will crash immediately on connection refused.
*   **The Resolution:** We introduce a service dependency handshake within our Ansible playbooks (`local.yml`). The very first tasks execute a localized wait-for-port loop:
    ```yaml
    - name: Wait for local Gitea Service Hub (Port 3000)
      ansible.builtin.wait_for:
        host: 127.0.0.1
        port: 3000
        state: started
        timeout: 60

    - name: Wait for local Nexus Service Hub (Port 8081)
      ansible.builtin.wait_for:
        host: 127.0.0.1
        port: 8081
        state: started
        timeout: 90
    ```
    This holds playbook execution safely in memory until the Service Hub boundaries are listening and healthy.

### Gap 2.3: Serial Console Logger Deadlocks
*   **The Threat:** If a script writes a success token to `/dev/ttyS0` but no serial connection is listening on the host hypervisor, the write command can block indefinitely under standard TTY flow control.
*   **The Resolution:** We wrap the success signaling in a non-blocking shell loop:
    ```bash
    # Non-blocking write to serial port with a 3-second timeout fallback
    timeout 3 sh -c 'echo "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" > /dev/ttyS0' || true
    ```
