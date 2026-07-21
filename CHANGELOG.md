# Changelog

All notable changes to the `gdc-disk-provisioner` repository will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.116] - 2026-07-21

### Added
- **Target-Side TPM 2.0 Unsealing Integration:** Programmed a native Ansible task in our `security_hardening` playbook role that deploys a custom `gdc-tpm2` initramfs-tools hook, copying systemd-tpm2 tokens and exact 24.04-native TSS2 dynamic libraries into the target OS boot ramdisk to support secure, automatic unlocking on reboot.
- **Path-Agnostic Deletion & Verification Hook (`zz-gdc-blacklist`):** Engineered a standard `initramfs-tools` hook that searches for blacklisted fTPM-deadlocking drivers (`amd_sfh` and `pcie_mp2_amd`) across legacy `/lib/` and UsrMerged `/usr/lib/` staging paths using a path-agnostic `find` command.
- **Strict Count-and-Abort Gate:** The new `zz-gdc-blacklist` hook dynamically counts matching driver files before pruning, deletes them, and asserts that the remaining count is exactly `0`, failing immediately if any blacklisted files persist to prevent quiet-room regressions.
- **Static Command & Option Auditor:** Integrated an automated command-line options validation gate inside `test/validate_artifacts.py` that recursively extracts shell commands from the hydrated `user-data` configuration and dynamically parses their argument flags against local manual pages (`man`) or help screens (`--help`).
- **Consecutive-Success Stability Verification Loop:** Refactored `src/build/bootimus.py` with an unbuffered feedback control loop requiring boot configurations to persist in their correct, enabled states across **4 consecutive checks (20s duration)**, successfully defeating asynchronous background catalog sync clobbers on the Synology Bootimus server.

### Changed
- **Initramfs Generator Reversion:** Reverted the bootloader and initrd compiler back from `dracut` to native **`initramfs-tools`** and **`cryptsetup-initramfs`**, bringing the compressed initrd size down from 200MB+ to a highly optimized **35MB** to prevent early UEFI memory fragmentation.
- **Alphabetical Hook Ordering:** Prepend `zz-` to our custom initramfs hook (`zz-gdc-blacklist`) to force it alphabetically after the system's `udev` and `zz-busybox-initramfs` hooks, ensuring the deletion sweep runs at the absolute end of the staging phase.

### Fixed
- **Transition Key Naming Mismatch:** Fixed the validation assertion in `user-data.j2` to search for either `temp_key.key` or `crypt-system.key`, accommodating `cryptsetup-initramfs`'s native behavior of renaming the compiled key file to match its mapper target.
- **Bootimus API Timeout Protection:** Added a 30-second socket timeout to all `urllib.request.urlopen` requests inside `src/build/bootimus.py` to prevent indefinite blocking hangs during busy filesystem scans.

## [0.1.105] - 2026-07-20

### Added
- **Dynamic Test Execution & Discovery (`bin/run_all_tests.py`):** Implemented an automated python test runner that dynamically discovers and executes all python unit tests (capturing test pydocs as verification criteria) and static validations, exporting the serialized results cleanly to `build-workspace/test_results.json`.
- **Dynamic Category-Grouped Reports:** Upgraded `generate_build_report.py` to consume `test_results.json` and dynamically render detailed, category-grouped verification tables in the human-readable Markdown After Action Report, requiring zero maintenance as tests are added or changed.

### Changed
- **Subprocess Loop Optimization:** Shaved build report compilation time from 200+ seconds to under 0.1 seconds by bypassing the sequential `apt-cache show` loop for pre-seeded offline packages.

## [0.1.104] - 2026-07-20

### Added
- **Five-Point Pre-Reboot Initrd Validation:** Appended an automated post-compilation check inside Subiquity `late-commands` that uses `lsinitrd` to programmatically assert the exact state of the generated initrd (presence of the transition key, `crypt` and `lvm` modules, physical NVMe/SATA storage drivers, and absolute omission of fTPM-deadlocking drivers) before the system is allowed to reboot.

### Changed
- **Generic Bootloader Compilation:** Configured `dracut` to build a 100% generic, non-deadlocking ramdisk (`hostonly="no"` and `omit_drivers+=" pcie_mp2_amd amd_sfh "`) inside the Subiquity installer chroot to prevent NVMe storage driver exclusions and early-boot AMD hardware lockups.

## [0.1.103] - 2026-07-20

### Added
- **Dracut LVM Module Integration:** Explicitly enabled `lvm` module packaging in `user-data.j2` late-commands (`add_dracutmodules+=" crypt lvm "`) to resolve the first-boot NVMe-blind hang, allowing the target kernel to successfully map logical volumes on boot.

### Changed
- **Persistent Hardened Module Configurations:** Patched the security hardening first-boot Ansible playbook to rewrite `/etc/dracut.conf.d/gdc.conf` to permanently retain generic crypt/lvm and blacklisted driver configurations across future system and kernel security updates.

