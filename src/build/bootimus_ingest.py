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
import subprocess

# Configurable Defaults (Can be overridden by environment variables)
BOOTIMUS_API_HOST = os.environ.get("BOOTIMUS_API_HOST", "192.168.254.12")
BOOTIMUS_API_PORT = int(os.environ.get("BOOTIMUS_API_PORT", 26000))
BOOTIMUS_HTTP_PORT = int(os.environ.get("BOOTIMUS_HTTP_PORT", 16000))
API_BASE = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_API_PORT}/api"

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
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        
    encoded_data = None
    if data:
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

def main():
    print("==============================================================================")
    print(" BOOTIMUS ISO INGEST & PXE LOADER ENGINE")
    print("==============================================================================")
    
    # 1. Determine Target ISO Filename
    # Read filename from CLI or fall back to the dynamic build_meta.env if running post-build
    filename = None
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        # Check workspace metadata
        meta_file = "build-workspace/build_meta.env"
        if os.path.exists(meta_file):
            with open(meta_file, "r") as f:
                for line in f:
                    if line.startswith("ISO_OUTPUT_NAME="):
                        filename = line.split("=")[1].strip()
                        break
                        
    # Ensure correct relative folder prefix matching GCS structure
    if filename and not filename.startswith("sync/"):
        filename = f"sync/{filename}"
        
    if not filename:
        print("[!] Error: No target ISO filename specified or found in metadata.")
        print("    Usage: ./bootimus_ingest.py <iso_filename>")
        sys.exit(1)
        
    print(f"[-] Target Ingest Image: {filename}")
    
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
    except Exception as e:
        print(f"[!] Authentication failed: {e}")
        sys.exit(1)
        
    # 3. Trigger Filesystem Scan
    print("[-] Triggering Bootimus file scanner for newly synchronized GCS ISOs...")
    api_request(f"{API_BASE}/scan", method="POST", token=token)
    time.sleep(2) # Allow scanner initialization
    
    # 4. Locate and Verify Image
    print("[-] Searching for scanned image...")
    image_data = None
    retries = 10
    while retries > 0:
        images_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token)
        if images_res.get("success") and images_res.get("data"):
            image_data = images_res["data"][0]
            print(f"[x] Located image: {image_data['name']} (Size: {image_data['size']} bytes)")
            break
        print(f"[-] Still searching... ({retries} retries left)")
        time.sleep(3)
        retries -= 1
        
    if not image_data:
        print(f"[!] Error: Could not locate '{filename}' in Bootimus. Verify Synology Cloud Sync.")
        sys.exit(1)
        
    # 5. Extract Kernel/Initrd from ISO if not already done
    if not image_data.get("extracted"):
        print(f"[-] Image is not extracted. Triggering kernel/initrd extraction...")
        api_request(f"{API_BASE}/images/extract?filename={urllib.parse.quote(filename)}", method="POST", token=token)
        
        # Poll extraction progress
        print("[-] Monitoring extraction progress...")
        while True:
            progress_res = api_request(
                f"{API_BASE}/images/extract-progress?filename={urllib.parse.quote(filename)}",
                token=token
            )
            # The progress structure can vary, handle both direct number or nested dictionary
            data = progress_res.get("data", {})
            progress = data.get("progress", 0) if isinstance(data, dict) else data
            status = data.get("status", "") if isinstance(data, dict) else ""
            
            print(f"    [-] Progress: {progress}% - Status: {status or 'Running'}")
            if progress >= 100 or status == "completed":
                break
            time.sleep(4)
        print("[-] Extraction complete.")
    else:
        print("[-] Image already extracted. Skipping extraction phase.")
        
    # 6. Configure Boot Method & Custom Boot Parameters
    iso_name_no_ext = filename[:-4] # strip '.iso'
    
    # Dynamic URLs matching user specifications
    iso_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{filename}"
    cloud_config_url = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_HTTP_PORT}/isos/{iso_name_no_ext}/iso/nocloud/user-data"
    
    boot_params = (
        f"boot=casper initrd=initrd ip=dhcp netboot=url "
        f"url={iso_url} "
        f"root=/dev/ram0 ramdisk_size=4500000 autoinstall "
        f"cloud-config-url={cloud_config_url}"
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
    
    print("==============================================================================")
    print(" [x] SUCCESS: ISO INGEST & BOOTIMUS PROVISIONING COMPLETED!")
    print("==============================================================================")
    print(f"  Image Name:  {image_data['name']}")
    print(f"  Method:      Kernel/Initrd")
    print(f"  Parameters:  {boot_params}")
    print("==============================================================================")

if __name__ == "__main__":
    main()
