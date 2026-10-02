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
# GDC Storage Capability Validation & Benchmarking Utility
# ==============================================================================
# Executes synthetic storage performance workloads via kubestr fio with
# strict pre-flight guards on cluster connectivity and longhorn-system readiness.
# Normalizes telemetry into standardized GDC metrics schema.
# ==============================================================================

import argparse
from datetime import datetime, timezone
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

STANDARD_KUBESTR_PATHS = [
    "/var/gdc-install/tools/kubestr/kubestr",
    "/usr/local/bin/kubestr",
    "/custom-data/tools/kubestr/kubestr",
]

KUBESTR_RELEASE_URL = (
    "https://github.com/kastenhq/kubestr/releases/download/v0.4.48/kubestr_0.4.48_Linux_amd64.tar.gz"
)

DEFAULT_PROBE_TIMEOUT = 10
DEFAULT_POD_QUERY_TIMEOUT = 15

BANDWIDTH_MULTIPLIERS: Dict[str, float] = {
    "G": 1024.0 * 1024.0,
    "M": 1024.0,
    "K": 1.0,
    "B": 1.0 / 1024.0,
}


def verify_architecture() -> Tuple[bool, str]:
    """Confirms host architecture is x86_64 or amd64."""
    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        return True, arch
    return False, arch


def check_kubeconfig_and_cluster(
    kubeconfig_path: str,
) -> Tuple[bool, str, str]:
    """Verifies kubeconfig exists and Kubernetes cluster API is reachable."""
    if not kubeconfig_path or not os.path.exists(kubeconfig_path):
        return False, "FAILED_KUBECONFIG", f"Kubeconfig not found: {kubeconfig_path}"

    try:
        res = subprocess.run(
            ["kubectl", "--kubeconfig", kubeconfig_path, "version", "--client=false"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_PROBE_TIMEOUT,
        )
        if res.returncode != 0:
            # Fallback check with cluster-info
            res2 = subprocess.run(
                ["kubectl", "--kubeconfig", kubeconfig_path, "cluster-info"],
                capture_output=True,
                text=True,
                timeout=DEFAULT_PROBE_TIMEOUT,
            )
            if res2.returncode != 0:
                return False, "SKIPPED_NO_CLUSTER", "Kubernetes cluster is unreachable"
    except (subprocess.SubprocessError, FileNotFoundError) as err:
        return False, "SKIPPED_NO_CLUSTER", f"kubectl cluster probe failed: {err}"

    return True, "OK", "Cluster reachable"


def check_longhorn_system_ready(kubeconfig_path: str) -> Tuple[bool, str]:
    """Pre-flight guard checking if longhorn-system exists and components are healthy."""
    # 1. Check namespace
    try:
        res_ns = subprocess.run(
            ["kubectl", "--kubeconfig", kubeconfig_path, "get", "ns", "longhorn-system"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_PROBE_TIMEOUT,
        )
        if res_ns.returncode != 0:
            return False, "Namespace 'longhorn-system' not found"
    except (subprocess.SubprocessError, FileNotFoundError) as err:
        return False, f"Failed checking namespace longhorn-system: {err}"

    # 2. Check longhorn-manager daemonset or pods
    try:
        # Check pods in longhorn-system
        res_pods = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                kubeconfig_path,
                "-n",
                "longhorn-system",
                "get",
                "pods",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=DEFAULT_POD_QUERY_TIMEOUT,
        )
        if res_pods.returncode != 0:
            return False, "Failed to list pods in longhorn-system"

        pod_data = json.loads(res_pods.stdout)
        items = pod_data.get("items", [])
        if not items:
            return False, "No pods running in longhorn-system"

        # Check for longhorn-manager pods running and ready
        manager_ready = False
        for pod in items:
            pod_name = pod.get("metadata", {}).get("name", "")
            labels = pod.get("metadata", {}).get("labels", {})
            if "longhorn-manager" in pod_name or labels.get("app") == "longhorn-manager":
                phase = pod.get("status", {}).get("phase", "")
                conditions = pod.get("status", {}).get("conditions", [])
                ready_condition = any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in conditions
                )
                if phase == "Running" and ready_condition:
                    manager_ready = True
                    break

        if not manager_ready:
            return False, "No ready longhorn-manager pod found in longhorn-system"

    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError) as err:
        return False, f"Failed evaluating longhorn-system pod health: {err}"

    return True, "longhorn-system ready"


