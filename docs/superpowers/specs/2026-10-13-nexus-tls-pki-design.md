# Specification: Dual-Tier Nexus TLS & Enterprise Sub-CA PKI Architecture

**Document Identifier:** `2026-10-13-nexus-tls-pki-design`  
**Status:** PROPOSED  
**Author:** GDC Disk Provisioner & Infrastructure Security Architecture Team  
**Scope:** GDC Bare Metal Node Host & In-Cluster Kubernetes PKI Integration  

---

## 1. Executive Summary & Purpose

This specification defines the Public Key Infrastructure (PKI) architecture, host-level reverse proxy configuration, secret ingestion pipeline, and certificate rotation lifecycle required to enable end-to-end TLS termination for Sonatype Nexus (`nexus.internal.gdc.local`) across both bare-metal host bootstrapping and in-cluster Kubernetes services.

The solution operates as a **Dual-Tier PKI**:
1. **Tier 1 (Host Bootstrapping & Readiness):** Before Kubernetes exists, host-level provisioning fetches an enterprise-delegated Intermediate Sub-CA from Google Cloud Secret Manager (GSM) via hardware-attested Mutual TLS (mTLS) with GDC Companion. The host utilizes `step-cli` to mint local server certificates offline and launches an Nginx reverse proxy on port 443.
2. **Tier 2 (Kubernetes Handover):** During post-cluster turnup, the Sub-CA credentials are seeded into a Kubernetes Secret in the `cert-manager` namespace. A `cert-manager` `ClusterIssuer` (type `CA`) assumes autonomous lifecycle management for all in-cluster microservices, ingresses, and pods.

---

## 2. Core Decisions & Principles

1. **Company Deliverables (Zero-Trust Delegated Sub-CA):**
   * **`ca.crt`**: Enterprise Intermediate Sub-CA certificate with `basicConstraints: CA:TRUE, pathlen:0` and strict RFC 5280 `nameConstraints` (`.internal.gdc.local`, `.gdc.local`).
   * **`ca.key`**: Sub-CA private key.
   * **`root.crt`**: Enterprise Root CA certificate for system trust registration.
2. **Daemonless Host Minting:**
   * No `step-ca` daemon runs on the host. Leaf certificates are minted offline in milliseconds using `step-cli` directly against the local Sub-CA keypair (`step certificate create --ca ... --ca-key ...`).
3. **Hardware & Cryptographic Demarcation (TPM Boundary):**
   * Public certificates (`root.crt`, `ca.crt`) reside in the standard Linux system trust store (`/usr/local/share/ca-certificates/`) and are registered via `update-ca-certificates`.
   * Private keys are stored in root-only protected paths (`/etc/ssl/sub-ca/` and `/etc/ssl/private/`, mode `0600 root:root`), which are hardware-encrypted at rest by LUKS sealed to the motherboard TPM 2.0 (PCRs `0+7`).
   * TPM hardware attestation (EKCert) remains dedicated to node identity authentication against GDC Companion.
4. **Unified Traffic Layout (Standard Port 443):**
   * Nginx terminates TLS on standard port `443` for `nexus.internal.gdc.local` (and `nexus.gdc.local`).
   * `/v2/` routes to `127.0.0.1:5001` (Docker/OCI Registry v2 API).
   * `/` routes to `127.0.0.1:8081` (APT repos, Raw LLM blobs, PyPI wheels, Web UI).
5. **Independent Lifecycle Timers:**
   * Host leaf certificate rotation is managed by a dedicated systemd timer (`refresh-nexus-tls.timer`) completely decoupled from GDC Companion cloud credential refresh timers (`refresh-gdc-credentials.service`).

---

## 3. High-Level Architecture Sequence

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Enterprise Root CA (Offline)                     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Signs once
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      Enterprise Sub-CA Keypair                         │
│              Stored in Google Cloud Secret Manager (GSM)               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
               1. mTLS Token Federation with GDC Companion
               2. gcloud secrets versions access (with location fallback)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         Target Bare-Metal Node                         │
