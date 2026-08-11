# Root Cause Analysis: Node 192.168.9.242 "Failures" & gdc-collector Integration

**Date:** 2026-08-11  
**Node:** `192.168.9.242` (extreme-edge-1)  
**Report ID:** `369340fc-cb63-4e12-bd37-73e175a2aa87`  

## 1. Issue Summary
The operator observed "many failures" in the diagnostic report sent to `gdc-companion` for node `192.168.9.242`, specifically noting that `gdc-provision-service` appeared to be down or not working, and multiple OS prerequisite software checks were failing. The operator suspected this was related to the recent integration of the `gdc-collector` binary and the new Companion API data fetches.

## 2. Root Cause Analysis

After auditing the node directly via SSH and reviewing the provided report JSON, I have identified that the system is actually behaving **exactly as designed**. The "failures" seen in the report are artifacts of **when** the report was generated, combined with the transition from the legacy bash script to the new compiled Go binary.

### A. Why `gdc-provision.service` appeared "down" or "activating"
The diagnostic report was generated and uploaded exactly at the end of **Stage 2 (`FIRST_BOOT`)**. 
The Ansible playbook (`local.yml`) executes the diagnostic collector inside an `always:` block at the end of every individual stage. Because the report was taken mid-execution of the overall provisioning run:
1. `gdc-provision.service` was actively running the playbook. Systemd reports this transient state as `activating` (meaning it has started but not yet completed/exited). It was not down or broken.
2. The playbook was actively preparing to reboot the machine to transition into `SECOND_BOOT`.

### B. Why "Many Failures" appeared in the OS Prerequisites
The `gdc-collector` executes a comprehensive suite of OS prerequisite checks (e.g., checking if UFW is disabled, Swap is disabled, the HWE kernel is installed, and Chrony NTP is active). 
All of these system hardening and tuning tasks are explicitly executed in **Stage 4 (`LINUX_READY`)**. 
Because the diagnostic payload was captured at the end of **Stage 2 (`FIRST_BOOT`)**, none of the hardening tasks had been executed yet. It is expected and intended that these checks fail early in the bootstrap sequence. (If you pull a report from the node right now, they will all show `PASS` because the node has since successfully completed the `LINUX_READY` stage).

### C. What changed and what is incorrect with `gdc-collector`
While the perceived system failures are false positives, there is a **real integration flaw** regarding the `gdc-collector` switchover:
1.  **Missing Network Validation:** In the previous iteration using `collect-diagnostics.sh`, we appended a hook to execute `/usr/local/bin/validate-cluster-networking.sh` and embed the output into the diagnostic tarball. 
2.  **The Flaw:** `gdc-collector` is a pre-compiled Go binary hosted on GCS. By replacing the bash script with this binary, the custom Bash injection we wrote was completely wiped out. The Go binary has no knowledge of `validate-cluster-networking.sh` and no hook to execute it. Consequently, the Cluster Ready network validation evidence is not being gathered or uploaded to the companion.

## 3. Current State of the Node
To ensure the node was not actually broken, I directly SSH'd into `192.168.9.242` and reviewed its current status:
*   The node successfully completed `FIRST_BOOT`, `SECOND_BOOT`, and `LINUX_READY`. All prerequisite software checks are now compliant.
*   The node successfully entered `CLUSTER_READY` and executed the `machine_orchestration` role.
*   It successfully reached the new `Wait up to 5 mins` peer ping loop we added earlier today. 
*   Because its cluster peers (`192.168.9.11` and `192.168.9.13`) are currently offline/unreachable, the 5-minute loop timed out.
*   The playbook elegantly gracefully halted and marked the `cluster-ready.json` state as `"in_progress"`, completely bypassing a hard failure.

## 4. Conclusion & Next Steps
**The node is perfectly healthy.** It is currently paused in the `CLUSTER_READY` stage, waiting for its peers to come online.

**What needs to be fixed:**
Since we cannot inject bash commands into a pre-compiled Go binary (`gdc-collector`), we need to modify the Go source code of `gdc-collector` (wherever that repository lives) to natively execute `/usr/local/bin/validate-cluster-networking.sh` and append the results to its JSON output, OR we need to build a wrapper script that executes both and bundles them together before upload.
