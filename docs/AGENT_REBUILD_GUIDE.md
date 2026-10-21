# Agent Runbook: Full GDC Environment Rebuild & Deployment Cycle

This guide provides AI agents and platform engineers with exact instructions to execute a **full environment rebuild, Bootimus PXE staging, and node fleet reboot** with a single command or step-by-step.

---

## 1. Quick Start: Single-Command Unattended Rebuild

To completely rebuild and reboot an environment in one command, execute:

```bash
./bin/local/gdc-node-ops.sh rebuild-cycle --profile <PROFILE> --version <SEMVER> --yes
```
*(Or directly using the standalone orchestrator: `./bin/local/gdc-rebuild-environment.sh --profile <PROFILE> --version <SEMVER> --yes`)*

### Concrete Example (Barn Environment)
```bash
./bin/local/gdc-node-ops.sh rebuild-cycle --profile barn --version 0.11.3 --yes
```

### Dry-Run Simulation (Preview Actions)
```bash
./bin/local/gdc-node-ops.sh rebuild-cycle --profile barn --dry-run
```

---

## 2. What the Rebuild Cycle Executes (Architecture & Data Flow)

```text
┌────────────────────────────────────────────────────────────────────────────────┐
│  Phase 1: GDC Companion Profile Sync                                           │
│  bin/local/gdc-node-ops.sh pull-profile --name <profile>                       │
│  • Downloads src/build/<profile>.env (contains target machines & ISO prefix)   │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  Phase 2: Cloud Build Remastering & ISO Publication                            │
│  ./build.sh --env <profile> --version <version> --bootimus --yes               │
│  • Compiles custom LiveCD ISO via Google Cloud Build                           │
│  • Publishes to GCS (gs://gdc-disk-provisioner-isos/sync/<ISO>)                │
│  • Triggers initial Bootimus NAS sync and extraction                           │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  Phase 3: Bootimus Settlement & Auto-Heal Verification Gate                    │
│  python3 test/bin/check-bootimus-settings.py <ISO>                             │
│  • Asserts kernel & initrd extraction is COMPLETE                              │
│  • Verifies autoinstall and nocloud boot parameters are strictly locked        │
│  • (Fallback) Runs ./bootimus.sh <ISO> if extraction/parameters need healing    │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  Phase 4: Bare-Metal Fleet Reboot via UEFI PXE NextBoot                        │
│  bin/local/gdc-node-ops.sh reset-pxe --next-boot <ISO> --nodes <IPS> --yes     │
│  • Unregisters stale Fleet memberships from Google Cloud Fleet                 │
│  • Configures Bootimus NextBoot one-shot override per node MAC                 │
│  • Sets UEFI BootNext to PXE and issues immediate reboot                       │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Step-by-Step Manual Breakdown

If an agent needs to execute the phases individually or debug a specific stage:

### Step 1: Pull Profile from GDC Companion
```bash
./bin/local/gdc-node-ops.sh pull-profile \
    --name barn \
    --companion-url https://gdc-companion.ensor-labs.com/
```
* **Output:** Updates `src/build/barn.env` with current cluster definitions and `TARGET_TEST_MACHINES`.

### Step 2: Compile ISO via Google Cloud Build
```bash
./build.sh --version 0.11.3 --env barn --bootimus --yes
```
* **Output:** Builds `gdc-labs-24.04-v0.11.3-debug.iso`, copies to `gs://gdc-disk-provisioner-isos/sync/`, and initiates Bootimus ingestion.

### Step 3: Verify and Force-Lock Bootimus Settings
Before touching bare-metal nodes, verify that Bootimus has fully extracted the kernel and locked boot parameters:
```bash
# Verify settings
python3 test/bin/check-bootimus-settings.py gdc-labs-24.04-v0.11.3-debug.iso

# If Bootimus has not extracted or needs manual force-ingestion:
./bootimus.sh gdc-labs-24.04-v0.11.3-debug.iso
```

