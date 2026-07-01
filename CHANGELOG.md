# Changelog

All notable changes to the `gdc-disk-provisioner` repository will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.11] - 2026-07-01

### Added
- **Programmatic Sonatype Nexus Bootstrapping (Stage 1b):** Implemented automated resetting of initial admin credentials and dynamic provisioning of all 7 core repositories (Docker Hosted/Proxy/Group on ports 5002/5001, APT Hosted/Proxy, and Raw Hosted/Proxy) completely offline. Added dynamic GPG signing keypair generation on the box for GGD local APT repository metadata validation.
- **Administrative Sudo & Keys Provisioning (Stage 8):** Automated the creation of the system user `gdc-admin` and group `gdc-admin`, deploying passwordless sudo configs under `/etc/sudoers.d/gdc-admin` and injecting configured administrator SSH public keys.
- **OS Package Slimming:** Reduced the node's attack surface and footprint by purging redundant system snap packages (`snapd`, `lxd`, and `x11-common`).
- **Enriched Diagnostics Engine (`collect-diagnostics.sh`):** Rewrote the diagnostics collector to incorporate systemd active run-state checking, listening port mapping audits, and local service health handshakes. Included complete CPU, RAM free space, file mounts fstab, Netplan, and GDC configurations gathering.
- **Dynamic L3 Network Connectivity Checks:** Incorporated a dynamic, non-hardcoded Network Connectivity Check section auditing interfaces, gateways, and cross-interface isolation at run-time, including a full DNS/TCP port 443 readiness check for all 25 GDC Google Cloud endpoints on both interfaces.
- **Upgraded Machine-Parsable Diagnostics Outputs:** Built an inline Python-driven JSON compiler producing highly legible `report.txt` and fully valid, structured `report.json` outputs carrying dynamic `inotify` watches/instances and system health specifications.

### Fixed
- **Sonatype Nexus HTTP 415 & 503 Errors:** Resolved the Sonatype Nexus HTTP 415 password-reset error by explicitly passing `Content-Type: "text/plain"`, and resolved the Sonatype Nexus 503 REST API race-condition by introducing an active HTTP status validator loop.
- **Cloud Build Gitea Pre-Seeding checkout mismatch:** Resolved the pre-seeding checkout mismatch inside Gitea by enforcing temporary git initialization during compile-time, excluding heavy caches to avoid the 4 GiB `.pack` file size limit.
- **Default Single-Disk Compile Layout**: Defaulted compile-time static layout of the ISO to Single-Disk `nvme0n1` to prevent Subiquity startup aborts on hardware.
- **Subiquity Webhook Reporting Crash**: Fixed the Subiquity reporting webhook crash by passing `X-Client-Cert-CN` via URL query parameters, fully supported by our upgraded log companion.

## [0.0.85] - 2026-06-30

### Fixed
- **Subiquity UEFI Bootloader Verification (`grub_device`):** Configured `grub_device: true` on the EFI partition (`partition-efi`) in `storage_config.j2`, `storage_config_uefi_single.yaml`, and `storage_config_uefi_dual.yaml` templates. This fixes the Subiquity `needs_bootloader_partition()` lookup error which crashed installation loops on physical UEFI bare-metal hardware.
- **Boot Validation Partition Flags:** Corrected EFI partition flags from `flag: boot` to `flag: uefi` and removed legacy bios grub actions from partition-script targets, allowing GDC images to boot to absolute completion on modern physical bare-metal hardware.

## [Unreleased] - 2026-06-25