## [0.1.102] - 2026-07-20

### Fixed
- **Stale blkid Cache LUKS Resolution Fallback:** Resolved a critical installation bug where Subiquity skipped passwordless transition keyfile enrollment due to `blkid` returning an empty string. Introduced a bulletproof fallback that parses `/target/etc/crypttab` and queries active mappings directly from `cryptsetup status` inside the Live CD.

## [0.1.101] - 2026-07-20

### Added
- **Dracut Bootloader Migration:** Migrated Ubuntu 24.04 noble bootloader and ramdisk generation from `initramfs-tools` to `dracut` and `cryptsetup` packages to natively support systemd-based early-boot TPM unsealing.
- **At-Boot AMD Module Blacklisting:** Appended `modprobe.blacklist=pcie_mp2_amd,amd_sfh` directly to GRUB command-lines in the installer config, fallback config, and the target's `/etc/default/grub` to completely bypass early-boot fTPM PSP deadlocks on AMD platforms.

## [0.1.57] - 2026-07-11

### Added
- **Dynamic Telemetry Parameter Injection (bootcmd):** Integrated a cloud-init `bootcmd` background python script in `src/build/templates/user-data.j2` that dynamically queries the target machine's unique SMBIOS product UUID and MAC address of the primary connected network interface, then parameterizes Subiquity's reporting webhook endpoint with these parameters (`product_uuid` and `mac`) before Subiquity initializes reporting.

### Changed
- **Dynamic autoinstall-user-data Preference:** Updated the `early-commands` custom partition script in `user-data.j2` to read `/run/installer/autoinstall-user-data` if it exists (instead of `/cdrom/nocloud/user-data`), ensuring the dynamically parameterized webhook URL persists when merging LVM storage configurations.

## [0.1.43] - 2026-07-08

### Added
- **Declarative Package Configuration (`packages_config.yaml`):** Implemented a structured YAML configuration to govern GDC pre-seeded package include/exclude rules, decoupling includes (`platform_required` and `customer_added`) from implementation scripts.
- **Test-Driven Python Pre-seeding Engine (`preseed_packages.py`):** Re-engineered the caching engine from raw shell to object-oriented Python, supporting comprehensive unit test suites covering configuration ingestion and regex-based exclusions.
- **Fail-Safe Automatic Telemetry Uploads:** Configured `collect-node-diagnostics.sh` and the first-boot playbook to automatically compile and upload telemetry tarballs to `gdc-companion.ensor-labs.com` upon completion via secure POST webhooks.
- **Target OS Version Compatibility Guardrails:** Programmed strict container-to-target version assertions inside `preseed_packages.py` to prevent library pollution during recursive dependency resolutions.

### Changed
- **Padded LVM Logical Volumes:** Resized metrics, containerd, and etcd partitions up by 2-3 GiB to satisfy GDC available block capacities while absorbing filesystem metadata taxes.
- **Superblock Wiping Integration:** Configured `wipe: superblock-recursive` on system disks and `wipe: superblock` on LVM partition elements in all four storage configs to support 100% automated reinstallations on previously structured physical drives.

### Fixed
- **Defensive UFW Hardening:** Patched the `security_hardening` role to retrieve service facts and stop/disable UFW only if the service exists, avoiding fatal playbook exits on pre-slimmed target hosts.
- **False-Positive etcd Clean Patches:** Corrected `/var/lib/etcd` dirtiness checks to ignore standard ext4 `lost+found` system folders.

## [0.1.26] - 2026-07-06

### Fixed
- **Subiquity Offline Package Installation (`gdc-apt-proxy`):** Fixed a critical post-install crash during the `install_ansible` stage of Subiquity, which threw `Command 'system-install' --download-only -- ansible returned non-zero exit status 100`. The root cause was that `ansible` is not part of the standard Ubuntu `/cdrom` file repository. When we locked sources to `file:///cdrom/` in the previous version, Subiquity could not locate the Ansible package offline. Resolved this by updating `src/build/templates/user-data.j2` to point the Subiquity `primary` and `security` APT mirrors to the **local Live ISO Nexus server** (`http://127.0.0.1:8081/repository/gdc-apt-proxy/`). Since the Live ISO boots Gitea and Nexus as part of its live service hub, and the offline GDC ISO pre-bundles a complete, offline-cached package pool in the outer ISO directory, Subiquity can fetch and install `ansible`, `git`, and all Python/system dependencies completely offline with zero internet access, resolving the installation crash.

## [0.1.24] - 2026-07-06

### Added
- **End-to-End Build & Verify Pipeline (`build-iso.sh`):** Integrated the automated Bootimus non-interactive boot option auditor directly into the main remastering entrypoint. The build job now acts as an all-in-one pipeline that compiles the ISO in Google Cloud Build, waits for extraction, registers the new image, and triggers an immediate compliance sweep to guarantee that all 22 Ubuntu boot records remain completely safe from interactive prompt freezes.

