---
name: gdc-iso-build-deploy
description: Build, remaster, validate, and deploy GDC custom bootstrap ISOs. Use when compiling ISOs, running remaster pipelines, deploying release images to PXE/Bootimus, or troubleshooting installer boot loops, TPM enrollment, and partition failures.
dependencies: []
---

# Skill: gdc-iso-build-deploy

## 1. Abstract
Provides a structured workflow for remastering, cloud-building, PXE deploying, and validating GDC Custom Bootstrap ISOs. Orchestrates local and cloud environments, tracking long-running builds asynchronously using a state-machine persistence pattern.

## 2. Usage Examples

### Example 1: Full Pipeline Build
**Prompt:** "Build and deploy the new custom GDC ISO to the PXE server."
**Action:** The agent executes `./buildAll.sh` and tracks progress through each gate.

### Example 2: Resume Asynchronous Build Check
**Prompt:** "Is the custom GDC ISO build done yet?"
**Action:** The agent reads `.cache/build-state.json` to fetch the active Build ID, queries `gcloud builds describe`, and proceeds to Bootimus deployment if successful.

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
- [ ] Assert key variables: `PROJECT_ID`, `BUILD_VERSION`, `REGION`, `ISO_VERSION`.
- [ ] Check GCS destination collision to prevent overwrites:
  `gcloud storage objects describe gs://${GCS_BUCKET}/sync/gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso --project=${PROJECT_ID}`.
- [ ] Ensure local Cache directory is ready: `.cache/isos/`.

### State 2: Build Container Tooling (If Needed)
- [ ] Verify image `${REGION}-docker.pkg.dev/${PROJECT_ID}/gdc-build-images/iso-builder:${BUILD_VERSION}` exists in artifact registry.
- [ ] If missing, run `./build-builder.sh` to compile and push the xorriso/rsync-equipped builder container.

### State 3: Cloud Build Compilation & Async Handshake
- [ ] Execute `./build.sh` to trigger the Google Cloud Build pipeline.
- [ ] **Async & Subagent Handoff Protocol:**
  - Save the GCP Build ID and current target version to `.cache/build-state.json`.
  - Check build status periodically using:
    `gcloud builds describe <BUILD_ID> --project=${PROJECT_ID} --format="value(status)"`
  - If the build is in `QUEUED` or `WORKING` status, write a status summary, commit state to `.cache/build-state.json`, and pause execution/handoff back to the user or dispatch an async task. Do not hang.
- [ ] Once `SUCCESS` is achieved, verify the new ISO is present on GCS: `gs://${GCS_BUCKET}/sync/gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso`.

### State 4: Bootimus PXE Deployment
- [ ] Execute `./src/build/bootimus.py --list` to check current groups and images.
- [ ] Deploy the compiled image: `./src/build/bootimus.py gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso`.
- [ ] Verify the self-healing DB audit completes (verifying custom autoinstall parameters are written and locked).

### State 5: E2E Integration Testing
- [ ] Validate autoinstall schemas: `./test/validate_iso_static.sh`.
- [ ] (Optional) Launch headless virtual sandbox: `./test/run_qemu_e2e.sh`.
- [ ] Poll serial/console outputs to verify:
  - First-boot Ansible-pull triggers and completes without error.
  - Logical volume sizes are auto-sized.
  - TPM 2.0 PCR `0+2+7` LUKS registration and step-ca certificates are fully verified.
