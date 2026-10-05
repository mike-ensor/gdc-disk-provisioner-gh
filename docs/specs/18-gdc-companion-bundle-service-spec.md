# GDC Companion Specification: Custom Playbook Bundle Management & Distribution Service

**Document Version:** 1.0.0  
**Target Application:** `gdc-companion` microservice & Web UI  
**Target Repository:** `gdc-companion`  
**Coordinated Feature:** GDC Disk Provisioner Custom Playbook Lifecycle Extensions (`GDC-SPEC-017`)  
**Schema Authority:** `docs/machine-schema.json` (Draft-07)  

---

## 1. Executive Summary

With the introduction of the GDC Lifecycle Playbook Extension framework (`GDC-SPEC-017`), target bare-metal edge nodes can download and execute custom post-stage Ansible playbooks (such as post-cluster burn-in tests and workload validation suites).

To support this capability without requiring third-party object stores or external registries, `gdc-companion` must provide:
1. **Bundle Storage & Upload APIs:** Secure endpoints to upload, version, validate, and store custom `.tar.gz` bundles.
2. **Bundle Distribution Service:** Authenticated streaming endpoint allowing edge nodes (via mTLS client certificate and/or Bearer API token) to fetch the bundles.
3. **Machine Configuration Binding:** Updates to `machine-schema.json`, database models, and the Web UI allowing operators to attach a bundle to individual machines or machine profiles.
4. **Automated SHA-256 Checksumming:** Automatic calculation and injection of the SHA-256 hash into the machine's `custom_extensions` configuration payload.

---

## 2. Architecture & Service Components

```
+------------------+         Upload Bundle (multipart/form-data)         +--------------------+
|  Operator / CI   | --------------------------------------------------> |   GDC Companion    |
| (Web UI or API)  | <-------------------------------------------------- |   (Axum Service)   |
+------------------+         Returns bundle_id, sha256, URL               +----+---------------+
                                                                               |
                               Stores archive into /var/lib/gdc-companion/data/|
                                                                               v
+------------------+           GET /v1/machine-info/{mac}                +--------------------+
|                  | --------------------------------------------------> |                    |
|  Edge Node Host  | <-------------------------------------------------- |  Config Generator  |
|  (Disk Provision)|     Returns custom_extensions: {bundle_url, sha256} |                    |
|                  |                                                     +--------------------+
|                  |           GET /v1/bundles/{id}/download                   |
|                  | --------------------------------------------------> |  Artifact Server   |
|                  | <-------------------------------------------------- |  (mTLS / Token)    |
|                  |          Streams custom-bundle.tar.gz                     |
+------------------+                                                     +--------------------+
```

---

## 3. Data Contract & Schema Changes

### 3.1 Machine Schema (`docs/machine-schema.json`)
The machine configuration schema delivered via `GET /v1/machine-info/{mac}` must be augmented with the optional `custom_extensions` object:

```json
{
  "properties": {
    "custom_extensions": {
      "type": ["object", "null"],
      "description": "Optional custom Ansible playbook lifecycle extension configuration.",
      "properties": {
        "bundle_url": {
          "type": "string",
          "format": "uri",
          "description": "HTTPS URL from which the edge node downloads the playbook tarball."
        },
        "sha256": {
          "type": "string",
          "pattern": "^[a-fA-F0-9]{64}$",
          "description": "Hex-encoded SHA-256 checksum of the bundle tarball."
        }
      },
      "required": ["bundle_url", "sha256"]
    }
  }
}
```

---

## 4. REST API Specifications

### 4.1 Upload Custom Bundle
* **Method:** `POST`
* **Path:** `/v1/bundles`
* **Auth:** Operator Bearer Token (`ADMIN` or `OPERATOR` role)
* **Content-Type:** `multipart/form-data`
* **Request Fields:**
  * `file`: The `.tar.gz` bundle archive (max 200MB).
  * `name`: Human-readable identifier (e.g., `burnin-suite-v1.0`).
  * `description`: Optional text description.
* **Backend Processing:**
  1. Validates that the uploaded file is a valid gzip-compressed tar archive.
  2. Computes the SHA-256 hash in a single streaming pass.
  3. Verifies that the archive contains at least one recognized entry (e.g. `cluster_turnup.yml`, `post_cluster.yml`, or `requirements.yml`).
  4. Stores the archive on persistent disk under `/var/lib/gdc-companion/bundles/{bundle_id}.tar.gz`.
  5. Records metadata into database table `playbook_bundles`.
* **Response (HTTP 201 Created):**
  ```json
  {
    "bundle_id": "bnd_01j9a8c7b3e5f2",
    "name": "burnin-suite-v1.0",
    "filename": "burnin-suite-v1.0.tar.gz",
    "size_bytes": 1428570,
    "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "download_url": "/v1/bundles/bnd_01j9a8c7b3e5f2/download",
    "created_at": "2026-10-04T12:00:00Z"
  }
  ```

---

### 4.2 List Custom Bundles
* **Method:** `GET`
* **Path:** `/v1/bundles`
* **Auth:** Bearer Token
* **Response (HTTP 200 OK):**
  ```json
  {
    "bundles": [
      {
        "bundle_id": "bnd_01j9a8c7b3e5f2",
        "name": "burnin-suite-v1.0",
        "description": "Hardware stress test and storage burn-in suite",
        "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "size_bytes": 1428570,
        "created_at": "2026-10-04T12:00:00Z"
      }
    ]
  }
  ```

---

### 4.3 Download Bundle Artifact (Node Endpoint)
* **Method:** `GET`
* **Path:** `/v1/bundles/{bundle_id}/download`
* **Auth:** Node Identity (either `Authorization: Bearer <API_KEY>` or mTLS Client Certificate issued by GDC Step-CA)
* **Response:**
  * `Content-Type: application/gzip`
  * `Content-Disposition: attachment; filename="{name}.tar.gz"`
  * `ETag: "{sha256}"`
  * Streamed binary payload.

---

### 4.4 Delete Custom Bundle
* **Method:** `DELETE`
* **Path:** `/v1/bundles/{bundle_id}`
* **Auth:** Admin Bearer Token
* **Behavior:** Fails with HTTP 409 Conflict if any active machine or template references this bundle.

---

## 5. Web UI & Frontend Workflows

1. **Bundle Inventory Tab (`/bundles`):**
   - Displays all registered bundles, upload dates, file sizes, and SHA-256 hashes.
   - Includes a drag-and-drop file upload modal.
2. **Machine Details / Edit Modal & Profile Templates:**
   - Under the **Provisioning & Extensions** card, provides a dropdown to select an uploaded custom bundle.
   - Automatically populates the `bundle_url` and calculated `sha256` into the target machine's config.
   - **Operational Guidance Tooltip:** Includes an advisory banner in the UI: *"Warning: Avoid assigning disparate one-off bundles to individual machines. Use standardized fleet-wide bundles across machine profiles to prevent snowflake cluster configurations."*
3. **Telemetry & Evidence Display:**
   - When a machine reports an error in `custom_extension`, the Web UI surfaces a distinct warning badge:
     `Stage Failed (Custom Extension)`
   - Displays the playbook name, stage, and guidance to inspect node logs.

---

## 6. Security & Storage Policies

1. **Storage Quota:** Maximum 5GB total bundle storage allocated under `/var/lib/gdc-companion/bundles/`.
2. **Access Control:** Bundle download endpoint accepts both API Bearer tokens and valid client certificates verified against the Step-CA root.
3. **Archive Sanitization:** The upload extractor asserts that tar file headers do not contain path traversal entries (e.g. `../../etc/shadow`).
