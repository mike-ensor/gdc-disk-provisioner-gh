# GDC Disk Provisioner - Development Environment Setup

This document outlines the necessary infrastructure components, services, and networking configurations required to successfully build, test, and deploy GDC Bare Metal nodes using the automated ISO provisioner.

## 1. Step CA (mTLS Zero-Touch Provisioning)

The GDC Disk Provisioner relies on a central Certificate Authority to attest and enroll nodes automatically upon first boot using their physical TPM 2.0 Endorsement Keys (EK). We use **Smallstep (Step CA)** for this purpose.

### 1.1 Requirements
* The Step CA server must be reachable over the network by the booting nodes.
* The TLS certificate presented by the Step CA server **MUST** include a Subject Alternative Name (SAN) matching the public URL the nodes use to connect (e.g., `step-ca.ensor-labs.com`).

### 1.2 Configuring the Automated ACME Provisioner
By default, Step CA initializes with a `JWK` provisioner, which requires a human to type a password into a terminal. Because GDC nodes provision completely headless in the background via `ansible-pull`, interactive prompts will crash the process with an `error allocating terminal: open /dev/tty` error.

You must add an automated ACME provisioner to your Step CA server:

```bash
# Execute this on the server hosting your Step CA instance
step ca provisioner add acme --type ACME
```

Once added, ensure your `src/build/local.env` is updated to point to this non-interactive provisioner:
```env
STEP_CA_URL="https://step-ca.your-domain.com"
STEP_PROVISIONER_NAME="acme"
```

### 1.3 Validation Checks
To verify your Step CA is configured correctly for GDC node ingestion, run the following tests from a client machine:

**Check TLS SAN configuration:**
```bash
# Ensure your public domain shows up under "Subject Alternative Name"
openssl s_client -connect step-ca.your-domain.com:443 -showcerts < /dev/null 2>/dev/null | openssl x509 -noout -text | grep -A 1 "Subject Alternative Name"
```

**Check Provisioner availability:**
```bash
# Ensure the "acme" provisioner is listed in the output
curl -sk https://step-ca.your-domain.com/provisioners
```

---

## 2. Bootimus (PXE Boot Automation)

**Bootimus** is a custom PXE/iPXE orchestration server that automatically serves the compiled GDC Bootstrap ISOs over HTTP to bare metal nodes booting from the network. 

The GDC ISO build pipeline (specifically `make deploy` or `gdc-iso-build-deploy`) contains direct API integrations with Bootimus. When a new ISO finishes compiling, the pipeline registers it in the Bootimus database and automatically configures the `autoinstall` boot parameters to ensure zero-touch installation.

### 2.1 Bootimus Installation
*TBD: Detailed installation and configuration instructions for the Bootimus service will be documented in a subsequent effort.*

### 2.2 Network & DHCP Configuration (Option 67)
For nodes to successfully boot the GDC ISO over the network, your lab's DHCP server must be configured to point PXE clients to the Bootimus server.

Update your DHCP server configuration (e.g., `dnsmasq`, `isc-dhcp-server`, or your enterprise router) with the following parameters:

* **Next-Server (Option 66):** `[BOOTIMUS_IP_ADDRESS]`
* **Bootfile-Name (Option 67):** `bootimus.efi` (for UEFI nodes) or `undionly.kpxe` (for legacy BIOS nodes).

**Example `dnsmasq` configuration snippet:**
```conf
# Point PXE clients to the Bootimus server
dhcp-boot=bootimus.efi,,[BOOTIMUS_IP_ADDRESS]
```

When a node powers on, it will request an IP, receive the Bootimus address, download the `bootimus.efi` payload, and Bootimus will dynamically serve the `gdc-bootstrap-ubuntu-24.04-vX.Y.Z.iso` configured by the build pipeline.
