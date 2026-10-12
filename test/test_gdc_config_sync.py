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

"""Unit tests for GDC ConfigSync Decision Matrix and Ansible Lookup Plugin."""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOOKUP_PLUGIN_DIR = os.path.join(PROJECT_ROOT, "src", "ansible", "lookup_plugins")
if LOOKUP_PLUGIN_DIR not in sys.path:
    sys.path.insert(0, LOOKUP_PLUGIN_DIR)

for venv_dir in (".venv", "venv", "src/build/.venv"):
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    venv_site = os.path.join(PROJECT_ROOT, venv_dir, "lib", py_ver, "site-packages")
    if os.path.isdir(venv_site) and venv_site not in sys.path:
        sys.path.insert(0, venv_site)

from gdc_config_sync_resolver import (  # pylint: disable=wrong-import-position,import-error # type: ignore[import-not-found]
    extract_gsm_secret_info,
    resolve_primary_root_repo,
    resolve_secret_payload,
)
from gdc_config_sync import LookupModule  # pylint: disable=wrong-import-position,import-error # type: ignore[import-not-found]


class TestPrimaryRootRepoResolution(unittest.TestCase):
    """Verifies complete decision matrix for resolve_primary_root_repo."""

    def test_empty_or_invalid_machine_config(self):
        """Verifies empty, None, or invalid configs return default 'none' structure."""
        for invalid in [None, {}, {"other": 123}, "invalid"]:
            res = resolve_primary_root_repo(invalid)  # type: ignore[arg-type]
            self.assertEqual(res["repo_type"], "none")
            self.assertEqual(res["repo_url"], "")
            self.assertEqual(res["branch"], "")
            self.assertEqual(res["sync_dir"], "")
            self.assertEqual(res["gsm_secret_name"], "")
            self.assertEqual(res["k8s_secret_name"], "")
            self.assertFalse(res["requires_secret"])
            self.assertEqual(res["auth_type"], "none")

    def test_cluster_without_primary_root_repo(self):
        """Verifies machine_config with cluster but without primary_root_repo."""
        config = {"cluster": {"cluster_name": "edge-cluster-1"}}
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "none")
        self.assertFalse(res["requires_secret"])

    def test_legacy_string_git_url_without_secret(self):
        """Verifies legacy string git repo without auth secret."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": "https://gitlab.com/retail/edge-config.git",
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "git")
        self.assertEqual(res["repo_url"], "https://gitlab.com/retail/edge-config.git")
        self.assertEqual(res["branch"], "main")
        self.assertEqual(res["sync_dir"], "config/clusters/edge-01")
        self.assertEqual(res["gsm_secret_name"], "")
        self.assertEqual(res["k8s_secret_name"], "")
        self.assertFalse(res["requires_secret"])
        self.assertEqual(res["auth_type"], "none")

    def test_legacy_string_git_url_with_auth_secret(self):
        """Verifies legacy string git repo with primary_root_repo_auth_secret."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": "https://gitlab.com/retail/edge-config.git",
                "primary_root_repo_auth_secret": "git-creds-gsm",
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "git")
        self.assertEqual(res["gsm_secret_name"], "git-creds-gsm")
        self.assertEqual(res["k8s_secret_name"], "git-creds-gsm")
        self.assertTrue(res["requires_secret"])
        self.assertEqual(res["auth_type"], "token")

    def test_legacy_string_oci_without_secret(self):
        """Verifies legacy string OCI image without auth secret."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": "us-docker.pkg.dev/project/repo/config:v1",
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "oci")
        self.assertEqual(res["repo_url"], "us-docker.pkg.dev/project/repo/config:v1")
        self.assertEqual(res["sync_dir"], "config/clusters/edge-01")
        self.assertFalse(res["requires_secret"])
        self.assertEqual(res["auth_type"], "none")

    def test_legacy_string_none_or_blank(self):
        """Verifies legacy string 'none' or blank strings result in repo_type: none."""
        for val in ["none", "  ", ""]:
            config = {"cluster": {"cluster_name": "edge-01", "primary_root_repo": val}}
            res = resolve_primary_root_repo(config)
            self.assertEqual(res["repo_type"], "none")

    def test_structured_git_defaults_and_branch(self):
        """Verifies structured git config with explicit branch and gsm_secret_name."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/org/repo.git",
                        "branch": "release-v2",
                        "gsm_secret_name": "git-pat-secret",
                    }
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "git")
        self.assertEqual(res["repo_url"], "https://gitlab.com/org/repo.git")
        self.assertEqual(res["branch"], "release-v2")
        self.assertEqual(res["sync_dir"], "config/clusters/edge-01")
        self.assertEqual(res["gsm_secret_name"], "git-pat-secret")
        self.assertEqual(res["k8s_secret_name"], "git-pat-secret")
        self.assertTrue(res["requires_secret"])
        self.assertEqual(res["auth_type"], "token")

    def test_structured_git_cluster_config_name_override(self):
        """Verifies cluster_config_name overrides cluster_name in sync_dir."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "cluster_config_name": "cluster-tier-gold",
                    "git": {
                        "repo_url": "https://gitlab.com/org/repo.git",
                    },
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["sync_dir"], "config/clusters/cluster-tier-gold")
        self.assertEqual(res["branch"], "main")
        self.assertFalse(res["requires_secret"])

    def test_structured_oci_with_gsa_suppresses_secret(self):
        """Verifies OCI with GSA uses Workload Identity and suppresses secret injection."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "oci": {
                        "image": "us-docker.pkg.dev/proj/repo:v1",
                        "gsa": "sa-companion",
                        "gsm_secret_name": "ignored-secret",
                    }
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "oci")
        self.assertEqual(res["oci_gsa"], "sa-companion")
        self.assertEqual(res["auth_type"], "gcpserviceaccount")
        self.assertEqual(res["gsm_secret_name"], "")
        self.assertEqual(res["k8s_secret_name"], "")
        self.assertFalse(res["requires_secret"])

    def test_structured_oci_with_gsm_secret_and_no_gsa(self):
        """Verifies OCI with secret and no GSA uses auth: token and requires secret."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "oci": {
                        "image": "docker.io/private/config:v1",
                        "gsm_secret_name": "dockerhub-secret",
                    }
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "oci")
        self.assertEqual(res["gsm_secret_name"], "dockerhub-secret")
        self.assertEqual(res["k8s_secret_name"], "dockerhub-secret")
        self.assertEqual(res["auth_type"], "token")
        self.assertTrue(res["requires_secret"])

    def test_structured_oci_public_without_auth(self):
        """Verifies public OCI image with no GSA and no secret."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "oci": {
                        "image": "us-docker.pkg.dev/public/repo:v1",
                    }
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "oci")
        self.assertEqual(res["auth_type"], "none")
        self.assertFalse(res["requires_secret"])

    def test_precedence_git_over_oci_when_both_present(self):
        """Verifies git configuration takes precedence over oci when both are declared."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/primary.git",
                        "gsm_secret_name": "git-secret",
                    },
                    "oci": {
                        "image": "us-docker.pkg.dev/fallback/repo:v1",
                        "gsm_secret_name": "oci-secret",
                    },
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "git")
        self.assertEqual(res["repo_url"], "https://gitlab.com/primary.git")
        self.assertEqual(res["gsm_secret_name"], "git-secret")
        self.assertEqual(res["k8s_secret_name"], "git-secret")

    def test_fallback_cluster_name_param(self):
        """Verifies fallback_cluster_name is used when cluster_name is missing from config."""
        config = {
            "cluster": {
                "primary_root_repo": {
                    "git": {"repo_url": "https://gitlab.com/repo.git"}
                }
            }
        }
        res = resolve_primary_root_repo(config, cluster_name="fallback-node-42")
        self.assertEqual(res["sync_dir"], "config/clusters/fallback-node-42")

    def test_resolve_git_with_gsm_auth_secret_object(self):
        """Verifies resolving git repo with structured gsm-auth-secret object."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "cluster-config-name": "custom-override",
                    "git": {
                        "repo-url": "https://gitlab.com/retail-edge/repo.git",
                        "branch": "main",
                        "gsm-auth-secret": {
                            "gsm-name": "es-git-creds",
                            "gsm-location": "global",
                            "k8s-name": "git-creds",
                            "k8s-namespace": "config-management-system",
                        },
                    },
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "git")
        self.assertEqual(res["repo_url"], "https://gitlab.com/retail-edge/repo.git")
        self.assertEqual(res["branch"], "main")
        self.assertEqual(res["sync_dir"], "config/clusters/custom-override")
        self.assertEqual(res["gsm_secret_name"], "es-git-creds")
        self.assertEqual(res["k8s_secret_name"], "git-creds")
        self.assertEqual(res["k8s_namespace"], "config-management-system")
        self.assertEqual(res["gsm_location"], "global")
        self.assertTrue(res["requires_secret"])
        self.assertEqual(res["auth_type"], "token")

    def test_resolve_git_with_regional_gsm_location(self):
        """Verifies resolving regional gsm-location."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/retail-edge/repo.git",
                        "gsm_auth_secret": {
                            "gsm_name": "regional-scm-creds",
                            "gsm_location": "us-west1",
                            "k8s_name": "scm-creds",
                        },
                    },
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["gsm_secret_name"], "regional-scm-creds")
        self.assertEqual(res["gsm_location"], "us-west1")
        self.assertEqual(res["k8s_secret_name"], "scm-creds")

    def test_resolve_git_with_flat_gsm_location(self):
        """Verifies resolving flat gsm_location on git repo."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/retail-edge/repo.git",
                        "gsm_secret_name": "flat-creds",
                        "gsm_location": "us-central1",
                    },
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["gsm_secret_name"], "flat-creds")
        self.assertEqual(res["gsm_location"], "us-central1")

    def test_resolve_oci_with_gsm_auth_secret_object(self):
        """Verifies resolving structured gsm-auth-secret on OCI repo."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "oci": {
                        "image": "ghcr.io/org/repo:v1",
                        "gsm-auth-secret": {
                            "gsm-name": "oci-reg-secret",
                            "gsm-location": "europe-west1",
                            "k8s-name": "k8s-oci-secret",
                        },
                    },
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "oci")
        self.assertEqual(res["gsm_secret_name"], "oci-reg-secret")
        self.assertEqual(res["gsm_location"], "europe-west1")
        self.assertEqual(res["k8s_secret_name"], "k8s-oci-secret")
        self.assertTrue(res["requires_secret"])
        self.assertEqual(res["auth_type"], "token")

    def test_resolve_oci_with_flat_gsm_location(self):
        """Verifies resolving flat gsm-location on OCI repo."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "oci": {
                        "image": "ghcr.io/org/repo:v1",
                        "gsm_secret_name": "flat-oci-secret",
                        "gsm-location": "us-east4",
                    },
                },
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["repo_type"], "oci")
        self.assertEqual(res["gsm_secret_name"], "flat-oci-secret")
        self.assertEqual(res["gsm_location"], "us-east4")
        self.assertTrue(res["requires_secret"])
        self.assertEqual(res["auth_type"], "token")

    def test_resolve_git_legacy_with_primary_root_repo_auth_secret(self):
        """Verifies legacy facts with gsm_secret_name and primary_root_repo_auth_secret."""
        config = {
            "cluster": {
                "cluster_name": "edge-01",
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/retail-edge/repo.git",
                        "gsm_secret_name": "es-git-creds",
                    },
                },
                "primary_root_repo_auth_secret": "git-creds",
            }
        }
        res = resolve_primary_root_repo(config)
        self.assertEqual(res["gsm_secret_name"], "es-git-creds")
        self.assertEqual(res["k8s_secret_name"], "git-creds")

    def test_extract_gsm_secret_info_compatibility(self):
        """Verifies extract_gsm_secret_info returns (gsm_secret_name, repo_type)."""
        git_cfg = {
            "cluster": {
                "primary_root_repo": {"git": {"gsm_secret_name": "git-sec"}}
            }
        }
        self.assertEqual(extract_gsm_secret_info(git_cfg), ("git-sec", "git"))

        git_structured = {
            "cluster": {
                "primary_root_repo": {
                    "git": {
                        "gsm-auth-secret": {"gsm-name": "structured-sec"}
                    }
                }
            }
        }
        self.assertEqual(extract_gsm_secret_info(git_structured), ("structured-sec", "git"))

        oci_cfg = {
            "cluster": {
                "primary_root_repo": {"oci": {"gsm_secret_name": "oci-sec"}}
            }
        }
        self.assertEqual(extract_gsm_secret_info(oci_cfg), ("oci-sec", "oci"))

        none_cfg = {"cluster": {}}
        self.assertEqual(extract_gsm_secret_info(none_cfg), (None, None))


