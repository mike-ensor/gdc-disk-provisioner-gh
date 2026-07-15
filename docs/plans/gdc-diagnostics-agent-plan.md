# GDC Diagnostics Agent: Architectural Design & Testing Plan

This document defines the architectural specification, custom tools, unified log correlation rules, and verification procedures (both unit and functional testing) for the GDC Diagnostics Agent Team. The agent team is built upon Google's Agent Development Kit (ADK) to headlessly find, inspect, analyze, and remediate bare-metal provisioning failures.

---

## 1. Multi-Agent Team Architecture

The diagnostics workflow is orchestrated as an ADK `SequentialAgent` comprising four specialized sub-agents:

```
                  ┌──────────────────────────────┐
                  │      RootOrchestrator        │
                  └──────────────┬───────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌───────────────────┐
│ DiscoveryAgent  │───►│ CollectionAgent  │───►│   AnalysisAgent   │
└─────────────────┘    └──────────────────┘    └─────────┬─────────┘
 • Scan CIDR ranges     • Splay credentials              │
 • Probe Port 22        • Pull tarball via SCP/wget      ▼
 • Detect active state                                 ┌───────────────────┐
                                                       │  RcaWriterAgent   │
                                                       └───────────────────┘
                                                        • Correlate logs
                                                        • Synthesize RCA
                                                        • Generate remediate.sh
```

### 1.1 Agent Specifications

#### Agent 1: `DiscoveryAgent`
* **Role:** Detect active network endpoints.
* **Instruction:** Scan subnet CIDR ranges using `scan_ips.py` to identify active node IPs. Run TCP socket checks on Port 22 to determine if the node has rebooted, and determine active state (Past Live CD, In First Boot, Past First Boot, Past Second Boot).

#### Agent 2: `CollectionAgent`
* **Role:** Gather diagnostic payloads.
* **Instruction:** Log in using state-appropriate credentials (rotating through `gdc-admin` with keys, `temporary-installer` with build/local.env passwords, and unsealed recovery `root`/`gdc-password-123`). Check the GDC Companion REST API for out-of-band log telemetry if SSH is blocked. Trigger `/usr/local/bin/collect-node-diagnostics.sh` and download the resulting tarball.

#### Agent 3: `AnalysisAgent`
* **Role:** Inspect log structures.
* **Instruction:** Extract the diagnostic bundle into a temporary workspace. Review `report.json` for system statuses, and perform sequential grep/regex scans on `gdc-ansible-pull.log`, `netplan-hydration.log`, `installer-journal.txt`, and `cloud-init-output.log`.

#### Agent 4: `RcaWriterAgent`
* **Role:** Compile RCA reports.
* **Instruction:** Consolidate log facts, compile a structured Root Cause Analysis Markdown report, and generate a concrete `remediate.sh` script to fix the system.

### 1.2 Dynamic Configurations & Zero-Secrets Policy

To ensure absolute security, no IPs, passwords, tokens, or credential keys will ever be hardcoded into the agent's scripts or model instruction context. 

Instead, the agent team dynamically loads configurations at runtime through a cascaded hierarchy:
1. **Host Environment Variables:** Read active terminal context configurations (e.g. `PROJECT_ID`, `REGION`, `BOOTIMUS_USER`, `BOOTIMUS_PASS`).
2. **Git-Ignored Local Overrides:** Parse `/src/build/local.env` to dynamically resolve custom laboratory parameters (such as `TEMPORARY_INSTALLER_PASSWORD`, `MACHINE_IP_CIDR`, `K8S_IP_CIDR`).
3. **Committed Defaults:** Fallback to standard, public defaults defined in `/src/build/build.env` if local overrides are missing.

These configurations are loaded into the ADK `Runner` or `Session` short-term memory (`state`) during initialization, and are injected securely into the sub-agents and tool calls at execution time, guaranteeing zero leakage to version control systems or trace logs.

### 1.3 Agent Self-Adaptation & Self-Healing Framework

The agent utilizes standard ReAct loops and dynamic prompt formatting inside the ADK to respond cleanly to environment changes:
1. **Dynamic State-Morphing:** Upon discovering target OS details (such as `noble` vs `jammy` or `iso_version`), the agent automatically rewrites its own running instructions placeholder fields in real-time inside the `Session` `state`.
2. **Sequential Refinement:** If a log file format or JSON key changes, the `RefinerAgent` has access to python file-writing tools to modify `tools.py` rules on the fly and verify correctness against local unit tests before proceeding.

---

## 2. Log Correlation & Diagnostics Rules

The `AnalysisAgent` applies specific regex and verification rules to target critical GDC failure vectors:

### 2.1 TPM 2.0 PCR Sealing Failure (Second Boot Lock)
* **Logs to scan:** `dmesg.txt`, `report.json`, `/etc/crypttab` (if present)
* **Regex Patterns:**
  * `tpm2-device.*ignoring unknown option`
  * `Reading keyfile /etc/keys/temp_key.key failed: No such file or directory`
* **Correlation:** If the first boot completed but the second boot gets stuck asking for FDE passcodes, check if the initramfs failed to pack `systemd-cryptenroll` hooks or if the one-time `/etc/keys/temp_key.key` was deleted *before* the TPM key slots were registered.

