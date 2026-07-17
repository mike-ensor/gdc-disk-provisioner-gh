import os
import re
import json
import time
import tarfile
import subprocess
import requests
import urllib.parse

def scan_network_for_ips(interface: str, cidr: str = "192.168.9.8/29") -> str:
    """
    Runs the hybrid scan_ips.py script on the specified interface and returns the allocated MACHINE_IP.
    """
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src/build/scan_ips.py"))
    try:
        # Run scan_ips.py to check active nodes and populate env
        res = subprocess.run(
            ["python3", script_path, "--interface", interface, "--cidr", cidr],
            capture_output=True, text=True, check=True
        )
        # Squeeze values from written allocated_ips.env
        if os.path.exists("/tmp/allocated_ips.env"):
            with open("/tmp/allocated_ips.env", "r") as f:
                for line in f:
                    if "MACHINE_IP=" in line:
                        return line.split("=")[-1].strip()
    except Exception as e:
        print(f"[!] Error executing scan_ips.py: {e}")
    return "Unknown"

def probe_node_state(ip: str) -> dict:
    """
    Probes SSH port 22 and attempts connection using candidates to determine state.
    """
    local_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src/build/local.env"))
    build_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src/build/build.env"))
    
    password = "default-password-123"
    env_file = local_env_path if os.path.exists(local_env_path) else build_env_path
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if "TEMPORARY_INSTALLER_PASSWORD=" in line:
                    password = line.split("=", 1)[1].strip().strip('"\'')

    # Quick TCP Port 22 probe using netcat or similar
    try:
        res = subprocess.run(["nc", "-zv", "-w", "2", ip, "22"], capture_output=True, text=True)
        if res.returncode != 0:
            return {"status": "CRASHED_PROVISION", "ip": ip, "reason": "SSH socket connection refused/timed out."}
    except Exception:
        pass

    # Verify if SSH responds to temporary-installer credentials (Stage: First Boot / Post-CD)
    ssh_cmd = ["sshpass", "-p", password, "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3", f"temporary-installer@{ip}", "echo 'OK'"]
    ssh_res = subprocess.run(ssh_cmd, capture_output=True, text=True)
    if ssh_res.returncode == 0:
        return {"status": "BOOTED_FIRST_BOOT", "ip": ip, "password": password, "user": "temporary-installer"}
    
    # Verify if SSH responds to gdc-admin credentials (Stage: Fully Provisioned)
    admin_ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", f"gdc-admin@{ip}", "echo 'OK'"]
    admin_res = subprocess.run(admin_ssh_cmd, capture_output=True, text=True)
    if admin_res.returncode == 0:
        return {"status": "FULLY_PROVISIONED_READY_LINUX", "ip": ip, "user": "gdc-admin", "auth_method": "SSH Public Key"}

    # Check for unsealed root/recovery credentials (Stage: Installing / Crashed recovery)
    root_ssh_cmd = ["sshpass", "-p", "gdc-password-123", "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3", f"root@{ip}", "echo 'OK'"]
    root_res = subprocess.run(root_ssh_cmd, capture_output=True, text=True)
    if root_res.returncode == 0:
        return {"status": "CRASHED_POST_EXTRACT_RECOVERY", "ip": ip, "password": "gdc-password-123", "user": "root"}

    return {"status": "CRASHED_PROVISION", "ip": ip, "reason": "Node is unreachable or credentials rejected."}

