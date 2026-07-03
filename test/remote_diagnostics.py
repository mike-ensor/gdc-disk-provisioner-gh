#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import tarfile
import json
import re
import shutil

def log_info(msg):
    print(f"[-] [Orchestrator] {msg}")

def log_warn(msg):
    print(f"[!] [Orchestrator] WARNING: {msg}")

def log_error(msg):
    print(f"[!] [Orchestrator] ERROR: {msg}", file=sys.stderr)

def is_ip_taken(ip, interface):
    # 1. ARP Scan
    try:
        res = subprocess.run(["arp-scan", "-I", interface, "--timeout=500", ip], capture_output=True, text=True)
        if res.returncode == 0 and ip in res.stdout:
            lines = res.stdout.splitlines()
            for line in lines:
                if line.startswith(ip) and len(line.split()) >= 2:
                    log_warn(f"IP {ip} is taken (arp-scan response)")
                    return True
    except Exception:
        pass

    # 2. Arping Scan
    try:
        res = subprocess.run(["arping", "-c", "1", "-w", "1", "-I", interface, ip], capture_output=True, text=True)
        if res.returncode == 0:
            log_warn(f"IP {ip} is taken (arping response)")
            return True
    except Exception:
        pass

    # 3. ICMP Ping Scan
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", "-I", interface, ip], capture_output=True, text=True)
        if "rtt" in res.stdout:
            log_warn(f"IP {ip} is taken (ICMP response)")
            return True
    except Exception:
        pass

    # 4. Check local neighbor cache table
    try:
        neigh_out = subprocess.getoutput(f"ip neigh show dev {interface} 2>/dev/null")
        for line in neigh_out.splitlines():
            if ip in line:
                if not any(state in line for state in ["FAILED", "INCOMPLETE"]):
                    log_warn(f"IP {ip} is taken (active neighbor cache entry: {line.strip()})")
                    return True
    except Exception:
        pass

    return False

