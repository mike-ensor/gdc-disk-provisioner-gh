# GDC Provisioner Specification: Dual-Mode Nexus PKI & Public Demo Certificates

**Document Identifier:** `GDC-SPEC-019`  
**Document Version:** 1.0.0  
**Status:** PROPOSED  
**Target Components:** ISO Remaster Pipeline, Ansible Machine Orchestration, Local DNS, Service Hubs, Security Audit  
**Coordinated Features:** `docs/superpowers/specs/2026-10-13-nexus-tls-pki-design.md`, `machine-schema.json`  

---

## 1. Executive Summary & Purpose

This specification defines the architectural and operational design for the **Dual-Mode Public Key Infrastructure (PKI)** within the Google Distributed Cloud (GDC) bare-metal disk provisioner and appliance installer.

To enable secure, turnkey turnup across both enterprise production environments and offline lab/demo environments, the provisioner supports two mutually exclusive certificate operating modes:

1. **Enterprise Mode (Customer Delegated Sub-CA):**  
   Active when the GDC Companion machine configuration provides `cluster.sub_ca_secret` (for cluster-assigned machines) or top-level `sub_ca_secret` (for unassigned warm-spare machines stopping at `CLUSTER_READY`). The appliance retrieves an Intermediate Sub-CA keypair from Google Cloud Secret Manager (GSM) over hardware-attested mTLS, mints local host certificates for `nexus.internal.gdc.local`, and hands over the Sub-CA keypair to in-cluster `cert-manager`.
2. **Demo Mode (Pre-Baked 10-Year Demo Sub-CA):**  
   Active when both `cluster.sub_ca_secret` and top-level `sub_ca_secret` are omitted or empty (e.g. checkbox disabled in GDC Companion). The appliance activates a pre-baked, 10-year dedicated Demo Sub-CA embedded directly into the ISO image (`/custom-data/demo-certs/sub-ca.json`). The appliance writes the Demo Root CA into the system trust store, uses `step-cli` to mint local certificates valid for both `nexus.demo.gdc-labs.com` and `nexus.internal.gdc.local`, and seamlessly hands over the Sub-CA to `cert-manager`. This guarantees that offline demo ISOs can sit in storage or demo kits for years without encountering a 90-day certificate expiration brick.

---

## 2. Background & Problem Statement

### 2.1 The Container Trust Boundary
Modern container runtimes (`containerd`, `crictl`, Docker) and Kubernetes cluster bootstrap tools (`bmctl`) enforce strict Transport Layer Security (TLS):
* **Strict HTTPS on Port 443:** When querying an OCI registry without an explicit port, container engines mandate HTTPS on port 443. Plain HTTP on port 80 or 8081 is rejected with `server gave HTTP response to HTTPS client` unless the domain is pre-configured as an insecure registry.
* **Isolated Container Namespaces:** During cluster turnup, `bmctl` executes inside an ephemeral Kind bootstrap container (`bmctl-control-plane`). This container has its own mount and network namespaces and does not inherit the host's `/usr/local/share/ca-certificates/` system trust store.
* **The Self-Signed CA Dilemma:** If a demo appliance generates an ad-hoc self-signed CA locally, the host can trust it via `update-ca-certificates`, but the Kind bootstrap container and target Kubernetes pods fail image pulls with `x509: certificate signed by unknown authority`. Injecting CA mounts into `bmctl`'s dynamic container lifecycle adds fragile workarounds.

