---
marp: true
theme: gdc-brand
size: 16:9
paginate: true
---

<!-- _class: lead -->

# GDC Architecture & Security
### Zero-Trust, Attestation, and Private Mode Resilience

**Hardware-Rooted Trust | Step CA Attestation | Dual-Sided mTLS | Decentralized Day-2 Upkeep**

<!--
[VISUAL]: High-contrast title card in Google Distributed Cloud brand styling, featuring a TPM 2.0 silicon chip graphic interconnected with mutual TLS lock badges, an edge server chassis, and Private Mode shield iconography.
[VOICEOVER]: Welcome to the Google Distributed Cloud Architecture and Security Deep Dive. In this session, we examine how edge bare-metal infrastructure achieves zero-trust security, hardware-rooted cryptographic attestation, and operational resilience. We will explore how physical machines transition from unverified bare metal to fully attested, encrypted, and autonomously managed nodes operating reliably in Private Mode environments.
[LIVE DEMO / TERMINAL CUE]: Display presentation title graphic and terminal session connected to a secure lab bastion.
-->

---

## Core Architecture Principles

Securing distributed bare metal requires abandoning traditional data center assumptions:

* **Private Mode as the Fundamental Baseline:**
  * Architecture explicitly assumes WAN connectivity is hostile, intermittent, or entirely non-existent.
  * Systems are architected from day zero to operate, survive, and remediate drift without external dependencies.
* **Evolutionary Separation of Concerns:**
  * Clean architectural boundaries between installer boot environments, immutable host kernels, and container runtimes.
  * Ephemeral installer code completely self-terminates prior to production workload initialization.
* **Hub-and-Spoke Sideloading:**
  * Central provisioning gateways (`gdc-companion`) coordinate initial bootstrapping and configuration distribution.
  * Nodes receive fully hydrated, self-contained local software packages, eliminating runtime internet pulls.
* **Planning for Outages as Core Design:**
  * Network severance is treated as a routine operating state rather than an emergency exception.
  * All runtime decision loops execute node-locally to maintain unbroken operational integrity.

<!--
[VISUAL]: Architectural diagram showing the four core pillars: Private Mode baseline, evolutionary boundaries, hub-and-spoke sideloading, and outage-proof design with resilience shields.
[VOICEOVER]: Designing edge infrastructure begins with a fundamental security mindset: Private Mode is our baseline, not an afterthought. We assume that WAN uplinks will fail or be severed for days or weeks at a time. The system enforces clean evolutionary boundaries, separating ephemeral installer logic from the hardened host operating system. Software artifacts are sideloaded via a hub-and-spoke model during turnup, ensuring every node possesses everything required to run and heal itself locally during complete network isolation.
[LIVE DEMO / TERMINAL CUE]: Highlight the four architecture pillar cards on the visual slide.
-->

---

## System Demarcation: Engine vs. Gateway

Precise boundaries separate node-local execution from provisioning coordination:

| Dimension | `gdc-disk-provisioner` (Node Engine) | `gdc-companion` (Provisioning Gateway) |
| :--- | :--- | :--- |
| **Execution Domain** | Node-local (embedded within ISO and installed OS) | Central or bastion appliance (Day-0/Day-1) |
| **Lifecycle Scope** | Stages 1 through 8 bare-metal turnup & ongoing node upkeep | Initial Bootimus PXE coordination & Stage 5 templating |
| **Hardware Access** | Direct TPM 2.0, NVMe/LVM partitions, EFI NVRAM | Passive network listener; zero direct physical console access |
| **Credentials** | Owns TPM KMS keys, hardware CSR, and local certificates | Validates mTLS client certificates; brokers 1-hour GCP tokens |
| **Day-2 Fleet Ops** | **Owns autonomous Day-2 drift management locally** | **STRICTLY NONE. Does not manage Day-2 fleet operations** |

> **Architectural Rule:** `gdc-companion` is strictly a Day-0 and Day-1 configuration gateway. Ongoing Day-2 configuration drift remediation is decentralized and executes autonomously on each individual node.

