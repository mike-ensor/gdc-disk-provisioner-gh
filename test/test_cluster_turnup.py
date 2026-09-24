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

"""Unit tests verifying GDC automated cluster-create and CLUSTER_TURNUP stage integration."""

import os
import subprocess
import tempfile
import unittest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CREATE_CLUSTER_SCRIPT = os.path.join(PROJECT_ROOT, "bin/cluster/create_cluster.sh")
VALID_FACTS_FILE = os.path.join(PROJECT_ROOT, "test/fixtures/valid-gdc-fact-manual.json")
LOCAL_YML_PATH = os.path.join(PROJECT_ROOT, "src/ansible/local.yml")
STAGE_TURNUP_PATH = os.path.join(PROJECT_ROOT, "src/ansible/stages/stage_cluster_turnup.yml")
ROLE_TURNUP_TASKS_PATH = os.path.join(PROJECT_ROOT, "src/ansible/roles/cluster_turnup/tasks/main.yml")
STATE_INIT_PATH = os.path.join(PROJECT_ROOT, "src/ansible/stages/state_initialization.yml")


class TestClusterTurnupScript(unittest.TestCase):
    """Verifies that create_cluster.sh accurately parses facts, ENV variables, and CLI parameters."""

    def test_manual_env_execution(self):
        result = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run"],
            capture_output=True, text=True,
            env={
                **os.environ,
                "CLUSTER_NAME": "gdc-manual-241",
                "PROJECT_ID": "anthos-bare-metal-lab-1",
                "MACHINE_IP": "192.168.9.241",
                "CLUSTER_VIP": "192.168.9.143",
                "CLUSTER_INGRESS": "192.168.9.144",
                "PRIMARY_LOAD_BALANCER": "192.168.9.144-192.168.9.150",
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Starting GDC Cluster Creation Process", result.stdout)
        self.assertIn("Cluster Name:                       gdc-manual-241", result.stdout)
        self.assertIn("Project ID:                         anthos-bare-metal-lab-1", result.stdout)
        self.assertIn("Machine IP:                         192.168.9.241", result.stdout)
        self.assertIn("[DRY-RUN]", result.stdout)

    def test_manual_missing_env_fails(self):
        # When run without facts and with missing required ENV variables, script must fail fast
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "CLUSTER_NAME": "test-cluster",
            # Missing PROJECT_ID, MACHINE_IP, CLUSTER_VIP, CLUSTER_INGRESS, PRIMARY_LOAD_BALANCER
        }
        result = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run"],
            capture_output=True, text=True,
            env=clean_env
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: Missing required cluster configuration parameter(s):", result.stderr)
        self.assertIn("MACHINE_IP", result.stderr)
        self.assertIn("CLUSTER_VIP", result.stderr)

    def test_facts_file_dynamic_sourcing(self):
        # Automated run via facts file without requiring pre-set ENV variables
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        }
        result = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", VALID_FACTS_FILE],
            capture_output=True, text=True,
            env=clean_env
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn(f"Sourcing cluster parameters from facts: {VALID_FACTS_FILE}", result.stdout)
        self.assertIn("Cluster Name:                       gdc-extreme-1", result.stdout)
        self.assertIn("Project ID:                         anthos-bare-metal-lab-1", result.stdout)
        self.assertIn("Machine IP:                         192.168.109.12", result.stdout)
        self.assertIn("Cluster VIP:                        192.168.109.2", result.stdout)
        self.assertIn("Cluster Ingress:                    192.168.109.100", result.stdout)
        self.assertIn("Primary Load Balancer:              192.168.109.100-192.168.109.150", result.stdout)
        self.assertIn("Primary Root Repo:                  https://gitlab.com/gcp-solutions-public/retail-edge/customer-demos/dp-primary-root.git", result.stdout)

    def test_env_overrides_facts_file(self):
        # Operator ENV variables take precedence over facts file
        result = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", VALID_FACTS_FILE],
            capture_output=True, text=True,
            env={
                **os.environ,
                "CLUSTER_NAME": "env-override-cluster",
                "CLUSTER_VIP": "10.0.0.99",
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Cluster Name:                       env-override-cluster", result.stdout)
        self.assertIn("Cluster VIP:                        10.0.0.99", result.stdout)
        # Non-overridden fields still source from facts file
        self.assertIn("Machine IP:                         192.168.109.12", result.stdout)
        self.assertIn("Cluster Ingress:                    192.168.109.100", result.stdout)

    def test_cli_overrides_env_and_facts_file(self):
        # CLI options take top precedence over both ENV and facts file
        result = subprocess.run(
            [
                CREATE_CLUSTER_SCRIPT, "-y", "--dry-run",
                "--facts", VALID_FACTS_FILE,
                "--name", "cli-edge-99",
                "--vip", "10.0.0.50"
            ],
            capture_output=True, text=True,
            env={
                **os.environ,
                "CLUSTER_NAME": "env-cluster",
                "CLUSTER_VIP": "10.0.0.25",
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Cluster Name:                       cli-edge-99", result.stdout)
        self.assertIn("Cluster VIP:                        10.0.0.50", result.stdout)
        # Non-overridden fields still source from facts file
        self.assertIn("Machine IP:                         192.168.109.12", result.stdout)


class TestClusterTurnupAnsibleIntegration(unittest.TestCase):
    """Verifies the Ansible playbook and stage definitions for CLUSTER_TURNUP."""

    def test_local_yml_contains_stage_6(self):
        with open(LOCAL_YML_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("STAGE 6: ClusterTurnup", content)
        self.assertIn("stages/stage_cluster_turnup.yml", content)
        self.assertIn("cluster_turnup_start_time", content)
        self.assertIn("/var/gdc-install/state/cluster-turnup.json", content)
        self.assertIn("gdc-collector --stage cluster-turnup", content)
        self.assertIn('stop_stage == "CLUSTER_READY"', content)
        self.assertIn('stop_stage == "CLUSTER_TURNUP"', content)
        self.assertIn("Error creating a cluster. Check the 'bmctl-workspace' logs for details", content)

    def test_state_initialization_includes_cluster_turnup(self):
        with open(STATE_INIT_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("cluster-turnup", content)
        self.assertIn("cluster_turnup_state", content)

    def test_stage_cluster_turnup_syntax_and_evidence(self):
        self.assertTrue(os.path.exists(STAGE_TURNUP_PATH))
        with open(STAGE_TURNUP_PATH, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        self.assertIsInstance(tasks, list)
        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        self.assertTrue(any("cluster_turnup" in name.lower() for name in task_names))
        self.assertTrue(any("duration_seconds" in name.lower() or "timing" in name.lower() for name in task_names))
        self.assertTrue(any("completion state" in name.lower() for name in task_names))

    def test_role_cluster_turnup_tasks(self):
        self.assertTrue(os.path.exists(ROLE_TURNUP_TASKS_PATH))
        with open(ROLE_TURNUP_TASKS_PATH, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        self.assertIsInstance(tasks, list)
        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        # Must execute create_cluster.sh with ADC environment variables
        self.assertTrue(any("create_cluster.sh" in name for name in task_names))
        create_task = next(t for t in tasks if isinstance(t, dict) and "Execute create_cluster.sh" in t.get("name", ""))
        self.assertIn("environment", create_task)
        self.assertEqual(create_task["environment"].get("GOOGLE_APPLICATION_CREDENTIALS"), "/etc/gdc/application_default_credentials.json")
        self.assertEqual(str(create_task["environment"].get("GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES")), "1")
        # Must verify admin kubeconfig
        self.assertTrue(any("admin.conf" in name for name in task_names))
        # Must structure evidence
        self.assertTrue(any("Evidence" in name for name in task_names))


if __name__ == "__main__":
    unittest.main()
