---
marp: true
theme: gdc-brand
size: 16:9
paginate: true
---

<!-- _class: lead -->

# GDC Observability & Telemetry
### Monitoring Edge Provisioning with `gdc-companion`

**Telemetry Architecture | Correlation Schema | Diagnostics & Triage**

<!--
[VISUAL]: High-contrast title card in Google Distributed Cloud brand palette, displaying an edge server connected over an ephemeral telemetry channel to a monitoring gateway console, with live log metrics.
[VOICEOVER]: Welcome to the deep dive on Google Distributed Cloud Observability and Telemetry. In this session, we examine how edge bare-metal provisioning is observed and diagnosed at scale using gdc-companion, hardware-rooted correlation schemas, and node-local state persistence—all operating securely in Private Mode environments.
[LIVE DEMO / TERMINAL CUE]: Display title slide and switch terminal to gdc-companion log streaming window.
-->

---

## The Observability Challenge at the Edge

Monitoring bare-metal installations in remote enterprise locations breaks conventional monitoring assumptions:

* **No Inbound Remote Access:**
  * Firewalls, NAT gateways, and zero-trust perimeter policies block inbound SSH or remote console connections.
  * Operations teams cannot "log in and poke around" while the node is undergoing low-level installation.
* **Volatile & Intermittent Connectivity:**
  * Remote sites frequently endure flaky WAN links or high-latency uplinks during deployment.
  * In pure **Private Mode**, external internet connectivity is strictly disabled; monitoring must remain localized or intranet-bound.
* **Transient Ephemeral Boot Environments:**
  * The provisioning pipeline transitions through multiple disjointed operating environments: PXE RAM disk, Subiquity installer kernel, host kernel, and Kubernetes bootstrap.
  * Traditional host agents (e.g., standard Node Exporters or systemd journal forwarders) do not exist during early boot stages.
* **The Solution: Outbound Push Telemetry:**
  * The node initiates passive, one-way outbound webhooks at every stage boundary.
  * A lightweight central listener captures status without exposing node attack surfaces.

<!--
[VISUAL]: Architecture diagram contrasting traditional inbound SSH monitoring (crossed out with red shields) against passive outbound HTTP/mTLS telemetry flowing from edge server to monitoring gateway.
[VOICEOVER]: When deploying bare-metal servers at hundreds of edge locations, traditional observability tools fail. Zero-trust security models prohibit inbound SSH access from the WAN, and remote sites often experience flaky network conditions. Furthermore, during early installation, standard monitoring daemons cannot run because the node is cycling through ephemeral installer kernels and rebooting. To solve this, our architecture relies strictly on passive outbound telemetry, where the node pushes lightweight status webhooks to gdc-companion over an authorized link.
[LIVE DEMO / TERMINAL CUE]: Trace the one-way outbound webhook flow from the edge server toward gdc-companion on the network diagram.
-->

---

## The Distinct Role of `gdc-companion`

Understanding the exact operational boundary between provisioning and ongoing operations is vital:

```
┌────────────────────────────────────────────────────────┐
│                      gdc-companion                     │
│  • Day-0: Bootimus PXE coordination & MAC routing      │
│  • Day-1: Stage 5 cluster configuration & parameter    │
│           templating gateway                           │
│  • Telemetry: Real-time webhook ingestion & logging    │
└──────────────────────────┬─────────────────────────────┘
                           │ Outbound Push Webhooks
                           ▼
┌────────────────────────────────────────────────────────┐
│                    Edge Target Node                    │
│  • Stage 1–8: Autonomous bare-metal provisioning       │
│  • Day-2: Decentralized drift management               │
│           (ansible-pull + gdc-provision.timer)         │
│  • Local Repos: Loopback Gitea (3000) & Nexus (8081)   │
└────────────────────────────────────────────────────────┘
```

