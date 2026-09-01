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
# GDC Endpoints Connectivity & DNS Preflight Checker
# ==============================================================================
# Performs high-speed concurrent DNS resolution and TCP port 443 socket checks
# across mandatory Google APIs, container registries, and companion endpoints.
# ==============================================================================

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import sys
import time
from urllib.parse import urlparse

DEFAULT_DOMAINS = [
    "accounts.google.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "connectgateway.googleapis.com",
    "containerregistry.googleapis.com",
    "gkeconnect.googleapis.com",
    "gkehub.googleapis.com",
    "gkeonprem.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "gkeonprem.mtls.googleapis.com",
    "oauth2.googleapis.com",
    "securetoken.googleapis.com",
    "servicecontrol.googleapis.com",
    "serviceusage.googleapis.com",
    "stackdriver.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
    "www.googleapis.com",
    "gcr.io",
    "k8s.gcr.io",
    "logging.gdce.googleapis.com",
    "storage.gdce.googleapis.com",
]

def check_domain(domain: str) -> dict:
    t0 = time.time()
    dns_resolved = False
    resolved_ip = None
    tcp_connected = False
    err_msg = ""

    try:
        ip = socket.gethostbyname(domain)
        dns_resolved = True
        resolved_ip = ip
        with socket.create_connection((ip, 443), timeout=2.0):
            tcp_connected = True
    except Exception as e:
        err_msg = str(e)

    duration_ms = int((time.time() - t0) * 1000)

    if tcp_connected:
        status = "PASS"
        notes = f"Resolved to {resolved_ip} and connected via TCP/443 successfully."
    elif dns_resolved:
        status = "WARN"
        notes = f"DNS resolved to {resolved_ip}, but TCP/443 connection failed: {err_msg}"
    else:
        status = "WARN"
        notes = f"DNS resolution failed: {err_msg}"

    return {
        "test_name": f"endpoint_connect_{domain}",
        "category": "network",
        "status": status,
        "severity": "WARNING",
        "notes": notes,
        "remediation_hint": f"Check DNS server resolution and outbound firewall rules for {domain}:443.",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": duration_ms,
        "meta": {
            "domain": domain,
            "dns_resolved": dns_resolved,
            "resolved_ip": resolved_ip,
            "tcp_connected": tcp_connected
        }
    }

def main():
    parser = argparse.ArgumentParser(description="Check Google and GDC endpoint connectivity")
    parser.add_argument("--companion-url", help="GDC Companion URL to include in checks")
    parser.add_argument("--timeout", type=float, default=2.0, help="Socket connect timeout in seconds")
    parser.add_argument("--max-workers", type=int, default=12, help="Thread pool worker count")
    args = parser.parse_args()

    domains = list(DEFAULT_DOMAINS)
    if args.companion_url:
        try:
            parsed = urlparse(args.companion_url)
            if parsed.hostname and parsed.hostname not in domains:
                domains.append(parsed.hostname)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        results = list(executor.map(check_domain, domains))

    print(json.dumps(results))

if __name__ == "__main__":
    main()
