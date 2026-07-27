# Google Distributed Cloud (GDC) Offline Network Architecture & VRF Segmentation

This document specifies the network architecture, communication boundaries, and Virtual Routing and Forwarding (VRF) network isolation mechanisms implemented by the GDC Offline Bootloader ISO and installer.

---

## 1. Network Segmentation Strategy: Split-Plane Management

To satisfy GDC's strict security and multi-tenancy requirements, edge nodes segment network traffic into two isolated routing domains:

1. **The Host/Machine (Default) Network:**
   * **Purpose:** For node-level administrative tasks, SSH access, system log streaming (webhooks), GCS asset syncing, internet-facing queries, and host maintenance.
   * **Configuration:** Standard IPv4 DHCP enabled natively in the `main` routing table. No VRF encapsulation is applied, ensuring standard administrative lookups, diagnostic pings, and DNS queries resolve instantly out-of-the-box.
2. **The Kubernetes (Cluster) Network:**
   * **Purpose:** Dedicated exclusively to Kubernetes cluster operations, control plane traffic, etcd syncing, worker node cross-talk, and pod networks.
   * **VRF Device:** `vrf-k8s` (mapped to Routing Table `20`)
   * **VLAN Tag:** `109` (attached as sub-interface `enp1s0.109` or local standard tag)

This architecture guarantees that all Kubernetes resources are created and maintained within their own defined network, completely isolated from administrative or out-of-band host management interfaces, while keeping host diagnostics simple and failure-tolerant.

---

## 1.1. Networking Interface Layout Goal

Below is the targeted, production-grade segmented interface specification designed for bare-metal nodes:

### 1. Default Interface (Host Interface / Machine Interface)
* **Physical Interface:** `enp1s0` (first NIC, native/untagged port)
* **IP Address Allocation:** DHCP Enabled (`dhcp4: true`)
* **IPv6 Configuration:** Disabled (`dhcp6: no`)
* **VRF Association:** None *(runs natively in the default `main` routing table)*

### 2. Kubernetes Interface (Cluster Control Plane Segment)
* **VLAN Interface:** `enp1s0.109` (VLAN tag `109` on the primary NIC)
* **IP Address Allocation:** `192.168.109.14/24` *(widened from /29 to /24 to guarantee Layer 2 gateway reachability)*
* **Gateway:** `192.168.109.1`
* **DNS Nameservers:** `192.168.109.1` *(VLAN Gateway)*, `8.8.8.8`, and `8.8.4.4`
* **VRF Association:** Bound to `vrf-k8s` (Routing Table `20`)

### 3. Secondary/Additional Physical Interface (Administrative Fallback)
* **Physical Interface:** `enp2s0` (second NIC, if present)
* **Purpose:** Auxiliary fallback segment in the `main` routing table.
* **IPv4 Configuration:** DHCP enabled (`dhcp4: true`)
* **IPv6 Configuration:** Disabled (`dhcp6: no`)
* **VRF Association:** None *(completely isolated from GDC routing constraints)*

This setup guarantees that all core GDC workload traffic stays locked inside hardware-backed VRFs, while keeping host-level diagnostic lookups simple and failure-tolerant.

```text
                             [ PHYSICAL PORT: enp1s0 ]
                                         │
                    ┌────────────────────┴────────────────────┐
                    ▼                                         ▼
        [ Native IP: DHCP Enabled ]              [ VLAN Sub-interface: enp1s0.109 ]
                    │                                         │
                    ▼                                         ▼
         [ Default / main Table ]                  [ VRF Master: vrf-k8s ]
         • Standard Host shell                     • Routing Table: 20
         • Default Outbound & DNS                  • Independent Gateway/DNS
         • Scoped: Host Admin & Webhooks           • Scoped: K8s / etcd / Pods
```

---

## 2. Persistent Netplan VRF Configuration (Ubuntu 24.04 LTS)

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
      link-local: []
    enp2s0:
      dhcp4: true
      dhcp6: no
      link-local: []
  vlans:
    enp1s0.109:
      id: 109
      link: enp1s0
      addresses:
        - 192.168.109.14/24
      routes:
        - to: default
          via: 192.168.109.1
          metric: 200
      nameservers:
        addresses:
          - 192.168.109.1
          - 8.8.8.8
          - 8.8.4.4
  vrfs:
    vrf-k8s:
      table: 20
      interfaces:
        - enp1s0.109
