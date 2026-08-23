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

"""
GDC Disk Provisioner - Lab Setup & Diagnostic Auditor

This script connects to the critical infrastructure components (Step CA,
GDC Companion, Bootimus, Nexus, Network settings) of the GDC local lab.
It is designed to be executed from a central management server or a personal
workstation inside the lab network.

Usage:
  ./bin/check-lab-setup.py          (Runs full standard audit)
  ./bin/check-lab-setup.py --verbose (Shows detailed diagnostics)
"""

import os
import sys
import argparse
import urllib.request
import urllib.error
import urllib.parse
import ssl
import json
import socket
from typing import Dict, Any, Tuple

# Add src/build to path to parse env files
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/build')))
try:
    from preseed_packages import parse_env_file
except ImportError:
    def parse_env_file(filepath):
        env_vars = {}
        if not os.path.exists(filepath):
            return env_vars
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    env_vars[key] = value
        return env_vars

# Global state
VERBOSE = False
LAB_CONFIG = {}

def log_info(msg):
    print(f"[-] {msg}")

def log_success(msg):
    print(f"[+] {msg}")

def log_warn(msg):
    print(f"[!] WARNING: {msg}")

def log_error(msg):
    print(f"[X] ERROR: {msg}")

def log_debug(msg):
    if VERBOSE:
        print(f"    [DEBUG] {msg}")