* **Day-0 / Day-1 Gateway:** `gdc-companion` acts solely as the provisioning coordinator and configuration distributor.
* **Decentralized Day-2 Runtime Upkeep:** Crucially, `gdc-companion` does **NOT** manage Day-2 operations. Once turned up, ongoing configuration drift remediation runs autonomously on each node via local systemd timers executing `ansible-pull` against loopback Gitea repositories.

<!--
[VISUAL]: Split-plane architecture diagram highlighting gdc-companion as the Day-0 and Day-1 configuration gateway, contrasted with the edge node running decentralized Day-2 drift management independently.
[VOICEOVER]: It is critical to understand the architectural boundary of gdc-companion. It is strictly a Day-0 and Day-1 provisioning gateway. It coordinates initial Bootimus PXE parameters, ingests installation telemetry webhooks, and serves cluster configuration templates during Stage 5. Crucially, gdc-companion is not an ongoing Day-2 fleet manager. Day-2 drift remediation is fully decentralized on the node itself, driven by local systemd timers running ansible-pull against loopback Gitea repositories.
[LIVE DEMO / TERMINAL CUE]: Highlight the Day-0/Day-1 gateway box versus the autonomous decentralized Day-2 node loop.
-->

---

## Telemetry Protocol & Correlation Schema

To track nodes without relying on brittle IP addresses or static session tokens, telemetry utilizes a standardized schema:

* **Legacy Limitations:**
  * Static session IDs break across the mandatory multi-reboot provisioning sequence.
  * IP addresses frequently shift when transitioning from Stage 1 DHCP discovery to Stage 2 static VLAN interfaces.
* **Modern Query Parameter Schema:**
  ```http
  POST /public/webhook?version=v2.4.0&build_id=20261012-1430&mac=52:54:00:12:34:56&logname=stage1-install.log
  POST /secure/telemetry?version=v2.4.0&build_id=20261012-1430&mac=52:54:00:12:34:56&stage=5&status=in_progress
  ```
* **Schema Fields Defined:**
  * `version`: Release tag or Git commit hash of the operating system image bundle.
  * `build_id`: Unique timestamped build identifier assigned during ISO compilation.
  * `mac`: Primary NIC MAC address (immutable physical identifier).
  * `logname`: Specific diagnostic artifact being streamed or referenced.

<!--
[VISUAL]: Code breakdown highlighting URL query parameters: version, build_id, mac, and logname with annotation arrows explaining the role of each field.
[VOICEOVER]: Edge telemetry cannot rely on static session identifiers or ephemeral IP addresses. IP addresses change when switching from Stage 1 DHCP discovery to Stage 2 static VLAN assignment. Instead, our telemetry protocol embeds four core query parameters directly into every webhook payload: the OS release version, the unique compilation build_id, the physical MAC address, and the specific log name being reported. This creates a clean, predictable URL signature for log filtering and ingestion.
[LIVE DEMO / TERMINAL CUE]: Display curl command emitting an outbound webhook formatted with the full telemetry query string.
-->

---

## Hardware Identity Correlation via MAC Address

How operations teams correlate telemetry events across disjointed kernel environments:

* **The Multi-Boot Disconnect Problem:**
  * **Boot 1 (Stage 1–2):** Live Subiquity installer environment running a transient RAM disk kernel.
  * **Boot 2 (Stage 3–4):** Hardened Ubuntu host kernel unsealing LUKS via motherboard TPM 2.0.
  * **Boot 3 (Stage 5–8):** Bare-metal container runtime launching Kind bootstrap and `bmctl`.
  * Each boot generates a fresh ephemeral hostname and transient process tree.
* **The Anchor of Physical Identity:**
  * While `build_id` changes with every ISO compile, the hardware **MAC address** remains globally constant across all reboots.
  * Telemetry ingesters aggregate log streams by indexing:
    $$\text{Session Key} = (\text{mac}, \text{build\_id})$$