### Fixed
- **Subiquity Offline Installation Sandbox (`file:///cdrom/`):** Fixed an installation failure on offline nodes during the Subiquity filesystem probe and driver search phases. Under air-gapped/offline configurations, Subiquity attempts to contact default public Ubuntu APT repositories (e.g., `security.ubuntu.com`), which we map to `127.0.0.1` to prevent network timeouts. However, on nodes with low memory or packet drops, the full 4GB ISO download over HTTP (`url=http://...`) can result in incomplete `/cdrom` reads, causing APT cache lookups to fail with a fatal `Failed to retrieve available kernel versions` error. Solved this by explicitly overriding Subiquity's `apt:` block in `src/build/templates/user-data.j2`. We now configure the `primary` and `security` mirrors to point strictly to `file:///cdrom/` and set `preserve_sources_list: false`. This isolates all APT checks to local, zero-network, local-CDROM operations, rendering the installation completely self-contained and bulletproof in offline environments.

## [0.1.23] - 2026-07-06

### Fixed
- **TPM 2.0 Boot Unlocking Regression (`systemd-initramfs`):** Identified and resolved a critical boot failure where rebooting a TPM-sealed GDC node gets stuck at the `Please unlock disk crypt-system` console prompt, complaining `cryptsetup: WARNING: crypt-system: ignoring unknown option 'tpm2-device'`. The root cause is that Ubuntu's default `initramfs-tools` uses standard POSIX shell-based scripts during boot, which do not recognize systemd-specific options like `tpm2-device`. Resolved this by installing the `systemd-initramfs` package in `gdc_core_packages` (via `src/ansible/vars/all.yml`). This switches the initramfs to use a systemd-based boot runtime, ensuring that `systemd-cryptsetup` and `systemd-cryptenroll` natively parse `/etc/crypttab`, communicate with the physical TPM 2.0 chip, and automatically unlock the disk on boot.
- **Node Recovery Utility (`recover-tpm-unseal.sh`):** Created an automated recovery script in `bin/recover-tpm-unseal.sh` that can be run from the Live CD of a bricked node. The script unlocks the LUKS partition using the motherboard TPM, mounts root and boot partitions, chroots into the environment, installs `systemd-initramfs` and `cryptsetup-initramfs`, and regenerates the boot ramdisks with correct systemd and TPM2 TSS hooks.

## [0.1.21] - 2026-07-06

### Added
- **Centralized Version Tracker (`VERSION`):** Created a central, Git-tracked `VERSION` file in the project root to manage the active ISO version. Upgraded `build.sh` and `build-iso.sh` to read and auto-increment the version in both `VERSION` and `.envrc` in lock-step.
- **Git-Ignored Host Overlay (`add-hosts`):** Supported an `/etc/hosts`-formatted file at `src/build/add-hosts` allowing custom DNS overrides to be injected during template hydration without leaking local setups to git.
- **Flexible Host Persistence (`PERSIST_ADD_HOSTS`):** Introduced a configurable boolean mapping custom host overrides strictly to the live installer (`early-commands` only) or persisting them into `/target/etc/hosts` (`late-commands`) post-boot.
- **Automated Ingestion & Diagnostics summary table:** Upgraded `bin/gdc-diagnostics-transmit-analyze.py` to automatically upload extracted node tarballs to the `gdc-companion` API. Added active port-22 scans to identify possible GDC nodes stuck in pre-boot, print their console crash cart snippets, and output a beautifully aligned console ASCII summary table representing all diagnostic stages.
- **Bootimus Safety Locks & Delayed Verification:** Added a software-enforced API lock in `src/build/bootimus.py` that temporarily disables newly scanned ISOs during kernel extraction to prevent premature PXE boots. Implemented a Stage 2 delayed check (15-second background transaction sleep) to ensure the server-side sync does not clobber custom autoinstall parameters.

### Fixed
- **TPM 2.0 Boot-Unlocking:** Explicitly wrote `CRYPTENROLL=y` to the target `/etc/cryptsetup-initramfs/conf-hook` during both the CD late-commands phase and the post-boot security hardening playbook. This ensures that the rebuilt `initramfs` ramdisk compiles systemd's cryptenroll and TPM2 TSS libraries, completely resolving the fatal unsealing boot-loop issue (`ignoring unknown option 'tpm2-device'`).
- **Subiquity Storage Curtin formatting Crash:** Patched `src/build/templates/storage_config.j2` to add `wipe: superblock-recursive` to both system and data disk storage configurations. This recursively wipes stale LUKS, LVM, or superblock signatures before partitioning, preventing Curtin from trying to re-open locked containers on re-runs.
- **Crash Cart CLI Helper:** Updated `bin/bootloader-crash-cart.sh` to immediately print copy-pasteable root shell commands (without `sudo`) and create `/etc/ssh/sshd_config.d/99-root-ssh.conf` to override default systemd-sshd rules.

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
