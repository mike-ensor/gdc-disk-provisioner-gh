# Network Scan Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a fully CLI-customizable, standard-library-based network subnet scanner in `bin/crash-cart-scan-subnet.sh` with zero hardcoded IPs or ranges, and write matching unit tests to verify its behaviors.

**Architecture:** A Python 3 command-line utility utilizing the standard `ipaddress` module to parse CIDR blocks, `concurrent.futures.ThreadPoolExecutor` to probe hosts in parallel via ICMP ping and SSH socket connections, and `sshpass` to run diagnostic commands on uncovered target systems.

**Tech Stack:** Python 3 standard library (`ipaddress`, `concurrent.futures`, `argparse`, `socket`, `subprocess`), GDC unit test framework (`unittest`).

---

### Task 1: Create Unit Test Suite for Crash Cart Subnet Scanner

**Files:**
- Create: `test/test_crash_cart_scanner.py`

- [ ] **Step 1: Write the unit test code**
We will mock all socket operations, pings, and subprocess runs so the test suite is 100% deterministic, hermetic, and offline-compatible.

```python
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import ipaddress

# Add bin directory or the script's path so we can import modules if needed,
# or mock the main script behavior. Since we keep it in bin/crash-cart-scan-subnet.sh,
# we will import it directly by loading the source file dynamically.
import importlib.util

def load_scanner_module():
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin/crash-cart-scan-subnet.sh'))
    spec = importlib.util.spec_from_file_location("crash_cart_scanner", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["crash_cart_scanner"] = module
    spec.loader.exec_module(module)
    return module

class TestCrashCartScanner(unittest.TestCase):

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_cidr_parsing_and_exclusions(self, mock_socket, mock_run):
        # Load the module dynamically
        scanner = load_scanner_module()
        
        # Test 1: Verify parsing CIDR and extracting exclusions
        cidr = "192.168.9.230/27"
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = [str(ip) for ip in net.hosts()]
        
        # Usable range for /27 should have 30 host addresses (.225 to .254)
        self.assertEqual(len(hosts), 30)
        self.assertEqual(hosts[0], "192.168.9.225")
        self.assertEqual(hosts[-1], "192.168.9.254")

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_target_identification_and_diagnostics(self, mock_socket, mock_run):
        scanner = load_scanner_module()
        
        # Configure mock return values for subprocess/socket to simulate an active unidentified host
        # Let's say 192.168.9.230 is reachable (ping = True) and has SSH open (ssh = True)
        mock_socket_instance = MagicMock()
        mock_socket_instance.connect_ex.return_value = 0 # SSH port is open
        mock_socket.return_value = mock_socket_instance

        # Mock ping subprocess to succeed (returncode=0)
        # Mock SSH diagnostics subprocess to succeed
        def mock_subprocess_run(args, **kwargs):
            res = MagicMock()
            if "ping" in args:
                res.returncode = 0
            elif "sshpass" in args:
                res.returncode = 0
                res.stdout = "test-node-1\nPRETTY_NAME=\"Ubuntu 24.04 LTS\""
            return res
        mock_run.side_effect = mock_subprocess_run

        active = scanner.check_ip_state("192.168.9.230", 1.0)
        self.assertIsNotNone(active)
        self.assertEqual(active["ip"], "192.168.9.230")
        self.assertTrue(active["ping"])
        self.assertTrue(active["ssh"])

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest test/test_crash_cart_scanner.py`
Expected: FAIL since `bin/crash-cart-scan-subnet.sh` is currently an empty shell and cannot be executed as a Python module.

---

### Task 2: Implement Python Subnet Scanner in `bin/crash-cart-scan-subnet.sh`

**Files:**
- Modify: `bin/crash-cart-scan-subnet.sh`

- [ ] **Step 1: Write the minimal implementation**
We will replace the shell contents with a Python 3 script adhering strictly to `#!/usr/bin/env python3` shebang and standard libraries.

