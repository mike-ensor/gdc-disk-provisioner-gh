# GDC Post-Install Provisioning Root Cause Analysis (RCA)

* **RCA ID:** `RCA-v0.1.78-debug`
* **Target Node IP:** `192.168.9.247`
* **Target Hostname:** `ubuntu-server`
* **Target MAC ID (Unique):** `00:00:01:04:02:61`
* **GDC Booted ISO Version:** `v0.1.78-debug`
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

---

## 3. Access & Authentication Audit
* No public SSH keys were found authorized on the node.

---

## 4. Log Evidence Snippets
* No specific traceback or failure signature was matched in the logs.

---

## 5. Recommended Fixes (Ordered by Severity)
### Fix 1: Manual Inspection Recommended (Severity: MEDIUM)
* Please check the compiled on-device logs under the logs directory in the diagnostics package to locate the failing task.