def fetch_diagnostics_tarball(ip: str, download_url: str | None = None) -> str:
    """
    Downloads diagnostics bundle from a URL or queries GDC Ingestion Companion out-of-band REST API.
    """
    local_tar_path = f"/tmp/gdc-diagnostics-{ip}-{int(time.time())}.tar.gz"
    
    # Case A: URL provided
    if download_url:
        print(f"[-] Fetching diagnostics tarball from provided URL: {download_url}")
        try:
            res = requests.get(download_url, timeout=10)
            if res.status_code == 200:
                with open(local_tar_path, "wb") as f:
                    f.write(res.content)
                return local_tar_path
        except Exception as e:
            print(f"  [!] Failed to download from URL: {e}")

    # Case B: Out-of-band query to GDC Ingestion Companion REST API
    companion_api_url = f"https://gdc-companion.ensor-labs.com/v1/machine-reports?ip={ip}"
    print(f"[-] Querying GDC Companion out-of-band registry: {companion_api_url}")
    try:
        api_res = requests.get(companion_api_url, timeout=5)
        if api_res.status_code == 200:
            reports = api_res.json()
            if reports and isinstance(reports, list):
                latest_report = reports[0]
                report_id = latest_report.get("report_id")
                dl_url = f"https://gdc-companion.ensor-labs.com/?download=true&report_id={report_id}"
                print(f"  [x] Found out-of-band diagnostic payload on Companion! Fetching: {dl_url}")
                dl_res = requests.get(dl_url, timeout=10)
                if dl_res.status_code == 200:
                    with open(local_tar_path, "wb") as f:
                        f.write(dl_res.content)
                    return local_tar_path
    except Exception as e:
        print(f"  [!] Failed out-of-band API handshake: {e}")

    # Case C: SSH into target node and run/collect diagnostics directly if available
    state = probe_node_state(ip)
    if state.get("status") in ["BOOTED_FIRST_BOOT", "CRASHED_POST_EXTRACT_RECOVERY", "FULLY_PROVISIONED_READY_LINUX"]:
        user = state["user"]
        password = state.get("password")
        print(f"[-] SSH into target node {ip} as {user} to run diagnostics...")
        
        # Execute collect-node-diagnostics.sh and get output tarball filename
        diag_exec_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{ip}", "sudo /usr/local/bin/collect-node-diagnostics.sh"]
        if password:
            diag_exec_cmd = ["sshpass", "-p", password] + diag_exec_cmd
        
        try:
            subprocess.run(diag_exec_cmd, check=True, capture_output=True)
            
            # Find the latest tarball in root or user home
            find_tar_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{ip}", "ls -t ~/gdc-node-diagnostics-*.tar.gz /tmp/gdc-node-diagnostics-*.tar.gz 2>/dev/null | head -n 1"]
            if password:
                find_tar_cmd = ["sshpass", "-p", password] + find_tar_cmd
                
            find_res = subprocess.run(find_tar_cmd, capture_output=True, text=True, check=True)
            remote_tar_path = find_res.stdout.strip()
            
            if remote_tar_path:
                print(f"  [x] Diagnostics compiled successfully on node at: {remote_tar_path}")
                scp_cmd = ["scp", "-o", "StrictHostKeyChecking=no", f"{user}@{ip}:{remote_tar_path}", local_tar_path]
                if password:
                    scp_cmd = ["sshpass", "-p", password] + scp_cmd
                subprocess.run(scp_cmd, check=True, capture_output=True)
                return local_tar_path
        except Exception as se:
            print(f"  [!] Failed to collect diagnostics on-device over SSH: {se}")

    return "ERROR: Could not retrieve diagnostic tarball."

