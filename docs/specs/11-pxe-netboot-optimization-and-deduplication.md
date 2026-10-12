# GDC-SPEC-011: PXE Netboot Optimization and Multi-Download Elimination

**Spec Identifier:** `GDC-SPEC-011`  
**Status:** PROPOSED  
**Author:** GDC Disk Provisioner Architecture Team & opencode  
**Related Specs:** `GDC-SPEC-002-SEQ`, `GDC-SPEC-010`

---

## 1. Executive Summary

During automated bare-metal provisioning of multi-node GDC clusters (e.g., 5 nodes booted concurrently), target nodes experience significant network boot bottlenecks and delay. Telemetry gathered from the Bootimus PXE server (`automation` / `192.168.254.12`) revealed that each node downloads the ~5.5 GB bootstrap ISO (`gdc-bootstrap-ubuntu-24.04-v0.7.1-debug.iso`) **two to three times in succession** over HTTP before completing OS installation.

For a 5-node cluster, this results in **55 GB to 82.5 GB of aggregate network transfer**, exhausting the 1 Gbps link capacity of the PXE host, saturating the host's memory page cache, causing storage I/O thrashing against the upstream NFS ISO share, and inflating node turn-up times from under 3 minutes to over 20 minutes.

This specification documents the exact root causes of this duplicate download behavior in the Ubuntu 24.04 / Casper / Subiquity stack and outlines actionable remediation strategies to eliminate redundant downloads while strictly preserving the **core GDC design constraint: a single, fully baked, airgapped ISO artifact** that can boot disconnected without external shared filesystem infrastructure.

---

## 2. Telemetry & Problem Statement

### 2.1 Observed Behavior
During a concurrent 5-node PXE boot session:
1. **Node Connections:** 5 servers (`192.168.9.234`, `.235`, `.241`, `.242`, `.246`) booted via iPXE.
2. **Phase 1 (Casper initramfs):** All nodes fetched `vmlinuz` (14 MB) and `initrd` (70 MB), then initiated HTTP downloads of the full 5,503 MB ISO.
3. **Phase 2 (Immediate Re-download):** Within 3 to 4 seconds of completing the first 5.5 GB download, each client established a new TCP connection on port `16000` and started downloading the **exact same 5.5 GB ISO a second time**.
4. **Phase 3 (Subiquity Extract):** Certain nodes triggered a **third download** before fetching `meta-data` and `user-data` from `ds=nocloud-net`.

### 2.2 Host Resource Impact (`automation` - Raspberry Pi 4)
- **Network Interface (`eth0` - 1 Gbps Full Duplex):**
  - **TX (HTTP to Clients):** ~650 Mbps
  - **RX (NFS read from `storage.ensor-labs.com`):** ~355 Mbps
  - **Aggregate Throughput:** ~920 Mbps (near theoretical physical limit)
  - **Network RTT:** Escalated from <1 ms to ~134 ms due to interface queue bufferbloat.
- **CPU & I/O Wait:**
  - Load average peaked at `10.82` (4 CPU cores).
  - CPU breakdown: ~28% System (`sy`), ~28% I/O Wait (`wa` waiting on NFS reads), ~28% SoftIRQ (`si` handling TCP interrupts).
- **Memory Thrashing:**
  - Total RAM: 7.8 GiB. Active ISOs served concurrently: 2 distinct variants (~11.0 GB total).
  - Because combined ISO footprint exceeded RAM, Linux page cache was continuously invalidated, forcing continuous re-reads from upstream NFS.

---

## 3. Root Cause Analysis

### 3.1 Kernel Command-Line Namespace Collision (`url=`)
The primary culprit is a parameter namespace collision between **Casper** (Ubuntu's early initramfs live-boot environment), **Curtin** (Subiquity's low-level installation engine), and **Cloud-init**:

```text
boot_params: boot=casper initrd=initrd ip=dhcp netboot=url url=http://192.168.254.12:16000/isos/...iso ...
```

1. **Casper Execution:**
   - In `/main/scripts/casper`, Casper matches `url=*.iso`, exports `NETBOOT=url`, and calls `do_urlmount()`.
   - `do_urlmount()` executes `wget "${URL}" -O "${target}"`, downloading the entire ISO into RAM (tmpfs) and loop-mounting it onto `/cdrom`.
