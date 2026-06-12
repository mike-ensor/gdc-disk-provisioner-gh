# Changelog

All notable changes to the `gdc-disk-provisioner` repository will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] - 2026-06-12

### Added
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
