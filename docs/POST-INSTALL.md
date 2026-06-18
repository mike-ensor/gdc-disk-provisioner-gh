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
            ├── 5. Seals LUKS storage keys to TPM 2.0 PCR registers 0+2+7
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
