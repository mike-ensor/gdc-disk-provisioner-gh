# Google Distributed Cloud (GDC) Offline Network Architecture & VLAN Segmentation

This document specifies the network architecture, communication boundaries, and VLAN network isolation mechanisms implemented by the GDC Offline Bootloader ISO and installer.

---

## 1. Network Segmentation Strategy: Split-Plane Management

To satisfy GDC's strict security and multi-tenancy requirements, edge nodes segment network traffic into two isolated network domains:

1. **The Host/Machine (Default) Network:**
   * **Purpose:** For node-level administrative tasks, SSH access, system log streaming (webhooks), GCS asset syncing, internet-facing queries, and host maintenance.
   * **Configuration:** Standard IPv4 DHCP enabled natively in the `main` routing table, ensuring standard administrative lookups, diagnostic pings, and DNS queries resolve instantly out-of-the-box.
2. **The Kubernetes (Cluster) Network:**
   * **Purpose:** Dedicated exclusively to Kubernetes cluster operations, control plane traffic, etcd syncing, worker node cross-talk, and pod networks.
   * **VLAN Tag:** `109` (attached as sub-interface `enp1s0.109` or local standard tag)

This architecture guarantees that all Kubernetes resources are created and maintained within their own defined network, completely isolated from administrative or out-of-band host management interfaces, while keeping host diagnostics simple and failure-tolerant.

---

## 1.1. Networking Interface Layout Goal

Below is the targeted, production-grade segmented interface specification designed for bare-metal nodes:

### 1. Default Interface (Host Interface / Machine Interface)
* **Physical Interface:** `enp1s0` (first NIC, native/untagged port)
* **IP Address Allocation:** DHCP Enabled (`dhcp4: true`)
* **IPv6 Configuration:** Disabled (`dhcp6: no`)

### 2. Kubernetes Interface (Cluster Control Plane Segment)
* **VLAN Interface:** `enp1s0.109` (VLAN tag `109` on the primary NIC)
* **IP Address Allocation:** `172.31.250.10/24` (or dynamically allocated within `172.31.250.0/24`)
* **Gateway:** `none` (confined to local L2 switch domain by default) or `172.31.250.1`
* **DNS Nameservers:** `none` (or designated cluster DNS servers)

### 3. Secondary/Additional Physical Interface (Administrative Fallback)
* **Physical Interface:** `enp2s0` (second NIC, if present)
* **Purpose:** Auxiliary fallback segment in the `main` routing table.
* **IPv4 Configuration:** DHCP enabled (`dhcp4: true`)
* **IPv6 Configuration:** Disabled (`dhcp6: no`)

This setup guarantees that all core GDC workload traffic stays segmented on dedicated VLANs, while keeping host-level diagnostic lookups simple and failure-tolerant.

```text
                             [ PHYSICAL PORT: enp1s0 ]
                                         │
                    ┌────────────────────┴────────────────────┐
                    ▼                                         ▼
        [ Native IP: DHCP Enabled ]              [ VLAN Sub-interface: enp1s0.109 ]
                    │                                         │
                    ▼                                         ▼
         [ Default / main Table ]                  [ Isolated VLAN Segment ]
         • Standard Host shell                     • Dedicated 802.1Q Tag (109)
         • Default Outbound & DNS                  • Confined L2 Domain / 172.31.250.0/24
         • Scoped: Host Admin & Webhooks           • Scoped: K8s / etcd / Pods
```

---

## 2. Persistent Netplan VLAN Configuration (Ubuntu 24.04 LTS)

Ubuntu 24.04 LTS utilizes **Netplan** as its default network configuration renderer (backed by `systemd-networkd`). The initial networking configuration is declared inside our Subiquity autoinstall profile (`/nocloud/user-data`) and persistently written to `/etc/netplan/01-netcfg.yaml` upon installation.

Below is the standard, production-grade Netplan layout implementing the isolated split-plane configuration:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp1s0:
      dhcp4: true
      dhcp6: no
      dhcp-identifier: mac
      critical: true
      link-local: []
    enp2s0:
      dhcp4: true
      dhcp6: no
      dhcp-identifier: mac
      critical: true
      link-local: []
  vlans:
    enp1s0.109:
      id: 109
      link: enp1s0
      addresses:
        - 172.31.250.10/24