│                                                                        │
│  • Public Root Trust: /usr/local/share/ca-certificates/enterprise.crt   │
│  • Sub-CA Credentials: /etc/ssl/sub-ca/sub-ca.{crt,key} (0600 root)   │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ TIER 1: Host Bootstrapping & Readiness (Stage 4 / service_hubs)   │  │
│  │ • step-cli mints /etc/ssl/certs/nexus.bundle.crt                 │  │
│  │ • Nginx Reverse Proxy (:443) terminates TLS                      │  │
│  │     - /v2/ ──► 127.0.0.1:5001 (OCI/Docker Registry)              │  │
│  │     - /   ──► 127.0.0.1:8081 (APT, Raw GGUF, PyPI, UI)           │  │
│  │ • refresh-nexus-tls.timer autonomously rotates leaf cert         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ TIER 2: Kubernetes Cluster Turnup Handover (Stage 7 / post_cluster)│
│  │ • Secret gdc-sub-ca-keypair seeded into cert-manager namespace   │  │
│  │ • ClusterIssuer (gdc-ca-issuer) created                          │  │
│  │ • cert-manager manages in-cluster Ingress & service certs        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Secret Manager Contract & Schema Synchronization

### 4.1. Upstream Schema Authority (`gdc-companion`)
Per `docs/SCHEMA_MANAGEMENT.md`, the canonical source of truth for the machine configuration contract is owned by `gdc-companion`.
The schema extension must first be committed in `../gdc-companion/docs/machine-schema.json` and mirrored to `docs/machine-schema.json`.

### 4.2. Schema Definition (`machine-schema.json`)
Under `.cluster`:
```json
{
  "cluster": {
    "sub_ca_secret": {
      "type": "object",
      "description": "Enterprise Intermediate Sub-CA credentials stored in Google Cloud Secret Manager",
      "required": ["gsm-name"],
      "properties": {
        "gsm-name": {
          "type": "string",
          "description": "Identifier of the Secret Manager secret holding the Sub-CA JSON payload"
        },
        "gsm-location": {
          "type": "string",
          "default": "global",
          "description": "Secret Manager replication location (e.g., global, us-central1)"
        }
      }
    }
  }
}
```

### 4.3. GSM Secret JSON Payload
The secret payload stored in Secret Manager must adhere to the following JSON structure:
```json
{
  "ca.crt": "-----BEGIN CERTIFICATE-----\n<Intermediate Sub-CA Certificate PEM>\n-----END CERTIFICATE-----",
  "ca.key": "-----BEGIN PRIVATE KEY-----\n<Intermediate Sub-CA Private Key PEM>\n-----END PRIVATE KEY-----",
  "root.crt": "-----BEGIN CERTIFICATE-----\n<Corporate Root CA Certificate PEM>\n-----END CERTIFICATE-----"
}
```

For the step-by-step operator runbook detailing input certificate generation, JSON packaging via `jq`/Python, `gcloud` Secret Manager commands, and IAM role assignment, see:  
👉 [`docs/pki-sub-ca-gsm-setup.md`](../../pki-sub-ca-gsm-setup.md)

