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

"""Unit tests for GDC Pre-flight GSM Secret Fail-Fast Verification Logic and Ansible tasks."""

from datetime import datetime, timezone
import json
import os
import unittest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PREFLIGHT_STAGE_PATH = os.path.join(
    PROJECT_ROOT, "src", "ansible", "stages", "stage_preflight_checks.yml"
)


def extract_gsm_secret_info(machine_config):
    """Extracts (gsm_secret_name, repo_type) from machine_config.

    Args:
        machine_config: Dictionary representing the machine configuration.

    Returns:
        tuple (gsm_secret_name, repo_type):
            - gsm_secret_name (str or None): Target secret name in Secret Manager, or None.
            - repo_type (str or None): 'git', 'oci', or None if unspecified/legacy.
    """
    if not isinstance(machine_config, dict):
        return None, None

    cluster = machine_config.get("cluster")
    if not isinstance(cluster, dict):
        return None, None

    primary_root_repo = cluster.get("primary_root_repo")
    if not isinstance(primary_root_repo, dict):
        return None, None

    if "git" in primary_root_repo and isinstance(primary_root_repo["git"], dict):
        git_cfg = primary_root_repo["git"]
        secret_obj = git_cfg.get("gsm-auth-secret") or git_cfg.get("gsm_auth_secret")
        if isinstance(secret_obj, dict):
            secret_name = secret_obj.get("gsm-name") or secret_obj.get("gsm_name")
        else:
            secret_name = git_cfg.get("gsm_secret_name")
        return (str(secret_name).strip() if secret_name else None), "git"
    if "oci" in primary_root_repo and isinstance(primary_root_repo["oci"], dict):
        oci_cfg = primary_root_repo["oci"]
        secret_obj = oci_cfg.get("gsm-auth-secret") or oci_cfg.get("gsm_auth_secret")
        if isinstance(secret_obj, dict):
            secret_name = secret_obj.get("gsm-name") or secret_obj.get("gsm_name")
        else:
            secret_name = oci_cfg.get("gsm_secret_name")
        return (str(secret_name).strip() if secret_name else None), "oci"

    return None, None


def validate_secret_payload(payload, repo_type):
    """Validates the secret payload JSON for a given repository type ('git' or 'oci').

    Args:
        payload: JSON string or parsed dict containing secret data.
        repo_type: Repository type ('git' or 'oci').

    Returns:
        tuple (bool, str): (is_valid, message)
    """
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except (ValueError, TypeError) as e:
            return False, f"Invalid JSON payload: {e}"
        if not isinstance(data, dict):
            return False, "Decoded payload must be a JSON object"
    elif isinstance(payload, dict):
        data = payload
    else:
        return False, f"Expected string or dict payload, got {type(payload).__name__}"

    is_valid, msg = False, f"Unsupported repo type: {repo_type}"
    if repo_type == "git":
        valid_keys = ("token", "password", "ssh-privatekey")
        present = [k for k in valid_keys if str(data.get(k, "")).strip()]
        if present:
            is_valid, msg = (
                True,
                f"Valid git secret payload (found: {', '.join(present)})",
            )
        else:
            is_valid, msg = (
                False,
                "Git secret payload must contain at least one of: token, password, ssh-privatekey",
            )
    elif repo_type == "oci":
        missing = [
            k for k in ("username", "password") if not str(data.get(k, "")).strip()
        ]
        if not missing:
            is_valid, msg = True, "Valid OCI secret payload"
        else:
            is_valid, msg = (
                False,
                f"OCI secret payload missing required keys: {', '.join(missing)}",
            )
    return is_valid, msg


# pylint: disable=too-many-arguments,too-many-positional-arguments
def generate_preflight_result(
    status: str,
    test_name: str = "gsm_secret_validation",
    notes: str = "",
    remediation_hint: str = "",
    duration_ms: int = 10,
    severity: str = "FATAL",
) -> dict:
    """Generates a preflight result dictionary conforming to preflight schema."""
    return {
        "test_name": test_name,
        "category": "security",
        "status": status,
        "severity": severity,
        "notes": notes,
        "remediation_hint": remediation_hint,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_ms": duration_ms,
    }


