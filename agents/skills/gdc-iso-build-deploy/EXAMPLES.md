# GDC ISO Build & Deploy Examples

This file provides ready-to-run CLI commands, troubleshooting checks, and async patterns for operating the GDC custom bootstrap pipeline.

---

## 1. Preparing the Environment & Pre-Flight Checks

Before doing any work, you must load and check your environment settings.

```bash
# Load workspace variables
source .envrc

# Display active variables for validation
echo "GCP Project:   $PROJECT_ID"
echo "Target Region: $REGION"
echo "ISO Version:   $ISO_VERSION"

# Pre-flight GCS collision check (asserts output is not already on GCS)
TARGET_ISO="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso"
if gcloud storage objects describe "gs://${GCS_BUCKET}/sync/${TARGET_ISO}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "[!] Collision: ${TARGET_ISO} already exists! Increment version in .envrc before building."
else
    echo "[+] Collision check passed. Destination is clear."
fi
```

---

## 2. Compiling the ISO Builder Image

If modifying the tooling container definitions (e.g. adding tools inside `Dockerfile`), compile the builder image:

```bash
# Triggers the Artifact Registry docker push
./build-builder.sh
```

---

## 3. Triggering Cloud Build (Async Workflow)

Rather than letting the CLI agent block and hang during 15-minute compilations, trigger the build, record state, and verify asynchronously:

```bash
# 1. Trigger the cloud remaster pipeline and capture its build output
./build.sh --bucket your-gcs-bucket-name

# 2. Store active state to .cache/build-state.json
cat <<EOF > .cache/build-state.json
{
  "iso_version": "${ISO_VERSION}",
  "gcs_bucket": "your-gcs-bucket-name",
  "status": "triggered"
}
EOF

# 3. Check build status periodically (non-blocking poll)
gcloud builds list \
  --project="${PROJECT_ID}" \
  --limit=3 \
  --format="table(id, status, startTime, finishTime)"
```

---

## 4. Bootimus PXE Server Operations

Bootimus acts as your dynamic PXE boot provider. You can query, ingest, or force configurations easily.

```bash
# List active PXE groups and registered boot images
./src/build/bootimus.py --list

# Register the newly compiled ISO image on the PXE server
NEW_ISO="gdc-bootstrap-ubuntu-24.04-v${ISO_VERSION}.iso"
./src/build/bootimus.py "${NEW_ISO}"

# Force kernel/initrd re-extraction (bypasses cache if rebuilding with same name)
./src/build/bootimus.py "${NEW_ISO}" --force

# Filter the Bootimus image tree list to show only custom GDC images
./src/build/bootimus.py --list --filter "gdc"
```

---

## 5. Verification & Headless Testing

Once compiled and registered, verify your configuration and boot states:

```bash
# Tier 1: Run static schema and YAML syntax verification on cloud-init/autoinstall
./test/validate_iso_static.sh

# Tier 2: Launch local headless QEMU integration sandbox testing
./test/run_qemu_e2e.sh

# Check the live serial console outputs to audit the setup progress
tail -f gdc-installer-receiver.log
```

---

## 6. Troubleshooting Boot Loops & Parameter Clashes

If a node gets stuck in a boot-loop, it is usually because Bootimus lost its correct autoinstall kernel boot parameters. Use the self-healing DB script:

```bash
# Bootimus automatically runs a self-healing audit upon execution
# You can force a fresh self-healing cycle by running list or ingestion:
./src/build/bootimus.py --list
```
