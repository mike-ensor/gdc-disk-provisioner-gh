# Specification: GDC ISO Verification & QEMU End-to-End Testing

**Spec Identifier:** `GDC-SPEC-004`  
**Status:** APPROVED (Spec-Review Pass)  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Overview & Objectives
To guarantee the bootable GDC ISO is structurally correct, has valid cloud-init syntax, and installs successfully onto bare metal partitions without manual intervention, a automated two-tier testing pipeline is established:

1. **Static Validation (Structural Integrity):** Inspects the compiled ISO's filesystem without mounting or booting. Validates the existence of critical payload files and runs schema checks against Cloud-Init files.
2. **Dynamic E2E Verification (Headless Boot):** Spawns a temporary, headless virtual machine inside QEMU/KVM. It maps an emulated TPM 2.0 chip, mounts the remastered ISO as a CD-ROM, boots the installer, monitors serial output for success signals, and executes SSH-based post-install assertion suites.

---

## 2. Tier 1: Static Structural Validation
Static checks run instantly after the compilation of the ISO inside the build system. This avoids VM boot overhead for simple syntax errors.

```text
Compiled ISO File
      │
      ├── 1. File Inventory Check (via xorriso / 7z)
      │     └── Is /nocloud/user-data present?
      │     └── Is /custom-data/gitea/gitea present?
      │     └── Is /custom-data/nexus/nexus present?
      │
      └── 2. Cloud-Init Schema Checker
            └── Run "cloud-init schema --config-file user-data"
```

### 2.1. File Extraction Utility
Because mounting `.iso` files requires root/loopback administrative privileges, the validator extracts configurations using `xorriso` which executes cleanly in restricted CI/CD environments:
```bash
xorriso -osirrox on -indev build-workspace/output/gdc-bootstrap.iso -extract /nocloud/user-data /tmp/user-data
```

### 2.2. Schema Validation
The extracted autoinstall yaml is validated against the official Subiquity schema:
```bash
cloud-init schema --config-file /tmp/user-data
```

---

## 3. Tier 2: Dynamic QEMU End-to-End Boot Testing
To verify the complex interactions of Subiquity partitioning, local Gitea/Nexus service transfers, local `ansible-pull` operations, and TPM 2.0 cryptobindings, the ISO must undergo a dynamic boot.

```text
  [ Host Test Runner Script (test/run_qemu_e2e.sh) ]
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
 [ swtpm socket ]             [ QEMU/KVM VM Process ]
  (Emulated TPM)               ├── -cdrom gdc-bootstrap.iso
  (Unique mktemp)              ├── -drive disk-sys.qcow2 (250G sparse SSD)
       │                       ├── -drive disk-data.qcow2 (350G sparse SSD)
       └─> Mapped into VM <────├── -nographic (Headless)
                               ├── -serial file:serial.log <─── (Writes success token)
                               └── -net user,hostfwd=tcp::2222-:22 (Secure Ephemeral Key)
```

### 3.1. Emulated TPM 2.0 Configuration (Isolated Socket Mapping)
Because GDC requires LUKS disk encryption and SSH host key binding to a TPM 2.0 chip, standard QEMU must be integrated with a software-emulated TPM state. This is accomplished using `swtpm`.
* **Isolated Multi-Agent Directory Pattern:** To support concurrent test runs on the same build host without socket collisions or locked state crosstalk, the script creates a unique, isolated temp directory on every run:

```bash
# Start an isolated software TPM emulator in background
TPM_TEMP_DIR=$(mktemp -d -t gdc-tpm-XXXXXX)
swtpm socket --tpmstate dir="${TPM_TEMP_DIR}" \
  --tpm2 \
  --ctrl type=unixio,path="${TPM_TEMP_DIR}/swtpm-sock" \
  --daemon
```

### 3.2. Headless Dual-Disk QEMU Invocation
To thoroughly test our dynamic auto-partitioning script (`generate_storage_config.sh`) live on physical-emulated multi-drive topologies, the runner provisions and attaches **two** separate sparse virtual SSD drives (System and Data):

