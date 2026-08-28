---
name: gdc-iso-build-deploy
description: Build, remaster, validate, and deploy GDC custom bootstrap ISOs. Use when the user asks to "build a new ISO", "build a new ISO version", compile ISOs, run remaster pipelines, deploy release images to PXE/Bootimus, or troubleshoot installer boot loops, TPM enrollment, and partition failures.
dependencies: []
---

# Skill: gdc-iso-build-deploy

## 1. Abstract
Provides a structured workflow for remastering, cloud-building, PXE deploying, and validating GDC Custom Bootstrap ISOs. Orchestrates local and cloud environments, tracking long-running builds asynchronously using a state-machine persistence pattern.

## 2. Usage Examples

### Example 1: Full Pipeline Build
**Prompt:** "Build and deploy the new custom GDC ISO to the PXE server."
**Action:** The agent executes `./build-iso.sh` and tracks progress through each gate.

### Example 2: Resume Asynchronous Build Check
**Prompt:** "Is the custom GDC ISO build done yet?"
**Action:** The agent reads `.cache/build-state.json` to fetch the active Build ID, queries `gcloud builds describe`, and proceeds to Bootimus deployment if successful.

### Example 3: Build ISO without Companion Telemetry Webhooks
**Prompt:** "Build a new ISO but disable all phone-home tracking."
**Action:** The agent executes `./build.sh --companion FALSE` (or `GDC_COMPANION=FALSE ./build-iso.sh`).

## 3. Security Constraints
- **Secrets Isolation:** Never print `BOOTIMUS_USER` or `BOOTIMUS_PASS` credentials to logs. Leverage the Infisical CLI automatically when credentials are not in the active environment.
- **Verification Gate:** Static autoinstall validation must be executed and succeed before deploying to real or virtual target systems.

## 4. Dependencies
- **CLI Utilities:** `gcloud`, `git`, `python3`, `make`
- **Internal Tools:** `./build.sh`, `./build-iso.sh`, `./src/build/bootimus.py`

---

## 5. Standard Stage-Gate Workflows

### State 1: Prep & Validation
- [ ] Source the environment: `source .envrc`.
- [ ] Assert key variables: `PROJECT_ID`, `REGION`, `ISO_VERSION`.
- [ ] Check GCS destination collision to prevent overwrites:
  `gcloud storage objects describe gs://${GCS_BUCKET}/sync/gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso --project=${PROJECT_ID}`.
- [ ] Ensure local Cache directory is ready: `.cache/isos/`.

### State 2: Build Container Tooling (If needed)
- [ ] NOTE: Running the build image update is NOT a common operation. Only run if build tools/dependencies changed.
- [ ] Verify image `${REGION}-docker.pkg.dev/${PROJECT_ID}/gdc-build-images/iso-builder:${BUILD_VERSION}` exists in artifact registry.
- [ ] If missing or explicitly requested to rebuild, run `./build-builder.sh` to compile and push the xorriso/rsync-equipped builder container.

### State 3: Cloud Build Compilation & Async Handshake
- [ ] NOTE: CloudBuild is the ONLY way to build an ISO that ends up published. Local builds are strictly for local testing.
- [ ] Execute `./build.sh` (optionally appending `--companion [TRUE|FALSE]` if modifying telemetry behavior) to trigger the Google Cloud Build pipeline (this auto-increments the ISO version patch).
- [ ] **Async & Subagent Handoff Protocol:**
  - Save the GCP Build ID and current target version to `.cache/build-state.json`.
  - Check build status periodically using:
    `gcloud builds describe <BUILD_ID> --project=${PROJECT_ID} --format="value(status)"`
  - If the build is in `QUEUED` or `WORKING` status, write a status summary, commit state to `.cache/build-state.json`, and pause execution/handoff back to the user or dispatch an async task. Do not hang.
- [ ] Once `SUCCESS` is achieved, verify the new ISO is present on GCS: `gcloud storage objects describe gs://${GCS_BUCKET_NAME}/sync/gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso --project=${PROJECT_ID}`.

### State 4: Bootimus PXE Deployment
- [ ] Wait for the NAS sync to happen by querying the Bootimus API for the version to show up in the list. Wait at least 30s.
- [ ] Execute `./src/build/bootimus.py --list` to check the status of the current groups and images.
- [ ] Only after the ISO shows up in Bootimus, deploy the compiled image: `./src/build/bootimus.py gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso` (which enforces a 30s settling window right after trigger-scan).
- [ ] The agent must monitor the progress of `bootimus.py` as it explodes the kernel, sets the type to Ubuntu, enables the ISO, and sets the boot parameters.
- [ ] **MANDATORY BOOTIMUS COMPLETION GATE:** You MUST execute `python3 test/bin/check-bootimus-settings.py` after deploying the ISO and the 30s cool-off period.
  - At NO TIME should there be a built `gdc-bootstrap-*` ISO that does not complete extraction in Bootimus.
  - The script asserts that the image is classified as `ubuntu`, extraction is `COMPLETE`, and Boot Parameters (autoinstall) are correctly set.
  - If extraction is still `PENDING` or `EXTRACTING`, you MUST wait and retry until `check-bootimus-settings.py` returns `SUCCESS`.
- [ ] Verify the stability-verification feedback loop successfully locks and holds parameters by querying the API one final time.

### State 5: E2E Integration Testing (local builds only, executed with explicit ask only)
- [ ] NOTE: Tests can and should be run locally if they do not require a QEMU environment.
- [ ] Validate autoinstall schemas: `./test/validate_iso_static.sh` (or `python3 test/validate_iso_static.py`).
- [ ] (Optional) Launch headless virtual sandbox: `./test/run_qemu_e2e.sh`.
- [ ] Poll serial/console outputs to verify:
  - First-boot Ansible-pull triggers and completes without error.
  - Logical volume sizes are auto-sized.
  - TPM 2.0 PCR `0+7` LUKS registration and step-ca certificates are fully verified.

### State 6: After Action Report (AAR)
- [ ] Compile and save an After Action Report (AAR) in `docs/reports/aar-v${ISO_VERSION}.md` containing:
  - **Build Metadata:** GCP Project ID, Build ID, final execution status, and detailed timing (Start Time, Finish Time, and total elapsed duration).
  - **Version Information:** Remastered ISO version (`ISO_VERSION`), builder container version (`BUILD_VERSION`), base OS ISO filename, and active Git branch/commit SHA.
  - **Phases Status Table:** A tabular overview highlighting the completeness and success status of all states.
  - **Diagnostic Log Links:** Cloud Build, GCS, Local paths.
  - **GDC Companion Live Telemetry Logs:** Direct HTTPS link.

### State 7: Download and share the Build Report in GDC Companion
- [ ] Download the build-report from the GCS bucket folder `gs://${GCS_BUCKET_NAME}/reports/build-reports/build-report-v${ISO_VERSION}.json` or `.md`. to ./build-workspace/output/build-report-{{ISO_VERSION}}.json
- [ ] **Upload** to the gdc-companion service using the following pattern. Expect to see an HTTP 200
  ```shell
  curl -X POST http://{{gdc-companion}}/v1/build-reports/ingest \
  -F "file=@path/to/build-report-gdc-{{ISO_VERSION}}.json"

  # Response
  `{
  "status": "ingested",
  "id": "gdc-v1.2.0"
  }`
  ```