### Step 4: Schedule PXE Next-Boot and Reboot Nodes
```bash
./bin/local/gdc-node-ops.sh reset-pxe \
    --next-boot gdc-labs-24.04-v0.11.3-debug.iso \
    --nodes 192.168.9.241,192.168.9.242,192.168.9.243,192.168.9.244,192.168.9.246 \
    --user gdc-admin \
    --key ~/.ssh/gdc-disk-provisioner \
    --yes
```

---

## 4. Parameter Reference & Defaults

| Option | Description | Default Source |
| :--- | :--- | :--- |
| `--profile <NAME>` | Environment profile name (`barn`, `honeywell`) | `barn` (or `$ISO_PROFILE`) |
| `--version <VER>` | SemVer version tag (`0.11.3`) | Current value in `VERSION` file |
| `--companion-url <URL>` | Base URL for GDC Companion | `local.env` or `https://gdc-companion.ensor-labs.com/` |
| `--nodes <IPS>` | Comma-separated target node IPs | `TARGET_TEST_MACHINES` inside `src/build/<profile>.env` |
| `--key <PATH>` | SSH private key to authenticate to nodes | `~/.ssh/gdc-disk-provisioner` (fallback: `~/.ssh/id_ed25519`) |
| `--ssh-user <USER>` | SSH user on target bare-metal nodes | `gdc-admin` |
| `--bootimus-user <USER>` | Bootimus API username | `BOOTIMUS_USER` (defaults to `admin`) |
| `--bootimus-pass <PASS>` | Bootimus API password | `BOOTIMUS_PASS` |
| `--secret-method <METHOD>` | Secret provider lookup: `env` (default), `file`, `infisical`, `gcloud` | `BOOTIMUS_SECRET_METHOD` (or `env`) |
| `--secret-file <PATH>` | File containing credentials JSON (`{"username": "...", "password": "..."}`) | `BOOTIMUS_SECRET_FILE` |
| `--skip-auth` | Skip pre-flight Bootimus authentication check | `false` (auth is checked by default) |
| `--skip-build` | Skip compilation; only verify Bootimus & reboot | `false` |
| `--skip-reboot` | Compile and verify Bootimus, but do not reboot | `false` |
| `--dry-run` | Print planned commands without executing | `false` |
| `--yes`, `-y` | Unattended execution (skips `read` prompts) | `false` |

---

## 5. Bootimus Credential Lookup Hierarchy (Zero Hardcoded Lock-in)

The orchestrator and Bootimus scripts resolve credentials using an explicit, isolated 4-tier hierarchy:
1. **Explicit CLI flags:** `--bootimus-user <U> --bootimus-pass <P>` (highest priority).
2. **Environment variables:** `BOOTIMUS_USER` and `BOOTIMUS_PASS` (e.g. exported in shell or in `src/build/local.env`).
3. **Secret file:** `--secret-file <PATH>` or `BOOTIMUS_SECRET_FILE`.
4. **Dynamic provider:** Only invoked if explicitly opted into via `--secret-method [infisical|gcloud]`:
   - `infisical`: Queries `bootimus_creds` via `infisical secrets get`.
   - `gcloud`: Queries Google Secret Manager `bootimus_creds` via `gcloud secrets versions access`.
   - Default: `env`. External secret managers are **never** invoked unless explicitly requested.

---

## 6. Agent Troubleshooting & Recovery Rules

1. **Stuck in `check-bootimus-settings.py`**:
   Synology Cloud Sync may take 30–60 seconds to pull the ISO from GCS to local NAS storage (`/volume1/iso_share/sync/`). The orchestrator automatically retries up to 10 times and invokes `./bootimus.sh <ISO>` to heal extraction parameters.
2. **SSH Authentication Failure during `reset-pxe`**:
   Ensure `~/.ssh/gdc-disk-provisioner` exists with permissions `0600`. If running as a non-interactive agent, always provide `--key <PATH>`.
3. **Fleet Hub Collision**:
   `reset-pxe` automatically unregisters prior Fleet memberships in GCP before rebooting nodes to avoid GKE Hub membership collision during re-installation. If you need to preserve membership, pass `--skip-fleet`.