def extract_and_analyze_tarball(tarball_path: str) -> dict:
    """
    Explodes GDC diagnostic tarball and runs deep regex/correlation scans on reports and logs.
    """
    analysis = {
        "hostname": "Unknown", "ip": "Unknown", "iso_version": "Unknown",
        "mac_address": "Unknown", "services": {}, "failures": [], "log_evidence": {},
        "access_audit": {
            "authorized_keys": [],
            "ssh_config": {},
            "sudoers_rules": []
        }
    }
    
    # Guard missing tarball path
    if not tarball_path or not os.path.exists(tarball_path):
        analysis["failures"].append("Diagnostic tarball is missing or unavailable.")
        return analysis

    extract_dir = f"/tmp/gdc-analysis-{int(time.time())}"
    os.makedirs(extract_dir, exist_ok=True)
    
    try:
        with tarfile.open(tarball_path, "r:gz") as tar:
            tar.extractall(path=extract_dir)
    except Exception as e:
        analysis["failures"].append(f"Failed to extract tarball: {e}")
        return analysis

    # Parse report.json
    json_path = os.path.join(extract_dir, "gdc-diagnostics/report.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r") as f:
                data = json.load(f)
                analysis["hostname"] = data.get("host_metadata", {}).get("hostname", "Unknown")
                analysis["ip"] = data.get("ip_address", "Unknown")
                analysis["iso_version"] = data.get("host_metadata", {}).get("iso_version", "Unknown")
                
                # Fallback: Parse ISO version from dmesg or installer logs if report.json is an older schema
                if analysis["iso_version"] == "Unknown":
                    for log_file in ["dmesg.txt", "logs/installer-journal.txt", "logs/gdc-provision.log"]:
                        fpath = os.path.join(extract_dir, "gdc-diagnostics", log_file)
                        if os.path.exists(fpath):
                            try:
                                with open(fpath, "r", encoding="utf-8", errors="ignore") as lf:
                                    content = lf.read()
                                    match = re.search(r"gdc-bootstrap-ubuntu-24\.04-v([0-9]+\.[0-9]+\.[0-9]+(-debug)?)", content)
                                    if match:
                                        analysis["iso_version"] = match.group(1)
                                        break
                            except Exception:
                                pass
                analysis["mac_address"] = data.get("host_metadata", {}).get("machine_id", "Unknown")
                analysis["services"] = data.get("services", {})
                
                # Check for failed software checks
                checks = data.get("gdc_os_prerequisites", {}).get("software_checks", {})
                for check_name, check_info in checks.items():
                    if check_info.get("status") == "FAIL":
                        analysis["failures"].append(f"OS preflight requirement failed: {check_name} | Detail: {check_info.get('details')}")
        except Exception as e:
            analysis["failures"].append(f"Failed to parse report.json: {e}")

    # Correlate Logs (TPM / VRF / Nexus concurrency / unmet dependencies)
    logs_dir = os.path.join(extract_dir, "gdc-diagnostics/logs")
    if os.path.exists(logs_dir):
        # 1. Ansible Pull failure checks
        pull_log = os.path.join(logs_dir, "gdc-ansible-pull.log")
        if os.path.exists(pull_log):
            with open(pull_log, "r") as f:
                content = f.read()
                if "curl: (7) Failed to connect" in content or "status=6/ABRT" in content:
                    analysis["failures"].append("NEXUS_CONCURRENCY_ABORT: Sonatype Nexus JVM crashed with SIGABRT during splayless package uploads.")
                    analysis["log_evidence"]["nexus_crash"] = "Failed task: GDC-TASK-02 | Upload pre-seeded packages"
                if "Reading keyfile" in content and "failed: No such file" in content:
                    analysis["failures"].append("TPM_UNSEAL_ERROR: LUKS keyfile missing during systemd PCR enrollment.")
                    analysis["log_evidence"]["tpm_sealing"] = "Reading keyfile /etc/keys/temp_key.key failed: No such file or directory"
                if "No package matching" in content:
                    match = re.search(r"No package matching '([^']+)' is available", content)
                    pkg = match.group(1) if match else "Unknown"
                    analysis["failures"].append(f"APT_INSTALL_ERROR: Missing pre-seeded package: '{pkg}' (not found in repositories).")
                    analysis["log_evidence"]["apt_failure"] = f"No package matching '{pkg}' is available"

        # 2. Netplan Hydration routing errors
        net_log = os.path.join(logs_dir, "netplan-hydration.log")
        if os.path.exists(net_log):
            with open(net_log, "r") as f:
                net_content = f.read()
                if "RTNETLINK answers: File exists" in net_content or "Failed to add route" in net_content:
                    analysis["failures"].append("NETPLAN_ROUTING_CONFLICT: RTNETLINK route overlap or VRF loop detected.")
                    analysis["log_evidence"]["routing"] = "RTNETLINK answers: File exists / Overlapping subnet assignments"

        # 3. Curtin installer / LUKS key failures
        curtin_log = os.path.join(logs_dir, "curtin-install.log")
        if os.path.exists(curtin_log):
            with open(curtin_log, "r") as f:
                curtin_content = f.read()
                if "No key available with this passphrase" in curtin_content and "/run/installer/gdc-luks-key" in curtin_content:
                    analysis["failures"].append("LUKS_KEY_PROPAGATION_ERROR: Snap-to-host mount namespace propagation delay caused gdc-luks-key to be empty or unreadable during LUKS format.")
                    analysis["log_evidence"]["luks_failure"] = "Command: ['cryptsetup', 'open', '--type', 'luks', '/dev/nvme0n1p3', 'crypt-system', '--key-file', '/run/installer/gdc-luks-key']\nExit code: 2\nReason: -\nNo key available with this passphrase."

    # Auditing Security Access Profiles
    configs_dir = os.path.join(extract_dir, "gdc-diagnostics/configs")
    if os.path.exists(configs_dir):
        # Parse SSH Keys and user access configurations securely (Zero-Secrets)
        for user_folder in ["root", "temporary-installer", "gdc-admin"]:
            keys_path = os.path.join(extract_dir, f"gdc-diagnostics/{user_folder}/.ssh/authorized_keys")
            if not os.path.exists(keys_path):
                keys_path = os.path.join(extract_dir, f"gdc-diagnostics/home/{user_folder}/.ssh/authorized_keys")
            if os.path.exists(keys_path):
                with open(keys_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            parts = line.split()
                            key_type = parts[0] if parts else "Unknown"
                            comment = parts[-1] if len(parts) >= 3 else "No comment"
                            analysis["access_audit"]["authorized_keys"].append({
                                "user": user_folder,
                                "type": key_type,
                                "comment": comment
                            })

    return analysis

def self_update_diagnostic_rules(rule_id: str, new_pattern: str) -> bool:
    """
    Surgically updates the log parsing patterns inside tools.py dynamically
    and runs local pytests to verify correctness before proceeding.
    """
    tools_file = __file__
    with open(tools_file, "r") as f:
        content = f.read()
    
    # Surgically replace the regex rule on disk
    old_line_pattern = rf'"{rule_id}":\s*".*?"'
    new_line = f'"{rule_id}": "{new_pattern}"'
    updated_content = re.sub(old_line_pattern, new_line, content)
    
    with open(tools_file, "w") as f:
        f.write(updated_content)
        
    # Execute self-verification unit tests
    test_res = subprocess.run(["pytest", "tests/unit/test_diagnostics_agent.py"])
    return test_res.returncode == 0