* **Cross-Reboot Timeline Stitching:**
  * Operators and automated log collectors construct an unbroken chronological timeline of the entire provisioning sequence for any physical server chassis.

<!--
[VISUAL]: Timeline diagram showing three consecutive boot phases (RAM disk, Host OS, Kubernetes runtime), with distinct process trees stitched together by a shared physical MAC address timeline.
[VOICEOVER]: Because bare-metal turnup involves two automated reboots and three distinct kernel execution environments, hostnames and process IDs cannot provide continuity. The hardware MAC address serves as the immutable anchor. By indexing telemetry streams on the tuple of physical MAC and compilation build_id, gdc-companion stitches disparate log streams into a single unbroken timeline, tracing the node from initial PXE power-on all the way to Kubernetes cluster readiness.
[LIVE DEMO / TERMINAL CUE]: Terminal showing gdc-companion log tail aggregating events from the same MAC address across multiple reboots.
-->

---

## Stage 1 Live Webhook Stream

Examining how the node establishes initial contact during live autoinstall:

* **Dual-Tier Endpoints on `gdc-companion`:**
  * `/public/webhook`: Open HTTP endpoint utilized exclusively during Stage 1 unauthenticated bootstrap (before local certificates exist).
  * `/secure/telemetry`: Mutual TLS (mTLS) verified endpoint utilized for Stage 3+ events after Step CA attestation.
* **Stage 1 Payload Structure:**
  ```json
  {
    "event": "stage1_autoinstall_started",
    "timestamp": "2026-10-12T14:32:05Z",
    "system": {
      "mac": "52:54:00:12:34:56",
      "ip": "192.168.1.145",
      "build_id": "20261012-1430",
      "target_disk": "/dev/nvme0n1",
      "disk_capacity_gb": 1920
    },
    "subiquity_status": "installing_curtin"
  }
  ```
* **Real-Time Stream Forwarding:**
  * As Curtin partitions the NVMe drives, autoinstall hooks stream progress chunked logs to `gdc-companion`.

<!--
[VISUAL]: Split view showing Subiquity installer progress on the physical node console alongside incoming JSON events landing in the gdc-companion log stream.
[VOICEOVER]: During Stage 1, the node operates in an unauthenticated bootstrap environment before cryptographic certificates are minted. It transmits early phone-home signals to gdc-companion's public webhook endpoint. The payload reports disk geometry, Curtin partitioning status, and the build identifier. As Subiquity formats the NVMe drives and unpacks the OS, progress events stream to gdc-companion in real time, giving operators visibility into hardware preparation without serial console access.
[LIVE DEMO / TERMINAL CUE]: Run curl streaming mock webhook to /public/webhook and display JSON ingestion on gdc-companion.
-->

---

## Stage 5 Gating & Configuration Serving

How target nodes query `gdc-companion` for cluster parameters before invoking `bmctl`:

* **The Stage 5 Handshake:**
  * Once the host OS boots and decrypts root storage via TPM 2.0 (Stages 3–4), it must configure the target cluster.
  * In **Private Mode**, cluster parameters (VIPs, node CIDRs, service subnets) are fetched locally from the site's `gdc-companion` instance.
* **Mutual Authentication & Verification:**
  * The node presents its client certificate (signed by Step CA during Stage 4 attestation) containing its MAC address in the SAN.
  * `gdc-companion` verifies that the requesting MAC is authorized to receive target cluster credentials.
* **Delivered Artifacts:**
  * Templated `cluster.yaml` manifest for Anthos / GDC bare metal.
  * Pre-seeded Gitea Git repository commit pointers and Nexus mirror registries.
  * Temporary, short-lived (1-hour) cloud deployment tokens if hybrid management is enabled.

