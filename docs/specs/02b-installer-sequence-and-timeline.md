# Specification: GDC Installation Sequence, Timeline, & Transition Gaps

**Spec Identifier:** `GDC-SPEC-002-SEQ`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Security Architecture Team

---

## 1. Step-by-Step Sequence of Operations & Timeline
The entire bootstrapping lifecycle spans approximately **16 minutes** from bare-metal cold boot to fully hardened Ready-Linux state. Below is the precise operational timeline:

```text
TIME (MIN)   PHASE                         ACTIONS EXECUTED
15: ─────────────────────────────────────────────────────────────────────────────────────────────
16: T = 0.0m     BIOS/UEFI Boot Phase         • Node powers on, reads custom GRUB EFI boot loader.
17:                                           • Custom Kernel & Initramfs load with parameters:
18:                                             "autoinstall ds=nocloud;s=/cdrom/nocloud/"
19:                                           • systemd initializes RAM tmpfs filesystem.
20: 
21: T = 1.0m     Live Service Hub Phase       • systemd starts live Gitea (port 3000) & Nexus (8081)
22:                                             listening on loopback 127.0.0.1 in RAM overlayfs.
23:                                           • Nexus initializes pre-seeded repositories, including the
24:                                             Docker Group Repository aggregating hosted (local versioned
25:                                             OCI images) and proxy-cache endpoints.
26:                                           • Subiquity installer launches.
27: 
28: T = 2.0m     LVM Partitioning Phase       • Subiquity matches the largest SSD (e.g. /dev/nvme0n1).
29:                                           • Early-commands detect disks & generate autoinstall LVM maps.
30:                                           • Runs `cryptsetup luksFormat /dev/nvme0n1p3` using the
31:                                             temporary bootstrap passcode.
32:                                           • Creates Volume Group vg_system and formats logical volumes.
33: 
34: T = 5.0m     OS Writing Phase             • Subiquity writes core Ubuntu 24.04 image into /dev/mapper/lv_root.
35:                                           • Sets target's /etc/fstab with optimized mount barriers (commit=1).
36:                                           • APT pulls standard updates offline from live Nexus proxy port 8081.
37: 
38: T = 12.0m    Late-Command Migration       • Subiquity late-commands copy persistent configurations, Gitea
39:                                             repositories, and Nexus caches to their respective persistent
40:                                             LVM partitions (lv_gitea and lv_nexus).
41:                                           • The Nexus cache holds the entire pre-seeded OCI library:
42:                                             all Cluster (Kubernetes), Platform, and Application container
43:                                             images with their exact version tags defined at ISO creation.
44:                                           • Copies Gitea, Nexus, and `gdc-provision.service` systemd units.
45:                                           • Writes a temporary, un-checked keyfile /boot/temp_key.key and
46:                                             maps it in /etc/crypttab to allow one-time passwordless boot.
47:                                           • Rebuilds target ramdisks: `update-initramfs -u -k all`.
48:                                           • Installation completes, node restarts.
49: 
50: T = 14.5m    Target OS First Boot         • Node boots on physical target drive.
51:                                           • target initramfs reads /boot/temp_key.key, unlocks LUKS, maps vg_system.
52:                                           • Gitea & Nexus persistent daemons launch on localhost.
53:                                           • `gdc-provision.service` executes `ansible-pull`.
54: 
55: T = 15.0m    Ansible Self-Test & Sync     • Playbooklocal.yml blocks until Gitea (3000) & Nexus (8081) are up.
56:                                           • Runs Hello World, prints lsblk partitions, and logs ping 8.8.8.8.
57:                                           • Pulls GDC deployment playbooks.
58: 
59: T = 16.0m    TPM-Sealing & Finalization   • Ansible executes `systemd-cryptenroll --tpm2-device=auto`
60:                                             to seal LUKS to hardware registers PCR 0+7 (Secure Boot).
61:                                           • Rewrites /etc/crypttab to "tpm2-device=auto,discard" and
62:                                             erases temporary key /boot/temp_key.key and password slots.
63:                                           • Generates TPM-bound SSH host keys and requests Device Identity CA Certs.
64:                                           • Performs CIS Level 2 hardening and purges snapd bloat.
65:                                           • Writes "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" to ttyS0.
66:                                           • Node enters immutable Ready-Linux state.
67: ─────────────────────────────────────────────────────────────────────────────────────────────
```

---

## 2. Integration with Overarching Machine States State Machine

The GDC bootstrapping process integrates with the official 8-phase sequential state machine to ensure hardware, software, and cluster-readiness are verified and locked before proceeding.

