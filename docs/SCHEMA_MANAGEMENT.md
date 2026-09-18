# GDC Schema Management & Upstream Synchronization

This document establishes the lifecycle, canonical ownership, and synchronization procedures for JSON Schemas shared between **`gdc-companion`** and **`gdc-disk-provisioner`**.

---

## 1. Canonical Source of Truth

The authoritative, canonical source of truth for the machine configuration schema is owned by **`gdc-companion`**:
* **Upstream Repository:** `gitlab.com/gcp-solutions-public/retail-edge/gdc-companion`
* **Upstream File Path:** `docs/machine-schema.json`
* **Rust Schema Structs:** `crates/models/src/schemas.rs`

Any additions, modifications, or deprecations to the machine configuration contract (e.g. adding cluster topologies, new network parameters, or authentication fields) **must originate in the `gdc-companion` repository**.

---

## 2. Why is `docs/machine-schema.json` Mirrored Here?

The `gdc-disk-provisioner` repository maintains a vendored copy at:
`docs/machine-schema.json`

This mirrored copy is required because:
1. **Air-Gapped & Offline ISO Builds:** The ISO generation and remastering pipeline operates offline and must validate configuration templates without access to external networks.
2. **Hermetic CI Execution:** GitLab CI runners execute jobs inside isolated Docker containers (`python:3.12-slim`) that do not have access to sibling directories or external repositories.
3. **Pre-Flight Validation:** Workstation tools like `bin/node-ops/inject-manual-facts.sh` need local, offline access to validate manual facts before uploading them to bare-metal edge nodes.

---

## 3. How Divergence is Prevented

To ensure the local schema never silently drifts from `gdc-companion`, the following safeguards are in place:

### 3.1. In-File Ownership Metadata
`docs/machine-schema.json` contains an explicit JSON Schema `$comment` tag:
```json
"$comment": "UPSTREAM OWNER: gdc-companion (docs/machine-schema.json). DO NOT EDIT DIRECTLY. This file is vendored from the gdc-companion repository to support hermetic, air-gapped CI and offline validation. Run bin/sync-schemas.sh to sync with upstream."
```

### 3.2. Automated Parity Test
`test/test_manual_facts_schema.py` contains `test_no_divergence_from_upstream_companion`. Whenever tests are run in an environment where `gdc-companion` is available:
* It reads both upstream and local schemas.
* It parses and asserts semantic equality across all schema properties, required fields, and types.
* If a drift occurs, the test fails immediately with:
  ```
  Local schema has diverged from upstream! Run ./bin/sync-schemas.sh to synchronize.
  ```

### 3.3. Drift Check Tooling (`bin/sync-schemas.sh`)
The repository includes a dedicated synchronization utility:

```bash
# Check if schemas are identical (exits 0 if clean, 1 if diverged)
./bin/sync-schemas.sh --check

# Synchronize local schema with upstream gdc-companion
./bin/sync-schemas.sh
```

---

## 4. Operator Runbook: Updating the Schema

When updating the machine schema:

1. **Update `gdc-companion` first:**
   - Modify `docs/machine-schema.json` and associated Rust model structs in `gdc-companion`.
   - Submit and merge the changes into `gdc-companion`.
2. **Synchronize in `gdc-disk-provisioner`:**
   ```bash
   ./bin/sync-schemas.sh
   ```
3. **Verify tests:**
   ```bash
   python3 -m unittest test/test_manual_facts_schema.py
   python3 -m unittest discover -s test -p 'test_*.py'
   ```
4. **Commit and create MR:**
   ```bash
   git commit -am "chore: sync docs/machine-schema.json from gdc-companion"
   ```
