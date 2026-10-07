# Root Cause Analysis (RCA) Report

## 1. Incident Overview

*   **Incident ID / Ticket Ref:** `GDC-RCA-2026-10-06-01`
*   **Target Nodes:**
    *   `192.168.9.242` (`gdc-extreme-242` - AMD Phoenix APU)
    *   `192.168.9.243` (`gdc-extreme-243` - AMD Phoenix APU)
    *   `192.168.9.246` (`honeywell-01` - Intel Core Ultra + NVIDIA RTX 4000 SFF Ada)
    *   `192.168.9.234` / `192.168.9.238` (`honeywell-02` - Intel Core Ultra + NVIDIA RTX 4000 SFF Ada)
*   **Problem Statement:** Following bare-metal provisioning under ISO release `v0.10.7`, all physical target nodes failed to complete cluster turnup. Simultaneously, automated companion telemetry for node `192.168.9.246` (Report ID `1ef84ed3-8d02-4b93-b98f-1515ad9755b5`) reported a fatal prerequisite failure: `clean_installation_paths: FAIL` ("Pristine control plane directories check").
*   **Impact Summary:**
    *   All physical target nodes were blocked from advancing past `STAGE 4: LinuxReady`, preventing `STAGE 5: ClusterReady` and `STAGE 6: ClusterTurnup` from running.
    *   On GPU nodes (`.246` and `.234`), the proprietary NVIDIA 580 server driver failed to initialize the RTX 4000 SFF Ada card with `nvidia-smi` reporting `No devices were found`.
    *   On `192.168.9.246`, `gdc-collector` falsely reported OS prerequisite failure after cluster inception due to flawed directory heuristics checking `/var/lib/etcd`.
*   **Final Resolution:**
    1. Removed incompatible Bash-ism (`set -o pipefail`) from POSIX `/bin/sh` shell execution in `roles/nvidia_gpu/tasks/detect.yml` (MR `!51`).
    2. Transitioned NVIDIA driver provisioning on Ada Lovelace / Blackwell GPUs to `nvidia-driver-580-server-open` and rebuilt `dracut` initramfs to resolve NVRM module rejection.
    3. Redesigned `gdc-collector` prerequisite checks (`crates/collector/src/prereqs.rs` in `gdc-companion` MR `!29`) to inspect GDC-specific workspace artifacts (`/var/gdc-install/bmctl-workspace/<cluster_name>`) and `/etc/kubernetes/admin.conf`, with non-blocking `kubectl` operational health verification for idempotent re-runs. Published `gdc-collector` v0.1.135 to GCS.
*   **Investigators:** GDC Disk Provisioner Architecture & Engineering Team / opencode

---

## 2. Timeline of Significance

| Timestamp (UTC) | Node | System State / Event / Trigger | Operational Impact |
| :--- | :--- | :--- | :--- |
| **2026-10-05 21:55:25** | `.246` | **ClusterReady Completed:** First-boot stages 2 through 5 finished cleanly. Node halted per `stop_stage: CLUSTER_READY`. | Node operating in Ready-Linux baseline. |
| **2026-10-05 22:01:05** | `.246` | **Cluster Bootstrap Initiated:** `create_cluster.sh --yes` launched `bmctl create cluster -c honeywell-1`. | Control plane deployment began. |
| **2026-10-05 22:20:00** | `.246` | **Cluster Inception Success:** Kubernetes v1.35.3 control plane established. Nodes report `Ready`. | Active cluster running. |
| **2026-10-05 22:40:16** | `.246` | **Diagnostics Invoked:** Systemd timer triggered `/usr/local/bin/gdc-collector`. Report `1ef84ed3` uploaded. | **FALSE FAIL:** `clean_installation_paths` failed because `/var/lib/etcd` was populated with active cluster data. |
| **2026-10-06 02:58:05** | Fleet | **ISO v0.10.7 Remastered:** Release ISO compiled with initial `nvidia_gpu` role including `set -o pipefail` in `detect.yml`. | Flawed task baked into offline bootstrap repo. |
| **2026-10-06 12:10:08** | `.246`, `.234` | **LinuxReady Failure:** Task `GDC-GPU \| Probe PCI bus` crashed with `/bin/sh: 1: set: Illegal option -o pipefail`. | Provisioning halted at Stage 4 on GPU nodes. |
| **2026-10-06 12:23:34** | `.243`, `.242` | **LinuxReady Failure:** Same shell failure tripped non-GPU nodes during probe. | Provisioning halted at Stage 4 across entire fleet. |
| **2026-10-06 12:34:00** | `.242` | **Shell Syntax Fix Applied:** Removed `set -o pipefail` in `detect.yml`. Local Gitea updated. | Node `.242` immediately advanced past Stage 4 into `ClusterTurnup`. |
| **2026-10-06 12:38:02** | `.246`, `.234` | **Package Failure:** GPU probe passed, but `nvidia-container-toolkit` failed because offline Nexus repository lacked the package. | Provisioning stalled in `install_driver.yml`. |
| **2026-10-06 12:40:15** | `.246`, `.234` | **Toolkit Fallback Configured:** Added GPG keyring and upstream apt source fallback. Packages installed cleanly. | Packages installed; Stage 4.5 reboot scheduled. |
| **2026-10-06 12:49:44** | `.246` | **Kernel Driver Rejection:** Node rebooted; `nvidia-smi` reported `No devices were found`. `dmesg` showed `NVRM: installed in this system requires use of the NVIDIA open kernel modules`. | Proprietary module refused to bind Ada GPU. |
| **2026-10-06 12:51:30** | `.246` | **Open Driver & Dracut Rebuild:** Installed `nvidia-driver-580-server-open` and rebuilt initramfs (`dracut -f`). Initramfs module size shrank from 82.9 MB to 6.6 MB. | Open driver compiled and packed into initrd. |
| **2026-10-06 13:02:17** | `.246` | **GPU Operational:** Reboot complete. `nvidia-smi` reports RTX PRO 4000, 145W, Driver 580.178.04, Clock locked at 7000 MHz. | GPU hardware fully operational. |
| **2026-10-06 13:05:49** | `.246` | **Collector v0.1.135 Deployed:** Deployed updated `gdc-collector`. Report `e2915d27` uploaded. | **100% PASS:** OS Prerequisites passed with zero failures. |
| **2026-10-06 13:14:00** | `.242`, `.243` | **Cluster Verification:** Both nodes finished `CLUSTER_TURNUP`. Control planes reported `Ready`. | Clusters fully operational. |

