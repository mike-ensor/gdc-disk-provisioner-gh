# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Pure-Python decision matrix and resolution logic for GDC ConfigSync and primary_root_repo."""

from typing import Any, Dict, Optional, Tuple


def _clean_str(value: Any) -> str:
    """Return stripped string or empty string if None or non-string."""
    if value is None:
        return ""
    return str(value).strip()


def _resolve_git_repo(
    git_cfg: Dict[str, Any],
    sync_dir: str,
    legacy_auth_secret: str,
) -> Dict[str, Any]:
    """Resolves a structured Git primary_root_repo configuration."""
    repo_url = _clean_str(git_cfg.get("repo-url")) or _clean_str(git_cfg.get("repo_url"))
    branch = _clean_str(git_cfg.get("branch")) or "main"

    # Check for structured gsm-auth-secret object (or snake_case/alias)
    secret_obj = (
        git_cfg.get("gsm-auth-secret")
        or git_cfg.get("gsm_auth_secret")
        or git_cfg.get("gsm-git-creds-secret")
        or git_cfg.get("gsm_git_creds_secret")
    )

    if isinstance(secret_obj, dict):
        gsm_secret_name = _clean_str(secret_obj.get("gsm-name")) or _clean_str(secret_obj.get("gsm_name"))
        gsm_location = (
            _clean_str(secret_obj.get("gsm-location"))
            or _clean_str(secret_obj.get("gsm_location"))
            or _clean_str(git_cfg.get("gsm_location"))
            or _clean_str(git_cfg.get("gsm-location"))
            or "global"
        )
        k8s_secret_name = (
            _clean_str(secret_obj.get("k8s-name"))
            or _clean_str(secret_obj.get("k8s_name"))
            or legacy_auth_secret
            or gsm_secret_name
        )
        k8s_namespace = (
            _clean_str(secret_obj.get("k8s-namespace"))
            or _clean_str(secret_obj.get("k8s_namespace"))
            or "config-management-system"
        )
    else:
        gsm_secret_name = (
            _clean_str(git_cfg.get("gsm_secret_name"))
            or _clean_str(git_cfg.get("gsm-secret-name"))
            or legacy_auth_secret
        )
        gsm_location = (
            _clean_str(git_cfg.get("gsm_location"))
            or _clean_str(git_cfg.get("gsm-location"))
            or "global"
        )
        k8s_secret_name = legacy_auth_secret or gsm_secret_name
        k8s_namespace = "config-management-system"

    has_secret = bool(gsm_secret_name)

    return {
        "repo_type": "git",
        "repo_url": repo_url,
        "branch": branch,
        "sync_dir": sync_dir,
        "gsm_secret_name": gsm_secret_name,
        "k8s_secret_name": k8s_secret_name,
        "k8s_namespace": k8s_namespace,
        "gsm_location": gsm_location,
        "oci_gsa": "",
        "requires_secret": has_secret,
        "auth_type": "token" if has_secret else "none",
    }


def _resolve_oci_repo(
    oci_cfg: Dict[str, Any],
    sync_dir: str,
    legacy_auth_secret: str,
) -> Dict[str, Any]:
    """Resolves a structured OCI primary_root_repo configuration."""
    image = _clean_str(oci_cfg.get("image"))
    oci_gsa = _clean_str(oci_cfg.get("gsa"))

    secret_obj = oci_cfg.get("gsm-auth-secret") or oci_cfg.get("gsm_auth_secret")
    if isinstance(secret_obj, dict):
        gsm_secret_name = _clean_str(secret_obj.get("gsm-name")) or _clean_str(secret_obj.get("gsm_name"))
        gsm_location = (
            _clean_str(secret_obj.get("gsm-location"))
            or _clean_str(secret_obj.get("gsm_location"))
            or _clean_str(oci_cfg.get("gsm_location"))
            or _clean_str(oci_cfg.get("gsm-location"))
            or "global"
        )
        k8s_secret_name = (
            _clean_str(secret_obj.get("k8s-name"))
            or _clean_str(secret_obj.get("k8s_name"))
            or legacy_auth_secret
            or gsm_secret_name
        )
        k8s_namespace = (
            _clean_str(secret_obj.get("k8s-namespace"))
            or _clean_str(secret_obj.get("k8s_namespace"))
            or "config-management-system"
        )
    else:
        gsm_secret_name = (
            _clean_str(oci_cfg.get("gsm_secret_name"))
            or _clean_str(oci_cfg.get("gsm-secret-name"))
            or legacy_auth_secret
        )
        gsm_location = (
            _clean_str(oci_cfg.get("gsm_location"))
            or _clean_str(oci_cfg.get("gsm-location"))
            or "global"
        )
        k8s_secret_name = legacy_auth_secret or gsm_secret_name
        k8s_namespace = "config-management-system"

    if oci_gsa:
        return {
            "repo_type": "oci",
            "repo_url": image,
            "branch": "",
            "sync_dir": sync_dir,
            "gsm_secret_name": "",
            "k8s_secret_name": "",
            "k8s_namespace": k8s_namespace,
            "gsm_location": "global",
            "oci_gsa": oci_gsa,
            "requires_secret": False,
            "auth_type": "gcpserviceaccount",
        }

    has_secret = bool(gsm_secret_name)
    return {
        "repo_type": "oci",
        "repo_url": image,
        "branch": "",
        "sync_dir": sync_dir,
        "gsm_secret_name": gsm_secret_name,
        "k8s_secret_name": k8s_secret_name,
        "k8s_namespace": k8s_namespace,
        "gsm_location": gsm_location,
        "oci_gsa": "",
        "requires_secret": has_secret,
        "auth_type": "token" if has_secret else "none",
    }