<!--
[VISUAL]: Sequence diagram detailing the Stage 5 mTLS request: Node presents Step CA client cert, gdc-companion validates MAC address, and returns cluster.yaml configuration payload.
[VOICEOVER]: When the node reaches Stage 5, it needs cluster topology details before launching bmctl. Operating in Private Mode, it queries gdc-companion over mutual TLS. The node presents its Step CA-minted client certificate, which binds its MAC address in the Subject Alternative Name. gdc-companion verifies the hardware identity against site authorization records and responds with the templated cluster.yaml configuration and local mirror pointers.
[LIVE DEMO / TERMINAL CUE]: Terminal execution showing Stage 5 curl fetching cluster config over mTLS with Step CA client certificate.
-->

---

## Node-Local State Persistence: `/var/gdc-install/state/`

Resilience requires that state is maintained locally on the disk, independent of network telemetry:

* **State Directory Anatomy:**
  ```
  /var/gdc-install/state/
  ├── stage1-subiquity.json        # OS partitioning and kernel package installation
  ├── stage2-grub-reboot.json      # EFI boot order reordering and reboot trigger
  ├── stage3-tpm-unseal.json       # LUKS crypt enrollment and PCR register validation
  ├── stage4-nodeagent.json        # Loopback services (Gitea/Nexus) and mTLS attestation
  ├── stage5-bmctl-prep.json       # Cluster manifest generation and preflight checks
  ├── stage6-kind-bootstrap.json   # Ephemeral Kind control plane creation
  ├── stage7-target-cp.json        # Pivoting control plane to bare-metal nodes
  └── stage8-complete.json         # GitOps reconciler validation and node ready mark
  ```
* **State File Structure (`stage3-tpm-unseal.json`):**
  ```json
  {
    "stage": 3,
    "status": "COMPLETED",
    "started_at": "2026-10-12T14:38:10Z",
    "completed_at": "2026-10-12T14:39:02Z",
    "steps": [
      {"name": "pcr_quote_verify", "status": "OK", "duration_sec": 4},
      {"name": "tpm2_unseal_luks", "status": "OK", "duration_sec": 48}
    ],
    "last_error": null
  }
  ```
* **Atomic File Updates:** All state files are written to `.tmp` files and committed via atomic `rename()` syscalls to prevent corruption during unexpected power cuts.

<!--
[VISUAL]: File tree of /var/gdc-install/state/ expanding into JSON payload structure detailing atomic state persistence and step timing.
[VOICEOVER]: Because remote power cuts or transient network drops can interrupt telemetry, the ultimate source of truth is stored locally on the node in /var/gdc-install/state. Each stage produces an atomic JSON document recording execution timestamps, individual step outcomes, and error details. If a reboot or power interruption occurs, the provisioning engine reads these state files to determine whether to resume, retry, or abort cleanly.
[LIVE DEMO / TERMINAL CUE]: Terminal showing jq inspection of /var/gdc-install/state/stage3-tpm-unseal.json on an edge node.
-->

---

## The 8-Stage Machine Through the Telemetry Lens

What operators observe on `gdc-companion` dashboards as the machine progresses:

| Stage | Name | Key Telemetry Event | Expected Duration |
|:---:|:---|:---|:---:|
| **1** | Subiquity Autoinstall | `curtin_install_complete` | 4–6 min |
| **2** | First Reboot & EFI Boot | `efibootmgr_next_boot_host` | 1–2 min |
| **3** | Host TPM Unseal & Hardening | `luks_tpm_unsealed_pcr0_7` | 1–2 min |
| **4** | NodeAgent & Mirror Startup | `loopback_gitea_nexus_ready` | 2–3 min |
| **5** | `bmctl` Preflight & Config Sync | `cluster_yaml_templated` | 3–5 min |
| **6** | Kind Ephemeral Bootstrap | `kind_cluster_ready` | 4–7 min |
| **7** | Target Control Plane Pivot | `target_cp_pivoted_healthy` | 8–12 min |
| **8** | Fleet GitOps Synchronization | `gitops_reconciler_synced` | 2–4 min |

