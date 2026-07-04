# GDC Dynamic IP Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a robust Python 3 dynamic IP scanner utilizing `arp-scan` with randomized splay jitter and 5-pass verification to eliminate IP conflicts and boot-time race conditions, backed by comprehensive unit tests.

**Architecture:** A standalone Python script `scan_ips.py` parses a CIDR range, executes 5 jittered validation passes using `arp-scan`/`arping`/`ping` + robust `ip neigh` parsing, and writes the selected IP to `/tmp/allocated_ips.env`.

**Tech Stack:** Python 3, Shell/Bash, Jinja2 (autoinstall), Ansible.

---

### File Structure Changes

- Create: `src/build/scan_ips.py` (The main scanning script)
- Create: `test/test_ip_scanner.py` (Unit tests for the scanner)
- Modify: `src/build/templates/user-data.j2` (Integrate scanner and package seeding)
- Modify: `src/ansible/vars/all.yml` (Add net-tools and arp-scan to gdc_core_packages)
- Modify: `src/build/build.env` (Add net-tools and arp-scan to POST_INSTALL_PACKAGES)

---

### Task 1: Package List Seeding Configuration

**Files:**
- Modify: `src/build/build.env:180-181`
- Modify: `src/ansible/vars/all.yml:8-31`

- [ ] **Step 1: Add net-tools and arp-scan to build.env**
  Replace `POST_INSTALL_PACKAGES="git"` with `POST_INSTALL_PACKAGES="git net-tools arp-scan"`.

- [ ] **Step 2: Add net-tools and arp-scan to gdc_core_packages inside vars/all.yml**
  Add the packages to the `gdc_core_packages` YAML list to ensure they are installed and maintained by GDC Ansible suites.

- [ ] **Step 3: Commit Task 1**
  ```bash
  git add src/build/build.env src/ansible/vars/all.yml
  git commit -m "feat(build): seed net-tools and arp-scan into core package configurations"
  ```

---

### Task 2: Implement the Dynamic IP Scanner Script

**Files:**
- Create: `src/build/scan_ips.py`

- [ ] **Step 1: Write the complete `scan_ips.py` file**
  Create `/d/projects/google/gdc-disk-provisioner/src/build/scan_ips.py` with executable permissions and the following robust code:

```python
#!/usr/bin/env python3
import os
import sys
import argparse
import ipaddress
import subprocess
import random
import time

def log_info(msg):
    print(f"[-] [GDC-IP-Scanner] {msg}")

def log_warn(msg):
    print(f"[!] [GDC-IP-Scanner] WARNING: {msg}")

def is_ip_taken(ip, interface):
    # 1. ARP Scan
    try:
        res = subprocess.run(["arp-scan", "-I", interface, "--timeout=500", ip], capture_output=True, text=True)
        if res.returncode == 0 and ip in res.stdout:
            # Check if there is an actual MAC address mapped in stdout
            lines = res.stdout.splitlines()
            for line in lines:
                if line.startswith(ip) and len(line.split()) >= 2:
                    log_warn(f"IP {ip} is taken (arp-scan response)")
                    return True
    except Exception:
        pass

    # 2. Arping Scan
    try:
        res = subprocess.run(["arping", "-c", "1", "-w", "1", "-I", interface, ip], capture_output=True, text=True)
        if res.returncode == 0:
            log_warn(f"IP {ip} is taken (arping response)")
            return True
    except Exception:
        pass

    # 3. ICMP Ping Scan
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", "-I", interface, ip], capture_output=True, text=True)
        # Standard ping in this environment returns 0 even on failure, so grep for rtt
        if "rtt" in res.stdout:
            log_warn(f"IP {ip} is taken (ICMP response)")
            return True
    except Exception:
        pass

    # 4. Check local neighbor cache table
    try:
        neigh_out = subprocess.getoutput(f"ip neigh show dev {interface} 2>/dev/null")
        for line in neigh_out.splitlines():
            if ip in line:
                if not any(state in line for state in ["FAILED", "INCOMPLETE"]):
                    log_warn(f"IP {ip} is taken (active neighbor cache entry: {line.strip()})")
                    return True
    except Exception:
        pass

    return False

def scan_network(cidr, interface, passes=5):
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        candidates = [str(ip) for ip in net.hosts()]
    except Exception as e:
        print(f"[!] Invalid CIDR network {cidr}: {e}", file=sys.stderr)
        sys.exit(2)

    if not candidates:
        print(f"[!] No valid host IPs in CIDR {cidr}", file=sys.stderr)
        sys.exit(2)

    log_info(f"Scanning CIDR {cidr} ({len(candidates)} candidates) on interface {interface} over {passes} passes...")
    
    # Track which IPs have been detected as taken during any of the passes
    taken_ips = set()

    for p in range(1, passes + 1):
        log_info(f"--- Pass {p} / {passes} ---")
        # Apply randomized splay jitter (1-5 seconds) before starting the pass to prevent boot race conditions
        sleep_time = random.uniform(1.0, 5.0)
        log_info(f"Applying randomized splay delay of {round(sleep_time, 2)}s...")
        time.sleep(sleep_time)

        # Check each candidate not already known to be taken
        for ip in candidates:
            if ip in taken_ips:
                continue
            if is_ip_taken(ip, interface):
                taken_ips.add(ip)

    # Return the first candidate that was never detected as taken in any of the passes
    for ip in candidates:
        if ip not in taken_ips:
            return ip

    return None

def main():
    parser = argparse.ArgumentParser(description="GDC Jittered Dynamic L2/L3 IP Scanner")
    parser.add_argument("--cidr", default="192.168.9.8/29", help="CIDR candidate pool network (default: 192.168.9.8/29)")
    parser.add_argument("--interface", required=True, help="Network interface to scan on")
    parser.add_argument("--fallback", default="192.168.9.14", help="Default fallback IP if all are taken (default: 192.168.9.14)")
    parser.add_argument("--output", default="/tmp/allocated_ips.env", help="Output file path (default: /tmp/allocated_ips.env)")
    args = parser.parse_args()

    # Validate that fallback IP is within the CIDR range to prevent configuration faults
    try:
        net = ipaddress.ip_network(args.cidr, strict=False)
        fallback_ip = ipaddress.ip_address(args.fallback)
        if fallback_ip not in net:
            print(f"[!] CRITICAL CONFIG ERROR: Fallback IP {args.fallback} is outside the CIDR scanning range {args.cidr}!", file=sys.stderr)
            sys.exit(3)
    except Exception as e:
        print(f"[!] Config Validation Error: {e}", file=sys.stderr)
        sys.exit(3)

    selected_ip = scan_network(args.cidr, args.interface, passes=5)

    if selected_ip:
        log_info(f"[x] SUCCESS: Allocated free IP {selected_ip}")
        allocated_suffix = selected_ip.split(".")[-1]
    else:
        log_warn(f"All IP slots in range {args.cidr} are occupied! Falling back to safety IP {args.fallback}")
        selected_ip = args.fallback
        allocated_suffix = selected_ip.split(".")[-1]

    # Write environment output file
    try:
        with open(args.output, "w") as f:
            f.write(f"ALLOC_SUFFIX={allocated_suffix}\n")
            f.write(f"MACHINE_IP={selected_ip}\n")
            f.write(f"K8S_IP=192.168.109.{allocated_suffix}\n")
            f.write(f"MACHINE_IP_CIDR=192.168.9.8/24\n")
            f.write(f"K8S_IP_CIDR=192.168.109.8/24\n")
        log_info(f"Dynamic IP allocation written to {args.output}")
    except Exception as e:
        print(f"[!] Failed to write output env file: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make the script executable**
  Run: `chmod +x src/build/scan_ips.py`

- [ ] **Step 3: Commit Task 2**
  ```bash
  git add src/build/scan_ips.py
  git commit -m "feat(build): implement dynamic splay IP scanner utility"
  ```

---

### Task 3: Implement Unit Tests for the IP Scanner

**Files:**
- Create: `test/test_ip_scanner.py`

- [ ] **Step 1: Write the test suite**
  Create `/d/projects/google/gdc-disk-provisioner/test/test_ip_scanner.py` with full unittest mock assertions:

```python
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import ipaddress

# Add src/build directory to python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/build')))
import scan_ips

