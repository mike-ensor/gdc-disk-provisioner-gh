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

"""Unit tests verifying Companion API payload merging with variables overrides and core field preservation."""

import json
import os
import unittest
import jinja2
import yaml

TASKS_PATH = os.path.join(
    os.path.dirname(__file__),
    "../src/ansible/roles/machine_orchestration/tasks/main.yml"
)

class TestCompanionPayloadMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert os.path.exists(TASKS_PATH), f"Tasks file not found at {TASKS_PATH}"
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        parse_task = next(
            (t for t in tasks if isinstance(t, dict) and "Parse and register configuration facts" in t.get("name", "")),
            None
        )
        assert parse_task is not None, "Parse and register configuration facts task not found"
        cls.parse_task = parse_task
        cls.template_str = parse_task["ansible.builtin.set_fact"]["machine_config"]

        cls.env = jinja2.Environment()

        def ansible_combine(*terms, **kwargs):
            recursive = kwargs.get("recursive", False)
            def _merge(d1, d2):
                result = dict(d1)
                for k, v in d2.items():
                    if k in result and isinstance(result[k], dict) and isinstance(v, dict) and recursive:
                        result[k] = _merge(result[k], v)
                    else:
                        result[k] = v
                return result

            current = {}
            for t in terms:
                if isinstance(t, dict):
                    current = _merge(current, t) if current else dict(t)
            return current

        cls.env.filters["combine"] = ansible_combine
        cls.env.filters["b64decode"] = lambda val: val
        cls.env.filters["from_json"] = lambda val: json.loads(val) if isinstance(val, str) else val

    def _render(self, **context):
        # Default mock and manual stats
        base_ctx = {
            "manual_fact_stat": {"stat": {"exists": False}},
            "mock_file_stat": {"stat": {"exists": False}},
        }
        base_ctx.update(context)
        rendered = self.env.from_string(self.template_str).render(**base_ctx).strip()
        # Parse YAML / JSON output
        return yaml.safe_load(rendered)

    def test_preserves_core_cluster_and_peers_when_variables_omits_them(self):
        """Top-level cluster and peers must be preserved when variables has no cluster and empty peers."""
        api_response = {
            "json": {
                "hostname": "gdc-extreme-243",
                "bmctl_version": "1.35.300-gke.87",
                "network": {
                    "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
                    "cluster_network": {"vlan_id": 109, "dhcp_v4": False, "ip_cidr": "192.168.109.13/24"}
                },
                "gcp_info": {
                    "project_id": "anthos-bare-metal-lab-1",
                    "region": "us-central1"
                },
                "cluster": {
                    "cluster_name": "gdc-extreme-243",
                    "networking": {
                        "cluster_vip": "192.168.109.4",
                        "cluster_ingress": "192.168.109.40",
                        "cluster_lb_range": "192.168.109.40-192.168.109.49"
                    }
                },
                "peers": [
                    {"hostname": "gdc-extreme-243", "ipv4": "192.168.109.13", "node_type": "cp-worker", "primary": True}
                ],
                "variables": {
                    "hostname": "gdc-extreme-243",
                    "bmctl_version": "1.35.300-gke.87",
                    "peers": []
                }
            }
        }
        res = self._render(api_response=api_response)
        self.assertIn("cluster", res, "machine_config must retain cluster from top-level payload")
        self.assertEqual(res["cluster"]["cluster_name"], "gdc-extreme-243")
        self.assertEqual(res["cluster"]["networking"]["cluster_vip"], "192.168.109.4")
        self.assertEqual(len(res["peers"]), 1, "machine_config must not have peers wiped by empty variables.peers")
        self.assertEqual(res["peers"][0]["hostname"], "gdc-extreme-243")

    def test_variables_overrides_specific_nested_fields(self):
        """Variables overrides must take higher precedence than core values, preserving sibling fields."""
        api_response = {
            "json": {
                "hostname": "gdc-node-1",
                "cluster": {
                    "cluster_name": "gdc-node-1",
                    "networking": {
                        "cluster_vip": "192.168.109.4",
                        "cluster_ingress": "192.168.109.40"
                    }
                },
                "variables": {
                    "cluster": {
                        "networking": {
                            "cluster_vip": "192.168.109.99"
                        }
                    },
                    "custom_tuning_flag": "enabled"
                }
            }
        }
        res = self._render(api_response=api_response)
        self.assertEqual(res["cluster"]["networking"]["cluster_vip"], "192.168.109.99", "Override VIP must take precedence")
        self.assertEqual(res["cluster"]["networking"]["cluster_ingress"], "192.168.109.40", "Sibling field must be preserved")
        self.assertEqual(res["cluster"]["cluster_name"], "gdc-node-1", "Parent sibling field must be preserved")
        self.assertEqual(res["custom_tuning_flag"], "enabled", "Supplemental variable must be included")

if __name__ == "__main__":
    unittest.main()
