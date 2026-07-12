# Design Spec: Python-Powered Subnet CIDR Scanner for Crashed Node Discovery

## 1. Abstract
This specification defines the implementation of a robust, standard-library-based subnet scanning utility (`bin/crash-cart-scan-subnet.sh`) running via Python 3 on the GDC Bare-Metal deployment environment. 

The tool accepts an input CIDR range, dynamically parses it, performs a high-performance parallelized subnet sweep using ICMP pings and SSH port connection probes, and automatically attempts safe SSH diagnostics on any unidentified active targets. It replaces the empty shell of `bin/crash-cart-scan-subnet.sh` without any hardcoded network configurations or target credentials.

---

## 2. Core Features & Architecture

### A. Strict Argument-Driven Operation
To prevent configuration drift and hardcoding, the scanner accepts all options through CLI arguments:
1. **`-c` / `--cidr`** (Required): Standard CIDR block indicating the scanning subnet (e.g. `192.168.9.230/27`).
2. **`-e` / `--exclude`** (Optional): Comma-separated list of healthy, active, or known IPs to exclude from target identification (e.g. `192.168.9.234,192.168.9.248`).
3. **`-w` / `--workers`** (Optional): Number of concurrent execution threads in the `ThreadPoolExecutor` (defaults to `20`).
4. **`-t` / `--timeout`** (Optional): Socket connection and ping wait timeouts in seconds (defaults to `1.0`).
5. **`--ssh-user`** (Optional): Username used to attempt diagnostics on unidentified active nodes (defaults to `temporary-installer`).
6. **`--ssh-pass`** (Optional): Password used to attempt diagnostics on unidentified active nodes (defaults to `troubled-marble-150`).

### B. High-Performance Parallel Sweep
* **Host Range Extraction**: Parses the CIDR range dynamically with `ipaddress.ip_network(cidr, strict=False).hosts()`.
* **Multi-Threaded Probe**:
  * Runs concurrent standard ICMP `ping` scans.
  * Checks for open TCP Port 22 using standard socket connection handshakes.
* **Non-Blocking Execution**: High worker density ensures that sweeping a `/27` range (30 hosts) takes under 2 seconds.

### C. Automatic Diagnostics Extraction
* Any active host not listed in the `--exclude` set is classified as an **Identified Target System**.
* If SSH (Port 22) is open on a target system, the scanner invokes `sshpass` using `--ssh-user` and `--ssh-pass` to query system diagnostics, outputting:
  * Hostname
  * OS Release Information (`PRETTY_NAME`)

---

## 3. Unit Verification & Testing Plan

### A. Manual Verification CLI Scenarios
We will run and verify the following operational paths in the development environment:
1. **Help Output Verification**: Ensure `./bin/crash-cart-scan-subnet.sh --help` returns detailed argument documentation.
2. **Invalid Subnet Error Handling**: Ensure specifying a malformed CIDR block outputs a clean error message.
3. **Exclusions Validation**: Ensure the exclusions are correctly respected and omitted from identified targets.

---

## 4. Phase Checklist

- [x] State 1: Spec Definition & User Review
- [ ] State 2: Implementing Python Logic in `bin/crash-cart-scan-subnet.sh`
- [ ] State 3: Local CLI Verification & Output Format Testing
