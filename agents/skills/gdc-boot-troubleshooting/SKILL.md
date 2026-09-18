---
name: gdc-boot-troubleshooting
description: Router-led orchestrator to diagnose GDC nodes that are offline, boot-looping, or stuck at bootup. Directs the agent to load specialized GRUB, LUKS, or AMD platform sub-skills.
---

# Skill: gdc-boot-troubleshooting (Orchestration Router)

This router-led skill coordinates GDC node boot/encryption failures. It uses network and out-of-band **tools** to discover context, then instructs the agent to transition to specialized **sub-skills** for recovery.

## 🛠️ Step 1: Execute Diagnostic Tools
Before loading recovery skills, run the following deterministic diagnostic tools to locate the node and extract out-of-band context:

### Tool A: Subnet Discovery Scanners
If the node's IP or status is unknown, scan the subnets to locate active, offline, or crashed target systems:
*   **Parallel SSH/Ping Probe:**
    `./bin/local/gdc-crash-cart.sh scan-subnet --cidr 192.168.9.230/27`
*   **L2/ARP Hybrid Allocator:**
    `python3 src/build/scan_ips.py --interface eth0`

### Tool B: Out-of-Band Companion Log Fetcher
If the node is offline or SSH is completely blocked, do not halt. Instead, query live install telemetry from the central GDC Companion:
*   **REST endpoint queries:** Access logs posted dynamically to `http://gdc-companion.local/v1/install-logs`.
*   **Live Stream Logs:** Read raw incoming webhooks via `gdc-installer-receiver.log`.

---

## 🧭 Step 2: Route to Specialized Sub-Skills
Based on the gathered terminal logs, serial outputs, or webhook payloads, immediately load the corresponding deep-dive sub-skill:

### Case A: System is Stuck in GRUB Prompt (`grub>`)
*   **Symptom:** Console shows `GNU GRUB version 2.12` and a non-booted command shell.
*   **Action:** Load the **`gdc-grub-recovery`** skill to execute manual boot mappings and repair EFI sectors.

### Case B: Curtin Decryption Failure / Key Propagation Delay
*   **Symptom:** Log reveals `Exit code: 2` with `No key available with this passphrase` on `cryptsetup open /dev/nvme0n1p3`.
*   **Action:** Load the **`gdc-luks-tpm-recovery`** skill to resolve snap-to-host overlay timing races and run live CD chroot repairs.

### Case C: Early Kernel Hangs (AMD platforms)
*   **Symptom:** Serial console stops dead after `clocksource: Switched to clocksource tsc`.
*   **Action:** Load the **`gdc-kernel-hang-troubleshooting`** skill to apply AMD hardware blacklists and force TPM polling mode.
