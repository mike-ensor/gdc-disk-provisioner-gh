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

"""Unit tests for bin/cluster/run-storage-benchmark.py storage benchmark utility."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(PROJECT_ROOT, "bin/cluster/run-storage-benchmark.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("run_storage_benchmark", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStorageBenchmark(unittest.TestCase):
    """Test suite for run-storage-benchmark.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "storage-benchmark.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_script_exists_and_executable(self):
        """Verifies script exists, has shebang, and executable bits set."""
        self.assertTrue(os.path.exists(SCRIPT_PATH), f"Script not found at {SCRIPT_PATH}")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), "Script is not executable")
        with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        self.assertEqual(first_line, "#!/usr/bin/env python3", "Shebang mismatch")

    def test_help_flag(self):
        """Verifies --help and -h flags display usage and expected options."""
        for flag in ["--help", "-h"]:
            res = subprocess.run(
                [SCRIPT_PATH, flag],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, f"{flag} returned non-zero")
            self.assertIn("usage:", res.stdout.lower())
            self.assertIn("--storage-class", res.stdout)
            self.assertIn("--volume-size", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--skip-guard", res.stdout)
            self.assertIn("--kubeconfig", res.stdout)
            self.assertIn("--timeout", res.stdout)
            self.assertIn("--state-file", res.stdout)
            self.assertIn("--json", res.stdout)

    def test_missing_kubeconfig_skips_gracefully(self):
        """Verifies missing kubeconfig exits cleanly (code 0) with SKIPPED status."""
        non_existent_kubeconfig = os.path.join(self.temp_dir.name, "nonexistent.conf")
        res = subprocess.run(
            [
                SCRIPT_PATH,
                "--kubeconfig", non_existent_kubeconfig,
                "--state-file", self.state_file,
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Expected exit code 0, got {res.returncode}")
        data = json.loads(res.stdout)
        self.assertIn(data.get("status"), ["SKIPPED", "SKIPPED_NO_CLUSTER", "FAILED_KUBECONFIG"])
        self.assertEqual(data.get("guard_passed"), False)
        self.assertEqual(data.get("health_status"), "SKIPPED")
        self.assertEqual(data.get("metrics"), {})

    def test_longhorn_system_guard_skips_when_ns_missing(self):
        """Verifies pre-flight guard skips when longhorn-system namespace is missing."""
        # Create a dummy kubeconfig file so it passes the file existence check
        fake_kubeconfig = os.path.join(self.temp_dir.name, "fake.conf")
        with open(fake_kubeconfig, "w", encoding="utf-8") as f:
            f.write("apiVersion: v1\nclusters: []\n")

        # Create a mock kubectl script in a temp bin
        mock_bin = os.path.join(self.temp_dir.name, "bin")
        os.makedirs(mock_bin, exist_ok=True)
        mock_kubectl = os.path.join(mock_bin, "kubectl")
        with open(mock_kubectl, "w", encoding="utf-8") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"cluster-info"* ]] || [[ "$*" == *"version"* ]]; then
    exit 0
fi
if [[ "$*" == *"get ns longhorn-system"* ]]; then
    echo "Error from server (NotFound): namespaces \\"longhorn-system\\" not found" >&2
    exit 1
fi
exit 0
""")
        os.chmod(mock_kubectl, 0o755)

        env = os.environ.copy()
        env["PATH"] = f"{mock_bin}:{env['PATH']}"

        res = subprocess.run(
            [
                SCRIPT_PATH,
                "--kubeconfig", fake_kubeconfig,
                "--state-file", self.state_file,
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("WARNING: longhorn-system is not installed or not ready", res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "SKIPPED")
        self.assertEqual(
            data.get("reason"),
            "longhorn-system is not installed or not fully ready: Namespace 'longhorn-system' not found",
        )
        self.assertEqual(data.get("guard_passed"), False)
        self.assertEqual(data.get("health_status"), "SKIPPED")
        self.assertEqual(data.get("metrics"), {})

    def test_longhorn_system_guard_skips_when_pods_not_ready(self):
        """Verifies pre-flight guard skips when longhorn-manager has 0 ready replicas."""
        fake_kubeconfig = os.path.join(self.temp_dir.name, "fake.conf")
        with open(fake_kubeconfig, "w", encoding="utf-8") as f:
            f.write("apiVersion: v1\nclusters: []\n")

        mock_bin = os.path.join(self.temp_dir.name, "bin")
        os.makedirs(mock_bin, exist_ok=True)
        mock_kubectl = os.path.join(mock_bin, "kubectl")
        with open(mock_kubectl, "w", encoding="utf-8") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"cluster-info"* ]] || [[ "$*" == *"version"* ]]; then
    exit 0
fi
if [[ "$*" == *"get ns longhorn-system"* ]]; then
    exit 0
fi
if [[ "$*" == *"get daemonset longhorn-manager"* ]] || [[ "$*" == *"get pods"* ]]; then
    # Return 0 ready pods
    echo '{"items": []}'
    exit 0
fi
exit 0
""")
        os.chmod(mock_kubectl, 0o755)

        env = os.environ.copy()
        env["PATH"] = f"{mock_bin}:{env['PATH']}"

        res = subprocess.run(
            [
                SCRIPT_PATH,
                "--kubeconfig", fake_kubeconfig,
                "--state-file", self.state_file,
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("WARNING: longhorn-system is not installed or not ready", res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "SKIPPED")
        self.assertEqual(data.get("guard_passed"), False)

    def test_dry_run_execution_and_schema(self):
        """Verifies --dry-run simulates execution, outputs normalized metrics and formatted schema."""
        res = subprocess.run(
            [
                SCRIPT_PATH,
                "--dry-run",
                "--storage-class", "longhorn",
                "--volume-size", "20Gi",
                "--state-file", self.state_file,
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Dry run failed: {res.stderr}")
        data = json.loads(res.stdout)

        self.assertEqual(data.get("status"), "OK")
        self.assertEqual(data.get("guard_passed"), True)
        self.assertEqual(data.get("health_status"), "OK")

        metrics = data.get("metrics", {})
        # Normalized float fields required by schema
        normalized_keys = [
            "elapsed_time_seconds",
            "random_read_iops",
            "random_read_bandwidth_kbs",
            "random_write_iops",
            "random_write_bandwidth_kbs",
            "sequential_read_iops",
            "sequential_read_bandwidth_kbs",
            "sequential_write_iops",
            "sequential_write_bandwidth_kbs",
            "device_utilization_percent",
            "health_status",
        ]
        for key in normalized_keys:
            self.assertIn(key, metrics, f"Missing normalized metric key '{key}'")
            if key != "health_status":
                self.assertIsInstance(metrics[key], (int, float), f"Key '{key}' is not float/int")

        # Formatted schema fields matching Issue #17 table
        formatted_keys = [
            "Elapsed Time",
            "Random Read IOPS",
            "Random Read Bandwidth",
            "Random Write IOPS",
            "Random Write Bandwidth",
            "Sequential Read IOPS",
            "Sequential Read Bandwidth",
            "Sequential Write IOPS",
            "Sequential Write Bandwidth",
            "Device Utilization",
            "Health / Pass Status",
        ]
        for key in formatted_keys:
            self.assertIn(key, metrics, f"Missing formatted metric key '{key}'")

        # Verify state file was written
        self.assertTrue(os.path.exists(self.state_file))
        with open(self.state_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        self.assertEqual(saved_data.get("status"), "OK")

    def test_fio_stdout_parsing_helper(self):
        """Tests internal parser on representative kubestr fio output."""
        module = _load_module()

        sample_fio_output = """
PVC created: kubestr-fio-pvc-benchmark
Pod created: kubestr-fio-pod-benchmark
Running FIO test...
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
        metrics = module.parse_fio_output(sample_fio_output, health_status="OK")
        self.assertAlmostEqual(metrics["elapsed_time_seconds"], 35.8)
        self.assertAlmostEqual(metrics["random_read_iops"], 24500.0)
        self.assertAlmostEqual(metrics["random_read_bandwidth_kbs"], 98000.0)
        self.assertAlmostEqual(metrics["random_write_iops"], 12300.0)
        self.assertAlmostEqual(metrics["random_write_bandwidth_kbs"], 49200.0)
        self.assertAlmostEqual(metrics["sequential_read_iops"], 35000.0)
        self.assertAlmostEqual(metrics["sequential_read_bandwidth_kbs"], 140000.0)
        self.assertAlmostEqual(metrics["sequential_write_iops"], 21000.0)
        self.assertAlmostEqual(metrics["sequential_write_bandwidth_kbs"], 84000.0)
        self.assertAlmostEqual(metrics["device_utilization_percent"], 91.2)
        self.assertEqual(metrics["health_status"], "OK")

        self.assertEqual(metrics["Elapsed Time"], "35.8s")
        self.assertEqual(metrics["Random Read IOPS"], "24500")
        self.assertEqual(metrics["Random Read Bandwidth"], "95.7MB/s (98000 KiB/s)")
        self.assertEqual(metrics["Random Write IOPS"], "12300")
        self.assertEqual(metrics["Random Write Bandwidth"], "48.0MB/s (49200 KiB/s)")
        self.assertEqual(metrics["Sequential Read IOPS"], "35000")
        self.assertEqual(metrics["Sequential Read Bandwidth"], "136.7MB/s (140000 KiB/s)")
        self.assertEqual(metrics["Sequential Write IOPS"], "21000")
        self.assertEqual(metrics["Sequential Write Bandwidth"], "82.0MB/s (84000 KiB/s)")
        self.assertEqual(metrics["Device Utilization"], "91.2%")
        self.assertEqual(metrics["Health / Pass Status"], "OK")

    def test_kubestr_binary_discovery(self):
        """Verifies discover_kubestr finds binary in explicit path or standard locations."""
        module = _load_module()

        # 1. Custom path
        mock_kubestr = os.path.join(self.temp_dir.name, "my-kubestr")
        with open(mock_kubestr, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(mock_kubestr, 0o755)

        found = module.discover_kubestr(explicit_path=mock_kubestr)
        self.assertEqual(found, mock_kubestr)

        # 2. Standard locations fallback
        custom_data_dir = os.path.join(self.temp_dir.name, "custom-data/tools/kubestr")
        os.makedirs(custom_data_dir, exist_ok=True)
        std_kubestr = os.path.join(custom_data_dir, "kubestr")
        with open(std_kubestr, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(std_kubestr, 0o755)

        with patch("shutil.which", return_value=None):
            with patch.object(module, "STANDARD_KUBESTR_PATHS", [std_kubestr]):
                found = module.discover_kubestr(explicit_path=None)
                self.assertEqual(found, std_kubestr)

    def test_architecture_verification_failure(self):
        """Verifies script fails when executed on unsupported CPU architecture."""
        module = _load_module()
        with patch("platform.machine", return_value="aarch64"):
            ok, arch = module.verify_architecture()
            self.assertFalse(ok)
            self.assertEqual(arch, "aarch64")

        with patch.object(module, "verify_architecture", return_value=(False, "armv7l")), \
             patch("sys.stderr"), \
             patch("sys.stdout"):
            with patch("sys.argv", ["run-storage-benchmark.py", "--state-file", self.state_file, "--json"]):
                ret = module.main()
                self.assertEqual(ret, 1)
                self.assertTrue(os.path.exists(self.state_file))
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data.get("status"), "FAIL")
                self.assertEqual(data.get("health_status"), "FAIL")
                for key in [
                    "status",
                    "reason",
                    "guard_passed",
                    "health_status",
                    "storage_class",
                    "volume_size",
                    "dangling_volumes",
                    "timestamp",
                    "metrics",
                ]:
                    self.assertIn(key, data)

    def test_skip_guard_flag_bypasses_longhorn_check(self):
        """Verifies --skip-guard proceeds even if longhorn-system is not installed."""
        fake_kubeconfig = os.path.join(self.temp_dir.name, "fake.conf")
        with open(fake_kubeconfig, "w", encoding="utf-8") as f:
            f.write("apiVersion: v1\nclusters: []\n")

        mock_bin = os.path.join(self.temp_dir.name, "bin")
        os.makedirs(mock_bin, exist_ok=True)
        mock_kubectl = os.path.join(mock_bin, "kubectl")
        with open(mock_kubectl, "w", encoding="utf-8") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"cluster-info"* ]] || [[ "$*" == *"version"* ]]; then
    exit 0
fi
if [[ "$*" == *"get ns longhorn-system"* ]]; then
    echo "NotFound" >&2
    exit 1
fi
if [[ "$*" == *"get sc"* ]]; then
    echo '{"provisioner": "driver.longhorn.io"}'
    exit 0
fi
exit 0
""")
        os.chmod(mock_kubectl, 0o755)

        mock_kubestr = os.path.join(mock_bin, "kubestr")
        with open(mock_kubestr, "w", encoding="utf-8") as f:
            f.write("""#!/usr/bin/env bash
echo "Elapsed Time: 10s"
echo "Random Read IOPS: 1000"
echo "Random Read Bandwidth: 10MB/s (10000 KiB/s)"
echo "Random Write IOPS: 500"
echo "Random Write Bandwidth: 5MB/s (5000 KiB/s)"
echo "Sequential Read IOPS: 2000"
echo "Sequential Read Bandwidth: 20MB/s (20000 KiB/s)"
echo "Sequential Write IOPS: 1000"
echo "Sequential Write Bandwidth: 10MB/s (10000 KiB/s)"
echo "Device Utilization: 50%"
exit 0
""")
        os.chmod(mock_kubestr, 0o755)

        env = os.environ.copy()
        env["PATH"] = f"{mock_bin}:{env['PATH']}"

        res = subprocess.run(
            [
                SCRIPT_PATH,
                "--kubeconfig", fake_kubeconfig,
                "--skip-guard",
                "--state-file", self.state_file,
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "OK")
        self.assertEqual(data.get("guard_passed"), True)

    def test_missing_kubestr_without_download(self):
        """Verifies missing kubestr reports SKIPPED_NO_KUBESTR cleanly."""
        fake_kubeconfig = os.path.join(self.temp_dir.name, "fake.conf")
        with open(fake_kubeconfig, "w", encoding="utf-8") as f:
            f.write("apiVersion: v1\nclusters: []\n")

        mock_bin = os.path.join(self.temp_dir.name, "bin")
        os.makedirs(mock_bin, exist_ok=True)
        mock_kubectl = os.path.join(mock_bin, "kubectl")
        with open(mock_kubectl, "w", encoding="utf-8") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"cluster-info"* ]] || [[ "$*" == *"version"* ]]; then
    exit 0
fi
if [[ "$*" == *"get ns longhorn-system"* ]]; then
    exit 0
fi
if [[ "$*" == *"get pods"* ]]; then
    echo '{"items": [{"metadata": {"name": "longhorn-manager-abc", "labels": {"app": "longhorn-manager"}}, "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}]}'
    exit 0
fi
exit 0
""")
        os.chmod(mock_kubectl, 0o755)

        # Empty bin directory without kubestr, preserving current Python on PATH
        env = os.environ.copy()
        py_dir = os.path.dirname(sys.executable)
        env["PATH"] = f"{mock_bin}:{py_dir}:/usr/local/bin:/usr/bin:/bin"

        res = subprocess.run(
            [
                sys.executable,
                SCRIPT_PATH,
                "--kubeconfig", fake_kubeconfig,
                "--kubestr-path", "/nonexistent/kubestr",
                "--state-file", self.state_file,
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "SKIPPED_NO_KUBESTR")
        self.assertEqual(data.get("health_status"), "SKIPPED")

    def test_fio_parsing_various_units(self):
        """Verifies bandwidth, IOPS, and time units are properly parsed."""
        module = _load_module()
        # Test GiB/s, MiB/s, KiB/s, B/s
        self.assertAlmostEqual(module.parse_bandwidth_kbs("1.5 GiB/s"), 1.5 * 1024 * 1024)
        self.assertAlmostEqual(module.parse_bandwidth_kbs("200 MiB/s"), 200 * 1024)
        self.assertAlmostEqual(module.parse_bandwidth_kbs("500 KiB/s"), 500)
        self.assertAlmostEqual(module.parse_bandwidth_kbs("2048 B/s"), 2.0)
        # Test commas in bandwidth
        self.assertAlmostEqual(module.parse_bandwidth_kbs("95.7MB/s (98,000 KiB/s)"), 98000.0)
        self.assertAlmostEqual(module.parse_bandwidth_kbs("1,200 MB/s"), 1200 * 1024)

        # Test IOPS k/M suffixes
        self.assertAlmostEqual(module.parse_iops("12.5k"), 12500)
        self.assertAlmostEqual(module.parse_iops("1.2M"), 1200000)
        self.assertAlmostEqual(module.parse_iops("34,500"), 34500)

        # Test Elapsed Time minutes
        self.assertAlmostEqual(module.parse_elapsed_time("2m30s"), 150.0)
        self.assertAlmostEqual(module.parse_elapsed_time("45s"), 45.0)

    def test_dangling_volume_check(self):
        """Verifies check_dangling_volumes detects or confirms no residual volumes."""
        module = _load_module()

        # In dry run mode, check_dangling_volumes returns empty list
        res = module.check_dangling_volumes(kubeconfig_path=None, dry_run=True)
        self.assertEqual(res, [])

        # Verify production volumes without kubestr or benchmark are NOT flagged
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "pvc-production-data-vol longhorn-system-vol\n"
            mock_run.return_value = mock_proc
            res = module.check_dangling_volumes(
                kubeconfig_path="/etc/kubernetes/admin.conf", dry_run=False
            )
            self.assertEqual(res, [])

        # Verify benchmark and kubestr volumes/PVCs/VolumeAttachments are detected while production ones are ignored
        def mock_subprocess_run(cmd, *args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0
            cmd_str = " ".join(cmd)
            if "volumes.longhorn.io" in cmd_str:
                proc.stdout = "prod-data-volume kubestr-fio-vol-01 benchmark-temp-vol prod-db-vol\n"
            elif "pvc" in cmd_str:
                proc.stdout = "prod-ns/prod-pvc\ndefault/kubestr-fio-pvc-1234\n"
            elif "volumeattachments" in cmd_str:
                proc.stdout = "csi-att-prod kubestr-va-5678\n"
            else:
                proc.stdout = ""
            return proc

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            res = module.check_dangling_volumes(
                kubeconfig_path="/etc/kubernetes/admin.conf", dry_run=False
            )
            self.assertIn("kubestr-fio-vol-01", res)
            self.assertIn("benchmark-temp-vol", res)
            self.assertIn("default/kubestr-fio-pvc-1234", res)
            self.assertIn("kubestr-va-5678", res)
            self.assertNotIn("prod-data-volume", res)
            self.assertNotIn("prod-db-vol", res)
            self.assertNotIn("prod-ns/prod-pvc", res)
            self.assertNotIn("csi-att-prod", res)


if __name__ == "__main__":
    unittest.main()
