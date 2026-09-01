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
# GDC Bootloader - Bootimus Ingest & Configuration Automation
# ==============================================================================
# Triggers a filesystem scan on the Bootimus PXE Server, waits for the newly
# synchronized GDC ISO to appear, triggers kernel extraction, and configures the
# boot method and custom kernel boot parameters dynamically.
# ==============================================================================

import os
import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess

# Configurable Defaults (Can be overridden by environment variables)
BOOTIMUS_API_HOST = os.environ.get("BOOTIMUS_API_HOST", "192.168.254.12")
BOOTIMUS_API_PORT = int(os.environ.get("BOOTIMUS_API_PORT", 26000))
BOOTIMUS_HTTP_PORT = int(os.environ.get("BOOTIMUS_HTTP_PORT", 16000))
API_BASE = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_API_PORT}/api"
BOOTIMUS_SCAN_RETRIES = int(os.environ.get("BOOTIMUS_SCAN_RETRIES", 24))
BOOTIMUS_SCAN_DELAY = int(os.environ.get("BOOTIMUS_SCAN_DELAY", 15))

def get_bootimus_credentials():
    """Retrieves credentials from environment or dynamically from Infisical."""
    user = os.environ.get("BOOTIMUS_USER")
    passwd = os.environ.get("BOOTIMUS_PASS")
    
    if user and passwd:
        return user, passwd
        
    print("[-] Credentials not in environment. Querying Infisical for 'bootimus_creds'...")
    try:
        # Fetch dynamically using the Infisical CLI
        res = subprocess.run(
            ["infisical", "secrets", "get", "bootimus_creds", "--json"],
            capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)
        secret_val = json.loads(data["secretValue"])
        return secret_val["username"], secret_val["password"]
    except Exception as e:
        print(f"[!] Warning: Failed to retrieve secrets from Infisical ({e}).")
        print("[!] Please export BOOTIMUS_USER and BOOTIMUS_PASS in your environment.")
        sys.exit(1)

