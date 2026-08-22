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
from bootimus import BOOTIMUS_API_HOST, BOOTIMUS_API_PORT, API_BASE, get_bootimus_credentials, api_request, auto_heal_boot_params

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
        
        # Run self-healing audit to automatically restore any clobbered/disabled GDC image configs
        auto_heal_boot_params(token)
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
    print("==========================================================================================")
    print(f"{'IMAGE NAME':<40} | {'DISTRO':<10} | {'ENABLED':<7} | {'EXTRACTION':<11} | {'AUTOINSTALL':<11}")
    print("-" * 90)

    failures = 0
    total_ubuntu = 0

    for img in images:
        filename = img.get("filename", "")
        # Filter out subdirectories or tests inside the raw disk storage representation
        if not filename or "/iso/" in filename or "/extracted/" in filename or "tests/" in filename:
            continue
            
        distro = img.get("distro", "unknown")
        boot_params = img.get("boot_params", "")
        enabled = img.get("enabled", False)
        extracted = img.get("extracted", False)
        
        # Identify the group the image belongs to, safely handling unexpected structures
        group_data = img.get("group")
        if isinstance(group_data, dict):
            group_name = group_data.get("name")
        else:
            group_name = "ungrouped"
            
        group_name = str(group_name) if group_name is not None else "ungrouped"

        # Explicitly skip auditing images inside 'windows' and 'linux' groups
        # as these are typically non-GDC stock images that do not support autoinstall.
        if group_name.lower() in ["windows", "linux"]:
            continue

        # We are specifically concerned with Ubuntu OS images
        if distro == "ubuntu":
            total_ubuntu += 1
            has_autoinstall = "autoinstall" in boot_params
            has_ds = "ds=nocloud-net" in boot_params
            
            # Formulate detailed statuses based on actual database states
            enabled_str = "TRUE" if enabled else "FALSE"
            
            if not extracted:
                extraction_status = "IN-PROGRESS"
                autoinstall_status = "PENDING"
                # If extraction is in progress, it's not a failure yet
                is_failed = False
            else:
                extraction_status = "COMPLETE"
                if has_autoinstall and has_ds:
                    autoinstall_status = "YES"
                    # If extraction is complete, it must be enabled. If not, it was clobbered or failed!
                    if not enabled:
                        autoinstall_status = "🔒 LOCKED"
                        is_failed = True
                    else:
                        is_failed = False
                else:
                    autoinstall_status = "⚠️  MISSING"
                    is_failed = True

            if is_failed:
                failures += 1

            print(f"{filename:<40} | {distro:<10} | {enabled_str:<7} | {extraction_status:<11} | {autoinstall_status:<11}")

            if is_failed:
                if not extracted:
                    pass
                elif not enabled and (has_autoinstall and has_ds):
                    print(f"    [ALERT] Image is LOCKED/DISABLED in database but has valid boot params. Clobbering detected!")
                    print("-" * 90)
                else:
                    print(f"    [ALERT] Invalid boot params found:")
                    print(f"            {boot_params}")
                    print("-" * 90)

    print("==========================================================================================")
    print(f"AUDIT SUMMARY:")
    print(f"  Total Ubuntu Images Checked: {total_ubuntu}")
    print(f"  Interactive Mode/Locked Failures: {failures}")
    print("==========================================================================================")

    if failures > 0:
        print("[!] Warning: Some Ubuntu images are locked or missing autoinstall parameters!")
        print("    These nodes could fail to boot or launch in interactive mode.")
        sys.exit(1)
    else:
        print("[x] SUCCESS: All Ubuntu/GDC images are unlocked and configured in secure, non-interactive autoinstall mode!")
        sys.exit(0)

if __name__ == "__main__":
    main()
