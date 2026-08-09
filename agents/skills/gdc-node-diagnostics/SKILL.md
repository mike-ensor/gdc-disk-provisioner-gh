---
name: gdc-node-diagnostics
description: Finds, queries, and deep-inspects target GDC nodes to compile structured Root Cause Analysis (RCA) Markdown documents. Use when troubleshooting failed installations, provisioning freezes, network timeouts, or missing dependencies.
dependencies:
  - "src/build/scan_ips.py"
  - "collect-diagnostics.sh"
---

# Skill: gdc-node-diagnostics

## 1. Abstract
Provides a structured workflow for identifying, connecting, extracting, and deep-analyzing diagnostic logs from GDC bare-metal nodes. Resolves bootstrap and installation states, determines crash conditions, and generates a structured Root Cause Analysis (RCA) document with ranked severity remediations.

## 2. Usage Examples

### Example 1: Troubleshoot Remote Failed Provision
**Prompt:** "Troubleshoot why the node at 192.168.9.248 didn't finish provisioning."
**Action:** The agent attempts SSH connections, pulls node diagnostics, analyzes logs, and outputs a formatted RCA.

### Example 2: Scans network and Diagnoses
**Prompt:** "Find our newly booted lab node, grab its diagnostics, and analyze any issues."
**Action:** The agent runs `scan_ips.py` to discover the node's IP, connects to pull the tarball, explodes it, and evaluates Subiquity/Ansible logs.

## 3. Security Constraints
- **Private Key / Plaintext Password Security:** Never commit or print plaintext passwords to workspace files or terminal logs. Always load `TEMPORARY_INSTALLER_PASSWORD` dynamically from environment or private configuration scopes (`local.env`).
- **Audit Sanctity:** Never modify or edit the target logs during extraction or inspection.

## 4. Dependencies
- **Discovery Tool:** `src/build/scan_ips.py`
- **On-Node Collector:** `/usr/local/bin/collect-diagnostics.sh`
- **CLI Utilities:** `sshpass`, `ssh`, `scp`, `tar`

---

## 5. Standard Stage-Gate Workflows

### State 1: Network IP Discovery
- [ ] If no IP address is provided by the user, discover the active node by scanning the subnet using the hybrid IP suffix allocator tool:
  `python3 src/build/scan_ips.py --interface <active_interface>`
- [ ] Squeeze `/tmp/allocated_ips.env` (or custom outputs file) to retrieve the active `MACHINE_IP` variable.

### State 2: Connection & Phase Determination
- [ ] Extract `TEMPORARY_INSTALLER_PASSWORD` from `src/build/local.env` or fallback to `src/build/build.env`.
- [ ] Attempt a brief TCP SSH socket connection to `MACHINE_IP` on Port 22 using the `temporary-installer` user account and the extracted password.
- [ ] **Forks Selection:**
  - **Case A (Success):** The machine is active on the network and has booted successfully past the initial Subiquity phase into the persistent target OS. Proceed to **State 4**.
  - **Case B (Fail/Refused):** SSH is unreachable, or the user prompt explicitly indicates a crashed installation. Proceed to **State 3 (Crashed Provision)**.

### State 3: Crashed Provision Escalation
- [ ] If the SSH connection is unreachable or the node is in a boot-loop, attempt fallback SSH entry using the default unsealed root credentials: **`root`** with password **`gdc-password-123`**.
- [ ] If root login is successful, the node is in a chroot/recovery or raw installation state. Keep track of this as a "Crashed Post-Extract" condition.
- [ ] If root login also fails, report a "Bricked/Dead Network" condition and instruct the operator to verify physical console displays or power status.

### State 4: Diagnostics Tarball Acquisition
- [ ] **Case A (URL Provided):** If the user provides a direct URL to a diagnostic tarball uploaded to the GDC Ingestion Companion app, download the archive using `curl` or `wget` directly to `/tmp/`.
- [ ] **Case B (Direct SSH Fetch):** If no URL is provided, run `/usr/local/bin/collect-diagnostics.sh` on the remote target node via the active SSH session, and download the resulting gzip tarball archive locally using SCP:
  `sshpass -p '<password>' scp -o StrictHostKeyChecking=no <user>@<ip>:~/gdc-node-diagnostics-*.tar.gz /tmp/`

### State 5: Extraction & Unified Log Audit
- [ ] Create a local temporary directory: `/tmp/gdc-diagnostics-analysis-<timestamp>/`.
- [ ] Extract the diagnostic tarball into this workspace:
  `tar -xzf /tmp/gdc-node-diagnostics-*.tar.gz -C /tmp/gdc-diagnostics-analysis-<timestamp>/`
- [ ] Conduct sequential, deep-dive examination of the exploded files:
  1. **`report.json`:** Read minimum requirements statuses, systemd active service states, socket listeners, and GDC endpoints connection success rates.
  2. **`report.txt`:** Review the "GDC Component Services Status" and locate the "Ansible Pull Success" state line (`true`/`false`/`Not-Run`).
  3. **`logs/installer-journal.txt`:** If `report.json` reports failures, scan the Subiquity installer logs for storage partitions or filesystem extraction failures.
  4. **`logs/cloud-init-output.log`:** Check for package installation, caching, and pre-seeding failures.
  5. **`logs/gdc-ansible-pull.log`:** Audit detailed Ansible task executions and locate the exact failing role, module, or CLI task.

### State 6: RCA Documentation & Actionable Remedies
- [ ] Compile and display a formal **Root Cause Analysis (RCA)** in Markdown format containing:
  - **Header:** Node Hostname, IP, MAC ID, GDC ISO version found (from report.json `host_metadata.iso_version` key), and boot-state status.
  - **Issue Summary:** Concise statement of the primary cause of failure.
  - **Telemetry Timeline:** Step-by-step chronology leading to the error.
  - **Log Extracts:** Verbatim error messages or stderr logs.
  - **Primary Recommended Fixes:** Ranked list of concrete, actionable remedies grouped by severity (High, Medium, Low) to resolve the block.
