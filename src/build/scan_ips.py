#!/usr/bin/env python3
import os
import sys
import argparse
import ipaddress
import subprocess
import random
import time
import re

def log_info(msg):
    print(f"[-] [GDC-IP-Scanner] {msg}")

def log_warn(msg):
    print(f"[!] [GDC-IP-Scanner] WARNING: {msg}")

def get_mac_address(interface):
    try:
        # Check /sys/class/net/<interface>/address directly (unprivileged ok)
        sys_path = f"/sys/class/net/{interface}/address"
        if os.path.exists(sys_path):
            with open(sys_path, 'r') as f:
                return f.read().strip()
    except Exception:
        pass
    # Fallback to ip link
    try:
        res = subprocess.run(["ip", "link", "show", interface], capture_output=True, text=True)
        if res.returncode == 0:
            match = re.search(r"link/ether\s+([0-9a-fA-F:]+)", res.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass
    # Safety default mock MAC
    return "00:00:00:00:00:00"

def calculate_preferred_ip(mac_addr, hosts):
    try:
        last_byte = int(mac_addr.split(":")[-1], 16)
    except Exception:
        last_byte = 0
    idx = last_byte % len(hosts)
    return hosts[idx]

def bind_defensive_ip(ip, interface):
    try:
        log_info(f"Applying defensive L2 IP reservation for {ip} on {interface}...")
        # Add a temporary /24 or /32 IP address alias to the interface
        # This forces the kernel to respond to any incoming ARP queries for this IP immediately
        res = subprocess.run(["ip", "addr", "add", f"{ip}/24", "dev", interface, "label", f"{interface}:gdc_temp"], capture_output=True, text=True)
        if res.returncode == 0:
            log_info(f"[+] Defensive L2 reservation locked successfully for {ip}.")
            return True
        else:
            log_warn(f"Failed to apply defensive L2 reservation: {res.stderr.strip()}")
    except Exception as e:
        log_warn(f"Defensive L2 reservation exception: {e}")
    return False

def is_ip_taken(ip, interface):
    # 1. ARP Scan
    try:
        res = subprocess.run(["arp-scan", "-I", interface, "--timeout=500", ip], capture_output=True, text=True)
        if res.returncode == 0 and ip in res.stdout:
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

def scan_network_hybrid(cidr, interface):
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = [str(ip) for ip in net.hosts()]
    except Exception as e:
        print(f"[!] Invalid CIDR network {cidr}: {e}", file=sys.stderr)
        sys.exit(2)

    if not hosts:
        print(f"[!] No valid host IPs in CIDR {cidr}", file=sys.stderr)
        sys.exit(2)

    mac_addr = get_mac_address(interface)
    log_info(f"Primary Interface: {interface} | MAC: {mac_addr}")

    # Compute preferred IP deterministically
    preferred_ip = calculate_preferred_ip(mac_addr, hosts)
    log_info(f"Deterministic preferred IP: {preferred_ip}")

    # Pass 1: Jitter and check the preferred IP
    sleep_time = random.uniform(1.0, 3.0)
    log_info(f"Applying randomized splay delay of {round(sleep_time, 2)}s...")
    time.sleep(sleep_time)

    if not is_ip_taken(preferred_ip, interface):
        # Claim immediately and reserve!
        bind_defensive_ip(preferred_ip, interface)
        return preferred_ip

    # Pass 2: Fallback Loop (Shuffle remaining and scan)
    log_warn(f"Preferred IP {preferred_ip} is already taken! Initiating randomized splay fallback check...")
    candidates = [ip for ip in hosts if ip != preferred_ip]
    random.shuffle(candidates)

    for ip in candidates:
        sleep_time = random.uniform(1.0, 3.0)
        log_info(f"Applying randomized splay delay of {round(sleep_time, 2)}s before checking {ip}...")
        time.sleep(sleep_time)

        if not is_ip_taken(ip, interface):
            # Claim immediately and reserve!
            bind_defensive_ip(ip, interface)
            return ip

    return None

def main():
    parser = argparse.ArgumentParser(description="GDC Jittered Hybrid IP Suffix Allocator")
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

    selected_ip = scan_network_hybrid(args.cidr, args.interface)

    if selected_ip:
        log_info(f"[x] SUCCESS: Allocated and reserved free IP {selected_ip}")
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