```

---

## 3. Dynamic Build-Time Configuration

During the Phase 1 ISO build stage, the target subnets, VLAN IDs, gateways, and DNS servers for both interfaces are pulled from our centralized environment config (`src/build/build.env`). 

The build pipeline injects these parameters dynamically into the cloud-init network configuration block:

| Parameter | Build Variable | Default Value | Scoped Routing Domain |
| :--- | :--- | :--- | :--- |
| **Machine IP / Subnet** | `MACHINE_IP_CIDR` | `192.168.10.5/24` | `vrf-machine` (Table 10) |
| **Machine Gateway** | `MACHINE_GATEWAY` | `192.168.10.1` | `vrf-machine` (Table 10) |
| **Machine VLAN ID** | `MACHINE_VLAN_ID` | `10` | Physical 802.1Q tag |
| **Machine DNS** | `MACHINE_DNS` | `8.8.8.8, 8.8.4.4` | `vrf-machine` (Table 10) |
| **Kubernetes IP / Subnet** | `K8S_IP_CIDR` | `192.168.20.5/24` | `vrf-k8s` (Table 20) |
| **Kubernetes Gateway** | `K8S_GATEWAY` | `192.168.20.1` | `vrf-k8s` (Table 20) |
| **Kubernetes VLAN ID** | `K8S_VLAN_ID` | `20` | Physical 802.1Q tag |
| **Kubernetes DNS** | `K8S_DNS` | `1.1.1.1` | `vrf-k8s` (Table 20) |

---

## 4. Verification and Routing Domain Control

To verify the setup or manually execute diagnostic queries inside a specific VRF routing domain, operators must prefix standard Linux network utility commands with `ip vrf exec`:

```bash
# 1. List active VRF devices and Table associations
ip link show type vrf

# 2. Query routes assigned to the Machine VRF
ip route show table 10

# 3. Query routes assigned to the Kubernetes VRF
ip route show table 20

# 4. Perform an administrative outbound ping within the Machine VRF
sudo ip vrf exec vrf-machine ping -c 3 8.8.8.8

# 5. Perform a cluster control plane ping within the Kubernetes VRF
sudo ip vrf exec vrf-k8s ping -c 3 192.168.20.1
```

---

## 5. Hub-and-Spoke Sideloading boundaries

Even under active VRFs, the offline local service hubs bind to the loopback interface (`127.0.0.1`), allowing local system processes (like Kubelet or containerd) to fetch code, packages, and container images locally without cross-VRF routing leaks:

* **Gitea Git Server (Port 3000):** Exposes configurations at `http://127.0.0.1:3000/gdc/bootstrap-playbooks.git`.
* **Nexus APT Repository (Port 8081):** Exposes debian package mirrors at `http://127.0.0.1:8081/repository/gdc-apt-proxy/`.
* **Nexus OCI Docker Registry Group (Port 5001):** Consolidates local and cached images at `http://127.0.0.1:5001`.
* **Nexus LLM Model Proxy & Raw Store (Port 8081/raw):** Serves raw GGUF neural weights locally.

---

## 6. Offline Update Pathways

Lifecycle modifications are pulled through two designated routes:

* **Option A: Sideload Update (Offline Media):** Inserting a USB drive labeled `GDC-UPDATE-USB` triggers a custom `udev` rule, launching our headless update loop. The script verifies cryptographic signatures (`update.sig`), mounts the media, and pushes Git bundles and package assets to our local Gitea/Nexus servers on localhost.
* **Option B: Connected Update (Reverse VPN):** Initiates an outbound-only WireGuard tunnel. Because the host routes WireGuard through the `vrf-machine` domain, the Gitea instance on the host pulls configuration updates from `UPSTREAM_PLAYBOOKS_REPO` without any access to the isolated `vrf-k8s` routing context.

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
