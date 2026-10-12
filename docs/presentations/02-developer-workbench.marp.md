---
marp: true
theme: gdc-brand
size: 16:9
paginate: true
---

<!-- _class: lead -->

# GDC Developer Workbench
### Rapid Bare-Metal Systems Engineering

**Offline-First OS Engine | Remastering Pipeline | Zen 4 Hardware Tuning**

<!--
[VISUAL]: Title card with Google Distributed Cloud brand layout, featuring bare-metal rack hardware icons, code editor prompts, and the Developer Workbench banner.
[VOICEOVER]: Welcome to the GDC Developer Workbench deep dive. In this session, we explore the rapid inner-loop engineering workflows powering the offline-first operating system engine for Google Distributed Cloud bare-metal deployments in Private Mode. We will dive into the remastering pipeline, lab virtualization, silicon adaptations, automated RCA diagnostics, and decentralized Day-2 playbook engineering.
[LIVE DEMO / TERMINAL CUE]: Display presentation title graphic and initialize developer workstation terminal shell.
-->

---

## The Developer Mission: Offline-First Engine in Private Mode

Engineering OS images for remote enterprise locations requires an **outage-first** architectural paradigm:

* **Zero-WAN Dependency:**
  * Provisioning must succeed in 100% disconnected Private Mode environments.
  * Every deb package, container image, root certificate, and Ansible playbook must be packaged directly into the ISO payload.
* **Deterministic Bare-Metal Execution:**
  * No interactive console intervention, no dynamic external package resolution, no unpredictable mirrors.
  * Deterministic Subiquity autoinstall templating with hermetic integrity checking.
* **Decentralized Day-2 Runtime Upkeep:**
  * Crucial architectural demarcation: `gdc-companion` acts solely as a Day-0/Day-1 provisioning gateway.
  * Day-2 ongoing configuration drift management runs decentralized on the node itself via local systemd timers and `ansible-pull` against loopback Gitea.
* **Rapid Developer Feedback:**
  * Compressing bare-metal firmware, partitioning, and kernel validation loops from hours down to minutes.

<!--
[VISUAL]: Architectural diagram showing edge node isolation in Private Mode, with local loopback repositories feeding internal installation agents without any WAN dependency.
[VOICEOVER]: The developer mission centers on building an OS engine that treats network outages as normal operating conditions rather than exceptional failures. In Private Mode, every dependency—from deb packages and container images to Ansible playbooks and root certificates—must be bundled directly into the remaster. Furthermore, Day-2 ongoing configuration alignment is intentionally decentralized on the node itself, never driven remotely by gdc-companion. Our engineering goal is to make iterating on this low-level bare-metal software fast, repeatable, and deterministic.
[LIVE DEMO / TERMINAL CUE]: Highlight the Private Mode offline boundary and point out the decentralized Day-2 node-local execution model.
-->

---

## Repository Anatomy & Architecture

The `gdc-disk-provisioner` repository bridges low-level Linux systems engineering and cloud-native cluster turnup:

```
gdc-disk-provisioner/
├── src/build/                      # ISO remastering toolchain & PXE test runners
│   ├── remaster.sh                 # Core pipeline: un-squashfs, inject payload, xorriso repack
│   └── bootimus.py                 # Multi-target BMC/PXE orchestrator & next-boot daemon
├── custom-data/                    # Injected offline payloads & configuration sources
│   ├── gitea/                      # Pre-seeded bare Git repositories for node-local GitOps
│   ├── nexus/                      # Offline apt repositories & OCI container registry mirrors
│   └── examples/burnin-bundle/     # Hardware validation playbooks & stress test hooks
├── agents/                         # Autonomous diagnostics & troubleshooting agents
│   ├── diagnostics_agent/          # Tool-augmented agent generating structured RCA reports
│   └── skills/                     # Domain skills (kernel hang, GRUB recovery, TPM/LUKS repair)
└── test/                           # Python unit, integration, and syntax verification suite
```

