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
# GDC Storage Lifecycle - GCS ISO Retention & Archive Sweeper
# ==============================================================================
# Sweeps Google Cloud Storage (GCS) buckets for compiled ISO release artifacts,
# enforcing series-aware retention policies (e.g. keep top 3 builds per prefix)
# and moving older releases to an archive folder or pruning them safely.
# ==============================================================================

import argparse
from collections import defaultdict
import os
import re
import subprocess
import sys

getattr(sys.stdout, "reconfigure", lambda **kwargs: None)(line_buffering=True)

GCS_METRICS_ENV = "gcs-skills gcs-skills/1.0 (skill:google-cloud-storage-basics)"
DEFAULT_BUCKET = "gs://gdc-disk-provisioner-isos"
ISO_REGEX = re.compile(r"^(?P<base>.+?)-v(?P<ver>[0-9]+(?:\.[0-9]+)+)(?P<variant>.*)\.iso$")


def parse_env_file(filepath):
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


def load_default_bucket():
    """Discovers bucket default from environment variables or build configuration files."""
    env_bucket = os.environ.get("GCS_BUCKET")
    if env_bucket and env_bucket.strip():
        return env_bucket.strip()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    iso_env = os.environ.get("ISO_ENVIRONMENT", "local")

    for fname in [f"{iso_env}.env", "honeywell.env", "local.env", "build.env"]:
        path = os.path.join(script_dir, fname)
        parsed = parse_env_file(path)
        if "GCS_BUCKET" in parsed and parsed["GCS_BUCKET"].strip():
            return parsed["GCS_BUCKET"].strip()

    return DEFAULT_BUCKET


def parse_version_key(version_str):
    """Converts a semantic version string (e.g. '0.10.9') into a tuple of integers."""
    try:
        return tuple(int(x) for x in version_str.split("."))
    except ValueError:
        return (0,)


def parse_iso_entry(filename, size_bytes=0, timestamp=""):
    """
    Parses an ISO filename into its series identifier, semantic version tuple,
    and metadata components.
    """
    match = ISO_REGEX.match(filename)
    if match:
        base = match.group("base")
        ver_str = match.group("ver")
        variant = match.group("variant")
        series = f"{base}{variant}"
        version_tuple = parse_version_key(ver_str)
    else:
        series = "other"
        ver_str = "0.0.0"
        version_tuple = (0,)

    return {
        "filename": filename,
        "series": series,
        "version_str": ver_str,
        "version_tuple": version_tuple,
        "timestamp": timestamp,
        "size_bytes": size_bytes,
    }


def list_gcs_isos(bucket, prefix="sync"):
    """
    Lists ISO objects from a GCS bucket prefix using gcloud storage ls -l.
    Returns a list of parsed entry dicts.
    """
    clean_bucket = bucket.rstrip("/")
    if not clean_bucket.startswith("gs://"):
        clean_bucket = f"gs://{clean_bucket}"
    clean_prefix = prefix.strip("/")

    target_pattern = f"{clean_bucket}/{clean_prefix}/*.iso" if clean_prefix else f"{clean_bucket}/*.iso"

    env = os.environ.copy()
    env["CLOUDSDK_METRICS_ENVIRONMENT"] = GCS_METRICS_ENV

    cmd = ["gcloud", "storage", "ls", "-l", target_pattern]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, check=True)
    except subprocess.CalledProcessError as e:
        if "One or more URLs matched no objects" in e.stderr or not e.stdout.strip():
            return []
        raise RuntimeError(f"Failed to list objects at {target_pattern}: {e.stderr.strip()}") from e

    entries = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and parts[2].startswith("gs://") and parts[2].endswith(".iso"):
            try:
                size_bytes = int(parts[0])
            except ValueError:
                continue
            timestamp = parts[1]
            uri = parts[2]
            filename = uri.split("/")[-1]
            entry = parse_iso_entry(filename, size_bytes=size_bytes, timestamp=timestamp)
            entry["uri"] = uri
            entries.append(entry)

    return entries


