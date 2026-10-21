# Enterprise Sub-CA Secret Setup for Google Secret Manager & GDC Companion

This guide explains how to generate, package, and upload an **Enterprise Intermediate Sub-CA** into **Google Cloud Secret Manager (GSM)**, and how to register the secret in the **GDC Companion** machine configuration (`machine-schema.json`).

---

## 1. Overview & Architecture

To enable autonomous TLS termination for Nexus (`nexus.internal.gdc.local`) and in-cluster Kubernetes microservices without managing external CA daemons, each GDC bare-metal appliance ingests a delegated Sub-CA keypair.

```text
  [ Enterprise Root CA ] (Corporate PKI / HSM)
            │
            ▼ (Issues once with Name Constraints)
  [ Sub-CA Keypair ] (sub-ca.crt + sub-ca.key + root.crt)
            │
            ▼ (Packaged into JSON)
  [ Google Cloud Secret Manager ] (e.g. secret: "gdc-pki-sub-ca")
            ▲
            │ (Referenced by name & location)
  [ GDC Companion ] machine-config (.cluster.sub_ca_secret)
            │
            ▼ (mTLS fetch on first boot)
  [ GDC Bare-Metal Node ] (/etc/ssl/sub-ca/ & cert-manager ClusterIssuer)
```

---

## 2. Required Input Files

Before creating the GSM secret, obtain or generate the following three PEM-encoded files:

| File Name | Description | Key Properties & Constraints |
| :--- | :--- | :--- |
| **`root.crt`** | Corporate Root CA public certificate | Installed into `/usr/local/share/ca-certificates/` to establish system-wide trust across OS tools (`curl`, `apt`, `containerd`, Python). |
| **`sub-ca.crt`** | Intermediate Sub-CA certificate signed by `root.crt` | **MANDATORY SECURITY CONSTRAINTS:**<br>• `basicConstraints = critical, CA:TRUE, pathlen:0`<br>• `nameConstraints = critical, Permitted;DNS:.internal.gdc.local, Permitted;DNS:.gdc.local`<br>• `keyUsage = critical, digitalSignature, keyCertSign, cRLSign` |
| **`sub-ca.key`** | Private key corresponding to `sub-ca.crt` | Traditional RSA (2048/4096-bit) or ECDSA (P-256/P-384) unencrypted PEM private key (`-----BEGIN PRIVATE KEY-----` or `-----BEGIN EC/RSA PRIVATE KEY-----`). |

---

## 3. How to Generate Test Sub-CA Files (Lab / Staging)

If you are generating test credentials in a lab environment:

### Option A: Using `step-cli` (Recommended)
```bash
# 1. Create a lab Root CA (valid for 10 years)
step certificate create "Enterprise Root CA" root.crt root.key \
    --profile root-ca \
    --no-password --insecure

# 2. Create the Intermediate Sub-CA with Name Constraints (valid for 3 years)
step certificate create "GDC Edge Sub-CA" sub-ca.crt sub-ca.key \
    --profile intermediate-ca \
    --ca root.crt \
    --ca-key root.key \
    --not-after 26280h \
    --no-password --insecure
```

### Option B: Using OpenSSL with Strict RFC 5280 Name Constraints
Create `sub-ca.cnf`:
```ini
[ req ]
distinguished_name = req_distinguished_name
prompt = no

[ req_distinguished_name ]
CN = GDC Edge Intermediate Sub-CA
O = Enterprise
OU = Edge Infrastructure

[ sub_ca_ext ]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, digitalSignature, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
nameConstraints = critical, @name_constraints

[ name_constraints ]
permitted;DNS.1 = .internal.gdc.local
permitted;DNS.2 = .gdc.local
```

Generate the key and certificate:
```bash
# Generate private key
openssl ecparam -name prime256v1 -genkey -noout -out sub-ca.key

# Generate CSR
openssl req -new -key sub-ca.key -out sub-ca.csr -config sub-ca.cnf

# Sign with Root CA
openssl x509 -req -in sub-ca.csr -CA root.crt -CAkey root.key \
    -CAcreateserial -out sub-ca.crt -days 1095 \
    -extfile sub-ca.cnf -extensions sub_ca_ext
```

