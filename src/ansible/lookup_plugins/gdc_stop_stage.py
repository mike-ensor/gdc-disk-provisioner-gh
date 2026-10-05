# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""Ansible lookup plugin for resolving GDC machine state stop stage."""

import os
import sys

# Ensure plugin directory is on sys.path for local module import
PLUGIN_DIR = os.path.dirname(__file__)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# pylint: disable=wrong-import-position,wrong-import-order
from ansible.plugins.lookup import LookupBase
from gdc_state_machine import get_stop_stage


class LookupModule(LookupBase):
    """Lookup plugin providing resolution of machine_state_stop_stage."""

    def run(self, terms, variables=None, **kwargs):  # type: ignore[override]
        explicit = terms[0] if (terms and len(terms) > 0) else kwargs.get("stop_stage")
        stop_stage = get_stop_stage(
            variables=variables,
            explicit_stop_stage=explicit,
            **kwargs,
        )
        return [stop_stage]