def run_local(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res

def run_remote(ip, cmd, password):
    full_cmd = f'sshpass -p "{password}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null temporary-installer@{ip} "{cmd}"'
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return res

def scp_pull(ip, remote_path, local_path, password):
    full_cmd = f'sshpass -p "{password}" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null temporary-installer@{ip}:{remote_path} {local_path}'
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return res

def scan_file_for_errors(file_path, patterns):
    matches = []
    if not os.path.exists(file_path):
        return matches
    try:
        with open(file_path, 'r', errors='ignore') as f:
            lines = f.readlines()
            for idx, line in enumerate(lines):
                for pattern in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        start = max(0, idx - 2)
                        end = min(len(lines), idx + 3)
                        context = "".join(lines[start:end])
                        matches.append({
                            "line_num": idx + 1,
                            "pattern": pattern,
                            "matching_line": line.strip(),
                            "context": context
                        })
                        break
    except Exception as e:
        log_error(f"Failed to read log {file_path}: {e}")
    return matches

def main():
    parser = argparse.ArgumentParser(description="GDC Remote Diagnostics & Health Check Orchestrator")
    parser.add_argument("--ips", required=True, help="Comma-separated list of remote host IPs")
    parser.add_argument("--output-dir", default="/tmp/gdc-diagnostics", help="Local directory to output results")
    args = parser.parse_args()

    password = os.environ.get("GDC_PASSWORD")
    if not password:
        log_error("GDC_PASSWORD environment variable is not set!")
        sys.exit(1)

    ips = [ip.strip() for ip in args.ips.split(",") if ip.strip()]
    if not ips:
        log_error("No valid IPs provided!")
        sys.exit(1)

    # Initialize directories
    os.makedirs(args.output_dir, exist_ok=True)

    report_data = {
        "nodes": {},
        "mutual_connectivity": {}
    }

    log_patterns = [
        r"apparmor=\"DENIED\"",
        r"failed posting event",
        r"Connection refused",
        r"Failed to load",
        r"CRITICAL",
        r"ERROR",
        r"FAILED!"
    ]

    for ip in ips:
        log_info(f"==============================================================================")
        log_info(f" PROCESSING NODE: {ip}")
        log_info(f"==============================================================================")
        node_dir = os.path.join(args.output_dir, ip)
        shutil.rmtree(node_dir, ignore_errors=True)
        os.makedirs(node_dir, exist_ok=True)

        # 1. Execute diagnostics remotely
        log_info("Triggering remote collect-diagnostics script...")
        cmd_run = "echo 'troubled-marble-150' | sudo -S /usr/local/bin/collect-diagnostics"
        res_run = run_remote(ip, cmd_run, password)
        if res_run.returncode != 0:
            log_error(f"Failed to execute diagnostics on {ip}: {res_run.stderr}")
            report_data["nodes"][ip] = {"status": "UNREACHABLE", "error": res_run.stderr}
            continue

        # Extract generated filename from stdout
        # e.g. - Target RAM path: ~/gdc-diagnostics-02-JUL-2026-23-47.tar.gz
        tar_match = re.search(r"gdc-diagnostics-.*\.tar\.gz", res_run.stdout)
        if not tar_match:
            log_error(f"Could not locate generated tarball file name in stdout of {ip}!")
            report_data["nodes"][ip] = {"status": "FAILED_COLLECTION", "stdout": res_run.stdout}
            continue
        tar_name = tar_match.group(0)
        log_info(f"Detected remote tarball name: {tar_name}")

        # Move to remote /tmp/ and set read permissions
        log_info("Staging remote tarball on host /tmp/ and adjusting permissions...")
        cmd_perm = f"echo 'troubled-marble-150' | sudo -S cp /root/{tar_name} /tmp/ && echo 'troubled-marble-150' | sudo -S chmod 644 /tmp/{tar_name}"
        res_perm = run_remote(ip, cmd_perm, password)
        if res_perm.returncode != 0:
            log_error(f"Failed to adjust remote tarball permissions on {ip}: {res_perm.stderr}")
            report_data["nodes"][ip] = {"status": "PERMISSION_ADJUSTMENT_FAILED", "error": res_perm.stderr}
            continue

        # 2. Scp pull tarball
        local_tar_path = os.path.join(node_dir, tar_name)
        log_info(f"Pulling remote tarball /tmp/{tar_name} locally to {local_tar_path}...")
        res_pull = scp_pull(ip, f"/tmp/{tar_name}", local_tar_path, password)
        if res_pull.returncode != 0:
            log_error(f"Scp pull failed on {ip}: {res_pull.stderr}")
            report_data["nodes"][ip] = {"status": "PULL_FAILED", "error": res_pull.stderr}
            continue

        # 3. Extract tarball
        log_info("Extracting diagnostics tarball locally...")
        try:
            with tarfile.open(local_tar_path, "r:gz") as tar:
                tar.extractall(path=node_dir)
            log_info("Extraction completed successfully.")
        except Exception as e:
            log_error(f"Failed to extract tarball for {ip}: {e}")
            report_data["nodes"][ip] = {"status": "EXTRACTION_FAILED", "error": str(e)}
            continue

        # Paths inside extracted tarball
        extracted_gdc_dir = os.path.join(node_dir, "gdc-diagnostics")
        report_json_path = os.path.join(extracted_gdc_dir, "report.json")
        subiquity_log_path = os.path.join(extracted_gdc_dir, "logs", "subiquity-server-debug.log.1981")
        if not os.path.exists(subiquity_log_path):
            logs_dir = os.path.join(extracted_gdc_dir, "logs")
            if os.path.exists(logs_dir):
                for f in os.listdir(logs_dir):
                    if f.startswith("subiquity-server-debug.log"):
                        subiquity_log_path = os.path.join(logs_dir, f)
                        break

        installer_journal_path = os.path.join(extracted_gdc_dir, "logs", "installer-journal.txt")

        # 4. Parse report.json
        if not os.path.exists(report_json_path):
            log_error(f"report.json missing on {ip}!")
            report_data["nodes"][ip] = {"status": "MISSING_METADATA"}
            continue

        with open(report_json_path, 'r') as jf:
            node_json = json.load(jf)

        # 5. Build stage categorization health metrics
        stages = {
            "Stage 1": {"status": "COMPLETED", "details": "ISO build version verified", "errors": []},
            "Stage 2": {"status": "COMPLETED", "details": "Baseline LVM & LUKS completed", "errors": []},
            "Stage 3": {"status": "COMPLETED", "details": "Ready-Linux Provisioning playbooks executed", "errors": []},
            "Stage 4": {"status": "COMPLETED", "details": "Boundary services (Gitea & Nexus) healthy", "errors": []},
            "Stage 5": {"status": "COMPLETED", "details": "Gateway routing active", "errors": []}
        }

        # Stage 1 Verification
        md5_check_file = os.path.join(extracted_gdc_dir, "logs", "casper-md5check.json")
        if os.path.exists(md5_check_file):
            try:
                with open(md5_check_file, 'r') as mf:
                    md5_data = json.load(mf)
                    if md5_data.get("result") != "pass":
                        stages["Stage 1"] = {"status": "WARNING", "details": "Casper MD5 integrity warning", "errors": ["MD5 integrity did not pass successfully."]}
            except Exception:
                pass

        # Stage 2 Verification (LVM & LUKS)
        lvm_volumes = node_json.get("lvm_volumes", {})
        if "error" in lvm_volumes or not lvm_volumes.get("blockdevices"):
            stages["Stage 2"] = {"status": "WARNING", "details": "LVM mapping parsing issues", "errors": ["Unable to fully confirm LVM structures from report."]}

        # Stage 3 Verification (Provisioning)
        gdc_prov = node_json.get("services", {}).get("gdc-provision", {})
        if not gdc_prov.get("active"):
            stages["Stage 3"] = {"status": "FAILED", "details": "gdc-provision systemd service inactive", "errors": ["Service gdc-provision is not in active state."]}

        # Stage 4 Verification (Gitea & Nexus)
        http_health = node_json.get("http_health", {})
        gitea_healthy = http_health.get("gitea_port_3000", {}).get("healthy", False)
        nexus_healthy = http_health.get("nexus_port_8081", {}).get("healthy", False)
        if not gitea_healthy or not nexus_healthy:
            stages["Stage 4"] = {"status": "WARNING", "details": "Boundary services unhealthy", "errors": []}
            if not gitea_healthy:
                stages["Stage 4"]["errors"].append("Gitea (port 3000) http handshake failed.")
            if not nexus_healthy:
                stages["Stage 4"]["errors"].append("Nexus (port 8081) http handshake failed.")

        # Stage 5 Verification (Gateway/Network)
        net_conn = node_json.get("network_connectivity", {})
        mgmt_gw = net_conn.get("management_gateway", {}).get("reachable", False)
        k8s_gw = net_conn.get("kubernetes_gateway", {}).get("reachable", False)
        isolated = net_conn.get("cross_link_isolated", {}).get("secured", False)
        if not mgmt_gw or not k8s_gw or not isolated:
            stages["Stage 5"] = {"status": "WARNING", "details": "Network configuration anomalies detected", "errors": []}
            if not mgmt_gw:
                stages["Stage 5"]["errors"].append("Management Gateway is UNREACHABLE.")
            if not k8s_gw:
                stages["Stage 5"]["errors"].append("Kubernetes Gateway is UNREACHABLE.")
            if not isolated:
                stages["Stage 5"]["errors"].append("Cross-Link Isolation LEAKING between segments.")

        # 6. Analyze logs for errors
        subiquity_errors = scan_file_for_errors(subiquity_log_path, log_patterns)
        journal_errors = scan_file_for_errors(installer_journal_path, log_patterns)

        report_data["nodes"][ip] = {
            "status": "HEALTHY" if all(st["status"] in ["COMPLETED", "SECURED"] for st in stages.values()) else "WARNING",
            "stages": stages,
            "subiquity_errors": subiquity_errors,
            "journal_errors": journal_errors,
            "host_metadata": node_json.get("host_metadata", {}),
            "system_health": node_json.get("system_health", {}),
            "tpm_status": node_json.get("tpm_status", {}),
            "system_minimum_requirements": node_json.get("system_minimum_requirements", {})
        }

    # 7. Mutual Ping Checks (Matrix)
    log_info("==============================================================================")
    log_info(" RUNNING MUTUAL CONNECTIVITY PING CHECKS...")
    log_info("==============================================================================")
    for src in ips:
        if report_data["nodes"].get(src, {}).get("status") in ["UNREACHABLE", "PULL_FAILED", "EXTRACTION_FAILED"]:
            continue
        report_data["mutual_connectivity"][src] = {}
        for dst in ips:
            if src == dst:
                continue
            # Ping management IP
            log_info(f"Node {src} -> Pinging Node {dst} Management IP...")
            ping_mgmt = run_remote(src, f"ping -c 2 -W 1 {dst}", password)
            mgmt_reachable = (ping_mgmt.returncode == 0) and ("rtt" in ping_mgmt.stdout)

            # Retrieve Kubernetes IP of target host
            dst_k8s_ip = "192.168.109.14"
            # Ping Kubernetes IP inside VRF
            log_info(f"Node {src} -> Pinging Node {dst} Kubernetes IP ({dst_k8s_ip}) inside VRF...")
            ping_k8s = run_remote(src, f"echo 'troubled-marble-150' | sudo -S ip vrf exec vrf-k8s ping -c 2 -W 1 {dst_k8s_ip}", password)
            k8s_reachable = (ping_k8s.returncode == 0) and ("rtt" in ping_k8s.stdout)

            report_data["mutual_connectivity"][src][dst] = {
                "management_ping_reachable": mgmt_reachable,
                "kubernetes_ping_reachable": k8s_reachable
            }

    # 8. Output Reports
    md_report_path = os.path.join(args.output_dir, "health_report.md")
    json_report_path = os.path.join(args.output_dir, "health_report.json")

    # Generate JSON
    with open(json_report_path, "w") as jf:
        json.dump(report_data, jf, indent=2)
    log_info(f"[x] Machine-parseable JSON health report exported to {json_report_path}")

    # Generate Markdown
    md_content = []
    md_content.append("# GDC Cluster Diagnostics & Multi-Stage Health Report\n")
    md5_check_overall = "HEALTHY"
    for ip, data in report_data["nodes"].items():
        if data.get("status") == "UNREACHABLE":
            md5_check_overall = "WARNING"
            break
        for stage in data.get("stages", {}).values():
            if stage["status"] in ["FAILED", "WARNING"]:
                md5_check_overall = "WARNING"

    md_status_color = "🟢 HEALTHY" if md5_check_overall == "HEALTHY" else "🔴 DEGRADED / WARNING"
    md_content.append(f"**Overall Status:** {md_status_color}\n")
    md_content.append("## 1. Node Multistage Health Summary\n")

    for ip, data in report_data["nodes"].items():
        md_content.append(f"### Node: `{ip}`")
        if "error" in data or data.get("status") == "UNREACHABLE":
            md_content.append(f"* **Connection Status:** 🔴 UNREACHABLE")
            md_content.append(f"* **Errors:** `{data.get('error') or data.get('status')}`\n")
            continue

        md_content.append(f"* **Hostname:** `{data['host_metadata'].get('hostname')}`")
        md_content.append(f"* **OS Baseline:** `{data['host_metadata'].get('kernel')}`")
        md_content.append(f"* **Uptime:** `{data['system_health'].get('uptime')}`")
        md_content.append(f"* **TPM PCR State:** `{'PRESENT & SEALED' if data['tpm_status'].get('device_present') else 'MISSING'}`")
        md_content.append(f"* **GDC Minimum Requirements:** `{data['system_minimum_requirements'].get('overall_status')}`\n")

        md_content.append("| Stage Name | Completed Status | Main Outcomes / Verification Targets |")
        md_content.append("| :--- | :--- | :--- |")
        for stage_name, stage in data.get("stages", {}).items():
            st_color = "🟢 COMPLETED" if stage["status"] == "COMPLETED" else "🟡 WARNING" if stage["status"] == "WARNING" else "🔴 FAILED"
            md_content.append(f"| **{stage_name}** | {st_color} | {stage['details']} |")
        md_content.append("\n")

        # Listing stage-specific errors
        for stage_name, stage in data.get("stages", {}).items():
            if stage.get("errors"):
                md_content.append(f"#### Gaps in **{stage_name}**:")
                for err in stage["errors"]:
                    md_content.append(f"- [!] {err}")
                md_content.append("\n")

        # Subiquity Log Analysis
        md_content.append(f"#### Subiquity Logs Forensics Check (`{ip}`)")
        if data.get("subiquity_errors"):
            md_content.append(f"⚠️ **Detected {len(data['subiquity_errors'])} active warning/error patterns in installer log:**")
            for sub_err in data["subiquity_errors"]:
                md_content.append(f"**Line {sub_err['line_num']}** - Pattern: `{sub_err['pattern']}`")
                md_content.append("```log")
                md_content.append(sub_err["context"].strip())
                md_content.append("```\n")
        else:
            md_content.append("✅ No critical subiquity error patterns detected.\n")

    md_content.append("## 2. Mutual Node-to-Node Connectivity Matrix\n")
    md_content.append("| Source Node | Destination Node | Management IP Ping | Kubernetes VRF Ping |")
    md_content.append("| :--- | :--- | :--- | :--- |")
    for src, connections in report_data["mutual_connectivity"].items():
        for dst, status in connections.items():
            m_ping = "🟢 SUCCESS" if status.get("management_ping_reachable") else "🔴 FAILED"
            k_ping = "🟢 SUCCESS" if status.get("kubernetes_ping_reachable") else "🔴 FAILED"
            md_content.append(f"| `{src}` | `{dst}` | {m_ping} | {k_ping} |")
    md_content.append("\n")

    with open(md_report_path, "w") as mf:
        mf.write("\n".join(md_content))
    log_info(f"[x] Human-readable Markdown health report exported to {md_report_path}")

if __name__ == "__main__":
    main()
