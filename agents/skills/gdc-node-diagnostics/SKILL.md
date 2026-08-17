---
name: gdc-node-diagnostics
description: Finds, queries, and deep-inspects target GDC nodes to compile structured Root Cause Analysis (RCA) Markdown documents. Use when troubleshooting failed installations, provisioning freezes, network timeouts, or missing dependencies.
dependencies:
  - "src/build/scan_ips.py"
  - "sudo /usr/local/bin/gdc-collector --companion-url=https://gdc-companion.ensor-labs.com/v1/machine-reports/ingest"
---

# Skill: gdc-node-diagnostics

## 1. Abstract
Provides a structured workflow for identifying, connecting, extracting, and deep-analyzing diagnostic logs from GDC bare-metal nodes. It compares the **Desired State** (from the GDC Companion API) with the **Actual State** (extracted from node diagnostics) to determine root causes, network issues, or service failures, and generates a structured Root Cause Analysis (RCA) document with ranked severity remediations.

## 2. Usage Examples
See `EXAMPLES.md` for a complete walkthrough of diagnosing a node.

## 3. Security Constraints
- **Private Key / Plaintext Password Security:** Never commit or print plaintext passwords to workspace files or terminal logs. Always load `TEMPORARY_INSTALLER_PASSWORD` dynamically from environment or private configuration scopes (`local.env`).
- **Audit Sanctity:** Never modify or edit the target logs during extraction or inspection.

## 4. Dependencies
- **Discovery Tool:** `src/build/scan_ips.py`
- **On-Node Collector:** `/usr/local/bin/gdc-collector --companion-url={{companion_reports_ingest_url}}`
- **CLI Utilities:** `sshpass`, `ssh`, `scp`, `tar`, `curl`, `jq`

---

## 5. Standard Stage-Gate Workflows

### State 1: Network IP & MAC Discovery
- [ ] If no IP address is provided by the user, discover the active node by scanning the subnet using the hybrid IP suffix allocator tool:
  `python3 src/build/scan_ips.py --interface <active_interface>`
- [ ] Identify the node's MAC address either from `report.json` in the diagnostic tarball or by querying the network interface directly over SSH (`ip link`).

### State 2: Fetch Desired State (Companion API)
- [ ] Read the `INSTALL_COMPANION_API_KEY` from `src/build/local.env`.
- [ ] Query the Companion API to retrieve the intended desired state for the node based on its MAC address:
  `curl -s -X GET "https://gdc-companion.ensor-labs.com/v1/machine-info/<MAC>" -H "Authorization: Bearer <API_KEY>"`
- [ ] Record the desired hostname, management network, and cluster network (VRF/VLAN configurations).

### State 3: Connection & Phase Determination
- [ ] Extract `TEMPORARY_INSTALLER_PASSWORD` from `src/build/local.env` or fallback to `src/build/build.env`.
- [ ] Attempt a brief TCP SSH socket connection to `MACHINE_IP` on Port 22 using the `temporary-installer` user account and the extracted password.
- [ ] **Forks Selection:**
  - **Case A (Success):** The machine is active on the network and has booted successfully past the initial Subiquity phase into the persistent target OS. Proceed to **State 4**.
  - **Case B (Fail/Refused):** SSH is unreachable. If the node is in a boot-loop, attempt fallback SSH entry using the default unsealed root credentials: **`root`** with password **`gdc-password-123`**. If that fails, report a "Bricked/Dead Network" condition.

### State 4: Diagnostics Tarball Acquisition
- [ ] Ensure the node pushes the latest diagnostic state by triggering the collector over SSH:
  `sshpass -p '<password>' ssh -o StrictHostKeyChecking=no temporary-installer@<ip> 'sudo /usr/local/bin/gdc-collector --companion-url="https://gdc-companion.ensor-labs.com/v1/machine-reports/ingest"'`
- [ ] **Case A (URL Provided):** If the user provides a direct URL to a diagnostic tarball uploaded to the GDC Ingestion Companion app, download the archive using `curl` or `wget` directly to `/tmp/`.
- [ ] **Case B (Direct SSH Fetch):** If no URL is provided, download the resulting gzip tarball archive locally using SCP:
  `sshpass -p '<password>' scp -o StrictHostKeyChecking=no temporary-installer@<ip>:/tmp/gdc-node-diagnostics-*.tar.gz /tmp/`

### State 5: Extraction & Unified Log Audit
- [ ] Create a local temporary directory: `/tmp/gdc-diagnostics-analysis-<timestamp>/`.
- [ ] Extract the diagnostic tarball into this workspace:
  `tar -xzf /tmp/gdc-node-*.tar.gz -C /tmp/gdc-diagnostics-analysis-<timestamp>/`
- [ ] Conduct sequential, deep-dive examination of the exploded files:
  1. **`report.json`:** Read minimum requirements statuses, systemd active service states, socket listeners, and GDC endpoints connection success rates. Check which `stage` the node reached (e.g. `CLUSTER_READY`).
  2. **`logs/gdc-ansible-pull.log`:** Audit detailed Ansible task executions and locate the exact failing role, module, or CLI task.
  3. **`configs/api-lookup-status.json`:** Verify if the API lookup was successful or if the node reverted to the fallback config.
  4. **`configs/gdc.fact`:** Check the Ansible facts written to disk. Compare this actual state with the **Desired State** fetched in State 2. Note any discrepancies in JSON mapping (e.g., missing network blocks).
  5. **`configs/99-gdc-cluster-network.yaml`:** Verify if the intended VRF routing and `vlan` configurations were correctly generated by Netplan.
  6. **`logs/systemd-networkd.log`** & **`logs/cloud-init-output.log`:** Check for network bring-up issues or package installation failures.
  7. **System Services Status:** Query `systemctl --failed` or read `report.json` for crashed services (e.g., `node-agent.service`).

### State 6: RCA Documentation & Actionable Remedies
- [ ] Create the local analysis directory if it does not exist: `mkdir -p tmp/node-analysis-reports/`.
- [ ] Compile and save a formal **Root Cause Analysis (RCA)** in Markdown format. 
  - Save the file using the naming convention: `tmp/node-analysis-reports/rca-<IP>-v<ISO_VERSION>-<short-summary>.md` 
    *(e.g., `rca-192.168.9.242-v0.3.39-nodeagent-crash.md`)*.
- [ ] The report MUST contain:
  - **Header:** Node Hostname, IP, MAC ID, GDC ISO version found (from report.json `host_metadata.iso_version` key), and boot-state status.
  - **Desired vs Actual State:** 
    - Include a formatted JSON code block containing the exact `Desired State` payload retrieved from the Companion API.
    - Provide a brief comparison outlining what was actually configured on the machine versus the desired payload.
  - **Issue Summary:** Concise statement of the primary cause of failure.
  - **Telemetry Timeline:** Step-by-step chronology leading to the error.
  - **Log Extracts / Evidence:** Verbatim error messages or stderr logs supporting the conclusion.
  - **Primary Recommended Fixes:** Ranked list of concrete, actionable remedies grouped by severity (High, Medium, Low) to resolve the block.

