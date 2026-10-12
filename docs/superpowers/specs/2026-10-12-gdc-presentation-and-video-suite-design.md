# GDC Software-Only Provisioning: Presentation & Video Suite Design

- **Date:** 2026-10-12
- **Status:** Approved
- **Scope:** `gdc-disk-provisioner` & `gdc-companion` Presentation Suite & YouTube Video Architecture

---

## 1. Executive Summary & Core Philosophy

This specification outlines the architecture, slide deck structure, and video production strategy for the Google Distributed Cloud (GDC) Software-Only Provisioning documentation and presentation suite.

### 1.1 Core Philosophy: Outage-First & Private Mode
At edge environments (retail locations, fulfillment centers, remote facilities), network connectivity is intermittent, volatile, or intentionally restricted. Rather than treating network drops as exceptional error states:
- **Planning for Outages as a Core Design Principle:** The system is explicitly architected so that WAN outages are a non-event. If a node can provision, secure, and maintain itself in complete isolation, standard connectivity drops will never stall cluster inception.
- **Private Mode Terminology:** The project strictly uses the term **"Private Mode"** (never "airgapped") to describe 100% offline, self-contained, and local boundary operations.

### 1.2 Dual System Boundaries
The presentation suite and accompanying documentation articulate the distinct roles of the two interconnected systems:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   GDC FLEET & PROVISIONING ECOSYSTEM                   │
├───────────────────────────────────┬────────────────────────────────────┤
│       gdc-disk-provisioner        │           gdc-companion            │
│         (The Node Engine)         │      (The Fleet Coordinator)       │
├───────────────────────────────────┼────────────────────────────────────┤
│ • Custom Offline-First ISO Engine │ • Central Telemetry & Webhook Sink │
│ • UEFI Automated Bootloader Flip  │ • Ephemeral Boot ID & MAC Tracking │
│ • TPM 2.0 LUKS Disk Encryption    │ • Central Machine Configuration    │
│ • Local Boundary (Gitea & Nexus)  │ • Step CA / mTLS Token Brokering   │
│ • 8-Stage Node State Machine      │ • Cluster Inception Orchestration  │
│ • systemd / ansible-pull Upkeep   │ • Fleet Health & Audit Dashboard   │
└───────────────────────────────────┴────────────────────────────────────┘
```

---

## 2. Target Personas

The suite tailors its narrative across six key enterprise personas:

| Persona | Role Scope | Primary Goals | Key Pain Points Solved |
| :--- | :--- | :--- | :--- |
| **Fleet / Platform Engineer** | Infrastructure & Cluster Lifecycle | Automated bare-metal cluster turnup at scale; reproducible environments. | Eliminates manual server configuration, fragile PXE setups, and multi-day turnup cycles. |
| **Field Tech / Smart Hands** | Physical Site & Rack Deployment | Quick, foolproof server deployment on-site; zero-touch expectations. | Eliminates console typing; node handles two-reboot provisioning autonomously. |
| **Platform Developer** | ISO & Systems Engineering | Fast local iteration on ISOs, Subiquity autoinstall, and kernel tuning. | Provides reproducible local lab environments (`barn`), Bootimus next-boot automation, and instant feedback. |
| **Support / Ops Analyst** | Monitoring & Triage ("Viewer") | Tracking provisioning status, stage progression, and failure triage. | Centralized telemetry via `gdc-companion` webhooks without requiring root SSH access. |
| **Security & Compliance (SecOps)** | Zero-Trust & Auditability | Ensuring hardware authenticity, encryption at rest, and supply chain isolation. | TPM 2.0 silicon binding, measured boot, LUKS encryption, mTLS authentication, and CIS Level 2 hardening. |
| **Solutions Architect** | Enterprise Systems Design | Designing resilient hybrid-edge topologies and multi-site architectures. | Demonstrates scalable Hub-and-Spoke sideloading and deterministic offline execution. |

---

## 3. Directory Layout & Technical Standards

The presentation suite will reside inside the repository under `docs/presentations/`:

```
docs/presentations/
├── README.md                                  # Guide for rendering, viewing, and exporting decks via Marp CLI
├── common/
│   ├── theme.css                              # Custom Marp styling (Google Cloud brand colors: blue, red, yellow, green)
│   └── assets/                                # Shared diagrams, SVG icons, and flowcharts
├── 00-flagship-overview.marp.md               # Flagship Deck: High-impact overview + Modular chapters
├── 01-operator-guide.marp.md                  # Deep Dive 1: Fleet Engineers & Smart Hands
├── 02-developer-workbench.marp.md             # Deep Dive 2: Remastering Engine & Dev Inner Loop
├── 03-observability-and-companion.marp.md     # Deep Dive 3: Telemetry, Webhooks & Health Monitoring
└── 04-architecture-and-security.marp.md       # Deep Dive 4: TPM 2.0, Step-CA, mTLS & Private Mode
```

### Technical Standards:
- **Presentation Engine:** Marp Core / CLI (`marp --html --pdf`) with 16:9 widescreen layout (`size: 16:9`).
- **Presenter Notes & Scripting:** Every slide contains Marp speaker notes formatted for dual-use (live presentation speaker notes + YouTube voiceover script).
- **Embedded Visuals:** Mermaid diagrams natively rendered with explicit brand-aligned styling matching repository standards.

---

## 4. Deck Specifications

### 4.1 Flagship Overview Deck (`00-flagship-overview.marp.md`)
**Target Length:** 22–26 slides  
**Target Duration:** 15–20 min executive pitch, or ~40 min comprehensive walkthrough.

- **Part 1: High-Impact Upfront Pitch (Slides 1–10)**
  1. *Title Slide:* Autonomous Bare-Metal Edge Provisioning for Google Distributed Cloud.
  2. *The Reality of the Edge:* Network volatility, WAN outages, and the breakdown of traditional cloud-tethered installers.
  3. *Core Principle: Outage-First in Private Mode:* How planning for complete network failure enables 100% offline-first provisioning.
  4. *The Two Systems:* Demarcation between `gdc-disk-provisioner` (Node Engine) and `gdc-companion` (Fleet Coordinator).
  5. *Persona Lens:* How operators, developers, support analysts, and security officers interact with the system.
  6. *The 8-Stage State Machine:* LiveCD $\rightarrow$ First Boot $\rightarrow$ Second Boot $\rightarrow$ Linux Ready $\rightarrow$ Cluster Ready $\rightarrow$ Cluster Turnup $\rightarrow$ Post Cluster $\rightarrow$ Upkeep.
  7. *Stages 1–3 (Hardware Foundation):* Automated partitioning, TPM 2.0 LUKS sealing, and NVRAM bootloader flip.
  8. *Stages 4–5 (Boundary Services):* Node-local Gitea (playbooks) and Nexus (OCI/APT proxies); gating cluster creation via `gdc-companion`.
  9. *Stages 6–8 (Cluster Inception & Day-2):* Offline `bmctl create cluster` from loopback registries; autonomous `ansible-pull` drift management.
  10. *Enterprise Outcomes:* Zero console intervention, zero cloud dependency during turnup, cryptographic hardware identity.

- **Part 2: Modular Chapters (Slides 11–22)**
  11. *Chapter 1 (Operator):* Cable, power on, and walk away—the automated 2-reboot turnup experience.
  12. *Operator Prerequisites:* Baseline networking, DHCP discovery handoff to static VLAN, Bootimus PXE/USB media.
  13. *Chapter 2 (Developer):* Fast-feedback inner loop on bare-metal silicon.
  14. *Developer Workflow:* `build.sh` compilation, `bootimus.py` target management, and addressing hardware quirks (e.g. AMD Zen 4).
  15. *Chapter 3 (Observability):* Real-time monitoring across edge sites.
  16. *Telemetry Protocol:* Ephemeral `build_id` and hardware `mac` tracking via `gdc-companion` webhooks.
  17. *Node State Inspection:* `/var/gdc-install/state/*.json` and automated diagnostic RCA tooling.
  18. *Chapter 4 (Security):* Zero-Trust architecture in Private Mode.
  19. *Hardware Attestation:* TPM 2.0 EKCert, Step CA digital signing, and mutual TLS (mTLS) with MAC address verification.
  20. *Supply Chain Defense:* CIS Level 2 hardening, loopback-only dependencies, and short-lived GCP tokens.
  21. *The Deep-Dive Roadmap:* Summary of the 4 specialized follow-up sessions.
  22. *Conclusion & Repo Resources:* Reference docs, quick starts, and contribution guidelines.

---

### 4.2 Deep Dive 1: Operator Guide (`01-operator-guide.marp.md`)
**Target Audience:** Fleet/Platform Engineers and Field Technicians  
**Core Topics:**
1. Physical deployment vs. central management responsibilities.
2. Baseline network architecture: DHCP reservation for Stage 1, VLAN trunking for Stage 2+.
3. PXE server setup via Bootimus & fallback offline USB provisioning creation.
4. Step-by-step physical turnup sequence: The rationale behind the Stage 1–3 automated reboots.
5. `gdc-companion` cluster parameter templating and `bmctl` deployment manifests.
6. Day-2 operations: Autonomous drift remediation via `gdc-provision.timer` and `ansible-pull`.
7. Operational troubleshooting: Identifying stalled states, examining local journal logs, and triggering automated node resets.

---

### 4.3 Deep Dive 2: Developer Workbench (`02-developer-workbench.marp.md`)
**Target Audience:** Platform, OS, and Firmware Engineers  
**Core Topics:**
1. Remastering pipeline internals: `remaster.sh`, ISO unpack/repack via `xorriso`, and Subiquity autoinstall templates.
2. Development workstation and lab setup (`build.env`, test rigs, mock networks).
3. The rapid iteration loop: `./build.sh --version <V> --env barn` and `./src/build/bootimus.py --next-boot ...`.
4. Pre-seeding offline repositories: Bundling bare Git repositories into Gitea and apt/container packages into Nexus.
5. Low-level silicon and kernel adaptation: AMD Zen 4 PSP bus contention (`modprobe.blacklist`), NVMe driver timing, and UEFI boot order modification (`efibootmgr`).
6. Automated diagnostics: Running `diagnostics_agent` to extract node state and compile structured Root Cause Analysis (RCA) reports.

---

### 4.4 Deep Dive 3: Observability & Telemetry (`03-observability-and-companion.marp.md`)
**Target Audience:** Support Analysts, Viewers, and Operations SREs  
**Core Topics:**
1. Passive edge observability without opening inbound SSH ports.
2. The telemetry schema: Query string parameters (`build_id`, `mac`, `version`, `logname`).
3. Hardware correlation: Using the non-changing MAC address to tie together multiple dynamic `build_id` boot cycles.
4. Mapping real-time webhook payloads to the 8-stage state machine.
5. Interpreting local state artifacts: Schema and contents of `/var/gdc-install/state/`.
6. Troubleshooting triage matrix: Distinguishing network failure, TPM unseal rejection, NodeAgent timeout, and `bmctl` installation errors.

---

### 4.5 Deep Dive 4: Architecture & Security (`04-architecture-and-security.marp.md`)
**Target Audience:** Solutions Architects, Tech Leads, and SecOps/Compliance  
**Core Topics:**
1. Architectural principles: Evolutionary separation of concerns, Hub-and-Spoke sideloading, Private Mode first.
2. Hardware-Rooted Security:
   - TPM 2.0 Endorsement Key Certificate (EKCert) as the hardware "birth certificate".
   - Measured boot (PCR register policies) and unattended LUKS decryption.
3. Zero-Touch Attestation & mTLS Workflow:
   - Node generates non-exportable private key in TPM KMS.
   - Node submits CSR + EKCert proof to **Step CA** via `step-cli`.
   - Step CA verifies silicon authenticity against vendor root certificates and mints `client.crt` with the hardware MAC address as the SAN.
   - Dual-sided mutual TLS handshake with `gdc-companion` enforcing MAC authorization.
   - Brokering short-lived (1-hour) temporary GCP credentials; zero permanent cloud keys stored on disk.
4. Local Boundary Security:
   - Running Gitea (port 3000) and Nexus (port 8081/5001) bound strictly to loopback/private host interfaces.
   - CIS Level 2 hardening benchmarks and NodeAgent firewall shielding.
5. Scale & Enterprise Integration: Managing hundreds of distributed retail/edge clusters with zero drift.

---

## 5. YouTube Video Series Adaptation

Each slide deck includes presenter notes structured for video production:

```markdown
<!--
[VISUAL]: Architecture diagram highlighting Stage 2 to Stage 3 reboot handoff.
[VOICEOVER]: Once Subiquity formats the drives, the node reboots. But here is the critical part: it doesn't boot back into the installer. It boots into the hardened host OS to seal disk encryption directly to the motherboard's TPM chip.
[LIVE DEMO / TERMINAL CUE]: Terminal split-screen showing serial console reboot log and efibootmgr boot order output.
-->
```

### Video Episode Roadmap

1. **Episode 1: The Outage-Proof Edge (15–18 min)**  
   *Overview:* The problem with edge bare metal, the Private Mode philosophy, the 8-stage state machine, and the roles of `gdc-disk-provisioner` and `gdc-companion`.
2. **Episode 2: The Zero-Touch Operator Experience (10–12 min)**  
   *Hands-on:* Setting up Bootimus PXE, racking a server, observing the automated 2-reboot sequence, and verifying cluster turnup.
3. **Episode 3: The Developer Inner Loop (12–15 min)**  
   *Engineering:* Remastering an ISO from scratch, tweaking Subiquity autoinstall, targeting lab nodes via Bootimus, and resolving AMD hardware quirks.
4. **Episode 4: Telemetry & Edge Observability (10–12 min)**  
   *Operations:* Live tailing `gdc-companion` webhooks, tracking nodes across boot cycles via MAC and `build_id`, and debugging failures with state files.
5. **Episode 5: Zero-Trust Hardware Attestation & mTLS (12–15 min)**  
   *Security:* TPM 2.0 EKCert extraction, Step CA automated certificate minting, live mTLS handshake verification, and short-lived GCP token brokering.

---

## 6. Verification and Quality Criteria

Before publishing or presenting:
1. **Marp Rendering Validation:** Verify all markdown files compile cleanly to HTML and PDF via `marp --html`.
2. **Mermaid Compatibility:** Ensure all embedded Mermaid sequence diagrams and flowcharts render without syntax errors.
3. **Terminology Consistency:** Audit all slides to ensure "Private Mode" is used exclusively and "airgapped" is omitted.
4. **Script Flow:** Validate that presenter notes provide natural, conversational voiceover pacing matching the visual slide contents.
