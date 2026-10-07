# Automated NVIDIA GPU Driver & Toolkit Setup Design

**Date:** 2026-10-05  
**Author:** AI Product Manager / Systems Architecture Specialist  
**Target Systems:** Google Distributed Cloud (GDC) Bare Metal Nodes (Ubuntu 24.04 LTS)  
**Sample Verification Nodes:** `192.168.9.238` (GPU Attached - RTX 4000 SFF Ada), `192.168.9.242` (No GPU - AMD Phoenix APU)  

---

## 1. Context & Problem Statement

Google Distributed Cloud (GDC) for bare metal provisions physical server nodes from a custom remastered Ubuntu 24.04 LTS offline ISO. Following node installation, `gdc-provision.service` executes a multi-stage `ansible-pull` workflow bringing nodes from raw OS baseline to a hardened, cluster-ready state:
1. `STAGE 2: FIRST_BOOT` (Local Gitea and Nexus service hubs)
2. `STAGE 3: SECOND_BOOT` (TPM 2.0 unsealing and network gateway sanity)
3. `STAGE 4: LINUX_READY` (OS foundations, sysctl kernel tuning, storage prerequisites, CIS Level 2 hardening)
4. `STAGE 5: CLUSTER_READY` (Machine config, networking, NodeAgent mTLS credential pre-seeding)
5. `STAGE 6: CLUSTER_TURNUP` (Bare metal cluster creation via `bmctl create cluster`)
6. `STAGE 7: POST_CLUSTER` (Cluster health checks, CoreDNS, StorageClasses, ConfigSync)

Nodes equipped with dedicated NVIDIA GPUs (e.g. Dell PowerEdge with NVIDIA RTX 4000 SFF Ada, vendor ID `0x10de`, device `0x2c34`) require host-level preparation prior to `bmctl` cluster bootstrapping:
- The default open-source `nouveau` kernel driver must be suppressed and blacklisted in early boot.
- The proprietary headless server drivers (`nvidia-driver-580-server`, `nvidia-utils-580-server`) and `nvidia-container-toolkit` must be installed from offline mirrors (Sonatype Nexus).
- The `nvidia-persistenced` daemon must run continuously to prevent driver re-initialization latency during inference container teardowns.
- For high-performance inference consistency, GPU memory clocks must be locked (e.g. 7000 MHz) to prevent P-State throttling jitter.
- Nodes lacking an NVIDIA GPU (e.g., `192.168.9.242`) must skip this entire sequence cleanly with zero performance penalty and no modification to generic display drivers.
- The configuration must strictly avoid pre-configuring `/etc/containerd/config.toml` because `bmctl` regenerates containerd during cluster deployment; runtime CDI injection is managed by the NVIDIA GPU Operator post-cluster via ConfigSync.

---

## 2. Requirements & Goals

### 2.1 Functional Requirements

- **FR-1 (Hardware Detection & Gating):** Inspect the host PCI bus for any display or compute device with NVIDIA vendor ID `0x10de` in PCI classes `0300` (VGA), `0302` (3D Controller), or `0380` (Display Controller). If no matching device is found, bypass all GPU setup tasks immediately.
- **FR-2 (Nouveau Suppression):** When an NVIDIA GPU is detected, ensure `/etc/modprobe.d/blacklist-nouveau.conf` is written with `blacklist nouveau`, `blacklist lbm-nouveau`, `options nouveau modeset=0`, `alias nouveau off`, and `alias lbm-nouveau off`.
- **FR-3 (Initramfs Regeneration):** After updating modprobe configurations, rebuild the initial RAM filesystem using `dracut -f` (falling back to `update-initramfs -u` on standard environments) to ensure Nouveau is excluded from early boot.
- **FR-4 (Package Provisioning):** Install `linux-headers-$(uname -r)`, the headless server driver metapackage (`nvidia-driver-580-server`), utilities (`nvidia-utils-580-server`), and `nvidia-container-toolkit` via the local Nexus APT proxy (`nexus.internal.gdc.local:8081`). Driver package series must be parameterizable via Ansible variables.
- **FR-5 (Offline Pre-Seeding & Remastering):** Declare `nvidia-driver-580-server`, `nvidia-utils-580-server`, and `nvidia-container-toolkit` dependencies in `src/build/packages_config.yaml` so they are cached in GCS, included in the ISO `/custom-data/packages/`, and hosted in Nexus `gdc-apt-hosted`.
- **FR-6 (Systemd Persistence Daemon):** Deploy `/etc/systemd/system/nvidia-persistenced.service` running as `root`, ordered before `containerd.service` and `kubelet.service`, with auto-restart enabled.
- **FR-7 (Memory Clock Locking):** If configured (default `true` for inference tuning), execute `/usr/bin/nvidia-smi -lmc {{ nvidia_gpu_memory_clock_mhz | default(7000) }}` via `ExecStartPost` in the persistence service so clock locks persist across reboots.
- **FR-8 (Reboot Orchestration via Stage 4.5):** If Nouveau was newly blacklisted or driver packages were installed, touch `/var/run/reboot-required` so GDC's built-in Stage 4.5 automatically reboots the node cleanly into the NVIDIA driver stack before continuing to `ClusterReady`.
- **FR-9 (Evidence Collection):** Record structured GPU facts (presence, PCI ID, driver version, clock lock state, persistence daemon status) into `linux_ready_evidence.nvidia_gpu` within `/var/gdc-install/state/linux-ready.json`.

