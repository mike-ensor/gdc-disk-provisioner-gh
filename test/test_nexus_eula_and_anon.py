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

    def test_nexus_unprivileged_user_isolation(self):
        remaster_path = self.repo_root / "src/build/remaster.sh"
        self.assertIn('run_as_user="nexus"', remaster_path.read_text(encoding="utf-8"))

        service_path = self.repo_root / "src/build/templates/nexus.service.j2"
        service_content = service_path.read_text(encoding="utf-8")
        self.assertIn("User=nexus", service_content)
        self.assertIn("Group=nexus", service_content)
        self.assertNotIn("User=root", service_content)

        userdata_path = self.repo_root / "src/build/templates/user-data.j2"
        userdata_content = userdata_path.read_text(encoding="utf-8")
        self.assertIn("groupadd --system nexus", userdata_content)
        self.assertIn("useradd --system --uid 990 --gid nexus --shell /bin/false --comment \"Sonatype Nexus Service User\" --home-dir /var/lib/nexus nexus", userdata_content)
        self.assertIn("chown -R nexus:nexus /var/lib/nexus", userdata_content)

        service_hubs_path = self.repo_root / "src/ansible/roles/service_hubs/tasks/main.yml"
        with open(service_hubs_path, "r", encoding="utf-8") as f:
            tasks = yaml.safe_load(f)
        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        self.assertTrue(any("nexus system group" in name.lower() for name in task_names))
        self.assertTrue(any("nexus system user" in name.lower() for name in task_names))
        self.assertTrue(any("nexus ownership" in name.lower() for name in task_names))

if __name__ == "__main__":
    unittest.main()
