# GDC Disk Provisioner - Administrative Binaries & Utilities

This document outlines the administrative scripts, diagnostic tools, and operational utilities across the repository. Tools are categorized by functional domain and execution context (whether they run on the workstation or inside the deployed ISO).

---

## Directory & Lifecycle Layout

| Script / Command | Subcommand | Base Path | Execution Context | Included in ISO? | Primary Functionality | Brief Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`gcp-authentication.sh`** | *N/A* | `bin/auth/` | **Target Machine** | **Always** (`/usr/local/bin/auth/`) | Credential & Container Registry Bridge | Injects `gcloud` tokens into containerd (`certs.d/gcr.io/hosts.toml`) and `/run/gdc-auth/` so Anthos images can be pulled when Companion is disabled or offline. |
| **`create_cluster.sh`** | *N/A* | `bin/cluster/` | **Target Machine** | **DEBUG builds only** (`/usr/local/bin/cluster/`) | Standalone Cluster Turnup | Idempotently provisions a bare-metal cluster using `bmctl`; configures cluster YAML, generates WIF keys, and runs preflight checks. |
| **`verify-upgrade-readiness.sh`** | *N/A* | `bin/cluster/` | **Target Machine** | **DEBUG builds only** (`/usr/local/bin/cluster/`) | Kernel Upgrade Auditor | Verifies Dracut, GRUB, and cryptsetup settings on the node before `apt upgrade` to ensure TPM hooks and AMD blacklists are preserved. |
| **`run-storage-benchmark.py`** | *N/A* | `bin/cluster/` | **Target Machine** | **DEBUG builds only** (`/usr/local/bin/cluster/`) | Storage Capability Benchmark & Guard | Executes synthetic storage benchmark via `kubestr fio` with pre-flight guards on `longhorn-system` readiness and cluster health. |
| **`helm`** | *N/A* | `custom-data/tools/helm/` | **Target Machine** | **Always** (`/usr/local/bin/helm`) | Kubernetes Package Manager | Official Helm CLI binary used to deploy and configure Kubernetes workloads, charts, and CSI drivers (e.g. Longhorn). |
| **`kubestr`** | *N/A* | `custom-data/tools/kubestr/` | **Target Machine** | **Always** (`/usr/local/bin/kubestr`) | Storage Capability Benchmark CLI | Official Kubestr CLI binary used to discover storage classes and execute storage performance benchmarks (`kubestr fio`). |
| **`oras`** | *N/A* | `custom-data/tools/oras/` | **Target Machine** | **Always** (`/usr/local/bin/oras`) | OCI Registry As Storage CLI | Official ORAS CLI binary used to push, pull, and distribute arbitrary OCI artifacts and container packages offline. |
| **`gdc-node-ops.sh`** | `push-facts` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Fact Injection & State Reset | Validates local JSON against `machine-schema.json`, uploads to `/var/gdc-install/state/gdc-fact-manual.json`, wipes `cluster-ready.json`, and restarts `gdc-provision.service`. |
| | `push-playbook` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Hotfix Playbook Sync | Hydrates local Ansible variables and syncs playbooks into the remote node's local Gitea repository to test changes without rebuilding the ISO. |
| | `push-token` | `bin/local/` | **Local Workstation** | **No** (Host tool) | GCP Bearer Token Sideload | Extracts local workstation OAuth2 access token via `gcloud` and pushes it to remote containerd and `/run/gdc-auth/` directories. |
| | `rotate-token` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Force Token Rotation | Triggers `/usr/local/bin/refresh-gdc-credentials.sh` on target nodes and verifies that the rotated GCP Bearer token is valid and active in gcloud. |
| | `reset-pxe` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Remote PXE Boot Scheduler | Queries active network interface MAC addresses on target nodes and uses `efibootmgr` to schedule a one-time PXE reboot (BootNext). |
| | `refresh-telemetry` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Diagnostics Telemetry Trigger | Pings nodes and triggers on-device `/usr/local/bin/gdc-collector` to force an updated report payload into the GDC Companion API. |
| **`gdc-forensics.sh`** | `fetch` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Remote Log Harvester | Deploys the forensics collector over SSH to a failing node, runs collection, downloads the compressed tarball locally, and cleans up remote artifacts. |
| | `collect` | `bin/local/` | **Target Machine** | **No** (Pushed on-demand during `fetch` or run manually) | Local Host Log Bundler | Gathers `/var/log/installer`, cloud-init logs, `lsblk`, `dmesg`, and autoinstall configs into a `/tmp/gdc-installer-forensics-*.tar.gz` bundle. |
| | `inspect` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Forensic Bundle Analyzer | Extracts a forensic archive and runs automated regex diagnostics against kernel boot command lines, Subiquity logs, and config YAMLs. |
| **`gdc-crash-cart.sh`** | `snippet` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Emergency Access Generator | Generates the root password and SSH configuration block to paste into a serial console or BMC/KVM when early boot fails before cloud-init. |
| | `scan-subnet` | `bin/local/` | **Local Workstation** | **No** (Host tool) | Crashed Node Scanner | Executes multi-threaded ICMP ping and TCP port 22 probing across a CIDR subnet to locate nodes that received unknown DHCP leases. |
| | `recover-tpm` | `bin/local/` | **Target Machine** (LiveCD) | **No** (Run from LiveCD recovery shell) | TPM 2.0 Boot Unseal Repair | Unlocks encrypted system disks via TPM 2.0, mounts filesystems, chroots into target OS, repairs `cryptsetup-initramfs` hooks, and rebuilds initramfs. |
| **`crash-cart-scan-subnet.py`** | *N/A* | `bin/local/` | **Local Workstation** | **No** (Backend helper) | Subnet Discovery Engine | Python multi-threaded scanning backend invoked by `gdc-crash-cart.sh scan-subnet`. |
| **`sync-schemas.sh`** | *N/A* | `test/bin/` | **Local Workstation / CI** | **No** (Test/Dev tool) | Schema Parity & Synchronization | Pulls latest `docs/machine-schema.json` from `gdc-companion` or asserts parity via `--check` to prevent divergence across repos. |
| **`update-dependencies.sh`** | `check`, `update-*` | `bin/local/` | **Local Workstation / CI** | **No** (Dev/CI tool) | Dependency & Package Manager | Audits upstream versions, updates `dependencies.env` SHA256 hashes, pre-seeds Noble `.deb` packages, and syncs to GCS cache. |

