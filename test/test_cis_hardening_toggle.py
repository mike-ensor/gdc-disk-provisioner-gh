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

"""Unit tests for CIS Security Bundle Hardening toggle variable resolution."""

import os
import unittest
import yaml
import jinja2

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULTS_YAML_PATH = os.path.join(
    REPO_ROOT, "src/ansible/roles/cis_bundle_harness/defaults/main.yml"
)


class TestCisHardeningToggle(unittest.TestCase):
    """Verifies that cis_bundle_process_hardening defaults to false and honors opt-in triggers."""

    @classmethod
    def setUpClass(cls):
        with open(DEFAULTS_YAML_PATH, "r", encoding="utf-8") as f:
            defaults = yaml.safe_load(f)
        cls.raw_template = defaults["cis_bundle_process_hardening"]

    def _render(self, env_vars=None, machine_config=None, ansible_local=None):
        def bool_filter(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes", "on", "t")
            return bool(v)

        def lookup_filter(lookup_type, key):
            if lookup_type == "env":
                return (env_vars or {}).get(key, "")
            return ""

        env = jinja2.Environment()
        env.filters["bool"] = bool_filter
        env.globals["lookup"] = lookup_filter

        template = env.from_string(self.raw_template)
        context = {
            "machine_config": machine_config or {},
            "ansible_local": ansible_local or {},
        }
        rendered = template.render(**context).strip()
        return bool_filter(rendered)

    def test_default_is_false_when_unset(self):
        """Hardening MUST NOT execute by default when no variables are provided."""
        result = self._render()
        self.assertFalse(result, "cis_bundle_process_hardening must default to False")

    def test_env_var_true_triggers_hardening(self):
        """GDC_PROCESS_CIS_HARDENING=true in environment triggers hardening."""
        result = self._render(env_vars={"GDC_PROCESS_CIS_HARDENING": "true"})
        self.assertTrue(result)

        result = self._render(env_vars={"GDC_PROCESS_CIS_HARDENING": "TRUE"})
        self.assertTrue(result)

    def test_env_var_false_suppresses_hardening(self):
        """GDC_PROCESS_CIS_HARDENING=false in environment explicitly suppresses hardening."""
        result = self._render(env_vars={"GDC_PROCESS_CIS_HARDENING": "false"})
        self.assertFalse(result)

        result = self._render(env_vars={"GDC_PROCESS_CIS_HARDENING": "FALSE"})
        self.assertFalse(result)

    def test_machine_config_top_level_toggle(self):
        """process_cis_hardening at machine_config root triggers hardening."""
        result = self._render(machine_config={"process_cis_hardening": True})
        self.assertTrue(result)

        result = self._render(machine_config={"process_cis_hardening": False})
        self.assertFalse(result)

    def test_machine_config_nested_security_toggle(self):
        """process_cis_hardening under machine_config.security triggers hardening."""
        result = self._render(
            machine_config={"security": {"process_cis_hardening": True}}
        )
        self.assertTrue(result)

    def test_ansible_local_facts_top_level_toggle(self):
        """process_cis_hardening in gdc.fact triggers hardening."""
        result = self._render(ansible_local={"gdc": {"process_cis_hardening": True}})
        self.assertTrue(result)

        result = self._render(ansible_local={"gdc": {"process_cis_hardening": False}})
        self.assertFalse(result)

    def test_ansible_local_facts_nested_security_toggle(self):
        """process_cis_hardening under gdc.fact.security triggers hardening."""
        result = self._render(
            ansible_local={"gdc": {"security": {"process_cis_hardening": True}}}
        )
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
