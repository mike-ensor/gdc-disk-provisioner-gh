# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
import unittest
import yaml
from pathlib import Path

class TestNexusEulaAndAnon(unittest.TestCase):
    """Verifies that Nexus tasks include EULA acceptance and anonymous access enablement."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent

    def test_service_hubs_nexus_tasks_present(self):
        service_hubs_path = self.repo_root / "src/ansible/roles/service_hubs/tasks/main.yml"
        self.assertTrue(service_hubs_path.exists())
        with open(service_hubs_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        self.assertTrue(
            any("EULA" in name for name in task_names),
            "Expected EULA check/acceptance task in service_hubs role"
        )
        self.assertTrue(
            any("anonymous access" in name.lower() for name in task_names),
            "Expected anonymous access task in service_hubs role"
        )

    def test_host_foundations_nexus_safety_present(self):
        host_foundations_path = self.repo_root / "src/ansible/roles/host_foundations/tasks/main.yml"
        self.assertTrue(host_foundations_path.exists())
        with open(host_foundations_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)

        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        self.assertTrue(
            any("anonymous access and EULA" in name for name in task_names),
            "Expected defensive Nexus check in host_foundations role"
        )

    def test_remaster_nexus_properties_onboarding_disabled(self):
        remaster_path = self.repo_root / "src/build/remaster.sh"
        self.assertTrue(remaster_path.exists())
        content = remaster_path.read_text(encoding="utf-8")
        self.assertIn("nexus.onboarding.enabled=false", content)

if __name__ == "__main__":
    unittest.main()