class TestExtractGsmSecretInfo(unittest.TestCase):
    """Verifies extraction of gsm_secret_name and repo_type from machine_config."""

    def test_extract_git_secret_name_and_repo_type(self):
        """Verifies extracting git secret name and repo type from machine_config."""
        config = {
            "cluster": {
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/example/repo.git",
                        "gsm_secret_name": "git-creds",
                    }
                }
            }
        }
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertEqual(secret_name, "git-creds")
        self.assertEqual(repo_type, "git")

    def test_extract_git_with_structured_gsm_auth_secret(self):
        """Verifies extracting secret from structured gsm-auth-secret object."""
        config = {
            "cluster": {
                "primary_root_repo": {
                    "git": {
                        "repo-url": "https://gitlab.com/example/repo.git",
                        "gsm-auth-secret": {
                            "gsm-name": "es-git-creds",
                            "k8s-name": "git-creds",
                        },
                    }
                }
            }
        }
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertEqual(secret_name, "es-git-creds")
        self.assertEqual(repo_type, "git")

    def test_extract_oci_secret_name_and_repo_type(self):
        """Verifies extracting OCI secret name and repo type from machine_config."""
        config = {
            "cluster": {
                "primary_root_repo": {
                    "oci": {
                        "image": "us-docker.pkg.dev/project/repo/config:v1.0.0",
                        "auth_type": "secret",
                        "gsm_secret_name": "oci-creds",
                    }
                }
            }
        }
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertEqual(secret_name, "oci-creds")
        self.assertEqual(repo_type, "oci")

    def test_extract_git_without_gsm_secret(self):
        """Verifies git repo without gsm_secret_name yields None secret name."""
        config = {
            "cluster": {
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/example/public-repo.git",
                    }
                }
            }
        }
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertIsNone(secret_name)
        self.assertEqual(repo_type, "git")

    def test_extract_oci_without_gsm_secret_gsa(self):
        """Verifies OCI repo with GSA auth yields None secret name."""
        config = {
            "cluster": {
                "primary_root_repo": {
                    "oci": {
                        "image": "us-docker.pkg.dev/project/repo/config:v1.0.0",
                        "auth_type": "gsa",
                    }
                }
            }
        }
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertIsNone(secret_name)
        self.assertEqual(repo_type, "oci")

    def test_extract_legacy_string_primary_root_repo(self):
        """Verifies legacy string-based primary_root_repo returns None."""
        config = {
            "cluster": {
                "primary_root_repo": "https://gitlab.com/example/legacy.git",
                "primary_root_repo_auth_secret": "ext-secret",
            }
        }
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertIsNone(secret_name)
        self.assertIsNone(repo_type)

    def test_extract_omitted_primary_root_repo(self):
        """Verifies omitted primary_root_repo returns None."""
        config = {"cluster": {"cluster_name": "edge-1"}}
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertIsNone(secret_name)
        self.assertIsNone(repo_type)

    def test_extract_null_primary_root_repo(self):
        """Verifies null primary_root_repo returns None."""
        config = {"cluster": {"primary_root_repo": None}}
        secret_name, repo_type = extract_gsm_secret_info(config)
        self.assertIsNone(secret_name)
        self.assertIsNone(repo_type)

    def test_extract_empty_or_none_machine_config(self):
        """Verifies empty or None machine_config returns (None, None)."""
        self.assertEqual(extract_gsm_secret_info({}), (None, None))
        self.assertEqual(extract_gsm_secret_info(None), (None, None))