```bash
# Create sparse virtual SSD drives (takes 0 bytes of physical host disk)
qemu-img create -f qcow2 /tmp/gdc-test-sys.qcow2 250G
qemu-img create -f qcow2 /tmp/gdc-test-data.qcow2 350G
```

The VM is then executed headlessly with 8 GB RAM and 4 vCPUs:
```bash
qemu-system-x86_64 -enable-kvm -m 8192 -smp 4 \
  -drive file=/tmp/gdc-test-sys.qcow2,if=virtio,cache=writeback \
  -drive file=/tmp/gdc-test-data.qcow2,if=virtio,cache=writeback \
  -cdrom build-workspace/output/gdc-bootstrap.iso \
  -nographic \
  -serial file:/tmp/serial.log \
  -net nic -net user,hostfwd=tcp:127.0.0.1:2222-:22 \
  -chardev socket,id=chrtpm,path="${TPM_TEMP_DIR}/swtpm-sock" \
  -tpmdev emulator,id=tpm0,chardev=chrtpm \
  -device tpm-tis,tpmdev=tpm0 \
  -boot d &
```

### 3.3. Secure Ephemeral SSH Key Injections
* **The Threat:** Forwarding guest port 22 to host port 2222 on all interfaces allows other machines on the local area network (LAN) or unauthorized users on a shared CI/CD host to connect to the GDC guest VM.
* **The Mitigation:** Standard password-based SSH access is disabled on our test builds. Instead, we implement two core defenses:
  1. **Strict Loopback Binding:** The port forwarding is explicitly bound to `127.0.0.1` (`hostfwd=tcp:127.0.0.1:2222-:22`), preventing any external LAN machines from attempting connections.
  2. **Short-Lived Ephemeral Keys:** The test runner dynamically generates a short-lived ephemeral SSH key pair during the build stage, injects the public key onto the ISO's `/nocloud/user-data` file, and uses the private key to authenticate the remote post-boot validation queries. The keys are immediately deleted upon test cleanup.

### 3.4. Serial Log Verification (Success Signaling)
During the post-install setup (`GDC-SPEC-003`), our Ansible bootstrap playbooks or cloud-init late-commands append a distinct success token to the serial console device `/dev/ttyS0` once provisioning has succeeded completely:

```bash
# Executed within GDC target node post-install
echo "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" > /dev/ttyS0
```

The host test runner monitors `/tmp/serial.log` with a timeout threshold (e.g., 15 minutes):
```bash
# Polling loop in host test runner
timeout 900 grep -q "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" <(tail -f /tmp/serial.log)
```

---

## 4. SSH Assertions (Post-Boot Validation Suite)
Once the success token is observed in the logs, the test runner utilizes SSH via port-forwarding (`localhost:2222`) to execute an assertion suite on the running VM. The assertions align with the local first-boot self-tests executed by the Ansible bootstrap (`local.yml`):

1. **Verify Local Service Accessibility (Hubs):** Confirm that Gitea (`localhost:3000`) and Nexus (`localhost:8081`) have completely started and are serving connections.
2. **Verify Partition and Logical Block Separation:** Confirm separate LVM Logical Volumes have mounted successfully for etcd, containerd, metrics, and customer spaces using remote commands:
   ```bash
   ssh -p 2222 gdc-admin@localhost "lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINTS"
   ```
3. **Verify Outbound Connectivity Log (Ping 8.8.8.8):** Read the local Ansible run logs to verify the network ping probe successfully executed (either returning internet gateway success or falling back gracefully under air-gap conditions).
4. **Verify TPM Cryptobinding:** Confirm the LUKS partition key has been enrolled to the TPM:
   ```bash
   ssh -p 2222 gdc-admin@localhost "systemd-analyze security"
   ```
5. **Clean Termination:** Shutdown the QEMU process, kill `swtpm`, and delete temporary disk files.

---

## 5. Playbook Verification Tiers (Ansible Testing Suite)
To guarantee that GDC bootstrap playbooks compile correctly, run without exceptions, and execute in an idempotent manner, developers utilize a three-tiered testing hierarchy:

```text
       [ TIER 1: LINT & SYNTAX CHECKS ]
       • Execute "ansible-playbook --syntax-check local.yml"
       • Execute "ansible-lint local.yml"
                    │
                    ▼
       [ TIER 2: LOCAL DRY-RUN (CHECK MODE) ]
       • Execute "ansible-playbook --check --diff local.yml"
       • Simulates task effects without host modifications
                    │
                    ▼
       [ TIER 3: DYNAMIC VM E2E (QEMU & SWTPM) ]
       • Runs active playbook on bare-metal emulated host
       • Verifies LVM partitioning, Gitea/Nexus services, and TPM seals
       • Runs twin executions to verify Idempotency (changed=0)
```

### 5.1. Automated Verification Script (`test/verify_ansible.sh`)
The project provides a unified, portable testing harness (`test/verify_ansible.sh`) that automates Tiers 1 and 2:
* **Syntax Validation:** Fails the build immediately if the playbook contains incorrect YAML indentation, missing variable bindings, or unrecognized Ansible statements.
* **Local Check-Mode:** Runs a local simulation using `--check --diff` to log expected configuration changes. It dynamically sets `enforce_signed_commits=false` during development mode to prevent key verification crashes.
* **Best-Practice Linting:** Uses `ansible-lint` to assert compliance with modern, idempotent task structures and detect deprecated module parameters.
* **Portable Execution:** If executed in environments where Ansible is missing (e.g. baseline workspaces), the script outputs a structured tutorial and instruction guide before exiting with a success code.

### 5.2. Idempotency Assertion Standards
Any playbook written or modified inside `src/ansible` must meet strict **idempotency standards**:
1. Run the playbook the first time: Tasks execute and return `changed` or `ok` status codes.
2. Run the playbook a second time: Every single task must return `ok` (no changes made). The final execution report must read:
   `changed=0 failures=0`
3. Tasks using `command` or `shell` modules must define `changed_when` parameters to prevent breaking this standard. GDC continuous integration builds automatically reject any playbooks that do not satisfy this idempotency condition.

---

## 6. Security & Operational Mitigations in E2E Testing
Running bare-metal emulation and hardware cryptography tests inside shared CI/CD hosts introduces specific threats. The verification harness enforces the following mitigations:

| Threat Category | Potential Attack Vector / Operational Failure | Engineered Mitigation Solution |
| :--- | :--- | :--- |
| **Port Collision & Eavesdropping** | Multiple parallel test agents attempt to bind port `2222`, causing resource crashes. Other users on the same host can access GDC node ports. | **Strict Local Loopback Binding (`127.0.0.1`):** QEMU port forwarding binds strictly to local loopback (`hostfwd=tcp:127.0.0.1:2222-:22`), preventing external network access. Parallel test runners use a dynamic port discovery algorithm to allocate unique host ports. |
| **TPM State Corruption** | Parallel execution runs overwrite the standard `/tmp/mytpm` software TPM socket, leading to locks and test failures. | **Isolated Temporary Directories (`mktemp`):** Each run instantiates an isolated software TPM (`swtpm`) state directory using randomized temporary folder hashes, completely preventing crosstalk. |
| **Credential Exposure** | Leaving test SSH keys or administrative access backdoors active on the finished GDC node image. | **Secure Ephemeral Key Injection:** Test SSH keys are dynamically generated on the fly, injected at build time, used strictly during assertions, and permanently wiped from the host upon test completion. Standard password login is strictly disabled. |
| **KVM Performance Starvation** | Standard cloud build runners lack nested KVM virtualization (`/dev/kvm`), causing software emulation (TCG) to slow E2E runs to >45 minutes. | **Dynamic Virtualization Detection & Dedicated Runners:** The orchestrator detects `/dev/kvm` presence and falls back gracefully with prominent warning outputs, advising administrators to use GCE nested-virtualization VM instances. |
| **Resource & Billing Leakage** | Canceled or timed-out test runs leave orphaned background QEMU or `swtpm` processes running, consuming CPU/RAM and cloud costs. | **Global Signal Trap Cleanup (`trap EXIT`):** The orchestrator implements a robust exit trap that executes a forced termination command (`kill`) on all spawned subprocess PIDs and purges temporary files on any interrupt signal. |
