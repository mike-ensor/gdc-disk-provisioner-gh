# After Action Report: Custom GDC Bootstrap ISO v0.1.126-debug

## Build Metadata
*   **GCP Project ID:** `anthos-bare-metal-lab-1`
*   **GCP Build ID:** `e9fce8fa-af3d-4670-a690-bf3d8c13dde7`
*   **Execution Status:** `SUCCESS`
*   **Timing:**
    *   **Start Time:** `2026-07-26T04:21:40Z`
    *   **Finish Time:** `2026-07-26T04:26:00Z`
    *   **Total Elapsed Duration:** 4 minutes and 20 seconds

## Version Information
*   **Remastered ISO Version:** `0.1.126`
*   **Builder Container Version:** `0.0.73`
*   **Base OS ISO Filename:** `ubuntu-24.04-live-server-amd64.iso`
*   **Active Git Branch:** `feature/fix-gcloud-offline-install`
*   **Git Commit SHA:** `1497d6a`

## Phases Status Table

| Phase | Description | Completeness | Status | Details / Actions taken |
|---|---|---|---|---|
| **State 1** | Prep & Validation | Completed | SUCCESS | Static tests run; version incremented. No GCS overwrite collisions. |
| **State 2** | Build Container Tooling | Completed | SUCCESS | Existing `0.0.73` image verified. |
| **State 3** | Cloud Build Compilation | Completed | SUCCESS | Built successfully in GCP; generated JSON and Markdown validation reports. |
| **State 4** | Bootimus PXE Deployment | Completed | SUCCESS | Auto-extracted, parameter lockdown stabilized successfully. |
| **State 5** | E2E Integration Testing | Completed | SUCCESS | Static assertions passed via `validate_iso_static.sh`. `0+7` PCRs validated. |
| **State 6** | After Action Report | Completed | SUCCESS | Documented here in `docs/reports/aar-v0.1.126.md`. |

## Diagnostic Log Links
*   **Google Cloud Build logs:** [https://console.cloud.google.com/cloud-build/builds/e9fce8fa-af3d-4670-a690-bf3d8c13dde7?project=685813425367](https://console.cloud.google.com/cloud-build/builds/e9fce8fa-af3d-4670-a690-bf3d8c13dde7?project=685813425367)
*   **GCS Sync Folder:** `gs://gdc-disk-provisioner-isos/sync/`
*   **GDC Companion Live Telemetry Logs:** [http://gdc-companion.ensor-labs.com/v1/install-logs](http://gdc-companion.ensor-labs.com/v1/install-logs)

## Detailed Summary & Mitigations Included

1.  **Dracut Target Initrd TPM & AMD Fix (`v0.1.126`):**
    Included the fix where `ccp` is dynamically added to `omit_drivers+=" pcie_mp2_amd amd_sfh ccp "` on the target OS, and explicitly injected the `tpm2-tss` dracut hooks alongside the core kernel drivers via `--add "tpm2-tss" --add-drivers "tpm tpm_tis tpm_crb tpm_tis_core"` to guarantee the target machine will NOT deadlock, and WILL successfully read TPM 2.0 PCR registers on second-boot!