---

## 1. Authentication / Authorization (`bin/auth/`)

### `gcp-authentication.sh`
* **Target OS Path:** `/usr/local/bin/auth/gcp-authentication.sh`
* **Summary:** Seeds Google Cloud credentials into containerd (`/etc/containerd/certs.d/gcr.io/hosts.toml`) and GDC runtime authentication (`/run/gdc-auth/access_token` and `/run/gdc-auth/adc_token.json`). Supports both direct token input (`--token`) and local `gcloud` resolution.
* **When to Use:** Used **IF** `GDC_COMPANION` is set to `FALSE` (or the Companion server is unreachable) and `gcloud` authentication was not automatically completed via mTLS during LiveBoot/FirstBoot, or when sideloading credentials from an operator workstation via `gdc-node-ops.sh push-token`. Allows `kubelet` and `containerd` to authenticate and pull Anthos images from `gcr.io`.
* **Options:** Includes `--help` (`-h`), `--token <TOKEN>` (bypasses on-node gcloud requirement), and `--dry-run`.
* **Dependencies:** `containerd`, `systemctl`, and optionally `gcloud` (if `--token` is omitted).

---

## 2. Cluster Operations (`bin/cluster/`)

### `create_cluster.sh`
* **Target OS Path:** `/usr/local/bin/cluster/create_cluster.sh`
* **Summary:** Provisions a Google Distributed Cloud (GDC) Bare Metal standalone cluster. Configures the cluster YAML, performs pre-flight assertions, and triggers `bmctl create cluster -c <name>`.
* **When to Use:** Executed during the `ClusterReady` stage after `linux-ready` operating system foundations have completed. Idempotent (skips if the cluster is already active).
* **Options:** Includes `--help` (`-h`), `--name`, `--ip`, `--project`, `--vip`, `--ingress`, `--lb-range`, and `--admin-email`.
* **Dependencies:** `bmctl`, `kubectl`, `gcloud`

