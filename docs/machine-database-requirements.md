# Specification: GDC Machine Database & Cloud Verification Requirements

**Spec Identifier:** `GDC-SPEC-005`  
**Status:** DRAFT  
**Author:** GDC Disk Provisioner Security Architecture Team  

---

## 1. Overview & Purpose
This document specifies the technical and cryptographic requirements for the **GCP Cloud Enrollment App** and its supporting **Machine Database**. To validate that a bare-metal node's enrollment request originates from a genuine hardware server flashed with our exact "blessed" GDC bootstrap ISO, the Cloud App must cross-reference the node's live TPM measurements against a known-good reference baseline.

This prevents rogue nodes, software-emulated VMs, or compromised OS bootloads from obtaining cluster identity credentials.

*(For the complete architectural walkthrough, sequence diagram, and mTLS integration covering EKCert attestation and Step CA certificate issuance, see [`docs/TPM_ATTESTATION_AND_MTLS.md`](TPM_ATTESTATION_AND_MTLS.md).)*

---

## 2. The Machine Database (Reference Store Schema)
The Machine Database acts as the single source of truth for "golden" baselines and hardware inventory. It must maintain the following relational entities:

### 2.1. TPM Manufacturer Root Store
To validate that client Endorsement Key (EK) certificates are genuine, the database must store the Public CA Certificate Chains for all GDC-certified TPM 2.0 manufacturers:
*   **Infineon CA Store:** Root and Intermediate certificates.
*   **STMicroelectronics CA Store:** Root and Intermediate certificates.
*   **Intel fTPM CA Store:** Platform Root CA certificates.
*   **Nuvoton CA Store:** Root and Intermediate certificates.

### 2.2. Golden PCR Platform Profiles
The database must store the expected cryptographic hash measurements (baselines) of our booted systems. These are registered at build time during the ISO compilation:

| Register | Measured Component | Expected Value (SHA-256) | Security Metric Verified |
| :--- | :--- | :--- | :--- |
| **`PCR 0`** | Core System BIOS/Firmware | *Hardware Model Specific* | BIOS integrity & motherboard validation |
| **`PCR 2`** | Option ROMs / PCI Device Config | *Hardware Model Specific* | PCI/firmware card hardware integrity |
| **`PCR 4`** | System Kernel (`vmlinuz`) | `e3b0c44298fc1c149afb...` | Unaltered baseline OS kernel bootload |
| **`PCR 7`** | Secure Boot state (DB/DBX keys) | `98fc1c149afbf4c8996f...` | Secure Boot enabled with official signatures |
| **`PCR 9`** | Custom ISO configurations | `27ae41e4649b934ca495...` | Unaltered `user-data` and bootstrap configurations |

### 2.3. Pre-registered Node Inventory (High Security Layer)
Prior to shipment, the MAC address, Motherboard Serial, and expected **EK Public Key Fingerprint** are imported into the inventory tracking database:
```sql
CREATE TABLE node_inventory (
    id VARCHAR(64) PRIMARY KEY,
    chassis_serial VARCHAR(128) UNIQUE NOT NULL,
    expected_tpm_ek_pub_hash CHAR(64) UNIQUE NOT NULL, -- SHA-256 fingerprint of genuine TPM EK
    assigned_cluster_id VARCHAR(64),
    status VARCHAR(32) DEFAULT 'PENDING_BOOTSTRAP'
);
```

---

## 3. Cloud App Verification Engine Logic
Upon receiving an enrollment payload containing `EK_Cert`, `AK_Public_Key`, `PCR_Quote`, `Quote_Signature`, and `LID_CSR`, the Cloud App's verification engine must execute the following mathematical checks in sequence. Any failure must abort enrollment immediately.

```text
               NODE ENROLLMENT PAYLOAD
                          │
                          ▼
            [ Check 1: Vendor Authenticity ]
            Verify EK_Cert signature against Manufacturer CA Store
                          │
                          ▼
            [ Check 2: Key Binding Proof ]
            Verify Quote_Signature matches submitted AK_Public_Key
                          │
                          ▼
            [ Check 3: Anti-Replay Defense ]
            Verify Nonce inside Quote matches active GCP transaction
                          │
                          ▼
            [ Check 4: Software Integrity Check ]
            Compare Quote PCRs (0,2,4,7,9) against Golden Profiles
                          │
                          ▼
            [ Check 5: Cryptographic Enrollment ]
            Sign LID_CSR to issue GDC Device Identity TLS Certificate
```

### 3.1. Verification Algorithmic Steps

#### Step 1: Vendor TPM Authenticity Verification
The engine parses the DER-encoded `EK_Cert` and verifies its signature chain:
$$\text{Verify}(\text{EK\_Cert}, \text{Manufacturer\_Root\_CA}) == \text{True}$$
* **Purpose:** Proves the request originates from a real, physical, hardware-certified cryptographic chip, completely blocking virtual machine software-emulation spoofing.

#### Step 2: Quote Signature Verification
The engine validates that the cryptographic quote was signed by the node's unique Attestation Key (AK):
$$\text{VerifySignature}(\text{PCR\_Quote}, \text{Quote\_Signature}, \text{AK\_Public\_Key}) == \text{True}$$
* **Purpose:** Confirms that the submitted PCR measurements are fresh, active, and mathematically bound to the verified TPM.

#### Step 3: Anti-Replay Challenge Validation
The engine parses the extra data fields within the `PCR_Quote` and extracts the cryptographic **nonce**:
$$\text{Nonce}_{\text{Quote}} == \text{Nonce}_{\text{Active\_GCP\_Transaction}}$$
* **Purpose:** Blocks replay attacks (where an eavesdropper captures an honest boot quote from logs and attempts to re-send it over the network).

#### Step 4: Software Integrity Validation (Golden Profile Verification)
The engine decodes the SHA-256 register block inside the `PCR_Quote` and compares each PCR value against the expected golden database profiles:
$$\text{PCR}_{\text{Quote}}[i] == \text{PCR}_{\text{Golden\_Database}}[i] \quad \text{for } i \in \{0, 2, 4, 7, 9\}$$
* **Purpose:** Guarantees that the software stack currently booting the server is our unmodified, "blessed" GDC installer ISO. If an attacker modified `user-data` to write rogue backdoor keys, the hash measurement of `PCR 9` would mutate, and the Cloud App would **REJECT** the enrollment.

#### Step 5: CSR Validation & TLS Identity Issuance
Once checks 1 through 4 pass:
1.  The engine validates the `LID_CSR` schema.
2.  The Cloud CA signs the CSR, creating the GDC Client TLS Certificate:
    $$\text{SignCSR}(\text{LID\_CSR}, \text{GDC\_Intermediate\_CA}) \Rightarrow \text{Device\_Identity\_TLS\_Certificate}$$
3.  The database updates the node's tracking record state to `BOOTSTRAP_COMPLETE`.
4.  Returns the TLS certificate to the client node.