<!--
[VISUAL]: Two-column architectural comparison table highlighting gdc-disk-provisioner on the target node versus gdc-companion on the central gateway, with an emphatic callout box emphasizing decentralized Day-2 management.
[VOICEOVER]: A critical architectural principle of our solution is system demarcation. gdc-disk-provisioner is the autonomous engine running directly on the node, driving Stages 1 through 8, managing LUKS disk encryption, interacting with the motherboard TPM, and maintaining ongoing Day-2 state. In contrast, gdc-companion is strictly a Day-0 and Day-1 gateway. It coordinates initial Bootimus PXE boot, validates certificates, and templates configuration during turnup. Crucially, gdc-companion does not manage Day-2 operations—day-2 upkeep is fully decentralized on the node itself.
[LIVE DEMO / TERMINAL CUE]: Point to the highlighted Day-2 Fleet Ops row in the demarcation table.
-->

---

## Hardware-Rooted Trust: TPM 2.0 & EKCert

Security begins with a factory-burned silicon identity that cannot be forged or duplicated:

* **The Silicon Birth Certificate:**
  * Every server motherboard houses a discrete or firmware **TPM 2.0** cryptoprocessor.
  * Factory-burned into the TPM's write-protected NVRAM is the **Endorsement Key Certificate (EKCert)**.
* **Cryptographic Provenance:**
  * The EKCert is signed directly by the silicon manufacturer's Root CA (e.g., AMD, Intel, Infineon, or STMicroelectronics).
  * Contains the public Endorsement Key (`EKPub`) paired with an immutable, non-exportable private key burned into silicon.
* **Zero-Spoofing Guarantee:**
  * Virtual machines, rogue operating systems, or rogue network adapters cannot synthesize a valid vendor EKCert.
  * Proves cryptographically to the cluster orchestrator that physical, vendor-authentic hardware is present.

```bash
# Extracting and validating the hardware Endorsement Key Certificate from silicon NVRAM
tpm2_getekcertificate --ek-certificate=nvram_ek.crt
openssl verify -CAfile /etc/ssl/certs/tpm-vendor-root-ca.pem nvram_ek.crt
```

<!--
[VISUAL]: Schematic diagram illustrating the motherboard TPM 2.0 silicon chip, showing its internal non-volatile memory storing the non-exportable Endorsement Key and the factory-signed EKCert pointing back to the manufacturer root CA.
[VOICEOVER]: Trust begins in silicon. Every server motherboard features a TPM 2.0 cryptoprocessor containing an immutable Endorsement Key Certificate, or EKCert, burned into write-protected NVRAM during chip fabrication. This certificate is cryptographically signed by the silicon vendor's root certificate authority. Because the private key can never leave the TPM chip, the EKCert serves as an unforgeable physical birth certificate, guaranteeing that the machine attempting to join our network is genuine physical hardware and not an emulated adversary.
[LIVE DEMO / TERMINAL CUE]: Run tpm2_getekcertificate on the terminal and display the X.509 manufacturer issuer details using openssl.
-->

---

## Measured Boot & LUKS Encryption

Data confidentiality is sealed to hardware state using TPM 2.0 Platform Configuration Registers:

* **Dynamic LVM & DM-Crypt LUKS2 Partitioning:**
  * All primary storage volumes, OS roots, and data partitions are encrypted using LUKS2 (`aes-xts-plain64`).
  * System utilizes dynamic Logical Volume Management (LVM) layered strictly above encrypted physical devices.
* **TPM 2.0 Measured Boot Sealing:**
  * During boot, UEFI firmware, option ROMs, bootloaders, and kernel hashes are measured into Platform Configuration Registers (PCRs):
    * **PCR 0:** Core system firmware executable code and vendor UEFI measurements.
    * **PCR 2:** Option ROM execution and PCI device firmware integrity.
    * **PCR 4:** UEFI Boot Manager boot target and GRUB bootloader binary measurement.
    * **PCR 7:** Secure Boot state, PK, KEK, db, and dbx digital certificate policies.