### 4.4. Resilient Secret Ingestion Task (Ansible)
In `src/ansible/roles/machine_orchestration/tasks/main.yml`, secret retrieval implements location-aware fallback:
```yaml
- name: "GDC-PKI | Access Sub-CA Secret payload via gcloud"
  ansible.builtin.command: >-
    gcloud secrets versions access latest
    --secret={{ cluster_config.sub_ca_secret['gsm-name'] }}
    --project={{ gcp_project_id }}
    {% if cluster_config.sub_ca_secret['gsm-location'] is defined and cluster_config.sub_ca_secret['gsm-location'] | trim | length > 0 and cluster_config.sub_ca_secret['gsm-location'] != 'global' %}
    --location={{ cluster_config.sub_ca_secret['gsm-location'] }}
    {% endif %}
  register: gsm_sub_ca_res
  changed_when: false
  failed_when: false
  no_log: true

- name: "GDC-PKI | Fallback: Access Sub-CA Secret payload as global resource"
  ansible.builtin.command: >-
    gcloud secrets versions access latest
    --secret={{ cluster_config.sub_ca_secret['gsm-name'] }}
    --project={{ gcp_project_id }}
  register: gsm_sub_ca_res_fallback
  when:
    - gsm_sub_ca_res.rc != 0
    - cluster_config.sub_ca_secret['gsm-location'] is defined
    - cluster_config.sub_ca_secret['gsm-location'] != 'global'
  changed_when: false
  failed_when: false
  no_log: true

- name: "GDC-PKI | Adopt fallback Sub-CA payload if successful"
  ansible.builtin.set_fact:
    gsm_sub_ca_res: "{{ gsm_sub_ca_res_fallback }}"
  when:
    - gsm_sub_ca_res.rc != 0
    - gsm_sub_ca_res_fallback is defined
    - gsm_sub_ca_res_fallback.rc == 0

- name: "GDC-PKI | Parse and populate Sub-CA filesystem artifacts"
  block:
    - name: "GDC-PKI | Ensure Sub-CA and private key directories exist"
      ansible.builtin.file:
        path: "{{ item }}"
        state: directory
        owner: root
        group: root
        mode: '0700'
      loop:
        - /etc/ssl/sub-ca
        - /etc/ssl/private

    - name: "GDC-PKI | Write Corporate Root CA to system trust store"
      ansible.builtin.copy:
        dest: /usr/local/share/ca-certificates/gdc-enterprise-root.crt
        content: "{{ (gsm_sub_ca_res.stdout | from_json)['root.crt'] }}"
        owner: root
        group: root
        mode: '0644'
      notify: "Update CA Certificates"

    - name: "GDC-PKI | Write Sub-CA Certificate"
      ansible.builtin.copy:
        dest: /etc/ssl/sub-ca/sub-ca.crt
        content: "{{ (gsm_sub_ca_res.stdout | from_json)['ca.crt'] }}"
        owner: root
        group: root
        mode: '0644'

    - name: "GDC-PKI | Write Sub-CA Private Key"
      ansible.builtin.copy:
        dest: /etc/ssl/sub-ca/sub-ca.key
        content: "{{ (gsm_sub_ca_res.stdout | from_json)['ca.key'] }}"
        owner: root
        group: root
        mode: '0400'
        no_log: true
```

---

## 5. Host Reverse Proxy (`nginx`) & Unified URL Mapping

### 5.1. Nginx Host Configuration & Network Interface Binding Architecture
Deployed to `/etc/nginx/sites-available/nexus-tls.conf` and enabled via `/etc/nginx/sites-enabled/nexus-tls.conf`:

> **CRITICAL ARCHITECTURAL BINDING RULE:**  
> The host Nginx reverse proxy MUST listen strictly on the **VLAN cluster network IP** (`gdc_service_hub_ip`, e.g. `192.168.109.12:443`) and **NOT** on `127.0.0.1:443` or the machine/management IP:
> 1. **No Loopback (`127.0.0.1:443`) Collision:** GDC Anthos bare-metal deploys an `haproxy` static pod (`/etc/kubernetes/manifests/haproxy.yaml`) for control plane load balancing (`cplb-init`). HAProxy explicitly binds to both `127.0.0.1:443` and `CLUSTER_VIP:443`. If Nginx binds to `0.0.0.0:443` or `127.0.0.1:443`, HAProxy fails on startup (`cannot bind socket (Address already in use) for [127.0.0.1:443]`), deadlocking cluster initialization.
> 2. **Network Plane Isolation:** The machine/management IP (untagged native interface, e.g. `192.168.9.x`) is dedicated to host maintenance, SSH, and telemetry. Binding Nexus TLS to the cluster VLAN IP ensures all in-cluster container runtimes (`crictl`, Docker, Containerd, Kubernetes nodes) access package registries and OCI mirrors exclusively over the cluster VLAN plane.

```nginx
# /etc/nginx/sites-available/nexus-tls.conf
server {
    listen 192.168.109.12:443 ssl;
    server_name nexus.internal.gdc.local nexus.gdc.local;

    # Host certificate bundle generated via step-cli from Sub-CA
    ssl_certificate     /etc/ssl/certs/nexus.bundle.crt;
    ssl_certificate_key /etc/ssl/private/nexus.key;
    
    # Cryptographic hardening
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Security headers
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # Default body limit for Web UI & REST management endpoints (DoS protection)
    client_max_body_size 10M;

    # Route 1: Docker / OCI Registry v2 API
    location /v2/ {
        client_max_body_size 50G;
        client_body_buffer_size 512k;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        send_timeout 3600s;

        proxy_pass http://127.0.0.1:5001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto "https";
    }

    # Route 2: APT repositories, Raw GGUF models, and PyPI packages
    location /repository/ {
        client_max_body_size 50G;
        client_body_buffer_size 512k;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        send_timeout 3600s;

        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto "https";
    }

    # Route 3: Web UI and Nexus REST APIs
    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto "https";
    }
}
```

