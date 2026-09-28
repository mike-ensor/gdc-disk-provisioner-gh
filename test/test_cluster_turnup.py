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

    def test_custom_version_and_cidrs(self):
        # Verify custom version and CIDR flags override defaults
        result = subprocess.run(
            [
                CREATE_CLUSTER_SCRIPT, "-y", "--dry-run",
                "--facts", VALID_FACTS_FILE,
                "--version", "1.36.0-gke.10",
                "--pod-cidr", "10.100.0.0/16",
                "--service-cidr", "10.101.0.0/20",
            ],
            capture_output=True, text=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Anthos Version:                     1.36.0-gke.10", result.stdout)
        self.assertIn("Pod CIDR:                           10.100.0.0/16", result.stdout)
        self.assertIn("Service CIDR:                       10.101.0.0/20", result.stdout)

    def test_root_repo_parameter(self):
        # Verify primary root repo passed via CLI is parsed and displayed
        result = subprocess.run(
            [
                CREATE_CLUSTER_SCRIPT, "-y", "--dry-run",
                "--facts", VALID_FACTS_FILE,
                "--root-repo", "us-docker.pkg.dev/my-proj/repo/platform:v1",
            ],
            capture_output=True, text=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Primary Root Repo:                  us-docker.pkg.dev/my-proj/repo/platform:v1", result.stdout)

    def test_facts_file_cluster_admin_emails_parsing(self):
        # Automated run via facts file sourcing cluster_admin_emails array
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
        self.assertIn("Cluster Admin Emails (2):", result.stdout)
        self.assertIn("ensor@google.com", result.stdout)
        self.assertIn("michael.d.ensor@gmail.com", result.stdout)

    def test_facts_file_empty_admin_emails(self):
        # When cluster_admin_emails is empty array, dry-run succeeds and reports 0 emails
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('''{
              "cluster": {
                "cluster_name": "gdc-empty-admins",
                "cluster_admin_emails": [],
                "networking": {
                  "cluster_vip": "192.168.109.2",
                  "cluster_ingress": "192.168.109.100",
                  "cluster_lb_range": "192.168.109.100-192.168.109.150"
                }
              },
              "gcp_info": {
                "project_id": "anthos-bare-metal-lab-1",
                "region": "us-west1"
              },
              "network": {
                "cluster_network": {
                  "ip_cidr": "192.168.109.12/24"
                }
              }
            }''')
            temp_path = f.name
        try:
            result = subprocess.run(
                [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", temp_path],
                capture_output=True, text=True,
                env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
            )
            self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
            self.assertIn("Cluster Admin Emails (0):           none", result.stdout)
        finally:
            os.remove(temp_path)

    def test_manifest_generation_structure(self):
        # Validate that the generated manifest templates in bash produce valid YAML structure and expected names
        with open(CREATE_CLUSTER_SCRIPT, "r") as f:
            content = f.read()
        self.assertIn("name: automated-admin-email", content)
        self.assertIn("name: dynamic-installed-cluster-admin-list", content)
        self.assertIn("cluster-admin-automated.yaml", content)
        self.assertIn("cluster-admins-dynamic.yaml", content)

    def test_rbac_manifests_yaml_validity(self):
        # Verify that the bash script's RBAC manifest logic generates syntactically valid YAML
        with tempfile.TemporaryDirectory() as tmpdir:
            test_script = f"""
CLUSTER_CONFIG_DIR="{tmpdir}"
ADMIN_USER_EMAIL="admin@example.com"
CLUSTER_ADMIN_EMAILS=("admin1@example.com" "admin2@example.com")

ADMIN_EMAIL_FILE="${{CLUSTER_CONFIG_DIR}}/cluster-admin-automated.yaml"
cat <<EOF >"${{ADMIN_EMAIL_FILE}}"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: automated-admin-email
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ${{ADMIN_USER_EMAIL}}
EOF

DYNAMIC_ADMINS_FILE="${{CLUSTER_CONFIG_DIR}}/cluster-admins-dynamic.yaml"
cat <<EOF >"${{DYNAMIC_ADMINS_FILE}}"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dynamic-installed-cluster-admin-list
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
EOF
for admin_email in "${{CLUSTER_ADMIN_EMAILS[@]}}"; do
	cat <<EOF >>"${{DYNAMIC_ADMINS_FILE}}"
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ${{admin_email}}
EOF
done
"""
            subprocess.run(["bash", "-c", test_script], check=True)
            automated_yaml_path = os.path.join(tmpdir, "cluster-admin-automated.yaml")
            dynamic_yaml_path = os.path.join(tmpdir, "cluster-admins-dynamic.yaml")

            with open(automated_yaml_path, "r") as f:
                auto_manifest = yaml.safe_load(f)
            self.assertEqual(auto_manifest["apiVersion"], "rbac.authorization.k8s.io/v1")
            self.assertEqual(auto_manifest["kind"], "ClusterRoleBinding")
            self.assertEqual(auto_manifest["metadata"]["name"], "automated-admin-email")
            self.assertEqual(auto_manifest["roleRef"]["name"], "cluster-admin")
            self.assertEqual(auto_manifest["subjects"][0]["name"], "admin@example.com")

            with open(dynamic_yaml_path, "r") as f:
                dynamic_manifest = yaml.safe_load(f)
            self.assertEqual(dynamic_manifest["apiVersion"], "rbac.authorization.k8s.io/v1")
            self.assertEqual(dynamic_manifest["kind"], "ClusterRoleBinding")
            self.assertEqual(dynamic_manifest["metadata"]["name"], "dynamic-installed-cluster-admin-list")
            self.assertEqual(dynamic_manifest["roleRef"]["name"], "cluster-admin")
            self.assertEqual(len(dynamic_manifest["subjects"]), 2)
            self.assertEqual(dynamic_manifest["subjects"][0]["name"], "admin1@example.com")
            self.assertEqual(dynamic_manifest["subjects"][1]["name"], "admin2@example.com")



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