```text
                               ┌───────────────────────────┐
                               │     Phase 1: LiveCD       │
                               │  (Runs in RAM from ISO)   │
                               └─────────────┬─────────────┘
                                             │ (Subiquity complete)
                                             ▼
                               ┌───────────────────────────┐
                               │   Phase 2: First Boot     │
                               │  (Disk-based, Hubs Setup) │
                               └─────────────┬─────────────┘
                                             │ (TPM sealed / Reboot)
                                             ▼
                               ┌───────────────────────────┐
                               │   Phase 3: Second Boot    │
                               │ (Auto-Unlock Validation)  │
                               └─────────────┬─────────────┘
                                             │ (TPM unseal PASS)
                                             ▼
                               ┌───────────────────────────┐
                               │   Phase 4: Linux Ready    │
                               │ (Hardening & Optimizations)│
                               └─────────────┬─────────────┘
                                             │ (Verify Ansible PASS)
                                             ▼
                               ┌───────────────────────────┐
                               │   Phase 5: Cluster Ready  │
                               │ (Companion API & Gating)  │
                               └───────────────────────────┘
```

### 2.1. Phase 1: LiveCD State
*   **Execution Boundary:** Spans from initial BIOS/UEFI boot ($T = 0.0\text{m}$) up to the execution of `late-commands` and the immediate reboot trigger ($T = 12.0\text{m}$).
*   **Environment:** The operating system runs entirely in-memory from a transient RAM-backed `overlayfs` created by the Ubuntu Live Casper boot system. All filesystem changes are lost upon reboot.
*   **Service Profile:** Local boundary service hubs (Gitea and Sonatype Nexus) are **inactive** and not running in RAM.
*   **Core Outcomes:** Completes hardware discovery, generates LVM partition maps, formats encrypted LUKS volumes, writes the base OS, copies persistent Gitea/Nexus blobs, and triggers a clean hardware restart.

### 2.2. Phase 2: First Boot State
*   **Execution Boundary:** Spans from the first boot on the target physical drive ($T = 14.5\text{m}$) up to the completion of initial Ansible playbooks and the first state reboot trigger ($T = 16.0\text{m}$).
*   **Environment:** The operating system runs permanently on the physical target block devices (`vg_system-lv_root` etc.).
*   **Service Profile:** Gitea (port 3000) and Nexus (port 8081) daemons are started automatically by systemd.
*   **Core Outcomes:** Unlocks LUKS on boot using the one-time `/boot/temp_key.key` file, starts `gdc-provision.service`, and runs `ansible-pull`. Ansible executes TPM 2.0 cryptographic sealing of the LUKS container, erases `/boot/temp_key.key`, and triggers a controlled reboot to verify auto-unlocking.

### 2.3. Phase 3 & 4: Second Boot & Linux Ready State
*   **Execution Boundary:** Spans from the second boot on the target drive up to the completion of host hardening and system optimization.
*   **Environment:** Permanent operating system running on physical SSD, auto-unlocked cleanly via systemd-cryptenroll/TPM 2.0.
*   **Core Outcomes:** Verifies that the system booted completely headless without a password (TPM successful), runs best-practice system modifications, applies CIS Level 2 hardening, purges Snapd/LXD packages, and compiles the final `linux-ready` verification files.

### 2.4. Phase 5: Cluster Ready State
*   **Execution Boundary:** Queries the GDC Companion API (`GET /v1/machine-info/{mac}`) using mTLS client certificates, maps peer directories, configures `/etc/hosts`, and starts the gated `node-agent` daemon. This marks the transition to Stage 5 Cluster Turnup.

---

## 3. Analysis of Overlapping Issues & Transition Gaps

### Gap 3.1: The Boot-Unlock "Chicken-and-Egg" Transition
*   **The Threat:** You cannot enroll a LUKS partition to the TPM 2.0 chip during the Subiquity installation phase because Subiquity executes in a generic chroot environment without active access to the physical TPM device drivers and systemd-cryptenroll services on the target.
*   **The Overlap:** The disk must be encrypted during install, but it must boot once passwordlessly to run the first-boot Ansible playbook which does the TPM enrollment.
*   **The Resolution:** 
    1. During installation, Subiquity encrypts the drive using a baseline temporary passcode.
    2. In `late-commands`, the installer creates a one-time keyfile `/target/boot/temp_key.key` and configures `/target/etc/crypttab` to read this keyfile during early boot.
    3. The node reboots, automatically decrypting via the local file, and launches the first-boot `ansible-pull` service.
    4. The Ansible playbook executes `systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=0+7`, sealing the LUKS slot to the hardware TPM chip.
    5. The playbook rewrites `/etc/crypttab` with the `tpm2-device=auto` flag, **deletes `/boot/temp_key.key`**, and runs `systemd-cryptenroll --wipe-slot=password` to erase the temporary password.
    6. *Vulnerability Closed:* The node can now only boot on the physical motherboard with an un-tampered Secure Boot configuration.

### Gap 3.2: Race Conditions between Gitea/Nexus Start and `ansible-pull`
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

### Gap 3.3: Serial Console Logger Deadlocks
*   **The Threat:** If a script writes a success token to `/dev/ttyS0` but no serial connection is listening on the host hypervisor, the write command can block indefinitely under standard TTY flow control.
*   **The Resolution:** We wrap the success signaling in a non-blocking shell loop:
    ```bash
    # Non-blocking write to serial port with a 3-second timeout fallback
    timeout 3 sh -c 'echo "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" > /dev/ttyS0' || true
    ```