* **Zero Plaintext Keys on Disk:**
  * LUKS decryption keys are sealed inside TPM NVRAM under a policy requiring matching PCR values.
  * If boot parameters, firmware, or disks are altered, the TPM refuses to release the key, leaving disk contents unreadable.

<!--
[VISUAL]: Diagram tracking the measured boot chain from UEFI firmware, Option ROMs, GRUB, to Linux kernel, measuring each component into TPM PCR registers 0, 2, 4, and 7 to unlock the sealed LUKS2 master key.
[VOICEOVER]: Physical security at unattended edge sites demands strong encryption without requiring manual passphrases at boot. We combine DM-Crypt LUKS2 full-disk encryption with TPM 2.0 measured boot. As the system boots, hardware hashes of the UEFI firmware, option ROMs, GRUB bootloader, and Secure Boot certificates are calculated into PCR registers 0, 2, 4, and 7. The LUKS volume key is sealed inside the TPM and is only released if every single PCR matches the expected baseline. If someone swaps the drive or tampers with the bootloader, decryption completely locks down.
[LIVE DEMO / TERMINAL CUE]: Terminal inspection of cryptsetup status and tpm2_pcrread displaying PCR 0, 2, 4, and 7 measurements.
-->

---

## The Digital Passport: Zero-Touch Attestation

Transforming raw hardware silicon into an authenticated cryptographic identity:

```
┌──────────────┐          1. Generate Non-Exportable Key           ┌──────────────┐
│  Target Node │ ────────────────────────────────────────────────> │   TPM KMS    │
│              │ <──────────────────────────────────────────────── │              │
│              │          2. Hardware Private Key Handle           └──────────────┘
│              │
│              │          3. Submit CSR + EKCert Proof
│              │ ────────────────────────────────────────────────> ┌──────────────┐
│              │             (Subject SAN: MAC Address)            │   Step CA    │
│              │                                                   │ (Root Trust) │
│              │          4. Minted Client Certificate             │              │
│              │ <──────────────────────────────────────────────── └──────────────┘
│              │             (client.crt: Authorized Identity)
└──────────────┘
```

* **Step 1 & 2:** Node requests the TPM KMS to generate an asymmetric private key that cannot be exported from hardware.
* **Step 3:** Node builds a CSR embedding its primary active MAC address in the Subject Alternative Name (`SAN`) and submits it with the manufacturer `EKCert` to **Step CA** via `step-cli`.
* **Step 4:** Step CA verifies the EKCert against vendor root trust chains, validates silicon provenance, and mints an X.509 `client.crt`.

<!--
[VISUAL]: Sequence flowchart tracing the Digital Passport creation: TPM KMS key generation, CSR construction with MAC SAN, EKCert proof verification by Step CA, and issuance of the client.crt identity.
[VOICEOVER]: To authenticate with the cluster, the node creates what we call a Digital Passport. First, the node generates an asymmetric key pair directly within the TPM KMS—the private key is hardware-bound and non-exportable. Next, the node packages a Certificate Signing Request with its physical MAC address specified in the Subject Alternative Name, pairing it with the manufacturer EKCert as cryptographic proof. The node sends this request to Step CA using step-cli. Step CA validates the silicon proof against vendor root authorities and issues an authenticated client certificate.
[LIVE DEMO / TERMINAL CUE]: Trace the four-step sequence diagram from node to TPM KMS to Step CA.
-->

---

## Dual-Sided Mutual TLS (mTLS) Handshake

All control plane communications between edge nodes and `gdc-companion` enforce strict two-way mutual TLS:

* **Two-Way Cryptographic Verification (Port 443):**
  * Communication over HTTPS requires bidirectional verification; anonymous or one-way TLS connections are rejected.
  * Node verifies `gdc-companion` TLS certificate against the internal Step CA Root Certificate authority.
  * `gdc-companion` demands client certificate presentation and validates `client.crt` signature chain against Step CA.
