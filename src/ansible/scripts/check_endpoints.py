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
from functools import partial
import json
import socket
import sys
import time
from typing import Optional
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

def check_target(target: dict, timeout: float = 2.0) -> dict:
    test_name = target["test_name"]
    domain = target["domain"]
    port = target.get("port", 443)
    service_label = target.get("service_label")
    url = target.get("url")

    t0 = time.time()
    dns_resolved = False
    resolved_ip = None
    tcp_connected = False
    err_msg = ""

    try:
        ip = socket.gethostbyname(domain)
        dns_resolved = True
        resolved_ip = ip
        with socket.create_connection((ip, port), timeout=timeout):
            tcp_connected = True
    except Exception as e:
        err_msg = str(e)

    duration_ms = int((time.time() - t0) * 1000)

    if tcp_connected:
        status = "PASS"
        if service_label:
            notes = f"{service_label} ({domain}:{port}): Resolved to {resolved_ip} and connected via TCP/{port} successfully."
            remediation_hint = f"Endpoint {domain}:{port} is reachable."
        else:
            notes = f"Resolved to {resolved_ip} and connected via TCP/{port} successfully."
            remediation_hint = f"Check DNS server resolution and outbound firewall rules for {domain}:{port}."
    elif dns_resolved:
        status = "WARN"
        if service_label:
            notes = f"{service_label} ({domain}:{port}): DNS resolved to {resolved_ip}, but TCP/{port} connection failed: {err_msg} (Host unreachable or port {port} closed)."
            remediation_hint = f"Check network routing, default gateway reachability, and firewall rules for {resolved_ip}:{port} ({domain})."
        else:
            notes = f"DNS resolved to {resolved_ip}, but TCP/{port} connection failed: {err_msg}"
            remediation_hint = f"Check DNS server resolution and outbound firewall rules for {domain}:{port}."
    else:
        status = "WARN"
        if service_label:
            notes = f"{service_label} ({domain}:{port}): DNS resolution failed: {err_msg}. Host '{domain}' could not be resolved by DNS nameservers or /etc/hosts."
            remediation_hint = f"Verify DNS nameserver configuration or ensure '{domain}' is mapped in /etc/hosts (via src/build/add-hosts)."
        else:
            notes = f"DNS resolution failed: {err_msg}"
            remediation_hint = f"Check DNS server resolution and outbound firewall rules for {domain}:{port}."

    meta = {
        "domain": domain,
        "port": port,
        "dns_resolved": dns_resolved,
        "resolved_ip": resolved_ip,
        "tcp_connected": tcp_connected
    }
    if url:
        meta["url"] = url
    if "service" in target:
        meta["service"] = target["service"]

    return {
        "test_name": test_name,
        "category": "network",
        "status": status,
        "severity": "WARNING",
        "notes": notes,
        "remediation_hint": remediation_hint,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": duration_ms,
        "meta": meta
    }

def parse_endpoint_url(url_str: str, service_name: str, test_name: str) -> Optional[dict]:
    if not url_str or not url_str.strip():
        return None
    try:
        parsed = urlparse(url_str.strip())
        if not parsed.hostname:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return {
            "test_name": test_name,
            "service_label": service_name,
            "service": test_name.replace("endpoint_connect_", ""),
            "domain": parsed.hostname,
            "port": port,
            "url": url_str.strip(),
        }
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser(description="Check Google and GDC endpoint connectivity")
    parser.add_argument("--companion-url", help="GDC Companion URL to include in checks")
    parser.add_argument("--step-ca-url", help="Step CA URL to include in checks")
    parser.add_argument("--timeout", type=float, default=2.0, help="Socket connect timeout in seconds")
    parser.add_argument("--max-workers", type=int, default=12, help="Thread pool worker count")
    args = parser.parse_args()

    targets = []

    # 1. Specialized GDC Infrastructure endpoints (Companion & Step CA)
    companion_target = parse_endpoint_url(args.companion_url, "GDC Companion", "endpoint_connect_companion")
    if companion_target:
        targets.append(companion_target)

    step_ca_target = parse_endpoint_url(args.step_ca_url, "Step CA", "endpoint_connect_step_ca")
    if step_ca_target:
        targets.append(step_ca_target)

    # 2. Standard Google API and container registry endpoints
    for domain in DEFAULT_DOMAINS:
        targets.append({
            "test_name": f"endpoint_connect_{domain}",
            "domain": domain,
            "port": 443,
            "service_label": None,
            "url": None
        })

    checker = partial(check_target, timeout=args.timeout)
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        results = list(executor.map(checker, targets))

    print(json.dumps(results))

if __name__ == "__main__":
    main()