```

---

### 2.1. Early-Stage DHCP Identity: Why `dhcp-identifier: mac` is Enforced

During the earliest bootstrap stages (PXE network boot, Linux kernel/casper initialization with `ip=dhcp`, Subiquity autoinstall, and First Boot), bare-metal nodes must maintain a single, deterministic IPv4 address. 

#### 1. The Client Identifier Discrepancy & IP Churn
* **PXE & Initramfs Phase:** When the node boots into the live installer environment over PXE, the kernel/initramfs DHCP client requests an IP lease using the network interface's hardware MAC address as the client identifier (RFC 2132, type `01:<mac>`).
* **The Default `systemd-networkd` Behavior:** In Ubuntu 24.04 LTS, `systemd-networkd` (the Netplan backend) defaults to RFC 4361 DUID client identifiers (`dhcp-identifier: duid`). The DUID is derived from `/etc/machine-id`. Because the live installer runs inside an ephemeral RAM overlay (`/cow`), its generated machine ID does not match the initramfs MAC identifier.
* **The Failure Mode:** When Subiquity applies its autoinstall network configuration (`netplan apply`), `systemd-networkd` sends a DHCP request with the DUID client ID. Upstream DHCP servers (dnsmasq, ISC DHCP, Kea, switch DHCP agents) treat this as an entirely different machine, lease a new IP address, and immediately expire or drop the original IP lease.

#### 2. Synchronous Installer Deadlocks (The Webhook Trap)
Subiquity logs installer progress synchronously to the GDC Companion API (`reporting: webhook`). When `netplan apply` triggers mid-install IP churn:
1. The socket connection to the Companion server is bound to the original IP address.
2. When `systemd-networkd` swaps the IP address on the interface, the existing TCP socket becomes orphaned. Packets can no longer route to the vacated IP.
3. Subiquity's reporting handler uses Python's `urllib.request.urlopen` with no socket timeout. Under default Linux kernel parameters (`net.ipv4.tcp_keepalive_time=7200`), the process blocks in `sk_wait_data`/`tcp_recvmsg_locked` for 2 hours, completely stalling disk partitioning and OS installation.

#### 3. Why `mac` is Used for DHCP
By explicitly enforcing `dhcp-identifier: mac` across all early-stage network declarations:
* `systemd-networkd` is constrained to send the exact hardware MAC address as its DHCP Client Identifier, identical to the kernel/PXE bootloader.
* Upstream DHCP servers recognize the request as a lease renewal rather than a new client, preserving the exact same IP throughout LiveCD boot, Subiquity partitioning, First Boot, and post-install configuration.
* Adding `critical: true` directs `systemd-networkd` (`KeepConfiguration=yes`) never to flush addresses or tear down the interface link during Netplan reconfiguration passes.
* In conjunction, `bootcmd` tunes kernel TCP keepalive parameters (`net.ipv4.tcp_keepalive_time=15`, `net.ipv4.tcp_retries2=5`) so that even if an external switch flaps, any severed socket aborts in ~30 seconds rather than freezing the installer for hours.

---

## 3. Dynamic Build-Time Configuration

During the Phase 1 ISO build stage, the target subnets, VLAN IDs, gateways, and DNS servers for both interfaces are pulled from our centralized environment config (`src/build/build.env`). 

The build pipeline injects these parameters dynamically into the cloud-init network configuration block:

| Parameter | Build Variable | Default Value | Network Segment | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Machine IP / Subnet** | `BOOTSTRAP_MACHINE_IP_CIDR` | `192.168.4.11/24` | Management Network | Static IP fallback when DHCP is disabled |
| **Machine Gateway** | `BOOTSTRAP_MACHINE_GATEWAY` | `192.168.4.1` | Management Network | Gateway for host management |
| **Machine VLAN ID** | `BOOTSTRAP_MACHINE_VLAN_ID` | `0` | Physical 802.1Q tag | `0` = Flat, untagged native network (non-VLAN) |
| **Machine DNS** | `BOOTSTRAP_MACHINE_DNS` | `192.168.4.1, 8.8.8.8, 8.8.4.4` | Management Network | Host nameservers |
| **Kubernetes IP / Subnet** | `BOOTSTRAP_K8S_IP_CIDR` | `172.31.250.10/24` | Kubernetes Network (VLAN) | High-end RFC 1918 space (`172.31.250.0/24`) |
| **Kubernetes Gateway** | `BOOTSTRAP_K8S_GATEWAY` | `none` | Kubernetes Network (VLAN) | `none` confines cluster VLAN to local L2 switch domain |
| **Kubernetes VLAN ID** | `BOOTSTRAP_K8S_VLAN_ID` | `109` | Physical 802.1Q tag | Tagged 802.1Q VLAN (`0` disables VLAN tagging) |
| **Kubernetes DNS** | `BOOTSTRAP_K8S_DNS` | `none` | Kubernetes Network (VLAN) | Nameservers for cluster segment (`none` if unrouted) |
| **Fallback Cluster VLAN** | `FALLBACK_CLUSTER_VLAN_ID` | `0` | Standalone Fallback | `0` = Untagged flat network if Companion is unreachable |

---

## 4. Verification and Routing Control

To verify the setup or manually execute diagnostic queries, operators can use standard Linux network utilities:

```bash
# 1. List active network devices and VLAN interfaces
ip -d link show type vlan