* **Cryptographic MAC Authorization & Whitelisting:**
  * During the handshake, `gdc-companion` extracts the Subject Alternative Name (`SAN`) containing the hardware MAC address.
  * It verifies that the incoming request originates from a pre-registered, authorized edge chassis in the deployment manifest.
* **Elimination of Attack Vectors:**
  * Man-in-the-middle attacks, DNS hijacking, and rogue nodes on the local switch fabric are completely blocked.

```bash
# Node establishing authenticated mutual TLS connection to companion gateway
curl --cacert /etc/ssl/certs/step-ca.crt \
     --cert /var/gdc/pki/client.crt \
     --key "pkcs11:model=TPM%202.0;object=client-key" \
     https://companion.edge.internal:443/v1/attest
```

<!--
[VISUAL]: Two-way mTLS handshake diagram over port 443 showing bidirectional certificate exchange, Step CA root validation, and companion extracting the MAC address from the SAN field.
[VOICEOVER]: Once the node holds its Step CA minted certificate, it initiates a mutual TLS handshake with gdc-companion over port 443. Both sides must verify each other. The node validates the gateway against the Step CA root, and gdc-companion validates the node's client certificate. But we go one step further: gdc-companion extracts the hardware MAC address from the certificate's Subject SAN and matches it against an authorized inventory list. Even on a shared local switch, unapproved machines cannot communicate with the provisioning gateway.
[LIVE DEMO / TERMINAL CUE]: Show live curl mTLS command using the hardware-backed PKCS#11 key to connect to gdc-companion.
-->

---

## Temporary Cloud Token Brokering

Secure cloud integration without storing persistent credentials on physical edge disks:

```
┌─────────────┐            1. Verified mTLS Request (/v1/token)          ┌─────────────┐
│ Target Node │ ───────────────────────────────────────────────────────> │gdc-companion│
│             │                                                          │ (Gateway)   │
│             │                                                          └──────┬──────┘
│             │                                                                 │ 2. IAM Service
│             │                                                                 │    Account API
│             │                                                                 ▼
│             │            3. Ephemeral 1-Hour Access Token              ┌─────────────┐
│             │ <─────────────────────────────────────────────────────── │Google Cloud │
│             │               (Stored in RAM Only)                       │ IAM API     │
└─────────────┘                                                          └─────────────┘
```

* **Short-Lived Ephemeral Credentials:**
  * Upon successful mTLS verification, `gdc-companion` brokers a **1-hour temporary Google Cloud access token**.
  * Tokens are scoped strictly to the specific cluster inception permissions required for Anthos turnup.
* **Zero Long-Lived Keys on Disk:**
  * Zero service account JSON keys, permanent API tokens, or long-lived credentials are ever written to edge storage.
  * Tokens exist exclusively in volatile memory (`tmpfs` / RAM); a power loss immediately purges all credentials.

<!--
[VISUAL]: Architecture sequence showing target node requesting a token over mTLS, gdc-companion communicating with Google Cloud IAM, and returning an ephemeral 1-hour access token kept solely in volatile memory.
[VOICEOVER]: When an edge cluster connects to Google Cloud for management or fleet registration, storing permanent service account JSON keys on physical disks at an unattended retail store or factory is an unacceptable security risk. Instead, gdc-companion brokers short-lived, 1-hour ephemeral OAuth2 access tokens upon successful mTLS verification. These tokens reside strictly in volatile RAM. No long-lived cloud credentials ever touch physical storage. If a physical server is stolen from a rack, there are zero cloud keys to extract.
[LIVE DEMO / TERMINAL CUE]: Inspect tmpfs mount point and demonstrate the absence of service account keys on persistent disk.
-->

---

## Supply Chain Isolation: The Local Boundary

Preventing supply chain attacks by eliminating external internet pulls during installation:

