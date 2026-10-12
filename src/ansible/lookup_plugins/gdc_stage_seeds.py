# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Ansible lookup plugin for GDC lifecycle stage seed manifest."""

import os
import sys

# Ensure plugin directory is on sys.path for local module import
PLUGIN_DIR = os.path.dirname(__file__)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ansible.plugins.lookup import LookupBase
from gdc_state_machine import get_stage_seed_manifest


class LookupModule(LookupBase):
    """Lookup plugin providing initial seed manifest for GDC lifecycle stages."""

    def run(self, terms, variables=None, **kwargs):
        stop_stage = terms[0] if (terms and len(terms) > 0) else kwargs.get("stop_stage")
        if not stop_stage and variables:
            stop_stage = variables.get("stop_stage") or variables.get("MACHINE_STATE_STOP_STAGE")
        manifest = get_stage_seed_manifest(stop_stage=stop_stage)
        return manifest