* **Total End-to-End Elapsed Time:** Approximately **25 to 35 minutes** unattended from cold PXE boot to healthy Kubernetes cluster node.

<!--
[VISUAL]: High-level dashboard matrix displaying the 8 lifecycle stages with green/yellow status badges, event names, and typical durations.
[VOICEOVER]: Here is the entire eight-stage state machine viewed through the telemetry lens. As the server progresses from Subiquity autoinstall in Stage 1 through Kind bootstrap in Stage 6 to GitOps synchronization in Stage 8, gdc-companion registers each distinct milestone. Total provisioning time is between twenty-five and thirty-five minutes, fully automated without requiring any manual terminal intervention.
[LIVE DEMO / TERMINAL CUE]: Display synchronized dashboard timeline advancing from Stage 1 through Stage 8.
-->

---

## Triage Decision Tree: Isolating Provisioning Failures

When a node stalls, telemetry pinpoints the root cause in minutes:

```
Telemetry Stalled?
│
├── No Stage 1 webhook received?
│   ├── DHCP failure / untagged VLAN mismatch (Smart Hands check)
│   └── Bootimus PXE misconfiguration or BIOS PXE disabled
│
├── Stalled between Stage 2 and Stage 3?
│   ├── GRUB boot sector corruption or UEFI boot order reverted
│   └── AMD Zen 4 PSP bus hang (check `modprobe.blacklist=ccp`)
│
├── Stage 3 fails (`luks_unseal_error`)?
│   ├── Motherboard TPM 2.0 unseal failure / PCR mismatch
│   └── Step CA attestation rejected (invalid EKCert)
│
├── Stage 5 fails (`companion_timeout`)?
│   └── Network firewall blocking port 8443 or mTLS cert SAN mismatch
│
└── Stage 6/7 fails (`bmctl_preflight_failed`)?
    ├── Insufficient memory/disk resources on bare-metal node
    └── Local Docker daemon or container mirror offline on 127.0.0.1:5001
```

<!--
[VISUAL]: Flowchart illustrating triage branches: network misconfiguration, TPM unseal rejection, kernel bus hangs, and container mirror reachability.
[VOICEOVER]: When an installation halts, telemetry isolates the failure point without guessing. If Stage 1 never rings home, the issue is physical cabling, DHCP reservation, or PXE configuration. If the node reboots after Stage 2 but never reaches Stage 3, check GRUB boot order or AMD silicon kernel flags. If Stage 3 reports an unseal error, investigate the TPM PCR registers. If Stage 6 fails, inspect local container mirrors on port 5001.
[LIVE DEMO / TERMINAL CUE]: Follow a triage branch from stalled Stage 3 event to inspecting TPM PCR quote logs.
-->

---

## Telemetry Security: Hardening with Step CA & mTLS

Protecting the telemetry channel in Zero-Trust environments:

* **The Security Threat Model:**
  * Threat: Rogue devices on the provisioning network spoofing telemetry or requesting cluster configurations.
  * In **Private Mode**, isolation does not replace authentication; internal traffic must be cryptographically protected.
* **Step CA Automated Attestation:**
  1. The node extracts its TPM 2.0 Endorsement Key Certificate (EKCert) stamped by the silicon manufacturer.
  2. The node sends an attestation challenge to the local Step CA instance.
  3. Step CA validates the cryptographic signature and issues a short-lived client certificate with `SAN: DNS:node-<mac>.gdc.internal, URI:mac:<mac>`.
* **Enforcing mTLS on `/secure/telemetry`:**
  * `gdc-companion` strictly rejects connections without client certificates signed by the trusted Step CA root.
  * Every telemetry event is cryptographically non-repudiable and bound to verified physical hardware.

