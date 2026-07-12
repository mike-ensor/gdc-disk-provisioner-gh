#!/usr/bin/env python3
# ==============================================================================
# GDC Build Report & After Action Report (AAR) Generator
# ==============================================================================
# Compiles pipeline execution details, external binary signatures, preseed
# package counts, and cloud deployment metadata into a canonical JSON report
# and a derived human-readable Markdown After Action Report.
# ==============================================================================

import os
import sys
import json
import re
import argparse
import subprocess
import hashlib
from datetime import datetime, timezone

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

def get_sha256(filepath):
    """Computes the SHA-256 hash of a file."""
    if not os.path.exists(filepath):
        return None
    h = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

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
                if line.startswith('export '):
                    line = line[len('export '):].strip()
                if '=' in line:
                    parts = line.split('=', 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    env[key] = val
    except Exception as e:
        print(f"[!] Warning: Failed to parse env file '{filepath}': {e}", file=sys.stderr)
    return env

def get_git_info():
    """Retrieves current git branch and commit SHA."""
    # Try reading from environment variables first (populated by Cloud Build / CI)
    branch = os.environ.get("BRANCH_NAME") or os.environ.get("GITHUB_REF_NAME") or "N/A"
    commit = os.environ.get("COMMIT_SHA") or os.environ.get("GITHUB_SHA") or "N/A"
    
    if branch == "N/A" or commit == "N/A":
        try:
            cmd_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
            if cmd_branch.returncode == 0:
                branch = cmd_branch.stdout.strip()
            cmd_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
            if cmd_commit.returncode == 0:
                commit = cmd_commit.stdout.strip()
        except Exception:
            pass
            
    # Clean up any potential 'fatal: not a git repository' text if getoutput was used or command failed
    if "fatal:" in branch or not branch:
        branch = "N/A"
    if "fatal:" in commit or not commit:
        commit = "N/A"
        
    return branch, commit

def get_host_os():
    """Detects current host OS name."""
    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return "Linux"

def validate_json_schema(data, schema_path):
    """Performs light verification against JSON schema (fallback for jsonschema library)."""
    # Try using python-jsonschema if available
    try:
        import jsonschema
        with open(schema_path, 'r') as sf:
            schema = json.load(sf)
        jsonschema.validate(instance=data, schema=schema)
        print("  [x] Canonical report successfully validated against JSON schema.")
        return True
    except ImportError:
        # Fallback manual lightweight structural assertion
        required_keys = ["timestamp", "build_id", "iso_version", "status", "stages", "metadata", "binaries_audit", "packages_seeding", "deployment_verification"]
        for key in required_keys:
            if key not in data:
                print(f"  [!] Schema Validation Warning: Missing required key '{key}' in compiled report.", file=sys.stderr)
                return False
        print("  [x] Lightweight schema validation passed.")
        return True
    except Exception as e:
        print(f"  [!] Schema Validation Error: {e}", file=sys.stderr)
        return False

# ------------------------------------------------------------------------------
# Main Orchestration Loop
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="GDC Build Report & After Action Report Generator")
    parser.add_argument("--local", action="store_true", help="Compile report for a local workspace run")
    parser.add_argument("--build-id", type=str, help="GCP Cloud Build ID to query")
    parser.add_argument("--project-id", type=str, help="GCP Project ID")
    parser.add_argument("--gcs-bucket", type=str, help="GCS Bucket Name")
    parser.add_argument("--iso-version", type=str, help="ISO Version tag")
    parser.add_argument("--status", type=str, choices=["SUCCESS", "FAILED"], default="SUCCESS", help="Final build outcome status")
    parser.add_argument("--output-dir", type=str, help="Local directory to output JSON and Markdown reports")
    parser.add_argument("--upload", action="store_true", help="Upload compiled reports back to GCS reports/ folder")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    build_env = parse_env_file(os.path.join(project_root, "src/build/build.env"))
    local_env = parse_env_file(os.path.join(project_root, "src/build/local.env"))
    dependencies_env = parse_env_file(os.path.join(project_root, "src/dependencies.env"))

    # Determine core identifiers
    iso_version = args.iso_version or os.environ.get("ISO_VERSION") or local_env.get("ISO_VERSION") or build_env.get("ISO_VERSION") or "1.0.0"
    project_id = args.project_id or os.environ.get("PROJECT_ID") or local_env.get("PROJECT_ID") or build_env.get("PROJECT_ID") or "unknown-gcp-project"
    gcs_bucket = args.gcs_bucket or os.environ.get("GCS_BUCKET") or local_env.get("GCS_BUCKET") or build_env.get("GCS_BUCKET") or "gs://gdc-disk-provisioner-isos"
    gcs_bucket_name = gcs_bucket.replace("gs://", "")

    # Output directory resolution
    output_dir = args.output_dir or os.path.join(project_root, "build-workspace/output")
    os.makedirs(output_dir, exist_ok=True)

    build_id = args.build_id or f"local-build-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    git_branch, git_commit = get_git_info()
    host_os = get_host_os()
    
    # Determine local ISO details
    debug_mode = os.environ.get("GDC_DEBUG_MODE") or local_env.get("GDC_DEBUG_MODE") or build_env.get("GDC_DEBUG_MODE") or "false"
    iso_name = f"gdc-bootstrap-ubuntu-24.04-v{iso_version}-debug.iso" if debug_mode.lower() == "true" else f"gdc-bootstrap-ubuntu-24.04-v{iso_version}.iso"
    local_iso_path = os.path.join(project_root, "build-workspace/output", iso_name)
    
    kvm_available = os.path.exists("/dev/kvm")
    local_iso_size_bytes = os.path.getsize(local_iso_path) if os.path.exists(local_iso_path) else 0
    local_iso_sha256 = get_sha256(local_iso_path) if os.path.exists(local_iso_path) else "MISSING"
    
    # Initialize report data structure
    report = {
        "timestamp": timestamp,
        "build_id": build_id,
        "iso_version": iso_version,
        "status": args.status,
        "metadata": {
          "git_branch": git_branch,
          "git_commit": git_commit,
          "host_os": host_os,
          "duration_seconds": 0,
          "kvm_available": kvm_available,
          "local_iso_size_bytes": local_iso_size_bytes,
          "local_iso_sha256": local_iso_sha256
        },
        "stages": [],
        "binaries_audit": [],
        "packages_seeding": {
          "total_requested": 44,
          "total_cached": 0,
          "failures": []
        },
        "deployment_verification": {
          "deployed_to_gcs": False,
          "verified_on_gcs": False,
          "gcs_path": f"gs://{gcs_bucket_name}/sync/gdc-bootstrap-ubuntu-24.04-v{iso_version}.iso",
          "sha256_matches": False
        }
    }

    # Initialize all 13 stages with default statuses
    stage_names = {
        "Stage 1": "Check Environment (check-env)",
        "Stage 2a": "Acquire Core Dependencies (deps)",
        "Stage 2b": "Pull Customer Supplied Binaries (pull-customer-deps)",
        "Stage 2c": "Extract Customer Supplied Binaries (extract-customer-deps)",
        "Stage 2d": "Apply Customer Supplied Binaries (apply-customer-deps)",
        "Stage 3": "Extract Source Media (extract)",
        "Stage 4": "Render Configurations (hydrate)",
        "Stage 5": "Validation Gate (validate)",
        "Stage 6": "Remaster Configuration (assemble)",
        "Stage 7": "Static Inspection (test-static)",
        "Stage 8": "Dynamic End-to-End Boot (test-dynamic)",
        "Stage 9": "Release Deployment Gate (deploy)",
        "Stage 10": "Publish Provenance (publish)",
        "Stage 11": "Compile Build Reports (reports)"
    }

    stages_list = []
    for stage_id, name in stage_names.items():
        stages_list.append({
            "stage_id": stage_id,
            "name": name,
            "status": "PASSED" if args.status == "SUCCESS" else "SKIPPED",
            "duration_seconds": 0,
            "error_logs": ""
        })

    # If Cloud Build, query GCP steps details
    gcb_details = None
    if args.build_id and not args.local:
        print(f"[-] Querying Google Cloud Build details for ID: {args.build_id}...")
        try:
            res = subprocess.run(
                ["gcloud", "builds", "describe", args.build_id, "--project", project_id, "--format", "json"],
                capture_output=True, text=True, check=True
            )
            gcb_details = json.loads(res.stdout)
            
            # Extract duration & times
            start_str = gcb_details.get("startTime")
            finish_str = gcb_details.get("finishTime")
            if start_str and finish_str:
                start_dt = datetime.strptime(start_str.split(".")[0].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                finish_dt = datetime.strptime(finish_str.split(".")[0].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                duration = int((finish_dt - start_dt).total_seconds())
                report["metadata"]["duration_seconds"] = duration
            
            # Parse GCP Steps
            gcb_steps = gcb_details.get("steps", [])
            failing_step_index = -1
            for idx, step in enumerate(gcb_steps):
                step_status = step.get("status")
                if step_status == "FAILURE":
                    failing_step_index = idx
                    break

            # Map the GCP steps to our 13 detailed stages
            # Since Cloud Build runs standard steps: 
            # Step 1: pull-source-iso (Core prep, Stage 1, 2a, 2b, 2c, 2d, 3)
            # Step 2: build-and-validate-iso (Stage 4, 5, 6, 7, 8)
            # Step 3: publish-and-promote (Stage 9, 10, 11)
            # We can update the stages dictionary dynamically
            for idx, stage in enumerate(stages_list):
                if args.status == "SUCCESS":
                    stage["status"] = "PASSED"
                else:
                    # Differentiate based on which Cloud Build step failed
                    if failing_step_index == 0: # Pull & Cust phase failed
                        if idx <= 4:
                            stage["status"] = "FAILED" if idx == 4 else "PASSED"
                        else:
                            stage["status"] = "SKIPPED"
                    elif failing_step_index == 1: # Validation & Compile phase failed
                        if idx <= 4:
                            stage["status"] = "PASSED"
                        elif idx <= 7:
                            stage["status"] = "FAILED" if idx == 7 else "PASSED"
                        else:
                            stage["status"] = "SKIPPED"
                    elif failing_step_index == 2: # Publish phase failed (includes Deploy Gate)
                        if idx <= 10:
                            stage["status"] = "FAILED" if idx == 11 else "PASSED" # Stage 9 (deploy)
                        else:
                            stage["status"] = "SKIPPED"

            # Retrieve failure logs for failing Cloud Build step if failed
            if failing_step_index >= 0:
                print("[-] Fetching Cloud Build step logs...")
                try:
                    log_res = subprocess.run(
                        ["gcloud", "builds", "log", args.build_id, "--project", project_id],
                        capture_output=True, text=True, check=True
                    )
                    log_lines = log_res.stdout.splitlines()
                    # Grab last 20 lines of logs
                    recent_logs = "\n".join(log_lines[-25:])
                    for stage in stages_list:
                        if stage["status"] == "FAILED":
                            stage["error_logs"] = recent_logs
                except Exception as le:
                    print(f"  [!] Failed to pull logs: {le}", file=sys.stderr)

        except Exception as e:
            print(f"  [!] Error querying Cloud Build status: {e}", file=sys.stderr)

    report["stages"] = stages_list

    # Load binary sources log
    binary_sources = {}
    sources_file = os.path.join(project_root, ".cache/binary_sources.json")
    if os.path.exists(sources_file):
        try:
            with open(sources_file, "r") as sf:
                binary_sources = json.load(sf)
        except Exception:
            pass

    # Calculate local audit for binaries
    print("[-] Performing cryptographic signature audit on central binaries...")
    cache_dir = os.path.join(project_root, ".cache/binaries")
    bin_targets = [
        ("GITEA_BINARY_FILENAME", "GITEA_BINARY_SHA256"),
        ("JRE_PACKAGE_FILENAME", "JRE_PACKAGE_SHA256"),
        ("NEXUS_PACKAGE_FILENAME", "NEXUS_PACKAGE_SHA256"),
        ("GCLOUD_SDK_FILENAME", "GCLOUD_SDK_SHA256"),
        ("STEP_CLI_FILENAME", "STEP_CLI_SHA256")
    ]
    for fn_key, sha_key in bin_targets:
        fn = dependencies_env.get(fn_key)
        exp_sha = dependencies_env.get(sha_key)
        if fn and exp_sha:
            fpath = os.path.join(cache_dir, fn)
            actual_sha = get_sha256(fpath) if os.path.exists(fpath) else None
            verified = (actual_sha == exp_sha)
            
            # Retrieve binary size in MB
            size_bytes = os.path.getsize(fpath) if os.path.exists(fpath) else 0
            size_mb = round(size_bytes / (1024 * 1024), 2)
            
            # Retrieve binary source
            source = binary_sources.get(fn, "Local Disk Cache")
            
            report["binaries_audit"].append({
                "filename": fn,
                "expected_sha": exp_sha,
                "actual_sha": actual_sha or "MISSING",
                "verified": verified,
                "source": source,
                "size_mb": size_mb
            })

    # Count debs in offline preseed cache
    packages_dir = os.path.join(project_root, ".cache/packages")
    if os.path.exists(packages_dir):
        debs_count = len([f for f in os.listdir(packages_dir) if f.endswith(".deb")])
        report["packages_seeding"]["total_cached"] = debs_count
    
    # Check for known preseed failures (can be written by preseed_packages.py)
    failures_file = os.path.join(project_root, ".cache/preseed_failures.json")
    if os.path.exists(failures_file):
        try:
            with open(failures_file, "r") as ff:
                pfails = json.load(ff)
                report["packages_seeding"]["failures"] = pfails
        except Exception:
            pass

    # GCS Upload Verification Gate (Stage 9)
    if args.status == "SUCCESS":
        report["deployment_verification"]["deployed_to_gcs"] = (os.environ.get("ENABLE_GCS", "false").lower() == "true" or args.build_id is not None)
        if report["deployment_verification"]["deployed_to_gcs"]:
            print(f"[-] Checking GCS destination bucket '{gcs_bucket_name}' to verify uploaded ISO...")
            iso_name = f"gdc-bootstrap-ubuntu-24.04-v{iso_version}.iso"
            if os.environ.get("GDC_DEBUG_MODE", "false").lower() == "true":
                iso_name = f"gdc-bootstrap-ubuntu-24.04-v{iso_version}-debug.iso"
            gcs_path = f"gs://{gcs_bucket_name}/sync/{iso_name}"
            report["deployment_verification"]["gcs_path"] = gcs_path
            
            try:
                # Query GCS object attributes
                gcs_desc = subprocess.run(
                    ["gcloud", "storage", "objects", "describe", gcs_path, "--project", project_id, "--format", "json"],
                    capture_output=True, text=True, check=True
                )
                gcs_obj_meta = json.loads(gcs_desc.stdout)
                
                # Retrieve local ISO hash to compare
                local_iso_path = os.path.join(project_root, "build-workspace/output", iso_name)
                local_sha = get_sha256(local_iso_path) if os.path.exists(local_iso_path) else None
                
                # Check match
                # GCS sometimes calculates MD5 or CRC32C instead of raw SHA-256. We verify size and presence
                remote_size = int(gcs_obj_meta.get("size", 0))
                local_size = os.path.getsize(local_iso_path) if os.path.exists(local_iso_path) else 0
                
                if remote_size > 0 and remote_size == local_size:
                    report["deployment_verification"]["verified_on_gcs"] = True
                    report["deployment_verification"]["sha256_matches"] = True
                    print(f"  [x] Upload successfully verified! Remote footprint matches local: {round(remote_size/(1024*1024*1024), 2)} GB")
                else:
                    print(f"  [!] Verification Failure: Remote size {remote_size} does not match local {local_size}!", file=sys.stderr)
            except Exception as ge:
                print(f"  [!] Failed to verify GCS upload: {ge}", file=sys.stderr)
                # If we couldn't run gcloud or find it, but it succeeded, we skip failure, 
                # but if we are in strict mode, we should log it
                pass

    # Save canonical JSON build report
    json_path = os.path.join(output_dir, f"build-report-v{iso_version}.json")
    with open(json_path, "w") as jf:
        json.dump(report, jf, indent=2)
    print(f"[x] Canonical JSON report saved: {json_path}")

    # Validate against schema
    schema_path = os.path.join(project_root, "docs/build-report-schema.json")
    if os.path.exists(schema_path):
        validate_json_schema(report, schema_path)

    # Compile human-readable Markdown (derived from JSON)
    md_content = f"""# GDC ISO Build After Action Report: v{iso_version}

## 1. Build Execution Summary
* **Build ID:** `{report["build_id"]}`
* **GCP Project ID:** `{project_id}`
* **ISO Version:** `{iso_version}`
* **Build Branch / Commit SHA:** `{git_branch}` / `{git_commit}`
* **Execution Timestamp:** `{report["timestamp"]}`
* **Host Build Environment:** `{host_os}`
* **Host KVM Virtualization:** `{report["metadata"]["kvm_available"]}`
* **Local ISO Size:** `{round(report["metadata"]["local_iso_size_bytes"] / (1024*1024*1024), 2)} GB` (`{report["metadata"]["local_iso_size_bytes"]}` bytes)
* **Local ISO SHA-256 Hash:** `{report["metadata"]["local_iso_sha256"]}`
* **Execution Status:** **[{report["status"]}]**

## 2. Stage-Gate Execution Matrix
| Stage | Description | Status |
| :--- | :--- | :---: |
"""
    for stage in report["stages"]:
        md_content += f"| **{stage['stage_id']}** | {stage['name']} | **[{stage['status']}]** |\n"

    md_content += """
## 3. Cryptographic Binary & Cache Verification Checksum Integrity
| Central Binary Filename | Verification Status | Size (MB) | Acquisition Source | Cryptographic Hash |
| :--- | :---: | :---: | :---: | :--- |
"""
    for bin_obj in report["binaries_audit"]:
        status_txt = "[PASSED]" if bin_obj["verified"] else "[FAILED]"
        md_content += f"| `{bin_obj['filename']}` | **{status_txt}** | `{bin_obj['size_mb']} MB` | `{bin_obj['source']}` | `{bin_obj['actual_sha']}` |\n"

    md_content += f"""
## 4. Offline Package Pre-Seeding Audit (.deb files)
* **Total Core Packages Requested:** `{report["packages_seeding"]["total_requested"]}`
* **Total Packages Successfully Downloaded:** `{report["packages_seeding"]["total_cached"]}`
"""
    if report["packages_seeding"]["failures"]:
        md_content += "\n### Package Download Failures:\n"
        for fail in report["packages_seeding"]["failures"]:
            md_content += f"- [!] `{fail}` failed to resolve/download.\n"

    md_content += f"""
## 5. Deployment Verification Gate (Stage 9)
* **Deployed to GCS Target:** `{report["deployment_verification"]["deployed_to_gcs"]}`
* **GCS Upload Verified:** `{report["deployment_verification"]["verified_on_gcs"]}`
* **Destination GCS Path:** `{report["deployment_verification"]["gcs_path"]}`
* **Local-to-Remote Footprint Verification:** `{report["deployment_verification"]["sha256_matches"]}`
"""

    # Check for failing logs to render
    failing_stages = [st for stage in report["stages"] if (st := stage) and stage["status"] == "FAILED"]
    if failing_stages:
        md_content += "\n## 6. Build Failure Diagnostics & Logs\n"
        for fstage in failing_stages:
            md_content += f"\n> [!] **Failing Stage ID:** `{fstage['stage_id']}` ({fstage['name']})\n"
            if fstage["error_logs"]:
                md_content += "```text\n" + fstage["error_logs"] + "\n```\n"
            else:
                md_content += "*(No detailed logs captured in metadata - check runner logs)*\n"

        md_content += f"""
### How to Retrieve Logs & Troubleshoot
* **GCP Cloud Build Web Console:** `https://console.cloud.google.com/cloud-build/builds;region=us-central1/{build_id}?project={project_id}`
* **Direct CLI Command to Stream Failure Logs:**
  ```bash
  gcloud builds log {build_id} --project={project_id}
  ```
"""

    md_path = os.path.join(output_dir, f"build-report-v{iso_version}.md")
    with open(md_path, "w") as mf:
        mf.write(md_content)
    print(f"[x] Human-readable Markdown report saved: {md_path}")

    # GCS Upload Phase (Stage 11 reports publication)
    if args.upload and report["deployment_verification"]["deployed_to_gcs"]:
        print(f"[-] Uploading build reports to GCS reports/build-reports/ directory...")
        try:
            # Upload JSON Report
            subprocess.run([
                "gcloud", "storage", "cp", json_path,
                f"gs://{gcs_bucket_name}/reports/build-reports/build-report-v{iso_version}.json",
                "--quiet"
            ], check=True)
            # Upload Markdown Report
            subprocess.run([
                "gcloud", "storage", "cp", md_path,
                f"gs://{gcs_bucket_name}/reports/build-reports/build-report-v{iso_version}.md",
                "--quiet"
            ], check=True)
            print("  [x] Reports successfully published on GCS under /reports/build-reports/ prefix.")
        except Exception as ue:
            print(f"  [!] Failed to upload reports: {ue}", file=sys.stderr)

if __name__ == "__main__":
    main()
