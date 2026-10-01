# Google Distributed Cloud (GDC) First-Boot Post-Install Lifecycle & Provisioning

This document specifies the sequence of operations, service handshakes, and host configuration actions that execute during the transition from a raw baseline OS installation to a hardened, cluster-ready GDC Production Node.

---

## 1. First-Boot Transition Sequence

The bootstrapping timeline spans approximately **16 minutes** from cold boot to a fully hardened, secure "Ready-Linux" state:

```text
  [ SUBIQUITY FINISHES ]
            │
            ▼ (Node Reboots)
  [ EARLY BOOT ] ---> Initramfs reads `/etc/keys/temp_key.key` to unlock LUKS
            │
            ▼ (Services Start)
  [ SYSTEMD RUNS ] -> Starts Gitea (3000) & Nexus (8081) on loopback
            │
            ▼ (gdc-provision.service starts)
  [ SERVICE HANDSHAKE ] -> Waits on local service port health checks
            │
            ▼
  [ ANSIBLE PULL ] -> Clones configuration playbooks from local Gitea mirror
            │
            ▼
  [ POST-INSTALL PLAYBOOK ]
            ├── 1. Performs safe offline OS system upgrades (via Nexus APT proxy)
            ├── 2. Installs core package loops (git, python3-pip, wireguard, etc.)
            ├── 3. Creates 'gdc-admin' with passwordless sudo permissions
            ├── 4. Executes CIS Level 2 hardening & purges snapd/bloat
            ├── 5. Seals LUKS storage keys to TPM 2.0 PCR registers 0+7
            ├── 6. Wipes temporary key file and erases insecure passcode slots
            ├── 7. Generates TPM-bound Device TLS identities & ssh keys
            └── 8. Pre-seeds mTLS trust credentials for GDC NodeAgent (Zero-SSH)
            │
            ▼
  [ SUCCESS SIGNAL ] -> Writes success token to serial console /dev/ttyS0
```

---

## 2. GDC Local Service Handshake

During system boot, systemd launches Gitea, Nexus, and `gdc-provision.service` (which executes `ansible-pull`) in parallel. Because the Java JVM-based Nexus registry can take 30 to 45 seconds to initialize its database and bind to port `8081`, direct execution of `ansible-pull` would crash immediately on connection refused.

To eliminate this race condition, the local Ansible playbook (`src/ansible/local.yml`) executes a localized port wait-loop as its primary tasks:

```yaml
- name: "GDC-VERIFY-001 | Check Gitea Service Hub Readiness (Port 3000)"
  ansible.builtin.wait_for:
    host: 127.0.0.1
    port: 3000
    state: started
    timeout: 60

- name: "GDC-VERIFY-002 | Check Nexus Service Hub Readiness (Port 8081)"
  ansible.builtin.wait_for:
    host: 127.0.0.1
    port: 8081
    state: started
    timeout: 90
```

This safely holds playbook processing in memory until both service gateways are active and listening.

---

## 3. Persistent Local Registry & APT Configuration

During the installation's late commands phase, pre-loaded package and OCI caches are copied from the read-only ISO media to persistent high-capacity logical volumes:
* **Gitea Persistent Storage:** Synced to `/var/lib/gitea` from `/cdrom/custom-data/gitea/`.
* **Nexus Persistent Storage:** Synced to `/var/lib/nexus` from `/cdrom/custom-data/nexus/`.

### Offline Package Maintenance & Upgrade
To execute system upgrades completely offline:
1. The node's APT sources list is locked to the local Nexus APT proxy endpoint:
   `http://127.0.0.1:8081/repository/gdc-apt-proxy/`
2. The playbook executes `apt-get upgrade` securely. Package indexes and updates are resolved directly from Nexus's pre-seeded blob store.
3. The playbook dynamically loops through our custom list of GDC core packages specified in `build.env` (under `POST_INSTALL_PACKAGES`) and installs them with fixed versions (e.g. `git`, `python3-pip`, `wireguard`).

