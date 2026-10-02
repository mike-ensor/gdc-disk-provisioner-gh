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

"""Unit tests validating machine config schema for ConfigSync primary root repo."""

import json
import os
import unittest
import jsonschema

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestMachineSchema(unittest.TestCase):
    """Unit tests validating docs/machine-schema.json against primary root repo configs."""

    def setUp(self):
        """Load docs/machine-schema.json from the repository root."""
        schema_path = os.path.join(REPO_ROOT, "docs/machine-schema.json")
        if not os.path.exists(schema_path):
            schema_path = "docs/machine-schema.json"
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_schema_validates_legacy_string_primary_root_repo(self):
        """Verify that a legacy string primary_root_repo validates successfully."""
        mock_path = os.path.join(REPO_ROOT, "custom-data/machine-info-mock-net-9.json")
        if not os.path.exists(mock_path):
            mock_path = "custom-data/machine-info-mock-net-9.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "management_network" in data.get("network", {}):
            data["network"]["management_network"].setdefault("dns_servers", ["8.8.8.8"])
        if "cluster_network" in data.get("network", {}):
            data["network"]["cluster_network"].setdefault("dhcp_v4", True)
        data.update(
            {
                "bmctl_version": "1.35.300-gke.87",
                "gcp_info": {
                    "project_id": "test-proj",
                    "region": "us-west1",
                    "primary_gsa": "sa@test-proj.iam.gserviceaccount.com",
                },
                "cluster": {
                    "cluster_name": "test-cluster",
                    "primary_root_repo": "us-docker.pkg.dev/test-proj/repo/config:v1.0.0",
                    "primary_root_repo_auth_secret": "ext-oci-secret",
                    "networking": {
                        "cluster_vip": "192.168.9.100",
                        "cluster_ingress": "192.168.9.101",
                        "cluster_lb_range": "192.168.9.101-192.168.9.109",
                    },
                    "fleet_cluster_labels": ["type=test"],
                },
            }
        )
        jsonschema.validate(instance=data, schema=self.schema)

    def test_schema_validates_structured_git_primary_root_repo(self):
        """Verify that a structured git primary_root_repo object validates successfully."""
        data = {
            "hostname": "test-host",
            "bmctl_version": "1.35.300-gke.87",
            "network": {
                "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
                "cluster_network": {"vlan_id": 9, "dhcp_v4": True},
            },
            "gcp_info": {
                "project_id": "test-proj",
                "region": "us-west1",
                "primary_gsa": "sa@test-proj.iam.gserviceaccount.com",
            },
            "cluster": {
                "cluster_name": "test-cluster",
                "config_sync_enabled": True,
                "primary_root_repo": {
                    "cluster_config_name": "custom-folder",
                    "git": {
                        "repo_url": "https://gitlab.com/test-org/test-repo.git",
                        "branch": "main",
                        "gsm_secret_name": "git-creds",
                    },
                },
                "networking": {
                    "cluster_vip": "192.168.9.100",
                    "cluster_ingress": "192.168.9.101",
                    "cluster_lb_range": "192.168.9.101-192.168.9.109",
                },
                "fleet_cluster_labels": ["type=test"],
            },
            "peers": [],
        }
        jsonschema.validate(instance=data, schema=self.schema)

    def test_schema_validates_structured_oci_primary_root_repo(self):
        """Verify that a structured oci primary_root_repo object validates successfully."""
        data = {
            "hostname": "test-host",
            "bmctl_version": "1.35.300-gke.87",
            "network": {
                "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
                "cluster_network": {"vlan_id": 9, "dhcp_v4": True},
            },
            "gcp_info": {
                "project_id": "test-proj",
                "region": "us-west1",
                "primary_gsa": "sa@test-proj.iam.gserviceaccount.com",
            },
            "cluster": {
                "cluster_name": "test-cluster",
                "primary_root_repo": {
                    "oci": {
                        "image": "us-docker.pkg.dev/test-proj/repo/config:v1.0.0",
                        "gsa": "sa-name",
                        "gsm_secret_name": "ext-oci-secret",
                    }
                },
                "networking": {
                    "cluster_vip": "192.168.9.100",
                    "cluster_ingress": "192.168.9.101",
                    "cluster_lb_range": "192.168.9.101-192.168.9.109",
                },
                "fleet_cluster_labels": ["type=test"],
            },
            "peers": [],
        }
        jsonschema.validate(instance=data, schema=self.schema)

    def test_schema_validates_optional_or_null_primary_root_repo(self):
        """Verify that primary_root_repo can be omitted or explicitly null."""
        data = {
            "hostname": "test-host",
            "bmctl_version": "1.35.300-gke.87",
            "network": {
                "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
                "cluster_network": {"vlan_id": 9, "dhcp_v4": True},
            },
            "gcp_info": {
                "project_id": "test-proj",
                "region": "us-west1",
                "primary_gsa": "sa@test-proj.iam.gserviceaccount.com",
            },
            "cluster": {
                "cluster_name": "test-cluster",
                "config_sync_enabled": True,
                "networking": {
                    "cluster_vip": "192.168.9.100",
                    "cluster_ingress": "192.168.9.101",
                    "cluster_lb_range": "192.168.9.101-192.168.9.109",
                },
                "fleet_cluster_labels": ["type=test"],
            },
            "peers": [],
        }
        # Validate when primary_root_repo is omitted
        jsonschema.validate(instance=data, schema=self.schema)

        # Validate when primary_root_repo is null
        data["cluster"]["primary_root_repo"] = None
        jsonschema.validate(instance=data, schema=self.schema)

    def test_schema_validates_gsm_auth_secret_object(self):
        """Verify that primary_root_repo with gsm-auth-secret validates successfully."""
        data = {
            "hostname": "test-host",
            "bmctl_version": "1.35.300-gke.87",
            "network": {
                "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
                "cluster_network": {"vlan_id": 9, "dhcp_v4": True},
            },
            "gcp_info": {
                "project_id": "test-proj",
                "region": "us-west1",
                "primary_gsa": "sa@test-proj.iam.gserviceaccount.com",
            },
            "cluster": {
                "cluster_name": "test-cluster",
                "config_sync_enabled": True,
                "primary_root_repo": {
                    "cluster-config-name": "custom-folder",
                    "git": {
                        "repo-url": "https://gitlab.com/test-org/test-repo.git",
                        "branch": "main",
                        "gsm-auth-secret": {
                            "gsm-name": "es-git-creds",
                            "gsm-location": "global",
                            "k8s-name": "git-creds",
                            "k8s-namespace": "config-management-system",
                        },
                    },
                },
                "networking": {
                    "cluster_vip": "192.168.9.100",
                    "cluster_ingress": "192.168.9.101",
                    "cluster_lb_range": "192.168.9.101-192.168.9.109",
                },
                "fleet_cluster_labels": ["type=test"],
            },
            "peers": [],
        }
        jsonschema.validate(instance=data, schema=self.schema)

    def test_schema_validates_gsm_auth_secret_regional_location(self):
        """Verify that gsm-auth-secret with regional gsm-location validates."""
        data = {
            "hostname": "test-host",
            "bmctl_version": "1.35.300-gke.87",
            "network": {
                "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
                "cluster_network": {"vlan_id": 9, "dhcp_v4": True},
            },
            "gcp_info": {
                "project_id": "test-proj",
                "region": "us-west1",
                "primary_gsa": "sa@test-proj.iam.gserviceaccount.com",
            },
            "cluster": {
                "cluster_name": "test-cluster",
                "primary_root_repo": {
                    "git": {
                        "repo_url": "https://gitlab.com/test-org/test-repo.git",
                        "gsm_auth_secret": {
                            "gsm_name": "regional-secret",
                            "gsm_location": "us-west1",
                            "k8s_name": "k8s-secret",
                        },
                    },
                },
                "networking": {
                    "cluster_vip": "192.168.9.100",
                    "cluster_ingress": "192.168.9.101",
                    "cluster_lb_range": "192.168.9.101-192.168.9.109",
                },
                "fleet_cluster_labels": ["type=test"],
            },
            "peers": [],
        }
        jsonschema.validate(instance=data, schema=self.schema)

    def test_schema_validates_optional_primary_root_repo_auth_secret(self):
        """Verify that primary_root_repo_auth_secret is optional."""
        data = {
            "hostname": "test-host",
            "bmctl_version": "1.35.300-gke.87",
            "network": {
                "management_network": {"dhcp_v4": True, "dns_servers": ["8.8.8.8"]},
                "cluster_network": {"vlan_id": 9, "dhcp_v4": True},
            },
            "gcp_info": {
                "project_id": "test-proj",
                "region": "us-west1",
                "primary_gsa": "sa@test-proj.iam.gserviceaccount.com",
            },
            "cluster": {
                "cluster_name": "test-cluster",
                "primary_root_repo": "us-docker.pkg.dev/test-proj/repo/config:v1.0.0",
                "networking": {
                    "cluster_vip": "192.168.9.100",
                    "cluster_ingress": "192.168.9.101",
                    "cluster_lb_range": "192.168.9.101-192.168.9.109",
                },
                "fleet_cluster_labels": ["type=test"],
            },
            "peers": [],
        }
        # primary_root_repo_auth_secret is omitted
        jsonschema.validate(instance=data, schema=self.schema)


if __name__ == "__main__":
    unittest.main()