2. **Subiquity / Curtin Handover:**
   - Once Casper pivots to the live environment, Subiquity launches Curtin (`curtin install`).
   - Curtin independently parses `/proc/cmdline`. When it detects `url=http://...`, Curtin registers this as a remote installation source (`LayeredSourceHandler`).
   - Curtin's `url_helper.download()` initiates a second HTTP GET request to pull the entire ISO again to extract the root filesystem into `/target`, completely ignoring that the ISO was already downloaded and mounted at `/cdrom`.
3. **Cloud-init Crash & OOM Killer Intervention:**
   - In `cloudinit.cmd.main`, `attempt_cmdline_url()` parses `/proc/cmdline` for tokens named `url` or `cloud-config-url`.
   - Upon matching `url=http://.../debug.iso`, cloud-init assumes this URL points to a `#cloud-config` user-data document and invokes `url_helper.readurl()`.
   - Although `stream=True` is requested, `readurl()` evaluates `len(response.content)` to format debug logs, forcing Python's `requests` library to buffer the **entire 7.1 GB ISO into process RAM**.
   - On nodes with 16 GB RAM (e.g. `192.168.9.244`), the combination of the 7.1 GB Casper RAM disk and the 7.1 GB Python heap allocation exhausts physical memory. The Linux kernel OOM Killer terminates `cloud-init-local.service` and `cloud-init.service`.
   - Without a running cloud-init daemon, the legitimate autoinstall seed (`ds=nocloud-net`) is never delivered to Subiquity, causing the installer to drop into an interactive language selection TUI.

### 3.2 Missing Local `source` Specification in `user-data`
In `user-data`, the `autoinstall` block defines:
```yaml
autoinstall:
  version: 1
```
Because no `source:` block is explicitly declared, Subiquity does not force Curtin to use `/cdrom/casper/install-sources.yaml`. Curtin falls back to the kernel command-line source (`url=`).

---

## 4. Remediation Architecture & Solutions

### Option 1: Kernel Argument Decoupling (`iso-url=`) — *Immediate Fix*

#### Mechanism
In `/main/scripts/casper`, Casper accepts **both** `url=` and `iso-url=`:
```sh
url=*.iso)     export NETBOOT=url; export URL="${x#url=}" ;;
iso-url=*.iso) export NETBOOT=url; export URL="${x#iso-url=}" ;;
```
However, **Curtin only recognizes `url=`**. It does not look for `iso-url=`.

#### Implementation
In Bootimus `boot_params` (configured in `bootimus.db` or via UI/API):
- **Replace:**
  `netboot=url url=http://192.168.254.12:16000/isos/sync/gdc-bootstrap-ubuntu-24.04-v0.7.1-debug.iso`
- **With:**
  `netboot=url iso-url=http://192.168.254.12:16000/isos/sync/gdc-bootstrap-ubuntu-24.04-v0.7.1-debug.iso`

#### Impact
- Casper successfully downloads and mounts the ISO to `/cdrom` in Phase 1.
- Curtin does not find `url=` in `/proc/cmdline`, so it defaults to the local `/cdrom` media descriptor (`install-sources.yaml`).
- **Eliminates the 2nd and 3rd download completely.** Transfer per machine drops from ~16 GB to 5.5 GB.

---

### Option 2: Explicit Local Media Declaration in `user-data`

#### Mechanism
Force Subiquity to declare `/cdrom` as the primary image source and mask the kernel `url=` argument before Curtin reads it.

#### Implementation
Update the `user-data` template:
```yaml
autoinstall:
  version: 1
  source:
    id: ubuntu-server-minimal
    search_drivers: false
  early-commands:
    # Scrub url= parameter from runtime cmdline visibility if needed
    - sed -i 's/url=[^ ]*//g' /proc/cmdline 2>/dev/null || true
```

---

