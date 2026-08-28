# GDC Disk Provisioner - Administrative Binaries & Utilities

This document outlines the administrative scripts, diagnostic tools, and operational utilities across the repository. Tools are categorized by functional domain and execution context (whether they run on the workstation or inside the deployed ISO).

---

## Directory & Lifecycle Layout

| Functional Group | Base Folder | Target OS Path (In ISO) | Included in ISO? | Description |
|---|---|---|---|---|
| **Authentication/Authorization** | `bin/auth/` | `/usr/local/bin/auth/` | **Always (Debug: No)** | Credential configuration & offline registry auth utilities. |
| **Cluster Operations** | `bin/cluster/` | `/usr/local/bin/cluster/` | **Only with Debug (Debug: Yes)** | Cluster turnup, verification, and upgrade readiness tools. |
| **Node Operations** | `bin/node-ops/` | *N/A (Host Tool)* | **No** | Live playbook prototyping and remote PXE reboot triggers. |
| **Node Debug** | `bin/debug/` | *N/A (Host/Rescue Tool)* | **No** | Serial crash-cart, TPM recovery, subnet scanning, & forensics. |
| **Build Validation & Lab Utilities** | `test/bin/` | *N/A (CI/Build Tool)* | **No** | ISO linters, test runner, QEMU test harness, & lab auditors. |

---

## 1. Authentication / Authorization (`bin/auth/`)

### `gcp-authentication.sh`
* **Target OS Path:** `/usr/local/bin/auth/gcp-authentication.sh`
* **Summary:** Seeds active Google Cloud credentials (`gcloud`) into containerd (`/etc/containerd/certs.d/gcr.io/hosts.toml`) and `/run/gdc-auth/access_token`.
* **When to Use:** Used **IF** `GDC_COMPANION` is set to `FALSE` (or the Companion server is unreachable) and `gcloud` authentication was not automatically completed via mTLS during LiveBoot/FirstBoot. Allows `kubelet` and `containerd` to authenticate and pull Anthos images from `gcr.io`.
* **Options:** Includes `--help` (`-h`) documenting full usage and prerequisite gcloud auth login commands.
* **Dependencies:** `gcloud`, `containerd`, `systemctl`

---

## 2. Cluster Operations (`bin/cluster/`)

### `create_cluster.sh`
* **Target OS Path:** `/usr/local/bin/cluster/create_cluster.sh`
* **Summary:** Provisions a Google Distributed Cloud (GDC) Bare Metal standalone cluster. Configures the cluster YAML, performs pre-flight assertions, and triggers `bmctl create cluster -c <name>`.
* **When to Use:** Executed during the `ClusterReady` stage after `linux-ready` operating system foundations have completed. Idempotent (skips if the cluster is already active).
* **Dependencies:** `bmctl`, `kubectl`, `gcloud`

### `verify-upgrade-readiness.sh`
* **Target OS Path:** `/usr/local/bin/cluster/verify-upgrade-readiness.sh`
* **Summary:** Audits Dracut, GRUB, and cryptsetup configurations on the target node to ensure AMD fTPM blacklists, polling mode, and TPM unseal hooks are preserved before running package updates.
* **When to Use:** Executed on a running GDC node prior to performing OS / kernel upgrades (`apt upgrade`).
* **Dependencies:** `dracut`, `grub-probe`, `cryptsetup`

---

## 3. Node Operations (`bin/node-ops/`)

### `push-hotfix-playbook.sh`
* **Summary:** Rsyncs local development Ansible playbooks directly into the target node's local Gitea repository (`/var/lib/gitea/repos/gdc/bootstrap-playbooks.git`) and restarts the `gdc-provision` pull service.
* **When to Use:** Used during rapid development/troubleshooting to test changes to Ansible roles on a live target node without rebuilding the ISO.
* **Dependencies:** `sshpass`, `rsync`, `ssh`

### `reset-machines.sh`
* **Summary:** Connects to target nodes listed in `TARGET_TEST_MACHINES`, matches the active network MAC to the UEFI PXE boot entry via `efibootmgr`, sets `BootNext`, and initiates a reboot.
* **When to Use:** Used to wipe and re-provision test machines from scratch over PXE/Bootimus.
* **Dependencies:** `sshpass`, `efibootmgr` (on target node)

---

## 4. Node Debug (`bin/debug/`)

