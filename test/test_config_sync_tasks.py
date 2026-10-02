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

"""Unit tests for Post-Cluster ConfigSync and RootSync tasks and manifest generation."""
# pylint: disable=too-many-lines,too-many-public-methods,line-too-long,missing-function-docstring,import-outside-toplevel,too-many-locals,too-many-return-statements,unused-argument

import os
import sys
import unittest
import jinja2
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOOKUP_PLUGIN_DIR = os.path.join(PROJECT_ROOT, "src", "ansible", "lookup_plugins")
if LOOKUP_PLUGIN_DIR not in sys.path:
    sys.path.insert(0, LOOKUP_PLUGIN_DIR)

from gdc_config_sync_resolver import (  # pylint: disable=wrong-import-position,import-error # type: ignore[import-not-found]
    resolve_primary_root_repo,
    resolve_secret_payload,
)

CONFIG_SYNC_TASKS_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "roles", "post_cluster", "tasks", "config_sync.yml"
)
MAIN_TASKS_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "roles", "post_cluster", "tasks", "main.yml"
)


def compute_cluster_config_dir(
    cluster_name: str, cluster_config_name: str | None = None
) -> str:
    """Computes the target sync directory path under config/clusters/."""
    if cluster_config_name and str(cluster_config_name).strip():
        target = str(cluster_config_name).strip()
    else:
        target = cluster_name
    return f"config/clusters/{target}"


def generate_rootsync_manifest(
    cluster_name: str,
    primary_root_repo: dict | str | None,
    gcp_project_id: str = "test-project",
    target_git_auth: str | None = None,
) -> dict | None:
    """Generates a Kubernetes RootSync v1beta1 resource definition from machine_config."""
    if not primary_root_repo:
        return None

    if isinstance(primary_root_repo, str):
        # Legacy string format treated as OCI image or git repo
        computed_dir = compute_cluster_config_dir(cluster_name)
        if primary_root_repo.endswith(".git") or primary_root_repo.startswith("http"):
            return {
                "apiVersion": "configsync.gke.io/v1beta1",
                "kind": "RootSync",
                "metadata": {
                    "name": "root-sync",
                    "namespace": "config-management-system",
                },
                "spec": {
                    "sourceFormat": "unstructured",
                    "sourceType": "git",
                    "git": {
                        "repo": primary_root_repo,
                        "branch": "main",
                        "dir": computed_dir,
                        "auth": "none",
                    },
                },
            }
        return {
            "apiVersion": "configsync.gke.io/v1beta1",
            "kind": "RootSync",
            "metadata": {
                "name": "root-sync",
                "namespace": "config-management-system",
            },
            "spec": {
                "sourceFormat": "unstructured",
                "sourceType": "oci",
                "oci": {
                    "image": primary_root_repo,
                    "dir": computed_dir,
                    "auth": "none",
                },
            },
        }

    if not isinstance(primary_root_repo, dict):
        return None

    cluster_config_name = primary_root_repo.get("cluster_config_name")
    computed_dir = compute_cluster_config_dir(cluster_name, cluster_config_name)

    # Git supersedes OCI if both are provided
    if "git" in primary_root_repo and isinstance(primary_root_repo["git"], dict):
        git_spec = primary_root_repo["git"]
        gsm_secret_name = git_spec.get("gsm_secret_name")
        has_secret = bool(gsm_secret_name and str(gsm_secret_name).strip())
        if has_secret:
            auth = target_git_auth if target_git_auth else git_spec.get("auth", "token")
        else:
            auth = "none"
        branch_raw = git_spec.get("branch")
        branch = (
            str(branch_raw).strip()
            if (branch_raw and str(branch_raw).strip())
            else "main"
        )
        spec_git = {
            "repo": git_spec.get("repo_url", ""),
            "branch": branch,
            "dir": computed_dir,
            "auth": auth,
        }
        if has_secret:
            spec_git["secretRef"] = {"name": str(gsm_secret_name).strip()}

        return {
            "apiVersion": "configsync.gke.io/v1beta1",
            "kind": "RootSync",
            "metadata": {
                "name": "root-sync",
                "namespace": "config-management-system",
            },
            "spec": {
                "sourceFormat": "unstructured",
                "sourceType": "git",
                "git": spec_git,
            },
        }

    if "oci" in primary_root_repo and isinstance(primary_root_repo["oci"], dict):
        oci_spec = primary_root_repo["oci"]
        gsa = oci_spec.get("gsa")
        has_gsa = bool(gsa and str(gsa).strip())
        gsm_secret_name = oci_spec.get("gsm_secret_name")
        has_secret = bool(gsm_secret_name and str(gsm_secret_name).strip())

        spec_oci = {
            "image": oci_spec.get("image", ""),
            "dir": computed_dir,
        }

        if has_gsa:
            spec_oci["auth"] = "gcpserviceaccount"
            spec_oci["gcpServiceAccountEmail"] = (
                f"{str(gsa).strip()}@{gcp_project_id}.iam.gserviceaccount.com"
            )
        elif has_secret:
            spec_oci["auth"] = "token"
            spec_oci["secretRef"] = {"name": str(gsm_secret_name).strip()}
        else:
            spec_oci["auth"] = "none"

        return {
            "apiVersion": "configsync.gke.io/v1beta1",
            "kind": "RootSync",
            "metadata": {
                "name": "root-sync",
                "namespace": "config-management-system",
            },
            "spec": {
                "sourceFormat": "unstructured",
                "sourceType": "oci",
                "oci": spec_oci,
            },
        }

    return None


def compute_secret_data_dict(repo_type: str, payload: dict) -> tuple[dict, str]:
    """Computes secret_data_dict and target_git_auth from GSM secret payload."""
    secret_data_dict = {}
    target_git_auth = "token"
    if repo_type == "git":
        ssh_key = payload.get("ssh-privatekey")
        if ssh_key and str(ssh_key).strip():
            secret_data_dict = {"ssh-privatekey": str(ssh_key)}
            target_git_auth = "ssh"
        elif ("token" in payload and str(payload["token"]).strip()) or (
            "password" in payload and str(payload["password"]).strip()
        ):
            token_val = payload.get("token") or payload.get("password") or ""
            secret_data_dict["token"] = str(token_val)
            username_val = payload.get("username")
            if username_val and str(username_val).strip():
                secret_data_dict["username"] = str(username_val)
            target_git_auth = "token"
    elif repo_type == "oci":
        secret_data_dict = {
            "username": str(payload.get("username", "")),
            "password": str(payload.get("password", "")),
        }
    return secret_data_dict, target_git_auth


