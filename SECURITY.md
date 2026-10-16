# Security Policy (SECURITY.md)

## System Overview: Security for GDC Disk Provisioner
*   **Goal:** To ensure that the disk provisioner, its helper daemons, controllers, and configurations do not introduce vulnerabilities and to provide a secure channel for reporting any discovered issues.
*   **Scope:** This policy covers the source code in `src/`, manifests, tests, and the security posture of the bundled components.
*   **Tech Stack:** Kubernetes CSI / Storage APIs, Linux block devices, privileged containers, and container security.

---

## Infrastructure & Resource Requirements
*   **Contact Point:** mike@ensor.cc
*   **Encryption:** [Link to Public PGP Key] (Optional but highly recommended for sensitive reports).
*   **Visibility:** This file must remain in the root of the repository to be automatically detected by GitHub/GitLab security features.

---

## Supported Versions

| Version | Supported | Compatibility |
| :--- | :---: | :--- |
| v1.0.x | ✅ | Active |
| < v1.0.0 | ❌ | End of Life |

---

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

If you discover a security issue in this project (e.g., an privilege escalation, insecure mount option, host path traversal, or a misconfigured security context), please follow these steps:

1.  **Email:** Send a detailed report to the contact point listed above.
2.  **Content:** Include the affected version, a description of the vulnerability, and steps to reproduce.
3.  **Triage:** Our team will acknowledge your report within 48 hours and provide an estimated timeline for a fix.

---

## Security Principles

As a storage provisioning component, this project adheres to the following security standards:

*   **Least Privilege:** Host access and capabilities are limited to the minimum set required for local storage provisioning and attachment.
*   **Input Validation:** Device paths, volume IDs, and request parameters are rigorously validated to prevent command injection and directory traversal attacks.
*   **Image Integrity:** All deployment manifests and container references must use immutable image tags (SHAs) or verified registries in production.
*   **No Secrets in Git:** This repository never stores actual secrets (passwords, keys, credentials).

---

## Public Key Infrastructure (PKI) & Certificate Security Policy

The GDC Disk Provisioner and appliance installer utilize a **Dual-Mode PKI architecture** to support both production enterprise deployments and demonstration/lab environments.

### 1. Enterprise Mode (Production Requirements)
* **Delegated Sub-CA Ingestion:** Production appliances strictly require an enterprise-delegated Intermediate Sub-CA configured in GDC Companion via `cluster.sub_ca_secret`.
* **Zero Trust Secret Delivery:** Sub-CA credentials are retrieved from Google Cloud Secret Manager (GSM) via hardware-attested mutual TLS (mTLS) token federation.
* **TPM Sealing & Encryption at Rest:** Ingested Sub-CA private keys are stored in root-only protected paths (`/etc/ssl/sub-ca/sub-ca.key`, mode `0400`) within LUKS-encrypted partitions sealed to the motherboard TPM 2.0.
* **Autonomous In-Cluster Handover:** During Stage 7 (`POST_CLUSTER`), Sub-CA credentials are automatically handed over to Kubernetes `cert-manager` (`gdc-ca-issuer`) to manage in-cluster service certificates.

### 2. Demo Mode (Non-Production Lab Environment Policy)
* **Purpose:** If `cluster.sub_ca_secret` is omitted or empty in GDC Companion (e.g., Sub-CA checkbox disabled), the appliance operates in **Demo Mode** using a pre-baked public wildcard certificate (`*.demo.gdc-labs.com`).
* **Security & Non-Production Notice:** 
  > **WARNING: Demo mode is strictly intended for demonstrations, sandbox evaluations, and lab turnups. Security is NOT guaranteed for production workloads when operating in Demo Mode.**
* **Scope & Blast Radius:** Demo certificates are strictly scoped to `*.demo.gdc-labs.com` and isolated to the local Layer 2 cluster network (VLAN 109) via split-horizon DNS (`dnsmasq`). They cannot assert identity for production systems, customer domains, or Google Cloud services.
* **No Private Keys in Git:** Private keys for the public demo certificate are fetched at ISO build time from Google Cloud Secret Manager (`gdc-labs-wildcard-pki`) and injected into the ISO's `custom-data` partition. They MUST NEVER be committed to the git repository.
* **Audit Trail:** When operating in Demo Mode, the appliance records `PASS_DEMO_MODE` and an explicit security warning in the machine evidence state (`/var/gdc-install/state/cluster-ready.json`), preventing silent adoption in production environments.