### 2.2 The Public Domain Constraint (RFC 6761)
Public Certificate Authorities (Let's Encrypt, Google Trust Services) are prohibited by CA/Browser Forum baseline requirements from issuing certificates for reserved local TLDs (`.local`, `.internal`) or private RFC 1918 IP addresses.

To utilize public certificates that are trusted out-of-the-box by all operating systems and base container images, the demo domain must be an officially owned public domain: **`*.demo.gdc-labs.com`**.

---

## 3. Dual-Mode Architecture & Behavior Matrix

| Dimension | Enterprise Mode (Production) | Demo / Lab Mode (Pre-Baked 10-Year Sub-CA) |
| :--- | :--- | :--- |
| **Activation Condition** | `cluster.sub_ca_secret` or top-level `sub_ca_secret` defined in Companion | Both `cluster.sub_ca_secret` and `sub_ca_secret` are omitted / empty |
| **Domain Name** | `nexus.internal.gdc.local` (alias `nexus.gdc.local`) | `nexus.demo.gdc-labs.com` & `nexus.internal.gdc.local` |
| **Certificate Authority** | Enterprise Intermediate Sub-CA (from GSM) | Dedicated GDC Demo Intermediate Sub-CA (10-Year) |
| **Certificate Scope** | Host leaf minted via `step-cli` for internal domain | Host leaf minted via `step-cli` with multi-domain SANs |
| **Key Storage & Delivery** | Downloaded at runtime via mTLS token federation | Pre-baked into ISO `/custom-data/demo-certs/sub-ca.json` |
| **Local DNS Mapping** | `nexus.internal.gdc.local` $\rightarrow$ `gdc_service_hub_ip` | `*.demo.gdc-labs.com` & `internal.gdc.local` $\rightarrow$ `gdc_service_hub_ip` |
| **Reverse Proxy Binding** | `gdc_service_hub_ip:443` | `gdc_service_hub_ip:443` |
| **In-Cluster Handover** | Seeds `cert-manager` `ClusterIssuer` | Seeds `cert-manager` `ClusterIssuer` with Demo Sub-CA |
| **Offline Lifespan** | Configured per corporate policy | **10 Years** (prevents offline ISO expiration brick) |
| **Evidence Status** | `PASS` | `PASS_DEMO_MODE` (with non-production warning) |

---

## 4. End-to-End Workflow

### 4.1 Phase 1: Build & Remaster Pipeline (`remaster.sh`)

At ISO build time, `remaster.sh` prepares the fallback Sub-CA bundle for air-gapped offline use:

1. **Secret Retrieval:** The build script authenticates to Google Cloud and reads the fallback Sub-CA credentials from Google Cloud Secret Manager (`gdc-labs-wildcard-pki`) or local cache (`.cache/pki/fallback-sub-ca.json`):
   * `root.crt` (10-Year Demo Root CA)
   * `ca.crt` / `sub-ca.crt` (10-Year Intermediate Sub-CA)
   * `ca.key` / `sub-ca.key` (Sub-CA private key)
2. **ISO Partition Injection:**
   The JSON payload is placed onto the ISO filesystem at:
   `/custom-data/pki/fallback-sub-ca.json` (permissions: `0400`)
3. **Build Logging & Confirmation Banner:**
   `remaster.sh` prints a prominent confirmation banner:
   ```text
   ====================================================================
   [!] NOTICE: Packaging 10-Year Demo Sub-CA for offline lab use.
   [!] Root CA & Sub-CA valid through 2036.
   [!] This ISO fallback is intended for DEMO / LAB environments ONLY.
   ====================================================================
   ```

### 4.2 Phase 2: Host Provisioning & Decision Logic (Stage 4 / 5)

During First Boot and Stage 5 (`CLUSTER_READY`), Ansible evaluates whether Enterprise Sub-CA credentials were provided:

```text
                     ┌──────────────────────────────────┐
                     │ Check Companion Machine Config:  │
                     │  cluster.sub_ca_secret provided? │
                     └─────────────────┬────────────────┘
                                       │
                      ┌────────────────┴────────────────┐
                      ▼                                 ▼
                   [ YES ]                           [ NO ]
        ┌───────────────────────────┐     ┌───────────────────────────┐
        │      ENTERPRISE MODE      │     │    DEMO FALLBACK MODE     │
        ├───────────────────────────┤     ├───────────────────────────┤
        │ • Fetch Sub-CA from GSM   │     │ • Slurp fallback payload  │
        │ • Write Root CA to trust  │     │   from /var/gdc-install/  │
        │ • Write Sub-CA to         │     │   pki/fallback-sub-ca.json│
        │   /etc/ssl/sub-ca/        │     │ • Write Root CA & Sub-CA  │
        │ • Mint leaf via step-cli  │     │ • Purge /var/gdc-install/ │
        │ • Evidence: PASS          │     │   pki payload immediately │
        │                           │     │ • Mint leaf with demo SANs│
        │                           │     │ • Evidence: PASS_DEMO_MODE│
        └───────────────────────────┘     └───────────────────────────┘
```

#### Step 1: Sub-CA Ingestion & Ephemeral Purge
When `cluster_config.sub_ca_secret` is not provided:
1. `pki_ingest.yml` slurps `/var/gdc-install/pki/fallback-sub-ca.json`.
2. Writes the Root CA to `/usr/local/share/ca-certificates/gdc-enterprise-root.crt` (`0644 root:root`) and runs `update-ca-certificates`.
3. Writes the Sub-CA credentials to `/etc/ssl/sub-ca/sub-ca.crt` (`0644`) and `/etc/ssl/sub-ca/sub-ca.key` (`0400 root:root`).
4. **Immediately purges** `/var/gdc-install/pki` (`state: absent`) so plaintext secret files never linger on disk.
5. Marks `is_demo_fallback_pki: true`.

#### Step 2: Multi-Domain Leaf Minting
`refresh-nexus-tls.sh` mints the leaf certificate using `step-cli` covering:
* `nexus.internal.gdc.local`
* `nexus.gdc.local`
* `nexus.demo.gdc-labs.com`

#### Step 3: Local Split-Horizon DNS Configuration
`src/ansible/roles/local_dns/templates/internal-gdc.conf.j2` includes authoritative local routes for both domains:
```dnsmasq
# Authoritative local boundary
local=/{{ gdc_nexus_domain }}/
local=/demo.gdc-labs.com/
local=/internal.gdc.local/

# Service Hub resolution to isolated cluster VLAN IP
address=/{{ gdc_nexus_domain }}/{{ gdc_service_hub_ip }}
address=/nexus.demo.gdc-labs.com/{{ gdc_service_hub_ip }}
address=/nexus.internal.gdc.local/{{ gdc_service_hub_ip }}
```

#### Step 4: Reverse Proxy Nginx Configuration
The Nginx site template (`nexus-tls.conf.j2`) binds to `gdc_service_hub_ip:443` and handles requests with SNI matching the active domain:
* `/v2/` $\rightarrow$ `http://127.0.0.1:5001` (Docker/OCI registry)
* `/repository/` $\rightarrow$ `http://127.0.0.1:8081` (APT repositories & raw assets)
* `/` $\rightarrow$ `http://127.0.0.1:8081` (Web UI & REST API)

#### Step 5: Post-Cluster Turnup Handover
* **Enterprise Mode:** Executes `cert_manager_pki.yml` to seed `gdc-sub-ca-keypair` into the `cert-manager` Kubernetes namespace and deploys `ClusterIssuer` `gdc-ca-issuer`.
* **Demo Mode:** Skips `cert_manager_pki.yml`. Because the certificate was signed by a public CA, any standard pod image pulling from `nexus.demo.gdc-labs.com:443` verifies the signature using its existing container CA bundle.

---

## 5. Security & Threat Model

### 5.1 Blast Radius & Scope of Compromise
* **Domain Isolation:** The certificate covers strictly `*.demo.gdc-labs.com` and `demo.gdc-labs.com`. It cannot validate or decrypt traffic for Google Cloud APIs, customer domain names, or internal production clusters (`*.internal.gdc.local`).
* **Traffic Demarcation:** The appliance network configuration confines `gdc_service_hub_ip` to the isolated Layer 2 cluster network (VLAN 109). Traffic cannot be intercepted from external networks.
* **Separation from Production:** Production environments strictly require `cluster.sub_ca_secret`. Demo certificates must never be deployed on appliances handling customer production workloads.

### 5.2 Private Key Management
* **Zero Keys in Source Code:** Private keys (`demo.key`) MUST NEVER be committed to git. Automated CA scanners (e.g. Let's Encrypt / GitHub secret scanning) immediately revoke public certificates whose private keys are pushed to source control.
* **Build-Time Ingestion:** The private key is fetched exclusively during Phase 1 remastering from Google Cloud Secret Manager (`gdc-demo-wildcard-pki`) using build credentials.
* **Filesystem Protection:** On the running appliance, the demo private key is owned by `root:root` with mode `0400` inside the LUKS hardware-encrypted partition.

### 5.3 Expiration & Renewal Lifecycle
* **Public CA 90-Day Lifespan:** Public certificates issued by ACME / Let's Encrypt are valid for 90 days.
* **Scheduled Pipeline Renewal:** A recurring Cloud Build or GitHub Actions workflow uses Certbot with Cloud DNS (`dns-01`) validation to renew `*.demo.gdc-labs.com` every 30 days and store the updated bundle in Secret Manager.
* **Build Warning:** If an ISO build occurs when the certificate has less than 15 days of validity remaining, the build pipeline warns the operator to trigger renewal before flashing appliances.

---

## 6. Audit & Evidence Reporting

The Stage 5 evidence payload written to `/var/gdc-install/state/cluster-ready.json` captures the exact operational mode:

### 6.1 Enterprise Mode Evidence
```json
{
  "nexus_tls": {
    "status": "PASS",
    "mode": "ENTERPRISE",
    "domain": "nexus.internal.gdc.local",
    "cert_path": "/etc/ssl/certs/nexus.bundle.crt",
    "gsm_secret_name": "gdc-pki-sub-ca",
    "gsm_secret_location": "global"
  }
}
```

### 6.2 Demo Mode Evidence
```json
{
  "nexus_tls": {
    "status": "PASS_DEMO_MODE",
    "mode": "DEMO",
    "domain": "nexus.demo.gdc-labs.com",
    "cert_path": "/etc/ssl/certs/nexus-demo.bundle.crt",
    "warning": "Appliance running in non-production demo mode using public wildcard certificate for *.demo.gdc-labs.com. Not for production use."
  }
}
```

---

## 7. Implementation Checklist

- [ ] Register Google Cloud Secret Manager secret `gdc-demo-wildcard-pki` with `demo.crt` and `demo.key`.
- [ ] Add `remaster.sh` step to fetch demo certificates into `${EXTRACT_DIR}/custom-data/demo-certs/`.
- [ ] Update `src/ansible/roles/machine_orchestration/tasks/pki_ingest.yml` to switch between Enterprise Sub-CA and Demo certificate loading.
- [ ] Update `src/ansible/roles/local_dns/templates/internal-gdc.conf.j2` with `nexus.demo.gdc-labs.com` routing.
- [ ] Update `src/ansible/roles/service_hubs/templates/nexus-tls.conf.j2` with dynamic domain and certificate path variables.
- [ ] Update `SECURITY.md` and `docs/NETWORK.md` to document the dual-mode certificate architecture.
