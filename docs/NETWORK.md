# Google Distributed Cloud (GDC) Offline Network Architecture & VRF Segmentation

This document specifies the network architecture, communication boundaries, and Virtual Routing and Forwarding (VRF) network isolation mechanisms implemented by the GDC Offline Bootloader ISO and installer.

---

## 1. Network Segmentation Strategy: Machine vs. Kubernetes

To satisfy GDC's strict security and multi-tenancy requirements, edge nodes segment network traffic into two completely isolated routing domains over a **single physical network interface** (e.g., `eth0` or `enp0s3`):

1. **The Machine (Host) Network:**
   * **Purpose:** For node-level administrative tasks, SSH access, system log streaming (webhooks), GCS asset syncing, and host maintenance.
   * **VRF Device:** `vrf-machine` (mapped to Routing Table `10`)
   * **VLAN Tag:** `10` (or local standard tag)
2. **The Kubernetes (Cluster) Network:**
   * **Purpose:** Dedicated exclusively to Kubernetes cluster operations, control plane traffic, etcd syncing, worker node cross-talk, and pod networks.
   * **VRF Device:** `vrf-k8s` (mapped to Routing Table `20`)
   * **VLAN Tag:** `20` (or cluster standard tag)

This architecture guarantees that all Kubernetes resources are created and maintained within their own defined network, completely isolated from administrative or out-of-band host management interfaces.

```text
                             [ PHYSICAL PORT: eth0 ]
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
        [ VLAN Sub-interface: eth0.10 ]         [ VLAN Sub-interface: eth0.20 ]
                    │                                       │
                    ▼                                       ▼
         [ VRF Master: vrf-machine ]              [ VRF Master: vrf-k8s ]
         • Routing Table: 10                     • Routing Table: 20
         • Independent Gateway/DNS               • Independent Gateway/DNS
         • Scoped: Host Admin & SSH              • Scoped: K8s / etcd / Pods
```

---

## 2. Persistent Netplan VRF Configuration (Ubuntu 24.04 LTS)

Ubuntu 24.04 LTS utilizes **Netplan** as its default network configuration renderer (backed by `systemd-networkd`). The initial networking configuration is declared inside our Subiquity autoinstall profile (`/nocloud/user-data`) and persistently written to `/etc/netplan/01-netcfg.yaml` upon installation.

Below is the standard, production-grade Netplan layout implementing the isolated dual-VRF configuration:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: no
      dhcp6: no
      link-local: []
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses:
        - 192.168.10.5/24
      routes:
        - to: default
          via: 192.168.10.1
          metric: 100
      nameservers:
        addresses:
          - 8.8.8.8
          - 8.8.4.4
    eth0.20:
      id: 20
      link: eth0
      addresses:
        - 192.168.20.5/24
      routes:
        - to: default
          via: 192.168.20.1
          metric: 200
      nameservers:
        addresses:
          - 1.1.1.1
  vrfs:
    vrf-machine:
      table: 10
      interfaces:
        - eth0.10
    vrf-k8s:
      table: 20
      interfaces:
        - eth0.20
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
| **`8080`** | TCP | GDC Booting Node | Admin Workstation | **GDC Installation Companion (Log Webhooks)** |
| **`16000`** | TCP | GDC Booting Node | Bootimus NAS Server | **Bootimus HTTP File Assets (ISO, user-data, kernel)** |
| **`26000`** | TCP | Admin Workstation | Bootimus NAS Server | **Bootimus REST API Endpoint** |

### 7.2. Host Firewall Configuration (UFW Prerequisite)
To allow the booting node to successfully verify connectivity to your local workstation running the `install_companion.py` script on port `8080`, **you must allow incoming connections on port `8080`**:

```bash
# Allow incoming GDC companion logging webhooks on the workstation
sudo ufw allow 8080/tcp
```
If this port is blocked, the node's `early-commands` connectivity health checks will time out, causing Subiquity to halt the headless installation and drop back into manual interactive setup.