* **Host-Local Loopback Boundaries:**
  * Software repositories are hosted locally on the node and bound strictly to loopback (`127.0.0.1`):
    * **Gitea (Port 3000):** Hosts version-controlled Ansible playbooks, cluster manifests, and OS configs.
    * **Sonatype Nexus (Port 8081 / 5001):** Hosts local Debian package mirrors and OCI container image registries.
* **Strict Loopback Interface Binding:**
  * Neither Gitea nor Nexus binds to public or VLAN network interfaces (`0.0.0.0` is strictly forbidden).
  * Services listen only on `lo` (`127.0.0.1`), entirely inaccessible from outside the physical chassis.
* **Immunity to WAN Outages & Upstream Poisoning:**
  * Remastered ISO images pre-populate all required deb packages and container images during the build.
  * Turnup and provisioning succeed cleanly in pure **Private Mode** without internet access or external registries.

```bash
# Verifying loopback-only binding for local supply chain services
ss -tulpn | grep -E ':(3000|8081|5001)'
# tcp LISTEN 0 4096 127.0.0.1:3000 users:(("gitea",pid=1420,fd=6))
# tcp LISTEN 0 4096 127.0.0.1:8081 users:(("nexus",pid=1532,fd=12))
```

<!--
[VISUAL]: Network socket diagram showing Gitea and Nexus bound strictly to 127.0.0.1 on the internal loopback adapter, with red firewall blocks preventing external ingress from physical network adapters.
[VOICEOVER]: Edge deployments cannot depend on public package registries or GitHub being reachable during installation. To achieve true supply chain isolation, our provisioning pipeline runs local instances of Gitea and Nexus right on the node. Crucially, these services are bound exclusively to the loopback interface on 127.0.0.1. They never listen on external network cards. All required debian packages and container images are pre-staged in the remastered ISO, ensuring turnup succeeds in complete Private Mode with zero risk of upstream tampering.
[LIVE DEMO / TERMINAL CUE]: Run ss -tulpn in the terminal to verify ports 3000, 8081, and 5001 are bound strictly to 127.0.0.1.
-->

---

## Operating System Hardening & CIS Level 2

Enforcing strict operating system security baselines during Stage 4 configuration:

* **CIS Benchmark Level 2 Compliance:**
  * Host operating system is hardened against the Center for Internet Security (CIS) Level 2 Server benchmark.
  * Disables unnecessary legacy protocols and unneeded filesystem drivers (`cramfs`, `freevxfs`, `jffs2`, `hfs`).
* **Kernel Parameter (`sysctl`) Security Profiles:**
  ```ini
  # /etc/sysctl.d/99-gdc-security.conf
  net.ipv4.conf.all.rp_filter = 1                # Strict reverse path filtering (anti-spoofing)
  net.ipv4.conf.all.accept_redirects = 0         # Reject ICMP redirect route modifications
  net.ipv4.conf.all.send_redirects = 0           # Prevent node acting as a rogue router
  fs.protected_hardlinks = 1                     # Prevent hardlink symlink-race exploits
  fs.protected_symlinks = 1                      # Restrict arbitrary symlink traversal
  kernel.kptr_restrict = 2                       # Hide kernel pointers from unprivileged users
  kernel.dmesg_restrict = 1                      # Restrict dmesg buffer to root
  ```
* **Time Synchronization Integrity:**
  * Hardened `chrony` NTP configuration with strict drift slew limits to prevent replay and timing attacks.

<!--
[VISUAL]: Security checklist graphic showing CIS Benchmark Level 2 badge, hardened sysctl configuration file snippet, and kernel protection shield locks.
[VOICEOVER]: Stage 4 of provisioning applies rigorous operating system hardening. The node is configured to comply with the CIS Level 2 Server benchmark. Unneeded legacy filesystem kernel modules are completely blacklisted. Kernel parameters are tuned via sysctl to enforce strict reverse path filtering against IP spoofing, disable ICMP redirects, protect symlinks from race conditions, and conceal kernel memory pointers. Time synchronization is locked down with Chrony to prevent timestamp manipulation attacks.
[LIVE DEMO / TERMINAL CUE]: View /etc/sysctl.d/99-gdc-security.conf and run sysctl -p to show active kernel hardening rules.
-->