### 4.3 Architectural Note: Stateless NFS-Root (`netboot=nfs`) Constraints
*Note on Alternative Architectures:*
In traditional data center deployments, mounting root directly over NFS (`boot=casper netboot=nfs nfsroot=...`) is often considered because it completely avoids downloading the ISO into client RAM and only streams squashfs blocks on demand (~1.2 GB vs 5.5 GB). 

However, **this approach is explicitly disqualified for GDC Airgapped Deployments**, because:
1. **Single Artifact Constraint:** GDC Disk Provisioner strictly requires a single, self-contained, fully baked `.iso` file containing all OS components, Gitea, Nexus, OCI images, and playbooks.
2. **Infrastructure Independence:** An NFS-root workflow requires pre-extracting ISO contents onto an external NFS server and managing export permissions, which breaks disconnected, zero-infrastructure edge deployments and physical USB workflows.

Therefore, the architecture remains committed to **HTTP-based ISO streaming from a single image**, resolved via `iso-url=`.

---

### Option 3: Bootimus Local Caching (Alleviate Upstream NFS Link)

#### Mechanism
If retaining HTTP ISO delivery, eliminate the dual-direction traffic contention on the Raspberry Pi's NIC. Currently, the Pi reads from `storage.ensor-labs.com` over NFS (350 Mbps RX) while serving HTTP to nodes (650 Mbps TX).

#### Implementation
Store the active `.iso` files on the local NVMe or high-speed storage of the `automation` host (`/opt/bootimus/data/isos/`) instead of mounting via NFS.

---

### 4.4 Seed Artifact Hydration (`nocloud/vendor-data`)

#### Mechanism
When `cloud-init` probes `ds=nocloud-net;s=http://.../nocloud/`, it requests three seed files: `meta-data`, `user-data`, and `vendor-data`. By default, Ubuntu 24.04 cloud-init has `vendor_data: {enabled: true}`.

If the HTTP endpoint returns `404 Not Found` for `vendor-data`, `cloud-init`'s HTTP retry handler executes **11 retries with a 1-second backoff**, introducing a 10+ second stall into the node's boot sequence.

#### Implementation
In `src/build/render_templates.py`, the hydration stage automatically writes a minimal `#cloud-config\n` payload to `output_dir/nocloud/vendor-data` alongside `meta-data` and `user-data`. The web server returns `200 OK` on attempt 0, eliminating retry loops and reducing netboot latency.

---

## 5. Architectural Comparison Matrix

| Attribute | Current (`url=`) | Option 1 (`iso-url=`) | Option 2 (`user-data`) |
|---|---|---|---|
| **ISO Downloads per Node** | 2 to 3 times | 1 time | 1 time |
| **RAM Footprint on Client** | 5.5 GB (tmpfs) | 5.5 GB (tmpfs) | 5.5 GB (tmpfs) |
| **Total Transfer (5 Nodes)** | ~55–82 GB | ~27.5 GB | ~27.5 GB |
| **Pi Network Load** | ~920 Mbps (Saturated) | ~500 Mbps | ~500 Mbps |
| **Turn-up Time (5 Nodes)** | 18–25 mins | 6–8 mins | 6–8 mins |
| **Implementation Effort** | None | 1 line in Bootimus | Edit `user-data` |

---

## 6. Recommended Action Plan

1. **Phase 1 (Immediate Fix):** Update Bootimus image `boot_params` for `sync/gdc-bootstrap-ubuntu-24.04-v0.7.1-debug` and `no-comp-debug` to replace `url=` with `iso-url=`.
   - **Dynamic Variables:** Utilize Bootimus dynamic variables instead of hard-coded IP addresses and ISO names to ensure portability across different PXE deployments. 
   - **Example Replacement:** 
     `netboot=url iso-url=http://{{ .ServerIP }}:{{ .HTTPPort }}/isos/{{ .Image.Filename }}`
2. **Phase 2 (Configuration Hardening):** Add explicit `source: id: ubuntu-server-minimal` to the GDC `user-data` template.
3. **Phase 3 (Bootimus Host Optimization):** Copy active bootstrap ISOs to local fast storage on the `automation` host (`/opt/bootimus/data/isos/`) instead of mounting over NFS from Synology to free the 1 Gbps link exclusively for client outbound traffic.