def discover_kubestr(
    explicit_path: Optional[str] = None, allow_download: bool = False
) -> Optional[str]:
    """Finds kubestr binary in explicit path, PATH, or standard GDC offline locations."""
    if explicit_path:
        if os.path.exists(explicit_path) and os.access(explicit_path, os.X_OK):
            return explicit_path
        return None

    which_path = shutil.which("kubestr")
    if which_path and os.access(which_path, os.X_OK):
        return which_path

    for candidate in STANDARD_KUBESTR_PATHS:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate

    if allow_download:
        dest_dir = "/tmp/kubestr"
        os.makedirs(dest_dir, exist_ok=True)
        archive_path = os.path.join(dest_dir, "kubestr.tar.gz")
        binary_path = os.path.join(dest_dir, "kubestr")

        try:
            sys.stderr.write(f"Downloading kubestr from {KUBESTR_RELEASE_URL}...\n")
            urllib.request.urlretrieve(KUBESTR_RELEASE_URL, archive_path)
            with tarfile.open(archive_path, "r:gz") as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(path=dest_dir, filter="data")
                else:
                    tar.extractall(path=dest_dir)
            if os.path.exists(binary_path):
                os.chmod(binary_path, 0o755)
                return binary_path
        except Exception as e:
            sys.stderr.write(f"Failed to download/extract kubestr: {e}\n")

    return None


def inspect_storage_class(kubeconfig_path: str, storage_class: str) -> Tuple[bool, str]:
    """Inspects target StorageClass to ensure existence and driver compatibility."""
    try:
        res = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                kubeconfig_path,
                "get",
                "sc",
                storage_class,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=DEFAULT_PROBE_TIMEOUT,
        )
        if res.returncode != 0:
            return False, f"StorageClass '{storage_class}' not found"

        sc_data = json.loads(res.stdout)
        provisioner = sc_data.get("provisioner", "")
        return True, f"StorageClass found with provisioner: {provisioner}"
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError) as err:
        return False, f"Error inspecting StorageClass: {err}"


def parse_bandwidth_kbs(text: str) -> float:
    """Extracts bandwidth in KiB/s from string e.g. '95.7MB/s (98000 KiB/s)'."""
    text_clean = text.strip().replace(",", "")
    # Look for parenthetical KiB/s or KB/s first
    paren_match = re.search(r"\(([0-9.]+)\s*(?:KiB/s|KB/s|kib/s|kb/s)\)", text_clean)
    if paren_match:
        return float(paren_match.group(1))

    # Look for direct unit
    direct_match = re.search(
        r"([0-9.]+)\s*(GiB/s|GB/s|MiB/s|MB/s|KiB/s|KB/s|B/s)", text_clean, re.IGNORECASE
    )
    if direct_match:
        val = float(direct_match.group(1))
        unit_prefix = direct_match.group(2)[0].upper()
        return val * BANDWIDTH_MULTIPLIERS.get(unit_prefix, 1.0)

    clean = re.sub(r"[^\d.]", "", text_clean)
    return float(clean) if clean else 0.0


def parse_iops(text: str) -> float:
    """Parses IOPS count e.g. '24500' or '24.5k'."""
    clean = text.strip().replace(",", "")
    match = re.match(r"^([0-9.]+)\s*([kKmMgG])?$", clean)
    if match:
        val = float(match.group(1))
        unit = (match.group(2) or "").upper()
        if unit == "K":
            return val * 1000
        elif unit == "M":
            return val * 1000000
        return val

    num_match = re.search(r"([0-9.]+)", clean)
    return float(num_match.group(1)) if num_match else 0.0


def parse_elapsed_time(text: str) -> float:
    """Parses elapsed time in seconds e.g. '35.8s' or '1m12s'."""
    clean = text.strip()
    m_match = re.match(r"^(?:(\d+)m)?\s*([0-9.]+)s?$", clean)
    if m_match:
        mins = float(m_match.group(1)) if m_match.group(1) else 0.0
        secs = float(m_match.group(2))
        return mins * 60.0 + secs

    num_match = re.search(r"([0-9.]+)", clean)
    return float(num_match.group(1)) if num_match else 0.0


def parse_device_utilization(text: str) -> float:
    """Parses device utilization percentage e.g. '91.2%'."""
    clean = text.strip().replace("%", "")
    num_match = re.search(r"([0-9.]+)", clean)
    return float(num_match.group(1)) if num_match else 0.0