class TestSecretPayloadResolution(unittest.TestCase):
    """Verifies decision matrix for resolve_secret_payload."""

    def test_invalid_payload_type(self):
        """Verifies non-dictionary payload fails validation."""
        for invalid in [None, "string", [1, 2], 123]:
            res = resolve_secret_payload(invalid)
            self.assertFalse(res["valid"])
            self.assertIn("not a valid JSON dictionary", res["failure_reason"])

    def test_git_payload_with_ssh_private_key(self):
        """Verifies git payload with ssh-privatekey selects auth: ssh."""
        payload = {"ssh-privatekey": "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END-----"}
        res = resolve_secret_payload(payload, repo_type="git")
        self.assertTrue(res["valid"])
        self.assertEqual(res["auth_type"], "ssh")
        self.assertIn("ssh-privatekey", res["secret_data"])

    def test_git_payload_with_token(self):
        """Verifies git payload with token selects auth: token."""
        payload = {"token": "glpat-secrettoken123"}
        res = resolve_secret_payload(payload, repo_type="git")
        self.assertTrue(res["valid"])
        self.assertEqual(res["auth_type"], "token")
        self.assertEqual(res["secret_data"]["token"], "glpat-secrettoken123")
        self.assertNotIn("username", res["secret_data"])

    def test_git_payload_with_token_and_username(self):
        """Verifies git payload with token and username populates both."""
        payload = {"username": "oauth2", "token": "glpat-secrettoken123"}
        res = resolve_secret_payload(payload, repo_type="git")
        self.assertTrue(res["valid"])
        self.assertEqual(res["auth_type"], "token")
        self.assertEqual(res["secret_data"]["username"], "oauth2")
        self.assertEqual(res["secret_data"]["token"], "glpat-secrettoken123")

    def test_git_payload_with_password_fallback(self):
        """Verifies git payload with password falls back to token field."""
        payload = {"username": "gituser", "password": "mypassword"}
        res = resolve_secret_payload(payload, repo_type="git")
        self.assertTrue(res["valid"])
        self.assertEqual(res["auth_type"], "token")
        self.assertEqual(res["secret_data"]["token"], "mypassword")

    def test_git_payload_missing_credentials(self):
        """Verifies git payload missing token, password, and ssh key fails."""
        payload = {"username": "onlyuser"}
        res = resolve_secret_payload(payload, repo_type="git")
        self.assertFalse(res["valid"])
        self.assertIn(
            "must contain 'token', 'password', or 'ssh-privatekey'",
            res["failure_reason"],
        )

    def test_oci_payload_with_username_and_password(self):
        """Verifies OCI payload with username and password succeeds."""
        payload = {"username": "_json_key", "password": '{"private_key": "abc"}'}
        res = resolve_secret_payload(payload, repo_type="oci")
        self.assertTrue(res["valid"])
        self.assertEqual(res["auth_type"], "token")
        self.assertEqual(res["secret_data"]["username"], "_json_key")
        self.assertEqual(res["secret_data"]["password"], '{"private_key": "abc"}')

    def test_oci_payload_missing_password(self):
        """Verifies OCI payload missing password fails."""
        payload = {"username": "admin"}
        res = resolve_secret_payload(payload, repo_type="oci")
        self.assertFalse(res["valid"])
        self.assertIn("must contain 'username' and either 'password' or 'token'", res["failure_reason"])

    def test_oci_payload_with_token_fallback(self):
        """Verifies OCI payload accepts 'token' field as password."""
        payload = {"username": "oauth2", "token": "glpat-xyz123"}
        res = resolve_secret_payload(payload, repo_type="oci")
        self.assertTrue(res["valid"])
        self.assertEqual(res["auth_type"], "token")
        self.assertEqual(res["secret_data"]["username"], "oauth2")
        self.assertEqual(res["secret_data"]["password"], "glpat-xyz123")

    def test_unsupported_repo_type(self):
        """Verifies unsupported repository type fails."""
        res = resolve_secret_payload({"token": "abc"}, repo_type="svn")
        self.assertFalse(res["valid"])
        self.assertIn("Unsupported repository type", res["failure_reason"])