### `verify-upgrade-readiness.sh`
* **Target OS Path:** `/usr/local/bin/cluster/verify-upgrade-readiness.sh`
* **Summary:** Audits Dracut, GRUB, and cryptsetup configurations on the target node to ensure AMD fTPM blacklists, polling mode, and TPM unseal hooks are preserved before running package updates.
* **When to Use:** Executed on a running GDC node prior to performing OS / kernel upgrades (`apt upgrade`).
* **Options:** Includes `--help` (`-h`) documenting check criteria and exit codes.
* **Dependencies:** `dracut`, `grub-probe`, `cryptsetup`

### `run-storage-benchmark.py`
* **Target OS Path:** `/usr/local/bin/cluster/run-storage-benchmark.py`
* **Summary:** Executes synthetic storage capability benchmarking against Kubernetes StorageClasses using `kubestr fio`. Enforces pre-flight guards on cluster connectivity and `longhorn-system` readiness, and extracts standardized performance metrics.
* **When to Use:** Executed after cluster turnup and Longhorn deployment to benchmark storage performance (IOPS, bandwidth, latency) before running production workloads.
* **Options:** Includes `--help` (`-h`), `--storage-class <SC>`, `--volume-size <SIZE>`, `--kubeconfig <PATH>`, `--timeout <SEC>`, `--state-file <PATH>`, `--json` (`--json-output`), `--dry-run`, `--skip-guard`, `--kubestr-path <PATH>`, and `--allow-download`.
* **Dependencies:** `kubectl`, `kubestr`, Python 3

---

## 3. Workstation Local Utilities (`bin/local/`)

All scripts in `bin/local/` are designed to be executed from the operator's local workstation.

### 3.1. Node Operations CLI (`bin/local/gdc-node-ops.sh`)

Unified operator tool to manage active edge nodes.

* **`gdc-node-ops.sh push-facts --node <IP> --facts <FILE>`**: Validates a local JSON fact file against `machine-schema.json`, uploads it to `/var/gdc-install/state/gdc-fact-manual.json` on the target node, wipes the `cluster-ready` completion state, and restarts `gdc-provision.service`. Supports `--user`, `--key`, `--schema`, `--dry-run`, and `--no-follow`.
* **`gdc-node-ops.sh push-playbook --nodes <IP(s)>`**: Rsyncs local development Ansible playbooks directly into the target node's local Gitea repository (`/var/lib/gitea/repos/gdc/bootstrap-playbooks.git`), optionally wipes a specific stage's state (`--resume-from`), and restarts `gdc-provision.service`. Supports `--user` and `--key`.
* **`gdc-node-ops.sh push-token --nodes <IP(s)>`**: Sideloads a Google Cloud OAuth2 Bearer token from the local workstation into remote node containerd registry credentials (`certs.d/gcr.io`) and `/run/gdc-auth/` runtime auth files without requiring `gcloud` or interactive login on the target machine. Supports `--nodes`, `--user`, `--key`, `--token`, `--account`, `--test-rotation`, and `--dry-run`.
* **`gdc-node-ops.sh rotate-token --nodes <IP(s)>`**: Triggers execution of `/usr/local/bin/refresh-gdc-credentials.sh` on target nodes, rotates the client mTLS certificate via Step CA, fetches a fresh token from Companion, and verifies that the new token is active in `gcloud`. Supports `--nodes`, `--user`, `--key`, and `--dry-run`.
* **`gdc-node-ops.sh reset-pxe --nodes <IP(s)>`**: Queries target nodes, identifies their active network interface MAC address, schedules a one-time UEFI PXE boot (BootNext) via `efibootmgr`, and reboots the machine. Supports `--user`, `--key`, and `-y`/`--yes`.
* **`gdc-node-ops.sh refresh-telemetry [NODE_IPS...]`**: Pings target nodes, invokes `/usr/local/bin/gdc-collector`, and forces an updated diagnostics ingestion into the GDC Companion API. Supports `--nodes`, `--user`, `--password`, `--key`, and `--companion-url`.