FIO_FIELD_DEFINITIONS: List[Tuple[str, str, str, Any]] = [
    ("Elapsed Time", r"Elapsed\s+Time\s*:\s*(.+)$", "elapsed_time_seconds", parse_elapsed_time),
    ("Random Read IOPS", r"Random\s+Read\s+IOPS\s*:\s*(.+)$", "random_read_iops", parse_iops),
    ("Random Read Bandwidth", r"Random\s+Read\s+Bandwidth\s*:\s*(.+)$", "random_read_bandwidth_kbs", parse_bandwidth_kbs),
    ("Random Write IOPS", r"Random\s+Write\s+IOPS\s*:\s*(.+)$", "random_write_iops", parse_iops),
    ("Random Write Bandwidth", r"Random\s+Write\s+Bandwidth\s*:\s*(.+)$", "random_write_bandwidth_kbs", parse_bandwidth_kbs),
    ("Sequential Read IOPS", r"Sequential\s+Read\s+IOPS\s*:\s*(.+)$", "sequential_read_iops", parse_iops),
    ("Sequential Read Bandwidth", r"Sequential\s+Read\s+Bandwidth\s*:\s*(.+)$", "sequential_read_bandwidth_kbs", parse_bandwidth_kbs),
    ("Sequential Write IOPS", r"Sequential\s+Write\s+IOPS\s*:\s*(.+)$", "sequential_write_iops", parse_iops),
    ("Sequential Write Bandwidth", r"Sequential\s+Write\s+Bandwidth\s*:\s*(.+)$", "sequential_write_bandwidth_kbs", parse_bandwidth_kbs),
    ("Device Utilization", r"Device\s+Utilization\s*:\s*(.+)$", "device_utilization_percent", parse_device_utilization),
]


def parse_fio_output(output: str, health_status: str = "OK") -> Dict[str, Any]:
    """Extracts normalized metrics and formatted schema fields from kubestr fio stdout."""
    # Normalized defaults
    normalized: Dict[str, Any] = {
        "elapsed_time_seconds": 0.0,
        "random_read_iops": 0.0,
        "random_read_bandwidth_kbs": 0.0,
        "random_write_iops": 0.0,
        "random_write_bandwidth_kbs": 0.0,
        "sequential_read_iops": 0.0,
        "sequential_read_bandwidth_kbs": 0.0,
        "sequential_write_iops": 0.0,
        "sequential_write_bandwidth_kbs": 0.0,
        "device_utilization_percent": 0.0,
        "health_status": health_status,
    }

    # Formatted schema defaults
    formatted: Dict[str, str] = {
        "Elapsed Time": "N/A",
        "Random Read IOPS": "N/A",
        "Random Read Bandwidth": "N/A",
        "Random Write IOPS": "N/A",
        "Random Write Bandwidth": "N/A",
        "Sequential Read IOPS": "N/A",
        "Sequential Read Bandwidth": "N/A",
        "Sequential Write IOPS": "N/A",
        "Sequential Write Bandwidth": "N/A",
        "Device Utilization": "N/A",
        "Health / Pass Status": health_status,
    }

    lines = [line.strip() for line in output.splitlines()]
    for field, pat, norm_key, parser_func in FIO_FIELD_DEFINITIONS:
        for line in lines:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                raw_val = m.group(1).strip()
                formatted[field] = raw_val
                normalized[norm_key] = parser_func(raw_val)
                break

    # Combined dictionary containing normalized and formatted fields
    return {**normalized, **formatted}