def check_tcp_port(host: str, port: int, timeout: int = 3) -> bool:
    """Checks if a TCP port is open on the target host."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except Exception:
        return False

def http_get(url: str, headers: dict = None, timeout: int = 5, verify_ssl: bool = False) -> Tuple[bool, int, str]:
    """Helper to perform HTTP GET requests."""
    if headers is None:
        headers = {}
    
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
            return True, response.getcode(), response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return False, e.code, e.read().decode('utf-8')
    except urllib.error.URLError as e:
        return False, 0, str(e.reason)
    except Exception as e:
        return False, 0, str(e)

def load_environment():
    """Loads variables from build.env and local.env."""
    global LAB_CONFIG
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    build_env = parse_env_file(os.path.join(project_root, "src/build/build.env"))
    local_env = parse_env_file(os.path.join(project_root, "src/build/local.env"))
    
    # Merge environments, local.env taking precedence
    for key, val in build_env.items():
        LAB_CONFIG[key] = val
    for key, val in local_env.items():
        LAB_CONFIG[key] = val

    log_debug(f"Loaded {len(LAB_CONFIG)} configuration variables.")

# ==============================================================================
# INDIVIDUAL SERVICE CHECKS
# ==============================================================================

def check_step_ca():
    """Audits the Step CA server configuration and reachability."""
    print("\n--- 1. Step CA Audit ---")
    ca_url = LAB_CONFIG.get("STEP_CA_URL")
    provisioner = LAB_CONFIG.get("STEP_PROVISIONER_NAME", "acme")
    
    if not ca_url or "example.com" in ca_url:
        log_warn(f"STEP_CA_URL is missing or uses default example: {ca_url}")
        log_warn("Please update 'src/build/local.env'.")
        return False

    log_info(f"Targeting Step CA at: {ca_url}")
    
    # Check domain resolution & port
    parsed = urllib.parse.urlparse(ca_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    
    if not check_tcp_port(host, port):
        log_error(f"Cannot reach Step CA TCP port {port} at {host}. Is the server up?")
        return False
    log_success(f"Network connectivity to Step CA {host}:{port} established.")

    # Check SAN (Subject Alternative Name)
    try:
        cmd = ["openssl", "s_client", "-connect", f"{host}:{port}", "-showcerts"]
        res = subprocess.run(cmd, input=b"", capture_output=True, timeout=5)
        if res.returncode != 0 and not res.stdout:
            log_warn("openssl s_client command failed or returned empty.")
        else:
            x509_cmd = ["openssl", "x509", "-noout", "-text"]
            x509_res = subprocess.run(x509_cmd, input=res.stdout.decode('utf-8', errors='ignore'), capture_output=True, text=True, check=True)
            if "Subject Alternative Name" in x509_res.stdout:
                # Basic string match to see if the host is covered
                if host in x509_res.stdout:
                    log_success(f"TLS Certificate includes valid SAN for '{host}'.")
                else:
                    log_error(f"TLS Certificate does NOT include SAN for '{host}'.")
                    # Strict validation mandates we fail if SAN is missing
                    return False
            else:
                log_error("No Subject Alternative Name extension found in the certificate!")
                return False
    except Exception as e:
        log_warn(f"Failed to check TLS SAN via openssl: {e}")

    # Check provisioners endpoint
    success, status, body = http_get(f"{ca_url}/provisioners", verify_ssl=False)
    if not success and status == 0:
        log_error(f"Failed to fetch Step CA provisioners: {body}")
        return False
        
    try:
        data = json.loads(body)
        
        # In case the API returns a dictionary, check if the provisioners are under a specific key (like "data" or "provisioners")
        # Step CA /provisioners typically returns a dictionary containing a 'provisioners' list
        if isinstance(data, dict):
            if "provisioners" in data:
                prov_list = data["provisioners"]
            elif "data" in data:
                prov_list = data["data"]
            else:
                prov_list = []
        else:
            prov_list = data

        # If it's a list but contains strings (unlikely for Step CA, but prevents AttributeError)
        if prov_list and isinstance(prov_list[0], str):
            log_error(f"Unexpected response format from Step CA: {prov_list}")
            return False

        found_provisioner = False
        for prov in prov_list:
            if isinstance(prov, dict) and prov.get("name") == provisioner:
                found_provisioner = True
                prov_type = prov.get("type", "").lower()
                has_password = bool(LAB_CONFIG.get("STEP_PROVISIONER_PASSWORD"))
                
                if prov_type == "acme":
                    log_success(f"ACME Provisioner '{provisioner}' found and correctly configured.")
                elif prov_type == "jwk" and has_password:
                    log_success(f"JWK Provisioner '{provisioner}' found. Configured for automated token generation.")
                elif prov_type == "jwk" and not has_password:
                    log_warn(f"JWK Provisioner '{provisioner}' found, but STEP_PROVISIONER_PASSWORD is empty. This will cause interactive prompts that break headless boots!")
                else:
                    log_warn(f"Provisioner '{provisioner}' is of type '{prov_type}', which may not be supported for headless boots.")
                break
                
        if not found_provisioner:
            log_error(f"Required provisioner '{provisioner}' was NOT found on the CA server.")
            try:
                available = [p.get('name') for p in prov_list if isinstance(p, dict)]
                log_info(f"Available provisioners: {available}")
            except Exception:
                pass
            return False
            
    except json.JSONDecodeError:
        log_warn("Received invalid JSON from Step CA provisioners endpoint.")
        
    return True

def check_gdc_companion():
    """Audits the GDC Companion fallback configuration and reachability."""
    print("\n--- 2. GDC Companion Audit ---")
    companion_url = LAB_CONFIG.get("INSTALL_COMPANION_BASE")
    api_key = LAB_CONFIG.get("INSTALL_COMPANION_API_KEY")
    
    if not companion_url or "example.com" in companion_url:
        log_warn(f"INSTALL_COMPANION_BASE is missing or uses default example: {companion_url}")
        return False

    if not api_key or "not-filled-in" in api_key:
        log_warn("INSTALL_COMPANION_API_KEY is not configured or uses default.")

    log_info(f"Targeting Companion at: {companion_url}")
    
    parsed = urllib.parse.urlparse(companion_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    
    if not check_tcp_port(host, port):
        log_error(f"Cannot reach GDC Companion TCP port {port} at {host}.")
        return False
    log_success(f"Network connectivity to GDC Companion established.")

    # Check health/ping endpoint if it exists (assuming /health or similar)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    health_url = companion_url.rstrip("/") + "/health"
    
    success, status, body = http_get(health_url, headers=headers, verify_ssl=False)
    if status == 200:
        log_success("Companion API health check passed.")
    elif status in (401, 403):
        log_warn("Companion API is reachable, but returned Unauthorized. Verify your INSTALL_COMPANION_API_KEY.")
    else:
        log_warn(f"Companion API /health endpoint returned HTTP {status}. Service might be starting or endpoint differs.")
        
    return True

def check_network_configs():
    """Audits static network definitions for collisions or missing parameters."""
    print("\n--- 3. Static Network Configuration Audit ---")
    
    machine_ip = LAB_CONFIG.get("BOOTSTRAP_MACHINE_IP_CIDR")
    machine_gw = LAB_CONFIG.get("BOOTSTRAP_MACHINE_GATEWAY")
    k8s_ip = LAB_CONFIG.get("BOOTSTRAP_K8S_IP_CIDR")
    k8s_gw = LAB_CONFIG.get("BOOTSTRAP_K8S_GATEWAY")
    
    issues = 0
    
    if not machine_ip or not machine_gw:
        log_error("Machine (Table 10) network parameters are incomplete.")
        issues += 1
    else:
        log_success(f"Machine network defined: {machine_ip} (Gateway: {machine_gw})")
        
    if not k8s_ip or not k8s_gw:
        log_warn("Kubernetes (Table 20) network parameters are incomplete.")
        issues += 1
    else:
        log_success(f"Kubernetes network defined: {k8s_ip} (Gateway: {k8s_gw})")
        
    if machine_ip and k8s_ip and machine_ip == k8s_ip:
        log_error("Machine IP CIDR and K8s IP CIDR are identical. VRF tables will collide!")
        issues += 1
        
    if issues == 0:
        return True
    return False

import subprocess

def check_bootimus_server():
    """Audits the Bootimus HTTP Orchestrator reachability."""
    print("\n--- 6. Bootimus Orchestrator Audit ---")
    pxe_host = LAB_CONFIG.get("PXE_SERVER_HOST")
    pxe_port = LAB_CONFIG.get("PXE_SERVER_PORT", "26000")
    
    if not pxe_host or "example-labs.com" in pxe_host:
        log_warn(f"PXE_SERVER_HOST is missing or uses default example: {pxe_host}")
        return False
    
    try:
        port_int = int(pxe_port)
    except ValueError:
        port_int = 80
        
    log_info(f"Targeting Bootimus at: {pxe_host}:{port_int}")
    if check_tcp_port(pxe_host, port_int):
        log_success(f"Bootimus HTTP service is REACHABLE on {pxe_host}:{port_int}.")
        return True
    else:
        log_error(f"Bootimus HTTP service is UNREACHABLE on {pxe_host}:{port_int}.")
        return False


    log_info(f"Targeting TFTP Server at: {pxe_host}:69")
    
    # TFTP RRQ for a dummy file "probe.txt"
    # Opcode 1 (RRQ), filename, 0, mode, 0
    payload = b"\x00\x01probe.txt\x00octet\x00"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        sock.sendto(payload, (pxe_host, 69))
        # Any response (even an error opcode 5) means a TFTP daemon is listening
        data, server = sock.recvfrom(1024)
        log_success(f"TFTP service is REACHABLE on {pxe_host}:69 (received daemon response).")
        return True
    except socket.timeout:
        log_error(f"TFTP service is UNREACHABLE on {pxe_host}:69 (timeout). Is the daemon running?")
        return False
    except Exception as e:
        log_error(f"TFTP service check failed: {e}")
        return False

def check_gcloud_config():
    """Audits the local gcloud CLI configuration for authentication and project ID."""
    print("\n--- 5. Google Cloud CLI (gcloud) Audit ---")
    
    # 1. Check if gcloud is installed
    res = subprocess.run(["which", "gcloud"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        log_error("gcloud CLI is not installed or not in PATH.")
        return False
        
    log_success("gcloud CLI is installed.")
    
    issues = 0
    
    # 2. Check authenticated account
    try:
        acct_res = subprocess.run(
            ["gcloud", "config", "get-value", "account"], 
            capture_output=True, text=True, check=True
        )
        account = acct_res.stdout.strip()
        if not account or account == "(unset)":
            log_error("No authenticated gcloud account found. Run 'gcloud auth login'.")
            issues += 1
        else:
            log_success(f"Authenticated as: {account}")
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to retrieve gcloud account: {e.stderr.strip()}")
        issues += 1
        
    # 3. Check active project
    try:
        proj_res = subprocess.run(
            ["gcloud", "config", "get-value", "project"], 
            capture_output=True, text=True, check=True
        )
        project = proj_res.stdout.strip()
        if not project or project == "(unset)":
            log_error("No active GCP project is set. Run 'gcloud config set project <PROJECT_ID>'.")
            issues += 1
        else:
            log_success(f"Active GCP Project: {project}")
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to retrieve gcloud project: {e.stderr.strip()}")
        issues += 1

    return issues == 0

def check_nexus_registry():
    """Audits the Nexus Apt/Docker local registry if specified."""
    print("\n--- 4. Sonatype Nexus Hub Audit ---")
    # Normally Nexus IP is determined during provisioning or set via an env var like NEXUS_IP 
    # For this audit, we will look for an override or inform the user.
    nexus_ip = LAB_CONFIG.get("NEXUS_IP")
    
    if not nexus_ip:
        log_info("NEXUS_IP is not explicitly set in environment configurations. Skipping direct Nexus checks.")
        log_info("Note: Nexus is usually hosted dynamically or on a dedicated lab node.")
        return True
        
    log_info(f"Targeting Nexus Hub at: {nexus_ip}")
    
    # Check Nexus UI port (8081)
    if check_tcp_port(nexus_ip, 8081):
        log_success(f"Nexus Web/API port (8081) is OPEN.")
    else:
        log_error(f"Nexus Web/API port (8081) is CLOSED on {nexus_ip}.")
        
    # Check Docker Proxy port (5001)
    if check_tcp_port(nexus_ip, 5001):
        log_success(f"Nexus Docker Proxy port (5001) is OPEN.")
    else:
        log_warn(f"Nexus Docker Proxy port (5001) is CLOSED on {nexus_ip}.")

    return True


def main():
    parser = argparse.ArgumentParser(description="Audit and diagnose GDC local lab setup.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed diagnostic output.")
    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    print("==============================================================================")
    print(" GDC BARE METAL - LOCAL LAB SETUP AUDITOR")
    print("==============================================================================")
    
    log_info("Loading configurations from src/build/build.env and local.env...")
    load_environment()
    
    step_ok = check_step_ca()
    comp_ok = check_gdc_companion()
    net_ok = check_network_configs()
    nex_ok = check_nexus_registry()
    gcloud_ok = check_gcloud_config()
    bootimus_ok = check_bootimus_server()
    
    print("\n==============================================================================")
    print(" AUDIT SUMMARY")
    print("==============================================================================")
    
    all_ok = True
    print(f"  Step CA Configuration : {'[OK]' if step_ok else '[FAIL/WARN]'}")
    print(f"  GDC Companion API     : {'[OK]' if comp_ok else '[FAIL/WARN]'}")
    print(f"  Network Definitions   : {'[OK]' if net_ok else '[FAIL/WARN]'}")
    print(f"  Nexus Offline Hub     : {'[OK]' if nex_ok else '[FAIL/WARN]'}")
    print(f"  Google Cloud CLI      : {'[OK]' if gcloud_ok else '[FAIL]'}")
    print(f"  Bootimus Orchestrator : {'[OK]' if bootimus_ok else '[FAIL]'}")
    
    if not (step_ok and comp_ok and net_ok and gcloud_ok and bootimus_ok):
        all_ok = False
        
    print("\n==============================================================================")
    if all_ok:
        log_success("All core lab services appear to be healthy and configured correctly.")
        sys.exit(0)
    else:
        log_error("One or more critical lab services failed the audit. Please review the warnings above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