### `bootloader-crash-cart.sh`
* **Summary:** Outputs a self-contained shell snippet to restore root password login and enable SSH daemon access directly via serial console/IPMI.
* **When to Use:** Used when a node fails early in the boot sequence before `cloud-init` starts or before the network becomes accessible.

### `recover-tpm-unseal.sh`
* **Summary:** Unlocks the LUKS encrypted system partition from a Live CD, chroots into the target OS, updates Dracut configuration, and rebuilds the initramfs with TPM 2.0 / TSS drivers.
* **When to Use:** Used when a node is stuck at boot due to LUKS failing to auto-unseal via the motherboard TPM.
* **Dependencies:** `tpm2-tools`, `cryptsetup`, `dracut`

### `crash-cart-scan-subnet.sh`
* **Summary:** Performs parallel ICMP and TCP port scans across a target subnet to discover active nodes in rescue/crash mode.
* **When to Use:** Used when a machine boots into a rescue environment and its DHCP-assigned IP address is unknown.
* **Dependencies:** `python3`, `ping`

### `run-forensics-remote.sh` / `collect-forensics.sh`
* **Summary:** Uploads `collect-forensics.sh` to a target IP, executes comprehensive log and hardware extraction, and downloads the compressed `.tar.gz` archive back to the local workstation.
* **When to Use:** Remotely executed when an installation fails or stalls.
* **Dependencies:** `ssh`, `scp`, `tar`

### `inspect-forensics.sh`
* **Summary:** Extracts a forensics tarball and parses error patterns in `subiquity-server-debug.log`, `cloud-init.log`, and `dmesg`.
* **When to Use:** Run locally on the host workstation to inspect captured forensic bundles.
* **Dependencies:** `tar`, `grep`, `awk`

### `extract-installer-logs.sh`
* **Summary:** Quick extraction of `/var/log/installer` and `/var/log/cloud-init.log` via `scp`.
* **When to Use:** Used for rapid log retrieval when full hardware forensics are not required.
* **Dependencies:** `scp`, `ssh`

### `refresh-telemetry.sh`
* **Summary:** Triggers `gdc-collector` on target nodes and forces an updated payload ingest into the GDC Companion API.
* **When to Use:** Used when target node status appears stale in the Companion dashboard.
* **Dependencies:** `sshpass`, `curl`

---

## 5. Build Validation & Lab Utilities (`test/bin/`)

### `validate-hydrated-files.sh`
* **Summary:** Statically lints and validates hydrated cloud-init, netplan, and systemd templates before ISO assembly.
* **When to Use:** Invoked during `make validate` / `make build` or locally prior to image compilation.

### `generate_build_report.py`
* **Summary:** Compiles pipeline execution details, external binary signatures, preseed package counts, and test outcomes into canonical JSON and Markdown After Action Reports.
* **When to Use:** Invoked by `Makefile` and Cloud Build post-assembly.

### `run_all_tests.py`
* **Summary:** Dynamic test runner that discovers and executes all python unit tests and static validation scripts, exporting results to `build-workspace/test_results.json`.
* **When to Use:** Invoked during `make test-static` and CI validation gates.

### `run-qemu-detached.sh`
* **Summary:** Launches a background headless QEMU virtual machine attached to a build ISO with forwarded SSH and serial console logging.
* **When to Use:** Used for rapid local end-to-end ISO testing without physical bare-metal hardware.

### `generate-mock-certs.sh`
* **Summary:** Generates self-signed mock client certificates and keys in `custom-data/` for testing mTLS bypass workflows.
* **When to Use:** Used during offline testing when Step-CA / Companion services are simulated.

### `check-lab-setup.py`
* **Summary:** Connects to critical infrastructure components (Step CA, GDC Companion, Bootimus, Nexus) to audit the local lab network.
* **When to Use:** Pre-flight verification before running automated cluster installations.

### `check-bootimus-settings.py`
* **Summary:** Connects to the Bootimus PXE server and validates that registered Ubuntu images have autoinstall and nocloud parameters configured correctly.
* **When to Use:** Post-deployment validation gate to verify PXE readiness.

### `audit-machine-states.py`
* **Summary:** Queries local node state files in `/var/gdc-install/state/` to summarize the provisioning status of a machine.
* **When to Use:** Quick terminal inspection of node lifecycle state transitions.
