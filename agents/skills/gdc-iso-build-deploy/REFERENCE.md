# GDC ISO Build & Deploy Reference

This file documents the environment parameters, cloud storage structures, partition layouts, and API endpoints of the GDC custom bootstrap pipeline.

---

## 1. Required Workspace Environment Variables

Before triggering any build steps, ensure the local `.envrc` or shell has these variables exported:

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `PROJECT_ID` | GCP Project ID hosting GCS and Artifact Registry | `gdc-prod-host` |
| `BUILD_VERSION` | Version of the custom Docker `iso-builder` container | `1.0.0` |
| `REGION` | GCP Region where images and GCS buckets are co-located | `us-central1` |
| `ISO_VERSION` | Current Semantic version tag of the output ISO | `1.0.2` (auto-incremented on builds) |

---

## 2. Google Cloud Storage (GCS) Structure

The GCS bucket is used both for caching inputs and storing release outputs.

* **Raw Base/Blessed Image Location:**
  `gs://<BUCKET_NAME>/source/ubuntu-24.04-live-server-amd64.iso`
  *Note: Ensure this is uploaded first to prevent slow internet fetches during CI runs.*
* **Active ISO Distribution Directory:**
  `gs://<BUCKET_NAME>/sync/gdc-bootstrap-ubuntu-24.04-v<ISO_VERSION>.iso`
* **Retention Policy & Cleanup:**
  * The `publish-and-promote` build stage restricts the `sync/` directory to the **last 5 compiled ISOs**.
  * Any older ISO files are moved to `gs://<BUCKET_NAME>/archived/` using `gcloud storage mv`.

---

## 3. Bootimus PXE Server Configuration

Bootimus manages headless OS network-boot parameters on target bare-metal machines.

* **API Endpoints:**
  * API Base: `http://<BOOTIMUS_API_HOST>:<BOOTIMUS_API_PORT>/api`
  * HTTP Assets: `http://<BOOTIMUS_API_HOST>:<BOOTIMUS_HTTP_PORT>/isos`
  * Default Host IP: `192.168.254.12`
  * Default Ports: `26000` (API), `16000` (HTTP assets)
* **Authentication:**
  * Relies on `BOOTIMUS_USER` and `BOOTIMUS_PASS` in the environment.
  * If missing, the helper script automatically performs an Infisical secrets query for `bootimus_creds`.

### Custom Autoinstall Kernel Parameters (Self-Healed)
Bootimus must serve the following parameters to the network booting machines to automate Subiquity:
```text
boot=casper initrd=initrd ip=dhcp netboot=url url=http://<IP>:<PORT>/isos/<ISO> root=/dev/ram0 ramdisk_size=4500000 autoinstall ds=nocloud-net;s=http://<IP>:<PORT>/isos/<ISO_FOLDER>/iso/nocloud/
```

---

## 4. Enterprise LVM Partition Layout Specs

When bare-metal target nodes boot the custom ISO, the automated installer initializes local disks according to the following layout:

* **Physical Partitions:**
  * `/boot/efi`: `1 GiB` (FAT32)
  * `/boot`: `2 GiB` (EXT4)
* **Volume Group:** `vg_system`
* **Logical Volumes:**
  * `lv_root`: Root operating system
  * `lv_var`: Persistent service states
  * `lv_var_log`: Isolated log storage
  * `lv_var_opt_metrics`: Core performance metrics
  * `lv_containerd`: Isolated Containerd namespace
  * `lv_etcd` & `lv_etcd_events`: Dedicated high-IOPS write volumes
  * `lv_gitea` & `lv_nexus`: Standalone offline repositories
  * `lv_local_disk`: Local cluster ephemeral disk storage (capped at `100 GiB`)
  * `lv_sds`: Software Defined Storage / Distributed block pool (allocates remaining raw disk capacity)

---

## 5. Hardware Hardening (TPM 2.0 & Cryptenroll)

* Custom ISO automates **LUKS disk decryption binding** to target system hardware.
* Decryption keys are bound using `systemd-cryptenroll` to Platform Configuration Registers (PCR) `0+7` (Firmware + Secure Boot state).
* Target `/etc/crypttab` is updated with `tpm2-device=auto` to bypass passcodes on authorized boot paths.