def _resolve_legacy_string_repo(
    repo_str: str,
    effective_cluster_name: str,
    legacy_auth_secret: str,
) -> Dict[str, Any]:
    """Resolves legacy string primary_root_repo formats."""
    clean_repo = repo_str.strip()
    if not clean_repo or clean_repo == "none":
        return _empty_repo_result()

    sync_dir = f"config/clusters/{effective_cluster_name}" if effective_cluster_name else ""
    has_secret = bool(legacy_auth_secret)

    if clean_repo.endswith(".git") or clean_repo.startswith("http"):
        return {
            "repo_type": "git",
            "repo_url": clean_repo,
            "branch": "main",
            "sync_dir": sync_dir,
            "gsm_secret_name": legacy_auth_secret,
            "k8s_secret_name": legacy_auth_secret,
            "k8s_namespace": "config-management-system",
            "gsm_location": "global",
            "oci_gsa": "",
            "requires_secret": has_secret,
            "auth_type": "token" if has_secret else "none",
        }

    return {
        "repo_type": "oci",
        "repo_url": clean_repo,
        "branch": "",
        "sync_dir": sync_dir,
        "gsm_secret_name": legacy_auth_secret,
        "k8s_secret_name": legacy_auth_secret,
        "k8s_namespace": "config-management-system",
        "gsm_location": "global",
        "oci_gsa": "",
        "requires_secret": has_secret,
        "auth_type": "token" if has_secret else "none",
    }


def _empty_repo_result() -> Dict[str, Any]:
    """Returns default empty configuration when repository is unset."""
    return {
        "repo_type": "none",
        "repo_url": "",
        "branch": "",
        "sync_dir": "",
        "gsm_secret_name": "",
        "k8s_secret_name": "",
        "k8s_namespace": "config-management-system",
        "gsm_location": "global",
        "oci_gsa": "",
        "requires_secret": False,
        "auth_type": "none",
    }


def _resolve_dict_repo(
    primary_repo: Dict[str, Any],
    effective_cluster: str,
    legacy_secret: str,
) -> Dict[str, Any]:
    """Resolves a dictionary primary_root_repo configuration."""
    override_dir = (
        _clean_str(primary_repo.get("cluster-config-name"))
        or _clean_str(primary_repo.get("cluster_config_name"))
        or _clean_str(primary_repo.get("oci", {}).get("cluster-config-name") if isinstance(primary_repo.get("oci"), dict) else None)
        or _clean_str(primary_repo.get("oci", {}).get("cluster_config_name") if isinstance(primary_repo.get("oci"), dict) else None)
        or _clean_str(primary_repo.get("git", {}).get("cluster-config-name") if isinstance(primary_repo.get("git"), dict) else None)
        or _clean_str(primary_repo.get("git", {}).get("cluster_config_name") if isinstance(primary_repo.get("git"), dict) else None)
    )
    explicit_sync_dir = (
        _clean_str(primary_repo.get("root-sync-dir"))
        or _clean_str(primary_repo.get("root_sync_dir"))
        or _clean_str(primary_repo.get("oci", {}).get("dir-path") if isinstance(primary_repo.get("oci"), dict) else None)
        or _clean_str(primary_repo.get("oci", {}).get("dir_path") if isinstance(primary_repo.get("oci"), dict) else None)
        or _clean_str(primary_repo.get("git", {}).get("dir-path") if isinstance(primary_repo.get("git"), dict) else None)
        or _clean_str(primary_repo.get("git", {}).get("dir_path") if isinstance(primary_repo.get("git"), dict) else None)
    )
    target_dir = override_dir if override_dir else effective_cluster
    sync_dir = explicit_sync_dir if explicit_sync_dir else (f"config/clusters/{target_dir}" if target_dir else "")

    if isinstance(primary_repo.get("git"), dict):
        return _resolve_git_repo(primary_repo["git"], sync_dir, legacy_secret)
    if isinstance(primary_repo.get("oci"), dict):
        return _resolve_oci_repo(primary_repo["oci"], sync_dir, legacy_secret)
    res = _empty_repo_result()
    res["sync_dir"] = sync_dir
    return res