---

## 4. Packing Files into JSON Structure

The GDC Ansible provisioner expects a **single JSON payload** with the exact keys:
* `"ca.crt"`
* `"ca.key"`
* `"root.crt"`

### Target JSON Structure (`sub-ca-payload.json`)
```json
{
  "ca.crt": "-----BEGIN CERTIFICATE-----\nMIIB...<Sub-CA Certificate PEM>...\n-----END CERTIFICATE-----\n",
  "ca.key": "-----BEGIN PRIVATE KEY-----\nMIGH...<Sub-CA Private Key PEM>...\n-----END PRIVATE KEY-----\n",
  "root.crt": "-----BEGIN CERTIFICATE-----\nMIIB...<Corporate Root CA PEM>...\n-----END CERTIFICATE-----\n"
}
```

> ⚠️ **CRITICAL FORMATTING RULE:** Newlines inside PEM certificates MUST be serialized as literal `\n` characters in JSON strings. Do not attempt to hand-craft JSON with raw linebreaks.

### Method 1: Automated Packaging with `jq` (Linux / macOS)
```bash
jq -n \
  --rawfile ca_crt sub-ca.crt \
  --rawfile ca_key sub-ca.key \
  --rawfile root_crt root.crt \
  '{ "ca.crt": $ca_crt, "ca.key": $ca_key, "root.crt": $root_crt }' > sub-ca-payload.json
```

### Method 2: Automated Packaging with Python
```bash
python3 -c '
import json

payload = {
    "ca.crt": open("sub-ca.crt", "r").read(),
    "ca.key": open("sub-ca.key", "r").read(),
    "root.crt": open("root.crt", "r").read(),
}

with open("sub-ca-payload.json", "w") as f:
    json.dump(payload, f, indent=2)
'
```

### Validate the JSON Payload
```bash
# Verify all required keys are present and non-empty
jq -e 'has("ca.crt") and has("ca.key") and has("root.crt")' sub-ca-payload.json
```

---

## 5. Creating the Secret in Google Cloud Secret Manager (GSM)

### Step 5.1: Set Environment Variables
```bash
export GCP_PROJECT_ID="your-gcp-project-id"
export GSM_SECRET_NAME="gdc-pki-sub-ca"
export GSM_LOCATION="global"  # Or regional: "us-central1", "us-west1"
```

### Step 5.2: Create the Secret Resource
For **global** replication (standard):
```bash
gcloud secrets create "${GSM_SECRET_NAME}" \
    --project="${GCP_PROJECT_ID}" \
    --replication-policy="automatic" \
    --labels="managed-by=gdc-companion,purpose=edge-pki"
```

For **user-managed regional** replication:
```bash
gcloud secrets create "${GSM_SECRET_NAME}" \
    --project="${GCP_PROJECT_ID}" \
    --replication-policy="user-managed" \
    --locations="${GSM_LOCATION}" \
    --labels="managed-by=gdc-companion,purpose=edge-pki"
```

### Step 5.3: Upload the JSON Payload
```bash
gcloud secrets versions add "${GSM_SECRET_NAME}" \
    --project="${GCP_PROJECT_ID}" \
    --data-file="sub-ca-payload.json"
```

### Step 5.4: Grant Access to the Edge Node Service Account
The primary Google Service Account (GSA) used by the edge node must hold the Secret Accessor role:
```bash
export EDGE_NODE_GSA="gdc-node-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

gcloud secrets add-iam-policy-binding "${GSM_SECRET_NAME}" \
    --project="${GCP_PROJECT_ID}" \
    --member="serviceAccount:${EDGE_NODE_GSA}" \
    --role="roles/secretmanager.secretAccessor"
```

---

## 6. Configuring GDC Companion (`machine-config`)

In **GDC Companion**, register the secret name and location under the `.cluster.sub_ca_secret` object in the machine configuration.