class TestGDCIPScanner(unittest.TestCase):

    @patch('time.sleep', return_value=None) # Fast execution by mocking sleep splay
    @patch('subprocess.run')
    @patch('subprocess.getoutput')
    def test_successful_allocation_when_some_ips_taken(self, mock_getoutput, mock_run, mock_sleep):
        # Setup mocks
        # Candidate range: .8 to .15. Assume .8 and .10 are taken, so .9 should be selected.
        
        def mock_subprocess_run(args, **kwargs):
            mock_res = MagicMock()
            target_ip = args[-1]
            if target_ip in ["192.168.9.8", "192.168.9.10"]:
                mock_res.returncode = 0
                mock_res.stdout = f"{target_ip}  00:11:22:33:44:55\n"
            else:
                mock_res.returncode = 1
                mock_res.stdout = ""
            return mock_res

        mock_run.side_effect = mock_subprocess_run
        mock_getoutput.return_value = "" # No neighbors

        # Run scanner on CIDR
        selected_ip = scan_ips.scan_network("192.168.9.8/29", "enp1s0", passes=2)
        
        self.assertEqual(selected_ip, "192.168.9.9")

    @patch('time.sleep', return_value=None)
    @patch('subprocess.run')
    @patch('subprocess.getoutput')
    def test_fallback_when_all_ips_taken(self, mock_getoutput, mock_run, mock_sleep):
        # GIVEN all candidates in 192.168.9.8/29 are taken
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "192.168.9.8  00:11:22:33:44:55\n" # returns responses for any IP queried
        mock_run.return_value = mock_res
        mock_getoutput.return_value = ""

        # Run scanner
        selected_ip = scan_ips.scan_network("192.168.9.8/29", "enp1s0", passes=1)
        
        self.assertIsNone(selected_ip)

    def test_fallback_ip_outside_cidr_range_validation(self):
        # Validate that system exits with status 3 when fallback IP is outside the CIDR scanning range
        with patch('sys.argv', ['scan_ips.py', '--cidr', '192.168.9.8/29', '--fallback', '192.168.9.254', '--interface', 'enp1s0']):
            with self.assertRaises(SystemExit) as cm:
                scan_ips.main()
            self.assertEqual(cm.exception.code, 3)

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run unit tests**
  Run: `python3 -m unittest test/test_ip_scanner.py -v`
  Expected: All tests pass.

- [ ] **Step 3: Commit Task 3**
  ```bash
  git add test/test_ip_scanner.py
  git commit -m "test(build): add comprehensive unit tests for splay IP scanner"
  ```

---

### Task 4: Integrate the Scanner into autoinstall user-data

**Files:**
- Modify: `src/build/templates/user-data.j2:30-33` and `src/build/templates/user-data.j2:149-197`

- [ ] **Step 1: Add net-tools and arp-scan packages to Subiquity autoinstall block**
  In `/d/projects/google/gdc-disk-provisioner/src/build/templates/user-data.j2`, append `- net-tools` and `- arp-scan` under `packages:`.

- [ ] **Step 2: Replace manual scanning bash loop with python scanner invocation**
  In `src/build/templates/user-data.j2`, replace the old inline Bash scanning task (lines 149-197) with the python executable wrapper:

```yaml
      echo "=============================================================================="
      echo "[GDC-INSTALL-GOAL] Starting Task: Scanning for free Machine & Kubernetes IPs"
      echo "=============================================================================="
      PHYS_IFACE=$(ls /sys/class/net | grep -E '^e' | head -n 1 || echo "eth0")
      
      # Ensure arp-scan and net-tools are dynamically bootstrapped in live environment (connected mode)
      if ! command -v arp-scan &>/dev/null; then
        echo "[-] Sideloading net-tools & arp-scan packages in live environment..."
        apt-get update &>/dev/null && apt-get install -y arp-scan net-tools &>/dev/null || true
      fi

      # Invoke the robust splay python IP scanner
      python3 /cdrom/custom-data/scan_ips.py --cidr "192.168.9.8/29" --interface "${PHYS_IFACE}" --fallback "192.168.9.14" --output "/tmp/allocated_ips.env"
```

- [ ] **Step 3: Commit Task 4**
  ```bash
  git add src/build/templates/user-data.j2
  git commit -m "feat(autoinstall): integrate dynamic python IP scanner and bootstrap layers"
  ```

---

### Task 5: Copy scanner script into ISO remaster custom-data directory

**Files:**
- Modify: `src/build/remaster.sh` (Verify `scan_ips.py` is copied to `/custom-data/`)

- [ ] **Step 1: Inspect `src/build/remaster.sh` copy targets**
  Read `src/build/remaster.sh` around where files are copied from repository to the ISO chroot/custom-data directory. Ensure `/custom-data/*` includes our new `scan_ips.py`.
  If we copy files dynamically, ensure it is covered.

- [ ] **Step 2: Commit Task 5**
  ```bash
  git add src/build/remaster.sh
  git commit -m "chore(build): ensure scan_ips.py is packaged into ISO remaster custom-data"
  ```