def evaluate_retention(entries, keep_count=3, series_filter=None):
    """
    Evaluates a list of parsed ISO entries, grouping them by series and sorting
    by (version_tuple, timestamp) descending. Partitions into kept and candidate items.
    """
    groups = defaultdict(list)
    for entry in entries:
        if series_filter and series_filter not in entry["series"]:
            continue
        groups[entry["series"]].append(entry)

    evaluated = {}
    for series, items in groups.items():
        # Sort descending: newest semantic version first, then timestamp
        items.sort(key=lambda x: (x["version_tuple"], x["timestamp"]), reverse=True)
        keep = items[:keep_count]
        candidates = items[keep_count:]
        evaluated[series] = {
            "all": items,
            "keep": keep,
            "candidates": candidates,
        }

    return evaluated


def format_gib(bytes_val):
    """Formats bytes to GiB string with two decimal places."""
    return f"{bytes_val / (1024 ** 3):.2f} GiB"


def execute_moves(moves, dry_run=False):
    """Moves objects from source URIs to destination URIs using gcloud storage mv."""
    if not moves:
        return True

    env = os.environ.copy()
    env["CLOUDSDK_METRICS_ENVIRONMENT"] = GCS_METRICS_ENV

    total = len(moves)
    for idx, (src, dst) in enumerate(moves, start=1):
        filename = os.path.basename(src)
        print(f"  [{idx}/{total}] Moving: {filename} -> {dst}")
        if not dry_run:
            cmd = ["gcloud", "storage", "mv", src, dst]
            res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                print(f"    [!] Error moving {src}: {res.stderr.strip()}", file=sys.stderr)
                return False
    return True


