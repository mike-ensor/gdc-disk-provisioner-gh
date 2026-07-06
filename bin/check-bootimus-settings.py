#!/usr/bin/env python3
# ==============================================================================
# GDC Bootloader - Bootimus Boot Option Auditor
# ==============================================================================
# Connects to the Bootimus PXE server and validates that every registered Ubuntu
# image has autoinstall and nocloud parameters configured correctly, preventing
# the node installer from boot-looping or entering interactive console prompt.
# ==============================================================================

import os
import sys
import urllib.request
import urllib.parse
import json

# Add project src to path so we can reuse bootimus module methods
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/build')))
from bootimus import BOOTIMUS_API_HOST, BOOTIMUS_API_PORT, API_BASE, get_bootimus_credentials, api_request

def main():
    print("==============================================================================")
    print(" GDC BOOTIMUS INTERACTIVE-MODE PREVENTION AUDITOR")
    print("==============================================================================")

    # 1. Authenticate
    username, password = get_bootimus_credentials()
    print(f"[-] Authenticating with Bootimus at {BOOTIMUS_API_HOST}:{BOOTIMUS_API_PORT}...")
    try:
        login_res = api_request(
            f"{API_BASE}/login",
            method="POST",
            data={"username": username, "password": password}
        )
        token = login_res["data"]["token"]
        print("[+] Authentication successful.")
    except Exception as e:
        print(f"[!] Authentication failed: {e}")
        sys.exit(1)

    # 2. Fetch all images
    print("[-] Fetching all registered images from Bootimus...")
    try:
        images_res = api_request(f"{API_BASE}/images", token=token)
        images = images_res.get("data", [])
    except Exception as e:
        print(f"[!] Failed to fetch images: {e}")
        sys.exit(1)

    print(f"[+] Retrieved {len(images)} image records from database.")
    print("==============================================================================")
    print(f"{'IMAGE NAME':<40} | {'DISTRO':<10} | {'ENABLED':<7} | {'AUTOINSTALL':<11}")
    print("-" * 78)

    failures = 0
    total_ubuntu = 0

    for img in images:
        filename = img.get("filename", "")
        # Filter out subdirectories or tests inside the raw disk storage representation
        if not filename or "/iso/" in filename or "/extracted/" in filename or "tests/" in filename:
            continue
            
        distro = img.get("distro", "unknown")
        boot_method = img.get("boot_method", "unknown")
        boot_params = img.get("boot_params", "")
        enabled = img.get("enabled", False)

        # We are specifically concerned with Ubuntu OS images
        if distro == "ubuntu":
            total_ubuntu += 1
            has_autoinstall = "autoinstall" in boot_params
            has_ds = "ds=nocloud-net" in boot_params
            
            # Autoinstall is only healthy if both 'autoinstall' and the seed 'ds=nocloud-net' are present
            is_healthy = has_autoinstall and has_ds
            autoinstall_status = "YES" if is_healthy else "NO"
            
            if not is_healthy:
                autoinstall_status = "⚠️  MISSING"
                failures += 1

            enabled_str = "TRUE" if enabled else "FALSE"
            print(f"{filename:<40} | {distro:<10} | {enabled_str:<7} | {autoinstall_status:<11}")

            if not is_healthy:
                print(f"    [ALERT] Invalid boot params found:")
                print(f"            {boot_params}")
                print("-" * 78)

    print("==============================================================================")
    print(f"AUDIT SUMMARY:")
    print(f"  Total Ubuntu Images Checked: {total_ubuntu}")
    print(f"  Interactive Mode Vulnerable: {failures}")
    print("==============================================================================")

    if failures > 0:
        print("[!] Warning: Some Ubuntu images are missing non-interactive autoinstall parameters!")
        print("    These nodes could launch in interactive mode when PXE booted.")
        sys.exit(1)
    else:
        print("[x] SUCCESS: All Ubuntu/GDC images are locked in secure, non-interactive autoinstall mode!")
        sys.exit(0)

if __name__ == "__main__":
    main()