### 2.2 Network Interface Routing / VRF Loops
* **Logs to scan:** `netplan-hydration.log`, `report.json`
* **Regex Patterns:**
  * `Failed to add route`
  * `RTNETLINK answers: File exists`
* **Correlation:** If gateways are unreachable or endpoints report 0/25 connections after reboot, check for overlapping subnet assignments or routing conflicts between the standard Management and the isolated Kubernetes VRF (`vrf-k8s`) interfaces.

### 2.3 APT Hosted Repository Concurrency Crash
* **Logs to scan:** `gdc-ansible-pull.log`, `nexus.log`
* **Regex Patterns:**
  * `curl: \(7\) Failed to connect to`
  * `nexus.service: Main process exited, code=dumped, status=6/ABRT`
* **Correlation:** If the package upload loop fails with code 7, check if the Sonatype Nexus JVM process crashed under back-to-back metadata rebuild contention.

### 2.4 Access & Authentication Telemetry Audit
* **Logs to scan:** `report.json`, `report.txt`, `/etc/ssh/sshd_config`, `/etc/sudoers.d/*`
* **Audit Rules:**
  1. Parse `.ssh/authorized_keys` for all active accounts, extracting key comments and types (with zero exposure of raw cryptographic signatures) to list exactly who has access.
  2. Parse `PasswordAuthentication`, `PermitRootLogin`, and `PubkeyAuthentication` parameters to audit active terminal ingress policies.
  3. Validate `NOPASSWD` rules in sudoers files to verify privilege isolation limits on administrative accounts (such as `gdc-admin`).

### 2.5 Booted ISO Version Telemetry
* **Logs to scan:** `report.json`, `report.txt`, `/proc/cmdline` (via dmesg)
* **Verification:** Identify the booted ISO version (from `host_metadata.iso_version` key) to track the exact release branch the node was provisioned from. This allows the RCA to trace issues back to their origin and prevent regressions.

---

## 3. Testing Strategy

### 3.1 Unit Testing Strategy (Pytest / Unittest)
We will implement Pytest unit tests using standard `unittest.mock` to verify the Python ADK state transitions and tools without real network dependencies:

* **Test Discover Tool:** Mock `subprocess.run` calls inside `scan_ips.py` to assert correct candidate IP selections.
* **Test Credentials Rotation:** Mock SSH connection errors to test that the agent correctly rotates from `gdc-admin` down to `temporary-installer`, and finally to recovery `root` (escalating to "Crashed Provision" state).
* **Test Companion Out-of-band Fetch:** Mock `requests.get` to return a fake JSON report stream from GDC Companion and verify the collection agent parses it successfully.
* **Test Tarball Extraction:** Mock `tarfile.open` to simulate extracting files into `/tmp/` and assert directories are created with correct permissions.
* **Test RCA Generation:** Provide mock log files containing known errors (e.g., TPM missing keyfile) and verify the `RcaWriterAgent` writes a compliant Markdown report containing the correct `iso_version`.

### 3.2 Functional Testing Strategy (Integration)
We will run real E2E functional checks using our local virtualization sandbox:

* **Live Node Diagnostics:** Run the diagnostics agent against the QEMU guest VM (`127.0.0.1:2222` or live target `192.168.9.248`).
* **Format Assertions:** Assert that the final output matches the requested format:
  1. A valid, structured Markdown RCA file under `docs/rca/`.
  2. The RCA file contains the actual booted `iso_version` (e.g. `v0.1.73`) inside its name and metadata.
  3. A generated `remediate.sh` is written and packed inside the analysis output folder.

---

## 4. Chronological Implementation Checklist (TODO List)

### Stage 1: Scaffold & Project Setup
- [ ] Task 1.1: Create directory `agents/diagnostics_agent/` and scaffold python structures (`agent.py`, `tools.py`, `requirements.txt`).
- [ ] Task 1.2: Initialize the ADK configurations in `pyproject.toml`.

### Stage 2: Custom Tools Development
- [ ] Task 2.1: Implement `discovery_tool` executing `scan_ips.py` and scanning Port 22.
- [ ] Task 2.2: Implement `connection_tool` executing SSH credential rotation.
- [ ] Task 2.3: Implement `collection_tool` capable of downloading diagnostics via SCP or requesting GDC Companion URL payloads.
- [ ] Task 2.4: Implement `analysis_tool` executing regex scans on extracted logs (TPM, VRF, Nexus, and Security/Auth Access).

### Stage 3: ADK Multi-Agent Definition
- [ ] Task 3.1: Define individual agents (`DiscoveryAgent`, `CollectionAgent`, `AnalysisAgent`, `RcaWriterAgent`).
- [ ] Task 3.2: Assemble agents into a unified `SequentialAgent` pipeline inside `agent.py`.

### Stage 4: Test Infrastructure & Verification
- [ ] Task 4.1: Write python unit tests inside `tests/unit/test_diagnostics_agent.py` mocking SSH and GCS.
- [ ] Task 4.2: Write integration tests inside `tests/integration/test_diagnostics_agent_e2e.py`.
- [ ] Task 4.3: Execute testing suite and verify that tests achieve >90% coverage.
