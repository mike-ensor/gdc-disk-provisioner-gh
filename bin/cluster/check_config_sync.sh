#!/usr/bin/env bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
#
# Audits ConfigSync RootSync and RepoSync operational readiness.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/../../src/ansible/roles/post_cluster/files/check_config_sync_operational.py"

if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
    PYTHON_SCRIPT="/var/gdc-install/playbooks/bootstrap/roles/post_cluster/files/check_config_sync_operational.py"
fi

if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
    echo "[!] ERROR: Unable to locate check_config_sync_operational.py" >&2
    exit 1
fi

exec python3 "${PYTHON_SCRIPT}" "$@"