---

## Network Segmentation & Firewall Isolation

Layered network zoning prevents lateral movement and protects node control planes:

* **Tagged VLAN Segmentation:**
  * Physical NIC bonds partition traffic into distinct isolated virtual networks:
    * **VLAN 10 (OOB Management):** Dedicated IPMI / BMC management interface isolated from host OS.
    * **VLAN 20 (Host Provisioning):** Stage 1 PXE / DHCP bootstrap traffic and companion gateway telemetry.
    * **VLAN 30 (Node Interconnect):** High-speed inter-node Kubernetes pod networking and CNI traffic.
    * **VLAN 40 (Storage Network):** Distributed block storage replication (e.g., Ceph or local storage SAN).
* **NodeAgent Host Firewall Shielding:**
  * Host firewalls enforce default-deny incoming policies across all external interfaces.
  * Internal control plane ports (`10250`, `6443`, `2379-2380`) are restricted to verified peer node IP ranges.
  * Loopback boundary guarantees that local repositories (ports `3000`, `8081`, `5001`) remain unreachable over the LAN.

<!--
[VISUAL]: Network topology diagram displaying physical NIC bonded trunk lines split into tagged VLANs: OOB Management, Host Provisioning, Node Interconnect, and Storage Network, with NodeAgent firewall shields.
[VOICEOVER]: Network architecture at the edge must defend against lateral movement across local LAN switches. Physical network interfaces are bonded and segregated into tagged VLANs. Out-of-band IPMI sits on its own isolated management subnet. Provisioning traffic is separated from Kubernetes cluster networking and storage replication. On the host, the NodeAgent firewall enforces default-deny ingress policies, shielding Kubernetes API ports and strictly confining local supply chain services to loopback.
[LIVE DEMO / TERMINAL CUE]: Display ip link and VLAN sub-interface tagging on the terminal.
-->

---

## Decentralized Day-2 Drift Management

Configuration consistency is enforced autonomously by the node without central orchestrator dependency:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Edge Target Node Host OS                        │
│                                                                        │
│   ┌─────────────────────┐   Triggers (15m)   ┌─────────────────────┐   │
│   │ gdc-provision.timer │ ─────────────────> │gdc-provision.service│   │
│   └─────────────────────┘                    └──────────┬──────────┘   │
│                                                         │ Executes     │
│                                                         ▼              │
│   ┌─────────────────────┐   Pulls Playbooks  ┌─────────────────────┐   │
│   │ Loopback Gitea Repo │ <───────────────── │    ansible-pull     │   │
│   │  (127.0.0.1:3000)   │                    │ (Local Convergence) │   │
│   └─────────────────────┘                    └─────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

* **Independent Autonomous Execution:**
  * Systemd timer `gdc-provision.timer` triggers `gdc-provision.service` every 15 minutes.
  * Executes `ansible-pull -U http://127.0.0.1:3000/gdc/provisioning.git` directly against local loopback Gitea.
* **Automatic Drift Remediation:**
  * Idempotent playbooks audit file permissions, firewall rules, sysctl settings, and container runtimes.
  * Any unauthorized local configuration changes are reverted immediately to the golden baseline.
* **Resilient in Private Mode:**
  * Operates with 100% autonomy even if the WAN uplink is permanently disconnected.

<!--
[VISUAL]: Architecture loop showing gdc-provision.timer triggering gdc-provision.service, running ansible-pull against loopback Gitea (127.0.0.1:3000) inside the edge node host OS box.
[VOICEOVER]: Now let's examine Day-2 operations. Unlike centralized management tools that push configurations over fragile WAN connections, our architecture is fully decentralized. Every node runs a local systemd timer—gdc-provision.timer—every fifteen minutes. This timer fires ansible-pull against the node's own loopback Gitea repository. The playbooks run locally, auditing file permissions, kernel settings, and system services. If configuration drift occurs, it is automatically corrected. Because the Git repository is local, this self-healing loop runs indefinitely in Private Mode without any WAN connection.
[LIVE DEMO / TERMINAL CUE]: Terminal showing systemctl status gdc-provision.timer and running an idempotent ansible-pull check.
-->

