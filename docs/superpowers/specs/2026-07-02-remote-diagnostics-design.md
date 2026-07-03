# Spec: GDC Stage-Based Remote Diagnostics and Health-Check Orchestrator

## 1. Abstract
This specification defines the design and implementation of the `remote_diagnostics.py` test utility. This Python 3 script manages the automated collection, extraction, and stage-by-stage evaluation of system health-check reports across multiple GDC Bare-Metal nodes. 

By mapping specific logs and tests directly to the five primary GDC Lifecycle Stages, the orchestrator produces a highly readable dual-format output: a human-friendly GitHub-flavored Markdown report and a machine-parseable JSON payload.

---

## 2. Stages and Log Mapping Category Matrix

As defined in the GDC Node Bootstrap & Turnup Sequence (from [README.md](file:///d/projects/google/gdc-disk-provisioner/README.md)), our diagnostics, tests, and logs map to the lifecycle stages as follows:

| Stage Name | Log Files Inspected | Main Verification Targets |
| :--- | :--- | :--- |
| **Stage 1: ISO Generation & Build** | `casper-md5check.json` | ISO checksum validity, dynamic build banners |
| **Stage 2: Baseline OS & LVM Setup** | `subiquity-server-debug.log`, `curtin-install.log`, `installer-journal.txt`, `dmesg.txt` | Autoinstall errors, dynamic LVM layout partitions, LUKS crypto formatting, storage sizes |
| **Stage 3: Ready-Linux Provisioning** | `gdc-provision.log`, `ssh.log`, `report.json` | `ansible-pull` playbooks success token (`GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY`), CIS hardening state, TPM 2.0 PCR status |
| **Stage 4: GDC Bootstrapping** | `gitea.log`, `nexus.log`, `report.json` | Port 3000 (Gitea) and Port 8081 (Nexus) HTTP health check handshakes, local boundary services availability |
| **Stage 5: Cluster Turnup** | `report.json`, `syslog` / network tests | Outbound Google API DNS/TCP audits, gateways reachability, mutual ping connectivity between nodes |

---

## 3. Execution Workflow & Automation
1. **Remote Sshpass Ingestion**: SSHs into specified target IPs using environment variable `$GDC_PASSWORD` and user `temporary-installer`.
2. **Dynamic Script Execution**: Runs `/usr/local/bin/collect-diagnostics` on the remote hosts to compile a fresh tarball.
3. **Local Pull & Extract**: Copies the tarballs to `/tmp/gdc-diagnostics/<IP>/` and extracts them.
4. **Stage-Gate Evaluation Engine**:
   - Parses `report.json` to verify metrics.
   - Parses the subiquity server logs for errors/warnings.
   - Validates GDC provisioner playbooks.
5. **Cross-Link Connectivity Check**: Initiates a cross-ping task from each node to other nodes to verify Layer 2 and Layer 3 reachability.
6. **Dual Report Compilation**:
   - Writes a human-readable Markdown summary with syntax-highlighted log segments for warning/error regions.
   - Writes a structured machine-readable JSON health report.

---

## 4. GDC Spec Verification Checklist

- [x] State 1: Spec Definition & User Review
- [ ] State 2: Writing & Testing `remote_diagnostics.py`
- [ ] State 3: Execution against live hosts (`192.168.9.234` and `192.168.9.239`)
- [ ] State 4: Generating and rendering Markdown & JSON dual reports
