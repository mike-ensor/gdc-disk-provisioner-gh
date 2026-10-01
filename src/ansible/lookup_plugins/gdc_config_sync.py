# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Ansible lookup plugin for resolving ConfigSync and primary_root_repo configurations."""

import os
import sys

# Ensure plugin directory is on sys.path for local module import
PLUGIN_DIR = os.path.dirname(__file__)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# pylint: disable=wrong-import-position,wrong-import-order
from ansible.plugins.lookup import LookupBase
from gdc_config_sync_resolver import (
    resolve_primary_root_repo,
    resolve_secret_payload,
)


class LookupModule(LookupBase):
    """Lookup plugin providing resolution for primary_root_repo and GSM secret payloads."""

    def run(self, terms, variables=None, **kwargs):  # type: ignore[override]
        """Executes lookup resolution for repo configuration or secret payloads."""
        # Mode 1: Secret Payload resolution & validation
        if terms and str(terms[0]).lower() in ("secret", "secret_payload"):
            payload = terms[1] if len(terms) > 1 else kwargs.get("payload", {})
            repo_type = kwargs.get("repo_type") or (terms[2] if len(terms) > 2 else "git")
            return [resolve_secret_payload(payload, repo_type=repo_type)]

        # Mode 2: primary_root_repo configuration resolution
        cfg = None
        if terms and terms[0] not in ("repo", "root_repo"):
            cfg = terms[0]
        elif variables and "machine_config" in variables:
            cfg = variables.get("machine_config")

        cluster_name = kwargs.get("cluster_name")
        if not cluster_name and variables:
            cluster_name = variables.get("target_cluster_name") or variables.get("cluster_name", "")

        return [resolve_primary_root_repo(cfg, cluster_name=str(cluster_name or "").strip())]