### 5.2. Unified URL Mapping Matrix
| Asset Class | Client Tool | Client Endpoint Configuration | Upstream Nexus Target |
| :--- | :--- | :--- | :--- |
| **`.deb`** | `apt`, `apt-get` | `URIs: https://nexus.internal.gdc.local/repository/gdc-apt-hosted/` | `127.0.0.1:8081` |
| **OCI Containers** | `containerd`, `crictl`, `docker` | `nexus.internal.gdc.local/<image>:<tag>` | `127.0.0.1:5001` |
| **`.gguf`** (LLMs) | `curl`, `wget`, python | `https://nexus.internal.gdc.local/repository/gdc-raw-hosted/models/<name>.gguf` | `127.0.0.1:8081` |
| **`.whl`** (PyPI) | `pip`, `uv` | `https://nexus.internal.gdc.local/repository/pypi-group/simple/` | `127.0.0.1:8081` |
| **Admin Web UI** | Web Browser | `https://nexus.internal.gdc.local/` | `127.0.0.1:8081` |

---

## 6. Host Certificate Minting & Autonomous Rotation

### 6.1. Host Leaf Minting Script (`/usr/local/bin/refresh-nexus-tls.sh`)
```bash
#!/usr/bin/env bash
set -euo pipefail

CERT_PATH="/etc/ssl/certs/nexus.bundle.crt"
KEY_PATH="/etc/ssl/private/nexus.key"
SUB_CA_CERT="/etc/ssl/sub-ca/sub-ca.crt"
SUB_CA_KEY="/etc/ssl/sub-ca/sub-ca.key"

# Threshold: 30 days in seconds (30 * 86400 = 2592000)
RENEW_THRESHOLD_SECONDS=2592000

needs_renewal=false

if [[ ! -f "${CERT_PATH}" ]] || [[ ! -f "${KEY_PATH}" ]]; then
    echo "[*] Nexus TLS certificates not found. Minting initial certificate..."
    needs_renewal=true
elif ! openssl x509 -checkend "${RENEW_THRESHOLD_SECONDS}" -noout -in "${CERT_PATH}" &>/dev/null; then
    echo "[*] Nexus TLS certificate is expiring within 30 days. Initiating renewal..."
    needs_renewal=true
else
    echo "[+] Nexus TLS certificate is valid for at least 30 days. No action required."
    exit 0
fi

if [[ "${needs_renewal}" == "true" ]]; then
    if [[ ! -f "${SUB_CA_CERT}" ]] || [[ ! -f "${SUB_CA_KEY}" ]]; then
        echo "[!] Error: Sub-CA credentials missing at ${SUB_CA_CERT} or ${SUB_CA_KEY}." >&2
        exit 1
    fi

    # Mint leaf certificate with complete chain bundle
    step certificate create nexus.internal.gdc.local \
        "${CERT_PATH}" \
        "${KEY_PATH}" \
        --ca="${SUB_CA_CERT}" \
        --ca-key="${SUB_CA_KEY}" \
        --san="nexus.internal.gdc.local" \
        --san="nexus.gdc.local" \
        --bundle \
        --not-after=8760h \
        --no-password --insecure --force

    chmod 0644 "${CERT_PATH}"
    chmod 0600 "${KEY_PATH}"
    chown root:root "${CERT_PATH}" "${KEY_PATH}"

    # Validate syntax before reloading Nginx
    if nginx -t &>/dev/null; then
        systemctl reload nginx
        echo "[+] Successfully minted Nexus TLS certificate and reloaded Nginx."
    else
        echo "[!] Nginx configuration test failed after certificate renewal!" >&2
        exit 1
    fi
fi
```

### 6.2. Systemd Service & Timer Definitions

#### Service: `/etc/systemd/system/refresh-nexus-tls.service`
```ini
[Unit]
Description=Autonomous Nexus TLS Certificate Renewal
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/refresh-nexus-tls.sh
User=root
Group=root
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/etc/ssl/certs /etc/ssl/private
ReadOnlyPaths=/etc/ssl/sub-ca
```

#### Timer: `/etc/systemd/system/refresh-nexus-tls.timer`
```ini
[Unit]
Description=Weekly Check for Nexus TLS Certificate Expiration
After=time-sync.target

[Timer]
OnCalendar=Sun *-*-* 03:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
```

---

