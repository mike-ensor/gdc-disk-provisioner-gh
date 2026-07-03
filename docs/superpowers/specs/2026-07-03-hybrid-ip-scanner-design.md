# Design Spec: Hybrid MAC-to-IP Suffix Hashing & Jittered Fallback Protocol

## 1. Abstract
This specification defines a distributed, offline-friendly dynamic IP assignment protocol for Google Distributed Cloud (GDC) Bare-Metal nodes. By combining deterministic MAC-to-IP hashing (preferred suffix calculation) with a multi-pass, randomized splay defensive fallback loop, booting nodes can coordinate collision-free IP suffix selections on the same Layer 2 segment with zero central state synchronization.

---

## 2. IP Suffix Mapping & CIDR Scaling
To prevent IP suffix calculation from generating host addresses outside the target subnet, the preferred suffix is dynamically mapped to the usable host pool of the scanning CIDR network (e.g., `/29` subnets have exactly 6 usable host IPs).

Let the CIDR range have $N$ usable host addresses. We derive the index from the last byte of the MAC address:
$$\text{Candidate\_Index} = \text{Last\_Byte\_of\_MAC} \pmod N$$

This index maps to the host IP list derived via Python's native `ipaddress` module. For example:
- Subnet `192.168.10.0/29` has hosts: `[.1, .2, .3, .4, .5, .6]`. A MAC suffix of `0xd9` (217) maps to:
  $$\text{Index} = 217 \pmod 6 = 0 \implies \text{Host: } 192.168.10.1$$
- Subnet `172.16.1.8/29` has hosts: `[.9, .10, .11, .12, .13, .14]`. A MAC suffix of `0xd9` (217) maps to:
  $$\text{Index} = 217 \pmod 6 = 0 \implies \text{Host: } 172.16.1.9$$
- Subnet `10.200.0.16/29` has hosts: `[.17, .18, .19, .20, .21, .22]`. A MAC suffix of `0xd9` (217) maps to:
  $$\text{Index} = 217 \pmod 6 = 0 \implies \text{Host: } 10.200.0.17$$

---

## 3. Algorithm & Protocol Flow
1. **Auto-detect interface and MAC**: Get primary physical interface and extract its HW MAC address.
2. **Compute Preferred Suffix Index**: Calculate `Last_Byte_of_MAC % len(hosts)`.
3. **Verify Preferred Host IP**:
   - Sleep for a random splay delay (1.0 to 3.0 seconds).
   - Query if the preferred IP is taken.
   - **If FREE**: Immediately run Defensive Binding (`ip addr add <ip> dev <interface>`) to reserve it, write state env, and exit.
4. **Shuffled Fallback Loop**:
   - Shuffle remaining usable host list.
   - For each candidate:
     - Sleep for a random splay delay (1.0 to 3.0 seconds).
     - Verify if candidate is taken.
     - **If FREE**: Immediately bind the IP, write state env, and exit.
5. **Hard Safety Fallback**: If all IPs are taken, use the defined fallback default.

---

## 4. Test Matrix Verification Plans
- Test dozens of simulated MAC addresses against `/29` CIDR blocks (`192.168.10.0/29`, `172.16.1.8/29`, `10.200.0.16/29`), asserting that the calculated preferred IP always falls strictly inside the subnet's host boundaries.
- Mock external network commands (`arp-scan`, `arping`, `ping`, `ip addr add`) to verify the fallback logic works deterministically under various simulated network state collisions.
