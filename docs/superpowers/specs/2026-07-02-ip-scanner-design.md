# Design Spec: Robust Dynamic IP Scanning & Collision Avoidance

## 1. Abstract
This specification defines the implementation of a robust, testable, and deterministic IP scanner tool (`scan_ips.py`) and its integration into the Google Distributed Cloud (GDC) Bare-Metal offline bootloader. 

By leveraging `arp-scan`, `arping`, and robust kernel neighbor table parsing, the tool ensures that multiple booting nodes can dynamically select a free IP address from a target CIDR block while preventing race conditions via randomized splay delays and multi-pass verification.

---

## 2. Core Enhancements

### A. Core Package Pre-Seeding
To support the use of `arp-scan` and `net-tools` both during first-boot and late-provisioning:
1. **`build.env`**: Append `arp-scan` and `net-tools` to `POST_INSTALL_PACKAGES`.
2. **`vars/all.yml`**: Add `arp-scan` and `net-tools` to the `gdc_core_packages` list.
3. **`user-data.j2`**: Add `arp-scan` and `net-tools` to the autoinstall `packages` section.

### B. Bootstrapping during Early Install
Since the `early-commands` phase executes before packages are officially installed in the target, the installer will attempt to dynamically bootstrap `arp-scan` and `net-tools` in the live environment if internet access is available, fallback-gracefully using native `ping` and corrected `ip neigh` parsing if offline.

### C. The Dynamic IP Scanner Script (`src/build/scan_ips.py`)
A modular Python 3 script responsible for IP selection:
* **CIDR Input Validation**: Parses the target CIDR (e.g. `192.168.9.8/29`) using Python's native `ipaddress` module.
* **Jittered 5-Pass Scanning**:
  * Runs 5 consecutive scanning passes over the candidates (hosts within the CIDR range).
  * Applies a randomized sleep interval between `1.0` and `5.0` seconds before each pass to eliminate race conditions between concurrently booting hosts.
* **Layer 2 & Layer 3 Collision Verification**:
  * Runs `arp-scan` if available.
  * Runs `arping` on the target interface.
  * Runs standard `ping` checks.
  * Robustly parses `ip neigh` state, discarding `FAILED` or `INCOMPLETE` cache entries and only marking the IP as taken if it has active ARP bindings (`REACHABLE`, `STALE`, `DELAY`, `PROBE`).
* **Output Generation**: Writes the resolved metadata directly to `/tmp/allocated_ips.env`.

---

## 3. Unit Verification & Test Plan

A complete unit test suite `test/test_ip_scanner.py` will verify:
1. **Successful Allocation**: Selecting the first free IP inside the range when some IPs are taken.
2. **Outside Subnet Check**: Throwing a clean validation error if the static fallback/target IP does not reside in the scanned CIDR block.
3. **Worst-case Fallback**: Gracefully falling back to `.14` (safety default) if all IPs are fully saturated.

---

## 4. Phase Checklist

- [x] State 1: Spec Definition & User Review
- [ ] State 2: Writing & Testing `scan_ips.py`
- [ ] State 3: Sideloading configuration files (`build.env`, `all.yml`, `user-data.j2`)
- [ ] State 4: Packaging and Building `0.1.14-debug` via `./build-iso.sh`
- [ ] State 5: Bootimus Registration & Deploy Verification