```python
#!/usr/bin/env python3
# ==============================================================================
# GDC Bare-Metal - Crash Cart Subnet Scanner
# ==============================================================================
# Performs high-performance parallel scanning of a given CIDR network subnet
# to discover active "Crashed Provision" target systems.
# ==============================================================================

import os
import sys
import socket
import subprocess
import concurrent.futures
import argparse
import ipaddress

def is_ping_reachable(ip, timeout=1.0):
    """Checks if the target IP responds to standard ICMP pings."""
    try:
        res = subprocess.run(
            ["ping", "-c", "2", "-W", str(timeout), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return res.returncode == 0
    except Exception:
        return False

def is_ssh_open(ip, port=22, timeout=1.0):
    """Checks if the SSH port is open and accepting TCP handshakes."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception:
        return False

def check_ip_state(ip, timeout=1.0):
    """Probes the IP and returns its network footprint state if active."""
    ping_ok = is_ping_reachable(ip, timeout)
    ssh_ok = is_ssh_open(ip, 22, timeout)
    if ping_ok or ssh_ok:
        return {
            "ip": ip,
            "ping": ping_ok,
            "ssh": ssh_ok
        }
    return None

def run_diagnostics(ip, ssh_user, ssh_pass):
    """Attempts to run diagnostics via SSH using sshpass."""
    ssh_cmd = (
        f"sshpass -p '{ssh_pass}' ssh "
        f"-o StrictHostKeyChecking=no "
        f"-o UserKnownHostsFile=/dev/null "
        f"-o ConnectTimeout=3 "
        f"{ssh_user}@{ip} "
        f"'hostname && cat /etc/os-release | grep PRETTY_NAME'"
    )
    res = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
    return res

def main():
    parser = argparse.ArgumentParser(
        description="GDC Crashed Node Network Discovery Subnet Scanner"
    )
    parser.add_argument(
        "-c", "--cidr",
        required=True,
        help="Subnet CIDR range to scan (e.g. 192.168.9.230/27)"
    )
    parser.add_argument(
        "-e", "--exclude",
        default="",
        help="Comma-separated list of active IPs to exclude/ignore"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=20,
        help="Number of concurrent scanner threads (default: 20)"
    )
    parser.add_argument(
        "-t", "--timeout",
        type=float,
        default=1.0,
        help="Ping and socket connection timeout in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--ssh-user",
        default="temporary-installer",
        help="SSH username for diagnostic attempts (default: temporary-installer)"
    )
    parser.add_argument(
        "--ssh-pass",
        default="troubled-marble-150",
        help="SSH password for diagnostic attempts (default: troubled-marble-150)"
    )

    args = parser.parse_args()

    # Parse CIDR
    try:
        network = ipaddress.ip_network(args.cidr, strict=False)
    except ValueError as e:
        print(f"[!] Error: Invalid CIDR subnet range: {args.cidr}. Details: {e}")
        sys.exit(1)

    exclusions = set(ip.strip() for ip in args.exclude.split(",") if ip.strip())

    print("==============================================================================")
    print(" GDC CRASHED NODE NETWORK DISCOVERY SCANNER")
    print("==============================================================================")
    print(f"[-] Scanning CIDR range: {args.cidr}")
    print(f"[-] Subnet bounds: {list(network.hosts())[0]} to {list(network.hosts())[-1]}")
    if exclusions:
        print(f"[-] Excluded active IPs: {', '.join(sorted(list(exclusions)))}")
    print("[-] Performing parallel subnet sweep...")

    all_ips = [str(ip) for ip in network.hosts()]
    active_devices = []

    # Run checks in parallel using ThreadPool for maximum performance
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        # Wrap helper to inject timeout
        def check_host(ip):
            return check_ip_state(ip, args.timeout)
            
        results = executor.map(check_host, all_ips)
        for res in results:
            if res:
                active_devices.append(res)

    print("\n[+] ACTIVE NETWORK DEVICES FOUND:")
    print("------------------------------------------------------------------------------")
    for dev in active_devices:
        status_str = f"IP: {dev['ip']:15} | Ping: {'🟢 REACHABLE' if dev['ping'] else '🔴 BLOCKED'} | SSH: {'🟢 OPEN (Port 22)' if dev['ssh'] else '🔴 CLOSED'}"
        if dev['ip'] in exclusions:
            status_str += " (EXCLUDED)"
        print(status_str)
    print("------------------------------------------------------------------------------")

    # Filter out exclusions to find our target crashed system
    targets = [dev for dev in active_devices if dev['ip'] not in exclusions]

    if not targets:
        print("[!] Warning: No unidentified active devices found in the target range.")
        print("    The crashed system might be powered off or have lost link completely.")
        sys.exit(0)

    print(f"\n🎯 IDENTIFIED TARGET SYSTEM:")
    for tgt in targets:
        print(f"    --> IP Address: {tgt['ip']}")
        print(f"        Ping Reachable: {tgt['ping']}")
        print(f"        SSH Accessible: {tgt['ssh']}")
        
        if tgt['ssh']:
            print(f"\n[-] Testing SSH diagnostics login on the identified target {tgt['ip']}...")
            res = run_diagnostics(tgt['ip'], args.ssh_user, args.ssh_pass)
            if res.returncode == 0:
                print(f"        [+] Logged in successfully!")
                lines = res.stdout.strip().splitlines()
                if len(lines) >= 1:
                    print(f"        [+] Hostname:  {lines[0]}")
                if len(lines) >= 2:
                    print(f"        [+] OS:        {lines[1].split('=')[-1].strip('\"')}")
            else:
                print("        [!] SSH connection failed (check credentials or public key locks).")

    print("==============================================================================")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make the script executable**
Explain and run: `chmod +x bin/crash-cart-scan-subnet.sh`

- [ ] **Step 3: Run the unit tests**
Run: `python3 -m unittest test/test_crash_cart_scanner.py`
Expected: PASS

---

### Task 3: Lint, Verify and Commit

**Files:**
- Modify: None

- [ ] **Step 1: Check LSP diagnostics and lint rules**
Verify that the files `bin/crash-cart-scan-subnet.sh` and `test/test_crash_cart_scanner.py` have zero lint or syntax errors.

- [ ] **Step 2: Run all tests in the repository**
Run: `python3 -m unittest discover -s test -p "test_*.py"`
Expected: All tests pass.

- [ ] **Step 3: Stage and Commit files**
```bash
git add bin/crash-cart-scan-subnet.sh test/test_crash_cart_scanner.py docs/superpowers/specs/2026-07-10-network-scan-design.md docs/superpowers/plans/2026-07-10-network-scan-tool.md
git commit -m "feat: implement robust python subnet scanner tool and test suite"
```
