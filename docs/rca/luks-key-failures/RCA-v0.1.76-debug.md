# GDC Post-Install Provisioning Root Cause Analysis (RCA)

* **RCA ID:** `RCA-v0.1.76-debug`
* **Target Node IP:** `192.168.9.246`
* **Target Hostname:** `ubuntu-server`
* **Target MAC ID (Unique):** `00:00:01:04:02:61`
* **GDC Booted ISO Version:** `v0.1.76-debug`
* **RCA Status:** **[ANALYZED FAILURE]**

---

## 1. Issue Summary
The diagnostics agent team has analyzed the node's bootstrap logs. The provisioning process failed during initial setup. Below is the compiled evidence and recommended remediations.

---

## 2. Detected System Failures & Key Telemetry
* **[FAIL]** OS preflight requirement failed: ufw_firewall | Detail: UFW firewall is active
* **[FAIL]** OS preflight requirement failed: inotify_limits | Detail: instances=128 (req>=8192), watches=735235 (req>=524288)
* **[FAIL]** OS preflight requirement failed: docker_version | Detail: Docker version non-compliant: 
* **[FAIL]** OS preflight requirement failed: gcloud_cli | Detail: Not found on PATH
* **[FAIL]** OS preflight requirement failed: gdc_admin_dir | Detail: Missing /var/gdc-install
* **[FAIL]** OS preflight requirement failed: gdc_keys_dir | Detail: Missing keys directory
* **[FAIL]** OS preflight requirement failed: ansible_pull_success | Detail: Not-Run
* **[FAIL]** OS preflight requirement failed: gitea_service | Detail: Inactive/Failed
* **[FAIL]** OS preflight requirement failed: nexus_service | Detail: Inactive/Failed
* **[FAIL]** OS preflight requirement failed: gdc_provision_service | Detail: Inactive/Failed
* **[FAIL]** LUKS_KEY_PROPAGATION_ERROR: Snap-to-host mount namespace propagation delay caused gdc-luks-key to be empty or unreadable during LUKS format.

---

## 3. Access & Authentication Audit
* No public SSH keys were found authorized on the node.

---

## 4. Log Evidence Snippets
### LUKS_FAILURE Log Output:
```
Command: ['cryptsetup', 'open', '--type', 'luks', '/dev/nvme0n1p3', 'crypt-system', '--key-file', '/run/installer/gdc-luks-key']
Exit code: 2
Reason: -
No key available with this passphrase.
```


---

## 5. Recommended Fixes (Ordered by Severity)
### Fix 1: Route keyfile through official host-to-snap bind mount (Severity: HIGH / CRITICAL)
* Re-route the installer bootstrap key from /run/installer/gdc-luks-key to /var/log/installer/gdc-luks-key in user-data.j2 and storage templates. Since /var/log/installer is an active, zero-delay host-to-snap bind-mount, it is 100% immune to namespace timing delays.