<!--
[VISUAL]: Repository file tree highlighting src/build/, custom-data/, agents/, and test/ directories with callouts showing component responsibilities.
[VOICEOVER]: Here is the anatomy of the codebase. The src/build directory houses the core remastering engine and our Bootimus hardware test runner. custom-data holds offline payloads, including bare Git repositories pre-seeded into Gitea and container mirrors destined for Nexus. The agents directory contains specialized diagnostic agents and domain skills for troubleshooting kernel hangs and TPM locks, while test enforces rigorous syntax, schema, and build verification.
[LIVE DEMO / TERMINAL CUE]: Open terminal and run `tree -L 2 src/build custom-data agents test/` to verify directory structure.
-->

---

## Workstation Prerequisites & Lab Environment

A reliable development workbench provides reproducible hermetic builds and isolated bare-metal target control:

* **Host Workstation Dependencies:**
  * Linux environment (Ubuntu 22.04/24.04 or Debian) with KVM hardware virtualization enabled.
  * Toolchain packages: `xorriso`, `squashfs-tools`, `isolinux`, `mtools`, `ipmitool`, `dosfstools`, `python3-venv`.
* **Lab Environment Profiles (`build.env`):**
  * Target profile configurations decouple developer workstations from specific test rigs.
  * Lab profiles (such as `barn` or `lab-west`) define BMC endpoints, IPMI credentials, target MAC addresses, and static test subnets.
* **Virtualization & Hardware Sandboxes:**
  * Local QEMU/KVM harness (`test/boot_qemu.sh`) for rapid pre-hardware validation.
  * Dedicated bare-metal target nodes configured for Bootimus automated iPXE chainloading.

<!--
[VISUAL]: Diagram contrasting the local developer workstation running build.sh against an isolated lab rack environment containing target bare-metal servers managed via IPMI/OOB.
[VOICEOVER]: Before compiling images, the developer workstation is configured with essential toolchains: xorriso for ISO mastering, squashfs-tools for root filesystem manipulation, and ipmitool for BMC orchestration. Environment settings in build.env define our lab profiles—like our internal 'barn' test lab—mapping target server MACs, IPMI credentials, and test subnets so builds can deploy directly to live silicon.
[LIVE DEMO / TERMINAL CUE]: Display sample `build.env` configuration snippet and run `kvm-ok` in developer terminal.
-->

---

## The Remastering Engine (`remaster.sh`)

`remaster.sh` is the deterministic core that transforms upstream Ubuntu 24.04 Server ISOs into hardened GDC node appliances:

```mermaid
flowchart LR
    A[Upstream Ubuntu 24.04 ISO] --> B[Unpack ISO & SquashFS]
    B --> C[Inject Subiquity Autoinstall]
    C --> D[Embed Custom Payloads & Offline Mirrors]
    D --> E[Kernel Patching & Bootloader Hooks]
    E --> F[xorriso Repackaging with UEFI MBR/GPT]
    F --> G[Custom GDC Appliance ISO]
```

* **1. Extract:** Unpacks ISO filesystem and unsquashes `casper/minimal.standard.live.squashfs`.
* **2. Template:** Generates cloud-init and Subiquity `user-data` injecting partitioning, LUKS encryption, and systemd units.
* **3. Payload Sideload:** Copies offline apt debs, container tarballs, and local service binaries into `/custom-data`.
* **4. Kernel & Bootloader:** Modifies GRUB configurations with kernel boot flags and silicon errata blacklists.
* **5. Hermetic xorriso Repack:** Produces a hybrid UEFI/BIOS bootable ISO with exact El Torito boot catalog signatures.