### Added
- **Modular Stage-Gate Release Pipeline (`Makefile`):** Re-architected the monolithic, single-pass build pipeline into 9 discrete, named lifecycle stages and targets (`check-env`, `deps`, `extract`, `hydrate`, `validate`, `assemble`, `test-static`, `test-dynamic`, `deploy`, `publish`), fully orchestrating and automating them inside `src/build/Makefile`.
- **Declarative Jinja2 Templating (`render_templates.py`):** Fully decoupled all dynamic text-replacement shells into clean, isolated Jinja2 templates (`user-data.j2`, `storage_config.j2`, `netplan.j2`, and systemd service units), introducing robust quote-stripping and a fail-early validation parser that checks for mandatory build variables.
- **Pre-flight Static Validator (`validate-hydrated-files.sh`):** Engineered a pre-flight validation gate that runs `cloud-init schema --annotate` to verify cloud-init syntax, `systemd-analyze verify` to parse service structures, and `pylint --errors-only` to validate build code *prior* to packing, catching syntax bugs early.
- **Harness Security & E2E Validation (`test/run_qemu_e2e.sh`):** Hardened QEMU testing by mapping SSH traffic strictly to loopback `127.0.0.1:2222` to prevent LAN eavesdropping, added fail-fast interactive installer detection, and programmed an SSH validation suite checking dynamic LVM sizes and pubkey/password entries.
- **Sealed Provenance Manifests & Symbolic Target Promotions:** Automatically generates detailed JSON release manifests containing tool, compiler, and dependency checksum stats, and promotes verified builds via atomic symbolic links.
- **Decoupled Orchestrator Scripts:** Split the monolithic `buildAll.sh` into two distinct scripts: `./build-builder.sh` (for compiling and registering the tooling build container) and `./build-iso.sh` (for remastering the custom GDC ISO and deploying it to Bootimus PXE), letting developers build the ISO completely independently from the container-builder job!
- **Parameterized Sync & Scan Retries:** Introduced and documented `BOOTIMUS_SCAN_RETRIES` and `BOOTIMUS_SCAN_DELAY` parameters in `src/build/build.env` with detailed mathematical justifications based on a 3.7GB ISO transfer over a 400Mbps connection.
- **Automated Sandboxed Netplan Validator:** Integrated a custom pre-flight validation check into `bin/validate-hydrated-files.sh` that leverages Netplan's actual parser (`netplan generate --prefix=...`) to statically lint the hydrated network configuration before assembling the bootloader ISO.
- **Persistent After Action Reports (AAR):** Introduced an automated State 6 reporting layout which compiles and archives detailed, persistent After Action Reports under `docs/reports/aar-v${ISO_VERSION}.md`.

### Changed
- **Governance Shift (`GEMINI.md`):** Updated the governance standards to include *Rule 1.9 (Prefer Declarative Templates over In-line Configuration)* and *Rule 2.3 (The "Do Not Guess" Principle)*, formally codifying the use of template-driven configuration and dynamic hardware probing.
- **CI/CD Pipeline Unification (`cloudbuild.yaml`):** Re-aligned Google Cloud Build pipeline steps to execute our standardized `make` targets, fully unifying the development and compilation loops across local developer machines and remote cloud runners.
- **Dynamic Placeholders in Templates:** Refactored `src/build/render_templates.py` to default `PHYS_IFACE` fallback to `__PHYS_IFACE__` instead of hardcoding `'eth0'`. This keeps the templated configurations inside the ISO dynamic, allowing Subiquity late-commands to dynamically replace them on the target host at installation time.

### Fixed
- **Cloud-Init Virtualenv Isolation:** Added `.venv/` to `.gcloudignore` to prevent uploading the host's Python virtual environment to Google Cloud Build, allowing the container runner to correctly provision its own native virtual environment.
- **Fail-Fast Pylint Import Correctness:** Patched `bin/validate-hydrated-files.sh` to run `pylint` via the virtual environment's Python interpreter (`python -m pylint`), allowing `pylint` to correctly import and validate `jinja2` and other dependencies.
- **GCS Sync Folder Target Correction:** Fixed `src/build/Makefile`'s release CP target to copy completed GDC ISO artifacts directly to the `/sync/` directory in GCS (rather than the bucket root), ensuring compatibility with Synology NAS synchronization and GCS bucket retention rules.
- **Bootimus Parameter Verification & Fail-Gates:** Refactored `src/build/bootimus.py` to fix type checker warnings, include `urllib.error`, and escalate verification failures to a hard exit (`sys.exit(1)`) to immediately flag clobbered/corrupted boot parameter configurations.
- **Robust Environment Preservation:** Patched `src/build/remaster.sh` to preserve initial environment overrides (such as `ISO_VERSION`) when loading static `build.env` defaults.
- **Dependency Loading Safeguard:** Updated `test/validate_iso_static.sh` to source `dependencies.env` to prevent unbound variable exceptions on local validation runs.
- **Netplan List Syntax & VRF Interfaces:** Patched `src/build/templates/netplan.j2` to dynamically generate the VRF interface list using Jinja2 loops and conditions, completely resolving the nested list double-brackets bug (`[['eth0']]`) that crashed Netplan generation during boot stages.
- **Build Container Package Checklist:** Appended the `netplan.io` package to `src/build/Dockerfile` to ensure the compilation container possesses native parsing and validation capabilities.