---

## Enterprise Scalability & Resilience

Scaling zero-trust bare-metal deployments from a single proof-of-concept to thousands of edge sites:

* **Stateless Fleet Gateways:**
  * `gdc-companion` instances operate completely statelessly behind standard internal load balancers.
  * Edge nodes authenticate to any available gateway instance using Step CA mTLS verification.
* **Zero Blast Radius Architecture:**
  * Because drift management and package repositories reside locally on each node, the failure of a central gateway or WAN link has zero operational impact on running edge clusters.
  * Cluster workloads and node self-healing loops continue operating uninterrupted.
* **Zero Console Touches at Scale:**
  * Automated silicon attestation (EKCert) + measured boot LUKS + Step CA certificate minting eliminates manual pre-shared keys, USB token handling, or technician passwords.
* **Deterministic Golden Baselines:**
  * Immutable ISO remastering paired with version-controlled GitOps repositories guarantees identical security postures across every edge location in the global enterprise fleet.

<!--
[VISUAL]: Infographic showing a global enterprise fleet map with thousands of edge nodes in retail, factories, and branch offices, all maintaining identical security baselines with zero console touches.
[VOICEOVER]: When scaling across hundreds of retail stores, healthcare clinics, or industrial plants, operational simplicity is the ultimate security feature. Because our nodes rely on hardware-rooted attestation, zero manual SSH keys or pre-shared passwords are ever required. Because our Day-2 drift remediation is fully decentralized, a network outage at headquarters has zero blast radius at the edge. Every site maintains an identical, verified golden security baseline whether operating online or in prolonged Private Mode.
[LIVE DEMO / TERMINAL CUE]: Point to the scale metrics on the slide, summarizing zero blast radius and zero console touches.
-->

---

## Summary & Zero-Trust Security Checklist

A complete hardware-to-workload chain of trust engineered for edge resilience:

* **[x] Hardware-Rooted Silicon Identity:** TPM 2.0 EKCert factory birth certificate verified against vendor Root CA.
* **[x] Sealed At-Rest Confidentiality:** DM-Crypt LUKS2 full-disk encryption sealed to PCRs 0, 2, 4, and 7.
* **[x] Zero-Touch Attestation:** Step CA mints X.509 `client.crt` with hardware MAC in Subject Alternative Name (`SAN`).
* **[x] Mutual Authentication:** Dual-sided mTLS over port 443 with MAC authorization before configuration delivery.
* **[x] Ephemeral Cloud Credentials:** 1-hour brokered OAuth2 tokens stored in volatile RAM; zero persistent keys on disk.
* **[x] Supply Chain Containment:** Loopback-only (`127.0.0.1`) Gitea and Nexus mirrors eliminate external dependencies.
* **[x] Hardened Platform Baseline:** CIS Level 2 benchmark compliance, sysctl tuning, and tagged VLAN isolation.
* **[x] Decentralized Day-2 Upkeep:** Node-local `ansible-pull` timer ensures continuous drift correction in **Private Mode**.

<!--
[VISUAL]: Complete zero-trust security checklist slide with animated checkmarks alongside the eight security layers from silicon to Day-2 operations, concluding with the GDC brand badge.
[VOICEOVER]: To summarize: Google Distributed Cloud delivers uncompromising zero-trust security at the edge. From the physical TPM silicon birth certificate and measured boot encryption, to Step CA automated mTLS attestation and ephemeral cloud tokens, every layer is cryptographically validated. Furthermore, by isolating supply chains to loopback mirrors and decentralizing Day-2 drift remediation, we achieve unmatched operational resilience in Private Mode. Thank you for watching.
[LIVE DEMO / TERMINAL CUE]: Check off each item on the architecture checklist and show final green turnup status in the terminal.
-->