## 7. In-Cluster Kubernetes Integration (`cert-manager`)

### 7.1. Secret Injection (`stage_post_cluster`)
During post-cluster configuration (`src/ansible/roles/post_cluster/tasks/main.yml`):
```yaml
- name: "GDC-K8S-PKI | Ensure cert-manager namespace exists"
  kubernetes.core.k8s:
    api_version: v1
    kind: Namespace
    name: cert-manager
    state: present

- name: "GDC-K8S-PKI | Seed Sub-CA TLS secret into cert-manager"
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Secret
      metadata:
        name: gdc-sub-ca-keypair
        namespace: cert-manager
      type: kubernetes.io/tls
      data:
        tls.crt: "{{ (lookup('file', '/etc/ssl/sub-ca/sub-ca.crt') + '\n' + lookup('file', '/usr/local/share/ca-certificates/gdc-enterprise-root.crt')) | b64encode }}"
        tls.key: "{{ lookup('file', '/etc/ssl/sub-ca/sub-ca.key') | b64encode }}"
```

### 7.2. `cert-manager` ClusterIssuer
```yaml
- name: "GDC-K8S-PKI | Deploy gdc-ca-issuer ClusterIssuer"
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: cert-manager.io/v1
      kind: ClusterIssuer
      metadata:
        name: gdc-ca-issuer
      spec:
        ca:
          secretName: gdc-sub-ca-keypair
```

### 7.3. Microservice / Ingress Certificate Consumption
Any Kubernetes service requiring TLS (e.g. Ingress, Git gateway, monitoring) specifies:
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: gitea-tls-cert
  namespace: gdc-platform
spec:
  secretName: gitea-tls-secret
  duration: 2160h # 90 days
  renewBefore: 720h # 30 days
  issuerRef:
    name: gdc-ca-issuer
    kind: ClusterIssuer
  commonName: git.internal.gdc.local
  dnsNames:
    - git.internal.gdc.local
    - git.gdc.local
```

---

## 8. Threat Modeling & Security Hardening Mitigations

| Threat | Impact | Implemented Mitigation |
| :--- | :--- | :--- |
| **Node Compromise & Sub-CA Theft** | Attacker uses Sub-CA to mint rogue certificates for corporate domains. | **RFC 5280 Name Constraints:** Sub-CA is constrained strictly to `.internal.gdc.local` and `.gdc.local`. All other domains hard-fail TLS validation. |
| **Nexus JVM Compromise / RCE** | Attacker leverages unprivileged RCE to read `/etc/ssl/sub-ca/sub-ca.key`. | **Isolate Nexus from Root (Issue #23):** Run Nexus as unprivileged `nexus:nexus`; Sub-CA key is `0400 root:root`, unreachable by JVM UID. |
| **Large Blob DoS on Nginx** | Attacker streams multi-GB files to management APIs. | **Path-segmented `client_max_body_size`:** 50G for `/v2/` and `/repository/`; 10M for Web UI and REST API. |
| **Physical Hard Drive Theft** | Exfiltration of Sub-CA and leaf private keys from offline disks. | **Hardware TPM 2.0 LUKS Sealing:** Storage volumes are encrypted at rest with PBKDF2/LUKS sealed to motherboard PCRs `0+7`. |
| **In-Cluster Secret Dumping** | Malicious pod dumps Sub-CA from `cert-manager` namespace. | **Strict Namespace RBAC & etcd Encryption:** Restrict secret read access; enforce KMS secrets encryption in Anthos Bare Metal control plane. |

---

## 9. Verification & Acceptance Criteria

1. **Host TLS Handshake:**
   * `curl -v https://nexus.internal.gdc.local/` succeeds with HTTP 200 without `-k` (insecure) flag.
2. **Container Registry Pull:**
   * `crictl pull nexus.internal.gdc.local/gke-release/coredns:v1.10.1` succeeds via standard HTTPS port 443.
3. **APT Package Indexing:**
   * `apt-get update` against `https://nexus.internal.gdc.local/repository/gdc-apt-hosted/` succeeds with verified TLS trust.
4. **Autonomous Rotation Test:**
   * Running `/usr/local/bin/refresh-nexus-tls.sh` verifies certificates and tests Nginx reload idempotently.
5. **In-Cluster Issuance:**
   * `cert-manager` successfully issues a valid `Certificate` signed by `gdc-ca-issuer`.