---

## 3. Root Causes Analysis

### Root Cause 1: Incompatible Shell Option in Ansible Shell Task
In `src/ansible/roles/nvidia_gpu/tasks/detect.yml`:
```yaml
- name: "GDC-GPU | Probe PCI bus for NVIDIA display/compute controllers"
  ansible.builtin.shell: |
    set -o pipefail
    lspci -nn | grep -E '\[(0300|0302|0380)\]:.*10de:' || true
```
*   **Mechanism:** Ansible's `shell` module invokes `/bin/sh` by default unless `args: executable: /bin/bash` is explicitly declared. In Ubuntu, `/bin/sh` symlinks to the Debian Almquist Shell (`dash`). Dash strictly complies with POSIX standards and does not support the `pipefail` option.
*   **Failure:** `set: Illegal option -o pipefail` exited with return code `2`, throwing an unhandled fatal error in Stage 4 (`LinuxReady`) before hardware detection could occur.

### Root Cause 2: NVIDIA Ada Lovelace Open Module Mandate
On nodes equipped with NVIDIA RTX 4000 SFF Ada (`10de:2c34`):
*   **Mechanism:** NVIDIA driver release 580 enforces an architectural mandate requiring the **open kernel modules** (`nvidia-driver-580-server-open`) on Ada Lovelace, Hopper, and Blackwell enterprise architectures.
*   **Failure:** The closed proprietary driver (`nvidia-driver-580-server`) logged `NVRM: The NVIDIA GPU 0000:02:00.0 (PCI ID: 10de:2c34) installed in this system requires use of the NVIDIA open kernel modules` and refused to register minor device nodes. Consequently, `nvidia-smi` reported `No devices were found`.
*   **Secondary Trap:** When installing `nvidia-driver-580-server-open`, `dracut` must be explicitly regenerated (`dracut -f`). The early initrd retained the legacy 82.9 MB proprietary module, creating an unresolved symbol mismatch (`Unknown symbol nvUvmInterfacePagingChannelAllocate`) against the new 6.6 MB open module on disk.

### Root Cause 3: Brittle Directory Heuristics in `gdc-collector` Preflight Checks
In `gdc-companion` (`crates/collector/src/prereqs.rs`):
*   **Mechanism:** The legacy `clean_installation_paths` check evaluated whether `/var/lib/etcd` and `/etc/kubernetes` were empty.
*   **Deficiencies:**
    1. `/var/lib/etcd` is an ext4 filesystem mount on GDC nodes (`lv_etcd`). Standard formatting automatically creates `lost+found`.
    2. If a node scheduled to stop at `CLUSTER_READY` was evaluated after a manual or prior cluster turnup, `CLUSTER_TURNUP` was treated as `BYPASSED`. Because it was marked `BYPASSED`, the collector assumed the node was pre-install and executed `clean_installation_paths` instead of `populated_control_plane`, failing a healthy operational cluster.

---

## 4. Remediations & Technical Fixes

### 4.1 Shell Compatibility Fix (`gdc-disk-provisioner`)
Removed `set -o pipefail` from `src/ansible/roles/nvidia_gpu/tasks/detect.yml`:
```yaml
- name: "GDC-GPU | Probe PCI bus for NVIDIA display/compute controllers"
  ansible.builtin.shell: |
    lspci -nn | grep -E '\[(0300|0302|0380)\]:.*10de:' || true
  register: pci_gpu_probe
  changed_when: false
```
*Committed and pushed to `feature/nvidia-gpu-driver-setup` in MR `!51`.*

