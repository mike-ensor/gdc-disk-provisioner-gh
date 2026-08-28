#!/usr/bin/env python3

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
        return

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