### 3.2. Forensics & Logging CLI (`bin/local/gdc-forensics.sh`)

Unified forensics tool for capturing and analyzing failed installations.

* **`gdc-forensics.sh fetch --node <IP>`**: Deploys the collector to a remote node, triggers log bundling, downloads the compressed tarball locally, and cleans up remote artifacts. Supports `--user`, `--key`, `--output-dir` (alias `--dest`), and `--inspect`.
* **`gdc-forensics.sh collect`**: Gathers `/var/log/installer`, `/var/log/cloud-init*.log`, `lsblk`, `dmesg`, `/proc/cmdline`, and autoinstall configs into a timestamped `/tmp` tarball. Supports `--dest` / `--output-dir`.
* **`gdc-forensics.sh inspect [TARBALL]`**: Extracts a forensics bundle and runs automated diagnostic regex checks against boot parameters, subiquity logs, and configuration YAMLs. Supports `--archive <FILE>`.

### 3.3. Emergency Recovery CLI (`bin/local/gdc-crash-cart.sh`)

Unified emergency recovery and subnet discovery tool.

* **`gdc-crash-cart.sh snippet`**: Prints the self-contained root password and SSH configuration block to paste into a serial console or IPMI KVM session when cloud-init fails to execute. Supports `--password <PASS>`.
* **`gdc-crash-cart.sh scan-subnet --cidr <CIDR>`**: Multi-threaded parallel ICMP ping and TCP port 22 scanner that identifies active nodes running in rescue or emergency mode on a subnet. Powered by `bin/local/crash-cart-scan-subnet.py`. Supports `-c/--cidr`, `-e/--exclude`, `-w/--workers`, `-t/--timeout`, `--ssh-user`, and `--ssh-pass`.
* **`gdc-crash-cart.sh recover-tpm`**: Automatically locates encrypted LUKS partitions, attempts auto-unlock via TPM 2.0 (with fallback to manual unlock), activates LVM volumes, mounts filesystems, chroots to rebuild initramfs with `cryptsetup-initramfs` and `tpm2-tss`, and cleanly unmounts. Designed for emergency execution from LiveCD recovery environments.

---

## 4. Build Validation & Lab Utilities (`test/bin/`)

* **`test/bin/sync-schemas.sh`**: Synchronizes `docs/machine-schema.json` from the upstream `gdc-companion` repository or checks for drift via `--check`.
* **`test/bin/validate-hydrated-files.sh`**: Statically lints and validates hydrated cloud-init, netplan, and systemd templates before ISO assembly.
* **`test/bin/generate_build_report.py`**: Compiles pipeline execution details, external binary signatures, preseed package counts, and test outcomes into canonical JSON and Markdown reports.
* **`test/bin/run_all_tests.py`**: Dynamic test runner that discovers and executes all python unit tests and static validation scripts, exporting results to `build-workspace/test_results.json`.
* **`test/bin/run-qemu-detached.sh`**: Launches a background headless QEMU virtual machine attached to a build ISO with forwarded SSH and serial console logging.
* **`test/bin/generate-mock-certs.sh`**: Generates self-signed mock client certificates and keys in `custom-data/` for testing mTLS bypass workflows.
* **`test/bin/check-lab-setup.py`**: Connects to critical infrastructure components (Step CA, GDC Companion, Bootimus, Nexus) to audit the local lab network.
* **`test/bin/check-bootimus-settings.py`**: Connects to the Bootimus PXE server and validates that registered Ubuntu images have autoinstall and nocloud parameters configured correctly.
* **`test/bin/audit-machine-states.py`**: Queries local node state files in `/var/gdc-install/state/` to summarize the provisioning status of a machine.
