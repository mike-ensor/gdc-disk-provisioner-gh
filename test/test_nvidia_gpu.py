#!/usr/bin/env python3
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

"""Unit tests for automated NVIDIA GPU driver and container toolkit provisioning."""

import os
import unittest
import yaml
from jinja2 import Environment

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestNvidiaGPU(unittest.TestCase):
    """Verifies NVIDIA GPU package declarations, Ansible role structure, and stage integration."""

    def test_packages_config_contains_gpu_packages(self):
        """Verifies packages_config.yaml declares NVIDIA drivers and container toolkit for offline caching."""
        config_path = os.path.join(PROJECT_ROOT, "src/build/packages_config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        packages = set(cfg.get("packages_to_include", {}).get("customer_added", []))
        self.assertIn("nvidia-driver-580-server", packages, "Missing 'nvidia-driver-580-server' in packages_config.yaml customer_added")
        self.assertIn("nvidia-utils-580-server", packages, "Missing 'nvidia-utils-580-server' in packages_config.yaml customer_added")
        self.assertIn("nvidia-container-toolkit", packages, "Missing 'nvidia-container-toolkit' in packages_config.yaml customer_added")

    def test_vars_all_nvidia_settings(self):
        """Verifies vars/all.yml and vars/all.yml.j2 define required NVIDIA GPU provisioning variables."""
        for filename in ("all.yml", "all.yml.j2"):
            vars_path = os.path.join(PROJECT_ROOT, "src/ansible/vars", filename)
            with open(vars_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("nvidia_driver_package: \"nvidia-driver-580-server\"", content, f"{filename} missing nvidia_driver_package")
            self.assertIn("nvidia_utils_package: \"nvidia-utils-580-server\"", content, f"{filename} missing nvidia_utils_package")
            self.assertIn("nvidia_container_toolkit_package: \"nvidia-container-toolkit\"", content, f"{filename} missing nvidia_container_toolkit_package")
            self.assertIn("nvidia_gpu_enable_persistence: true", content, f"{filename} missing nvidia_gpu_enable_persistence")
            self.assertIn("nvidia_gpu_lock_memory_clock: true", content, f"{filename} missing nvidia_gpu_lock_memory_clock")
            self.assertIn("nvidia_gpu_memory_clock_mhz: 7000", content, f"{filename} missing nvidia_gpu_memory_clock_mhz")

    def test_nvidia_gpu_role_structure(self):
        """Verifies the nvidia_gpu role directory, defaults, templates, and task files exist."""
        role_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/nvidia_gpu")
        self.assertTrue(os.path.isdir(role_dir), "Role directory src/ansible/roles/nvidia_gpu does not exist")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "defaults/main.yml")), "Missing defaults/main.yml")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "templates/blacklist-nouveau.conf.j2")), "Missing blacklist-nouveau.conf.j2")
        self.assertTrue(os.path.isfile(os.path.join(role_dir, "templates/nvidia-persistenced.service.j2")), "Missing nvidia-persistenced.service.j2")

    def test_nvidia_gpu_template_rendering(self):
        """Verifies blacklist-nouveau.conf.j2 and nvidia-persistenced.service.j2 render expected directives."""
        role_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/nvidia_gpu")
        env = Environment()

        # Render blacklist-nouveau.conf.j2
        with open(os.path.join(role_dir, "templates/blacklist-nouveau.conf.j2"), "r", encoding="utf-8") as f:
            blacklist_tmpl = env.from_string(f.read())
        rendered_blacklist = blacklist_tmpl.render()
        self.assertIn("blacklist nouveau", rendered_blacklist)
        self.assertIn("options nouveau modeset=0", rendered_blacklist)
        self.assertIn("alias nouveau off", rendered_blacklist)

        # Render nvidia-persistenced.service.j2 with clock lock
        with open(os.path.join(role_dir, "templates/nvidia-persistenced.service.j2"), "r", encoding="utf-8") as f:
            service_tmpl = env.from_string(f.read())
        rendered_service_locked = service_tmpl.render({
            "nvidia_gpu_lock_memory_clock": True,
            "nvidia_gpu_memory_clock_mhz": 7000
        })
        self.assertIn("ExecStart=/usr/bin/nvidia-persistenced --user root", rendered_service_locked)
        self.assertIn("ExecStartPost=-/usr/bin/nvidia-smi -lmc 7000", rendered_service_locked)
        self.assertIn("Before=containerd.service kubelet.service", rendered_service_locked)

        # Render nvidia-persistenced.service.j2 without clock lock
        rendered_service_unlocked = service_tmpl.render({
            "nvidia_gpu_lock_memory_clock": False,
            "nvidia_gpu_memory_clock_mhz": 7000
        })
        self.assertNotIn("ExecStartPost=", rendered_service_unlocked)

    def test_nvidia_gpu_tasks_exist(self):
        """Verifies all task files for the nvidia_gpu role exist."""
        tasks_dir = os.path.join(PROJECT_ROOT, "src/ansible/roles/nvidia_gpu/tasks")
        for filename in ("main.yml", "detect.yml", "blacklist_nouveau.yml", "install_driver.yml", "configure_persistence.yml", "collect_evidence.yml"):
            self.assertTrue(os.path.isfile(os.path.join(tasks_dir, filename)), f"Missing task file {filename}")

    def test_pci_detection_regex(self):
        """Verifies the regex properly matches NVIDIA display controllers and ignores others."""
        import re
        pattern = re.compile(r'\[(0300|0302|0380)\]:.*10de:', re.IGNORECASE)

        # 192.168.9.238 sample line (RTX 4000 SFF Ada)
        gpu_line = "02:00.0 VGA compatible controller [0300]: NVIDIA Corporation Device [10de:2c34] (rev a1)"
        self.assertIsNotNone(pattern.search(gpu_line))

        # NVIDIA audio endpoint on same card - must NOT match display/compute controller
        audio_line = "02:00.1 Audio device [0403]: NVIDIA Corporation Device [10de:22e9] (rev a1)"
        self.assertIsNone(pattern.search(audio_line))

        # 192.168.9.242 sample line (AMD Phoenix APU)
        amd_line = "05:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Phoenix1 [1002:15bf] (rev c4)"
        self.assertIsNone(pattern.search(amd_line))

        # Intel Arrow Lake graphics
        intel_line = "00:02.0 VGA compatible controller [0300]: Intel Corporation Arrow Lake-U [Intel Graphics] [8086:7d67] (rev 06)"
        self.assertIsNone(pattern.search(intel_line))

    def test_stage_linux_ready_integration(self):
        """Verifies stage_linux_ready.yml includes the nvidia_gpu role and captures nvidia_gpu evidence."""
        stage_path = os.path.join(PROJECT_ROOT, "src/ansible/stages/stage_linux_ready.yml")
        with open(stage_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("name: nvidia_gpu", content, "stage_linux_ready.yml does not include role nvidia_gpu")
        self.assertIn("nvidia_gpu: \"{{ nvidia_gpu_evidence", content, "stage_linux_ready.yml does not record nvidia_gpu evidence")


if __name__ == "__main__":
    unittest.main()
