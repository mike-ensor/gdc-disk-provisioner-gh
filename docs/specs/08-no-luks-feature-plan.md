# GDC-SPEC-008: Non-LUKS Storage Provisioning Architecture

To support diverse hardware constraints and bypass specific UEFI/TPM motherboard firmware lockouts on specialized edge nodes, GDC provides a declarative, compile-time toggle to bypass LUKS disk encryption and mount the system volume groups directly on raw NVMe partitions.

---

## 1. Architectural Overview & State Changes

When `GDC_ENABLE_LUKS=false` is declared, the GDC Bootloader ISO shifts its storage provisioning flow from a **two-phase hybrid cryptographic lifecycle** to a **direct unencrypted logical volume model**:

```text
+---------------------------------------------------------------------------------+
|                        GDC_ENABLE_LUKS=true (Default Secure)                    |
|                                                                                 |
|  [p3 Partition] ---> [LUKS2 crypt-system Container] ---> [vg_system] ---> [LVs]  |
+---------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------+
|                        GDC_ENABLE_LUKS=false (No-LUKS Bypass)                   |
|                                                                                 |
|  [p3 Partition] ----------------------------------------> [vg_system] ---> [LVs]  |
+---------------------------------------------------------------------------------+
```

### **Comparative Boot Flow**

| Stage-Gate | `GDC_ENABLE_LUKS=true` (Encrypted) | `GDC_ENABLE_LUKS=false` (No-LUKS) |
| :--- | :--- | :--- |
| **Partitioning** | Creates `/dev/nvme0n1p3` | Creates `/dev/nvme0n1p3` |
| **Encryption** | Configures `crypt-system` via `/dev/gdc-luks-key` | **Bypassed completely** |
| **Volume Group** | Binds `vg_system` to `/dev/mapper/crypt-system` | Binds `vg_system` directly to `/dev/nvme0n1p3` |
| **First Boot** | systemd-cryptsetup unlocks via `/etc/keys/temp_key.key` | **Bypassed completely** |
| **Playbook run** | Seals key to physical TPM 2.0; purges password slot | **Bypassed completely** |
| **Second Boot** | systemd-cryptsetup unseals passwordlessly via TPM | Direct raw mounting (0s encryption overhead) |

---

## 2. Detailed Technical Step-by-Step Implementation

To implement this feature seamlessly, the following codebases and templates must be updated:

### **Step 1: Hydrator Parameter Mapping (`src/build/render_templates.py`)**
Update the Python hydration runner to load the `GDC_ENABLE_LUKS` variable from the environment (defaulting to `true` to maintain GDC's secure baseline defaults):
```python
env['gdc_enable_luks'] = env.get('GDC_ENABLE_LUKS', 'true').lower() == 'true'
```

### **Step 2: Storage Template Conditionals (`src/build/templates/storage_config.j2`)**
Wrap the `dm_crypt` and `lvm_volgroup` blocks inside Jinja2 conditionals:
```yaml
  {% if gdc_enable_luks %}
  - {type: dm_crypt, id: crypt-system, volume: partition-lvm, keyfile: /var/log/installer/gdc-luks-key}
  - {type: lvm_volgroup, id: vg-system, name: vg_system, devices: [crypt-system]}
  {% else %}
  - {type: lvm_volgroup, id: vg-system, name: vg_system, devices: [partition-lvm]}
  {% endif %}
```
Apply the same conditional wrapper inside all static storage templates:
*   `storage_config_bios_single.yaml`
*   `storage_config_uefi_single.yaml`
*   `storage_config_bios_dual.yaml`
*   `storage_config_uefi_dual.yaml`

### **Step 3: Late-Commands Key Enrollment Bypass (`src/build/templates/user-data.j2`)**
Surgically wrap the bootstrap key creation, `/etc/cryptsetup-initramfs` injection, and `luksAddKey` loops inside conditional wrappers in `user-data.j2`'s late-commands:
```yaml
  - |
    {% if gdc_enable_luks %}
    # [GDC-INSTALL-STEP 11/12] Configuring passwordless boot-unlock key file...
    mkdir -p /target/etc/keys
    echo -n "temporary_bootstrap_key_to_be_enrolled_to_tpm" > /target/etc/keys/temp_key.key
    # ... rest of cryptsetup enrollment tasks ...
    {% else %}
    echo "[-] [No-LUKS Mode] Skipping bootstrap key configuration and keyslot enrollment."
    {% endif %}
```

### **Step 4: Ansible security_hardening Adaptation (`src/ansible/roles/security_hardening/`)**
Relax the `blkid` check inside `security_hardening/tasks/main.yml` to prevent failures when no LUKS volumes exist, and add conditional guards (`when: luks_partition_devices.stdout != ""`) to all subsequent tasks:
```yaml
- name: "GDC-TPM-SEAL | Retrieve GDC LUKS system device partitions"
  ansible.builtin.shell: blkid -t TYPE=crypto_LUKS -o device
  register: luks_partition_devices
  changed_when: false
  failed_when: false # Relaxed to allow unencrypted devices to pass cleanly

- name: "GDC-TPM-SEAL | Seal LUKS Master Key to TPM 2.0 PCR registers"
  ansible.builtin.shell: |
    systemd-cryptenroll --tpm2-device=auto --unlock-key-file=/etc/keys/temp_key.key {{ item }}
  loop: "{{ luks_partition_devices.stdout_lines }}"
  when:
    - tpm_device_stat.stat.exists
    - luks_partition_devices.stdout != ""
```

---

## 3. Dual-Image Compilation Matrix

Once implemented, the build orchestrator will support building two distinct release images side-by-side using different GCB build tags:

1.  **Standard Secure Production Image (`gdc-bootstrap-ubuntu-24.04-v0.1.91-debug.iso`):**
    *   `GDC_ENABLE_LUKS=true`
    *   Provides full, hardware-bound TPM 2.0 sealed disk encryption.
2.  **Edge Hardware Bypass Image (`gdc-bootstrap-ubuntu-24.04-v0.1.91-noluks-debug.iso`):**
    *   `GDC_ENABLE_LUKS=false`
    *   Installs directly onto unencrypted physical partitions to bypass problematic hardware.