## [Unreleased] - 2026-06-18

### Added
- **GDC ISO Google Cloud Build Integration (`cloudbuild.yaml`):** Built a secure, unprivileged Google Cloud Build pipeline that retrieves the "blessed" source Ubuntu ISO from a dedicated source GCS bucket (`ISO_BLESSED_GCS_BUCKET`), remasters it inside a customized builder container, and uploads the completed, versioned GDC bootstrap ISO back to your GCS output bucket (`ISO_OUTPUT_BUCKET`).
- **GCS Folder-Scoped Lifecycle and Retention Policy:** Programmed an automated GCS retention sweep at the end of every Cloud Build run. Pushes new ISOs into a GCS `/sync/` folder, lists and sorts files chronologically, maintains a maximum of 5 active ISO builds in the `/sync/` folder, and automatically archives older ones to the `/archived/` folder.
- **Custom Builder Container (`Dockerfile`):** Authored an optimized Dockerfile inside `src/build/` to package standard remastering dependencies (`xorriso`, `rsync`, `git`, `make`, `curl`) as a reusable CI/CD container in Artifact Registry (GAR), shaving startup overhead and removing public network dependency.
- **Google Cloud Build Trigger Script (`build.sh`):** Developed a robust workstation trigger script enforcing the validation of mandatory environment variables (`PROJECT_ID`, `BUILD_VERSION`, `REGION`, `ISO_VERSION`) and support for the `ISO_OUTPUT_BUCKET` environment variable.
- **Self-Healing Container Build Script (`src/build/build.sh`):** Created a container builder script that compiles the custom builder Dockerfile and dynamically verifies/creates the target Artifact Registry repository if missing, guaranteeing smooth initialization.
- **Dynamic Variable Fallbacks in Makefile & Shell:** Upgraded `Makefile` and `remaster.sh` to load `build.env` defaults conditionally, allowing exported terminal environment variables to seamlessly take precedence without modifying committed configurations.
- **Synology NAS GCS Cloud Sync Integration:** Documented DSM's native Cloud Sync configuration mapping GCS's `/sync/` directory down to your local PXE volume `/volume1/iso_share/sync/`, ignoring the `/archived/` folder to save local NAS disk space.
- **Bootimus Automation CLI (`bootimus.py`):** Developed a Python 3 CLI tool (`src/build/bootimus.py`) to automate local PXE booting:
  * Securely authenticates via environment credentials or dynamically retrieves them from **Infisical**.
  * Triggers a remote filesystem scan (`POST /api/scan`) on the Bootimus server to discover newly synchronized GCS ISOs.
  * Corrected `api_request` header behavior to bypass server-side empty JSON parsing crashes.
  * Filters scan results via exact local filename matching to prevent index collisions.
  * Automates kernel/initrd extraction from newly imported ISOs, polling progress asynchronously until complete.
  * Formats and updates Bootimus's distro to `"ubuntu"`, boot method to `"kernel"`, and boot parameters dynamically matching exact local web-server paths.
  * Renders beautiful, Unicode tree-views of all registered ISOs and folders on your network boot server with exact extraction state auditing (using the **`🚧`** emoji next to unextracted ISOs) and group-based filtering (`--filter`).

## [Unreleased] - 2026-06-12