<!--
[VISUAL]: Pipeline diagram illustrating remaster.sh phases from upstream ISO ingestion to squashfs decompression, autoinstall templating, payload injection, and xorriso mastering.
[VOICEOVER]: At the heart of our build process is remaster.sh. It begins by mounting the upstream Ubuntu 24.04 LiveCD and extracting its minimal squashfs root filesystem. The script templates our Subiquity autoinstall configurations, embeds offline payloads into custom-data, applies necessary kernel parameters, and repacks the entire appliance using xorriso with hybrid UEFI partition tables ready for USB and PXE boot.
[LIVE DEMO / TERMINAL CUE]: Terminal command showing dry-run inspection of xorriso flags in `src/build/remaster.sh`.
-->

---

## Pre-seeding Offline Boundary Repositories

To maintain 100% availability in Private Mode, the ISO embeds local service mirrors directly into node storage:

* **Node-Local Gitea (`custom-data/gitea/`):**
  * Bundles bare Git repositories containing node setup and cluster turnup playbooks.
  * During Stage 4, systemd initializes the local Gitea service and seeds repositories over loopback (`http://127.0.0.1:3000`).
  * Eliminates external Git dependencies for initial provisioning and ongoing Day-2 drift remediation.
* **Node-Local Nexus Mirror (`custom-data/nexus/`):**
  * Packages pre-warmed apt repositories for offline kernel and toolchain upgrades.
  * Pre-caches OCI container images required for `bmctl`, Anthos bare-metal core components, and local CNI/CSI drivers.
* **Offline Attestation & Sideload:**
  * All payload archives are cryptographically verified via SHA-256 manifests during the remaster build before inclusion.

<!--
[VISUAL]: Split illustration showing custom-data payloads unpacked onto the host disk, with loopback arrows connecting local systemd services to Gitea and Nexus.
[VOICEOVER]: Disconnected Private Mode demands that every dependency is local. We pre-seed bare Git repositories into custom-data/gitea and cache apt packages and container images for Nexus. When the node reaches Stage 4, local Gitea and Nexus services start up on loopback interfaces. When Ansible or bmctl executes, all repo queries resolve against 127.0.0.1 without sending a single packet out to the WAN.
[LIVE DEMO / TERMINAL CUE]: Terminal displaying directory listing of `custom-data/gitea/` showing bare git bundles.
-->

---

## The Fast Feedback Inner Loop

Developers can build, validate, and dispatch new appliance images to bare-metal targets with a single command:

```bash
# Execute hermetic build, publish to lab PXE server, and trigger target reboot
./build.sh --version 0.4.12 --env barn --bootimus --yes
```

* **What `./build.sh` Executes:**
  * **1. Syntax & Schema Validation:** Validates `machine-info.json` schemas and Ansible syntax before packaging.
  * **2. Hermetic Image Remaster:** Invokes `remaster.sh` to produce `gdc-node-v0.4.12.iso`.
  * **3. Artifact Publication:** Copies generated ISO into the lab environment's Bootimus HTTP/TFTP root.
  * **4. Bootimus Orchestration:** Instructs Bootimus to arm the lab targets for an immediate one-time network boot.
* **Typical Iteration Latency:** Under 4 minutes from code modification to target server UEFI bootloader handshake.

<!--
[VISUAL]: Developer terminal split-screen: left side showing build.sh executing xorriso repack, right side showing Bootimus log streaming image registration.
[VOICEOVER]: The developer inner loop must be fast. By invoking build.sh with version and lab environment flags, the engine validates syntax, runs remaster.sh, publishes the resulting ISO to the lab's Bootimus server, and arms the target machines via IPMI. Developers achieve a complete cycle—from editing an autoinstall template to watching bare-metal silicon boot the new image—in under four minutes.
[LIVE DEMO / TERMINAL CUE]: Run `./build.sh --help` in the terminal to showcase CLI flags including `--env`, `--bootimus`, and `--version`.
-->

---

## Rapid Target Booting with `bootimus.py`

`bootimus.py` orchestrates multi-target bare-metal recycling via out-of-band IPMI and iPXE automation:

```bash
# Configure all lab servers to boot the newly built ISO on next reboot
./src/build/bootimus.py --next-boot gdc-node-v0.4.12.iso --all-targets

# Target a specific test bench chassis and stream serial-over-LAN logs
./src/build/bootimus.py --target node-01.barn --power-cycle --sol
```

* **Dynamic iPXE Menu Generation:**
  * Bootimus updates the target MAC's iPXE chainload script to point to the new kernel, initrd, and ISO loopback mount.
* **BMC & IPMI Power Management:**
  * Issues `ipmitool chassis bootdev pxe options=efiboot` followed by a chassis power cycle.
* **Instantaneous Hardware Recycling:**
  * Avoids manual USB re-flashing or physical presence in the lab; enables unattended CI/CD test automation.

<!--
[VISUAL]: Sequence diagram showing bootimus.py sending IPMI chassis commands to a target server BMC, writing an iPXE boot recipe, and capturing serial-over-LAN telemetry.
[VOICEOVER]: Bootimus is our automation weapon for bare-metal targets. Running bootimus.py allows engineers to set the next-boot image across an entire rack or a specific server with a single command. It configures iPXE recipes dynamically and commands the chassis BMC over IPMI to execute a one-time network boot. This completely removes the need for physical USB drives or manual BIOS menu toggles in the lab.
[LIVE DEMO / TERMINAL CUE]: Terminal execution of `python3 src/build/bootimus.py --list-targets` displaying lab nodes and active boot configurations.
-->

---

## Bare-Metal Silicon & Kernel Quirks: AMD Zen 4

Modern high-density server silicon introduces low-level firmware and bus contention challenges during bootstrap:

* **The Problem on Zen 4 Architectures:**
  * During early PCIe bus enumeration, the AMD Platform Security Processor (PSP) / Cryptographic Coprocessor (`ccp`) and Sensor Fusion Hub (`amd_sfh`) conflict with concurrent NVMe driver probe interrupts.
  * Result: Kernel threads deadlock at early boot (`clocksource: Switched to clocksource tsc`), causing silent freezes before Subiquity starts.
* **The Silicon Blacklist Solution:**
  * Embedded in GRUB bootloader parameters via `remaster.sh`:
  ```bash
  modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp tpm_tis.interrupts=0 video=efifb:1280x1024
  ```
* **Impact of Blacklisting:**
  * Prevents PSP bus lockups during NVMe probing.
  * Disables polling interrupts on TPM 2.0 TIS interfaces, ensuring clean TPM handshakes without lockup.

<!--
[VISUAL]: Architecture schematic comparing standard Linux PCIe probe collision against the Zen 4 tuned boot sequence with blacklisted driver modules.
[VOICEOVER]: Deploying on modern bare-metal silicon like AMD Zen 4 requires addressing hardware-level quirks. During initial PCIe enumeration, concurrent driver loading for the AMD Cryptographic Coprocessor and Sensor Fusion Hub causes bus lockups with NVMe controllers, freezing early boot. By blacklisting pcie_mp2_amd, amd_sfh, and ccp, and suppressing TPM interrupts in GRUB, we eliminate the deadlock and ensure deterministic kernel initialization.
[LIVE DEMO / TERMINAL CUE]: Highlight the `modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp` directive in the GRUB template.
-->

---

## UEFI & Bootloader Manipulation: `efibootmgr`

Autonomous multi-reboot provisioning relies on deterministic non-destructive NVRAM boot order management:

* **The Two-Reboot Inception Problem:**
  * Stage 1 boots from LiveCD/PXE to partition and format drives.
  * Stage 2 must boot the installed OS from NVMe to seal TPM 2.0 encryption keys.
  * Subsequent reboots must never fall back into the PXE installer loop.
* **NVRAM Ordering via `efibootmgr`:**
  * During Subiquity post-installation hooks, the provisioner inspects UEFI boot entries:
  ```bash
  # Identify Ubuntu UEFI entry and elevate to primary boot priority
  efibootmgr -o 0001,0000,0002
  ```