---

## 4. GDC NodeAgent Pre-Installation & Zero-SSH Strategy

For GDC orchestration engines (like `bmctl` or the cluster controller) to bootstrap nodes completely without SSH (which is disabled or restricted in secure FIPS environments), the **GDC NodeAgent** is pre-installed/staged during the post-install playbook.

### Solve the Trust Problem (The mTLS Pre-Seed)
NodeAgent communicates strictly via mutual TLS (mTLS) over Port `9192`. To allow secure, SSH-less communication, the provisioning playbook must inject unique, authenticated GDC identities onto the node's local filesystem:

1. **Server CA Certificate:** To validate incoming cluster controller commands.
2. **Local Client CA Certificate:** To enforce client-side peer authorization.
3. **Local Node Certificate & Cryptographic Private Key:** Generated securely within the target TPM 2.0 PKCS#11 enclave so the node can prove its identity to the controller.

These credentials must match the exact paths declared in your GDC `CLUSTER_NAME.yaml` topology (e.g., `nodeAgentServerCACertificatePath`).

```text
[ ZERO-SSH ISO WORKFLOW ]

ISO Provisioning Playbook ──( Injects mTLS Credentials )──> NodeAgent Running
                                                                 │
                                                                 ▼
bmctl Workstation <───( Secure mTLS gRPC / Port 9192 )──── NodeAgent Listening
```

If these certificates are successfully pre-seeded, running `bmctl create cluster` will skip SSH attempts entirely and execute the secure gRPC handshake over Port `9192`, establishing an instant, authenticated deployment path.

---

## 5. Serial Console Logging & Diagnostics

To prevent terminal blockages if no hypervisor serial collector is actively listening during automated deployments, all installation status and success tokens are written to the physical serial console (`/dev/ttyS0`) using non-blocking subshells:

```bash
# Writes the completion success token to serial with a 3-second timeout fallback
timeout 3 sh -c 'echo "GDC_BOOTSTRAP_COMPLETE_SUCCESSFULLY" > /dev/ttyS0' || true
```

Operators can monitor `/var/log/gdc-ansible-pull.log` and `journalctl -u gdc-provision` to trace detailed step-by-step progress post-boot.

---

## 6. AMD fTPM / PSP Interrupt Deadlock Mitigation

AMD Ryzen Zen 4 (AM5) platforms suffer from a critical, low-level motherboard firmware bug where the ACPI tables incorrectly advertise hardware interrupt support for the Firmware TPM (fTPM / Platform Security Processor). 

### The Deadlock Mechanism
1. During early boot, the kernel loads the `tpm_tis` driver, which attempts to bind to the ACPI-declared fTPM interrupt lines.
2. Because the fTPM/PSP chipset fails to route these interrupts correctly, the CPU cores are instantly flooded with an unhandled, infinite interrupt storm, deadlocking the PCIe bus and freezing the system right as it transitions to the High-Resolution Time Stamp Counter (`tsc`) clocksource.
3. This is exacerbated during the **Second Reboot** when the temporary keyfile `/etc/keys/temp_key.key` is erased, forcing `initramfs-tools` to initialize the physical TPM in early kernel-space to unseal the LUKS keys.

### The Resolution
To permanently prevent early-boot deadlocks on AMD hardware, we enforce polling-only TPM access and maintain core CPU driver dependencies:
* **`tpm_tis.interrupts=0`:** Appended to the GRUB kernel command-line. This forces the built-in TPM driver to bypass hardware interrupt lines and operate in safe, high-performance polling mode.
* **Keep `ccp` Enabled:** The AMD Cryptographic Coprocessor (`ccp`) driver is critical for CPU power management and clock transitions on Zen 4. It **must not** be blacklisted, as doing so freezes the CPU at `1.6s`.
* **Standard Console Routing:** We use standard `console=ttyS0,115200` and avoid `earlycon` or legacy `earlyprintk` which trigger silent console handover hangs right after `hid_generic_init`.
* **`blacklist pcie_mp2_amd` and `blacklist amd_sfh`:** Blacklisted to prevent AMD Sensor Fusion Hub bus crashes.