### Added
- **GDC Offline Cluster Turnup Spec (`GDC-SPEC-005-TURNUP`):** Designed the technical sequence for GDC standalone cluster turnup completely offline, using pre-seeded local container image groups inside Nexus port `5001` and configuring `bmctl` configuration YAMLs with dedicated `registryMirror` endpoints.
- **GDC Lifecycle Update Flows Spec (`GDC-SPEC-006`):** Documented both the **Stage 6A Low-Internet update (Offline Sideload)** and **Stage 6B Connected update (Reverse Tunnel)** pathways. Explicitly specified GDC-UPDATE-USB layouts, cryptographic manifest signatures, udev-triggering update daemons, outbound reverse VPN tunnels, Gitea pull-mirror sync configurations, and local operator warning/success audio beeps.
- **GDC Master Dependency Matrix (`GDC-SPEC-DEP-001`):** Created a unified, comprehensive dependency reference mapping all required binaries, tools, operating system packages, and pre-seeded cached assets utilized or updated during each of the five GDC bootstrap phases.
- **GDC Bootstrapping & Cluster Turnup Architecture (Stages 4 & 5):** Refined our core architectural roadmap inside `README.md` and spec `GDC-SPEC-003`:
  1. Relabeled and redefined **Stage 4 as "GDC Bootstrapping"**, representing Gitea and Nexus as **Bootstrap Dependency Interfaces** that serve Git playbooks, OCI container layers, Debian packages, and raw LLM weights completely offline.
  2. Created a new **Stage 5 called "Cluster Turnup"**, modeling the final offline GDC cluster deployment using local pre-seeded container registries via `bmctl` or GKE On-Prem APIs.
- **Dynamic Dual-Disk & Isolated TPM Verification Suite:** Refactored the core headless testing runner (`test/run_qemu_e2e.sh`) and upgraded specification `GDC-SPEC-004` to support:
  1. Automated dual-disk sparse block device emulation (System SSD 250G and Data SSD 350G) mapping into QEMU to test our multi-disk auto-sizing partitioned layouts.
  2. Isolated unique `swtpm` socket mapping dynamically generated via `mktemp` to allow parallel, non-colliding test runs on shared build runners.
  3. Formulated secure ephemeral SSH key standards, mapping temporary generated public keys on the ISO dynamically to prevent loopback eavesdropping on port 2222.
- **Isolated Cloud Sandbox Testing (GCE):** Scaffolded an on-demand, isolated cloud-testing framework (`test/gce_startup_test.sh` and `test/provision_gce_sandbox.sh`) that provisions a 250GB GCE Ubuntu 24.04 server. It loads our active Ansible playbooks at first-boot, mocks localhost Gitea and Nexus port sockets using netcat-loops to satisfy preflight checks, runs the complete provisioning suite in isolation, streams/polls GCE's serial console port for success logs, and executes mandatory cloud teardowns to guarantee zero cost-drift on build runners.
- **Ansible Playbook Verification Suite:** Implemented an automated testing harness (`test/verify_ansible.sh`) to validate the syntax, logic, and best-practice compliance of GDC playbooks. The suite supports:
  1. Tier 1 Static Syntax Checks (`ansible-playbook --syntax-check`) to detect compile errors or broken schemas.
  2. Tier 2 Local Dry-Run Check Mode (`ansible-playbook --check --diff`) to simulate task execution without host modifications, dynamically bypassing signed-commit validations during development.
  3. Tier 3 Best-Practice Linting (`ansible-lint`) to guarantee clean, standard-compliant, and fully idempotent code.
- **Ready-Linux Post-Install Configuration & Provisioning:** Expanded the localized Ansible bootstrap playbook (`src/ansible/local.yml`) and upgraded the specification `GDC-SPEC-003` to orchestrate complete post-install provisioning on first boot. Key features include:
  1. Persistently enabling and starting local Gitea and Nexus service daemons on the host target OS.
  2. Executing safe offline system-wide upgrades (`apt-get upgrade`) directed completely at the local Nexus proxy on port 8081.
  3. Designing a variable-driven package installation task that parses the space-separated `POST_INSTALL_PACKAGES` list from `build.env` and loops through them dynamically (e.g. `git`, `python3-pip`, `wireguard`).
  4. Formulating an environment configuration file `/etc/default/gdc-provision` setting `ANSIBLE_PULL_FLAGS` to dynamically toggle GPG `--verify-commit` on and off during development vs production.
  5. Deploying the local `ansible-pull` runner as a persistent root cron job.