# 2. Query system routes
ip route show

# 3. Perform an administrative outbound ping
ping -c 3 8.8.8.8

# 4. Perform a cluster control plane ping via the VLAN interface
ping -I enp1s0.109 -c 3 172.31.250.10
```

---

## 5. Hub-and-Spoke Sideloading boundaries

The offline local service hubs bind to the loopback interface (`127.0.0.1`), allowing local system processes (like Kubelet or containerd) to fetch code, packages, and container images locally without external network exposure:

* **Gitea Git Server (Port 3000):** Exposes configurations at `http://127.0.0.1:3000/gdc/bootstrap-playbooks.git`.
* **Nexus APT Repository (Port 8081):** Exposes debian package mirrors at `http://127.0.0.1:8081/repository/gdc-apt-proxy/`.
* **Nexus OCI Docker Registry Group (Port 5001):** Consolidates local and cached images at `http://127.0.0.1:5001`.
* **Nexus LLM Model Proxy & Raw Store (Port 8081/raw):** Serves raw GGUF neural weights locally.

---

## 6. Offline Update Pathways

Lifecycle modifications are pulled through two designated routes:

* **Option A: Sideload Update (Offline Media):** Inserting a USB drive labeled `GDC-UPDATE-USB` triggers a custom `udev` rule, launching our headless update loop. The script verifies cryptographic signatures (`update.sig`), mounts the media, and pushes Git bundles and package assets to our local Gitea/Nexus servers on localhost.
* **Option B: Connected Update (Reverse VPN):** Initiates an outbound-only WireGuard tunnel. The host routes WireGuard through the primary network domain, and the Gitea instance on the host pulls configuration updates from `UPSTREAM_PLAYBOOKS_REPO` without exposing the isolated cluster network.

---

## 7. Local Development & Bootstrap Network Prerequisites

During local development and bare metal staging, specific network ports must be open and reachable across your subnet to prevent automated installations from failing and dropping back into the interactive TUI.

### 7.1. Required Network Ports

| Port | Protocol | Source | Destination | Service / Purpose |
| :--- | :---: | :--- | :--- | :--- |
| **`80` / `443`** | TCP | GDC Booting Node | Telemetry Endpoint | **GDC External Telemetry / Logging** |
| **`16000`** | TCP | GDC Booting Node | Bootimus NAS Server | **Bootimus HTTP File Assets (ISO, user-data, kernel)** |
| **`26000`** | TCP | Admin Workstation | Bootimus NAS Server | **Bootimus REST API Endpoint** |

### 7.2. External Telemetry Access
To allow the booting node to successfully verify connectivity to the external telemetry endpoint, the network must permit outbound traffic to the configured telemetry URL (e.g., `gdc-companion.ensor-labs.com`).

If outbound connectivity is blocked or unavailable, the node's `early-commands` connectivity health checks will time out, causing Subiquity to halt the headless installation and drop back into manual interactive setup.
