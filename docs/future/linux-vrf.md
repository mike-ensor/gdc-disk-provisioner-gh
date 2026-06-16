# Linux VRF for Multiple IPs on Single Physical Interface

To assign multiple IP addresses to a single interface while keeping them isolated in different routing domains, we must use Linux VRF (Virtual Routing and Forwarding) devices in combination with standard VLAN sub-interfaces.

A physical interface (e.g., `eth0`) can only be enslaved to one VRF. Therefore, we need to create VLANs for each IP address and enslave each VLAN sub-interface to its respective VRF.

## Step-by-Step Configuration Template

### 1. Create the VRF devices
First, create the VRF interfaces and bind them to distinct routing tables. Custom routing table numbers or names (mapped in `/etc/iproute2/rt_tables`) can be used.

```bash
# Create VRF Red and assign it to table 1001
sudo ip link add vrf-red type vrf table 1001
sudo ip link set vrf-red up

# Create VRF Blue and assign it to table 1002
sudo ip link add vrf-blue type vrf table 1002
sudo ip link set vrf-blue up
```

### 2. Create VLAN sub-interfaces
Because the physical interface can only belong to one master, attach different VLAN tags (e.g., 10 and 20) to the main interface (`eth0`).

```bash
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip link add link eth0 name eth0.20 type vlan id 20

sudo ip link set eth0.10 up
sudo ip link set eth0.20 up
```

### 3. Enslave VLAN sub-interfaces to the VRFs
Attach the VLAN interfaces as "slaves" to their respective VRFs.

```bash
sudo ip link set eth0.10 master vrf-red
sudo ip link set eth0.20 master vrf-blue
```

### 4. Assign the IP addresses
Once enslaved, configure the IP addresses on the sub-interfaces. The kernel will automatically scope these addresses and their connected routes to the VRF-associated routing tables.

```bash
sudo ip addr add 192.168.10.10/24 dev eth0.10
sudo ip addr add 192.168.20.10/24 dev eth0.20
```

## Validating and Testing
To verify that the configuration is isolated and that packets are routed through the correct VRF table, use the `ip vrf exec` command.

```bash
# Show routing table for VRF Red
sudo ip vrf exec vrf-red ip route show

# Ping a device on the VRF Red network, forcing the packet out via the VRF's table
sudo ip vrf exec vrf-red ping 192.168.10.1
```