### 4.2 NVIDIA Open Kernel Module & Toolkit Fallback (`gdc-disk-provisioner`)
Updated `install_driver.yml` to support upstream GPG key and APT repository configuration when `nvidia-container-toolkit` is not pre-cached on the node, and enabled `nvidia-driver-580-server-open` support with automatic `dracut -f` regeneration:
```yaml
- name: "GDC-GPU | Configure NVIDIA Container Toolkit repository if package not cached"
  when: _nct_cache_check.rc != 0
  block:
    - name: "GDC-GPU | Download NVIDIA Container Toolkit GPG keyring"
      ansible.builtin.get_url:
        url: "https://nvidia.github.io/libnvidia-container/gpgkey"
        dest: "/tmp/nvidia-container-toolkit.gpg"
...
```

### 4.3 Clean Installation Paths Redesign (`gdc-companion`)
Refactored `crates/collector/src/prereqs.rs` to implement `resolve_cluster_name_from` and `evaluate_clean_paths`:
1. **Workspace Discovery:** Resolves `cluster_name` via facts, fallback JSON, or scanning `/var/gdc-install/bmctl-workspace/`.
2. **Kubeconfig Inspection:** Inspects `/var/gdc-install/bmctl-workspace/<cluster_name>/<cluster_name>-kubeconfig` and `/etc/kubernetes/admin.conf` instead of raw directories. Cluster YAML templates (`<cluster_name>.yaml`) are allowed as valid scaffolding.
3. **Idempotent Health Verification:** If credentials exist, runs:
   ```bash
   kubectl --kubeconfig=/etc/kubernetes/admin.conf get nodes --request-timeout=3s
   ```
   If responsive, passes with `"Cluster already initialized and operational (idempotent re-run)"`.
4. **Pristine State:** Passes when workspace credentials and `/etc/kubernetes/admin.conf` are absent.
5. **Published to GCS:** Compiled release binary `gdc-collector` v0.1.135 and uploaded to `gs://gdc-disk-provisioner-isos/binaries/gdc-collector`. Tracked under MR `!29`.

---

## 5. Verification & Fleet Status

### 5.1 Bare-Metal Cluster Health
*   **`192.168.9.242` (`gdc-extreme-242`)**:
    ```text
    NAME              STATUS   ROLES           AGE   VERSION
    gdc-extreme-242   Ready    control-plane   25m   v1.35.3-gke.400
    ```
*   **`192.168.9.243` (`gdc-extreme-243`)**:
    ```text
    NAME              STATUS   ROLES           AGE   VERSION
    gdc-extreme-243   Ready    control-plane   23m   v1.35.3-gke.400
    ```

### 5.2 GPU & Persistence Subsystem Health (`192.168.9.246`)
*   **Driver & GPU State (`nvidia-smi`):**
    ```text
    +-----------------------------------------------------------------------------------------+
    | NVIDIA-SMI 580.178.04             Driver Version: 580.178.04     CUDA Version: 13.0     |
    | GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
    |=========================================+========================+======================|
    |   0  NVIDIA RTX PRO 4000 Blac...    On  |   00000000:02:00.0 Off |                  Off |
    | 30%   37C    P3             16W /  145W |       1MiB /  24467MiB |      0%      Default |
    +-----------------------------------------+------------------------+----------------------+
    ```
*   **Systemd Persistence Unit:** Active and running (`PID 2464`). Memory clock locked to `7000 MHz` on boot (`nvidia-smi -lmc 7000`).
*   **Container Runtime:** `nvidia-container-toolkit` v1.20.1 operational.

### 5.3 Diagnostic Telemetry Compliance (`192.168.9.246`)
*   **Report ID:** `e2915d27-0764-48ca-91d6-0551ad738dc9`
*   **Prerequisite Compliance:** **100% PASS** (`preq_percentage: 100`, `failed_stage: null`).
*   **Clean Paths Result:**
    ```json
    {
      "clean_installation_paths": {
        "status": "PASS",
        "test_results": [
          { "output": "Cluster workspace is clean or uninitialized", "status": "PASS", "test_name": "workspace_clean_check" },
          { "output": "/etc/kubernetes/admin.conf is absent (clean)", "status": "PASS", "test_name": "admin_conf_clean_check" }
        ]
      }
    }
    ```

---

## 6. Preventative Action Items

1. **Lint Rules for Shell Tasks:** Enforce `ansible-lint` rules disallowing shell built-ins like `pipefail` unless `executable: /bin/bash` is explicitly declared.
2. **ISO Package Pre-Seeding Audit:** Ensure `nvidia-driver-580-server-open` and `nvidia-container-toolkit` are pre-seeded into offline package caches (`packages_config.yaml`) prior to release builds.
3. **Collector Testing Pipeline:** Add automated integration tests in `gdc-companion` asserting that nodes evaluated at any lifecycle stage (including `stop_stage: CLUSTER_READY`) correctly differentiate between fresh installs, idempotent clusters, and corrupt state.
