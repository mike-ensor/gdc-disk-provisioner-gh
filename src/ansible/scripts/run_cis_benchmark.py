#!/usr/bin/env python3
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""
GDC Ready-Linux CIS Benchmark Runner

Runs the offline CIS-CAT Assessor in read-only audit mode against Level 1 and
Level 2 server profiles. Parses the resulting HTML reports to extract high-level
compliance metrics and writes them to a structured JSON evidence payload for
gdc-collector ingestion.
"""

import sys
import os
import json
import subprocess
import datetime
import traceback
import re
import gzip
import shutil

ASSESSOR_ROOT = "/opt/cis-benchmark/cis-hardening-amd64/CIS-CAT-Assessor-Linux-jre-v4.61.0/Assessor"
ASSESSOR_SCRIPT = os.path.join(ASSESSOR_ROOT, "Assessor-CLI.sh")
BENCHMARK_XML = "benchmarks/CIS_Ubuntu_Linux_24.04_LTS_Benchmark_v1.0.0-xccdf.xml"
LOG_DIR_BASE = "/var/gdc-install/logs/cis"
REPORTS_DIR_BASE = "/opt/cis-benchmark/reports"
STATE_FILE = "/var/gdc-install/state/cis-benchmark.json"

PROFILES = [
    {
        "id": "level_1_server",
        "name": "Level 1 - Server",
        "out_dir": os.path.join(LOG_DIR_BASE, "level-1-server"),
        "archive_dir": os.path.join(REPORTS_DIR_BASE, "level-1-server")
    },
    {
        "id": "level_2_server",
        "name": "Level 2 - Server",
        "out_dir": os.path.join(LOG_DIR_BASE, "level-2-server"),
        "archive_dir": os.path.join(REPORTS_DIR_BASE, "level-2-server")
    }
]

def extract_metrics(profile):
    metrics = {
        "score_percentage": 0.0,
        "rules_passed": 0,
        "rules_failed": 0,
        "rules_other": 0,
        "rules_total": 0,
        "report_path": ""
    }
    
    # We will read from the newly renamed canonical files
    html_path = os.path.join(profile["archive_dir"], f"cis-benchmark-{profile['id']}.html")
    txt_path = os.path.join(profile["out_dir"], f"cis-benchmark-{profile['id']}-summary.txt")
    
    if not os.path.exists(txt_path) or not os.path.exists(html_path):
        print(f"[!] Could not find summary TXT or archive HTML for metrics parsing.")
        return metrics
        
    metrics["report_path"] = html_path

    try:
        with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
            html_content = f.read()
            score_match = re.search(r'data-score="(\d+(?:\.\d+)?)"', html_content)
            if score_match:
                metrics["score_percentage"] = float(score_match.group(1))

        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            for line in lines:
                prefix = line.split(":")[0].strip().lower()
                if prefix == "pass":
                    metrics["rules_passed"] += 1
                elif prefix == "fail":
                    metrics["rules_failed"] += 1
                elif prefix in ["error", "unknown", "notchecked", "notapplicable", "manual", "informational"]:
                    metrics["rules_other"] += 1

            metrics["rules_total"] = metrics["rules_passed"] + metrics["rules_failed"] + metrics["rules_other"]

    except Exception as e:
        print(f"[!] Error parsing reports: {e}")

    return metrics

def cleanup_and_optimize(profile):
    """
    Moves heavy artifacts (HTML, XML) out of /var/gdc-install/logs/cis/ to avoid 
    gdc-collector tarball bloat, compresses XML, and deduplicates symlinks.
    """
    os.makedirs(profile["archive_dir"], exist_ok=True)
    
    for f in os.listdir(profile["out_dir"]):
        src_path = os.path.join(profile["out_dir"], f)
        
        # 1. Rename and compress raw ARF XML into the archive directory
        if f.endswith(".xml"):
            dest_xml = os.path.join(profile["archive_dir"], f"cis-benchmark-{profile['id']}-ARF.xml.gz")
            try:
                with open(src_path, 'rb') as f_in:
                    with gzip.open(dest_xml, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(src_path)
            except Exception as e:
                print(f"  [!] Failed to compress {f}: {e}")
                
        # 2. Rename and move the massive HTML report to the archive directory
        elif f.endswith(".html") and not f.startswith("cis-benchmark"):
            dest_html = os.path.join(profile["archive_dir"], f"cis-benchmark-{profile['id']}.html")
            try:
                os.replace(src_path, dest_html)
            except Exception as e:
                print(f"  [!] Failed to move {f}: {e}")
                
        # 3. Rename the plaintext report but KEEP it in the logs dir (it's lightweight)
        elif f.endswith(".txt") and not f.startswith("cis-benchmark"):
            dest_txt = os.path.join(profile["out_dir"], f"cis-benchmark-{profile['id']}-summary.txt")
            try:
                os.replace(src_path, dest_txt)
            except Exception as e:
                print(f"  [!] Failed to rename {f}: {e}")
                
        # 4. Cleanup any old duplicate symlinks
        elif os.path.islink(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass


def run_assessor(profile):
    os.makedirs(profile["out_dir"], exist_ok=True)
    
    cmd = [
        ASSESSOR_SCRIPT,
        "-b", BENCHMARK_XML,
        "-p", profile["name"],
        "-html", "-txt",
        "-rd", profile["out_dir"]
    ]
    
    console_log_path = os.path.join(profile["out_dir"], f"cis-benchmark-{profile['id']}-console.log")
    
    print(f"[-] Running CIS-CAT Assessor for {profile['name']}...")
    try:
        with open(console_log_path, "w") as log_file:
            process = subprocess.run(
                cmd,
                cwd=ASSESSOR_ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False
            )
        
        if process.returncode != 0:
            print(f"[!] Assessor returned non-zero exit code: {process.returncode}")
            
    except Exception as e:
        print(f"[!] Assessor execution failed: {e}")
        return False

    print(f"[-] Optimizing artifacts for {profile['name']}...")
    cleanup_and_optimize(profile)
    return True


def main():
    if not os.path.exists(ASSESSOR_SCRIPT):
        print(f"[!] FATAL: CIS-CAT Assessor script not found at {ASSESSOR_SCRIPT}")
        sys.exit(1)

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    
    state = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_status": "COMPLETED",
        "profiles": {}
    }

    try:
        for profile in PROFILES:
            success = run_assessor(profile)
            if success:
                metrics = extract_metrics(profile)
                state["profiles"][profile["id"]] = metrics
            else:
                state["execution_status"] = "ERROR"
                state["profiles"][profile["id"]] = {
                    "error": "Failed to run benchmark or locate output report."
                }
    except Exception as e:
        state["execution_status"] = "ERROR"
        state["error_message"] = str(e)
        state["traceback"] = traceback.format_exc()
        print(f"[!] Benchmark execution encountered a fatal error: {e}")

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"[+] CIS Benchmark state written to {STATE_FILE}")
    except Exception as e:
        print(f"[!] Failed to write state file: {e}")
        sys.exit(1)

    # Always exit 0 to ensure advisory, non-blocking behavior
    sys.exit(0)

if __name__ == "__main__":
    main()
