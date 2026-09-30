# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Ansible lookup plugin for dynamic GDC stage evaluation."""

import os
import sys

# Ensure plugin directory is on sys.path for local module import
PLUGIN_DIR = os.path.dirname(__file__)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# pylint: disable=wrong-import-position,wrong-import-order
from ansible.plugins.lookup import LookupBase
from gdc_state_machine import get_current_stage


class LookupModule(LookupBase):
    """Lookup plugin providing on-demand current GDC stage."""

    def run(self, terms, variables=None, **kwargs):
        state_dir = kwargs.get("state_dir", "/var/gdc-install/state")
        fallback_config = kwargs.get("fallback_config", "/etc/gdc/fallback-config.json")
        fstab_path = kwargs.get("fstab_path", "/etc/fstab")

        stage = get_current_stage(
            state_dir=state_dir,
            fallback_config_path=fallback_config,
            fstab_path=fstab_path,
        )
        return [stage.value]