---

## 7. Stage 7: Post-Cluster ConfigSync Provisioning

Following cluster creation and successful node readiness verification, the GDC state machine advances to **Stage 7 (`POST_CLUSTER`)** (managed by `src/ansible/stages/stage_post_cluster.yml` and the `post_cluster` Ansible role). In this stage, the installer validates CoreDNS and storage classes, then automatically provisions **Anthos Config Management (ACM) / ConfigSync** and the primary root synchronization repository (`primary-root-repo`).

```text
[ STAGE 7: POST-CLUSTER LIFECYCLE ]
               │
               ▼
   1. Cluster Sanity Checks (Nodes Ready, CoreDNS, Storage Classes)
               │
               ▼
   2. Enable Fleet Feature: `gcloud beta container fleet config-management enable`
               │
               ▼
   3. Apply ACM Operator Configuration (`sourceFormat: unstructured`)
               │
               ▼
   4. Wait for CRD: `rootsyncs.configsync.gke.io` condition=Established
               │
               ▼
   5. Zero-Disk Secret Bootstrapping (if private Git or OCI credentials configured)
      ├── Retrieve JSON from GSM via gcloud into in-memory facts (no_log)
      ├── Build K8s Secret manifest and pipe directly into `kubectl apply -f -` (stdin)
      └── Immediately purge in-memory secret facts in Ansible `always` block
               │
               ▼
   6. Render and Apply Primary RootSync (`/var/gdc-install/state/primary-root-repo.yaml`)
      ├── Resolve target dir: `config/clusters/<cluster-name>` (or `cluster_config_name`)
      ├── Configure Git (`auth: token` | `ssh`) or OCI (`auth: gcpserviceaccount` | `token` | `none`)
      └── Apply RootSync to namespace `config-management-system`
               │
               ▼
   7. Record Evidence into `/var/gdc-install/state/post-validation.json`
```

### 1. Idempotent Fleet Feature Enablement
The post-cluster workflow queries the GCP project to verify whether the Fleet Config Management feature is active:
```bash
gcloud beta container fleet config-management describe --project="${PROJECT_ID}"
```
*(In the Ansible task: `cmd: "gcloud beta container fleet config-management describe --project={{ target_gcp_project_id }}"`)*

If not enabled, it automatically and idempotently enables the feature across the project:
```bash
gcloud beta container fleet config-management enable --project="${PROJECT_ID}"
```
*(In the Ansible task: `cmd: "gcloud beta container fleet config-management enable --project={{ target_gcp_project_id }}"`)*

### 2. Applying ACM Operator Configuration
To support modern GitOps repository layouts without rigid hierarchical directory requirements, ConfigSync is configured in **unstructured format**. The playbook renders an operator spec at `/var/gdc-install/state/acm-config.yaml`:
```yaml
applySpecVersion: 1
spec:
  configSync:
    enabled: true
    sourceFormat: unstructured
```
And applies it to the cluster's fleet membership:
```bash
gcloud beta container fleet config-management apply \
  --membership="projects/${PROJECT_ID}/locations/${REGION}/memberships/${CLUSTER_NAME}" \
  --config=/var/gdc-install/state/acm-config.yaml \
  --project="${PROJECT_ID}"
```
*(In the Ansible task: `cmd: "gcloud beta container fleet config-management apply --membership=\"{{ membership }}\" --config=/var/gdc-install/state/acm-config.yaml --project=\"{{ target_gcp_project_id }}\""` where `membership` resolves to `projects/{{ target_gcp_project_id }}/locations/{{ target_gcp_region }}/memberships/{{ target_cluster_name }}`)*

