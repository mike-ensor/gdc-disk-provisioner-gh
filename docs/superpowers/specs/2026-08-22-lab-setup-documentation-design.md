# Specification: Local Lab Setup Guide (`LAB_SETUP.md`)

## 1. Overview
The goal of this task is to rename the existing `docs/DEV_ENVIRONMENT.md` to `docs/LAB_SETUP.md` and comprehensively refactor it. The new document will serve as a concise, clear instruction manual for setting up a local GDC Bare Metal test lab from scratch. 

It will adopt a "Prerequisites to Execution" flow, guiding the user chronologically through hardware acquisition, network configuration, cloud dependencies, and finally local service spin-up.

## 2. Document Structure

### 2.1 Overview & Hardware/Network Prerequisites
* **Introduction:** State the purpose of the lab (local GDC Bare Metal testing).
* **Target Machine Hardware:**
  * Note: Use external grounding data from official GDC documentation (e.g., https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/installing/node-machine-prerequisites) to validate and inform specific requirements when generating content.
  * Define minimums: 1+ physical computers, 4 CPU (8 vCPU with hyperthreading), 16GB RAM, 500GB SSD/NVMe.
  * Note that additional disks are supported and welcome.
* **Network Infrastructure:**
  * Define minimum space: `/24` RFC1918 IPv4 CIDR.
  * Require a dedicated Gateway IP.
  * Require a DHCP Server with network booting (PXE) capabilities.
  * Require TFTP capability (hosted via NAS, local disk, or router) to serve the initial PXE bootloader.

### 2.2 Cloud & Core Network Configuration
* **GCP Cloud Build Dependencies:**
  * Require an active GCP Project and Cloud Build API enablement.
  * **Critical CI/CD Variables:** Outline the environment variables passed into the Cloud Build pipeline to produce environment-specific ISOs. Provide a sample table showing variables like `_STEP_CA_URL`, `_PXE_SERVER_IP`, etc., with default/sample values.
* **DHCP & PXE Configuration:**
  * Migrate the Option 67 and Option 66 concepts from the old `DEV_ENVIRONMENT.md`.
  * Detail how to configure the DHCP server to point to the TFTP server, specifically instructing it to serve `bootimus.efi` as the payload.

### 2.3 Local Lab Services Setup
* **Step CA (mTLS Zero-Touch Provisioning):**
  * Migrate sections 1.1, 1.2, and 1.3 from the original `DEV_ENVIRONMENT.md` verbatim or with minor clarity tweaks. This covers the ACME provisioner, SAN requirements, and validation commands.
* **Bootimus:**
  * Explain its role as the PXE/iPXE orchestration server that dynamically serves the ISOs compiled by Cloud Build.
* **gdc-companion:**
  * Document its role as the local metadata and fallback service.
* **NAS Sync (Optional):**
  * Mention how a NAS can optionally store large assets (ISOs) and act as the TFTP server.

### 2.4 Operating the Lab (The Workflow)
* Provide a high-level, step-by-step lifecycle of a node boot to tie all the services together:
  1. Node powers on and requests DHCP.
  2. Node receives its IP and Option 67, then downloads `bootimus.efi` via TFTP.
  3. Bootimus serves the custom, environment-specific ISO built via Cloud Build.
  4. The node boots the ISO headless, authenticates against Step CA, and provisions itself.

## 3. Migration Plan
1. `git mv docs/DEV_ENVIRONMENT.md docs/LAB_SETUP.md`
2. Overwrite the contents of `docs/LAB_SETUP.md` with the new structure defined above, cleanly integrating the legacy Step CA text.
3. Update any internal references in other docs pointing to `DEV_ENVIRONMENT.md` (if any exist) to point to `LAB_SETUP.md`.