def generate_secret_manifest(
    secret_name: str,
    secret_data_dict: dict,
    namespace: str = "config-management-system",
) -> dict:
    """Generates the Kubernetes Secret manifest matching the apply stdin template."""
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": secret_name,
            "namespace": namespace,
        },
        "type": "Opaque",
        "stringData": secret_data_dict,
    }


def generate_secret_stdin_yaml(
    secret_name: str,
    secret_data_dict: dict,
    namespace: str = "config-management-system",
) -> str:
    """Generates the YAML string passed to kubectl apply -f - via stdin."""
    manifest = generate_secret_manifest(secret_name, secret_data_dict, namespace)
    return yaml.dump(manifest, default_flow_style=False)


def build_secret_injection_command(
    secret_name: str,
    repo_type: str,
    payload: dict,
    kubeconfig: str = "/etc/kubernetes/admin.conf",
) -> str:
    """Builds the kubectl apply command line for secret injection via stdin."""
    return f"kubectl --kubeconfig={kubeconfig} apply -f -"


class TestConfigSyncDirectoryComputation(unittest.TestCase):
    """Verifies directory path computation under config/clusters/."""

    def test_default_cluster_name_dir(self):
        """Defaults to config/clusters/<cluster_name> when cluster_config_name is absent or empty."""
        self.assertEqual(
            compute_cluster_config_dir("cluster-a"), "config/clusters/cluster-a"
        )
        self.assertEqual(
            compute_cluster_config_dir("cluster-a", ""), "config/clusters/cluster-a"
        )
        self.assertEqual(
            compute_cluster_config_dir("cluster-a", "   "), "config/clusters/cluster-a"
        )
        self.assertEqual(
            compute_cluster_config_dir("cluster-a", None), "config/clusters/cluster-a"
        )

    def test_overridden_cluster_config_name_dir(self):
        """Uses config/clusters/<cluster_config_name> when provided."""
        self.assertEqual(
            compute_cluster_config_dir("cluster-a", "shared-edge-prod"),
            "config/clusters/shared-edge-prod",
        )