### 3. Waiting for RootSync CRD Readiness
Because the ConfigSync operator asynchronously reconciles and creates its Custom Resource Definitions, immediate submission of a `RootSync` resource will fail. The playbook waits up to 180 seconds for `rootsyncs.configsync.gke.io` to reach condition `Established`:
```bash
kubectl --kubeconfig=/etc/kubernetes/admin.conf wait --for=condition=Established crd/rootsyncs.configsync.gke.io --timeout=180s
```

### 4. Zero-Disk Secret Bootstrapping
When `.cluster.primary_root_repo` requires authentication (via `git.gsm_secret_name` or `oci.gsm_secret_name`), the installer avoids writing sensitive credentials to disk:
1. **Dynamic In-Memory Retrieval:** Fetches the latest secret version from Google Secret Manager directly using `gcloud secrets versions access latest --secret="${GSM_SECRET_NAME}" --project="${PROJECT_ID}"` (Ansible task: `cmd: "gcloud secrets versions access latest --secret={{ target_secret_name }} --project={{ target_gcp_project_id }}"`). Tasks handling secret data are protected with `no_log: true`.
2. **Direct Stdin Injection:** Formulates the Kubernetes `Secret` manifest in memory and streams it directly to `kubectl apply -f -` via stdin into the `config-management-system` namespace. No plaintext token or private key touches disk.
3. **Immediate In-Memory Fact Purge:** An Ansible `always:` block immediately overwrites all in-memory variables (`gsm_access_res`, `gsm_secret_payload`, `secret_data_dict`, `secret_apply_res`) with empty values, preventing credential leakage in Ansible memory or state reports.

### 5. Automatic RootSync (`primary-root-repo`) Creation
The primary root repository sync is created from `/var/gdc-install/state/primary-root-repo.yaml`:
* **Directory Resolution:** Automatically targets `config/clusters/<cluster-name>/` inside the repository. This path can be customized via `.cluster.primary_root_repo.cluster_config_name`.
* **Git Source Types:** Configures `spec.git` with `repo`, `branch` (default `main`), `dir`, `auth: token` (or `ssh`), and links to `secretRef.name: "${GSM_SECRET_NAME}"` (populated from Ansible variable `{{ target_secret_name }}`).
* **OCI Source Types:** Configures `spec.oci` with `image`, `dir`, and authentication:
  * `auth: gcpserviceaccount` and `gcpServiceAccountEmail` when using a Workload Identity Google Service Account.
  * `auth: token` with `secretRef` when using a GSM pull secret.
  * `auth: none` for public images.
* **Application:** Applies the manifest to the cluster:
  ```bash
  kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f /var/gdc-install/state/primary-root-repo.yaml
  ```

### 6. Evidence Recording
Stage 7 writes full execution evidence to `/var/gdc-install/state/post-validation.json` (and updates the `/var/gdc-install/state/post-cluster.json` symlink), capturing ConfigSync status under `post_cluster_evidence.config_sync`:
```json
{
  "stage": "POST_CLUSTER",
  "status": "completed",
  "timestamp": "2026-09-30T12:00:00Z",
  "evidence": {
    "kubernetes_nodes_ready": true,
    "coredns_operational": true,
    "storage_classes_present": true,
    "config_sync": {
      "enabled": true,
      "rootsync_applied": true,
      "source_type": "git",
      "cluster_sync_dir": "config/clusters/my-cluster",
      "status": "completed"
    },
    "timing": {
      "start_time": "2026-09-30T11:58:00Z",
      "end_time": "2026-09-30T12:00:00Z",
      "duration_seconds": 120,
      "overall_provisioning_start_time": "2026-09-30T11:44:00Z"
    }
  }
}
```
This evidence is gathered by `gdc-collector` and reported back to the GDC Companion service to confirm that cluster turnup and GitOps reconciliation have succeeded.