def resolve_primary_root_repo(
    machine_config: Optional[Dict[str, Any]],
    cluster_name: str = "",
) -> Dict[str, Any]:
    """Resolves primary_root_repo settings from machine_config into normalized facts.

    Decision Matrix Rules:
    1. Precedence: 'git' configuration takes precedence over 'oci' when both are provided.
    2. Cluster Sync Dir: Defaults to 'config/clusters/<cluster_name>', overridable via
       'primary_root_repo.cluster_config_name'.
    3. Secret Name:
       - For Git: 'git.gsm_secret_name'.
       - For OCI: 'oci.gsm_secret_name' unless 'oci.gsa' is defined.
       - Legacy: fallback to 'primary_root_repo_auth_secret'.
    4. OCI Workload Identity: If 'oci.gsa' is configured, 'auth_type' is 'gcpserviceaccount',
       and secret lookup is suppressed.
    5. Auth Type:
       - Git with secret: 'token' (default, updated to 'ssh' if ssh key present).
       - Git without secret: 'none'.
       - OCI with GSA: 'gcpserviceaccount'.
       - OCI with secret: 'token'.
       - OCI without secret or GSA: 'none'.
    """
    if not isinstance(machine_config, dict):
        return _empty_repo_result()

    cluster = machine_config.get("cluster")
    if not isinstance(cluster, dict):
        return _empty_repo_result()

    cfg_cluster_name = _clean_str(cluster.get("cluster_name"))
    effective_cluster = cfg_cluster_name if cfg_cluster_name else _clean_str(cluster_name)
    primary_repo = cluster.get("primary_root_repo")
    legacy_secret = _clean_str(cluster.get("primary_root_repo_auth_secret"))

    if isinstance(primary_repo, dict):
        return _resolve_dict_repo(primary_repo, effective_cluster, legacy_secret)

    if isinstance(primary_repo, str):
        return _resolve_legacy_string_repo(primary_repo, effective_cluster, legacy_secret)

    return _empty_repo_result()


def _resolve_git_secret_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and formats Git credentials from secret payload."""
    ssh_key = _clean_str(payload.get("ssh-privatekey"))
    if ssh_key:
        return {
            "valid": True,
            "secret_data": {"ssh-privatekey": payload["ssh-privatekey"]},
            "auth_type": "ssh",
            "failure_reason": "",
        }

    token = _clean_str(payload.get("token")) or _clean_str(payload.get("password"))
    if token:
        secret_data: Dict[str, str] = {"token": token}
        username = _clean_str(payload.get("username"))
        if username:
            secret_data["username"] = username
        return {
            "valid": True,
            "secret_data": secret_data,
            "auth_type": "token",
            "failure_reason": "",
        }

    return {
        "valid": False,
        "secret_data": {},
        "auth_type": "none",
        "failure_reason": (
            "Git secret payload must contain 'token', 'password', or 'ssh-privatekey'."
        ),
    }


def _resolve_oci_secret_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and formats OCI credentials from secret payload."""
    username = _clean_str(payload.get("username"))
    password = _clean_str(payload.get("password")) or _clean_str(payload.get("token"))
    if username and password:
        return {
            "valid": True,
            "secret_data": {"username": username, "password": password},
            "auth_type": "token",
            "failure_reason": "",
        }

    return {
        "valid": False,
        "secret_data": {},
        "auth_type": "none",
        "failure_reason": "OCI secret payload must contain 'username' and either 'password' or 'token'.",
    }


def resolve_secret_payload(
    payload: Any,
    repo_type: str = "git",
) -> Dict[str, Any]:
    """Validates and extracts credential key-values from Secret Manager payload."""
    if not isinstance(payload, dict):
        return {
            "valid": False,
            "secret_data": {},
            "auth_type": "none",
            "failure_reason": "GSM secret payload is not a valid JSON dictionary.",
        }

    clean_type = _clean_str(repo_type).lower()
    if clean_type == "git":
        return _resolve_git_secret_payload(payload)
    if clean_type == "oci":
        return _resolve_oci_secret_payload(payload)

    return {
        "valid": False,
        "secret_data": {},
        "auth_type": "none",
        "failure_reason": f"Unsupported repository type '{repo_type}'.",
    }


def extract_gsm_secret_info(
    machine_config: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """Helper returning (gsm_secret_name, repo_type) for pre-flight backward compatibility."""
    resolved = resolve_primary_root_repo(machine_config)
    repo_type = resolved["repo_type"]
    gsm_secret_name = resolved["gsm_secret_name"]
    return (gsm_secret_name if gsm_secret_name else None), (repo_type if repo_type != "none" else None)