- **Cryptographic Sideload Verification & Headless USB Updates:** Upgraded specification `GDC-SPEC-003` to introduce:
  1. Mandated local cryptographic validation of all sideloaded code and container images using GPG commit verification in `ansible-pull` and **Sigstore/Cosign** signature validations inside `containerd` image pulls.
  2. Designed a headless, automated USB updates trigger using custom `udev` rules, a systemd runner (`gdc-usb-updater.service`), and an automated shell script (`gdc-headless-update.sh`) that mounts updates on USB drives labeled `GDC-UPDATE-USB`, cryptographically validates the package signature, executes Git bundle/REST API imports to Gitea/Nexus, and generates console audio warning/success beep signals to the local operator.
  3. Added size-cap guardrails on pre-seeded ISO caches to prevent filesystem exhaustion on scaled single-disk builds.
- **Smart Goal-Based Installation Logging:** Implemented a robust logging and error-trapping wrapper framework across our Subiquity scripting interfaces and `/d/projects/google/gdc-disk-provisioner/src/build/generate_storage_config.sh`. Before executing any shell action, the system outputs explicit `[GDC-INSTALL-GOAL]` lines to syslog and the console. If a command crashes, a global bash trap triggers a diagnostic `[GDC-INSTALL-FAIL]` block, logging the exact line number, exit code, and context to completely eliminate cryptic Subiquity failures.
- **Dynamic Multi-Disk (1 vs 2 Disks) Partitioning:** Designed and implemented a dynamic storage configuration generator script (`src/build/generate_storage_config.sh`) that auto-detects physical disks, sorts them by size, and formats them dynamically. Single-disk systems of $\ge 250\text{GB}$ automatically scale partition sizes down to prevent disk exhaustion. Dual-disk systems isolate Gitea, Nexus, containment CRI, and etcd transaction-intensive databases onto Disk 1, dedicating Disk 2 entirely to heavy storage block allocations (`/customer/local-disk` and `/customer/sds`), completely eliminating disk I/O latency spikes on etcd.
- **Installation Sequence & Overlapping Gaps Spec (`GDC-SPEC-002-SEQ`):** Formulated a comprehensive timeline mapping out the entire 16-minute bootstrapping lifecycle. Conducted a vulnerability and race-condition analysis, detailing how we solve the "Chicken-and-Egg" LUKS-to-TPM transition (using temporary boot keyfiles), resolve Gitea/Nexus startup delays (wait-for-port handshakes), and prevent serial logging deadlocks (timeout loops).
- **Machine Database & Cloud Verification Requirements (`GDC-SPEC-005`):** Formulated technical, algorithmic, and data requirements for the GCP Cloud Enrollment App and Machine Database. Documented the manufacturer TPM CA storage, the golden platform PCR profile schema, the pre-registered node inventory tables, and the sequential algorithmic checks (TPM authenticity, Quote signature validation, Anti-replay challenge, and Golden baseline profile matching) necessary to issue TPM-sealed Device TLS identities safely.
- **TPM 2.0 Remote Attestation & Identity:** Formulated a complete cryptographic handshake sequence enabling physical nodes to prove their authenticity to GCP Cloud Apps during the initial boot. Designed the process of harvesting the unique vendor EK Certificate, creating an AK (Attestation Key), executing cryptographic boot quotes (measuring Secure Boot PCR 7 and system file PCR 9), and requesting Intermediate CA signed Device Identity TLS certificates using un-extractable PKCS#11 TPM-bound keys.
- **Automated TPM 2.0 Boot-Unlocking:** Documented and verified the exact step-by-step sequence to auto-unlock the encrypted GDC storage disk at boot. Configured `systemd-cryptenroll` to dynamically generate a key, bind it to hardware registers PCR `0+2+7` (Secure Boot state), configure the target `/etc/crypttab` with the `tpm2-device=auto` and `discard` flag, update `initramfs` driver scopes, and wipe the insecure baseline passcode once recovery key escrows are securely stored.
- **GCP Logging Variables & Proxy Design:** Incorporated target `PROJECT_ID` and `REGION` variables in the build workspace (`src/build/build.env`). Evaluated the feasibility of live-boot logging, selecting an un-compromised, highly secure webhook proxy model (using Subiquity webhooks targeting the local Admin Workstation) to prevent service account credential leaks on the physical bootloader ISOs.
- **Service Boundary Integration Tests:** Implemented a new, dedicated test script (`test/verify_service_integration.sh`) that dynamically validates:
  1. Gitea's read-only push prohibition by attempting an unauthorized local commit push and asserting hook rejection.
  2. Gitea's local read-only fetch and replication capability.
  3. Nexus's OCI proxy registry pull capabilities using the newly introduced, fully configurable `TEST_PULL_OCI_IMAGE` parameter.
