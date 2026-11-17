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

getattr(sys.stdout, "reconfigure", lambda **kwargs: None)(line_buffering=True)

def _parse_env_file(filepath):
    """Safely parses a simple KEY=VALUE bash env file."""
    if not os.path.exists(filepath):
        return {}
    res = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    res[k] = v
    except Exception:
        pass
    return res

def _load_env_defaults():
    """Loads baseline build.env defaults merged with active ISO_ENVIRONMENT.env overrides."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    iso_env = os.environ.get("ISO_ENVIRONMENT", "local")
    if iso_env == "local":
        for a in sys.argv:
            if "gdc-labs" in a or "barn" in a:
                iso_env = "barn"
                break
            elif "honeywell" in a:
                iso_env = "honeywell"
                break
    merged = {}
    merged.update(_parse_env_file(os.path.join(script_dir, "build.env")))
    merged.update(_parse_env_file(os.path.join(script_dir, f"{iso_env}.env")))
    return merged

_ENV_DEFAULTS = _load_env_defaults()

def _get_str_env(keys, default):
    """Retrieves string environment variable by checking multiple aliases in os.environ and env files."""
    if isinstance(keys, str):
        keys = [keys]
    for k in keys:
        val = os.environ.get(k)
        if val is not None and str(val).strip():
            clean_val = str(val).strip()
            # If val is the generic example domain from build.env, check if profile defined a specific host
            if clean_val in ("pxe.example-labs.com", "http://pxe.example-labs.com:16000"):
                for alt_k in keys:
                    if alt_k in _ENV_DEFAULTS and str(_ENV_DEFAULTS[alt_k]).strip() and str(_ENV_DEFAULTS[alt_k]).strip() not in ("pxe.example-labs.com", "http://pxe.example-labs.com:16000"):
                        return str(_ENV_DEFAULTS[alt_k]).strip()
            return clean_val
    for k in keys:
        if k in _ENV_DEFAULTS and str(_ENV_DEFAULTS[k]).strip():
            return str(_ENV_DEFAULTS[k]).strip()
    return default

def _get_int_env(keys, default):
    """Retrieves integer environment variable by checking multiple aliases in os.environ and env files."""
    if isinstance(keys, str):
        keys = [keys]
    for k in keys:
        val = os.environ.get(k)
        if val is not None and str(val).strip().isdigit():
            return int(str(val).strip())
    for k in keys:
        if k in _ENV_DEFAULTS and str(_ENV_DEFAULTS[k]).strip().isdigit():
            return int(str(_ENV_DEFAULTS[k]).strip())
    return default

# Configurable Defaults (Can be overridden by environment variables)
BOOTIMUS_API_HOST = _get_str_env(["BOOTIMUS_API_HOST", "PXE_SERVER_HOST"], "192.168.254.12")
BOOTIMUS_API_PORT = _get_int_env(["BOOTIMUS_API_PORT", "PXE_SERVER_PORT"], 26000)
BOOTIMUS_HTTP_PORT = _get_int_env(["BOOTIMUS_HTTP_PORT"], 16000)
API_BASE = f"http://{BOOTIMUS_API_HOST}:{BOOTIMUS_API_PORT}/api"
BOOTIMUS_SCAN_RETRIES = _get_int_env(["BOOTIMUS_SCAN_RETRIES"], 80)
BOOTIMUS_SCAN_DELAY = _get_int_env(["BOOTIMUS_SCAN_DELAY", "BOOTIMUS_SCAN_INTERVAL_SECONDS"], 15)

# Boot Parameters Configuration Defaults (Configurable via Environment)
BOOT_RAMDISK_SIZE = os.environ.get("BOOT_RAMDISK_SIZE", "")
BOOT_CONSOLE = os.environ.get("BOOT_CONSOLE", "console=tty1 console=ttyS0")
BOOT_MODPROBE_BLACKLIST = os.environ.get("BOOT_MODPROBE_BLACKLIST", "pcie_mp2_amd,amd_sfh,ccp")
BOOT_APPARMOR = os.environ.get("BOOT_APPARMOR", "0")
BOOT_TPM_INTERRUPTS = os.environ.get("BOOT_TPM_INTERRUPTS", "0")
BOOT_EXTRA_PARAMS = os.environ.get("BOOT_EXTRA_PARAMS", "").strip()


def calculate_ramdisk_size(iso_size_bytes=None):
    """Calculates ramdisk_size (in KiB) with dynamic headroom above ISO size.
    Enforces a battle-tested 7.5GB (7500000 KiB) minimum floor, expanding
    dynamically by +1.5GB (1572864 KiB) if the ISO size exceeds headroom.
    """
    if BOOT_RAMDISK_SIZE:
        return BOOT_RAMDISK_SIZE

    floor_kib = 7500000
    headroom_kib = 1572864  # 1.5 GiB buffer for overlay filesystem and installer logs

    if iso_size_bytes and iso_size_bytes > 0:
        iso_kib = iso_size_bytes // 1024
        return str(max(floor_kib, iso_kib + headroom_kib))
    return str(floor_kib)


def get_boot_params(filename, iso_size_bytes=None):
    """Constructs dynamic Bootimus kernel parameters using template variables or env overrides."""
    # Support Bootimus native template substitution ({{BASE_URL}}, {{FILENAME}}, {{CACHE_DIR}})
    # while allowing explicit URL overrides if provided in the environment.
    iso_url = os.environ.get("BOOTIMUS_ISO_URL", "{{BASE_URL}}/isos/{{FILENAME}}")
    seed_url = os.environ.get("BOOTIMUS_SEED_URL", "{{BASE_URL}}/isos/{{CACHE_DIR}}/iso/nocloud/")
    ramdisk_size = calculate_ramdisk_size(iso_size_bytes)

    apparmor_val = BOOT_APPARMOR if BOOT_APPARMOR != "0" else "0"
    params = (
        f"boot=casper initrd=initrd ip=dhcp netboot=url "
        f"iso-url={iso_url} "
        f"root=/dev/ram0 ramdisk_size={ramdisk_size} autoinstall "
        f"apparmor=0 {BOOT_CONSOLE} "
        f"tpm_tis.interrupts={BOOT_TPM_INTERRUPTS} modprobe.blacklist={BOOT_MODPROBE_BLACKLIST} "
        f"ds=nocloud-net;s={seed_url}"
    )
    if BOOT_EXTRA_PARAMS:
        params = f"{params} {BOOT_EXTRA_PARAMS}"
    return params

def get_bootimus_credentials(cli_user=None, cli_pass=None, cli_provider=None, cli_file=None):
    """Retrieves credentials using an isolated, configurable lookup strategy:
    1. Explicit CLI arguments (--user, --pass)
    2. Direct environment variables (BOOTIMUS_USER, BOOTIMUS_PASS)
    3. Secret file (--secret-file or BOOTIMUS_SECRET_FILE)
    4. Configured secret provider (infisical, gcloud) ONLY if explicitly opted in via
       --secret-method / BOOTIMUS_SECRET_METHOD.
    """
    # 1. CLI arguments
    if cli_user and cli_pass:
        return cli_user, cli_pass

    # 2. Environment variables
    user = cli_user or os.environ.get("BOOTIMUS_USER")
    passwd = cli_pass or os.environ.get("BOOTIMUS_PASS")
    if user and passwd:
        return user, passwd

    # 3. Secret file
    secret_file = cli_file or os.environ.get("BOOTIMUS_SECRET_FILE")
    if secret_file and os.path.exists(secret_file):
        try:
            with open(secret_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content.startswith("{"):
                    data = json.loads(content)
                    return data.get("username", user or "admin"), data["password"]
                else:
                    return user or "admin", content
        except Exception as e:
            print(f"[!] Warning: Failed to read credentials from {secret_file}: {e}", file=sys.stderr)

    # 4. Check configured secret provider
    provider = (cli_provider or os.environ.get("BOOTIMUS_SECRET_PROVIDER") or os.environ.get("BOOTIMUS_SECRET_METHOD") or "infisical").strip().lower()

    if provider in ("infisical", "infiscial", "infisicial") or provider.startswith("infis"):
        print("[-] Querying Infisical for 'bootimus_creds' (BOOTIMUS_SECRET_METHOD=infisical)...")
        project_id = os.environ.get("INFISICAL_PROJECT_ID", "534a5b11-13bd-42fc-9937-426995d98707")
        inf_env = os.environ.get("INFISICAL_ENV", "prod")
        cmds = [
            ["infisical", "secrets", "get", "bootimus_creds", "--plain"],
            ["infisical", "secrets", "get", "bootimus_creds", "--projectId", project_id, "--env", inf_env, "--plain"],
            ["infisical", "secrets", "get", "bootimus_creds", "-o", "json"],
        ]
        for cmd in cmds:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                out = res.stdout.strip()
                if out.startswith("{") and "username" in out:
                    d = json.loads(out)
                    if "username" in d and "password" in d:
                        return d["username"], d["password"]
                data = json.loads(out)
                if isinstance(data, dict) and "secretValue" in data:
                    secret_val = json.loads(data["secretValue"]) if isinstance(data["secretValue"], str) else data["secretValue"]
                    return secret_val["username"], secret_val["password"]
            except Exception:
                continue
        print("[!] Warning: Failed to retrieve 'bootimus_creds' from Infisical.", file=sys.stderr)

    elif provider in ("gcloud", "gsm"):
        secret_name = os.environ.get("BOOTIMUS_GSM_SECRET", "bootimus_creds")
        project_arg = [f"--project={os.environ['PROJECT_ID']}"] if "PROJECT_ID" in os.environ else []
        print(f"[-] Querying Google Secret Manager for '{secret_name}' (BOOTIMUS_SECRET_METHOD=gcloud)...")
        try:
            res = subprocess.run(
                ["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_name}"] + project_arg,
                capture_output=True, text=True, check=True
            )
            out = res.stdout.strip()
            if out.startswith("{") and "username" in out:
                d = json.loads(out)
                return d["username"], d["password"]
            return user or "admin", out
        except Exception as e:
            print(f"[!] Warning: Failed to retrieve secret from GSM: {e}", file=sys.stderr)

    print("==============================================================================")
    print("  ERROR: Missing Bootimus API credentials.")
    print("  Please provide credentials via any of the following methods:")
    print("    1. Environment variables:  export BOOTIMUS_USER='admin' BOOTIMUS_PASS='...'")
    print("    2. CLI flags:              --user <USER> --pass <PASS>")
    print("    3. Secret file:            --secret-file /path/to/creds.json (or BOOTIMUS_SECRET_FILE)")
    print("    4. Configured provider:    --secret-method [infisical|gcloud|env]")
    print("==============================================================================")
    sys.exit(1)

def api_request(url, method="GET", data=None, token=None, retries=5, retry_delay=5, timeout=30, allow_404=False):
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
            if allow_404 and e.code == 404:
                try:
                    err_body = e.read().decode("utf-8")
                    return json.loads(err_body)
                except Exception:
                    return {"success": False, "error": "Not Found", "data": None}
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

def extract_images(res):
    """Safely extracts a list of image dicts from an API response across Bootimus versions.
    
    Handles Bootimus 0.1.69 (data is a list of image objects) and 0.1.79+ (data is a single
    image object when queried with ?filename=..., or a list when queried as /images).
    """
    if not res:
        return []
    if isinstance(res, list):
        return [img for img in res if isinstance(img, dict)]
    if isinstance(res, dict):
        if "data" in res:
            data = res.get("data")
            if isinstance(data, list):
                return [img for img in data if isinstance(img, dict)]
            elif isinstance(data, dict):
                if "filename" in data or "id" in data or "name" in data:
                    return [data]
                return []
            return []
        if "filename" in res or "id" in res or "name" in res:
            return [res]
    return []

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
    print("  ./src/build/bootimus.py --next-boot <iso> [options] Set one-time next-boot image.")
    print("  ./src/build/bootimus.py --clear-next-boot [options] Clear one-time next-boot override.")
    print("  ./src/build/bootimus.py -h, --help                  Show this help menu.")
    print("")
    print("Options:")
    print("  -f, --force                Force re-extraction of kernel/initrd boot files.")
    print("  --filter <group_name>      Filter the tree list to a specific group/folder.")
    print("  --mac <mac_address>        Target client MAC address for next-boot action.")
    print("  --targets, --nodes <IPs>   Target node IPs/MACs (defaults to TARGET_TEST_MACHINES).")
    print("                             Accepts space-separated or comma-separated lists.")
    print("  --all-targets              Apply next-boot action across all registered clients.")
    print("")
    print("Environment Variables:")
    print("  TARGET_TEST_MACHINES       Space or comma-separated IPs for default next-boot targets")
    print("  BOOTIMUS_API_HOST          Bootimus Server IP (default: 192.168.254.12)")
    print("  BOOTIMUS_API_PORT          Bootimus API Port (default: 26000)")
    print("  BOOTIMUS_HTTP_PORT         Bootimus HTTP assets Port (default: 16000)")
    print("  BOOTIMUS_USER              API username (falls back to Infisical 'bootimus_creds')")
    print("  BOOTIMUS_PASS              API password (falls back to Infisical 'bootimus_creds')")
    print("==============================================================================")

def format_mac_address(mac):
    """Normalizes MAC address string to standard lowercase colon-separated format (00:11:22:33:44:55)."""
    if not mac:
        return ""
    clean = str(mac).strip().lower().replace("-", "").replace(":", "")
    if len(clean) == 12:
        return ":".join(clean[i:i+2] for i in range(0, 12, 2))
    return str(mac).strip().lower()

def set_client_next_boot(token, mac_address, image_filename):
    """Sets a one-time next-boot image override on Bootimus for a specific client MAC address."""
    clean_mac = format_mac_address(mac_address)
    clean_img = image_filename.strip() if image_filename else ""
    if clean_img and not clean_img.startswith("sync/") and not clean_img.endswith(".iso"):
        clean_img = f"sync/{clean_img}.iso"
    elif clean_img and not clean_img.startswith("sync/"):
        clean_img = f"sync/{clean_img}"
    
    payload = {
        "mac_address": clean_mac,
        "image_filename": clean_img
    }
    return api_request(f"{API_BASE}/clients/next-boot", method="POST", data=payload, token=token)

def clear_client_next_boot(token, mac_address):
    """Clears any one-time next-boot override on Bootimus for a specific client MAC address."""
    clean_mac = format_mac_address(mac_address)
    payload = {
        "mac_address": clean_mac,
        "image_filename": ""
    }
    return api_request(f"{API_BASE}/clients/next-boot", method="POST", data=payload, token=token)

def set_client_group_next_boot(token, group_id, image_filename):
    """Sets a one-time next-boot image override on Bootimus for all members of a client group."""
    clean_img = image_filename.strip() if image_filename else ""
    if clean_img and not clean_img.startswith("sync/") and not clean_img.endswith(".iso"):
        clean_img = f"sync/{clean_img}.iso"
    elif clean_img and not clean_img.startswith("sync/"):
        clean_img = f"sync/{clean_img}"
    
    payload = {
        "image_filename": clean_img
    }
    return api_request(f"{API_BASE}/client-groups/next-boot?id={group_id}", method="POST", data=payload, token=token)

def parse_target_machines(target_raw):
    """Parses space-separated, comma-separated, or mixed IP/hostname/MAC list."""
    if not target_raw:
        return []
    cleaned = str(target_raw).replace("[", " ").replace("]", " ").replace("'", " ").replace('"', " ").replace(",", " ")
    return [item.strip() for item in cleaned.split() if item.strip()]

def resolve_target_macs(targets, token=None):
    """Resolves IP addresses, hostnames, or raw MACs into normalized MAC addresses."""
    if not targets:
        return []

    # Pre-load known IP->MAC mappings from _inventory.md if accessible
    ip_mac_map = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "..", "..", "_inventory.md"),
        "_inventory.md",
    ]
    import re
    for inv_path in candidates:
        if os.path.exists(inv_path):
            try:
                with open(inv_path, "r", encoding="utf-8") as f:
                    for line in f:
                        m = re.findall(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|[0-9a-fA-F:]{17}', line)
                        ip = None
                        mac = None
                        for token_str in m:
                            if "." in token_str and not ip:
                                ip = token_str
                            elif ":" in token_str and len(token_str) == 17 and not mac:
                                mac = token_str.lower()
                        if ip and mac:
                            ip_mac_map[ip] = mac
                if ip_mac_map:
                    break
            except Exception:
                pass

    resolved = []
    for tgt in targets:
        tgt_clean = tgt.strip()
        # 1. Is it already a MAC?
        raw_clean = tgt_clean.replace("-", "").replace(":", "")
        if len(raw_clean) == 12 and all(c in "0123456789abcdefABCDEF" for c in raw_clean):
            resolved.append(format_mac_address(tgt_clean))
            continue
        # 2. Check local inventory mapping
        if tgt_clean in ip_mac_map:
            resolved.append(ip_mac_map[tgt_clean])
            continue
        # 3. If token available, query Bootimus clients (check if client name matches)
        if token:
            try:
                clients_res = api_request(f"{API_BASE}/clients", token=token)
                for c in clients_res.get("data", []):
                    if c.get("name") == tgt_clean or c.get("mac_address") == tgt_clean:
                        resolved.append(c.get("mac_address"))
                        break
            except Exception:
                pass

    return list(dict.fromkeys(resolved))

def auto_heal_boot_params(token, target_images=None):
    """Scans all registered Ubuntu images on Bootimus and ensures they have correct autoinstall boot parameters."""
    print("[-] Running self-healing audit on Bootimus image database...")
    try:
        images_res = api_request(f"{API_BASE}/images", token=token)
        target_basenames = [os.path.basename(t) for t in (target_images or [])]
        for img in extract_images(images_res):
            filename = img.get("filename", "")
            distro = img.get("distro", "")
            boot_method = img.get("boot_method", "")
            boot_params = img.get("boot_params", "")
            enabled = img.get("enabled", False)
            extracted = img.get("extracted", False)
            
            # Any GDC/honeywell bootstrap image should use kernel boot method and correct autoinstall params
            is_gdc_image = filename and (
                "gdc-bootstrap" in filename or 
                "honeywell" in filename or 
                filename.startswith("sync/") or
                any(tb in filename for tb in target_basenames)
            )
            
            if is_gdc_image:
                has_correct_params = (
                    "autoinstall" in boot_params and 
                    "ds=nocloud-net" in boot_params and
                    "iso-url=" in boot_params and
                    f"modprobe.blacklist={BOOT_MODPROBE_BLACKLIST}" in boot_params and
                    f"tpm_tis.interrupts={BOOT_TPM_INTERRUPTS}" in boot_params and
                    f"apparmor={BOOT_APPARMOR}" in boot_params and
                    BOOT_CONSOLE in boot_params and
                    "ramdisk_size=" in boot_params and
                    ("{{BASE_URL}}" in boot_params or "http://" in boot_params)
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
                    
                    iso_size = img.get("size", 0)
                    fixed_params = get_boot_params(filename, iso_size_bytes=iso_size)
                    
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
                        verify_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token, allow_404=True)
                        matching = [m for m in extract_images(verify_res) if m.get("filename") == filename]
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
    check_auth = False
    group_filter = None
    next_boot_image = None
    clear_next_boot = False
    target_mac = None
    all_targets = False
    target_nodes_raw = None
    cli_user = None
    cli_pass = None
    cli_provider = None
    cli_file = None

    for ca_flag in ["--check-auth", "--test-credentials", "--test-creds"]:
        if ca_flag in args:
            check_auth = True
            args.remove(ca_flag)
            break

    for u_flag in ["--user", "--bootimus-user"]:
        if u_flag in args:
            idx = args.index(u_flag)
            if idx + 1 < len(args):
                cli_user = args[idx+1]
                args.pop(idx+1)
                args.pop(idx)
            break

    for p_flag in ["--pass", "--bootimus-pass", "--password", "--bootimus-password"]:
        if p_flag in args:
            idx = args.index(p_flag)
            if idx + 1 < len(args):
                cli_pass = args[idx+1]
                args.pop(idx+1)
                args.pop(idx)
            break

    for m_flag in ["--secret-method", "---secret-method", "--secret-provider", "--bootimus-secret-method", "--bootimus-secret-provider"]:
        if m_flag in args:
            idx = args.index(m_flag)
            if idx + 1 < len(args):
                cli_provider = args[idx+1]
                args.pop(idx+1)
                args.pop(idx)
            break

    for f_flag in ["--secret-file", "--bootimus-secret-file"]:
        if f_flag in args:
            idx = args.index(f_flag)
            if idx + 1 < len(args):
                cli_file = args[idx+1]
                args.pop(idx+1)
                args.pop(idx)
            break

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

    if "--clear-next-boot" in args:
        clear_next_boot = True
        args.remove("--clear-next-boot")
        
    for nb_flag in ["--next-boot", "--set-next-boot"]:
        if nb_flag in args:
            idx = args.index(nb_flag)
            if idx + 1 < len(args):
                next_boot_image = args[idx+1]
                args.pop(idx+1)
                args.pop(idx)
            else:
                print(f"[!] Error: {nb_flag} requires an ISO filename.")
                sys.exit(1)
            break

    if "--all-targets" in args:
        all_targets = True
        args.remove("--all-targets")

    for t_flag in ["--targets", "--nodes"]:
        if t_flag in args:
            idx = args.index(t_flag)
            if idx + 1 < len(args):
                target_nodes_raw = args[idx+1]
                args.pop(idx+1)
                args.pop(idx)
            break

    if "--mac" in args:
        idx = args.index("--mac")
        if idx + 1 < len(args):
            target_mac = args[idx+1]
            args.pop(idx+1)
            args.pop(idx)
        else:
            print("[!] Error: --mac requires a MAC address.")
            sys.exit(1)
            
    if check_auth:
        username, password = get_bootimus_credentials(
            cli_user=cli_user,
            cli_pass=cli_pass,
            cli_provider=cli_provider,
            cli_file=cli_file,
        )
        print(f"[-] Pre-flight check: Testing Bootimus credentials at {BOOTIMUS_API_HOST}:{BOOTIMUS_API_PORT}...")
        try:
            login_res = api_request(
                f"{API_BASE}/login",
                method="POST",
                data={"username": username, "password": password},
                retries=2,
                retry_delay=2,
                timeout=10,
            )
            token = login_res.get("data", {}).get("token")
            if token:
                print(f"[x] Pre-flight SUCCESS: Authenticated successfully with Bootimus as '{username}'.")
                sys.exit(0)
            else:
                print("[!] Pre-flight FAILURE: Login succeeded but no token returned.", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"[!] Pre-flight FAILURE: Unable to authenticate with Bootimus at {BOOTIMUS_API_HOST}:{BOOTIMUS_API_PORT}: {e}", file=sys.stderr)
            sys.exit(1)

    if (next_boot_image or clear_next_boot) and not target_mac and not all_targets and not target_nodes_raw:
        target_nodes_raw = os.environ.get("TARGET_TEST_MACHINES") or _ENV_DEFAULTS.get("TARGET_TEST_MACHINES")

    if next_boot_image or clear_next_boot:
        if not target_mac and not all_targets and not target_nodes_raw:
            print("[!] Error: Next-boot action requires --mac <mac_address>, --targets <IPs>, --all-targets, or export TARGET_TEST_MACHINES.")
            sys.exit(1)
            
        username, password = get_bootimus_credentials(
            cli_user=cli_user,
            cli_pass=cli_pass,
            cli_provider=cli_provider,
            cli_file=cli_file,
        )
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
            
        if all_targets:
            clients_res = api_request(f"{API_BASE}/clients", token=token)
            clients_list = clients_res.get("data", []) if isinstance(clients_res, dict) else []
            if not clients_list:
                print("[!] No clients registered in Bootimus.")
                sys.exit(1)
            for c in clients_list:
                mac = c.get("mac_address")
                name = c.get("name", mac)
                if not mac:
                    continue
                if clear_next_boot:
                    clear_client_next_boot(token, mac)
                    print(f"    [+] Cleared next-boot override for client {name} ({mac})")
                else:
                    set_client_next_boot(token, mac, next_boot_image)
                    print(f"    [+] Set next-boot to '{next_boot_image}' for client {name} ({mac})")
        elif target_mac:
            clean_mac = format_mac_address(target_mac)
            if clear_next_boot:
                clear_client_next_boot(token, clean_mac)
                print(f"[+] Cleared next-boot override for MAC {clean_mac}")
            else:
                set_client_next_boot(token, clean_mac, next_boot_image)
                print(f"[+] Successfully set next-boot to '{next_boot_image}' for MAC {clean_mac}")
        elif target_nodes_raw:
            parsed_targets = parse_target_machines(target_nodes_raw)
            resolved_macs = resolve_target_macs(parsed_targets, token=token)
            if not resolved_macs:
                print(f"[!] Error: Could not resolve any MAC addresses from target nodes: {parsed_targets}")
                sys.exit(1)
            print(f"[-] Applying next-boot action across {len(resolved_macs)} resolved target nodes...")
            for mac in resolved_macs:
                if clear_next_boot:
                    clear_client_next_boot(token, mac)
                    print(f"    [+] Cleared next-boot override for MAC {mac}")
                else:
                    set_client_next_boot(token, mac, next_boot_image)
                    print(f"    [+] Set next-boot to '{next_boot_image}' for MAC {mac}")
        sys.exit(0)
            
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
    username, password = get_bootimus_credentials(
        cli_user=cli_user,
        cli_pass=cli_pass,
        cli_provider=cli_provider,
        cli_file=cli_file,
    )
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
            for img in extract_images(images_res):
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
    matching = [img for img in extract_images(images_res) if img.get("filename") == filename]
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
        images_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token, allow_404=True)
        # Manually filter returned images by exact filename to avoid defaulting to the first item (cascade1)
        matching_images = [img for img in extract_images(images_res) if img.get("filename") == filename]
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
    iso_size = image_data.get("size", 0)
    boot_params = get_boot_params(filename, iso_size_bytes=iso_size)
    
    print("[-] Updating boot method to 'kernel', setting distro to 'ubuntu', and configuring parameters...")
    update_data = {
        "boot_method": "kernel",
        "distro": "ubuntu",
        "boot_params": boot_params,
        "enabled": True
    }
    
    # We must fetch the current full object state so the PUT API does not reject missing fields
    images_res = api_request(f"{API_BASE}/images", token=token)
    img_match = [i for i in extract_images(images_res) if i.get("filename") == filename]
    
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
        verify_res = api_request(f"{API_BASE}/images?filename={urllib.parse.quote(filename)}", token=token, allow_404=True)
        matching_images = [img for img in extract_images(verify_res) if img.get("filename") == filename]
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