### 2.2 Non-Requirements & Constraints

- **NR-1 (No containerd Config Tampering):** Do not alter `/etc/containerd/config.toml`. The NVIDIA GPU Operator handles CDI runtime injection dynamically post-cluster via ConfigSync GitOps.
- **NR-2 (No GPU Workloads on Load Balancer Nodes):** Operators must not assign GPU nodes to `loadBalancer.nodePoolSpec` in `cluster.yaml` due to GDC's automated weekly LB maintenance reboot jobs.
- **NR-3 (No Desktop/X11 Dependencies):** Only headless server driver packages (`*-server`) are deployed; desktop X11 servers and display managers are excluded.

---

## 3. Architecture & Detailed Design

### 3.1 Role Structure: `src/ansible/roles/nvidia_gpu`

```text
src/ansible/roles/nvidia_gpu/
├── defaults/
│   └── main.yml                  # Configurable driver versions, clock rates, flags
├── tasks/
│   ├── main.yml                  # PCI probe & gate entrypoint
│   ├── detect.yml                # PCI bus inspection & fact setting
│   ├── blacklist_nouveau.yml     # Modprobe configuration & dracut initramfs update
│   ├── install_driver.yml        # APT package installation
│   ├── configure_persistence.yml # Systemd service unit & clock lock
│   └── collect_evidence.yml      # Telemetry & LinuxReady evidence recording
└── templates/
    ├── blacklist-nouveau.conf.j2 # Modprobe blacklist directives
    └── nvidia-persistenced.service.j2 # Systemd persistence unit
```

### 3.2 Stage Integration (`stage_linux_ready.yml`)

The role is executed in `src/ansible/stages/stage_linux_ready.yml` following `system_tuning` and `storage_prereqs`:

```yaml
- name: Run nvidia_gpu role
  ansible.builtin.include_role:
    name: nvidia_gpu
```

### 3.3 Hardware Detection Logic

1. Run shell detection query:
   ```bash
   lspci -nn | grep -E '\[(0300|0302|0380)\]:.*10de:'
   ```
2. Set facts:
   - `nvidia_gpu_present`: `true` if exit code is 0 and output is non-empty; `false` otherwise.
   - `nvidia_gpu_pci_id`: Extracted PCI slot (e.g., `0000:02:00.0`).
3. If `nvidia_gpu_present` is `false`:
   - Set `linux_ready_evidence.nvidia_gpu = {"status": "SKIPPED_NO_GPU", "present": false}`.
   - End tasks for this role.

### 3.4 Nouveau Blacklisting & Initramfs Regeneration

1. Render `/etc/modprobe.d/blacklist-nouveau.conf`:
   ```ini
   # Managed by GDC Disk Provisioner
   blacklist nouveau
   blacklist lbm-nouveau
   options nouveau modeset=0
   alias nouveau off
   alias lbm-nouveau off
   ```
2. If the blacklist configuration changed:
   - Execute initramfs rebuild:
     ```bash
     if command -v dracut >/dev/null 2>&1; then
       dracut -f
     elif command -v update-initramfs >/dev/null 2>&1; then
       update-initramfs -u
     fi
     ```
   - Register `nvidia_reboot_required: true`.

### 3.5 Package Installation