def api_request(url, method="GET", data=None, token=None, retries=5, retry_delay=5, timeout=30):
    """Utility wrapper to perform HTTP API requests with automatic network retry for intermittent connectivity."""
    encoded_data = None
    if data is not None:
        encoded_data = json.dumps(data).encode("utf-8")
        
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
            
        try:
            with urllib.request.urlopen(req, data=encoded_data, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 4xx client errors (except 429) usually shouldn't be blindly retried unless it's a 408/429/5xx
            if e.code in (408, 429) or e.code >= 500:
                print(f"[!] HTTP Error {e.code} on attempt {attempt}/{retries}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print(f"[!] HTTP Error: {e.code} - {e.read().decode('utf-8')}")
                raise
        except Exception as e:
            if attempt < retries:
                print(f"[!] Request Error on attempt {attempt}/{retries} ({e}). Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print(f"[!] Request Error: {e} (all {retries} attempts failed)")
                raise
    raise RuntimeError(f"[!] Request to {url} failed after all {retries} retry attempts.")

def print_tree(grouped_images, group_filter=None):
    """Renders grouped images in a beautiful Unicode tree format."""
    groups_to_show = list(grouped_images.keys())
    if group_filter:
        groups_to_show = [g for g in groups_to_show if group_filter.lower() in g.lower()]
        if not groups_to_show:
            print(f"[-] No groups/folders found matching filter: '{group_filter}'")
            return
            
    # Sort groups so ungrouped is always at the bottom, and others are sorted alphabetically
    sorted_groups = sorted([g for g in groups_to_show if g != "ungrouped"])
    if "ungrouped" in groups_to_show:
        sorted_groups.append("ungrouped")
        
    for i, group in enumerate(sorted_groups):
        is_last_group = (i == len(sorted_groups) - 1)
        group_prefix = "└── " if is_last_group else "├── "
        print(f"{group_prefix}{group}")
        
        # Sort files alphabetically by filename
        sorted_images = sorted(grouped_images[group], key=lambda x: x["filename"])
        for j, img in enumerate(sorted_images):
            is_last_file = (j == len(sorted_images) - 1)
            parent_indent = "    " if is_last_group else "│   "
            file_prefix = "└── " if is_last_file else "├── "
            extracted_indicator = "" if img["extracted"] else " 🚧"
            print(f"{parent_indent}{file_prefix}{img['filename']}{extracted_indicator}")

def show_help():
    print("==============================================================================")
    print(" BOOTIMUS AUTOMATION CLI - HELP MENU")
    print("==============================================================================")
    print("Usage:")
    print("  ./src/build/bootimus.py <iso_filename> [options]    Ingest & configure an ISO.")
    print("  ./src/build/bootimus.py -l, --list [options]        List groups and images.")
    print("  ./src/build/bootimus.py -h, --help                  Show this help menu.")
    print("")
    print("Options:")
    print("  -f, --force                Force re-extraction of kernel/initrd boot files.")
    print("  --filter <group_name>      Filter the tree list to a specific group/folder.")
    print("")
    print("Environment Variables:")
    print("  BOOTIMUS_API_HOST          Bootimus Server IP (default: 192.168.254.12)")
    print("  BOOTIMUS_API_PORT          Bootimus API Port (default: 26000)")
    print("  BOOTIMUS_HTTP_PORT         Bootimus HTTP assets Port (default: 16000)")
    print("  BOOTIMUS_USER              API username (falls back to Infisical 'bootimus_creds')")
    print("  BOOTIMUS_PASS              API password (falls back to Infisical 'bootimus_creds')")
    print("==============================================================================")

def auto_heal_boot_params(token):
    """Scans all registered Ubuntu images on Bootimus and ensures they have correct autoinstall boot parameters."""
    print("[-] Running self-healing audit on Bootimus image database...")
    try:
        images_res = api_request(f"{API_BASE}/images", token=token)
        for img in images_res.get("data", []):
            filename = img.get("filename", "")
            distro = img.get("distro", "")
            boot_method = img.get("boot_method", "")
            boot_params = img.get("boot_params", "")
            enabled = img.get("enabled", False)
            extracted = img.get("extracted", False)
            
            # Any GDC bootstrap image should use kernel boot method and correct autoinstall params
            is_gdc_image = filename and ("gdc-bootstrap" in filename or filename.startswith("sync/gdc-bootstrap"))
            
            if is_gdc_image:
                has_correct_params = (
                    "autoinstall" in boot_params and 
                    "ds=nocloud-net" in boot_params and
                    "modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp" in boot_params and
                    "tpm_tis.interrupts=0" in boot_params and
                    "apparmor=0" in boot_params and
                    "console=tty1 console=ttyS0" in boot_params and
                    "ramdisk_size=7500000" in boot_params
                )

                if not extracted:
                    # ISO is syncing or extracting. MUST be disabled to prevent dangerous premature PXE boots.
                    if enabled:
                        print(f"[-] Alert: GDC Image '{img.get('name')}' is still extracting but is currently ENABLED. Disabling to prevent premature boot...")
                        disable_data = {
                            "boot_method": boot_method,
                            "distro": distro,
                            "boot_params": boot_params,
                            "enabled": False
                        }
                        update_url = f"{API_BASE}/images?filename={urllib.parse.quote(filename)}"
                        img.update(disable_data)
                        api_request(update_url, method="PUT", data=img, token=token)
                        
                elif boot_method != "kernel" or distro != "ubuntu" or not has_correct_params or not enabled:
                    print(f"[!] Alert: GDC Image '{img.get('name')}' configuration is missing or clobbered! Healing...")
                    
                    iso_name_no_ext = filename[:-4]
                    iso_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{filename}"
                    seed_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{iso_name_no_ext}/iso/nocloud/"
                    
                    fixed_params = (
                        f"boot=casper initrd=initrd ip=dhcp netboot=url "
                        f"url={iso_url} "
                        f"root=/dev/ram0 ramdisk_size=7500000 autoinstall "
                        f"apparmor=0 console=tty1 console=ttyS0 "
                        f"tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp "
                        f"ds=nocloud-net;s={seed_url}"
                    )
                    
                    # Stage 1: Configure parameters but DO NOT ENABLE yet
                    stage1_data = {
                        "boot_method": "kernel",
                        "distro": "ubuntu",
                        "boot_params": fixed_params,
                        "enabled": False
                    }
                    update_url = f"{API_BASE}/images?filename={urllib.parse.quote(filename)}"
                    
                    print(f"    [-] Stage 1: Writing strict parameters to '{img.get('name')}' (keeping disabled)...")
                    img.update(stage1_data)
                    api_request(update_url, method="PUT", data=img, token=token)
                    
                    # Robust consecutive-success loop to defeat delayed Bootimus database clobbering
                    consecutive_verifications = 0
                    required_consecutive = 6  # Require 6 consecutive successful checks (30 seconds of stability)
                    max_attempts = 20
                    verified = False
                    
                    for verify_attempt in range(1, max_attempts + 1):
                        time.sleep(5)
                        verify_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token)
                        if verify_res.get("success") and verify_res.get("data"):
                            matching = [m for m in verify_res["data"] if m.get("filename") == filename]
                            if matching:
                                current_img = matching[0]
                                current_params = current_img.get("boot_params", "")
                                current_method = current_img.get("boot_method", "")
                                current_enabled = current_img.get("enabled", False)
                                
                                is_correct = (
                                    current_params == fixed_params and 
                                    current_method == "kernel" and 
                                    current_enabled is False
                                )
                                
                                if is_correct:
                                    consecutive_verifications += 1
                                    if consecutive_verifications >= required_consecutive:
                                        print(f"    [+] Parameters verified stable! (Attempt {verify_attempt})")
                                        verified = True
                                        break
                                else:
                                    consecutive_verifications = 0
                                    current_img.update(stage1_data)
                                    api_request(update_url, method="PUT", data=current_img, token=token)
                                    
                    if not verified:
                        print(f"    [!] Warning: Failed to stabilize parameters for '{img.get('name')}'. Aborting healing.")
                        continue
                        
                    # Stage 2: We are 100% extracted, ubuntu kernel, correct parameters, and stable. NOW we enable.
                    print(f"    [-] Stage 2: Configuration locked. Setting ENABLED = True...")
                    stage2_data = {
                        "boot_method": "kernel",
                        "distro": "ubuntu",
                        "boot_params": fixed_params,
                        "enabled": True
                    }
                    img.update(stage2_data)
                    api_request(update_url, method="PUT", data=img, token=token)
                    print(f"    [+] Successfully healed, locked, and enabled '{img.get('name')}'!")
    except Exception as e:
        print(f"[!] Warning: Self-healing audit encountered an error: {e}")

def main():
    args = sys.argv[1:]
    
    # Trigger help if no arguments are provided or help flags are passed
    if not args or "--help" in args or "-h" in args:
        show_help()
        sys.exit(0)

    print("==============================================================================")
    print(" BOOTIMUS ISO INGEST & PXE LOADER ENGINE")
    print("==============================================================================")
    
    # 1. Determine Target ISO Filename & Options
    # Read filename and force flag from CLI, or fall back to dynamic build_meta.env post-build
    filename = None
    force_extract = False
    list_only = False
    group_filter = None
    
    if "--force" in args:
        force_extract = True
        args.remove("--force")
    if "-f" in args:
        force_extract = True
        args.remove("-f")
        
    if "--list" in args or "-l" in args:
        list_only = True
        if "--list" in args: args.remove("--list")
        if "-l" in args: args.remove("-l")
        
    if "--filter" in args:
        idx = args.index("--filter")
        if idx + 1 < len(args):
            group_filter = args[idx+1]
            args.pop(idx+1)
            args.pop(idx)
        else:
            print("[!] Error: --filter requires a value.")
            sys.exit(1)
            
    if len(args) > 0:
        filename = args[0]
    elif not list_only:
        # Check workspace metadata
        meta_file = "build-workspace/build_meta.env"
        if os.path.exists(meta_file):
            with open(meta_file, "r") as f:
                for line in f:
                    if line.startswith("ISO_OUTPUT_NAME="):
                        filename = line.split("=")[1].strip()
                        break
                        
    # Ensure correct relative folder prefix matching GCS structure
    if filename and not filename.startswith("sync/") and not list_only:
        filename = f"sync/{filename}"
        
    if not filename and not list_only:
        print("[!] Error: No target ISO filename specified or found in metadata.")
        print("    Usage:")
        print("      Ingest/Extract ISO:  ./bootimus.py <iso_filename> [--force]")
        print("      List groups/ISOs:    ./bootimus.py --list [--filter <group_name>]")
        sys.exit(1)
        
    if list_only:
        print("[-] Target Action: Render Bootimus image tree list" + (f" (Filter: '{group_filter}')" if group_filter else ""))
    else:
        print(f"[-] Target Ingest Image: {filename} (Force Re-extract: {force_extract})")
    
    # 2. Authenticate
    username, password = get_bootimus_credentials()
    print(f"[-] Authenticating with Bootimus at {BOOTIMUS_API_HOST}:{BOOTIMUS_API_PORT}...")
    try:
        login_res = api_request(
            f"{API_BASE}/login",
            method="POST",
            data={"username": username, "password": password}
        )
        token = login_res["data"]["token"]
        print("[-] Authentication successful.")
        
        # Run self-healing audit on all registered images
        auto_heal_boot_params(token)
    except Exception as e:
        print(f"[!] Authentication failed: {e}")
        sys.exit(1)
        
    # 3. If list_only, fetch images, render tree, and exit
    if list_only:
        print("[-] Fetching images from Bootimus...")
        try:
            images_res = api_request(f"{API_BASE}/images", token=token)
            grouped_images = {}
            for img in images_res.get("data", []):
                filename_val = img.get("filename", "unknown.iso")
                # Filter out extracted test/internal ISO files nested inside other ISOs
                if "/iso/" in filename_val or "/extracted/" in filename_val or "tests/" in filename_val:
                    continue
                
                group_name = "ungrouped"
                if img.get("group") and img["group"].get("name"):
                    group_name = img["group"]["name"]
                
                if group_name == "files":
                    continue
                
                if group_name not in grouped_images:
                    grouped_images[group_name] = []
                grouped_images[group_name].append({
                    "filename": filename_val,
                    "extracted": img.get("extracted", False)
                })
                
            print("==============================================================================")
            print(" BOOTIMUS IMAGES AND GROUPS TREE")
            print("==============================================================================")
            print_tree(grouped_images, group_filter)
            print("==============================================================================")
            sys.exit(0)
        except Exception as e:
            print(f"[!] Error listing images: {e}")
            sys.exit(1)
        
    # 3. Check if image is already registered to bypass heavy filesystem scan
    assert filename is not None, "filename cannot be None"
    print("[-] Querying Bootimus to see if the image is already registered...")
    images_res = api_request(f"{API_BASE}/images", token=token)
    image_already_registered = False
    if images_res.get("success") and images_res.get("data"):
        matching = [img for img in images_res["data"] if img.get("filename") == filename]
        if matching:
            image_already_registered = True
            print(f"[x] Image is already registered in Bootimus database. Bypassing heavy filesystem scan.")
            
    if not image_already_registered:
        print("[-] Ingesting new image. Triggering Bootimus file scanner for newly synchronized GCS ISOs...")
        api_request(f"{API_BASE}/scan", method="POST", token=token)
        print("[-] Waiting 30 seconds for scanner initialization and directory discovery to settle...")
        time.sleep(30)
    
    # 4. Locate and Verify Image
    print("[-] Searching for scanned image and waiting for download/loading to complete...")
    image_data = None
    retries = BOOTIMUS_SCAN_RETRIES
    last_size = -1
    stable_count = 0
    while retries > 0:
        images_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token)
        if images_res.get("success") and images_res.get("data"):
            # Manually filter returned images by exact filename to avoid defaulting to the first item (cascade1)
            matching_images = [img for img in images_res["data"] if img.get("filename") == filename]
            if matching_images:
                current_image = matching_images[0]
                current_size = current_image.get("size", 0)
                print(f"    [-] Found image: {current_image['name']} (Current Size: {current_size} bytes)")
                
                if current_size > 0:
                    if current_size == last_size:
                        stable_count += 1
                        print(f"    [-] Image size is stable ({stable_count}/2)...")
                    else:
                        stable_count = 0
                        last_size = current_size
                    
                    if stable_count >= 2:
                        image_data = current_image
                        print(f"[x] Located fully loaded image: {image_data['name']} (Size: {image_data['size']} bytes)")
                        
                        # Immediately disable to prevent premature booting of unconfigured/unextracted image
                        if image_data.get("enabled", True) and not image_data.get("extracted", False):
                            print("[-] Temporarily disabling image during extraction and configuration to prevent premature PXE boots...")
                            disable_data = {
                                "boot_method": image_data.get("boot_method", "iso"),
                                "distro": image_data.get("distro", ""),
                                "boot_params": image_data.get("boot_params", ""),
                                "enabled": False
                            }
                            try:
                                api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", method="PUT", data=disable_data, token=token)
                            except Exception as e:
                                print(f"[!] Warning: Failed to temporarily disable image: {e}")
                        break
                else:
                    print("    [-] Image size is 0 bytes (still registering/transferring)...")
                    stable_count = 0
                    last_size = 0
        print(f"[-] Still searching/loading... ({retries} retries left)")
        time.sleep(BOOTIMUS_SCAN_DELAY)
        retries -= 1
        
    if not image_data:
        print(f"[!] Error: Could not locate '{filename}' in Bootimus. Verify Synology Cloud Sync.")
        sys.exit(1)
        
    # 5. Extract Kernel/Initrd from ISO if not already done or if forced
    if not image_data.get("extracted") or force_extract:
        if force_extract:
            print(f"[-] Forcing kernel/initrd extraction on target...")
        else:
            print(f"[-] Image is not extracted. Triggering kernel/initrd extraction...")
        
        try:
            # Bootimus API blocks on /extract until complete or timeout. We trigger it with a short timeout
            # and intentionally catch the timeout so we can move immediately to the polling loop.
            api_request(f"{API_BASE}/images/extract?filename={urllib.parse.quote(filename)}", method="POST", token=token, timeout=2, retries=1)
        except Exception:
            print("[-] Extraction triggered (ignoring HTTP timeout due to Bootimus synchronous architecture)...")
            pass
        
        # Poll extraction progress
        print("[-] Monitoring extraction progress...")
        attempts = 1
        while True:
            progress_res = api_request(
                f"{API_BASE}/images/extract-progress?filename={urllib.parse.quote(filename)}",
                token=token
            )
            # The progress structure can vary, handle both direct number, nested dictionary, or "percent"
            data = progress_res.get("data", {})
            if isinstance(data, dict):
                progress = data.get("percent", data.get("progress", 0))
                status = data.get("status", "")
            else:
                progress = data
                status = ""
            
            try:
                progress = int(progress)
            except:
                progress = 0
                
            print(f"    [-] Progress (Attempt {attempts}): {progress}% - Status: {status or 'Running'}")
            
            # Failsafe abort to prevent infinite hangs
            if attempts > 300:
                print("[!] Extraction hung for over 20 minutes! Aborting.")
                sys.exit(1)
            # If the status is "idle" but we just started, ignore it to let the extraction daemon spin up
            if status == "idle" and attempts <= 3 and progress < 100:
                print("    [-] Ignoring initial 'idle' status to allow backend daemon to start...")
            else:
                if progress >= 100 or status in ["done", "completed", "idle"]:
                    break
            time.sleep(4)
            attempts += 1
        print("[-] Extraction complete. Waiting 5 seconds for database transactions to settle...")
        time.sleep(5)
        print("[-] Database transactions settled.")
    else:
        print("[-] Image already extracted. Skipping extraction phase.")
        
    # 6. Configure Boot Method & Custom Boot Parameters
    iso_name_no_ext = filename[:-4] # strip '.iso'
    
    # Dynamic URLs matching user specifications
    iso_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{filename}"
    seed_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{iso_name_no_ext}/iso/nocloud/"
    
    boot_params = (
        f"boot=casper initrd=initrd ip=dhcp netboot=url "
        f"url={iso_url} "
        f"root=/dev/ram0 ramdisk_size=7500000 autoinstall "
        f"apparmor=0 console=tty1 console=ttyS0 "
        f"tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp "
        f"ds=nocloud-net;s={seed_url}"
    )
    
    print("[-] Updating boot method to 'kernel', setting distro to 'ubuntu', and configuring parameters...")
    update_data = {
        "boot_method": "kernel",
        "distro": "ubuntu",
        "boot_params": boot_params,
        "enabled": True
    }
    
    # We must fetch the current full object state so the PUT API does not reject missing fields
    images_res = api_request(f"{API_BASE}/images", token=token)
    img_match = [i for i in images_res.get("data", []) if i.get("filename") == filename]
    
    if img_match:
        current_img_state = img_match[0]
        current_img_state.update(update_data)
        
        # Send PUT request to save image configurations
        update_url = f"{API_BASE}/images?filename={urllib.parse.quote(filename)}"
        api_request(update_url, method="PUT", data=current_img_state, token=token)
    else:
        update_url = f"{API_BASE}/images?filename={urllib.parse.quote(filename)}"
        api_request(update_url, method="PUT", data=update_data, token=token)
    
    print("[-] Running database stability verification (verifying parameters persist consecutively)...")
    consecutive_verifications = 0
    required_consecutive = 6  # Require 6 consecutive successful checks (30 seconds of stability)
    max_attempts = 20
    verified = False
    
    for verify_attempt in range(1, max_attempts + 1):
        time.sleep(5)
        verify_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token)
        if verify_res.get("success") and verify_res.get("data"):
            matching_images = [img for img in verify_res["data"] if img.get("filename") == filename]
            if matching_images:
                current_image = matching_images[0]
                current_params = current_image.get("boot_params", "")
                current_method = current_image.get("boot_method", "")
                current_enabled = current_image.get("enabled", False)
                
                is_correct = (
                    current_params == boot_params and 
                    current_method == "kernel" and 
                    current_enabled is True
                )
                
                if is_correct:
                    consecutive_verifications += 1
                    print(f"    [-] Attempt {verify_attempt}/{max_attempts}: Custom parameters verified ({consecutive_verifications}/{required_consecutive} stable)...")
                    if consecutive_verifications >= required_consecutive:
                        print(f"    [+] Success: Custom parameters verified and locked stable in database after {verify_attempt} attempts!")
                        verified = True
                        break
                else:
                    print(f"    [!] Warning: Attempt {verify_attempt}/{max_attempts}: Detected parameter clobbering or mismatch! Re-applying custom configurations...")
                    consecutive_verifications = 0
                    current_image.update(update_data)
                    api_request(update_url, method="PUT", data=current_image, token=token)
                    
    if not verified:
        print("[!] CRITICAL ERROR: Failed to establish a stable, un-clobbered boot configuration in Bootimus!")
        sys.exit(1)
    
    print("==============================================================================")
    print(" [x] SUCCESS: ISO INGEST & BOOTIMUS PROVISIONING COMPLETED!")
    print("==============================================================================")
    print(f"  Image Name:  {image_data['name']}")
    print(f"  Method:      Kernel/Initrd")
    print(f"  Parameters:  {boot_params}")
    print("==============================================================================")

if __name__ == "__main__":
    main()
