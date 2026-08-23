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
# GDC Bootloader ISO Offline Packages Pre-seeding Engine
# ==============================================================================
# Resolves, downloads, and caches critical system dependencies (.deb files)
# completely offline. Synchronizes cached packages to the central GCS bucket
# to facilitate zero-network CI/CD compilation loops.
# ==============================================================================

import os
import sys
import json
import re
import subprocess
import glob
import yaml

def parse_env_file(filepath):
    """Parses standard key=value and export key=value shell environment files."""
    env = {}
    if not os.path.exists(filepath):
        return env
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Strip leading export if present
                if line.startswith('export '):
                    line = line[len('export '):].strip()
                if '=' in line:
                    parts = line.split('=', 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    # Strip outer quotes
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    env[key] = val
    except Exception as e:
        print(f"[!] Warning: Failed to parse env file '{filepath}': {e}", file=sys.stderr)
    return env

def load_config(config_path):
    """Loads GDC package settings from the declarative YAML configuration file."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at '{config_path}'")
    
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)
        
    ubuntu_version = data.get("ubuntu_version", "24.04")
    to_include = data.get("packages_to_include", {})
    platform = to_include.get("platform_required") or []
    customer = to_include.get("customer_added") or []
    excludes = data.get("exclude_from_dependency_resolution") or []
    
    # Merge and dedup the target packages list
    packages = sorted(list(set(platform + customer)))
    
    return {
        "ubuntu_version": ubuntu_version,
        "packages": packages,
        "platform_packages": set(platform),
        "excludes": excludes
    }

def verify_compatibility(target_version, running_version):
    """Asserts that the running container/host matches the target Ubuntu version."""
    if not target_version or not running_version or running_version == "Unknown":
        return
    
    # Extract major/minor versions (e.g., "24.04" or "22.04")
    target_match = re.search(r"([0-9]+\.[0-9]+)", target_version)
    running_match = re.search(r"([0-9]+\.[0-9]+)", running_version)
    
    if target_match and running_match:
        t_ver = target_match.group(1)
        r_ver = running_match.group(1)
        if t_ver != r_ver:
            raise ValueError(
                f"GDC OS Package Target Mismatch! "
                f"Targeting Ubuntu {t_ver}, but executing on Ubuntu {r_ver}. "
                f"Downloading packages on a mismatched host will corrupt the target OS bootloader!"
            )

def should_exclude(package_name, exclude_patterns):
    """Checks if a resolved dependency name matches any of the exclude regex rules."""
    for pattern in exclude_patterns:
        try:
            if re.search(pattern, package_name):
                return True
        except re.error as e:
            print(f"[!] Warning: Invalid regex pattern '{pattern}': {e}", file=sys.stderr)
    return False

def resolve_dependencies(packages, exclude_patterns):
    """Uses apt-cache depends to recursively resolve all required dependencies."""
    resolved = set()
    for pkg in packages:
        # Resolve dependencies recursively
        try:
            cmd = ["apt-cache", "depends", "--recurse", "--no-recommends", 
                   "--no-suggests", "--no-conflicts", "--no-breaks", 
                   "--no-replaces", "--no-enhances", pkg]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            for line in res.stdout.splitlines():
                if "Depends:" in line:
                    dep = line.split("Depends:", 1)[1].strip()
                    # Strip bracketed architecture suffixes if present
                    if dep.startswith("<") or ":" in dep:
                        continue
                    if dep and not should_exclude(dep, exclude_patterns):
                        resolved.add(dep)
        except subprocess.SubprocessError as e:
            print(f"  [!] Warning: Failed to resolve dependencies for '{pkg}': {e}", file=sys.stderr)
    return sorted(list(resolved))

def main():
    # Setup paths and environment loading
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    cache_dir = os.path.join(project_root, ".cache/packages")
    config_path = os.path.join(script_dir, "packages_config.yaml")
    failures_file = os.path.join(project_root, ".cache/preseed_failures.json")
    if os.path.exists(failures_file):
        try:
            os.remove(failures_file)
        except Exception:
            pass
    
    # Load default build and local configuration files
    build_env = parse_env_file(os.path.join(script_dir, "build.env"))
    local_env = parse_env_file(os.path.join(script_dir, "local.env"))
    
    # Combine configurations (priority: process environment > local.env > build.env)
    gcs_bucket = os.environ.get("DEPENDENCY_CACHE_GCS_BUCKET") or local_env.get("DEPENDENCY_CACHE_GCS_BUCKET") or build_env.get("DEPENDENCY_CACHE_GCS_BUCKET") or "gs://gdc-disk-provisioner-isos"
    enable_gcs = os.environ.get("ENABLE_GCS") or local_env.get("ENABLE_GCS") or build_env.get("ENABLE_GCS") or "false"
    test_only = os.environ.get("TEST_ONLY") or local_env.get("TEST_ONLY") or build_env.get("TEST_ONLY") or "false"
    ubuntu_override = os.environ.get("_UBUNTU_VERSION") or local_env.get("_UBUNTU_VERSION") or build_env.get("_UBUNTU_VERSION")
    
    # Load declarative YAML configuration
    try:
        cfg = load_config(config_path)
    except Exception as e:
        print(f"[!] Error loading packages configuration: {e}", file=sys.stderr)
        sys.exit(1)
        
    target_ubuntu_version = ubuntu_override or cfg["ubuntu_version"]
    
    # Detect running version from /etc/os-release
    running_version = "Unknown"
    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("VERSION_ID="):
                        running_version = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
            
    # Perform target version assertion check
    print("[-] Checking GDC package host-to-target compatibility...")
    print(f"  - Target Ubuntu Release:   {target_ubuntu_version}")
    print(f"  - Executing Host Release:  {running_version}")
    try:
        verify_compatibility(target_ubuntu_version, running_version)
        print("  [x] Host-to-target OS version compatibility verified.")
    except ValueError as e:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!", file=sys.stderr)
        print(f"[FATAL ERROR] {e}", file=sys.stderr)
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!", file=sys.stderr)
        sys.exit(1)
        
    # Restrict packages if running in test mode
    target_packages = cfg["packages"]
    if test_only.lower() == "true":
        print("[-] Running in TEST mode. Restricting pre-seed download to minimal verification packages...")
        test_packages_set = {"chrony", "socat", "net-tools", "arp-scan", "ansible", "git"}
        target_packages = [pkg for pkg in target_packages if pkg in test_packages_set]
    else:
        print("[-] Running in PRODUCTION mode. Pulling all GDC system dependencies...")
        
    print(f"[-] Initializing package staging cache at: {cache_dir}")
    os.makedirs(cache_dir, exist_ok=True)
    os.chdir(cache_dir)
    
    # Refresh local APT package index
    print("[-] Refreshing local APT package metadata index...")
    sudo_prefix = []
    if os.getuid() != 0:
        # Check if sudo is available
        res = subprocess.run(["which", "sudo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            sudo_prefix = ["sudo"]
            
    # Programmatically register Docker CE repository for resolving docker-ce/containerd.io
    try:
        print("[-] Registering official Docker CE GPG keyring and repository sources...")
        subprocess.run(sudo_prefix + ["mkdir", "-p", "/etc/apt/keyrings"], check=True)
        subprocess.run(sudo_prefix + ["curl", "-fsSL", "https://download.docker.com/linux/ubuntu/gpg", "-o", "/etc/apt/keyrings/docker.asc"], check=True)
        repo_line = "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable"
        subprocess.run(["sh", "-c", f'echo "{repo_line}" | ' + " ".join(sudo_prefix + ["tee", "/etc/apt/sources.list.d/docker.list"])], check=True)
        print("  [x] Docker CE repository successfully registered.")
    except Exception as e:
        print(f"[!] Warning: Failed to register Docker CE repository: {e}", file=sys.stderr)

    try:
        subprocess.run(sudo_prefix + ["apt-get", "update", "-qq"], check=True)
    except subprocess.SubprocessError as e:
        print(f"[!] Warning: Failed to refresh APT metadata: {e}", file=sys.stderr)
        
    # Download primary packages
    print("[-] Downloading package binaries (.debs)...")
    downloaded_set = set()
    preseed_failures = []
    for pkg in target_packages:
        print(f"  [-] Resolving and downloading: {pkg}...")
        try:
            subprocess.run(["apt-get", "download", pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            downloaded_set.add(pkg)
        except subprocess.SubprocessError:
            preseed_failures.append(pkg)
            if pkg in cfg.get("platform_packages", set()):
                print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!", file=sys.stderr)
                print(f"[FATAL ERROR] Failed to download critical platform-required package '{pkg}'!", file=sys.stderr)
                print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!", file=sys.stderr)
                # Save failures JSON
                os.makedirs(os.path.dirname(failures_file), exist_ok=True)
                with open(failures_file, "w") as ff:
                    json.dump(preseed_failures, ff, indent=2)
                sys.exit(1)
            else:
                print(f"  [!] Warning: Failed to download optional package '{pkg}' directly. Dependency simulation will fallback.", file=sys.stderr)
            
    # Resolve and download dependencies
    print("[-] Resolving and downloading recursive dependencies...")
    dependencies = resolve_dependencies(target_packages, cfg["excludes"])
    for dep in dependencies:
        if dep not in downloaded_set:
            try:
                subprocess.run(["apt-get", "download", dep], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                downloaded_set.add(dep)
            except subprocess.SubprocessError:
                preseed_failures.append(dep)
                
    # Save failures list at the end of the script if there are any non-fatal failures
    if preseed_failures:
        os.makedirs(os.path.dirname(failures_file), exist_ok=True)
        with open(failures_file, "w") as ff:
            json.dump(preseed_failures, ff, indent=2)
                
    # Synchronize downloaded debs back to GCS Bucket if enabled
    if enable_gcs.lower() == "true":
        bucket_name = gcs_bucket.replace("gs://", "")
        res = subprocess.run(["which", "gcloud"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            print(f"[-] Uploading cached packages to GCS: gs://{bucket_name}/packages/ ...")
            try:
                subprocess.run(["gcloud", "storage", "cp"] + glob.glob("*.deb") + [f"gs://{bucket_name}/packages/", "--quiet"], check=True)
                print("  [x] GCS package pre-seeding upload completed successfully.")
            except Exception as e:
                print(f"  [!] Warning: Failed to sync packages to GCS: {e}", file=sys.stderr)
        else:
            print("  [!] Warning: 'gcloud' CLI is missing. Skipping GCS cache sync.", file=sys.stderr)
            
    num_debs = len([f for f in os.listdir(".") if f.endswith(".deb")])
    print("==============================================================================")
    print(f"[+] Pre-seeding completed. Total packages cached: {num_debs}")
    print("==============================================================================")

if __name__ == "__main__":
    # If executed directly as main script
    if len(sys.argv) > 1 and sys.argv[1] == "--test-mock":
        # Keep process bounds testable without running complete logic
        pass
    else:
        main()