### JSON Payload (`GET /v1/machine-info/{mac}` or `gdc-fact-manual.json`)
```json
{
  "hostname": "gdc-edge-node-01",
  "cluster": {
    "cluster_name": "gdc-edge-cluster-01",
    "sub_ca_secret": {
      "gsm-name": "gdc-pki-sub-ca",
      "gsm-location": "global"
    }
  }
}
```

### Schema Parameters (`machine-schema.json`)
| JSON Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `cluster.sub_ca_secret` | `object` | *Optional* | Activates Enterprise Sub-CA ingestion for Nexus TLS and cert-manager. |
| `cluster.sub_ca_secret.gsm-name` | `string` | *Required* | Exact name of the secret in Google Cloud Secret Manager (e.g. `gdc-pki-sub-ca`). |
| `cluster.sub_ca_secret.gsm-location` | `string` | `"global"` | Replication region (`global`, `us-central1`, `europe-west1`). If regional retrieval fails, Ansible automatically falls back to global. |

---

## 7. Verification Runbook

### 1. Test Secret Retrieval Locally
Verify that `gcloud` can read the secret payload:
```bash
gcloud secrets versions access latest \
    --secret="gdc-pki-sub-ca" \
    --project="${GCP_PROJECT_ID}" | jq -r 'keys[]'
```
*Expected output:*
```text
ca.crt
ca.key
root.crt
```

### 2. Verify Node Ingestion Output
On the bare-metal appliance after first boot completes:
```bash
# 1. Confirm corporate root certificate is in system trust store
ls -la /usr/local/share/ca-certificates/gdc-enterprise-root.crt

# 2. Confirm Sub-CA credentials exist with strict root-only permissions
ls -la /etc/ssl/sub-ca/
# -rw-r--r-- 1 root root sub-ca.crt
# -r-------- 1 root root sub-ca.key

# 3. Test TLS connection to local Nexus
curl -Iv https://nexus.internal.gdc.local/
# Expected: HTTP 200 OK without certificate validation warnings
```

---

## 8. Fallback Self-Signed Sub-CA & Regional GSM Architecture

When operating without an enterprise PKI or Google Cloud Certificate Authority Service (CAS), GDC nodes can automatically fall back to a self-signed Root/Sub-CA authority stored in Google Secret Manager or baked into the ISO.

### Configuration Variables (`src/build/build.env` & ISO Profiles)
| Variable | Default | Description |
| :--- | :--- | :--- |
| `FALLBACK_SUB_CA_SECRET_NAME` | `gdc-fallback-sub-ca` | Secret name in GSM. Hydrates to `gdc_fallback_sub_ca_gsm_name`. |
| `FALLBACK_SUB_CA_GSM_LOCATION` | `us-east4` | Regional location for Secret Manager replication when storing the secret. Hydrates to `gdc_fallback_sub_ca_gsm_location`. |
| `FALLBACK_SUB_CA_GSM_PROJECT` | Active `PROJECT_ID` | GCP Project ID where the fallback secret is hosted. Hydrates to `gdc_fallback_sub_ca_gsm_project`. |

### Creating and Staging Regional Fallback Sub-CA
Use the unified node operations CLI:
```bash
./bin/local/gdc-node-ops.sh create-fallback-ca \
  --project="anthos-bare-metal-lab-1" \
  --location="us-east4" \
  --secret="gdc-fallback-sub-ca" \
  --output=".cache/pki/fallback-sub-ca.json"
```

### Ingestion Retrieval Command
During node bootstrap (`pki_ingest.yml`) or ISO remastering, the node accesses the latest version without `--location`:
```bash
gcloud secrets versions access latest \
  --secret={{ gdc_fallback_sub_ca_gsm_name }} \
  --project={{ gdc_fallback_sub_ca_gsm_project }}
```
*Note: The secret is stored with `--replication-policy="user-managed" --locations="..."`, making it a global secret resource in Secret Manager with regional data placement. The location flag is only needed when creating/storing the secret; `--location` is NOT needed when pulling the latest version (and will trigger an `INVALID_ARGUMENT` error).*
