# GDC-SPEC-010: Boot & LUKS Troubleshooting Skills Architecture

**Spec Identifier:** `GDC-SPEC-010`  
**Status:** DRAFT (In Brainstorming Review)  
**Author:** GDC Disk Provisioner Architecture Team & opencode  

---

## 1. Executive Summary & Purpose

During physical or virtual node provisioning, target nodes can experience critical bootloader or cryptographic volume failures before SSH configurations can be completed. Since administrators and automated diagnostic agents need to recover these machines without relying on manually re-invented instructions, we establish a standardized set of diagnostic and repair **Skills** alongside a clearly defined set of network-probing and log-extraction **Tools**.

This specification outlines the decoupling of deterministic actions (**Tools**) from analytical reasoning workflows (**Skills**). It designs a hierarchical, router-led troubleshooting skill architecture that allows an agent to autonomously navigate from general "offline node" symptoms down to deep-dive GRUB shell, TPM unseal, or early-stage kernel module recovery.

---

## 2. Decoupled Architecture: Tools vs. Skills

To prevent token bloating and maintain clean software engineering boundaries, we enforce a strict separation of concerns:

```text
               ┌──────────────────────────────┐
               │     DIAGNOSTIC AGENT         │
               └──────────────┬───────────────┘
                              │
             Uses to query    │    Applies reasoning
             network/logs     │    workflows from
                              ▼
        ┌──────────────────────────────────────────┐
        │                 TOOLS                    │◄── [Query network/nodes]
        ├──────────────────────────────────────────┤
        │ • src/build/scan_ips.py (L2 ARP)         │
        │ • bin/debug/crash-cart-scan-subnet.sh    │
        │ • GDC Companion API (/v1/install-logs)   │
        └──────────────────────────────────────────┘
                              │
             Instructs which  │
             sub-skill to load│
                              ▼
        ┌──────────────────────────────────────────┐
        │             ROUTER SKILL                 │◄── [Triggers on offline node]
        │        gdc-boot-troubleshooting          │
        └─────────────────────┬────────────────────┘
                              │
             Forks depending  │
             on symptom state │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
     │  SUB-SKILL   │ │  SUB-SKILL   │ │  SUB-SKILL   │
     │   gdc-grub-  │ │  gdc-luks-   │ │ gdc-kernel-  │
     │   recovery   │ │ tpm-recovery │ │  hang-tb     │
     └──────────────┘ └──────────────┘ └──────────────┘
```

### 2.1. Tools (Deterministic Automation)
Tools represent executable binaries, scripts, or APIs within the codebase. They must perform deterministic inputs and outputs and are called by the agent to acquire system context:
*   **IP Subnet Scanners:** 
    *   `src/build/scan_ips.py`: Standard hybrid L2/ARP/ICMP allocator.
    *   `bin/debug/crash-cart-scan-subnet.sh`: Parallel ping/SSH prober.
*   **Log Receivers:**
    *   `gdc-companion` API (`POST /v1/install-logs/public`): Live JSON logs populated by Curtin/Subiquity over the local network when SSH is completely unreachable.

### 2.2. Skills (Analytical Workflows)
Skills represent Markdown files (`SKILL.md`, `REFERENCE.md`, `EXAMPLES.md`) containing systematic diagnosis pathways, checklists, and manual recovery instruction sets. They do not perform code execution directly but instruct the agent on *how* to interpret tool outputs and execute surgical repairs.

---

## 3. Hierarchical Skill-Set Specifications

### 3.1. Main Router Skill: `gdc-boot-troubleshooting`
*   **Description:** "Coordinate diagnosis and select appropriate deep-dive skills for GDC nodes that are offline, boot-looping, or stuck at bootup."
*   **Workflow:**
    1.  Instructs the agent to check if the target node is pingable and if SSH is listening on port 22.
    2.  If the node is completely unreachable, guides the agent to query the GDC Companion log database (or ask the operator for OOB companion logs) to inspect the latest received webhook telemetry.
    3.  Evaluates the captured symptoms against three distinct failure profiles:
        *   *Symptom A:* Stuck at `grub>` prompt $\rightarrow$ Loads **`gdc-grub-recovery`**.
        *   *Symptom B:* Curtin exit code 2 on decryption or TPM unseal timeouts $\rightarrow$ Loads **`gdc-luks-tpm-recovery`**.
        *   *Symptom C:* Freeze right after partition detection or clocksource switch $\rightarrow$ Loads **`gdc-kernel-hang-troubleshooting`**.

### 3.2. Deep-Dive Sub-Skill 1: `gdc-grub-recovery`
*   **Description:** "Manually boot nodes stuck in the `grub>` command prompt and repair EFI bootloader sectors."
*   **Checklist:**
    - [ ] Run `ls` to identify physical drives and GPT partitions.
    - [ ] Inspect `/boot` contents to locate the active kernel (`vmlinuz`) and initial ramdisk (`initrd.img`).
    - [ ] Run manual bootloader directives with console redirects and essential blacklists.
    - [ ] Once booted, re-install the GRUB boot sector and run `update-grub`.

### 3.3. Deep-Dive Sub-Skill 2: `gdc-luks-tpm-recovery`
*   **Description:** "Recover filesystems locked by LUKS namespace race conditions, missing keys, or failed TPM 2.0 unseal triggers."
*   **Checklist:**
    - [ ] Boot node into Live CD environment.
    - [ ] Run `./bin/debug/recover-tpm-unseal.sh` to automate decryption and chroot repair.
    - [ ] Verify Snap host-to-snap mount propagation by routing keyfiles through `/var/log/installer/`.
    - [ ] Inspect PCR registry values and Secure Boot profiles.

### 3.4. Deep-Dive Sub-Skill 3: `gdc-kernel-hang-troubleshooting`
*   **Description:** "Diagnose early-stage kernel lockups, black-screen freezes, and ACPI/fTPM interrupt deadlocks on Zen 4/AMD platforms."
*   **Checklist:**
    - [ ] Locate the hang signature (e.g. `Switched to clocksource tsc` or platform driver load logs).
    - [ ] Apply polling-mode parameters `tpm_tis.interrupts=0` to the GRUB command-line.
    - [ ] Blacklist the Zen 4 cryptographic coprocessor (`ccp`), `pcie_mp2_amd`, and `amd_sfh` module lines persistently.
    - [ ] Standardize a 1280p VGA geometry string `video=efifb:1280x1024` to prevent off-screen systemd rendering.

---

## 4. Verification & Testing

To validate the integration of the skills and tools:
1.  **Unit Tests:** Implement test coverage inside `test/test_crash_cart_scanner.py` ensuring the parallel probers correctly distinguish between `SSH_DOWN` and `BOOTED_TARGET_OS` states.
2.  **QEMU E2E Simulation:** Run `test/run_qemu_e2e.sh` and force-simulate a boot hang or decryption lockout to verify the diagnostic agent can autonomously escalate logs from the mock companion database.
