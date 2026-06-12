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
