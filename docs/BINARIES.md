# GDC Disk Provisioner - Administrative Binaries & Utilities

This document outlines the administrative scripts, diagnostic tools, and operational utilities available in the `bin/` directory. These tools are designed to help operators manage, diagnose, and recover GDC bare-metal nodes throughout their lifecycle.

## Environment Variables
Many scripts in this directory share a common environment variable for targeting fleets of machines:
*   `TARGET_TEST_MACHINES`: A comma-separated list, Python-style array, or space-separated list of target IPs. 
    *   *Example:* `TARGET_TEST_MACHINES="192.168.9.241, 192.168.9.242"`

---

## Operations & Node Management

### `reset-machines.sh`
**Summary:** Remotely reboots target nodes into their PXE/Network boot option. It dynamically identifies the active network interface, maps it to the UEFI `efibootmgr` list, sets the `BootNext` variable, and issues a reboot.
**Dependencies:** `ssh`, `efibootmgr` (on target node)
**Parameters:**
*   `TARGET_TEST_MACHINES` (Env Var): The IP(s) of the machine(s) to reset.
**Outcome:** The targeted nodes will gracefully reboot and bypass local disk storage to boot directly into the Bootimus PXE environment.

### `push-hotfix-playbook.sh`
**Summary:** Bypasses the Gitea pull-sync mechanism to force-push a local, uncommitted Ansible playbook directly to a node for rapid prototyping and testing.
**Dependencies:** `sshpass`, `scp`, `ssh`
**Parameters:** 
*   `$1`: Target Node IP Address
**Outcome:** The local `src/ansible/` directory is copied to the remote node, and `ansible-pull` is executed locally on the node using the transferred files instead of the Git repository.

### `generate-mock-certs.sh`
**Summary:** Generates short-lived, self-signed mock mTLS certificates for testing the `CLUSTER_READY` validation gates when the Step-CA environment is unavailable.
**Dependencies:** `openssl`
**Outcome:** Drops temporary certificates into `/tmp/` or the specified directory mimicking the `gdc-release.gpg` format.

---

## Telemetry & Diagnostics

### `refresh-telemetry.sh`
**Summary:** Forces an on-demand execution of the `gdc-collector` on target nodes, bypassing the daily 2 AM timer or Ansible stage transitions. Refreshes the Companion UI with the latest node state.
**Dependencies:** `sshpass`, `ping`
**Parameters:**
*   `$1, $2, ...` (CLI Args): Space-separated list of IPs.
*   `TARGET_TEST_MACHINES` (Env Var): Fallback if no CLI args are provided.
**Outcome:** The collector script runs on the target nodes and uploads a fresh `report.json` and diagnostic tarball to the GDC Companion App.

### `crash-cart-scan-subnet.sh`
**Summary:** A high-performance, parallelized Python subnet scanner that identifies GDC nodes in a "Crashed Provision" state (e.g. reachable via ICMP/SSH but failed to fully bootstrap).
**Dependencies:** `python3`, `ping`, `nmap` (optional)
**Outcome:** Outputs a terminal report listing active nodes, unreachable nodes, and nodes exhibiting crash-cart symptoms on the targeted subnet.

### `collect-forensics.sh` / `run-forensics-remote.sh`
**Summary:** Extracts deeply embedded logs (`/var/log/syslog`, `journalctl`, `cloud-init-output.log`, `gdc-ansible-pull.log`) from a node and packages them into a local tarball for offline analysis.
**Dependencies:** `ssh`, `tar`
**Parameters:**
*   `$1`: Target Node IP Address
**Outcome:** Generates a compressed archive of logs in your local workspace.

### `inspect-forensics.sh`
**Summary:** A companion utility to `collect-forensics.sh` that automatically extracts the tarball and runs a series of `grep` and `awk` filters to highlight common failure signatures (e.g., TPM sealing errors, network timeouts).
**Dependencies:** `tar`, `grep`, `awk`
**Parameters:**
*   `$1`: Path to the forensics tarball.
**Outcome:** A color-coded terminal output summarizing the root cause of the failure based on the extracted logs.

---

## Security & Recovery

### `recover-tpm-unseal.sh`
**Summary:** An emergency recovery script for nodes stuck in the initramfs `cryptsetup` prompt due to a failed TPM 2.0 unseal or corrupted PCR registers.
**Dependencies:** `sshpass` (if dropbear is enabled in initramfs) or executed locally via Crash Cart.
**Outcome:** Injects the fallback recovery key, wipes the corrupted `systemd-cryptenroll` slot, and reseals the LUKS volume to the current hardware state.

### `bootloader-crash-cart.sh`
**Summary:** Connects to a node stuck in a GRUB boot-loop or EFI shell to attempt automated recovery of the boot sector.
**Dependencies:** `sshpass`, `ipmitool`
**Outcome:** Rebuilds the `grub.cfg` and EFI variables to restore normal boot sequence.

---

## Validation & Testing

### `run_all_tests.py` / `run-qemu-detached.sh`
**Summary:** Orchestrates the local testing environment. It launches a headless QEMU virtual machine utilizing the locally built ISO, attaches serial consoles for logging, and verifies the installation lifecycle.
**Dependencies:** `qemu-system-x86_64`, `python3`
**Outcome:** A simulated bare-metal installation run entirely on the local developer workstation, producing a pass/fail output matrix.

### `validate-hydrated-files.sh`
**Summary:** Evaluates the Jinja2 templates in the Ansible payload without applying them to a host, verifying that syntax, loops, and variables render correctly.
**Dependencies:** `ansible-playbook`
**Outcome:** Terminal output indicating template compilation success or syntax errors.

### `verify-upgrade-readiness.sh`
**Summary:** Runs pre-flight checks against a node to ensure it has enough disk space, memory, and valid repositories before triggering an OS or GDC component upgrade.
**Dependencies:** `ssh`
**Outcome:** A terminal report outlining if the node is safe to upgrade.

### `generate_build_report.py`
**Summary:** Parses the output of a Cloud Build execution to generate the `build-report-vX.X.X.json` schema artifact that is uploaded to the Companion app.
**Dependencies:** `python3`
**Outcome:** A structured JSON file summarizing the build.

### `audit-machine-states.py`
**Summary:** Queries the Companion API to generate a summarized view of all nodes and their current lifecycle stage (e.g., `LIVECD`, `LINUX_READY`, `CLUSTER_READY`).
**Dependencies:** `python3`, `requests`
**Outcome:** A tabular terminal printout of the fleet status.