Install target packages using `ansible.builtin.apt`:
- `linux-headers-{{ ansible_kernel }}`
- `{{ nvidia_driver_package }}` (default: `nvidia-driver-580-server`)
- `{{ nvidia_utils_package }}` (default: `nvidia-utils-580-server`)
- `nvidia-container-toolkit`

If new packages are installed, set `nvidia_reboot_required: true`.

### 3.6 Systemd Persistence Daemon & Clock Locking

Template `/etc/systemd/system/nvidia-persistenced.service`:

```ini
[Unit]
Description=NVIDIA Persistence Daemon
Before=containerd.service kubelet.service
Wants=containerd.service

[Service]
Type=forking
ExecStart=/usr/bin/nvidia-persistenced --user root
{% if nvidia_gpu_lock_memory_clock | default(true) %}
ExecStartPost=/usr/bin/nvidia-smi -lmc {{ nvidia_gpu_memory_clock_mhz | default(7000) }}
{% endif %}
ExecStopPost=/bin/rm -rf /var/run/nvidia-persistenced
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start `nvidia-persistenced`.

### 3.7 Stage 4.5 Clean Reboot Sequencing

When `nvidia_reboot_required` is `true`:
1. Touch `/var/run/reboot-required` and write explanation to `/var/run/reboot-required.pkgs`.
2. As `stage_linux_ready.yml` finishes, `src/ansible/local.yml` enters:
   ```yaml
   # STAGE 4.5: Kernel/System Pending Reboots
   - name: "GDC-STATE | Check if system requires a reboot (e.g. for HWE kernel)"
     ansible.builtin.stat:
       path: /var/run/reboot-required
     register: reboot_required_file
   ```
3. Stage 4.5 initiates a clean system reboot (`shutdown -r now`) and ends the play.
4. On reboot, `gdc-desired-state.service` resumes at Stage 5 (`CLUSTER_READY`) with Nouveau completely unloaded and the NVIDIA driver stack active.

---

## 4. Configuration Variables (`src/ansible/vars/all.yml`)

```yaml
# ==============================================================================
# NVIDIA GPU Provisioning Configuration
# ==============================================================================
# Driver packages
nvidia_driver_package: "nvidia-driver-580-server"
nvidia_utils_package: "nvidia-utils-580-server"

# Persistence & Performance Tuning
nvidia_gpu_enable_persistence: true
nvidia_gpu_lock_memory_clock: true
nvidia_gpu_memory_clock_mhz: 7000
```

---

## 5. Offline Packaging & Dependency Caching

Update `src/build/packages_config.yaml`:

```yaml
packages_to_include:
  customer_added:
    - "nvidia-driver-580-server"
    - "nvidia-utils-580-server"
    - "nvidia-container-toolkit"
```

The unified dependency resolver (`bin/local/update-dependencies.sh`) fetches these packages into `.cache/packages/`, synchronizes them to `gs://${DEPENDENCY_CACHE_GCS_BUCKET}/packages/`, and `src/build/remaster.sh` packs them into `/custom-data/packages/` on the ISO.

---

## 6. Verification & Testing Strategy

### 6.1 Automated Unit Tests (`test/test_nvidia_gpu.py`)

1. **Hardware Detection Testing**:
   - Mock `lspci` with NVIDIA RTX 4000 Ada (`10de:2c34`): assert `nvidia_gpu_present == true`.
   - Mock `lspci` with AMD Phoenix APU (`1002:15bf`): assert `nvidia_gpu_present == false`.
   - Mock `lspci` with Intel Arrow Lake VGA (`8086:7d67`): assert `nvidia_gpu_present == false`.
2. **Early-Exit Gate Verification**:
   - Assert that when `nvidia_gpu_present == false`, all modification tasks report `skipping`.
3. **Service Unit Template Rendering**:
   - Test template rendering with `nvidia_gpu_lock_memory_clock: true` (asserts `ExecStartPost` present).
   - Test template rendering with `nvidia_gpu_lock_memory_clock: false` (asserts `ExecStartPost` omitted).
4. **Initramfs Generation Safety**:
   - Verify fallback logic executes `dracut -f` when available.

### 6.2 Live Node Validation

- **`192.168.9.242` (Negative Control - No GPU)**:
  - Run playbook: Verify role runs in under 1 second, skips driver install, leaves AMD driver intact.
- **`192.168.9.238` (Positive Control - GPU Present)**:
  - Run playbook: Verify Nouveau blacklisted, `dracut -f` regenerates initramfs, packages install, `/var/run/reboot-required` set, and persistence service configured.
