# GDC-SPEC-009: Temporary Installer Removal Plan

## 1. Overview
During the Ubuntu Subiquity autoinstall phase, a default user named `temporary-installer` is created. This user is injected with a cryptographically hashed temporary password and administrative SSH public keys to allow break-glass debugging during the critical first-boot window (Transition Gaps 3.1 - 3.3).

However, once the system is fully bootstrapped, the `gdc-admin` user is provisioned via Ansible-Pull, and the GDC node is joined to a cluster, the `temporary-installer` user becomes an unnecessary attack surface and a violation of the principle of least privilege.

This specification outlines the plan to safely remove this user without breaking the installation lifecycle.

## 2. The Problem (The Dependency Trap)
We cannot simply delete `temporary-installer` at the end of the Subiquity `late-commands` because:
1. It is the active user executing the first-boot sequence.
2. The `gdc-admin` user is not created until `ansible-pull` runs (which happens *after* the first reboot).
3. If an installation fails mid-way (e.g., Gitea fails to start, Ansible fails to pull), administrators need `temporary-installer` via SSH to debug the node.

## 3. Proposed Solutions

### Option A: End of Ansible-Pull Execution
Appends a final task to the `security_hardening` role in `ansible-pull` to delete the user.
* **Pros:** Simple to implement. Guaranteed to happen after `gdc-admin` is successfully created.
* **Cons:** If `ansible-pull` runs continuously on a cron schedule, this task will repeatedly check for a missing user. If an admin is actively using `temporary-installer` to debug a failing Ansible run, the moment it succeeds, their SSH session might be abruptly terminated or their home directory deleted.

### Option B: Post-Cluster Turnup (GDC Companion / NodeAgent)
Delays the removal until the GDC cluster is officially created and the NodeAgent signals healthy federation.
* **Pros:** Ensures the node is 100% healthy and managed by the control plane before removing the break-glass user.
* **Cons:** Requires integration with the cluster lifecycle management (bmctl or NodeAgent), which currently operates independently of the host OS user accounts.

### Option C: One-Shot systemd Timer (Time-Delayed Purge)
A systemd one-shot service (`gdc-purge-installer.service`) scheduled to run 24 hours after the first successful boot.
* **Pros:** Gives administrators a 24-hour window to debug any initial provisioning failures. Removes the user automatically even if the node never joins a cluster.
* **Cons:** Leaves the attack surface open for 24 hours.

## 4. Chosen Implementation Path: Option A (Ansible-Pull Finalization)
We will integrate the removal into the `security_hardening` Ansible role, but with safety conditions:

1. **Check for `gdc-admin`:** The task will assert that `gdc-admin` exists and has sudo privileges before attempting to delete `temporary-installer`.
2. **Graceful Deletion:** Use `userdel --remove temporary-installer` to ensure the home directory and `.ssh` authorized keys are fully wiped.
3. **Idempotency:** The task will simply `skip` if the user is already absent, ensuring no errors during cron-triggered Ansible runs.

## 5. Execution Plan (Future Implementation)
1. Write the Ansible task in `src/ansible/roles/security_hardening/tasks/main.yml`.
2. Add a verification step in `test/verify_ansible.sh` to ensure the user is absent after a successful run.
3. Update `docs/SECURITY.md` to reflect this ephemeral lifecycle.