* **Non-Destructive Recovery Fallbacks:**
  * The factory PXE boot entry remains preserved in NVRAM at lower priority.
  * If the primary OS fails to boot or TPM fails to unseal, an operator or BMC watchdog can trigger recovery without wiping hardware firmware.

<!--
[VISUAL]: Diagram illustrating UEFI NVRAM boot variable slots: Slot 0001 (Hardened Host OS) set to primary, Slot 0000 (Bootimus PXE) set to secondary fallback.
[VOICEOVER]: Zero-touch provisioning depends on precise UEFI bootloader manipulation. During Stage 1, the installer uses efibootmgr to inspect motherboard NVRAM and program the newly installed OS as the primary boot target. However, it preserves the PXE network boot entry as a secondary fallback. This guarantees that once installed, the node boots directly into its hardened OS without entering an endless installer loop, while retaining recovery options.
[LIVE DEMO / TERMINAL CUE]: Show terminal command running `efibootmgr -v` to inspect current boot entries and active BootOrder.
-->

---

## The Diagnostics Agent & Automated RCA

When nodes stall or fail pre-checks, autonomous diagnostic agents accelerate troubleshooting:

* **`agents/diagnostics_agent/` Architecture:**
  * Tool-augmented diagnostic engine designed to connect to unreachable or stalled nodes over out-of-band management or local SSH.
  * Gathers system journals, inspects `/var/gdc-install/state/`, reads `curtin` install logs, and evaluates hardware telemetry.
* **Structured Root Cause Analysis Reports (`rca-*.md`):**
  * Synthesizes dense kernel panics, state machine failures, and network timeouts into actionable markdown documents:
  ```
  tmp/node-analysis-reports/rca-192.168.9.242-v0.4.12-nvme-lockup.md
  ```
* **Domain Skills Integration:**
  * Diagnostic workflows route into specialized skills: `gdc-kernel-hang-troubleshooting`, `gdc-grub-recovery`, and `gdc-luks-tpm-recovery`.

<!--
[VISUAL]: Screenshot of an automated Root Cause Analysis markdown report with timeline, culprit component, evidence logs, and recommended remediation steps.
[VOICEOVER]: When a bare-metal node fails during installation, developers do not need to manually parse gigabytes of raw serial logs. Our diagnostics agent automatically interrogates the node, checks local state files in /var/gdc-install/state, and cross-references curtin logs to compile a structured Root Cause Analysis report in rca-*.md format. It directly links issues to domain skills for kernel hangs, GRUB recovery, or TPM unsealing.
[LIVE DEMO / TERMINAL CUE]: Display sample generated RCA report header showing root cause assessment and remediation commands.
-->

---

## Developing Custom Playbooks & Burn-in Bundles

Developers can extend provisioning behavior using modular Ansible bundles in `custom-data/examples/burnin-bundle/`:

```
custom-data/examples/burnin-bundle/
├── requirements.yml           # Community collections & local dependencies
├── cluster_turnup.yml         # Pre-cluster burn-in, memory testing, and GPU validation
├── post_cluster.yml          # Workload validation, storage benchmarking, and health checks
└── README.md                  # Execution instructions & parameter definitions
```

* **Pre-Cluster Burn-In (`cluster_turnup.yml`):**
  * Executes non-destructive CPU stress tests (`mprime`/`stress-ng`) and NVMe latency benchmarks before allowing `bmctl` cluster turnup.
  * Verifies thermal thresholds and PCI bus integrity to prevent mid-turnup hardware panics.
* **Post-Cluster Validation (`post_cluster.yml`):**
  * Deploys synthetic test pods, exercises local CSI storage drivers, and validates node-to-node network throughput.
* **Decentralized Execution:** Executed locally by `ansible-pull` against Gitea—zero central controller required.

