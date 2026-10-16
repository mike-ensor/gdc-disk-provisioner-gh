#!/usr/bin/env python3

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# GDC Bootloader - Webhook Ingestion & Host Header Verification
# ==============================================================================
# Emulates Curtin/Subiquity logging webhooks against the GDC Companion gateway
# to verify Host-header-based virtual routing and test other custom headers.
# ==============================================================================

import urllib.request
import urllib.error
import json
import sys

# Default Companion configuration (resolves to 192.168.20.102 via /etc/hosts)
COMPANION_IP = "192.168.20.102"
COMPANION_HOST = "gdc-companion.gdc-labs.com"

# Simulated payload representing a Curtin installer event
PAYLOAD = {
    "name": "subiquity/test-emulated-event",
    "description": "Emulated logging webhook from verification script",
    "event_type": "start",
    "origin": "subiquity",
    "timestamp": 1784435894
}

def test_endpoint(url, custom_headers=None):
    """Performs a HTTP POST request with an optional dictionary of custom headers."""
    headers_str = ", ".join(f"'{k}: {v}'" for k, v in (custom_headers or {}).items()) or "None"
    print(f"[-] Posting to: {url}")
    print(f"    Custom Headers: {headers_str}")
    
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    
    # Inject any custom headers (such as Host or auth tokens)
    if custom_headers:
        for key, val in custom_headers.items():
            req.add_header(key, val)
            
    try:
        encoded_data = json.dumps(PAYLOAD).encode("utf-8")
        with urllib.request.urlopen(req, data=encoded_data, timeout=3) as res:
            print(f"    [+] SUCCESS: HTTP {res.status}")
            print(f"    [+] Response: {res.read().decode('utf-8').strip()}")
    except urllib.error.HTTPError as e:
        print(f"    [!] FAILED: HTTP {e.code} ({e.reason})")
    except Exception as e:
        print(f"    [!] Connection Error: {e}")
    print("-" * 80)

def main():
    print("==============================================================================")
    # 1. Standard Hostname Routing (Succeeds via DNS/hosts mapping)
    test_endpoint(
        url=f"http://{COMPANION_HOST}/v1/install-logs/secure?client_cert_cn=gdc-provision-0.1.94"
    )

    # 2. Direct IP Routing without Host Header (Fails with 404 from Nginx)
    test_endpoint(
        url=f"http://{COMPANION_IP}/v1/install-logs/secure?client_cert_cn=gdc-provision-0.1.94"
    )

    # 3. Direct IP Routing with Custom Host Header (Succeeds - Emulates Option A)
    test_endpoint(
        url=f"http://{COMPANION_IP}/v1/install-logs/secure?client_cert_cn=gdc-provision-0.1.94",
        custom_headers={"Host": COMPANION_HOST}
    )

    # 4. Direct IP Routing with Multi-Header Injection (Succeeds)
    test_endpoint(
        url=f"http://{COMPANION_IP}/v1/install-logs/secure?client_cert_cn=gdc-provision-0.1.94",
        custom_headers={
            "Host": COMPANION_HOST,
            "X-Client-Cert-CN": "gdc-provision-0.1.94",
            "X-GDC-Custom-Token": "test-token-12345"
        }
    )
    print("==============================================================================")

if __name__ == "__main__":
    main()