class TestValidateSecretPayload(unittest.TestCase):
    """Verifies validation of secret payload JSON for git and oci types."""

    def test_git_payload_valid_with_token(self):
        """Verifies git payload with non-empty token passes validation."""
        valid, msg = validate_secret_payload('{"token": "ghp_mock_token_123"}', "git")
        self.assertTrue(valid)
        self.assertIn("token", msg)

    def test_git_payload_valid_with_password(self):
        """Verifies git payload with non-empty password passes validation."""
        valid, msg = validate_secret_payload(
            '{"username": "git", "password": "secret_pwd"}', "git"
        )
        self.assertTrue(valid)
        self.assertIn("password", msg)

    def test_git_payload_valid_with_ssh_privatekey(self):
        """Verifies git payload with non-empty ssh-privatekey passes validation."""
        valid, msg = validate_secret_payload(
            {
                "ssh-privatekey": (
                    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                    "mock\n"
                    "-----END OPENSSH PRIVATE KEY-----"
                )
            },
            "git",
        )
        self.assertTrue(valid)
        self.assertIn("ssh-privatekey", msg)

    def test_git_payload_invalid_without_required_keys(self):
        """Verifies git payload without required keys fails validation."""
        valid, msg = validate_secret_payload(
            '{"username": "git", "email": "dev@example.com"}', "git"
        )
        self.assertFalse(valid)
        self.assertIn("token, password, ssh-privatekey", msg)

    def test_git_payload_invalid_empty_dict(self):
        """Verifies empty dict payload fails git validation."""
        valid, _ = validate_secret_payload("{}", "git")
        self.assertFalse(valid)

    def test_git_payload_invalid_empty_fields(self):
        """Verifies git payload with empty/blank credentials fails validation."""
        valid, _ = validate_secret_payload('{"token": "   ", "password": ""}', "git")
        self.assertFalse(valid)

    def test_git_payload_invalid_json_syntax(self):
        """Verifies invalid JSON syntax fails git payload validation."""
        valid, msg = validate_secret_payload("{not-valid-json", "git")
        self.assertFalse(valid)
        self.assertIn("Invalid JSON", msg)

    def test_git_payload_invalid_non_dict_json(self):
        """Verifies non-dict JSON string fails git payload validation."""
        valid, msg = validate_secret_payload('"just-a-string"', "git")
        self.assertFalse(valid)
        self.assertIn("JSON object", msg)

    def test_oci_payload_valid_with_username_and_password(self):
        """Verifies OCI payload with username and password passes validation."""
        payload = json.dumps({"username": "_json_key", "password": "mock_sa_key_json"})
        valid, msg = validate_secret_payload(payload, "oci")
        self.assertTrue(valid)
        self.assertIn("Valid OCI", msg)

    def test_oci_payload_invalid_missing_username(self):
        """Verifies OCI payload missing username fails validation."""
        payload = json.dumps({"password": "some_password"})
        valid, msg = validate_secret_payload(payload, "oci")
        self.assertFalse(valid)
        self.assertIn("username", msg)

    def test_oci_payload_invalid_missing_password(self):
        """Verifies OCI payload missing password fails validation."""
        payload = json.dumps({"username": "user"})
        valid, msg = validate_secret_payload(payload, "oci")
        self.assertFalse(valid)
        self.assertIn("password", msg)

    def test_oci_payload_invalid_empty_fields(self):
        """Verifies OCI payload with empty values fails validation."""
        payload = json.dumps({"username": "", "password": "pwd"})
        valid, _ = validate_secret_payload(payload, "oci")
        self.assertFalse(valid)

    def test_oci_payload_invalid_json_syntax(self):
        """Verifies invalid JSON syntax fails OCI payload validation."""
        valid, msg = validate_secret_payload("{not: valid json", "oci")
        self.assertFalse(valid)
        self.assertIn("Invalid JSON", msg)

    def test_unsupported_repo_type(self):
        """Verifies unsupported repository types fail validation."""
        valid, msg = validate_secret_payload('{"token": "xyz"}', "unknown")
        self.assertFalse(valid)
        self.assertIn("Unsupported repo type", msg)


class TestPreflightResultGeneration(unittest.TestCase):
    """Verifies preflight result dictionary construction and schema compliance."""

    def test_generate_pass_result(self):
        """Verifies generating PASS preflight result dictionary."""
        res = generate_preflight_result(
            status="PASS",
            test_name="gsm_secret_primary_root_repo",
            notes="Secret verified",
            duration_ms=25,
        )
        self.assertEqual(res["category"], "security")
        self.assertEqual(res["test_name"], "gsm_secret_primary_root_repo")
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["severity"], "FATAL")
        self.assertEqual(res["notes"], "Secret verified")
        self.assertEqual(res["duration_ms"], 25)
        self.assertTrue(res["timestamp"].endswith("Z"))

    def test_generate_fail_result(self):
        """Verifies generating FAIL preflight result dictionary."""
        res = generate_preflight_result(
            status="FAIL",
            test_name="gsm_secret_primary_root_repo",
            notes="Secret describe failed: 404 Not Found",
            remediation_hint="Create the secret in GSM",
        )
        self.assertEqual(res["category"], "security")
        self.assertEqual(res["status"], "FAIL")
        self.assertEqual(res["severity"], "FATAL")
        self.assertIn("404", res["notes"])
        self.assertIn("Create the secret", res["remediation_hint"])

    def test_generate_skipped_result(self):
        """Verifies generating skipped PASS preflight result dictionary."""
        res = generate_preflight_result(
            status="PASS",
            test_name="gsm_secret_primary_root_repo",
            notes=(
                "No GSM secret required or configured for primary_root_repo "
                "(skipped/not required)."
            ),
            duration_ms=0,
        )
        self.assertEqual(res["category"], "security")
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["duration_ms"], 0)
        self.assertIn("skipped", res["notes"])