class TestGitRootSyncGeneration(unittest.TestCase):
    """Verifies RootSync v1beta1 resource generation for Git repositories."""

    def test_git_rootsync_without_secret(self):
        """Public git repo produces auth: none and no secretRef."""
        cfg = {
            "git": {
                "repo_url": "https://gitlab.com/org/repo.git",
                "branch": "main",
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["apiVersion"], "configsync.gke.io/v1beta1")
        self.assertEqual(res["kind"], "RootSync")
        self.assertEqual(res["metadata"]["name"], "root-sync")
        self.assertEqual(res["metadata"]["namespace"], "config-management-system")
        spec = res["spec"]
        self.assertEqual(spec["sourceFormat"], "unstructured")
        self.assertEqual(spec["sourceType"], "git")
        self.assertEqual(spec["git"]["repo"], "https://gitlab.com/org/repo.git")
        self.assertEqual(spec["git"]["branch"], "main")
        self.assertEqual(spec["git"]["dir"], "config/clusters/edge-01")
        self.assertEqual(spec["git"]["auth"], "none")
        self.assertNotIn("secretRef", spec["git"])

    def test_git_rootsync_with_secret(self):
        """Git repo with gsm_secret_name produces auth: token and secretRef."""
        cfg = {
            "cluster_config_name": "edge-cluster-template",
            "git": {
                "repo_url": "https://gitlab.com/org/repo.git",
                "branch": "v2.1",
                "gsm_secret_name": "git-deploy-token",
            },
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        spec = res["spec"]
        self.assertEqual(spec["git"]["dir"], "config/clusters/edge-cluster-template")
        self.assertEqual(spec["git"]["auth"], "token")
        self.assertEqual(spec["git"]["secretRef"]["name"], "git-deploy-token")

    def test_git_rootsync_with_ssh_secret(self):
        """Git repo with gsm_secret_name and target_git_auth='ssh' produces auth: ssh."""
        cfg = {
            "cluster_config_name": "edge-cluster-template",
            "git": {
                "repo_url": "git@github.com:org/repo.git",
                "branch": "v2.1",
                "gsm_secret_name": "git-deploy-ssh",
            },
        }
        res = generate_rootsync_manifest("edge-01", cfg, target_git_auth="ssh")
        self.assertIsNotNone(res)
        assert res is not None
        spec = res["spec"]
        self.assertEqual(spec["git"]["dir"], "config/clusters/edge-cluster-template")
        self.assertEqual(spec["git"]["auth"], "ssh")
        self.assertEqual(spec["git"]["secretRef"]["name"], "git-deploy-ssh")

    def test_git_rootsync_default_branch(self):
        """Git repo without branch defaults to main."""
        cfg = {
            "git": {
                "repo_url": "https://gitlab.com/org/repo.git",
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["spec"]["git"]["branch"], "main")

    def test_git_rootsync_null_branch_defaults_to_main(self):
        """Git repo with explicit null branch defaults to main."""
        cfg = {
            "git": {
                "repo_url": "https://gitlab.com/org/repo.git",
                "branch": None,
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["spec"]["git"]["branch"], "main")

    def test_git_rootsync_null_secret_uses_auth_none(self):
        """Git repo with explicit null gsm_secret_name produces auth: none."""
        cfg = {
            "git": {
                "repo_url": "https://gitlab.com/org/repo.git",
                "gsm_secret_name": None,
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["spec"]["git"]["auth"], "none")
        self.assertNotIn("secretRef", res["spec"]["git"])


class TestOciRootSyncGeneration(unittest.TestCase):
    """Verifies RootSync v1beta1 resource generation for OCI repositories."""

    def test_oci_rootsync_with_gsa_workload_identity(self):
        """OCI with GSA uses auth: gcpserviceaccount and gcpServiceAccountEmail."""
        cfg = {
            "oci": {
                "image": "us-docker.pkg.dev/proj-123/repo/config:v1",
                "gsa": "sa-configsync",
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg, gcp_project_id="proj-123")
        self.assertIsNotNone(res)
        assert res is not None
        spec = res["spec"]
        self.assertEqual(spec["sourceFormat"], "unstructured")
        self.assertEqual(spec["sourceType"], "oci")
        self.assertEqual(
            spec["oci"]["image"], "us-docker.pkg.dev/proj-123/repo/config:v1"
        )
        self.assertEqual(spec["oci"]["dir"], "config/clusters/edge-01")
        self.assertEqual(spec["oci"]["auth"], "gcpserviceaccount")
        self.assertEqual(
            spec["oci"]["gcpServiceAccountEmail"],
            "sa-configsync@proj-123.iam.gserviceaccount.com",
        )
        self.assertNotIn("secretRef", spec["oci"])

    def test_oci_rootsync_gsa_takes_precedence_over_secret(self):
        """When OCI has both GSA and gsm_secret_name, GSA takes precedence and secretRef is omitted."""
        cfg = {
            "oci": {
                "image": "us-docker.pkg.dev/proj-123/repo/config:v1",
                "gsa": "sa-configsync",
                "gsm_secret_name": "unused-secret",
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg, gcp_project_id="proj-123")
        self.assertIsNotNone(res)
        assert res is not None
        spec = res["spec"]
        self.assertEqual(spec["oci"]["auth"], "gcpserviceaccount")
        self.assertEqual(
            spec["oci"]["gcpServiceAccountEmail"],
            "sa-configsync@proj-123.iam.gserviceaccount.com",
        )
        self.assertNotIn("secretRef", spec["oci"])

    def test_oci_rootsync_null_credentials(self):
        """OCI with explicit null gsa and gsm_secret_name uses auth: none."""
        cfg = {
            "oci": {
                "image": "us-docker.pkg.dev/proj-123/repo/config:v1",
                "gsa": None,
                "gsm_secret_name": None,
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["spec"]["oci"]["auth"], "none")
        self.assertNotIn("secretRef", res["spec"]["oci"])
        self.assertNotIn("gcpServiceAccountEmail", res["spec"]["oci"])

    def test_oci_rootsync_with_gsm_secret(self):
        """OCI with gsm_secret_name and no GSA uses auth: token and secretRef."""
        cfg = {
            "cluster_config_name": "regional-profile",
            "oci": {
                "image": "docker.io/myorg/config:latest",
                "gsm_secret_name": "dockerhub-creds",
            },
        }
        res = generate_rootsync_manifest("edge-01", cfg, gcp_project_id="proj-123")
        self.assertIsNotNone(res)
        assert res is not None
        spec = res["spec"]
        self.assertEqual(spec["oci"]["auth"], "token")
        self.assertEqual(spec["oci"]["dir"], "config/clusters/regional-profile")
        self.assertEqual(spec["oci"]["secretRef"]["name"], "dockerhub-creds")
        self.assertNotIn("gcpServiceAccountEmail", spec["oci"])

    def test_oci_rootsync_without_credentials(self):
        """OCI without GSA or gsm_secret_name uses auth: none."""
        cfg = {
            "oci": {
                "image": "us-docker.pkg.dev/proj-123/public/config:v1",
            }
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        spec = res["spec"]
        self.assertEqual(spec["oci"]["auth"], "none")
        self.assertNotIn("secretRef", spec["oci"])
        self.assertNotIn("gcpServiceAccountEmail", spec["oci"])


class TestPrecedenceAndOmission(unittest.TestCase):
    """Verifies source precedence and handling of missing or skipped configurations."""

    def test_git_supersedes_oci(self):
        """When both git and oci are supplied, git takes precedence."""
        cfg = {
            "git": {
                "repo_url": "https://gitlab.com/org/repo.git",
                "branch": "main",
            },
            "oci": {
                "image": "us-docker.pkg.dev/proj/repo/config:v1",
            },
        }
        res = generate_rootsync_manifest("edge-01", cfg)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["spec"]["sourceType"], "git")
        self.assertNotIn("oci", res["spec"])

    def test_primary_root_repo_omitted_returns_none(self):
        """When primary_root_repo is None or empty dict, RootSync is skipped."""
        self.assertIsNone(generate_rootsync_manifest("edge-01", None))
        self.assertIsNone(generate_rootsync_manifest("edge-01", {}))
        self.assertIsNone(generate_rootsync_manifest("edge-01", ""))


class TestSecretInjectionLogic(unittest.TestCase):
    """Verifies secret injection data dict and stdin manifest generation without writing plaintext to disk."""

    def test_git_token_secret_manifest(self):
        """Generates Secret manifest with stringData token and username for git."""
        data_dict, auth = compute_secret_data_dict(
            repo_type="git",
            payload={"token": "ghp_mock123", "username": "gituser"},
        )
        self.assertEqual(auth, "token")
        self.assertEqual(data_dict, {"token": "ghp_mock123", "username": "gituser"})
        manifest = generate_secret_manifest("git-creds", data_dict)
        self.assertEqual(manifest["apiVersion"], "v1")
        self.assertEqual(manifest["kind"], "Secret")
        self.assertEqual(manifest["metadata"]["name"], "git-creds")
        self.assertEqual(manifest["metadata"]["namespace"], "config-management-system")
        self.assertEqual(manifest["type"], "Opaque")
        self.assertEqual(manifest["stringData"]["token"], "ghp_mock123")
        self.assertEqual(manifest["stringData"]["username"], "gituser")

    def test_git_password_fallback_secret_manifest(self):
        """Generates Secret manifest with token mapped from password when token is absent."""
        data_dict, auth = compute_secret_data_dict(
            repo_type="git",
            payload={"password": "pwd_secret123", "username": "gituser"},
        )
        self.assertEqual(auth, "token")
        self.assertEqual(data_dict, {"token": "pwd_secret123", "username": "gituser"})

    def test_git_ssh_key_secret_manifest_and_auth_detection(self):
        """Generates Secret manifest with stringData ssh-privatekey and detects auth: ssh."""
        multiline_key = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
            "-----END OPENSSH PRIVATE KEY-----\n"
        )
        data_dict, auth = compute_secret_data_dict(
            repo_type="git",
            payload={"ssh-privatekey": multiline_key},
        )
        self.assertEqual(auth, "ssh")
        self.assertEqual(data_dict, {"ssh-privatekey": multiline_key})
        manifest = generate_secret_manifest("ssh-creds", data_dict)
        self.assertEqual(manifest["stringData"]["ssh-privatekey"], multiline_key)

    def test_git_ssh_key_takes_precedence_over_token(self):
        """When both ssh-privatekey and token are present, ssh-privatekey takes precedence."""
        data_dict, auth = compute_secret_data_dict(
            repo_type="git",
            payload={"ssh-privatekey": "MOCK_SSH_KEY", "token": "ghp_unused"},
        )
        self.assertEqual(auth, "ssh")
        self.assertEqual(data_dict, {"ssh-privatekey": "MOCK_SSH_KEY"})

    def test_oci_secret_manifest(self):
        """Generates Secret manifest with username and password for OCI."""
        data_dict, _ = compute_secret_data_dict(
            repo_type="oci",
            payload={"username": "user", "password": "pass"},
        )
        self.assertEqual(data_dict, {"username": "user", "password": "pass"})
        manifest = generate_secret_manifest("oci-creds", data_dict)
        self.assertEqual(manifest["stringData"]["username"], "user")
        self.assertEqual(manifest["stringData"]["password"], "pass")

    def test_build_secret_injection_command(self):
        """Verifies build_secret_injection_command returns kubectl apply via stdin command."""
        cmd = build_secret_injection_command(
            secret_name="git-creds",
            repo_type="git",
            payload={"token": "ghp_mock123", "username": "gituser"},
        )
        self.assertEqual(
            cmd, "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f -"
        )

    def test_secret_stdin_yaml_roundtrip(self):
        """Verifies stdin YAML serializes and deserializes as a valid Kubernetes Secret."""
        data_dict, _ = compute_secret_data_dict(
            repo_type="git",
            payload={"token": "ghp_mock123", "username": "gituser"},
        )
        yaml_str = generate_secret_stdin_yaml("git-creds", data_dict)
        parsed = yaml.safe_load(yaml_str)
        self.assertEqual(parsed["apiVersion"], "v1")
        self.assertEqual(parsed["kind"], "Secret")
        self.assertEqual(parsed["metadata"]["name"], "git-creds")
        self.assertEqual(parsed["metadata"]["namespace"], "config-management-system")
        self.assertEqual(parsed["type"], "Opaque")
        self.assertEqual(parsed["stringData"]["token"], "ghp_mock123")
        self.assertEqual(parsed["stringData"]["username"], "gituser")


class TestConfigSyncAnsibleTasks(unittest.TestCase):
    """Verifies the structure and content of config_sync.yml."""

    def setUp(self):
        self.assertTrue(
            os.path.exists(CONFIG_SYNC_TASKS_PATH),
            f"ConfigSync tasks file does not exist at {CONFIG_SYNC_TASKS_PATH}",
        )
        with open(CONFIG_SYNC_TASKS_PATH, "r", encoding="utf-8") as f:
            self.raw_content = f.read()
            self.tasks = yaml.safe_load(self.raw_content)

    def test_tasks_parse_as_valid_yaml(self):
        """Verifies that config_sync.yml is valid YAML and contains tasks."""
        self.assertIsInstance(self.tasks, list)
        self.assertGreater(len(self.tasks), 0)

    def test_top_level_guard_conditions(self):
        """Verifies config_sync_enabled and offline_mode guards."""
        self.assertIn("config_sync_enabled", self.raw_content)
        self.assertIn("offline_mode", self.raw_content)

    def test_fleet_config_management_enablement(self):
        """Verifies Fleet config-management describe check and enable tasks."""
        self.assertIn(
            "gcloud beta container fleet config-management describe", self.raw_content
        )
        self.assertIn(
            "gcloud beta container fleet config-management enable", self.raw_content
        )

    def test_acm_config_generation(self):
        """Verifies acm-config.yaml generation with applySpecVersion and sourceFormat."""
        self.assertIn("/var/gdc-install/state/acm-config.yaml", self.raw_content)
        self.assertIn("applySpecVersion: 1", self.raw_content)
        self.assertIn("configSync:", self.raw_content)
        self.assertIn("sourceFormat: unstructured", self.raw_content)

    def test_fleet_config_management_apply(self):
        """Verifies gcloud beta container fleet config-management apply."""
        self.assertIn(
            "gcloud beta container fleet config-management apply", self.raw_content
        )
        self.assertIn("--membership=", self.raw_content)
        self.assertIn(
            "--config=/var/gdc-install/state/acm-config.yaml", self.raw_content
        )

    def test_wait_for_rootsync_crd(self):
        """Verifies wait for rootsyncs.configsync.gke.io CRD."""
        self.assertIn(
            "kubectl --kubeconfig=/etc/kubernetes/admin.conf wait --for=condition=Established crd/rootsyncs.configsync.gke.io --timeout=180s",
            self.raw_content,
        )

    def test_secret_access_and_injection_has_no_log(self):
        """Verifies secret access and injection tasks use no_log: true and stdin apply."""
        self.assertIn("gcloud secrets versions access latest", self.raw_content)
        self.assertIn(
            "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f -",
            self.raw_content,
        )
        self.assertIn("stdin: |", self.raw_content)
        self.assertIn("no_log: true", self.raw_content)

    def test_kubectl_apply_changed_when_idempotency(self):
        """Verifies kubectl apply tasks use created/configured checks instead of changed_when: true."""
        self.assertIn(
            "'created' in secret_apply_res.stdout or 'configured' in secret_apply_res.stdout",
            self.raw_content,
        )
        self.assertIn(
            "'created' in rootsync_apply_res.stdout or 'configured' in rootsync_apply_res.stdout",
            self.raw_content,
        )

    def test_secret_memory_purge(self):
        """Verifies in-memory secrets are purged after creation in always block."""
        self.assertIn("Purge in-memory secret facts", self.raw_content)
        self.assertIn("always:", self.raw_content)
        self.assertIn("secret_apply_res: {}", self.raw_content)

    def test_rootsync_manifest_path(self):
        """Verifies RootSync manifest is rendered to /var/gdc-install/state/primary-root-repo.yaml."""
        self.assertIn("/var/gdc-install/state/primary-root-repo.yaml", self.raw_content)
        self.assertIn(
            "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f /var/gdc-install/state/primary-root-repo.yaml",
            self.raw_content,
        )

    def test_config_sync_evidence_set(self):
        """Verifies config_sync_evidence fact is structured."""
        self.assertIn("config_sync_evidence", self.raw_content)


class TestPostClusterMainIntegration(unittest.TestCase):
    """Verifies post_cluster/tasks/main.yml includes config_sync and updates evidence."""

    def setUp(self):
        self.assertTrue(
            os.path.exists(MAIN_TASKS_PATH),
            f"Main tasks file does not exist at {MAIN_TASKS_PATH}",
        )
        with open(MAIN_TASKS_PATH, "r", encoding="utf-8") as f:
            self.raw_content = f.read()
            self.tasks = yaml.safe_load(self.raw_content)

    def test_main_includes_config_sync(self):
        """Verifies main.yml imports or includes config_sync.yml."""
        self.assertIn("config_sync.yml", self.raw_content)

    def test_main_updates_post_cluster_evidence(self):
        """Verifies main.yml incorporates config_sync into post_cluster_evidence."""
        self.assertIn("config_sync", self.raw_content)


class TestConfigSyncJinjaRendering(unittest.TestCase):
    """Verifies that the exact Jinja2 expressions and RootSync templates from config_sync.yml render correctly."""

    @classmethod
    def setUpClass(cls):
        with open(CONFIG_SYNC_TASKS_PATH, "r", encoding="utf-8") as f:
            tasks_data = yaml.safe_load(f)
        block = tasks_data[1]["block"]
        cls.identity_facts = next(
            t["ansible.builtin.set_fact"]
            for t in block
            if "Resolve cluster identity" in t.get("name", "")
        )
        cls.repo_facts = next(
            t["ansible.builtin.set_fact"]
            for t in block
            if "Set primary_root_repo facts" in t.get("name", "")
        )
        cls.git_copy = next(
            t["ansible.builtin.copy"]
            for t in block
            if "Render Git RootSync manifest" in t.get("name", "")
        )
        cls.oci_copy = next(
            t["ansible.builtin.copy"]
            for t in block
            if "Render OCI RootSync manifest" in t.get("name", "")
        )
        cls.secret_injection_task = next(
            t
            for t in block
            if "Execute Bootstrap Secret Injection" in t.get("name", "")
        )
        injection_block = cls.secret_injection_task.get("block", [])
        cls.secret_facts = next(
            t["ansible.builtin.set_fact"]
            for t in injection_block
            if "Set resolved secret data" in t.get("name", "")
        )
        cls.secret_apply_task = next(
            t
            for t in injection_block
            if "Create or update Kubernetes secret" in t.get("name", "")
        )
        cls.env = jinja2.Environment()
        try:
            from ansible.plugins.filter.core import (  # type: ignore[import-not-found]
                combine,
                to_nice_yaml,
            )
            cls.env.filters["combine"] = combine
            cls.env.filters["to_nice_yaml"] = to_nice_yaml
        except ImportError:
            cls.env.filters["combine"] = lambda *dicts, **kwargs: {
                k: v for d in dicts if isinstance(d, dict) for k, v in d.items()
            }
            cls.env.filters["to_nice_yaml"] = lambda val, indent=2, **kwargs: (
                yaml.dump(val, default_flow_style=False, indent=indent)
            )

    def _render(self, tmpl_str: str, **kwargs) -> str:
        return self.env.from_string(tmpl_str).render(**kwargs).strip()

    def _resolve_repo(self, field: str, machine_config=None, cluster_name="") -> str:
        resolved = resolve_primary_root_repo(machine_config, cluster_name=cluster_name)
        return self._render(self.repo_facts[field], config_sync_repo=resolved)

    # target_cluster_name fallback and null safety
    def test_target_cluster_name_from_machine_config(self):
        mc = {"cluster": {"cluster_name": "prod-cluster-01"}}
        val = self._render(
            self.identity_facts["target_cluster_name"], machine_config=mc
        )
        self.assertEqual(val, "prod-cluster-01")

    def test_target_cluster_name_null_fallback_to_cluster_name(self):
        mc = {"cluster": {"cluster_name": None}}
        val = self._render(
            self.identity_facts["target_cluster_name"],
            machine_config=mc,
            cluster_name="fallback-cluster",
        )
        self.assertEqual(val, "fallback-cluster")

    def test_target_cluster_name_empty_fallback(self):
        mc = {"cluster": {"cluster_name": "   "}}
        val = self._render(
            self.identity_facts["target_cluster_name"],
            machine_config=mc,
            cluster_name="fallback-cluster",
        )
        self.assertEqual(val, "fallback-cluster")

    def test_target_cluster_name_missing_machine_config(self):
        val = self._render(
            self.identity_facts["target_cluster_name"],
            cluster_name="fallback-cluster",
        )
        self.assertEqual(val, "fallback-cluster")

    # target_gcp_project_id fallback and null safety
    def test_target_gcp_project_id_from_machine_config(self):
        mc = {"gcp_info": {"project_id": "my-gcp-proj"}}
        val = self._render(
            self.identity_facts["target_gcp_project_id"], machine_config=mc
        )
        self.assertEqual(val, "my-gcp-proj")

    def test_target_gcp_project_id_null_fallback(self):
        mc = {"gcp_info": {"project_id": None}}
        val = self._render(
            self.identity_facts["target_gcp_project_id"],
            machine_config=mc,
            gcp_project_id="fallback-proj",
        )
        self.assertEqual(val, "fallback-proj")

    def test_target_gcp_project_id_empty_fallback(self):
        mc = {"gcp_info": {"project_id": ""}}
        val = self._render(
            self.identity_facts["target_gcp_project_id"],
            machine_config=mc,
            gcp_project_id="fallback-proj",
        )
        self.assertEqual(val, "fallback-proj")

    # target_gcp_region fallback and null safety
    def test_target_gcp_region_from_machine_config(self):
        mc = {"gcp_info": {"region": "us-central1"}}
        val = self._render(self.identity_facts["target_gcp_region"], machine_config=mc)
        self.assertEqual(val, "us-central1")

    def test_target_gcp_region_null_fallback(self):
        mc = {"gcp_info": {"region": None}}
        val = self._render(
            self.identity_facts["target_gcp_region"],
            machine_config=mc,
            gcp_region="europe-west1",
        )
        self.assertEqual(val, "europe-west1")

    def test_target_gcp_region_default_us_west1(self):
        mc = {"gcp_info": {}}
        val = self._render(self.identity_facts["target_gcp_region"], machine_config=mc)
        self.assertEqual(val, "us-west1")

    # target_sync_dir fallback and null safety
    def test_target_sync_dir_with_cluster_config_name(self):
        mc = {
            "cluster": {
                "cluster_name": "cluster-a",
                "primary_root_repo": {"cluster_config_name": "shared-edge-prod"},
            }
        }
        val = self._resolve_repo("target_sync_dir", machine_config=mc)
        self.assertEqual(val, "config/clusters/shared-edge-prod")

    def test_target_sync_dir_with_null_cluster_config_name(self):
        mc = {
            "cluster": {
                "cluster_name": "cluster-a",
                "primary_root_repo": {"cluster_config_name": None},
            }
        }
        val = self._resolve_repo("target_sync_dir", machine_config=mc)
        self.assertEqual(val, "config/clusters/cluster-a")
        self.assertNotIn("None", val)

    def test_target_sync_dir_with_empty_cluster_config_name(self):
        mc = {
            "cluster": {
                "cluster_name": "cluster-a",
                "primary_root_repo": {"cluster_config_name": "   "},
            }
        }
        val = self._resolve_repo("target_sync_dir", machine_config=mc)
        self.assertEqual(val, "config/clusters/cluster-a")

    def test_target_sync_dir_missing_cluster_config_name(self):
        mc = {
            "cluster": {
                "cluster_name": "cluster-a",
                "primary_root_repo": {
                    "git": {"repo_url": "https://example.com/repo.git"}
                },
            }
        }
        val = self._resolve_repo("target_sync_dir", machine_config=mc)
        self.assertEqual(val, "config/clusters/cluster-a")

    def test_target_sync_dir_fallback_to_cluster_name_var(self):
        mc = {
            "cluster": {
                "cluster_name": None,
                "primary_root_repo": {},
            }
        }
        val = self._resolve_repo(
            "target_sync_dir",
            machine_config=mc,
            cluster_name="var-cluster",
        )
        self.assertEqual(val, "config/clusters/var-cluster")

    # target_oci_gsa and target_secret_name exclusivity
    def test_target_oci_gsa_with_valid_gsa(self):
        mc = {"cluster": {"primary_root_repo": {"oci": {"gsa": "sa-configsync"}}}}
        val = self._resolve_repo("target_oci_gsa", machine_config=mc)
        self.assertEqual(val, "sa-configsync")

    def test_target_oci_gsa_with_null(self):
        mc = {"cluster": {"primary_root_repo": {"oci": {"gsa": None}}}}
        val = self._resolve_repo("target_oci_gsa", machine_config=mc)
        self.assertEqual(val, "")
        self.assertNotIn("None", val)

    def test_target_oci_gsa_with_empty(self):
        mc = {"cluster": {"primary_root_repo": {"oci": {"gsa": "   "}}}}
        val = self._resolve_repo("target_oci_gsa", machine_config=mc)
        self.assertEqual(val, "")

    def test_oci_gsa_suppresses_target_secret_name(self):
        """When OCI has a valid GSA, target_gsm_secret_name and target_k8s_secret_name MUST be empty."""
        mc = {
            "cluster": {
                "primary_root_repo": {
                    "oci": {
                        "gsa": "sa-configsync",
                        "gsm_secret_name": "dockerhub-token",
                    }
                }
            }
        }
        val_gsm = self._resolve_repo("target_gsm_secret_name", machine_config=mc)
        val_k8s = self._resolve_repo("target_k8s_secret_name", machine_config=mc)
        self.assertEqual(val_gsm, "")
        self.assertEqual(val_k8s, "")

    def test_oci_target_secret_name_with_secret_and_no_gsa(self):
        mc = {
            "cluster": {
                "primary_root_repo": {
                    "oci": {
                        "gsm_secret_name": "dockerhub-token",
                    }
                }
            }
        }
        val_gsm = self._resolve_repo("target_gsm_secret_name", machine_config=mc)
        val_k8s = self._resolve_repo("target_k8s_secret_name", machine_config=mc)
        self.assertEqual(val_gsm, "dockerhub-token")
        self.assertEqual(val_k8s, "dockerhub-token")

    def test_oci_target_secret_name_with_null_secret(self):
        mc = {
            "cluster": {
                "primary_root_repo": {
                    "oci": {
                        "gsm_secret_name": None,
                    }
                }
            }
        }
        val_gsm = self._resolve_repo("target_gsm_secret_name", machine_config=mc)
        val_k8s = self._resolve_repo("target_k8s_secret_name", machine_config=mc)
        self.assertEqual(val_gsm, "")
        self.assertEqual(val_k8s, "")

    def test_git_target_secret_name_with_secret(self):
        mc = {
            "cluster": {
                "primary_root_repo": {
                    "git": {
                        "gsm_secret_name": "git-deploy-token",
                    }
                }
            }
        }
        val_gsm = self._resolve_repo("target_gsm_secret_name", machine_config=mc)
        val_k8s = self._resolve_repo("target_k8s_secret_name", machine_config=mc)
        self.assertEqual(val_gsm, "git-deploy-token")
        self.assertEqual(val_k8s, "git-deploy-token")

    def test_git_target_secret_name_with_null_secret(self):
        mc = {
            "cluster": {
                "primary_root_repo": {
                    "git": {
                        "gsm_secret_name": None,
                    }
                }
            }
        }
        val_gsm = self._resolve_repo("target_gsm_secret_name", machine_config=mc)
        val_k8s = self._resolve_repo("target_k8s_secret_name", machine_config=mc)
        self.assertEqual(val_gsm, "")
        self.assertEqual(val_k8s, "")

    def test_git_target_secret_name_public(self):
        mc = {
            "cluster": {
                "primary_root_repo": {
                    "git": {"repo_url": "https://gitlab.com/org/repo.git"}
                }
            }
        }
        val_gsm = self._resolve_repo("target_gsm_secret_name", machine_config=mc)
        val_k8s = self._resolve_repo("target_k8s_secret_name", machine_config=mc)
        self.assertEqual(val_gsm, "")
        self.assertEqual(val_k8s, "")

    # Exact RootSync template rendering
    def test_git_rootsync_template_with_secret(self):
        rendered = self._render(
            self.git_copy["content"],
            target_repo_url="https://git.example.com/repo.git",
            target_branch="release-1.0",
            target_sync_dir="config/clusters/edge-01",
            target_k8s_secret_name="git-token-secret",
            target_git_auth="token",
        )
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed["apiVersion"], "configsync.gke.io/v1beta1")
        self.assertEqual(parsed["kind"], "RootSync")
        self.assertEqual(parsed["spec"]["sourceType"], "git")
        git_spec = parsed["spec"]["git"]
        self.assertEqual(git_spec["repo"], "https://git.example.com/repo.git")
        self.assertEqual(git_spec["branch"], "release-1.0")
        self.assertEqual(git_spec["dir"], "config/clusters/edge-01")
        self.assertEqual(git_spec["auth"], "token")
        self.assertEqual(git_spec["secretRef"]["name"], "git-token-secret")

    def test_git_rootsync_template_public_and_null_branch(self):
        rendered = self._render(
            self.git_copy["content"],
            target_repo_url="https://git.example.com/repo.git",
            target_branch="main",
            target_sync_dir="config/clusters/edge-01",
            target_k8s_secret_name="",
            target_git_auth="none",
        )
        parsed = yaml.safe_load(rendered)
        git_spec = parsed["spec"]["git"]
        self.assertEqual(git_spec["repo"], "https://git.example.com/repo.git")
        self.assertEqual(git_spec["branch"], "main")
        self.assertEqual(git_spec["dir"], "config/clusters/edge-01")
        self.assertEqual(git_spec["auth"], "none")
        self.assertNotIn("secretRef", git_spec)

    def test_oci_rootsync_template_with_gsa(self):
        rendered = self._render(
            self.oci_copy["content"],
            target_repo_url="us-docker.pkg.dev/my-proj/repo/cfg:v1",
            target_sync_dir="config/clusters/edge-01",
            target_oci_gsa="sa-configsync",
            target_gcp_project_id="my-proj",
            target_k8s_secret_name="",
        )
        parsed = yaml.safe_load(rendered)
        oci_spec = parsed["spec"]["oci"]
        self.assertEqual(oci_spec["image"], "us-docker.pkg.dev/my-proj/repo/cfg:v1")
        self.assertEqual(oci_spec["dir"], "config/clusters/edge-01")
        self.assertEqual(oci_spec["auth"], "gcpserviceaccount")
        self.assertEqual(
            oci_spec["gcpServiceAccountEmail"],
            "sa-configsync@my-proj.iam.gserviceaccount.com",
        )
        self.assertNotIn("secretRef", oci_spec)

    def test_oci_rootsync_template_gsa_ignores_secret_ref(self):
        """Even if target_k8s_secret_name is set, OCI with GSA does NOT emit secretRef."""
        rendered = self._render(
            self.oci_copy["content"],
            target_repo_url="us-docker.pkg.dev/my-proj/repo/cfg:v1",
            target_sync_dir="config/clusters/edge-01",
            target_oci_gsa="sa-configsync",
            target_gcp_project_id="my-proj",
            target_k8s_secret_name="ignored-secret",
        )
        parsed = yaml.safe_load(rendered)
        oci_spec = parsed["spec"]["oci"]
        self.assertEqual(oci_spec["auth"], "gcpserviceaccount")
        self.assertEqual(
            oci_spec["gcpServiceAccountEmail"],
            "sa-configsync@my-proj.iam.gserviceaccount.com",
        )
        self.assertNotIn("secretRef", oci_spec)

    def test_oci_rootsync_template_with_secret(self):
        rendered = self._render(
            self.oci_copy["content"],
            target_repo_url="docker.io/myorg/cfg:v1",
            target_sync_dir="config/clusters/edge-01",
            target_oci_gsa="",
            target_gcp_project_id="my-proj",
            target_k8s_secret_name="oci-creds",
        )
        parsed = yaml.safe_load(rendered)
        oci_spec = parsed["spec"]["oci"]
        self.assertEqual(oci_spec["image"], "docker.io/myorg/cfg:v1")
        self.assertEqual(oci_spec["dir"], "config/clusters/edge-01")
        self.assertEqual(oci_spec["auth"], "token")
        self.assertEqual(oci_spec["secretRef"]["name"], "oci-creds")
        self.assertNotIn("gcpServiceAccountEmail", oci_spec)

    def test_oci_rootsync_template_public(self):
        rendered = self._render(
            self.oci_copy["content"],
            target_repo_url="docker.io/myorg/cfg:v1",
            target_sync_dir="config/clusters/edge-01",
            target_oci_gsa="",
            target_gcp_project_id="my-proj",
            target_k8s_secret_name="",
        )
        parsed = yaml.safe_load(rendered)
        oci_spec = parsed["spec"]["oci"]
        self.assertEqual(oci_spec["image"], "docker.io/myorg/cfg:v1")
        self.assertEqual(oci_spec["dir"], "config/clusters/edge-01")
        self.assertEqual(oci_spec["auth"], "none")
        self.assertNotIn("secretRef", oci_spec)
        self.assertNotIn("gcpServiceAccountEmail", oci_spec)

    def test_git_rootsync_template_with_ssh_secret(self):
        rendered = self._render(
            self.git_copy["content"],
            target_repo_url="git@github.com:org/repo.git",
            target_branch="main",
            target_sync_dir="config/clusters/edge-01",
            target_k8s_secret_name="git-ssh-secret",
            target_git_auth="ssh",
        )
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed["apiVersion"], "configsync.gke.io/v1beta1")
        self.assertEqual(parsed["kind"], "RootSync")
        self.assertEqual(parsed["spec"]["sourceType"], "git")
        git_spec = parsed["spec"]["git"]
        self.assertEqual(git_spec["repo"], "git@github.com:org/repo.git")
        self.assertEqual(git_spec["branch"], "main")
        self.assertEqual(git_spec["dir"], "config/clusters/edge-01")
        self.assertEqual(git_spec["auth"], "ssh")
        self.assertEqual(git_spec["secretRef"]["name"], "git-ssh-secret")
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed["apiVersion"], "configsync.gke.io/v1beta1")
        self.assertEqual(parsed["kind"], "RootSync")
        self.assertEqual(parsed["spec"]["sourceType"], "git")
        git_spec = parsed["spec"]["git"]
        self.assertEqual(git_spec["repo"], "git@github.com:org/repo.git")
        self.assertEqual(git_spec["branch"], "main")
        self.assertEqual(git_spec["dir"], "config/clusters/edge-01")
        self.assertEqual(git_spec["auth"], "ssh")
        self.assertEqual(git_spec["secretRef"]["name"], "git-ssh-secret")

    def test_git_secret_fact_ssh_key(self):
        payload = {
            "ssh-privatekey": (
                "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                "abc\n"
                "-----END OPENSSH PRIVATE KEY-----\n"
            )
        }
        res = resolve_secret_payload(payload, repo_type="git")
        auth_val = self._render(
            self.secret_facts["target_git_auth"], secret_resolution=res
        )
        self.assertEqual(auth_val, "ssh")

    def test_git_secret_fact_token_and_username(self):
        payload = {"token": "ghp_mock123", "username": "gituser"}
        res = resolve_secret_payload(payload, repo_type="git")
        auth_val = self._render(
            self.secret_facts["target_git_auth"], secret_resolution=res
        )
        self.assertEqual(auth_val, "token")

    def test_git_secret_fact_password_fallback(self):
        payload = {"password": "pwd_secret123", "username": "gituser"}
        res = resolve_secret_payload(payload, repo_type="git")
        auth_val = self._render(
            self.secret_facts["target_git_auth"], secret_resolution=res
        )
        self.assertEqual(auth_val, "token")

    def test_git_secret_fact_ssh_precedence(self):
        payload = {"ssh-privatekey": "MOCK_KEY", "token": "ghp_mock123"}
        res = resolve_secret_payload(payload, repo_type="git")
        auth_val = self._render(
            self.secret_facts["target_git_auth"], secret_resolution=res
        )
        self.assertEqual(auth_val, "ssh")

    def test_oci_secret_fact(self):
        payload = {"username": "user", "password": "pass"}
        res = resolve_secret_payload(payload, repo_type="oci")
        self.assertEqual(res["secret_data"]["username"], "user")
        self.assertEqual(res["secret_data"]["password"], "pass")

    def test_secret_apply_task_command_and_changed_when(self):
        self.assertEqual(
            self.secret_apply_task["ansible.builtin.command"]["cmd"],
            "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f -",
        )
        self.assertEqual(
            self.secret_apply_task["changed_when"],
            "'created' in secret_apply_res.stdout or 'configured' in secret_apply_res.stdout",
        )

    def test_secret_apply_task_stdin_rendering(self):
        stdin_tmpl = self.secret_apply_task["ansible.builtin.command"]["stdin"]
        rendered = self._render(
            stdin_tmpl,
            target_k8s_secret_name="git-creds",
            target_k8s_namespace="config-management-system",
            secret_data_dict={"token": "ghp_123"},
        )
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed["apiVersion"], "v1")
        self.assertEqual(parsed["kind"], "Secret")
        self.assertEqual(parsed["metadata"]["name"], "git-creds")
        self.assertEqual(parsed["metadata"]["namespace"], "config-management-system")
        self.assertEqual(parsed["type"], "Opaque")
        self.assertEqual(parsed["stringData"]["token"], "ghp_123")

    def test_secret_apply_task_stdin_multi_key_rendering(self):
        """Verifies multi-key secret dictionary renders valid YAML with all keys under stringData."""
        stdin_tmpl = self.secret_apply_task["ansible.builtin.command"]["stdin"]
        rendered = self._render(
            stdin_tmpl,
            target_k8s_secret_name="oci-creds",
            target_k8s_namespace="config-management-system",
            secret_data_dict={"username": "user", "password": "password"},
        )
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed["apiVersion"], "v1")
        self.assertEqual(parsed["kind"], "Secret")
        self.assertEqual(parsed["metadata"]["name"], "oci-creds")
        self.assertEqual(parsed["metadata"]["namespace"], "config-management-system")
        self.assertEqual(parsed["type"], "Opaque")
        self.assertEqual(parsed["stringData"]["username"], "user")
        self.assertEqual(parsed["stringData"]["password"], "password")

    def test_secret_purge_task_in_always_block(self):
        """Verifies secret purge task is in always: block and purges all secret facts."""
        always_tasks = self.secret_injection_task.get("always", [])
        self.assertGreater(len(always_tasks), 0)
        purge_task = next(
            (t for t in always_tasks if "Purge" in t.get("name", "")), None
        )
        self.assertIsNotNone(purge_task)
        assert purge_task is not None
        self.assertTrue(purge_task.get("no_log", False))
        facts = purge_task["ansible.builtin.set_fact"]
        self.assertEqual(facts.get("gsm_access_res"), {})
        self.assertEqual(facts.get("gsm_secret_payload"), {})
        self.assertEqual(facts.get("secret_resolution"), {})
        self.assertEqual(facts.get("secret_data_dict"), {})
        self.assertEqual(facts.get("secret_apply_res"), {})

    def test_secret_injection_task_when_conditions(self):
        when_list = self.secret_injection_task.get("when", [])
        self.assertTrue(
            any("requires_secret" in cond for cond in when_list),
            f"Expected requires_secret in when conditions: {when_list}",
        )


if __name__ == "__main__":
    unittest.main()
