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

import os
import sys
import shutil
import subprocess
import hashlib
import tempfile

def log_info(msg):
    print(f"[-] {msg}")

def log_error(msg):
    print(f"[!] Error: {msg}", file=sys.stderr)

def parse_env_file(filepath):
    vars_dict = {}
    if not os.path.exists(filepath):
        return vars_dict
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                vars_dict[k.strip()] = v.strip().strip('"\'')
    return vars_dict

def sha256sum(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def verify_host_cache(filename, expected_sha, cache_dir):
    filepath = os.path.join(cache_dir, filename)
    if not os.path.exists(filepath):
        log_error(f"CACHED BINARY MISSING ON HOST: {filename} (Path: {filepath})")
        return False
    
    actual_sha = sha256sum(filepath)
    if actual_sha != expected_sha:
        log_error(f"CRYPTOGRAPHIC HASH MISMATCH ON HOST: {filename}!")
        print(f"    Expected: {expected_sha}", file=sys.stderr)
        print(f"    Actual:   {actual_sha}", file=sys.stderr)
        return False
    
    print(f"[x] Verified host cached binary: {filename} (Cryptographically valid)")
    return True

def main():
    print("==============================================================================")
    print("GDC Bootloader ISO Static Validation Suite (Tier 1 - Python)")
    print("==============================================================================")

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    envrc_path = os.path.join(project_root, ".envrc")
    build_env_path = os.path.join(project_root, "src/build/build.env")
    local_env_path = os.path.join(project_root, "src/build/local.env")
    dependencies_env_path = os.path.join(project_root, "src/dependencies.env")

    # Load version details from .envrc
    envrc = {}
    if os.path.exists(envrc_path):
        with open(envrc_path, 'r') as f:
            for line in f:
                if "export " in line and "=" in line:
                    k, v = line.replace("export ", "").strip().split("=", 1)
                    envrc[k.strip()] = v.strip().strip('"\'')

    # Load build.env and overlay with local.env if exists (GDC override pattern)
    build_env = parse_env_file(build_env_path)
    if os.path.exists(local_env_path):
        log_info(f"Sourcing local overrides from {local_env_path}...")
        local_env = parse_env_file(local_env_path)
        build_env.update(local_env)

    iso_version = os.environ.get("ISO_VERSION")
    if not iso_version and os.path.exists(os.path.join(project_root, "VERSION")):
        with open(os.path.join(project_root, "VERSION"), "r") as f:
            iso_version = f.read().strip()
    if not iso_version:
        iso_version = build_env.get("ISO_VERSION") or envrc.get("ISO_VERSION") or "0.1.14"
    project_id = os.environ.get("PROJECT_ID") or build_env.get("PROJECT_ID") or envrc.get("PROJECT_ID") or "anthos-bare-metal-lab-1"

    # Find the target ISO path
    companion_val = os.environ.get("GDC_COMPANION") or build_env.get("GDC_COMPANION") or envrc.get("GDC_COMPANION") or "TRUE"
    comp_suffix = "-no-comp" if str(companion_val).strip().upper() in ("FALSE", "0", "NO", "NONE") else ""
    target_iso_name = f"gdc-bootstrap-ubuntu-24.04-v{iso_version}{comp_suffix}-debug.iso"
    target_iso_path = os.path.join(project_root, "build-workspace/output", target_iso_name)

    if not os.path.exists(target_iso_path):
        # Fallback search
        output_dir = os.path.join(project_root, "build-workspace/output")
        iso_files = [f for f in os.listdir(output_dir) if f.endswith(".iso")] if os.path.exists(output_dir) else []
        if iso_files:
            target_iso_path = os.path.join(output_dir, iso_files[0])
        else:
            log_error(f"No compiled ISO file found. Run 'make -C src/build build' first.")
            sys.exit(1)

    print(f"[-] Target ISO: {target_iso_path}")
    size_bytes = os.path.getsize(target_iso_path)
    print(f"[-] Size: {round(size_bytes / (1024*1024*1024), 2)}G")

    # Check for xorriso
    print("[-] Checking static validation requirements...")
    if not shutil.which("xorriso"):
        log_error("'xorriso' is required but not installed.")
        sys.exit(1)

    # Load dependency expectations
    deps = parse_env_file(dependencies_env_path)
    cache_dir = os.path.join(project_root, ".cache/binaries")

    print("[-] Verifying local cached binaries on host...")
    host_cache_success = True
    if not verify_host_cache(deps.get("GITEA_BINARY_FILENAME", ""), deps.get("GITEA_BINARY_SHA256", ""), cache_dir):
        host_cache_success = False
    if not verify_host_cache(deps.get("NEXUS_PACKAGE_FILENAME", ""), deps.get("NEXUS_PACKAGE_SHA256", ""), cache_dir):
        host_cache_success = False
    if not verify_host_cache(deps.get("JRE_PACKAGE_FILENAME", ""), deps.get("JRE_PACKAGE_SHA256", ""), cache_dir):
        host_cache_success = False

    if not host_cache_success:
        log_error("Host cached binaries validation failed. Ensure dependencies are pulled.")
        sys.exit(1)

    # 3. File Inventory Checks (via xorriso non-root find)
    print("[-] Scanning ISO structural layout...")
    critical_files = [
        "/nocloud/user-data",
        "/nocloud/meta-data",
        "/custom-data/network-template.yaml",
        "/custom-data/configure_netplan.py",
        "/custom-data/generate_storage_config.sh",
        "/custom-data/gdc-collector",
        "/custom-data/security/cis-hardening-amd64.tar.gz",
        "/custom-data/auth/gcp-authentication.sh",
        "/custom-data/gitea/gitea",
        "/custom-data/nexus/nexus-bin/bin/nexus",
        "/boot/grub/grub.cfg"
    ]

    failed_checks = 0
    for target_file in critical_files:
        res = subprocess.run(["xorriso", "-indev", target_iso_path, "-find", target_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            print(f"[x] Found critical path: {target_file}")
        else:
            print(f"[ ] CRITICAL PATH MISSING: {target_file}", file=sys.stderr)
            failed_checks += 1

    if failed_checks > 0:
        log_error("File inventory check failed. ISO is missing structural paths.")
        sys.exit(1)
    print("[-] Layout verification completed successfully.")

    # 4. Extract & Validate compiled artifacts
    print("[-] Extracting dynamic parameters from compiled ISO...")
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create directories
        for sub_dir in ["nocloud", "custom-data/systemd", "boot/grub"]:
            os.makedirs(os.path.join(temp_dir, sub_dir), exist_ok=True)

        extract_files = [
            ("/nocloud/user-data", "nocloud/user-data"),
            ("/nocloud/meta-data", "nocloud/meta-data"),
            ("/custom-data/network-template.yaml", "custom-data/network-template.yaml"),
            ("/custom-data/systemd/gitea.service", "custom-data/systemd/gitea.service"),
            ("/custom-data/systemd/nexus.service", "custom-data/systemd/nexus.service"),
            ("/custom-data/systemd/gdc-provision.service", "custom-data/systemd/gdc-provision.service"),
            ("/custom-data/systemd/gdc-provision.timer", "custom-data/systemd/gdc-provision.timer"),
            ("/boot/grub/grub.cfg", "boot/grub/grub.cfg")
        ]

        for src, dest in extract_files:
            subprocess.run(["xorriso", "-osirrox", "on", "-indev", target_iso_path, "-extract", src, os.path.join(temp_dir, dest)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Assert AMD blacklist is present in extracted autoinstall user-data
        user_data_path = os.path.join(temp_dir, "nocloud/user-data")
        if os.path.exists(user_data_path):
            log_info("Asserting AMD blacklist is present in extracted autoinstall user-data...")
            with open(user_data_path, "r") as f:
                user_data_content = f.read()
            if "blacklist pcie_mp2_amd" not in user_data_content or "blacklist amd_sfh" not in user_data_content or "blacklist ccp" not in user_data_content:
                log_error("AMD Sensor Fusion Hub / CCP kernel blacklist is MISSING from user-data!")
                sys.exit(1)
            print("[x] Verified AMD Sensor Fusion Hub kernel blacklist is active in user-data.")
            
            raw_companion = build_env.get("GDC_COMPANION", build_env.get("BOOT_LOGGING", "TRUE"))
            companion_enabled = str(raw_companion).strip().upper() in ("TRUE", "1", "YES", "ALL", "BOTH")
            
            if companion_enabled:
                if "bootcmd:" not in user_data_content or "phone_home:" not in user_data_content:
                    log_error("bootcmd or phone_home sections are MISSING from user-data when GDC_COMPANION=TRUE!")
                    sys.exit(1)
                print("[x] Verified early-boot hosts mapping and phone_home are present and clean in user-data.")
                if "reporting:" not in user_data_content or "webhook:" not in user_data_content:
                    log_error("reporting or webhook sections are MISSING from user-data when GDC_COMPANION=TRUE!")
                    sys.exit(1)
                print("[x] Verified autoinstall webhook reporting is present and clean in user-data.")
            else:
                if "phone_home:" in user_data_content:
                    log_error("phone_home section is present in user-data but GDC_COMPANION=FALSE disables it!")
                    sys.exit(1)
                print("[x] Verified phone_home is omitted from user-data per GDC_COMPANION policy.")
                if "webhook:" in user_data_content:
                    log_error("reporting webhook section is present in user-data but GDC_COMPANION=FALSE disables it!")
                    sys.exit(1)
                print("[x] Verified autoinstall webhook reporting is omitted from user-data per GDC_COMPANION policy.")
                
            if "headers:" in user_data_content:
                log_error("Detected invalid 'headers:' block inside user-data! This will trigger a Subiquity crash.")
                sys.exit(1)

        print("[-] Running comprehensive artifacts static validation suite on extracted ISO components...")
        
        # Locate python binary from active .venv if present
        python_bin = sys.executable
        if os.path.exists(venv_py := os.path.join(project_root, ".venv/bin/python3")):
            python_bin = venv_py

        validate_script = os.path.join(project_root, "test/validate_artifacts.py")
        workspace_dir = os.path.join(project_root, "build-workspace")

        res_validate = subprocess.run([python_bin, validate_script, temp_dir, workspace_dir])
        if res_validate.returncode != 0:
            log_error("Artifacts static validation suite failed.")
            sys.exit(1)

    print("==============================================================================")
    print("[+] SUCCESS: ISO passes all Tier 1 structural validation checks!")
    print("==============================================================================")

if __name__ == "__main__":
    main()