def check_dangling_volumes(
    kubeconfig_path: Optional[str] = None,
    dry_run: bool = False,
) -> List[str]:
    """Inspects cluster for dangling Longhorn volumes, PVCs, or VolumeAttachments."""
    if dry_run or not kubeconfig_path:
        return []

    dangling: List[str] = []
    cmd_prefix = ["kubectl", "--kubeconfig", kubeconfig_path]

    def _is_benchmark_volume(name: str) -> bool:
        low = name.lower()
        return "kubestr" in low or "benchmark" in low or low.startswith("kubestr-fio-")

    # Query Longhorn volumes
    try:
        res_vols = subprocess.run(
            cmd_prefix
            + [
                "-n",
                "longhorn-system",
                "get",
                "volumes.longhorn.io",
                "-o",
                "jsonpath={.items[*].metadata.name}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res_vols.returncode == 0 and res_vols.stdout.strip():
            vols = res_vols.stdout.strip().split()
            dangling.extend([v for v in vols if _is_benchmark_volume(v)])
    except Exception:
        pass

    # Query PVCs in all namespaces matching kubestr
    try:
        res_pvc = subprocess.run(
            cmd_prefix
            + [
                "get",
                "pvc",
                "-A",
                "-o",
                'jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name}{"\\n"}{end}',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res_pvc.returncode == 0 and res_pvc.stdout.strip():
            pvcs = [line.strip() for line in res_pvc.stdout.splitlines() if line.strip()]
            dangling.extend([p for p in pvcs if _is_benchmark_volume(p)])
    except Exception:
        pass

    # Query VolumeAttachments
    try:
        res_va = subprocess.run(
            cmd_prefix
            + [
                "get",
                "volumeattachments",
                "-o",
                "jsonpath={.items[*].metadata.name}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res_va.returncode == 0 and res_va.stdout.strip():
            vas = res_va.stdout.strip().split()
            dangling.extend([v for v in vas if _is_benchmark_volume(v)])
    except Exception:
        pass

    return dangling


def persist_state_file(data: Dict[str, Any], state_file_path: str) -> None:
    """Writes state payload to disk cleanly, handling permissions gracefully."""
    try:
        parent = os.path.dirname(state_file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(state_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    except Exception as e:
        sys.stderr.write(f"Warning: could not write state file {state_file_path}: {e}\n")


def emit_result(
    payload: Dict[str, Any],
    state_file: Optional[str] = None,
    json_output: bool = False,
    exit_code: int = 0,
) -> int:
    """Persists state to disk and emits formatted JSON to stdout cleanly."""
    if state_file:
        persist_state_file(payload, state_file)
    if json_output:
        print(json.dumps(payload, indent=2))
    return exit_code


def build_skipped_payload(
    status: str,
    reason: str,
    storage_class: str = "longhorn",
    volume_size: str = "20Gi",
) -> Dict[str, Any]:
    """Generates canonical SKIPPED evidence JSON payload."""
    return {
        "status": status,
        "reason": reason,
        "guard_passed": False,
        "health_status": "SKIPPED",
        "metrics": {},
        "storage_class": storage_class,
        "volume_size": volume_size,
        "dangling_volumes": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def simulate_dry_run_benchmark(storage_class: str, volume_size: str) -> Dict[str, Any]:
    """Simulates kubestr fio benchmark execution for --dry-run validation."""
    simulated_stdout = f"""
PVC created: kubestr-fio-pvc-dryrun
Pod created: kubestr-fio-pod-dryrun
Running FIO test with storageclass '{storage_class}', size '{volume_size}'...
FIO test completed

Results:
Elapsed Time: 35.8s
FIO version: 3.28

Random Read IOPS: 24500
Random Read Bandwidth: 95.7MB/s (98000 KiB/s)
Random Write IOPS: 12300
Random Write Bandwidth: 48.0MB/s (49200 KiB/s)
Sequential Read IOPS: 35000
Sequential Read Bandwidth: 136.7MB/s (140000 KiB/s)
Sequential Write IOPS: 21000
Sequential Write Bandwidth: 82.0MB/s (84000 KiB/s)
Device Utilization: 91.2%
"""
    metrics = parse_fio_output(simulated_stdout, health_status="OK")
    return {
        "status": "OK",
        "guard_passed": True,
        "health_status": "OK",
        "metrics": metrics,
        "storage_class": storage_class,
        "volume_size": volume_size,
        "dangling_volumes": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GDC Storage Capability Validation & Benchmarking Utility (kubestr fio runner)."
    )
    parser.add_argument(
        "--storage-class",
        default="longhorn",
        help="Target Kubernetes StorageClass to benchmark (default: longhorn)",
    )
    parser.add_argument(
        "--volume-size",
        default="20Gi",
        help="PVC volume size for synthetic FIO workload (default: 20Gi)",
    )
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", "/etc/kubernetes/admin.conf"),
        help="Path to Kubernetes admin kubeconfig (default: /etc/kubernetes/admin.conf)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Execution timeout in seconds for kubestr fio (default: 300)",
    )
    parser.add_argument(
        "--state-file",
        default="/var/gdc-install/state/storage-benchmark.json",
        help="Destination path to persist benchmark results JSON (default: /var/gdc-install/state/storage-benchmark.json)",
    )
    parser.add_argument(
        "--json",
        "--json-output",
        dest="json_output",
        action="store_true",
        help="Output benchmark results JSON payload to stdout",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate benchmark execution without creating actual PVCs or pods",
    )
    parser.add_argument(
        "--skip-guard",
        action="store_true",
        help="Skip pre-flight longhorn-system readiness guard check",
    )
    parser.add_argument(
        "--kubestr-path",
        default=None,
        help="Explicit path to kubestr binary",
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow downloading kubestr from upstream release assets if missing locally",
    )

    args = parser.parse_args()

    # 1. Architecture Verification
    arch_ok, arch_name = verify_architecture()
    if not arch_ok:
        sys.stderr.write(f"ERROR: Unsupported host architecture '{arch_name}'. Requires x86_64/amd64.\n")
        payload = {
            "status": "FAIL",
            "reason": f"Unsupported architecture: {arch_name}",
            "guard_passed": False,
            "health_status": "FAIL",
            "storage_class": args.storage_class,
            "volume_size": args.volume_size,
            "dangling_volumes": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {},
        }
        return emit_result(payload, args.state_file, args.json_output, exit_code=1)

    # 2. Dry-Run Bypass
    if args.dry_run:
        payload = simulate_dry_run_benchmark(args.storage_class, args.volume_size)
        return emit_result(payload, args.state_file, args.json_output, exit_code=0)

    # 3. Kubeconfig and Cluster Guard
    kube_ok, kube_status, kube_reason = check_kubeconfig_and_cluster(args.kubeconfig)
    if not kube_ok:
        sys.stderr.write(f"WARNING: Cluster or kubeconfig check failed: {kube_reason}\n")
        payload = build_skipped_payload(
            status=kube_status,
            reason=kube_reason,
            storage_class=args.storage_class,
            volume_size=args.volume_size,
        )
        return emit_result(payload, args.state_file, args.json_output, exit_code=0)

    # 4. Longhorn-system Pre-Flight Guard
    if not args.skip_guard:
        guard_ok, guard_reason = check_longhorn_system_ready(args.kubeconfig)
        if not guard_ok:
            sys.stderr.write(
                "WARNING: longhorn-system is not installed or not ready. Skipping kubestr execution.\n"
            )
            payload = build_skipped_payload(
                status="SKIPPED",
                reason=f"longhorn-system is not installed or not fully ready: {guard_reason}",
                storage_class=args.storage_class,
                volume_size=args.volume_size,
            )
            return emit_result(payload, args.state_file, args.json_output, exit_code=0)

    # 5. Discover kubestr binary
    kubestr_bin = discover_kubestr(
        explicit_path=args.kubestr_path, allow_download=args.allow_download
    )
    if not kubestr_bin:
        sys.stderr.write("ERROR: kubestr binary not found in PATH or standard offline locations.\n")
        payload = build_skipped_payload(
            status="SKIPPED_NO_KUBESTR",
            reason="kubestr binary not found",
            storage_class=args.storage_class,
            volume_size=args.volume_size,
        )
        return emit_result(payload, args.state_file, args.json_output, exit_code=0)

    # 6. StorageClass Inspection
    sc_ok, sc_msg = inspect_storage_class(args.kubeconfig, args.storage_class)
    if not sc_ok:
        sys.stderr.write(f"ERROR: {sc_msg}\n")
        payload = {
            "status": "FAIL",
            "reason": sc_msg,
            "guard_passed": True,
            "health_status": "FAIL",
            "metrics": {},
            "storage_class": args.storage_class,
            "volume_size": args.volume_size,
            "dangling_volumes": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return emit_result(payload, args.state_file, args.json_output, exit_code=1)

    # 7. Execute kubestr fio
    env = os.environ.copy()
    if args.kubeconfig:
        env["KUBECONFIG"] = args.kubeconfig

    cmd = [
        kubestr_bin,
        "fio",
        "-s",
        args.storage_class,
        "-z",
        args.volume_size,
        "--cleanup=true",
    ]
    sys.stderr.write(f"Executing: {' '.join(cmd)}\n")

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            env=env,
        )
        stdout = res.stdout
        stderr = res.stderr
        success = res.returncode == 0
    except subprocess.TimeoutExpired:
        stdout = ""
        stderr = f"kubestr fio timed out after {args.timeout} seconds"
        success = False
    except Exception as e:
        stdout = ""
        stderr = str(e)
        success = False

    # 8. Check dangling volumes
    dangling = check_dangling_volumes(args.kubeconfig, dry_run=False)

    # 9. Parse output & normalize
    health_status = "OK" if success else "FAIL"
    status = "OK" if success else "FAIL"
    metrics = parse_fio_output(stdout, health_status=health_status)

    payload = {
        "status": status,
        "guard_passed": True,
        "health_status": health_status,
        "metrics": metrics,
        "storage_class": args.storage_class,
        "volume_size": args.volume_size,
        "dangling_volumes": dangling,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if not success:
        payload["reason"] = stderr.strip() or "kubestr fio returned non-zero exit code"

    return emit_result(payload, args.state_file, args.json_output, exit_code=(0 if success else 1))


if __name__ == "__main__":
    sys.exit(main())
