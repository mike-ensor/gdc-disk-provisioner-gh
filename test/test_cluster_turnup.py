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

import json
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
        self.assertIn("K8s Network IP:                     192.168.9.241", result.stdout)
        self.assertIn("[DRY-RUN]", result.stdout)

    def test_k8s_network_ip_env_execution(self):
        result = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run"],
            capture_output=True, text=True,
            env={
                **os.environ,
                "CLUSTER_NAME": "gdc-manual-241",
                "PROJECT_ID": "anthos-bare-metal-lab-1",
                "K8S_NETWORK_IP": "192.168.9.241",
                "CLUSTER_VIP": "192.168.9.143",
                "CLUSTER_INGRESS": "192.168.9.144",
                "PRIMARY_LOAD_BALANCER": "192.168.9.144-192.168.9.150",
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("K8s Network IP:                     192.168.9.241", result.stdout)

    def test_k8s_network_ip_cli_parameter(self):
        result = subprocess.run(
            [
                CREATE_CLUSTER_SCRIPT, "-y", "--dry-run",
                "--k8s-ip", "192.168.10.55",
                "--name", "gdc-k8s-ip-test",
                "--project", "test-project",
                "--vip", "192.168.10.50",
                "--ingress", "192.168.10.51",
                "--lb-range", "192.168.10.51-192.168.10.60"
            ],
            capture_output=True, text=True,
            env=os.environ
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("K8s Network IP:                     192.168.10.55", result.stdout)

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
        self.assertIn("K8s Network IP:                     192.168.109.12", result.stdout)
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
        self.assertIn("K8s Network IP:                     192.168.109.12", result.stdout)
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
        self.assertIn("K8s Network IP:                     192.168.109.12", result.stdout)

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

    def test_facts_file_with_structured_git_primary_root_repo(self):
        facts = {
            "cluster": {
                "cluster_name": "gdc-test-git-root",
                "primary_root_repo": {
                    "cluster_config_name": "custom-folder",
                    "git": {
                        "repo_url": "https://gitlab.com/test-org/primary-root.git",
                        "branch": "main",
                        "gsm_secret_name": "git-creds",
                    },
                },
                "networking": {
                    "cluster_vip": "192.168.109.2",
                    "cluster_ingress": "192.168.109.100",
                    "cluster_lb_range": "192.168.109.100-192.168.109.150",
                },
            },
            "gcp_info": {
                "project_id": "anthos-bare-metal-lab-1",
                "region": "us-west1",
            },
            "network": {
                "cluster_network": {
                    "ip_cidr": "192.168.109.12/24",
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(facts, f)
            temp_path = f.name
        try:
            result = subprocess.run(
                [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", temp_path],
                capture_output=True,
                text=True,
                env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
            )
            self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
            self.assertIn(
                "Primary Root Repo:                  https://gitlab.com/test-org/primary-root.git",
                result.stdout,
            )
        finally:
            os.remove(temp_path)

    def test_gitops_rich_summary_table_and_flags(self):
        """Verifies CLI flags for GitOps and rich summary table output in dry-run mode."""
        env = {
            **os.environ,
            "CLUSTER_NAME": "gdc-ux-test",
            "PROJECT_ID": "anthos-bare-metal-lab-1",
            "MACHINE_IP": "192.168.9.241",
            "CLUSTER_VIP": "192.168.9.143",
            "CLUSTER_INGRESS": "192.168.9.144",
            "PRIMARY_LOAD_BALANCER": "192.168.9.144-192.168.9.150",
        }

        # Case 1: Custom GitOps flags
        result = subprocess.run(
            [
                CREATE_CLUSTER_SCRIPT,
                "-y",
                "--dry-run",
                "--root-repo",
                "https://gitlab.com/test-org/repo.git",
                "--root-repo-branch",
                "develop",
                "--root-repo-secret",
                "custom-git-secret",
                "--cluster-config-name",
                "custom-folder",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Config Sync:                        true", result.stdout)
        self.assertIn(
            "Primary Root Repo:                  https://gitlab.com/test-org/repo.git",
            result.stdout,
        )
        self.assertIn("Root Repo Type:                     git", result.stdout)
        self.assertIn("Root Repo Branch:                   develop", result.stdout)
        self.assertIn("Target Sync Directory:              config/clusters/custom-folder", result.stdout)
        self.assertIn("Root Repo Authentication:           GSM Secret ('custom-git-secret')", result.stdout)

        # Case 2: ConfigSync disabled flag
        result_disabled = subprocess.run(
            [
                CREATE_CLUSTER_SCRIPT,
                "-y",
                "--dry-run",
                "--no-config-sync",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result_disabled.returncode, 0, f"Failed with: {result_disabled.stderr}")
        self.assertIn("Config Sync:                        false", result_disabled.stdout)

    def test_facts_file_with_structured_oci_primary_root_repo(self):
        facts = {
            "cluster": {
                "cluster_name": "gdc-test-oci-root",
                "primary_root_repo": {
                    "oci": {
                        "image": "us-docker.pkg.dev/test-proj/test-repo/config:v1.0.0",
                        "gsa": "sa-name",
                    },
                },
                "networking": {
                    "cluster_vip": "192.168.109.2",
                    "cluster_ingress": "192.168.109.100",
                    "cluster_lb_range": "192.168.109.100-192.168.109.150",
                },
            },
            "gcp_info": {
                "project_id": "anthos-bare-metal-lab-1",
                "region": "us-west1",
            },
            "network": {
                "cluster_network": {
                    "ip_cidr": "192.168.109.12/24",
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(facts, f)
            temp_path = f.name
        try:
            result = subprocess.run(
                [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", temp_path],
                capture_output=True,
                text=True,
                env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
            )
            self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
            self.assertIn(
                "Primary Root Repo:                  us-docker.pkg.dev/test-proj/test-repo/config:v1.0.0",
                result.stdout,
            )
        finally:
            os.remove(temp_path)

    def test_facts_file_with_omitted_or_null_primary_root_repo(self):
        # Case A: primary_root_repo is null
        facts_null = {
            "cluster": {
                "cluster_name": "gdc-test-null-root",
                "primary_root_repo": None,
                "networking": {
                    "cluster_vip": "192.168.109.2",
                    "cluster_ingress": "192.168.109.100",
                    "cluster_lb_range": "192.168.109.100-192.168.109.150",
                },
            },
            "gcp_info": {
                "project_id": "anthos-bare-metal-lab-1",
                "region": "us-west1",
            },
            "network": {
                "cluster_network": {
                    "ip_cidr": "192.168.109.12/24",
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(facts_null, f)
            temp_path = f.name
        try:
            result = subprocess.run(
                [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", temp_path],
                capture_output=True,
                text=True,
                env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
            )
            self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
            self.assertIn(
                "Primary Root Repo:                  none",
                result.stdout,
            )
        finally:
            os.remove(temp_path)

        # Case B: primary_root_repo is omitted
        facts_omitted = {
            "cluster": {
                "cluster_name": "gdc-test-omitted-root",
                "networking": {
                    "cluster_vip": "192.168.109.2",
                    "cluster_ingress": "192.168.109.100",
                    "cluster_lb_range": "192.168.109.100-192.168.109.150",
                },
            },
            "gcp_info": {
                "project_id": "anthos-bare-metal-lab-1",
                "region": "us-west1",
            },
            "network": {
                "cluster_network": {
                    "ip_cidr": "192.168.109.12/24",
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(facts_omitted, f)
            temp_path = f.name
        try:
            result = subprocess.run(
                [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", temp_path],
                capture_output=True,
                text=True,
                env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
            )
            self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
            self.assertIn(
                "Primary Root Repo:                  none",
                result.stdout,
            )
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

    def test_rootsync_manifests_yaml_validity(self):
        """Verify that create_cluster.sh's RootSync manifest generation produces valid YAML for Git and OCI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Test Git RootSync generation (with token auth)
            git_script = f"""
CLUSTER_CONFIG_DIR="{tmpdir}"
PRIMARY_ROOT_REPO="https://gitlab.com/test-org/primary-root.git"
ROOT_REPO_TYPE="git"
ROOT_REPO_BRANCH="release-1.0"
ROOT_SYNC_DIR="config/clusters/edge-1"
ROOT_REPO_SECRET="git-creds"
ROOTSYNC_FILE="${{CLUSTER_CONFIG_DIR}}/rootsync-git.yaml"

ROOT_GIT_AUTH="none"
if [[ -n "${{ROOT_REPO_SECRET:-}}" ]]; then
    if [[ "${{PRIMARY_ROOT_REPO}}" == git@* || "${{PRIMARY_ROOT_REPO}}" == ssh://* ]]; then
        ROOT_GIT_AUTH="ssh"
    else
        ROOT_GIT_AUTH="token"
    fi
fi

cat <<EOF >"${{ROOTSYNC_FILE}}"
apiVersion: configsync.gke.io/v1beta1
kind: RootSync
metadata:
  name: root-sync
  namespace: config-management-system
spec:
  sourceFormat: unstructured
  sourceType: git
  git:
    repo: ${{PRIMARY_ROOT_REPO}}
    branch: ${{ROOT_REPO_BRANCH:-main}}
    dir: ${{ROOT_SYNC_DIR:-.}}
    auth: ${{ROOT_GIT_AUTH}}
EOF
if [[ -n "${{ROOT_REPO_SECRET:-}}" ]]; then
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    secretRef:
      name: ${{ROOT_REPO_SECRET}}
EOF
fi
"""
            subprocess.run(["bash", "-c", git_script], check=True)
            git_yaml_path = os.path.join(tmpdir, "rootsync-git.yaml")
            with open(git_yaml_path, "r") as f:
                git_data = yaml.safe_load(f)

            self.assertEqual(git_data["apiVersion"], "configsync.gke.io/v1beta1")
            self.assertEqual(git_data["kind"], "RootSync")
            self.assertEqual(git_data["metadata"]["name"], "root-sync")
            self.assertEqual(git_data["metadata"]["namespace"], "config-management-system")
            self.assertEqual(git_data["spec"]["sourceFormat"], "unstructured")
            self.assertEqual(git_data["spec"]["sourceType"], "git")
            self.assertEqual(git_data["spec"]["git"]["repo"], "https://gitlab.com/test-org/primary-root.git")
            self.assertEqual(git_data["spec"]["git"]["branch"], "release-1.0")
            self.assertEqual(git_data["spec"]["git"]["dir"], "config/clusters/edge-1")
            self.assertEqual(git_data["spec"]["git"]["auth"], "token")
            self.assertEqual(git_data["spec"]["git"]["secretRef"]["name"], "git-creds")

            # 2. Test Git RootSync generation with SSH auth
            git_ssh_script = f"""
CLUSTER_CONFIG_DIR="{tmpdir}"
PRIMARY_ROOT_REPO="ssh://git@github.com/my-org/repo.git"
ROOT_REPO_TYPE="git"
ROOT_REPO_BRANCH="main"
ROOT_SYNC_DIR="config/clusters/edge-2"
ROOT_REPO_SECRET="ssh-key-secret"
ROOTSYNC_FILE="${{CLUSTER_CONFIG_DIR}}/rootsync-git-ssh.yaml"

ROOT_GIT_AUTH="none"
if [[ -n "${{ROOT_REPO_SECRET:-}}" ]]; then
    if [[ "${{PRIMARY_ROOT_REPO}}" == git@* || "${{PRIMARY_ROOT_REPO}}" == ssh://* ]]; then
        ROOT_GIT_AUTH="ssh"
    else
        ROOT_GIT_AUTH="token"
    fi
fi

cat <<EOF >"${{ROOTSYNC_FILE}}"
apiVersion: configsync.gke.io/v1beta1
kind: RootSync
metadata:
  name: root-sync
  namespace: config-management-system
spec:
  sourceFormat: unstructured
  sourceType: git
  git:
    repo: ${{PRIMARY_ROOT_REPO}}
    branch: ${{ROOT_REPO_BRANCH:-main}}
    dir: ${{ROOT_SYNC_DIR:-.}}
    auth: ${{ROOT_GIT_AUTH}}
EOF
if [[ -n "${{ROOT_REPO_SECRET:-}}" ]]; then
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    secretRef:
      name: ${{ROOT_REPO_SECRET}}
EOF
fi
"""
            subprocess.run(["bash", "-c", git_ssh_script], check=True)
            git_ssh_yaml_path = os.path.join(tmpdir, "rootsync-git-ssh.yaml")
            with open(git_ssh_yaml_path, "r") as f:
                git_ssh_data = yaml.safe_load(f)

            self.assertEqual(git_ssh_data["spec"]["sourceType"], "git")
            self.assertEqual(git_ssh_data["spec"]["git"]["repo"], "ssh://git@github.com/my-org/repo.git")
            self.assertEqual(git_ssh_data["spec"]["git"]["branch"], "main")
            self.assertEqual(git_ssh_data["spec"]["git"]["dir"], "config/clusters/edge-2")
            self.assertEqual(git_ssh_data["spec"]["git"]["auth"], "ssh")
            self.assertEqual(git_ssh_data["spec"]["git"]["secretRef"]["name"], "ssh-key-secret")

            # 3. Test OCI RootSync generation with GSA (Workload Identity)
            oci_gsa_script = f"""
CLUSTER_CONFIG_DIR="{tmpdir}"
PRIMARY_ROOT_REPO="us-docker.pkg.dev/my-proj/repo/config:v1"
ROOT_REPO_TYPE="oci"
ROOT_SYNC_DIR="config/clusters/edge-oci"
ROOT_REPO_GSA="sa-configsync"
ROOT_REPO_SECRET=""
PROJECT_ID="my-proj"
ROOTSYNC_FILE="${{CLUSTER_CONFIG_DIR}}/rootsync-oci-gsa.yaml"

cat <<EOF >"${{ROOTSYNC_FILE}}"
apiVersion: configsync.gke.io/v1beta1
kind: RootSync
metadata:
  name: root-sync
  namespace: config-management-system
spec:
  sourceFormat: unstructured
  sourceType: oci
  oci:
    image: ${{PRIMARY_ROOT_REPO}}
    dir: ${{ROOT_SYNC_DIR:-.}}
EOF
if [[ -n "${{ROOT_REPO_GSA:-}}" ]]; then
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    auth: gcpserviceaccount
    gcpServiceAccountEmail: ${{ROOT_REPO_GSA}}@${{PROJECT_ID}}.iam.gserviceaccount.com
EOF
elif [[ -n "${{ROOT_REPO_SECRET:-}}" ]]; then
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    auth: token
    secretRef:
      name: ${{ROOT_REPO_SECRET}}
EOF
else
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    auth: none
EOF
fi
"""
            subprocess.run(["bash", "-c", oci_gsa_script], check=True)
            oci_gsa_yaml_path = os.path.join(tmpdir, "rootsync-oci-gsa.yaml")
            with open(oci_gsa_yaml_path, "r") as f:
                oci_gsa_data = yaml.safe_load(f)

            self.assertEqual(oci_gsa_data["apiVersion"], "configsync.gke.io/v1beta1")
            self.assertEqual(oci_gsa_data["kind"], "RootSync")
            self.assertEqual(oci_gsa_data["metadata"]["name"], "root-sync")
            self.assertEqual(oci_gsa_data["metadata"]["namespace"], "config-management-system")
            self.assertEqual(oci_gsa_data["spec"]["sourceFormat"], "unstructured")
            self.assertEqual(oci_gsa_data["spec"]["sourceType"], "oci")
            self.assertEqual(oci_gsa_data["spec"]["oci"]["image"], "us-docker.pkg.dev/my-proj/repo/config:v1")
            self.assertEqual(oci_gsa_data["spec"]["oci"]["dir"], "config/clusters/edge-oci")
            self.assertEqual(oci_gsa_data["spec"]["oci"]["auth"], "gcpserviceaccount")
            self.assertEqual(
                oci_gsa_data["spec"]["oci"]["gcpServiceAccountEmail"],
                "sa-configsync@my-proj.iam.gserviceaccount.com",
            )

            # 4. Test OCI RootSync fallback (no GSA, no secret -> auth: none)
            oci_none_script = f"""
CLUSTER_CONFIG_DIR="{tmpdir}"
PRIMARY_ROOT_REPO="docker.io/my-org/my-config:v2"
ROOT_REPO_TYPE="oci"
ROOT_SYNC_DIR="config/clusters/edge-public"
ROOT_REPO_GSA=""
ROOT_REPO_SECRET=""
PROJECT_ID="my-proj"
ROOTSYNC_FILE="${{CLUSTER_CONFIG_DIR}}/rootsync-oci-none.yaml"

cat <<EOF >"${{ROOTSYNC_FILE}}"
apiVersion: configsync.gke.io/v1beta1
kind: RootSync
metadata:
  name: root-sync
  namespace: config-management-system
spec:
  sourceFormat: unstructured
  sourceType: oci
  oci:
    image: ${{PRIMARY_ROOT_REPO}}
    dir: ${{ROOT_SYNC_DIR:-.}}
EOF
if [[ -n "${{ROOT_REPO_GSA:-}}" ]]; then
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    auth: gcpserviceaccount
    gcpServiceAccountEmail: ${{ROOT_REPO_GSA}}@${{PROJECT_ID}}.iam.gserviceaccount.com
EOF
elif [[ -n "${{ROOT_REPO_SECRET:-}}" ]]; then
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    auth: token
    secretRef:
      name: ${{ROOT_REPO_SECRET}}
EOF
else
    cat <<EOF >>"${{ROOTSYNC_FILE}}"
    auth: none
EOF
fi
"""
            subprocess.run(["bash", "-c", oci_none_script], check=True)
            oci_none_yaml_path = os.path.join(tmpdir, "rootsync-oci-none.yaml")
            with open(oci_none_yaml_path, "r") as f:
                oci_none_data = yaml.safe_load(f)

            self.assertEqual(oci_none_data["spec"]["sourceType"], "oci")
            self.assertEqual(oci_none_data["spec"]["oci"]["image"], "docker.io/my-org/my-config:v2")
            self.assertEqual(oci_none_data["spec"]["oci"]["dir"], "config/clusters/edge-public")
            self.assertEqual(oci_none_data["spec"]["oci"]["auth"], "none")
            self.assertNotIn("secretRef", oci_none_data["spec"]["oci"])
            self.assertNotIn("gcpServiceAccountEmail", oci_none_data["spec"]["oci"])

    def test_root_repo_precedence_override(self):
        """Verify CLI and ENV overrides properly reset root repo type, secret, gsa, and branch."""
        # 1. Fact has Git with custom secret and branch, CLI overrides with OCI repo
        eval_script_cli = """
CLI_PRIMARY_ROOT_REPO="us-docker.pkg.dev/my-proj/repo/platform:v1"
ENV_PRIMARY_ROOT_REPO=""
FACT_PRIMARY_ROOT_REPO="https://gitlab.com/test-org/repo.git"
FACT_ROOT_REPO_TYPE="git"
FACT_ROOT_REPO_BRANCH="release-candidate"
FACT_ROOT_REPO_SECRET="old-git-secret"
FACT_ROOT_REPO_GSA=""

PRIMARY_ROOT_REPO="${CLI_PRIMARY_ROOT_REPO:-${ENV_PRIMARY_ROOT_REPO:-${FACT_PRIMARY_ROOT_REPO:-}}}"
if [[ -n "${CLI_PRIMARY_ROOT_REPO}" || -n "${ENV_PRIMARY_ROOT_REPO}" ]]; then
    ROOT_REPO_TYPE=""
    ROOT_REPO_SECRET=""
    ROOT_REPO_GSA=""
    ROOT_REPO_BRANCH="main"
    if [[ -n "${PRIMARY_ROOT_REPO}" && "${PRIMARY_ROOT_REPO}" != "none" ]]; then
        if [[ "${PRIMARY_ROOT_REPO}" == *.git || "${PRIMARY_ROOT_REPO}" == http* || "${PRIMARY_ROOT_REPO}" == git@* || "${PRIMARY_ROOT_REPO}" == ssh://* ]]; then
            ROOT_REPO_TYPE="git"
        else
            ROOT_REPO_TYPE="oci"
        fi
    fi
else
    ROOT_REPO_TYPE="${FACT_ROOT_REPO_TYPE:-}"
    ROOT_REPO_BRANCH="${FACT_ROOT_REPO_BRANCH:-main}"
    ROOT_REPO_SECRET="${FACT_ROOT_REPO_SECRET:-}"
    ROOT_REPO_GSA="${FACT_ROOT_REPO_GSA:-}"
fi
echo "TYPE=$ROOT_REPO_TYPE;BRANCH=$ROOT_REPO_BRANCH;SECRET=$ROOT_REPO_SECRET;GSA=$ROOT_REPO_GSA"
"""
        res_cli = subprocess.run(["bash", "-c", eval_script_cli], capture_output=True, text=True, check=True)
        self.assertIn("TYPE=oci;BRANCH=main;SECRET=;GSA=", res_cli.stdout.strip())

        # 2. Fact has OCI, ENV overrides with Git SSH URL
        eval_script_env = """
CLI_PRIMARY_ROOT_REPO=""
ENV_PRIMARY_ROOT_REPO="ssh://git@github.com/my-org/repo.git"
FACT_PRIMARY_ROOT_REPO="us-docker.pkg.dev/my-proj/repo/platform:v1"
FACT_ROOT_REPO_TYPE="oci"
FACT_ROOT_REPO_BRANCH="main"
FACT_ROOT_REPO_SECRET=""
FACT_ROOT_REPO_GSA="sa-companion"

PRIMARY_ROOT_REPO="${CLI_PRIMARY_ROOT_REPO:-${ENV_PRIMARY_ROOT_REPO:-${FACT_PRIMARY_ROOT_REPO:-}}}"
if [[ -n "${CLI_PRIMARY_ROOT_REPO}" || -n "${ENV_PRIMARY_ROOT_REPO}" ]]; then
    ROOT_REPO_TYPE=""
    ROOT_REPO_SECRET=""
    ROOT_REPO_GSA=""
    ROOT_REPO_BRANCH="main"
    if [[ -n "${PRIMARY_ROOT_REPO}" && "${PRIMARY_ROOT_REPO}" != "none" ]]; then
        if [[ "${PRIMARY_ROOT_REPO}" == *.git || "${PRIMARY_ROOT_REPO}" == http* || "${PRIMARY_ROOT_REPO}" == git@* || "${PRIMARY_ROOT_REPO}" == ssh://* ]]; then
            ROOT_REPO_TYPE="git"
        else
            ROOT_REPO_TYPE="oci"
        fi
    fi
else
    ROOT_REPO_TYPE="${FACT_ROOT_REPO_TYPE:-}"
    ROOT_REPO_BRANCH="${FACT_ROOT_REPO_BRANCH:-main}"
    ROOT_REPO_SECRET="${FACT_ROOT_REPO_SECRET:-}"
    ROOT_REPO_GSA="${FACT_ROOT_REPO_GSA:-}"
fi
echo "TYPE=$ROOT_REPO_TYPE;BRANCH=$ROOT_REPO_BRANCH;SECRET=$ROOT_REPO_SECRET;GSA=$ROOT_REPO_GSA"
"""
        res_env = subprocess.run(["bash", "-c", eval_script_env], capture_output=True, text=True, check=True)
        self.assertIn("TYPE=git;BRANCH=main;SECRET=;GSA=", res_env.stdout.strip())

    def test_cluster_dns_default_enabled(self):
        """Verify that ClusterDNS defaults to true when omitted."""
        result = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run"],
            capture_output=True, text=True,
            env={
                **os.environ,
                "CLUSTER_NAME": "dns-default-test",
                "PROJECT_ID": "anthos-lab",
                "K8S_NETWORK_IP": "192.168.1.10",
                "CLUSTER_VIP": "192.168.1.11",
                "CLUSTER_INGRESS": "192.168.1.12",
                "PRIMARY_LOAD_BALANCER": "192.168.1.13-192.168.1.20",
            }
        )
        self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
        self.assertIn("Configure ClusterDNS:               true", result.stdout)

    def test_cluster_dns_cli_flags(self):
        """Verify --no-cluster-dns and --cluster-dns CLI flags."""
        base_env = {
            **os.environ,
            "CLUSTER_NAME": "dns-flag-test",
            "PROJECT_ID": "anthos-lab",
            "K8S_NETWORK_IP": "192.168.1.10",
            "CLUSTER_VIP": "192.168.1.11",
            "CLUSTER_INGRESS": "192.168.1.12",
            "PRIMARY_LOAD_BALANCER": "192.168.1.13-192.168.1.20",
        }
        # Disable via flag
        res_disabled = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--no-cluster-dns"],
            capture_output=True, text=True,
            env=base_env
        )
        self.assertEqual(res_disabled.returncode, 0, f"Failed with: {res_disabled.stderr}")
        self.assertIn("Configure ClusterDNS:               false", res_disabled.stdout)

        # Enable via flag
        res_enabled = subprocess.run(
            [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--cluster-dns"],
            capture_output=True, text=True,
            env=base_env
        )
        self.assertEqual(res_enabled.returncode, 0, f"Failed with: {res_enabled.stderr}")
        self.assertIn("Configure ClusterDNS:               true", res_enabled.stdout)

    def test_cluster_dns_facts_disabled(self):
        """Verify that explicit configure_cluster_dns: false in facts disables ClusterDNS."""
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({
                "cluster": {
                    "cluster_name": "dns-fact-test",
                    "networking": {
                        "cluster_vip": "192.168.1.11",
                        "cluster_ingress": "192.168.1.12",
                        "cluster_lb_range": "192.168.1.13-192.168.1.20",
                        "configure_cluster_dns": False
                    }
                },
                "network": {
                    "cluster_network": {
                        "ip_cidr": "192.168.1.10/24"
                    }
                },
                "gcp_info": {
                    "project_id": "anthos-lab",
                    "region": "us-west1"
                }
            }, f)
            f.flush()

            result = subprocess.run(
                [CREATE_CLUSTER_SCRIPT, "-y", "--dry-run", "--facts", f.name],
                capture_output=True, text=True,
                env=os.environ
            )
            self.assertEqual(result.returncode, 0, f"Failed with: {result.stderr}")
            self.assertIn("Configure ClusterDNS:               false", result.stdout)

    def test_cluster_dns_manifest_scoped(self):
        """Verify that ClusterDNS manifest is scoped to gdc.local and internal.gdc.local without upstreamNameservers."""
        with open(CREATE_CLUSTER_SCRIPT, "r", encoding="utf-8") as f:
            content = f.read()

        # The ClusterDNS block should exist and not include upstreamNameservers
        self.assertIn("kind: ClusterDNS", content)
        self.assertIn("name: gdc.local", content)
        self.assertIn("name: internal.gdc.local", content)
        self.assertNotIn("upstreamNameservers", content)



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

    def test_role_cluster_turnup_idempotency_guards(self):
        """Verify role tasks implement local cluster health and Fleet Hub association guards."""
        with open(ROLE_TURNUP_TASKS_PATH, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        # Local cluster probe and fleet query tasks
        self.assertTrue(any("Probe local cluster responsiveness" in name for name in task_names))
        self.assertTrue(any("Query Fleet Hub for existing cluster membership" in name for name in task_names))
        self.assertTrue(any("Set cluster presence and fleet association facts" in name for name in task_names))
        
        # Orphan guard assert
        orphan_guard = next(t for t in tasks if isinstance(t, dict) and "Fail fast if Fleet Hub shows cluster membership" in t.get("name", ""))
        self.assertIsNotNone(orphan_guard)
        that_expr = orphan_guard["ansible.builtin.assert"]["that"][0]
        self.assertIn("fleet_membership_associated", that_expr)
        self.assertIn("local_cluster_healthy", that_expr)

        # Conditional create_cluster.sh execution
        create_task = next(t for t in tasks if isinstance(t, dict) and "Execute create_cluster.sh" in t.get("name", ""))
        self.assertEqual(create_task.get("when"), "not (local_cluster_healthy | bool)")

    def test_create_cluster_sh_idempotency_guards(self):
        """Verify create_cluster.sh contains idempotency checks and orphan membership protection."""
        with open(CREATE_CLUSTER_SCRIPT, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('LOCAL_CLUSTER_HEALTHY="false"', content)
        self.assertIn('FLEET_ASSOCIATED="false"', content)
        self.assertIn('already installed locally and registered in Fleet Hub. Skipping creation', content)
        self.assertIn('Aborting cluster turnup to prevent GKE Hub resource collision and corrupt state', content)

    def test_create_cluster_sh_contains_gmp_enablement(self):
        """Verify that create_cluster.sh contains the step to enable GMP for applications in Stackdriver."""
        with open(CREATE_CLUSTER_SCRIPT, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("enableGMPForApplications", content)
        self.assertIn("kubectl patch stackdriver stackdriver -n kube-system", content)
        self.assertIn("'{\"spec\":{\"enableGMPForApplications\":true}}'", content)


if __name__ == "__main__":
    unittest.main()
