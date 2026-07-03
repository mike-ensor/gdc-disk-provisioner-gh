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
    parser.add_argument("--machine-cidr", default="192.168.9.11/24", help="Baseline machine subnet CIDR")
    parser.add_argument("--k8s-cidr", default="192.168.109.8/24", help="Baseline kubernetes subnet CIDR")
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
            f.write(f"MACHINE_IP_CIDR={args.machine_cidr}\n")
            f.write(f"K8S_IP_CIDR={args.k8s_cidr}\n")
        log_info(f"Dynamic IP allocation written to {args.output}")
    except Exception as e:
        print(f"[!] Failed to write output env file: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
