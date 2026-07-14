# GDC Unified Logging & Offline Inception Plan

This document outlines the architecture and tasks required to consolidate GDC activities logs into a persistent, unified location (`/var/gdc-install/logs/`) and resolve the first-boot APT hosted repository dependency failures that prevent the automatic installation of the Google Cloud SDK.

---

## 1. Architectural Blueprint

### 1.1 Consolidated Workspace Layout
All diagnostic and operational log assets will converge under `/var/gdc-install/logs/` with local system symlinks mapped from legacy `/var/log` targets for structural coherence and developer convenience:

| Actual Log Target File | Legacy Symlink Source | Description |
| :--- | :--- | :--- |
| `/var/gdc-install/logs/gdc-ansible-pull.log` | `/var/log/gdc-ansible-pull.log` | Real-time `ansible-pull` execution logging |
| `/var/gdc-install/logs/netplan-hydration.log` | `/var/log/netplan-hydration.log` | Subiquity `configure_netplan.py` compilation telemetry |

### 1.2 Offline Hosted Package Seeding Loop
To bypass the "empty hosted repository" HTTP `404` fatal check during initial `apt-get update` runs:
1. Stage pre-seeded `.deb` files persistently in `/var/gdc-install/packages/` during the Subiquity installation sequence.
2. In the `service_hubs` role (Task 02), query and programmatically upload all files matching `/var/gdc-install/packages/*.deb` to the newly established local `gdc-apt-hosted` repository.
3. Once populated, Sonatype Nexus automatically compiles and signs the `noble/main` Release and Packages metadata trees, enabling successful offline index handshakes.

---

## 2. Phase-Based Implementation Tracker

### Stage 1: Workspace & Packaging Layout
- [ ] Task 1.1: Register `"logs"` and `"packages"` folder paths in `gdc_install_directories` list in `src/ansible/vars/all.yml` to enforce `gdc-admin` user/group ownership on creation.
- [ ] Task 1.2: Refactor `src/build/templates/user-data.j2` to copy pre-seeded `.deb` archives to persistent `/target/var/gdc-install/packages/` instead of `/target/tmp/packages`.
- [ ] Task 1.3: Update `src/build/templates/user-data.j2` to write `configure_netplan.py` logs directly to `/target/var/gdc-install/logs/netplan-hydration.log` and establish the legacy `/target/var/log/netplan-hydration.log` symlink.

### Stage 2: Provisioner Log Stream Redirection
- [ ] Task 2.1: Refactor `src/build/templates/gdc-provision.service.j2` to programmatically create the `/var/gdc-install/logs` parent, symlink `/var/log/gdc-ansible-pull.log`, and redirect `ansible-pull` output stream in real-time via `tee`.

### Stage 3: Repository Inception & Seeding
- [ ] Task 3.1: Add a programmatic package-uploader task to the `service_hubs` role in `src/ansible/roles/service_hubs/tasks/main.yml` using `curl` to POST files to `/service/rest/v1/components?repository=gdc-apt-hosted`.
- [ ] Task 3.2: Restrict the local loopback `gdc-nexus.sources` repository template in `src/ansible/roles/host_foundations/tasks/main.yml` to only target `Suites: noble` and `Components: main` for the hosted repository.

### Stage 4: Diagnostics Engine Upgrades
- [ ] Task 4.1: Simplify log gathering in `bin/collect-node-diagnostics.sh` to copy the consolidated `/var/gdc-install/logs` folder recursively rather than extracting individual hardcoded files.
- [ ] Task 4.2: Program the human diagnostic report (`report.txt`) to print `"Ansible Pull Success: [true|false|Not-Run]"`.
- [ ] Task 4.3: Program the machine diagnostic report (`report.json`) to include the calculated `"ansible_pull_success"` string.

### Stage 5: Verification & Testing
- [ ] Task 5.1: Synchronize local playbook directories to the target node `192.168.9.248` over SSH and execute the modified provisioning suite using `test/sync_and_run_ansible.sh`.
- [ ] Task 5.2: Audit the guest's PATH and `/var/gdc-install/tools/google-cloud-sdk/` directory to confirm the `gcloud` SDK has been successfully compiled and registered.
- [ ] Task 5.3: Run `collect-node-diagnostics.sh` on the target guest and verify the resulting package compiles correctly, includes the consolidated GDC activities logs, and reports successful provisioning.
- [ ] Task 5.4: Run a full Cloud Build to compile and publish a fresh working `v0.1.72` ISO on Bootimus PXE.
