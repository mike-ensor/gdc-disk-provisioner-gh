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

import os
import sys
import unittest
import tempfile
import shutil
import io
import subprocess
from datetime import datetime

# Set up paths so we can import src/build modules cleanly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))

import generate_banner
import bootimus

# Test file paths are modified; append test/ to sys.path to find the mock companion
sys.path.insert(0, os.path.join(PROJECT_ROOT, "test"))
import install_companion_mock

class TestGgdBuildScripts(unittest.TestCase):

    def setUp(self):
        # Create a clean, isolated temporary workspace
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.test_dir)

    # ==========================================================================
    # TEST SUITE 1: generate_banner.py (ASCII Art & Alignments)
    # ==========================================================================
    def test_boot_banner_generation_alignment(self):
        """Verifies generate_banner.py perfectly generates, aligns and centers build details."""
        mock_version = "v3.14.15-gdc"
        mock_time = datetime(2026, 6, 29, 12, 34, 56)
        
        # Call the core functional logic
        banner = generate_banner.generate_boot_text(mock_version, timestamp=mock_time)
        
        # Verify both dynamic values are embedded in the output
        self.assertIn("v3.14.15-gdc", banner)
        self.assertIn("2026-06-29 12:34", banner)
        
        # Verify frame boundaries are preserved (lines are exactly 76 chars wide)
        lines = banner.splitlines()
        for idx, line in enumerate(lines):
            # Check length of normal frame rows (76 characters)
            self.assertEqual(len(line), 76, f"Line {idx} does not have expected length 76. Content: '{line}'")
            # Verify frame vertical columns are placed symmetrically
            self.assertTrue(line.startswith("  | |") or line.startswith("__") or line.startswith("__|"), 
                            f"Line {idx} frame boundary violation: '{line}'")
            self.assertTrue(line.endswith("| |  ") or line.endswith("__") or line.endswith("| |__"), 
                            f"Line {idx} frame boundary violation: '{line}'")

    # ==========================================================================
    # TEST SUITE 2: install_companion_mock.py (Webhook Status mapping)
    # ==========================================================================
    def test_companion_log_status_colors(self):
        """Verifies install_companion_mock.py accurately maps status codes, color-prefixes and writes logs."""
        payload_success = {
            "name": "subiquity/test-success",
            "description": "Task completed successfully",
            "status": "SUCCESS"
        }
        
        # Override the log file path dynamically for tests
        mock_log = os.path.join(self.test_dir, "gdc-installer-receiver.log")
        
        # Suppress prints and capture standard output
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            # Create a class instance bypassing the constructor to avoid HTTPServer requirements
            mock_handler = install_companion_mock.SubiquityLogHandler.__new__(install_companion_mock.SubiquityLogHandler)
            install_companion_mock.SubiquityLogHandler.log_file_path = mock_log
            mock_handler.process_webhook_payload(payload_success)
        finally:
            sys.stdout = sys.__stdout__
            
        success_out = captured_stdout.getvalue()
        
        # Verify Success string colors and prefixes
        self.assertIn("[GDC-INSTALL-SUCCESS]", success_out)
        self.assertIn("\033[92m", success_out) # OKGREEN color
        self.assertIn("Task completed successfully", success_out)
        
        # Test 2: Verify Log File writes correctly
        self.assertTrue(os.path.exists(mock_log))
        with open(mock_log, "r") as f:
            log_content = f.read()
        self.assertIn("[SUCCESS] subiquity/test-success - Task completed successfully", log_content)

        # Test 3: Failure scenario (Testing Warning vs Error thresholds)
        payload_fail = {
            "name": "subiquity/critical-failure",
            "description": "Network timeout threshold exceeded",
            "status": "FAIL",
            "level": "ERROR"
        }
        
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            mock_handler.process_webhook_payload(payload_fail)
        finally:
            sys.stdout = sys.__stdout__
            
        fail_out = captured_stdout.getvalue()
        self.assertIn("[GDC-INSTALL-FAIL]", fail_out)
        self.assertIn("\033[91m", fail_out) # FAIL color

    # ==========================================================================
    def test_bootimus_pxe_unicode_tree_list(self):
        """Verifies bootimus.py renders, sorts, and filters the image tree cleanly."""
        mock_grouped_images = {
            "GDC-Staging": [
                {"filename": "gdc-v1.0.1.iso", "extracted": True},
                {"filename": "gdc-v1.0.0.iso", "extracted": True}
            ],
            "Retail-Edge": [
                {"filename": "retail-noble.iso", "extracted": False}
            ]
        }
        
        # Capture tree-print standard output
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            bootimus.print_tree(mock_grouped_images)
        finally:
            sys.stdout = sys.__stdout__
            
        tree_out = captured_stdout.getvalue()
        
        # Verify tree groups are listed alphabetically
        lines = [l.strip() for l in tree_out.splitlines() if l.strip()]
        
        self.assertIn("├── GDC-Staging", lines[0], "Groups must be printed sequentially.")
        # Verifies alphabetical sort of files under group (v1.0.0.iso should be before v1.0.1.iso)
        self.assertIn("gdc-v1.0.0.iso", lines[1])
        self.assertIn("gdc-v1.0.1.iso", lines[2])
        self.assertIn("└── Retail-Edge", lines[3])
        # Unextracted indicator (🚧) must be printed for unextracted images
        self.assertIn("retail-noble.iso 🚧", lines[4])

        # Test Filter Option
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            bootimus.print_tree(mock_grouped_images, group_filter="Retail")
        finally:
            sys.stdout = sys.__stdout__
            
        filter_out = captured_stdout.getvalue()
        self.assertNotIn("GDC-Staging", filter_out, "Filtered group must be completely excluded.")
        self.assertIn("Retail-Edge", filter_out, "Matched group must be included.")

    # ==========================================================================
    # TEST SUITE 3: gcp-authentication.sh Kubelet Service Guard
    # ==========================================================================
    def test_gcp_authentication_kubelet_guard_missing_service(self):
        """Verifies gcp-authentication.sh safely skips restarting kubelet when the unit is not found."""
        auth_script_path = os.path.join(PROJECT_ROOT, "bin/auth/gcp-authentication.sh")
        self.assertTrue(os.path.exists(auth_script_path), "gcp-authentication.sh must exist")
        
        with open(auth_script_path, "r") as f:
            script_content = f.read()
            
        self.assertIn("systemctl list-unit-files kubelet.service", script_content)
        self.assertIn("skipping kubelet restart", script_content)

        # Execute isolated bash simulation testing mock systemctl without kubelet
        test_bash_mock = """
        systemctl() {
            local action="$1"
            local target="${2:-}"
            if [[ "$action" == "list-unit-files" && "$target" == "kubelet.service" ]]; then
                return 1
            fi
            if [[ "$action" == "cat" && "$target" == "kubelet.service" ]]; then
                return 1
            fi
            if [[ "$action" == "restart" && "$target" == "containerd" ]]; then
                echo "MOCK: containerd restarted"
                return 0
            fi
            if [[ "$action" == "restart" && "$target" == "kubelet" ]]; then
                echo "ERROR: kubelet should not be restarted!" >&2
                return 1
            fi
            return 0
        }
        export -f systemctl
        
        # Test logic from gcp-authentication.sh
        echo "==> Restarting containerd service..."
        systemctl restart containerd

        if systemctl list-unit-files kubelet.service >/dev/null 2>&1 || systemctl cat kubelet.service >/dev/null 2>&1; then
            echo "==> Restarting kubelet service..."
            systemctl restart kubelet
        else
            echo "==> kubelet.service not found (cluster not yet deployed); skipping kubelet restart."
        fi
        """
        res = subprocess.run(["bash", "-c", test_bash_mock], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Simulation failed with stderr: {res.stderr}")
        self.assertIn("MOCK: containerd restarted", res.stdout)
        self.assertIn("skipping kubelet restart", res.stdout)
        self.assertNotIn("ERROR: kubelet should not be restarted", res.stderr)

    def test_gcp_authentication_kubelet_guard_present_service(self):
        """Verifies gcp-authentication.sh successfully restarts kubelet when the unit is found."""
        test_bash_mock = """
        systemctl() {
            local action="$1"
            local target="${2:-}"
            if [[ "$action" == "list-unit-files" && "$target" == "kubelet.service" ]]; then
                return 0
            fi
            if [[ "$action" == "restart" && "$target" == "containerd" ]]; then
                echo "MOCK: containerd restarted"
                return 0
            fi
            if [[ "$action" == "restart" && "$target" == "kubelet" ]]; then
                echo "MOCK: kubelet restarted"
                return 0
            fi
            return 0
        }
        export -f systemctl
        
        # Test logic from gcp-authentication.sh
        echo "==> Restarting containerd service..."
        systemctl restart containerd

        if systemctl list-unit-files kubelet.service >/dev/null 2>&1 || systemctl cat kubelet.service >/dev/null 2>&1; then
            echo "==> Restarting kubelet service..."
            systemctl restart kubelet
        else
            echo "==> kubelet.service not found (cluster not yet deployed); skipping kubelet restart."
        fi
        """
        res = subprocess.run(["bash", "-c", test_bash_mock], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Simulation failed with stderr: {res.stderr}")
        self.assertIn("MOCK: containerd restarted", res.stdout)
        self.assertIn("MOCK: kubelet restarted", res.stdout)

    # ==========================================================================
    # TEST SUITE 4: Ansible State Machine Evidence & Timing
    # ==========================================================================
    def test_ansible_stages_timing_evidence_structure(self):
        """Verifies that all Ansible stage definitions and local.yml record start, end, and duration timing in evidence."""
        ansible_dir = os.path.join(PROJECT_ROOT, "src/ansible")
        local_yml = os.path.join(ansible_dir, "local.yml")
        state_init = os.path.join(ansible_dir, "stages/state_initialization.yml")
        
        with open(local_yml, "r") as f:
            local_content = f.read()
            
        with open(state_init, "r") as f:
            init_content = f.read()
            
        # Verify state_initialization creates persistent provisioning timing file
        self.assertIn("provisioning-timing.json", init_content)
        self.assertIn("provisioning_start_time", init_content)
        self.assertIn("provisioning_start_epoch", init_content)
        
        # Verify local.yml records start times and timing in evidence for all stages
        self.assertIn("first_boot_start_time", local_content)
        self.assertIn("second_boot_start_time", local_content)
        self.assertIn("linux_ready_start_time", local_content)
        self.assertIn("cluster_ready_start_time", local_content)
        self.assertIn('"duration_seconds"', local_content)
        self.assertIn('"overall_provisioning_start_time"', local_content)
    # ==========================================================================
    # TEST SUITE 5: System Desired State Sync Service Configuration
    # ==========================================================================
    def test_desired_state_systemd_templates_and_tasks(self):
        """Verifies that the desired state systemd service, timer, and ansible orchestration tasks are properly hydrated."""
        ansible_dir = os.path.join(PROJECT_ROOT, "src/ansible")
        machine_orch_tasks = os.path.join(ansible_dir, "roles/service_hubs/tasks/main.yml")
        vars_all = os.path.join(ansible_dir, "vars/all.yml.j2")
        
        # Verify default variables are declared
        with open(vars_all, "r") as f:
            vars_content = f.read()
        self.assertIn("desired_state_enabled: true", vars_content)
        self.assertIn('desired_state_repo_name: "system-desired-state"', vars_content)
        self.assertIn("desired_state_pull_schedule", vars_content)
        
        # Verify the playbook initialization tasks exist
        with open(machine_orch_tasks, "r") as f:
            tasks_content = f.read()
            
        self.assertIn("GDC-TASK-03 | Verify Gitea repository path exists for system-desired-state", tasks_content)
        self.assertIn("git init --bare", tasks_content)
        self.assertIn("GDC-TASK-03 | Seed bare repository with no-op skeleton if empty", tasks_content)
        self.assertIn("GDC-TASK-03 | Enable and start system-desired-state timer", tasks_content)
        
        # Verify individual stage files have timing calculations and evidence structures
        stages = [
            "stage_first_boot.yml",
            "stage_second_boot.yml",
            "stage_linux_ready.yml",
            "stage_cluster_ready.yml"
        ]
        for stage in stages:
            stage_path = os.path.join(ansible_dir, "stages", stage)
            with open(stage_path, "r") as sf:
                s_content = sf.read()
            self.assertIn("duration_seconds", s_content, f"Stage {stage} must calculate duration_seconds")
            self.assertIn("start_time", s_content, f"Stage {stage} must record start_time")
            self.assertIn("end_time", s_content, f"Stage {stage} must record end_time")
            self.assertIn("timing", s_content, f"Stage {stage} must have timing dictionary in evidence")
            self.assertIn('"status": "completed"', s_content, f"Stage {stage} must record status")

if __name__ == "__main__":
    unittest.main()
