#!/usr/bin/env python3
import os
import sys
import argparse
import time
from tools import (
    scan_network_for_ips,
    probe_node_state,
    fetch_diagnostics_tarball,
    extract_and_analyze_tarball
)

def log_step(msg):
    print(f"[-] [Diagnostics-Agent] {msg}")

def log_success(msg):
    print(f"[x] [Diagnostics-Agent] SUCCESS: {msg}")

def log_error(msg):
    print(f"[!] [Diagnostics-Agent] ERROR: {msg}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="GDC Node Diagnostics & RCA Compiler Agent")
    parser.add_argument("--ip", help="Target node IP address")
    parser.add_argument("--interface", default="enp1s0", help="Local interface to scan on if IP is missing")
    parser.add_argument("--cidr", default="192.168.9.8/29", help="CIDR subnet range to scan if IP is missing")
    parser.add_argument("--bundle-url", help="Optional URL to download diagnostic tarball from")
    args = parser.parse_args()

    log_step("GDC Diagnostics Agent Team initialized.")

    # 1. Discovery Phase
    target_ip = args.ip
    if not target_ip:
        log_step(f"No target IP provided. Launching DiscoveryAgent on interface {args.interface}...")
        target_ip = scan_network_for_ips(args.interface, args.cidr)
        if not target_ip or target_ip == "Unknown":
            log_error("Could not discover any active GDC nodes on the network.")
            sys.exit(1)
        log_success(f"Discovered active GDC node: {target_ip}")
    else:
        log_step(f"Target node IP specified: {target_ip}")

    # 2. Connection & State Probe Phase
    log_step(f"Launching CollectionAgent to probe node state and credentials...")
    node_state = probe_node_state(target_ip)
    log_step(f"Probed node status: {node_state.get('status')}")
    if node_state.get("reason"):
         log_step(f"Probe detail: {node_state.get('reason')}")

    # 3. Collection Phase
    log_step(f"Retrieving diagnostics package from target node...")
    tarball_path = fetch_diagnostics_tarball(target_ip, args.bundle_url)
    if "ERROR" in tarball_path:
        log_error(f"Failed to gather diagnostics: {tarball_path}")
        sys.exit(1)
    log_success(f"Diagnostics bundle successfully staged locally at: {tarball_path}")

    # 4. Analysis Phase
    log_step("Launching AnalysisAgent to explode package and perform unified log correlation...")
    analysis_data = extract_and_analyze_tarball(tarball_path)
    
    # 5. RCA Generation Phase
    log_step("Launching RcaWriterAgent to synthesize Root Cause Analysis report...")
    
    iso_ver = analysis_data.get("iso_version", "Unknown")
    hostname = analysis_data.get("hostname", "Unknown")
    mac_addr = analysis_data.get("mac_address", "Unknown")
    
    rca_content = f"""# GDC Post-Install Provisioning Root Cause Analysis (RCA)

* **RCA ID:** `RCA-v{iso_ver}`
* **Target Node IP:** `{target_ip}`
* **Target Hostname:** `{hostname}`
* **Target MAC ID (Unique):** `{mac_addr}`
* **GDC Booted ISO Version:** `v{iso_ver}`
* **RCA Status:** **[ANALYZED FAILURE]**

---

## 1. Issue Summary
The diagnostics agent team has analyzed the node's bootstrap logs. The provisioning process failed during initial setup. Below is the compiled evidence and recommended remediations.

---

## 2. Detected System Failures & Key Telemetry
"""
    
    if analysis_data.get("failures"):
        for fail in analysis_data["failures"]:
            rca_content += f"* **[FAIL]** {fail}\n"
    else:
        rca_content += "* No primary systemd or OS prerequisites failures detected.\n"

    rca_content += """
---

## 3. Access & Authentication Audit
"""
    auth = analysis_data.get("access_audit", {})
    if auth.get("authorized_keys"):
        rca_content += "The following users have authorized SSH keys injected:\n\n"
        rca_content += "| User Account | SSH Key Type | Key Comment (OUI/Host) |\n"
        rca_content += "| :--- | :--- | :--- |\n"
        for key in auth["authorized_keys"]:
            rca_content += f"| `{key['user']}` | `{key['type']}` | `{key['comment']}` |\n"
    else:
         rca_content += "* No public SSH keys were found authorized on the node.\n"

    rca_content += """
---

## 4. Log Evidence Snippets
"""
    if analysis_data.get("log_evidence"):
        for log_key, snippet in analysis_data["log_evidence"].items():
            rca_content += f"### {log_key.upper()} Log Output:\n"
            rca_content += f"```\n{snippet}\n```\n\n"
    else:
        rca_content += "* No specific traceback or failure signature was matched in the logs.\n"

    rca_content += """
---

## 5. Recommended Fixes (Ordered by Severity)
"""
    # Dynamic remediation generator
    fixes = []
    for fail in analysis_data.get("failures", []):
        if "NEXUS" in fail:
            fixes.append((
                "HIGH / CRITICAL",
                "Splay Package Upload Loop with Sleep",
                "Introduce a 'sleep 2' command inside the shell upload loop in src/ansible/roles/service_hubs/tasks/main.yml to prevent Sonatype Nexus JVM lockups during consecutive uploads."
            ))
        if "TPM_UNSEAL" in fail:
            fixes.append((
                "HIGH",
                "LUKS TPM Keyslot Sealing Validation",
                "Verify that systemd-cryptenroll has been executed successfully before removing the plaintext temporary passcode key file from the host filesystem."
            ))
        if "APT_INSTALL" in fail:
            fixes.append((
                "MEDIUM",
                "Pre-seeded Package Availability Checks",
                "Verify that the offline package configurations list matching your Ubuntu release target is present in your build-workspace packages folder before compiling the ISO."
            ))
        if "ROUTING" in fail:
            fixes.append((
                "MEDIUM",
                "Netplan VRF Overlapping Route Mitigation",
                "Ensure that table 10 (Management) and table 20 (Kubernetes) routes do not intersect or overlap to prevent RTNETLINK answers: File exists errors."
            ))

    if fixes:
        for idx, (severity, title, desc) in enumerate(fixes, 1):
            rca_content += f"### Fix {idx}: {title} (Severity: {severity})\n"
            rca_content += f"* {desc}\n\n"
    else:
        rca_content += "### Fix 1: Manual Inspection Recommended (Severity: MEDIUM)\n"
        rca_content += "* Please check the compiled on-device logs under the logs directory in the diagnostics package to locate the failing task.\n"

    # Write RCA Markdown to docs
    rca_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../docs/rca/nexus-jvm-crash/"))
    os.makedirs(rca_folder, exist_ok=True)
    rca_path = os.path.join(rca_folder, f"RCA-v{iso_ver}.md")
    
    with open(rca_path, "w") as rf:
        rf.write(rca_content)
        
    log_success(f"RCA Report synthesized and written to: {rca_path}")
    print("==============================================================================")
    print(f"RCA-v{iso_ver}.md generated successfully!")
    print("==============================================================================")

if __name__ == "__main__":
    main()