<!--
[VISUAL]: Workflow diagram showing burnin-bundle playbooks executing system stress tests in Stage 5 before signaling green light for Stage 6 cluster turnup.
[VOICEOVER]: Extending node behavior is straightforward using custom playbook bundles. The burnin-bundle example demonstrates how developers can integrate hardware burn-in routines: running memory stress tests and NVMe benchmarks during Stage 5 before initiating cluster turnup, and executing synthetic container workloads in Stage 7. Because these run via ansible-pull, they execute natively on the node without external management servers.
[LIVE DEMO / TERMINAL CUE]: Open `custom-data/examples/burnin-bundle/cluster_turnup.yml` in editor to show task structure.
-->

---

## Testing & CI Validation

Rigorous automated testing ensures every code change preserves Private Mode compatibility and silicon stability:

* **Syntax & Schema Verification:**
  * `pytest test/test_presentations_syntax.py` - Enforces presentation structure, brand styling, and Marp standards.
  * `pytest test/test_machine_schema.py` - Validates `machine-info.json` network and hardware profile schemas.
* **Build & Remaster Pipeline Tests:**
  * `pytest test/test_build_script.py` - Verifies argument parsing, environment loading, and artifact packaging.
  * `pytest test/test_nexus_eula_and_anon.py` - Ensures offline Nexus repositories operate without online credential traps.
* **Kubernetes & GitOps Policy Checks:**
  * Nomos validation (`nomos vet`) verifies cluster manifests comply with Config Sync and policy controller standards.
* **Regression Suites:** Pre-flight checks guarantee zero regressions on Zen 4 silicon workarounds and TPM sealing.

<!--
[VISUAL]: Terminal showing a green pytest run across the repository test suite, highlighting tests for build scripts, schemas, and presentations.
[VOICEOVER]: Quality assurance is baked into every layer of the workbench. Our test suite validates machine schemas, build script flags, offline Nexus mirror configurations, and presentation syntax. In addition, nomos vet validates that Kubernetes manifests meet fleet policy standards. This multi-layered validation ensures that changes to remastering scripts or playbooks never break offline reliability.
[LIVE DEMO / TERMINAL CUE]: Run `pytest test/test_presentations_syntax.py -v` in terminal demonstrating green passing tests.
-->

---

## Summary & Developer Quick Reference

Key commands and workflows for the daily engineering inner loop:

| Goal | Command | Description |
| :--- | :--- | :--- |
| **Fast Build & Deploy** | `./build.sh --version <V> --env barn --bootimus --yes` | Build ISO, register to Bootimus, arm lab targets |
| **Target Management** | `./src/build/bootimus.py --next-boot <iso> --all-targets` | Set one-time network boot across all lab servers |
| **Direct Target BMC** | `./src/build/bootimus.py --target node-01.barn --power-cycle --sol` | Power cycle specific node and attach serial console |
| **Run Node RCA** | `python3 -m agents.diagnostics_agent.run --target <IP>` | Analyze stalled node and output structured `rca-*.md` |
| **Execute Test Suite** | `pytest test/ -v` | Run full unit, integration, and syntax validation |

* **Remember:**
  * Always test in Private Mode without external WAN gateways.
  * Day-2 runtime upkeep is decentralized on the node via `ansible-pull`.
  * AMD Zen 4 silicon requires `modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp`.

<!--
[VISUAL]: Quick reference cheat-sheet summarizing essential developer CLI commands with links to documentation and skill files.
[VOICEOVER]: To summarize: the developer workbench empowers rapid bare-metal engineering by combining fast remastering builds with automated Bootimus target recycling. Keep in mind the core architectural tenets: maintain strict Private Mode isolation, rely on decentralized node-local Day-2 upkeep, and ensure Zen 4 kernel parameters are preserved. With these tools, you can prototype and ship bare-metal edge features with speed and confidence.
[LIVE DEMO / TERMINAL CUE]: Display final summary slide and prompt for developer questions.
-->
