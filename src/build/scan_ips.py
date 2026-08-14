#!/usr/bin/env python3
import os
import sys
import argparse
import ipaddress
import subprocess
import json

def log_info(msg):
    print(f"[-] [GDC-IP-Scanner] {msg}")

def log_warn(msg):
    print(f"[!] [GDC-IP-Scanner] WARNING: {msg}")

def get_local_ips(interface):
    try:
        res = subprocess.run(["ip", "-o", "-4", "addr", "show", "dev", interface], capture_output=True, text=True)
        ips = []
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                ip = parts[3].split('/')[0]
                ips.append(ip)
        return ips
    except Exception:
        return []

def is_ip_taken(ip, interface):
    local_ips = get_local_ips(interface)
    
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
    if ip not in local_ips:
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

def expand_range(ip_range):
    try:
        start_str, end_str = ip_range.split('-')
        start_ip = ipaddress.IPv4Address(start_str.strip())
        end_ip = ipaddress.IPv4Address(end_str.strip())
        
        ips = []
        for ip_int in range(int(start_ip), int(end_ip) + 1):
            ips.append(str(ipaddress.IPv4Address(ip_int)))
        return ips
    except Exception as e:
        log_warn(f"Failed to expand IP range {ip_range}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="GDC IP Verification Scanner")
    parser.add_argument("--interface", required=True, help="Network interface to scan on")
    parser.add_argument("--config", required=True, help="Path to gdc.fact JSON file")
    
    # Kept for backward compatibility with existing calls if any
    parser.add_argument("--cidr", default="", help=argparse.SUPPRESS)
    parser.add_argument("--fallback", default="", help=argparse.SUPPRESS)
    parser.add_argument("--output", default="", help=argparse.SUPPRESS)
    parser.add_argument("--machine-cidr", default="", help=argparse.SUPPRESS)
    parser.add_argument("--k8s-cidr", default="", help=argparse.SUPPRESS)
    
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"[!] Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"[!] Failed to parse JSON config: {e}", file=sys.stderr)
        sys.exit(1)

    cluster = config.get("cluster", {})
    networking = cluster.get("networking", {})
    network = config.get("network", {})

    must_be_free = []
    if "cluster_ingress" in networking:
        must_be_free.append(networking["cluster_ingress"])
        
    if "cluster_vip" in networking:
        must_be_free.append(networking["cluster_vip"])
        
    if "cluster_lb_range" in networking:
        must_be_free.extend(expand_range(networking["cluster_lb_range"]))
        
    mgmt = network.get("management_network", {})
    if not mgmt.get("dhcp_v4", True) and "ip_cidr" in mgmt:
        try:
            ip = mgmt.get("ip_cidr", "").split('/')[0]
            if ip: must_be_free.append(ip)
        except Exception:
            pass

    must_be_taken = []
    k8s = network.get("cluster_network", {})
    if not k8s.get("dhcp_v4", True) and "gateway" in k8s:
        must_be_taken.append(k8s["gateway"])
        
    if not mgmt.get("dhcp_v4", True) and "gateway" in mgmt:
        must_be_taken.append(mgmt["gateway"])

    errors = 0

    log_info(f"Checking IPs that must be FREE on interface {args.interface}...")
    for ip in set(must_be_free):
        if not ip:
            continue
        log_info(f"Scanning {ip}...")
        if is_ip_taken(ip, args.interface):
            log_warn(f"[ERROR] IP {ip} is taken but it should be free!")
            errors += 1
        else:
            log_info(f"[+] {ip} is free.")

    log_info(f"Checking IPs that must be TAKEN on interface {args.interface}...")
    for ip in set(must_be_taken):
        if not ip:
            continue
        log_info(f"Scanning {ip}...")
        if not is_ip_taken(ip, args.interface):
            log_warn(f"[ERROR] Gateway IP {ip} is NOT responding!")
            errors += 1
        else:
            log_info(f"[+] {ip} is active/resolving.")

    if errors > 0:
        log_warn(f"Validation failed with {errors} errors.")
        sys.exit(1)
    else:
        log_info("[x] SUCCESS: All IPs validated successfully.")

if __name__ == "__main__":
    main()
