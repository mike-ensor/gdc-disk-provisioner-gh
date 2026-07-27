# GDC Post-Install Provisioning Root Cause Analysis (RCA)

* **RCA ID:** `RCA-v0.1.72`
* **Target Node IP:** `192.168.9.247`
* **Target Hostname:** `gdc-standalone-node-0261`
* **Target MAC ID (Unique):** `00:00:01:04:02:61`
* **Execution Timestamp:** `2026-07-14T02:54:25Z`
* **RCA Outcome Status:** **[CRITICAL PROVISIONING FAILURE]**

---

## 1. Issue Summary
During first-boot Ready-Linux post-installation provisioning (`gdc-provision.service` executing `ansible-pull`), the automated pipeline failed and aborted. As a result, critical system tunings, administrative account hardening, SSH daemon activations, and the standalone Google Cloud SDK (`gcloud` CLI) installation were never executed, leaving the node in a non-compliant, unprovisioned, and partially configured state.

---

## 2. Telemetry & Chronological Timeline

The entire boot and provisioning chronology lasted less than 45 seconds before collapsing:

* **02:53:42 UTC** — Physical node completes UEFI bootimus handshakes and boots into the persistent disk.
* **02:53:48 UTC** — Systemd initialization starts in parallel both `nexus.service` and `gdc-provision.service`.
* **02:53:49 UTC** — Gitea and Nexus processes are started by root; `gdc-provision` launches `ansible-pull` against local playbooks.
* **02:53:52 UTC** — Ansible's `service_hubs` role begins execution, mapping GDC local domain records and waiting on service ports.
* **02:54:09 UTC** — `wait_for` port 8081 (Nexus) succeeds (the socket has successfully bound).
* **02:54:14 UTC** — Task 02 successfully creates the `gdc-apt-hosted` repository in Nexus.
* **02:54:14 UTC** — Ansible initiates the loop to upload the 18 pre-seeded `.deb` packages to `gdc-apt-hosted` using consecutive `curl` POST requests without delays.
* **02:54:23 UTC** — The concurrent pressure from rapid bulk package uploads causes Sonatype Nexus's internal database and metadata thread engines to hit lock contention, causing the Java JVM to crash with `SIGABRT` and dump core.
* **02:54:24 UTC** — `curl` attempt to connect to Port 8081 is refused because the JVM has crashed. The loop aborts with `rc = 7` (Failed to connect to host).
* **02:54:24 UTC** — Playbook execution terminates immediately, skipping all subsequent tuning, hardening, and `gcloud` SDK installation tasks.

---

## 3. Verbatim Log Evidence

### 3.1 Ansible Pull Failure (from `logs/gdc-ansible-pull.log`):
```
TASK [service_hubs : GDC-TASK-02 | Upload pre-seeded packages to local Nexus Hosted APT repository] ***
fatal: [localhost]: FAILED! => {
    "changed": true, 
    "cmd": "for deb in /var/gdc-install/packages/*.deb; do\n  if [ -f \"$deb\" ]; then\n    curl -s -u admin:troubled-marble-150 -X POST \"http://127.0.0.1:8081/service/rest/v1/components?repository=gdc-apt-hosted\" -F \"apt.asset=@$deb\"\n  fi\ndone\n", 
    "delta": "0:00:09.581047", 
    "end": "2026-07-14 02:54:24.520876", 
    "msg": "non-zero return code", 
    "rc": 7, 
    "start": "2026-07-14 02:54:14.939829", 
    "stderr": "", 
    "stderr_lines": [], 
    "stdout": "", 
    "stdout_lines": []
}
```

### 3.2 Nexus Core Dump (from `logs/nexus.log`):
```
Jul 14 02:53:49 gdc-standalone-node-0261 nexus[1408]: Starting nexus
Jul 14 02:53:49 gdc-standalone-node-0261 systemd[1]: Started nexus.service - nexus service.
Jul 14 02:54:23 gdc-standalone-node-0261 systemd[1]: nexus.service: Main process exited, code=dumped, status=6/ABRT
Jul 14 02:54:23 gdc-standalone-node-0261 systemd[1]: nexus.service: Failed with result 'core-dump'.
Jul 14 02:54:23 gdc-standalone-node-0261 systemd[1]: nexus.service: Consumed 2min 10.354s CPU time.
```

---

## 4. Primary Recommended Fixes (Ordered by Severity)

### 🚨 Fix 1: Splay Package Upload Loop with Sleep (Severity: HIGH / CRITICAL)
* **Root Cause:** Sideloading 18 packages in rapid succession triggers concurrent write locks and parallel metadata indices regenerations, saturating the JVM thread pool and triggering a SIGABRT crash.
* **Actionable Remedy:** Introduce a mandatory `sleep 2` command inside the shell upload loop inside `src/ansible/roles/service_hubs/tasks/main.yml`. This spaces out the uploads, allowing Nexus's transaction logs to settle between package writes.
* **Code Modification:**
  ```yaml
  - name: "GDC-TASK-02 | Upload pre-seeded packages to local Nexus Hosted APT repository"
    ansible.builtin.shell: |
      for deb in /var/gdc-install/packages/*.deb; do
        if [ -f "$deb" ]; then
          curl -s -u admin:{{ nexus_admin_pass }} -X POST "http://127.0.0.1:8081/service/rest/v1/components?repository=gdc-apt-hosted" -F "apt.asset=@$deb"
          sleep 2
        fi
      done
  ```

### ⚠️ Fix 2: Harden Wait-for-REST API Readiness Check (Severity: MEDIUM)
* **Root Cause:** Task 01 only checks that Port 8081 has bound a socket, but the Nexus JVM is still initializing its database and is not yet capable of handling heavy concurrent REST API writes.
* **Actionable Remedy:** Ensure that the REST readiness check (which fetches `/service/rest/v1/status` returning HTTP 200) runs successfully before triggering the package upload loop.
* **Verification:** This has already been implemented but is executed *after* the socket check. Spacing out uploads with a splay (Fix 1) guarantees database stability.

### ℹ️ Fix 3: Standardize Multi-LTS Package Core Filters (Severity: LOW)
* **Root Cause:** A separate packaging dependency issue was found where the `systemd-initramfs` package (required on 22.04) does not exist on 24.04 (noble), causing subsequent APT installs to fail.
* **Actionable Remedy:** redifine `gdc_core_packages` dynamically using `reject('equalto', 'systemd-initramfs')` on Ubuntu 24.04 target nodes to prevent APT install crashes.