<!--
[VISUAL]: Security architecture diagram showing TPM 2.0 Endorsement Key certificate exchange with Step CA, culminating in an mTLS handshake to gdc-companion.
[VOICEOVER]: Telemetry channels must be as secure as the infrastructure they monitor. Even in isolated Private Mode environments, we enforce Zero-Trust principles. During Stage 4, the node proves its silicon identity to Step CA using its motherboard TPM 2.0 Endorsement Key Certificate. Step CA issues a client certificate binding the node's MAC address in the SAN. From that point forward, all telemetry pushes to gdc-companion require mutual TLS, preventing any rogue device on the wire from spoofing status or exfiltrating cluster configurations.
[LIVE DEMO / TERMINAL CUE]: Display openssl s_client verification connecting to gdc-companion mTLS port with Step CA certificate.
-->

---

## Forensics & Automated RCA Reports

When automated turnup encounters an unrecoverable fault, rapid forensics are required:

* **The Node Diagnostics Agent:**
  * In the `gdc-disk-provisioner` repository, `agents/skills/gdc-node-diagnostics` provides automated forensic analysis.
* **Automated Evidence Collection:**
  * Pulls `/var/gdc-install/state/*.json` step reports.
  * Extracts systemd journal entries: `journalctl -u gdc-provision -u nodeagent`.
  * Gathers hardware firmware states: `dmesg | grep -E "ccp|tpm|nvme|ath11k"`.
* **Structured RCA Generation:**
  * Synthesizes findings into a standardized Root Cause Analysis markdown report:
    * **Failure Stage:** Exact step and timestamp.
    * **Silicon & Kernel Signatures:** Driver errors or bus timeouts.
    * **Remediation Action:** Actionable fix (e.g., BIOS firmware update, PCR reset, or network cable swap).

<!--
[VISUAL]: Example generated Root Cause Analysis (RCA) report in Markdown with high-level summary cards, error callouts, and recommended remediation steps.
[VOICEOVER]: When an error occurs, engineers do not have to sift through gigabytes of raw syslog data manually. Our diagnostics agent automatically interrogates the node, ingests state files, extracts relevant journald and dmesg outputs, and synthesizes a structured Root Cause Analysis report. The report pinpoints the exact failure stage, silicon anomalies, and concrete corrective actions for Smart Hands or platform engineers.
[LIVE DEMO / TERMINAL CUE]: Run diagnostics agent CLI to generate a sample RCA report from /var/gdc-install/state artifacts.
-->

---

## Observability Best Practices & Summary

Key operational takeaways for monitoring GDC bare-metal turnup:

* **1. Rely on Outbound Telemetry:**
  * Never compromise perimeter security by opening inbound SSH ports on provisioning nodes.
* **2. Bind Telemetry to Immutable Hardware Identity:**
  * Always correlate dynamic boot cycles using the physical `mac` address combined with `build_id`.
* **3. Persist State Atomically on Local Disk:**
  * Treat `/var/gdc-install/state/` as the primary ground truth for recovery and idempotency.
* **4. Honor Architectural Boundaries:**
  * Remember that `gdc-companion` is strictly a Day-0/Day-1 provisioning and config gateway. Day-2 drift management is decentralized on the node itself.
* **5. Validate in Private Mode:**
  * Ensure all logging, Step CA attestation, and diagnostic tooling function seamlessly with zero WAN connectivity.

<!--
[VISUAL]: Summary scorecard with icons for outbound telemetry, MAC correlation, local atomic state, decentralized Day-2, and Private Mode compliance.
[VOICEOVER]: To summarize: Edge observability in Google Distributed Cloud succeeds by adopting passive outbound telemetry over inbound access, correlating multi-boot sequences via hardware MAC addresses, and maintaining atomic state files on the local disk. Remember that gdc-companion serves as your Day-0 and Day-1 turnup gateway, while Day-2 drift management remains decentralized on the node. With these practices, you can monitor and support hundreds of edge bare-metal clusters with total confidence in Private Mode.
[LIVE DEMO / TERMINAL CUE]: Display concluding slide with repository links and documentation references.
-->