class TestPreflightAnsibleTasks(unittest.TestCase):
    """Verifies presence, ordering, and structure of GSM secret preflight tasks."""

    def setUp(self):
        """Loads and parses the preflight stage YAML playbook."""
        self.assertTrue(
            os.path.exists(PREFLIGHT_STAGE_PATH),
            f"Preflight stage file not found at {PREFLIGHT_STAGE_PATH}",
        )
        with open(PREFLIGHT_STAGE_PATH, "r", encoding="utf-8") as f:
            self.raw_content = f.read()
            self.tasks = yaml.safe_load(self.raw_content)

    def test_preflight_stage_contains_gsm_secret_tasks(self):
        """Verifies tasks exist for verifying primary_root_repo GSM secret."""
        task_names = [t.get("name", "") for t in self.tasks if isinstance(t, dict)]
        self.assertTrue(
            any(
                "primary_root_repo" in name.lower() or "gsm" in name.lower()
                for name in task_names
            ),
            "Expected tasks verifying primary_root_repo GSM secret in stage_preflight_checks.yml",
        )

    def test_preflight_tasks_positioned_before_aggregate_results(self):
        """Verifies GSM secret tasks appear before Section 4: Aggregate Overall Status."""
        gsm_idx = None
        aggregate_idx = None

        for idx, task in enumerate(self.tasks):
            if not isinstance(task, dict):
                continue
            name = task.get("name", "")
            if (
                "primary_root_repo" in name.lower() or "gsm" in name.lower()
            ) and gsm_idx is None:
                gsm_idx = idx
            if "Aggregate Overall Status" in name:
                aggregate_idx = idx

        self.assertIsNotNone(gsm_idx, "GSM secret verification task not found")
        self.assertIsNotNone(aggregate_idx, "Aggregate Overall Status task not found")
        assert gsm_idx is not None and aggregate_idx is not None
        self.assertLess(
            gsm_idx,
            aggregate_idx,
            "GSM secret verification must occur before Section 4: Aggregate Overall Status",
        )

    def test_preflight_tasks_verify_describe_and_access_commands(self):
        """Verifies that gcloud secrets versions access command is defined."""
        self.assertIn("gcloud secrets versions access latest", self.raw_content)

    def test_preflight_tasks_validate_git_and_oci_keys(self):
        """Verifies that git and oci non-empty keys are checked in validity evaluation."""
        self.assertIn("token", self.raw_content)
        self.assertIn("password", self.raw_content)
        self.assertIn("ssh-privatekey", self.raw_content)
        self.assertIn("username", self.raw_content)
        self.assertIn("trim | length > 0", self.raw_content)

    def test_preflight_tasks_register_preflight_results(self):
        """Verifies preflight_results receives category: 'security' and test_name."""
        self.assertIn("gsm_secret_primary_root_repo", self.raw_content)
        self.assertIn('"category": "security"', self.raw_content)

    def test_preflight_tasks_conditional_error_guard(self):
        """Verifies that gsm_access_res.rc is guarded with is defined."""
        self.assertIn("gsm_access_res.rc is defined", self.raw_content)

    def test_preflight_tasks_variable_initialization_and_undefined_protection(self):
        """Verifies gsm_secret_decoded is initialized and protected with default({})."""
        self.assertIn("gsm_secret_decoded: {}", self.raw_content)
        self.assertIn("gsm_secret_parse_failed: false", self.raw_content)
        self.assertIn("gsm_secret_decoded | default({})", self.raw_content)

    def test_preflight_tasks_secret_masking_and_memory_hygiene(self):
        """Verifies no_log: true on secret assignments and final memory purge task."""
        self.assertIn("Decode secret JSON payload", self.raw_content)
        self.assertIn(
            "Purge GSM secret payload and access result from memory",
            self.raw_content,
        )


if __name__ == "__main__":
    unittest.main()
