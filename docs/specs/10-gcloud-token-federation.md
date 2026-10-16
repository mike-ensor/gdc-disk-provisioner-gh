# Specification: GDC Companion Token Federation for gcloud

**Spec Identifier:** `GDC-SPEC-010-TOKEN-FEDERATION`  
**Status:** PROPOSED  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Executive Summary & Purpose
This specification outlines the architecture for authenticating the `gcloud` CLI tool on offline or newly provisioned GDC bare-metal nodes without persisting static GCP Service Account JSON keys to disk. 

By leveraging the existing Mutual TLS (mTLS) trust established between the node and the **GDC Companion**, the companion app will act as a secure token broker. It will impersonate the node's designated primary Google Service Account (GSA) and mint short-lived OAuth 2.0 access tokens. This token is securely transmitted to the node to authenticate `gcloud` during the `CLUSTER_READY` and `CLUSTER_TURNUP` stages.

This architecture strictly adheres to the "Keyless Profile" outlined in `GDC-SPEC-005-TURNUP`.

*(For the complete hardware attestation flow, EKCert verification, Step CA certificate issuance, and mTLS handshake sequence, see [`docs/TPM_ATTESTATION_AND_MTLS.md`](../TPM_ATTESTATION_AND_MTLS.md).)*

---

## 2. Dual-Application Requirements

This specification defines coordinated responsibilities across two distinct applications:
1.  **GDC Companion App (Rust / CloudRun / GKE):** The central orchestration API handling mTLS termination and token generation.
2.  **GDC Bare Metal Node (Ansible):** The client node that requests the token and applies it to the local system environment.

### 2.1. GDC Companion Application Requirements

The GDC Companion must expose a new endpoint to broker GCP tokens.

#### Endpoint Contract
*   **Path:** `GET /v1/machine-credentials/gcp-token/{mac-address}`
*   **Authentication:** mTLS client certificate validation is **mandatory**. The Common Name (CN) or SAN of the client certificate must cryptographically match the requested `{mac-address}`.
*   **Authorization:** The Companion must lookup the node's configuration using the MAC address to identify the `gcp_info.primary_gsa` associated with that machine.
*   **Execution (GCP IAM API):** 
    *   The Companion itself will run with a high-privilege Workload Identity (e.g., in GKE or CloudRun) that holds the `roles/iam.serviceAccountTokenCreator` role.
    *   The Companion will call the GCP IAM Credentials API: `generateAccessToken` targeting the node's `primary_gsa`.
    *   It requests a short-lived token (e.g., 3600 seconds / 1 hour).
*   **Response:**
    *   **200 OK:** Returns a JSON payload containing the short-lived access token and expiry.
    ```json
    {
      "access_token": "ya29.c.c0AY_VpZ...",
      "expires_in": 3600,
      "token_type": "Bearer"
    }
    ```
    *   **401/403/404:** Standard error codes for missing mTLS, invalid MAC, or missing machine registration.

### 2.2. GDC Bare Metal Node (Ansible) Requirements

The `machine_orchestration` Ansible role must be updated to request this token and authenticate `gcloud` early in the `CLUSTER_READY` stage.

#### Execution Sequence
1.  **Token Request:** During the execution of `machine_orchestration`, after mTLS certificates are confirmed and the `machine_config` is pulled, the node makes a `GET` request to `/v1/machine-credentials/gcp-token/{{ node_mac }}` using its `/var/gdc-install/keys/client.crt` and `client.key`.
2.  **Token Persistence (In-Memory/Volatile):** The returned `access_token` is extracted using `jq` or Ansible's `from_json` filter.
3.  **Authentication:** The node authenticates `gcloud` by passing the raw access token directly (avoiding disk persistence where possible, or writing to a strict `tmpfs` RAM disk if a file is required by `gcloud` bounds).
    *   *Command:* `gcloud auth login --cred-file=...` (Requires a credential configuration file) OR `gcloud config set auth/access_token <TOKEN>`.
    *   *Note:* `gcloud` supports `--access-token-file` or environment variable `CLOUDSDK_AUTH_ACCESS_TOKEN` for ephemeral auth without writing to disk permanently.
4.  **Verification:** Run `gcloud auth list` or `gcloud config get-value account` to verify the GSA is active.
5.  **Post-Condition:** With `gcloud` authenticated, subsequent tasks in `CLUSTER_READY` (such as pulling from Google Secret Manager) can execute seamlessly.

---

## 3. Implementation Blueprint (Node-Side)

### Required Ansible Changes (`src/ansible/roles/machine_orchestration/tasks/main.yml`)

We will replace the existing legacy JSON key check with the dynamic Companion fetch.

```yaml
- name: "GDC-ORCH | Fetch short-lived GCP token from GDC Companion"
  ansible.builtin.uri:
    url: "https://gdc-companion.gdc-labs.com/v1/machine-credentials/gcp-token/{{ node_mac }}"
    method: GET
    client_cert: "/var/gdc-install/keys/client.crt"
    client_key: "/var/gdc-install/keys/client.key"
    status_code: 200
    return_content: yes
  register: companion_token_response
  ignore_errors: true

- name: "GDC-ORCH | Authenticate gcloud using short-lived access token"
  ansible.builtin.shell: |
    # Configure gcloud to use the ephemeral token
    gcloud config set auth/access_token {{ (companion_token_response.content | from_json).access_token }}
    # Set the default project
    gcloud config set project {{ machine_config.gcp_info.project_id }}
  when: 
    - companion_token_response.status == 200
    - companion_token_response.content is defined
  no_log: true # Ensure token is never printed to Ansible console
```

---

## 4. Security Considerations
*   **Token Expiry:** The requested OAuth token should have the minimum lifespan required to complete the cluster turnup (typically 1 hour).
*   **No Disk Persistence:** The raw `access_token` must be passed directly via memory/environment variables or `gcloud config set` rather than writing a `.json` credential to the LUKS partition.
*   **Companion IAM Scope:** The Companion App's IAM Service Account requires `roles/iam.serviceAccountTokenCreator`, but should be restricted via IAM Conditions to only generate tokens for specific `gdc-node-*` GSAs, preventing lateral movement if the Companion is compromised.
