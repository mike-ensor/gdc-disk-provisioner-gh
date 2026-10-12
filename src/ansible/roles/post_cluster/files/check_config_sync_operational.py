#!/usr/bin/env python3
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Audits and monitors ConfigSync RootSync and RepoSync operational readiness.

Polls Kubernetes RootSync and RepoSync custom resources across all namespaces,
verifying whether all synchronization units have completed without errors.
Exits 0 if all syncs are healthy, or 1 if errors persist or timeout is reached.
"""

import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


def get_utc_iso_now() -> str:
    """Returns current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_kubectl_get_json(kubeconfig: str, resource_kind: str) -> Tuple[int, Dict[str, Any], str]:
    """Runs kubectl get <resource_kind> -A -o json and parses the output."""
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend([f"--kubeconfig={kubeconfig}"])
    cmd.extend(["get", resource_kind, "-A", "-o", "json"])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            return res.returncode, {}, res.stderr.strip()
        data = json.loads(res.stdout) if res.stdout.strip() else {}
        return 0, data, ""
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return 1, {}, str(exc)


def extract_sync_info(item: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """Extracts standardized sync details, status, and error summaries from an R*Sync item."""
    metadata = item.get("metadata", {})
    status = item.get("status", {})

    name = metadata.get("name", "unknown")
    namespace = metadata.get("namespace", "default")

    conditions = status.get("conditions", [])
    sync_block = status.get("sync", {})
    source_block = status.get("source", {})
    rendering_block = status.get("rendering", {})

    sync_commit = sync_block.get("commit", "") or source_block.get("commit", "") or rendering_block.get("commit", "")
    short_commit = sync_commit[:7] if sync_commit else "N/A"

    errors: List[str] = []

    # Check errorSummary in sub-stages
    for stage_name, block in [("rendering", rendering_block), ("source", source_block), ("sync", sync_block)]:
        err_summary = block.get("errorSummary", {})
        if isinstance(err_summary, dict) and err_summary.get("totalCount", 0) > 0:
            errors.append(f"{stage_name.capitalize()} error count: {err_summary.get('totalCount')}")
        err_list = block.get("errors", [])
        if isinstance(err_list, list) and len(err_list) > 0:
            for e in err_list:
                msg = e.get("errorMessage") or str(e)
                errors.append(f"{stage_name.capitalize()}: {msg}")

    # Check conditions
    is_stalled = False
    is_syncing = False
    is_reconciling = False
    sync_completed = False

    for cond in conditions:
        ctype = cond.get("type", "")
        cstatus = cond.get("status", "")
        cmessage = cond.get("message", "")

        if ctype == "Stalled" and cstatus == "True":
            is_stalled = True
            errors.append(cmessage or "Resource is stalled")
        elif ctype == "Syncing":
            if cstatus == "True":
                is_syncing = True
            elif cstatus == "False" and ("Sync Completed" in cmessage or cond.get("reason") == "Sync"):
                sync_completed = True
        elif ctype == "Reconciling" and cstatus == "True":
            is_reconciling = True

    # Check root-level error count
    root_errors = status.get("errors", [])
    if isinstance(root_errors, list):
        for e in root_errors:
            errors.append(str(e))

    # Evaluate high-level status
    if is_stalled or len(errors) > 0:
        high_level_status = "STALLED" if is_stalled else "ERROR"
    elif sync_completed and sync_commit:
        high_level_status = "SYNCED"
    elif is_syncing:
        high_level_status = "SYNCING"
    elif is_reconciling:
        high_level_status = "RECONCILING"
    elif sync_commit:
        high_level_status = "PENDING"
    else:
        high_level_status = "INITIALIZING"

    return {
        "type": kind,
        "namespace": namespace,
        "name": name,
        "status": high_level_status,
        "commit": sync_commit,
        "short_commit": short_commit,
        "errors": errors,
        "error_count": len(errors),
    }


def format_audit_table(sync_list: List[Dict[str, Any]], start_iso: str, elapsed_sec: int, timeout_sec: int) -> str:
    """Formats an ASCII summary table of all inspected R*Syncs."""
    lines = [
        "=" * 88,
        " CONFIGSYNC OPERATIONAL READINESS & R*SYNC AUDIT",
        f" Started: {start_iso} | Elapsed: {elapsed_sec}s / {timeout_sec}s",
        "=" * 88,
        f"{'TYPE':<10} {'NAMESPACE':<26} {'NAME':<22} {'STATUS':<12} {'COMMIT':<10} {'ERRORS'}",
        "-" * 88,
    ]

    for item in sync_list:
        lines.append(
            f"{item['type']:<10} {item['namespace']:<26} {item['name']:<22} "
            f"{item['status']:<12} {item['short_commit']:<10} {item['error_count']}"
        )
        if item["errors"]:
            for err in item["errors"]:
                lines.append(f"  [!] {err}")

    lines.append("-" * 88)
    return "\n".join(lines)


def audit_config_sync(
    kubeconfig: str,
    timeout_sec: int = 600,
    interval_sec: int = 15,
) -> Tuple[bool, Dict[str, Any], str]:
    """Polls RootSyncs and RepoSyncs until all are SYNCED or timeout expires."""
    start_iso = get_utc_iso_now()
    start_epoch = time.time()
    last_table = ""

    while True:
        elapsed_sec = int(time.time() - start_epoch)

        rc_root, root_data, err_root = run_kubectl_get_json(kubeconfig, "rootsync")
        rc_repo, repo_data, _ = run_kubectl_get_json(kubeconfig, "reposync")

        sync_items: List[Dict[str, Any]] = []

        if rc_root == 0 and "items" in root_data:
            for item in root_data["items"]:
                sync_items.append(extract_sync_info(item, "RootSync"))

        if rc_repo == 0 and "items" in repo_data:
            for item in repo_data["items"]:
                sync_items.append(extract_sync_info(item, "RepoSync"))

        last_table = format_audit_table(sync_items, start_iso, elapsed_sec, timeout_sec)

        # Success requires at least 1 RootSync and all items in SYNCED status with 0 errors
        all_synced = len(sync_items) > 0 and all(
            item["status"] == "SYNCED" and item["error_count"] == 0 for item in sync_items
        )

        if all_synced:
            end_iso = get_utc_iso_now()
            duration_sec = int(time.time() - start_epoch)
            evidence = {
                "status": "PASS",
                "timing": {
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "duration_seconds": duration_sec,
                    "timeout_seconds": timeout_sec,
                    "timed_out": False,
                },
                "summary": {
                    "total_syncs": len(sync_items),
                    "synced_count": len(sync_items),
                    "stalled_count": 0,
                    "error_count": 0,
                },
                "sync_details": sync_items,
            }
            summary_msg = f"[+] All {len(sync_items)} R*Sync objects successfully reconciled and operational! (Duration: {duration_sec}s)"
            full_output = f"{last_table}\n{summary_msg}\n{'=' * 88}"
            return True, evidence, full_output

        # Check timeout condition
        if elapsed_sec >= timeout_sec:
            end_iso = get_utc_iso_now()
            duration_sec = int(time.time() - start_epoch)
            stalled_cnt = sum(1 for item in sync_items if item["status"] in ["STALLED", "ERROR"])
            err_cnt = sum(item["error_count"] for item in sync_items)
            synced_cnt = sum(1 for item in sync_items if item["status"] == "SYNCED")

            evidence = {
                "status": "FAIL",
                "timing": {
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "duration_seconds": duration_sec,
                    "timeout_seconds": timeout_sec,
                    "timed_out": True,
                },
                "summary": {
                    "total_syncs": len(sync_items),
                    "synced_count": synced_cnt,
                    "stalled_count": stalled_cnt,
                    "error_count": err_cnt,
                },
                "sync_details": sync_items,
            }
            if len(sync_items) == 0:
                err_detail = f"No RootSync or RepoSync resources found on cluster (error: {err_root or 'none'})"
            else:
                err_detail = f"{stalled_cnt} stalled/error sync(s) remain out of {len(sync_items)} total syncs"
            fail_msg = f"[!] TIMEOUT: ConfigSync operational audit timed out after {duration_sec}s. {err_detail}."
            full_output = f"{last_table}\n{fail_msg}\n{'=' * 88}"
            return False, evidence, full_output

        time.sleep(interval_sec)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Verify ConfigSync RootSync and RepoSync operational readiness."
    )
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", "/etc/kubernetes/admin.conf"),
        help="Path to admin kubeconfig",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout in seconds to wait for all syncs to become healthy (default: 600)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="Polling interval in seconds (default: 15)",
    )
    parser.add_argument(
        "--json-output-file",
        default="",
        help="Optional path to write structured JSON evidence output",
    )

    args = parser.parse_args()

    success, evidence, formatted_output = audit_config_sync(
        kubeconfig=args.kubeconfig,
        timeout_sec=args.timeout,
        interval_sec=args.interval,
    )

    print(formatted_output)

    if args.json_output_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_output_file)), exist_ok=True)
            with open(args.json_output_file, "w", encoding="utf-8") as f:
                json.dump(evidence, f, indent=2)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"[!] Warning: Failed to write JSON output to {args.json_output_file}: {exc}", file=sys.stderr)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
