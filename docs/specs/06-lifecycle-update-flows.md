# Specification: GDC Lifecycle Update Flows

**Spec Identifier:** `GDC-SPEC-006`  
**Status:** APPROVED  
**Author:** GDC Disk Provisioner Security Architecture Team  

---

## 1. Executive Summary & Purpose
To maintain the security, compliance, and runtime performance of Google Distributed Cloud (GDC) edge nodes throughout their entire production lifecycles (post-Stage 5 Cluster Turnup), a standard update mechanism is required. 

This specification defines the two operational pathways supported by the GDC platform: **Stage 6A: Low-Internet Update (Offline Sideload)** and **Stage 6B: Connected Update (Reverse Tunnel)**. Both pathways are designed to safely and cryptographically sync local Gitea code registries and Nexus cached binaries, culminating in the exact same endpoint: a fully patched host operating system and GDC platform.

---

## 2. Stage 6A: Low-Internet Update (Offline Sideload)
Designed for completely isolated, air-gapped, or bandwidth-restricted remote edge nodes. It leverages local physical USB updates and automated headless triggers.

```text
 [ Operator inserts USB ]
           │
           ▼
  (Udev Rule Triggers)
           │
           ▼
[ gdc-usb-updater.service ]
           │
           ├── 1. Verify USB crypt-signature file (update.sig)
           ├── 2. Mount USB to /media/gdc-update/
           ├── 3. Execute Gitea git-bundle sync
           ├── 4. Upload APT debs & OCI tars to local Nexus API
           ├── 5. Unmount USB
           │
           ▼
 [ Play Sound / Beep ] ---> (Operator removes USB safely)
```

### 2.1. Physical Update USB Media Structure
To be recognized and processed by the node, the physical update USB drive must be formatted with the exact filesystem label **`GDC-UPDATE-USB`** and structured as follows:

```text
GDC-UPDATE-USB/ (Root)
├── manifest.txt                    # List of all files and cryptographic hashes
├── update.sig                      # Cryptographic signature of manifest.txt
├── code/
│   └── bootstrap-playbooks.bundle  # Offline Gitea Git Bundle of Ansible playbooks
├── packages/
│   └── *.deb                       # Offline debian package patches for Nexus
└── images/
    └── *.tar                       # Exported offline Docker OCI containers for Nexus
```

### 2.2. Headless Sideloading Run-Sequence & Commands
The update process executes headlessly without requiring local terminal shell access:

1.  **Udev Event Detection:**
    A custom rule `/etc/udev/rules.d/99-gdc-usb-update.rules` detects drive insertion and triggers our systemd service:
    ```text
    ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="GDC-UPDATE-USB", RUN+="/usr/bin/systemctl start gdc-usb-updater.service"
    ```
2.  **Headless Service Execution:**
    `gdc-usb-updater.service` runs the `/usr/local/bin/gdc-headless-update.sh` script, which mounts the USB read-only and validates the signature of the update bundle against GDC's local public key:
    ```bash
    openssl dgst -sha256 -verify /etc/ssl/certs/gdc-usb-signing.pem \
      -signature /media/gdc-update/update.sig \
      /media/gdc-update/manifest.txt
    ```
3.  **Local Repositories & Cache Sync:**
    If signature checks pass:
    *   **Gitea Sync:** Clones and pushes the Git playbook bundle to Gitea:
        ```bash
        git -C /tmp clone /media/gdc-update/code/bootstrap-playbooks.bundle gdc-tmp-pull
        git -C /tmp/gdc-tmp-pull push http://127.0.0.1:3000/gdc/bootstrap-playbooks.git main:main
        ```
    *   **Nexus Sync:** Pushes `.deb` files to Nexus hosted APT repo via REST API:
        ```bash
        curl -s -u admin:password -X POST "http://127.0.0.1:8081/service/rest/v1/components?repository=gdc-apt-hosted" -F "apt.asset=@/media/gdc-update/packages/wireguard.deb"
        ```
4.  **Local Ansible-Pull Trigger:**
    The local root cron job detects the updated playbooks in Gitea during its next 30-minute interval, executing the host and system upgrades offline.

---

## 3. Stage 6B: Connected Update (Reverse Tunnel)
Designed for edge installations possessing a secure outbound network route, allowing centralized, automated management from central cloud endpoints.

```text
               [ GDC NODE ]                                [ GCP ADMINISTRATIVE GATEWAY ]
                    │                                                     │
                    │ 1. Establishes outbound WireGuard tunnel            │
                    ├────────────────────────────────────────────────────>│
                    │                                                     │
                    │ 2. Local Gitea mirror fetches playbook updates      │
                    │    (git pull over secure tunnel path)               │
                    |<====================================================│
                    │                                                     │
                    │ 3. local ansible-pull cron triggers, applies        │
                    │    upgrades, and pulls OCI/debs via Nexus proxies   │
                    │                                                     │
```

### 3.1. Reverse Tunnel Establishment
The GDC node initiates a secure, outbound-only **Reverse VPN Tunnel** (e.g. via WireGuard or GDC Connect agents) to GGD's central cloud administrative gateway:
*   Because the connection is outbound-only, it requires no local open firewall ports or static IP routing setups on the edge node.
*   Once established, the tunnel exposes a secure loopback path allowing authorized central controllers to tunnel back to the node.

### 3.2. Automated Sync & Execution
1.  **Gitea Fetch:** The Gitea persistent daemon is configured with a background pull-mirror task. Over the secure VPN tunnel, Gitea periodically runs `git fetch` against GGD's production `UPSTREAM_PLAYBOOKS_REPO`.
2.  **Ansible-Pull Playbook Execution:** The local cron daemon detects the Gitea repo's commits, executes `ansible-pull`, and applies host configuration changes.
3.  **Proxy Cache Upgrades:** Any upgraded system packages or OCI images are pulled through Nexus's proxy ports, automatically caching them offline for other cluster spokes.

---

## 4. Diagnostic Audio Indicators (Local Operator Feedback)
Since edge nodes are booted headlessly and updates execute without a screen, the update script utilizes the server's internal PC Speaker (`beep` / `/dev/console` write) to output clear diagnostic signals to the physical operator:

*   **Error Signal (Two Rapid, Loud Beeps):**
    *   *Triggers on:* Signature verification failure (untrusted USB) or directory copy crash.
    *   *Frequency:* 400Hz, duration 0.2s, pause 0.2s.
    *   *Operator Action:* Do NOT remove USB. Connect serial console to check `/var/log/syslog` for `[GDC-INSTALL-FAIL]` diagnostic details.
*   **Success Signal (One Long, High-Pitch Beep):**
    *   *Triggers on:* Completed Gitea and Nexus synchronization, clean drive unmount.
    *   *Frequency:* 800Hz, duration 1.0s.
    *   *Operator Action:* Update complete. Safe to extract GDC-UPDATE-USB.
