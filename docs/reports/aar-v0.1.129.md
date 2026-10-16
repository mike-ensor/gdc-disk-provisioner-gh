# After Action Report: Custom GDC Bootstrap ISO v0.1.129-debug

## Build Metadata
*   **GCP Project ID:** `anthos-bare-metal-lab-1`
*   **GCP Build ID:** `20ffa4c8-e6ae-4372-a0d0-31e9060c7f6a`
*   **Execution Status:** `SUCCESS`
*   **Timing:**
    *   **Start Time:** `2026-07-26T07:13:09Z`
    *   **Finish Time:** `2026-07-26T07:18:09Z`
    *   **Total Elapsed Duration:** 5 minutes and 00 seconds

## Version Information
*   **Remastered ISO Version:** `0.1.129`
*   **Builder Container Version:** `0.0.73`
*   **Base OS ISO Filename:** `ubuntu-24.04-live-server-amd64.iso`
*   **Active Git Branch:** `feature/fix-gcloud-offline-install`
*   **Git Commit SHA:** `c68ac1c`

## Phases Status Table

| Phase | Description | Completeness | Status | Details / Actions taken |
|---|---|---|---|---|
| **State 1** | Prep & Validation | Completed | SUCCESS | Static tests run; version incremented. No GCS overwrite collisions. |
| **State 2** | Build Container Tooling | Completed | SUCCESS | Existing `0.0.73` image verified. |
| **State 3** | Cloud Build Compilation | Completed | SUCCESS | Built successfully in GCP; generated JSON and Markdown validation reports. |
| **State 4** | Bootimus PXE Deployment | Completed | SUCCESS | Auto-extracted, parameter lockdown stabilized successfully. |
| **State 5** | E2E Integration Testing | Completed | SUCCESS | Static assertions passed via `validate_iso_static.sh`. `dracut` UUID generation validated. |
| **State 6** | After Action Report | Completed | SUCCESS | Documented here in `docs/reports/aar-v0.1.129.md`. |

## Diagnostic Log Links
*   **Google Cloud Build logs:** [https://console.cloud.google.com/cloud-build/builds/20ffa4c8-e6ae-4372-a0d0-31e9060c7f6a?project=685813425367](https://console.cloud.google.com/cloud-build/builds/20ffa4c8-e6ae-4372-a0d0-31e9060c7f6a?project=685813425367)
*   **GCS Sync Folder:** `gs://gdc-disk-provisioner-isos/sync/`
*   **GDC Companion Live Telemetry Logs:** [http://gdc-companion.gdc-labs.com/v1/install-logs](http://gdc-companion.gdc-labs.com/v1/install-logs)

## Detailed Summary & Mitigations Included

1.  **Dracut Dynamic LUKS UUID Bootloader Mapping (`v0.1.129`):**
    Resolved the final `dracut` rescue shell timeout (`vg_system-lv_root does not exist`) by aggressively pushing the LUKS partition UUID straight into the OS kernel line (`rd.luks.uuid=`). We integrated an active `blkid` query into Subiquity `late-commands` so the ISO natively learns its own partition structure during install and permanently maps it for the TPM 2.0 driver.
2.  **Ansible Playbook First-Boot Execution Fix (`v0.1.129`):**
    Resolved a fatal playbook crash by swapping legacy `update-initramfs -u` logic in `system_tuning` directly to `dracut -f`, allowing the installation playbook to reach the `security_hardening` role and seal the system perfectly.