def execute_deletions(uris, dry_run=False):
    """Deletes objects using gcloud storage rm in batches."""
    if not uris:
        return True

    env = os.environ.copy()
    env["CLOUDSDK_METRICS_ENVIRONMENT"] = GCS_METRICS_ENV

    batch_size = 50
    total = len(uris)

    for i in range(0, total, batch_size):
        batch = uris[i : i + batch_size]
        print(f"  [-] Deleting batch {i + 1}-{min(i + batch_size, total)} of {total} objects...")
        if not dry_run:
            cmd = ["gcloud", "storage", "rm"] + batch
            res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                print(f"    [!] Error deleting batch: {res.stderr.strip()}", file=sys.stderr)
                return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="GCS ISO Retention & Archive Sweeper: cleans up crowded ISO buckets."
    )
    parser.add_argument(
        "-b",
        "--bucket",
        help="Target GCS bucket (default: auto-detected from build environment or GCS_BUCKET env var)",
    )
    parser.add_argument(
        "-k",
        "--keep",
        type=int,
        default=3,
        help="Number of newest builds to keep per series/prefix group (default: 3)",
    )
    parser.add_argument(
        "--source-prefix",
        default="sync",
        help="Source bucket prefix to inspect (default: 'sync')",
    )
    parser.add_argument(
        "--archive-prefix",
        default="archived",
        help="Destination bucket prefix to move older builds to (default: 'archived')",
    )
    parser.add_argument(
        "--action",
        choices=["archive", "delete"],
        default="archive",
        help="Action to perform on older ISOs: 'archive' (mv to archive-prefix) or 'delete' (rm). Default: archive",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Preview operations without executing moves or deletions on GCS",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Proceed with moves/deletions without interactive confirmation",
    )
    parser.add_argument(
        "--series-filter",
        help="Only process series matching this substring (e.g. 'honeywell' or 'gdc-labs')",
    )

    args = parser.parse_args()

    bucket = args.bucket or load_default_bucket()
    if not bucket.startswith("gs://"):
        bucket = f"gs://{bucket}"
    bucket = bucket.rstrip("/")

    source_prefix = args.source_prefix.strip("/")
    archive_prefix = args.archive_prefix.strip("/")

    print("=" * 78)
    print(" GDC STORAGE LIFECYCLE - GCS ISO RETENTION SWEEPER")
    print("=" * 78)
    print(f"  Target Bucket:       {bucket}")
    print(f"  Source Prefix:       {source_prefix}/")
    print(f"  Archive Prefix:      {archive_prefix}/")
    print(f"  Action:              {args.action.upper()}")
    print(f"  Retention Target:    Keep newest {args.keep} build(s) per series")
    if args.series_filter:
        print(f"  Series Filter:       {args.series_filter}")
    if args.dry_run:
        print("  Mode:                DRY RUN (no modifications will be made)")
    print("-" * 78)

    print(f"[-] Scanning {bucket}/{source_prefix}/ for ISO artifacts...")
    try:
        entries = list_gcs_isos(bucket, prefix=source_prefix)
    except Exception as e:
        print(f"[!] Error querying GCS: {e}", file=sys.stderr)
        return 1

    if not entries:
        print(f"[-] No ISO artifacts found in {bucket}/{source_prefix}/.")
        return 0

    evaluated = evaluate_retention(entries, keep_count=args.keep, series_filter=args.series_filter)

    total_isos = sum(len(d["all"]) for d in evaluated.values())
    total_keep = sum(len(d["keep"]) for d in evaluated.values())
    total_candidates = sum(len(d["candidates"]) for d in evaluated.values())
    candidate_bytes = sum(sum(item["size_bytes"] for item in d["candidates"]) for d in evaluated.values())

    print(f"[-] Found {total_isos} ISO(s) across {len(evaluated)} series group(s).\n")

    moves = []
    deletions = []

    for series, data in sorted(evaluated.items()):
        print(f"Series: \033[1m{series}\033[0m (Total: {len(data['all'])})")
        print(f"  Retaining (Newest {len(data['keep'])}):")
        for k in data["keep"]:
            print(f"    \033[92m[+]\033[0m {k['filename']} (v{k['version_str']} | {k['timestamp']} | {format_gib(k['size_bytes'])})")

        if data["candidates"]:
            action_label = "Archiving" if args.action == "archive" else "Deleting"
            print(f"  {action_label} ({len(data['candidates'])}):")
            for c in data["candidates"]:
                color = "\033[93m" if args.action == "archive" else "\033[91m"
                print(f"    {color}[-]\033[0m {c['filename']} (v{c['version_str']} | {c['timestamp']} | {format_gib(c['size_bytes'])})")
                if args.action == "archive":
                    dest_uri = f"{bucket}/{archive_prefix}/{c['filename']}"
                    moves.append((c["uri"], dest_uri))
                else:
                    deletions.append(c["uri"])
        else:
            print(f"  (No older builds to {args.action})")
        print()

    print("-" * 78)
    print(" SUMMARY")
    print("-" * 78)
    print(f"  Total ISOs Inspected:   {total_isos}")
    print(f"  ISOs to Keep:           {total_keep}")
    print(f"  ISOs to {args.action.capitalize()}:         {total_candidates} ({format_gib(candidate_bytes)})")
    print("-" * 78)

    if total_candidates == 0:
        print("[x] Bucket is already clean. Nothing to do.")
        return 0

    if args.dry_run:
        print(f"\n[x] Dry-run complete. Would {args.action} {total_candidates} ISO(s) ({format_gib(candidate_bytes)}).")
        return 0

    if not args.yes:
        action_verb = f"move {total_candidates} ISO(s) to '{archive_prefix}/'" if args.action == "archive" else f"permanently delete {total_candidates} ISO(s)"
        prompt = f"\nAre you sure you want to {action_verb} ({format_gib(candidate_bytes)})? [y/N]: "
        try:
            choice = input(prompt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 1

        if choice not in ["y", "yes"]:
            print("Aborted by user. No modifications were made.")
            return 0

    print(f"\n[-] Executing {args.action} operation on {total_candidates} ISO(s)...")
    if args.action == "archive":
        success = execute_moves(moves, dry_run=args.dry_run)
    else:
        success = execute_deletions(deletions, dry_run=args.dry_run)

    if success:
        print(f"\n\033[92m[x] Successfully completed {args.action} on {total_candidates} ISO(s)!\033[0m")
        return 0
    else:
        print(f"\n\033[91m[!] Finished with errors.\033[0m", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
