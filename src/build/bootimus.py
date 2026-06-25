#!/usr/bin/env python3
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

def api_request(url, method="GET", data=None, token=None):
    """Utility wrapper to perform HTTP API requests using urllib standard library."""
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        
    encoded_data = None
    if data is not None:
        req.add_header("Content-Type", "application/json")
        encoded_data = json.dumps(data).encode("utf-8")
        
    try:
        with urllib.request.urlopen(req, data=encoded_data) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[!] HTTP Error: {e.code} - {e.read().decode('utf-8')}")
        raise
    except Exception as e:
        print(f"[!] Request Error: {e}")
        raise

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
            
            # We only heal Ubuntu images that are fully extracted and use kernel boot method
            if distro == "ubuntu" and boot_method == "kernel" and filename and img.get("extracted", False):
                # Check if it is missing autoinstall or ds=nocloud-net
                if "autoinstall" not in boot_params or "ds=nocloud-net" not in boot_params:
                    print(f"[!] Alert: Image '{img.get('name')}' is missing correct autoinstall boot parameters! Healing...")
                    
                    iso_name_no_ext = filename[:-4]
                    iso_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{filename}"
                    seed_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{iso_name_no_ext}/iso/nocloud/"
                    
                    fixed_params = (
                        f"boot=casper initrd=initrd ip=dhcp netboot=url "
                        f"url={iso_url} "
                        f"root=/dev/ram0 ramdisk_size=4500000 autoinstall "
                        f"ds=nocloud-net;s={seed_url}"
                    )
                    
                    update_data = {
                        "boot_method": "kernel",
                        "distro": "ubuntu",
                        "boot_params": fixed_params,
                        "enabled": True
                    }
                    update_url = f"{API_BASE}/images?filename={urllib.parse.quote(filename)}"
                    
                    # Robust check-and-reapply loop to defeat delayed Bootimus database clobbering
                    for i in range(1, 4):
                        api_request(update_url, method="PUT", data=update_data, token=token)
                        time.sleep(3)
                        verify_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token)
                        if verify_res.get("success") and verify_res.get("data"):
                            matching = [m for m in verify_res["data"] if m.get("filename") == filename]
                            if matching and matching[0].get("boot_params", "") == fixed_params:
                                print(f"    [+] Successfully healed and verified '{img.get('name')}' configuration (Attempt {i})!")
                                break
                    else:
                        print(f"    [!] Warning: Failed to permanently verify healed '{img.get('name')}' configuration. Forcing one final write...")
                        api_request(update_url, method="PUT", data=update_data, token=token)
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
        
    # 3. Trigger Filesystem Scan
    assert filename is not None, "filename cannot be None"
    print("[-] Triggering Bootimus file scanner for newly synchronized GCS ISOs...")
    api_request(f"{API_BASE}/scan", method="POST", token=token)
    time.sleep(2) # Allow scanner initialization
    
    # 4. Locate and Verify Image
    print("[-] Searching for scanned image...")
    image_data = None
    retries = BOOTIMUS_SCAN_RETRIES
    while retries > 0:
        images_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token)
        if images_res.get("success") and images_res.get("data"):
            # Manually filter returned images by exact filename to avoid defaulting to the first item (cascade1)
            matching_images = [img for img in images_res["data"] if img.get("filename") == filename]
            if matching_images:
                image_data = matching_images[0]
                print(f"[x] Located image: {image_data['name']} (Size: {image_data['size']} bytes)")
                break
        print(f"[-] Still searching... ({retries} retries left)")
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
        api_request(f"{API_BASE}/images/extract?filename={urllib.parse.quote(filename)}", method="POST", token=token)
        
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
            
            print(f"    [-] Progress (Attempt {attempts}): {progress}% - Status: {status or 'Running'}")
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
        f"root=/dev/ram0 ramdisk_size=4500000 autoinstall "
        f"ds=nocloud-net;s={seed_url}"
    )
    
    print("[-] Updating boot method to 'kernel', setting distro to 'ubuntu', and configuring parameters...")
    update_data = {
        "boot_method": "kernel",
        "distro": "ubuntu",
        "boot_params": boot_params,
        "enabled": True
    }
    
    # Send PUT request to save image configurations
    update_url = f"{API_BASE}/images?filename={urllib.parse.quote(filename)}"
    api_request(update_url, method="PUT", data=update_data, token=token)
    
    print("[-] Verifying database state for custom boot parameters...")
    verified = False
    for verify_attempt in range(1, 5):
        time.sleep(3)
        verify_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token)
        if verify_res.get("success") and verify_res.get("data"):
            matching_images = [img for img in verify_res["data"] if img.get("filename") == filename]
            if matching_images:
                current_params = matching_images[0].get("boot_params", "")
                if current_params == boot_params:
                    print(f"    [+] Success: Custom boot parameters verified correctly in database on attempt {verify_attempt}!")
                    verified = True
                    break
                else:
                    print(f"    [!] Warning: Detected parameter clobbering! Re-applying custom parameters (Attempt {verify_attempt})...")
                    api_request(update_url, method="PUT", data=update_data, token=token)
                    
    if not verified:
        print("[!] CRITICAL ERROR: Failed to verify custom boot parameters in Bootimus database after multiple attempts!")
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