class TestGdcConfigSyncLookupPlugin(unittest.TestCase):
    """Verifies LookupModule invocation behavior within Ansible workflows."""

    def setUp(self):
        self.plugin = LookupModule()

    def test_lookup_resolves_machine_config_from_terms(self):
        """Verifies LookupModule resolving machine_config passed via terms."""
        mc = {
            "cluster": {
                "cluster_name": "lookup-cluster",
                "primary_root_repo": {
                    "git": {"repo_url": "https://gitlab.com/test/repo.git", "branch": "prod"}
                },
            }
        }
        res = self.plugin.run([mc])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["repo_type"], "git")
        self.assertEqual(res[0]["branch"], "prod")
        self.assertEqual(res[0]["sync_dir"], "config/clusters/lookup-cluster")

    def test_lookup_resolves_machine_config_from_variables(self):
        """Verifies LookupModule reading machine_config and target_cluster_name from variables."""
        variables = {
            "machine_config": {
                "cluster": {
                    "primary_root_repo": {
                        "oci": {"image": "us-docker.pkg.dev/repo/img:v1", "gsa": "sa-test"}
                    }
                }
            },
            "target_cluster_name": "var-cluster",
        }
        res = self.plugin.run([], variables=variables)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["repo_type"], "oci")
        self.assertEqual(res[0]["auth_type"], "gcpserviceaccount")
        self.assertEqual(res[0]["sync_dir"], "config/clusters/var-cluster")

    def test_lookup_resolves_secret_payload_mode(self):
        """Verifies LookupModule invoked in secret_payload mode."""
        payload = {"token": "secret-token", "username": "bot"}
        res = self.plugin.run(["secret_payload", payload], repo_type="git")
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0]["valid"])
        self.assertEqual(res[0]["auth_type"], "token")
        self.assertEqual(res[0]["secret_data"]["username"], "bot")


if __name__ == "__main__":
    unittest.main()