- **Local Build Caching & Isolation:** Developed a localized, non-checked-in caching folder (`.cache/`) to hold large binary assets. Specifically established `.cache/isos/` (for caching official base OS releases), `.cache/binaries/` (for Gitea/Nexus installers), and `.cache/blobs/` (for offline registry sync caches). Added `.cache/` and `build-workspace/` to `.gitignore` to protect the repository from accidental multi-gigabyte check-ins.
- **First-Boot Self-Test Playbook:** Created our initial GDC Ansible bootstrap playbook (`src/ansible/local.yml`) which runs on first-boot as part of the `ansible-pull` sequence. It holds execution until Gitea (port 3000) and Nexus (port 8081) have started, registers a "Hello World" task, queries and logs target partition structures (`lsblk`), and tests external network connectivity (`ping 8.8.8.8`) with graceful fallbacks.
- **ISO Verification & Testing Suite:** Scaffolded a dual-tier testing suite (`test/validate_iso_static.sh` and `test/run_qemu_e2e.sh`) to perform non-root file inventory/schema checks, dynamically provision 400G virtual disks in QEMU/KVM, and programmatically monitor serial logs headlessly for installation success signals.
- **Specification `GDC-SPEC-004` (ISO Verification & E2E Testing):** Formulated the verification framework spec, detailings static schema checks, emulated hardware profiles, `swtpm` TPM 2.0 mapping, and SSH assertion suites.
- **Rapid ISO Build and Upload Pipeline:** Implemented automated build scripts (`src/build/build.env`, `src/build/remaster.sh`, and `src/build/Makefile`) to handle rapid ISO remastering, UEFI GRUB modification, local NoCloud configuration injection, and automated publishing/uploads to local NFS and Google Cloud Storage (GCS) buckets.
- **`README.md` Refactoring:** Restructured from a basic placeholder into a comprehensive architectural master plan including an interactive MermaidJS Hub-and-Spoke diagram, list of core goals, and detailed disk mappings.
- **Specification `GDC-SPEC-001` (ISO Build Pipeline):** Established the design spec for the `xorriso`/`mksquashfs` build workflow, including Live-ISO RAM mounting overlays for local Gitea and Nexus services.
- **Specification `GDC-SPEC-002` (Baseline Installer):** Modeled the Subiquity Autoinstall configuration and detailed the GDC Bare Metal required Enterprise LVM disk layouts.
- **Specification `GDC-SPEC-003` (Ready-Linux Provisioning & Sideloading):** Modeled the transition from installation to active OS boot. Documented `ansible-pull` tasks, TPM 2.0 LUKS/SSH configuration, CIS Benchmark hardening controls, and physical USB/REST API sideloading workflows.
- **Agent Governance (`GEMINI.md`):** Formulated rules-based instructions for AI agents working in this repository to prevent deviations from isolated architecture and performance standards.
- **Glossary Glossary (`DICTIONARY.md`):** Defined core domain terms such as "Baseline", "Ready-Linux", "Sideloading", "Hub-and-Spoke", "SDS", and "local-disk".
- **Progress Tracker (`PROGRESS.md`):** Added a master feature checklist and execution scorecard to trace upcoming milestones.

### Architectural Decisions (ADRs)
1. **Tooling Choice (Xorriso over Packer):** Remastering using standard Linux filesystem tools is chosen over Packer VMs due to its speed, deterministic outputs, and direct Infrastructure-as-Code integration.
2. **Hub-and-Spoke Service Separation:** Ephemeral services are selected to run from a writeable RAM partition overlay (`OverlayFS`) on the bootloader ISO to completely decouple package/code fetches from external network connections.
3. **Dedicated Performance LVs:** Disks are partitioned into dedicated logical volumes for logs, metrics, containerd, and etcd. Isolating etcd onto its own physical-backed block storage isolates writing latencies to satisfy GDC bare metal requirements.
