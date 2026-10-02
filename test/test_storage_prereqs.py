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

"""Unit tests for Longhorn v2 (SPDK / NVMe-oF) storage prerequisites."""

import os
import subprocess
import unittest
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestStoragePrereqs(unittest.TestCase):
    """Verifies all Longhorn v2 offline packages, cloud-init, Ansible role, and diagnostics."""

    def test_packages_config_contains_longhorn_dependencies(self):
        """Verifies packages_config.yaml bakes all required Longhorn v2 dependencies."""
        config_path = os.path.join(PROJECT_ROOT, "src/build/packages_config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        platform_pkgs = set(cfg.get("packages_to_include", {}).get("platform_required", []))
        expected_pkgs = {
            "open-iscsi",
            "nfs-common",
            "cryptsetup",
            "dmsetup",
            "util-linux",
            "libnvme1",
            "nvme-cli",
        }
        for pkg in expected_pkgs:
            self.assertIn(
                pkg,
                platform_pkgs,
                f"Missing required Longhorn dependency '{pkg}' in platform_required",
            )

    def test_cloud_init_user_data_enables_iscsid(self):
        """Verifies user-data.j2 enables iscsid service during Subiquity late-commands."""
        user_data_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(user_data_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            "curtin in-target -- systemctl enable iscsid.service",
            content,
            "user-data.j2 must enable iscsid.service for Longhorn node checks at first boot",
        )

    def test_storage_prereqs_role_tasks(self):
        """Verifies storage_prereqs tasks define HugePages, kernel modules, iscsid, and /customer/sds."""
        role_tasks_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/storage_prereqs/tasks/main.yml"
        )
        with open(role_tasks_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Engine sysctl verification
        self.assertIn("99-longhorn-engine.conf", content)
        self.assertIn("storage_engine_mode", content)

        # Persistent module configuration
        self.assertIn("longhorn-v2.conf", content)
        self.assertIn("/etc/modules-load.d/", content)

        # Live modprobe module loading
        self.assertIn("community.general.modprobe", content)

        # Service and mount path
        self.assertIn("name: iscsid", content)
        self.assertIn("state: directory", content)

    def test_storage_prereqs_role_defaults(self):
        """Verifies storage_prereqs defaults declare expected modules and page counts."""
        defaults_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/storage_prereqs/defaults/main.yml"
        )
        with open(defaults_path, "r", encoding="utf-8") as f:
            defaults = yaml.safe_load(f)

        self.assertEqual(defaults.get("storage_hugepages_count"), 2048)
        self.assertEqual(
            defaults.get("storage_hugepages_file"),
            "/etc/sysctl.d/99-longhorn-hugepages.conf",
        )
        self.assertEqual(
            defaults.get("storage_modules_file"),
            "/etc/modules-load.d/longhorn-v2.conf",
        )
        self.assertEqual(defaults.get("storage_sds_directory"), "/customer/sds")

        expected_modules = ["nvme-tcp", "uio", "uio_pci_generic", "vfio_pci"]
        self.assertEqual(defaults.get("storage_kernel_modules"), expected_modules)

    def test_stage_linux_ready_includes_storage_prereqs(self):
        """Verifies stage_linux_ready.yml executes storage_prereqs during NODE_PREP / pre-Kubelet."""
        stage_path = os.path.join(
            PROJECT_ROOT, "src/ansible/stages/stage_linux_ready.yml"
        )
        with open(stage_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            "name: storage_prereqs",
            content,
            "stage_linux_ready.yml must include storage_prereqs role during NODE_PREP",
        )

    def test_machine_orchestration_deploys_and_executes_validation_script(self):
        """Verifies machine_orchestration deploys validation script and records evidence."""
        orch_tasks_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/machine_orchestration/tasks/main.yml"
        )
        with open(orch_tasks_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("validate-storage-prereqs.sh", content)
        self.assertIn(
            "cmd: \"/usr/local/bin/validate-storage-prereqs.sh {{ storage_engine_mode | default('v2') }}\"",
            content,
        )
        self.assertIn("storage_prereqs:", content)
        self.assertIn("engine_mode:", content)
        self.assertIn("iscsid_active:", content)
        self.assertIn("inotify_verified:", content)
        self.assertIn("engine_mode_verified:", content)
        self.assertIn("hugepages_verified:", content)
        self.assertIn("kernel_modules_loaded:", content)
        self.assertIn("sds_directory_present:", content)
        self.assertIn("validation_status:", content)
        self.assertIn("details:", content)

    def test_validate_storage_prereqs_script_syntax(self):
        """Verifies that validate-storage-prereqs.sh passes bash syntax validation."""
        script_paths = [
            os.path.join(
                PROJECT_ROOT,
                "src/ansible/roles/storage_prereqs/files/validate-storage-prereqs.sh",
            ),
            os.path.join(
                PROJECT_ROOT,
                "src/ansible/roles/machine_orchestration/files/validate-storage-prereqs.sh",
            ),
        ]
        for script_path in script_paths:
            res = subprocess.run(
                ["bash", "-n", script_path], capture_output=True, text=True
            )
            self.assertEqual(
                res.returncode,
                0,
                f"{script_path} bash syntax error: {res.stderr}",
            )

        with open(script_paths[0], "r", encoding="utf-8") as f1, open(
            script_paths[1], "r", encoding="utf-8"
        ) as f2:
            self.assertEqual(
                f1.read(),
                f2.read(),
                "validate-storage-prereqs.sh must be identical across storage_prereqs and machine_orchestration",
            )

    def test_validate_storage_prereqs_five_sections(self):
        """Verifies validate-storage-prereqs.sh contains all 5 sections from Issue #17."""
        script_paths = [
            os.path.join(
                PROJECT_ROOT,
                "src/ansible/roles/storage_prereqs/files/validate-storage-prereqs.sh",
            ),
            os.path.join(
                PROJECT_ROOT,
                "src/ansible/roles/machine_orchestration/files/validate-storage-prereqs.sh",
            ),
        ]
        for script_path in script_paths:
            with open(script_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 1. Common: Checking iscsid Service
            self.assertIn("=== 1. Common: Checking iscsid Service ===", content)
            self.assertIn("systemctl is-active --quiet iscsid", content)

            # 2. Common: Checking inotify Limits
            self.assertIn("=== 2. Common: Checking inotify Limits ===", content)
            self.assertIn("cat /proc/sys/fs/inotify/max_user_watches", content)
            self.assertIn("524288", content)

            # 3. Common: Checking NVMe Schedulers
            self.assertIn("=== 3. Common: Checking NVMe Schedulers ===", content)
            self.assertIn("/sys/block/nvme*n1", content)
            self.assertIn("queue/scheduler", content)

            # 4. Common: Checking Storage Directory
            self.assertIn("=== 4. Common: Checking Storage Directory ===", content)
            self.assertIn("/customer/sds", content)

            # 5. Engine Verification ($ENGINE_MODE)
            self.assertIn("=== 5. Engine Verification ($ENGINE_MODE) ===", content)
            self.assertIn('ENGINE_MODE="${1:-v2}"', content)
            self.assertIn('2048', content)
            self.assertIn('REQUIRED_MODULES=("nvme_tcp" "uio" "uio_pci_generic" "vfio_pci")', content)
            self.assertIn('"$HP" -eq 0', content)

    def test_storage_prereqs_common_baseline(self):
        """Verifies udev NVMe scheduler rules, multipath blacklist, and common sysctl."""
        role_tasks_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/storage_prereqs/tasks/main.yml"
        )
        with open(role_tasks_path, "r", encoding="utf-8") as f:
            content = f.read()

        # udev rule
        self.assertIn("60-nvme-longhorn.rules", content)
        self.assertIn("queue/scheduler", content)
        self.assertIn("queue/read_ahead_kb", content)
        self.assertIn("udevadm control --reload-rules", content)
        self.assertIn("udevadm trigger --subsystem-match=block", content)

        # multipath blacklist
        self.assertIn("longhorn.conf", content)
        self.assertIn('vendor "LONGHORN"', content)
        self.assertIn('devnode "^sd[a-z0-9]+"', content)

        # common sysctl
        self.assertIn("90-longhorn-common.conf", content)
        self.assertIn("fs.file-max", content)
        self.assertIn("net.core.somaxconn", content)

        # defaults verification
        defaults_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/storage_prereqs/defaults/main.yml"
        )
        with open(defaults_path, "r", encoding="utf-8") as f:
            defaults = yaml.safe_load(f)

        self.assertEqual(
            defaults.get("storage_udev_rules_file"),
            "/etc/udev/rules.d/60-nvme-longhorn.rules",
        )
        self.assertEqual(
            defaults.get("storage_multipath_dir"),
            "/etc/multipath/conf.d",
        )
        self.assertEqual(
            defaults.get("storage_multipath_file"),
            "/etc/multipath/conf.d/longhorn.conf",
        )
        self.assertEqual(
            defaults.get("storage_common_sysctl_file"),
            "/etc/sysctl.d/90-longhorn-common.conf",
        )
        sysctl_params = defaults.get("storage_common_sysctl_parameters", [])
        param_dict = {p["name"]: str(p["value"]) for p in sysctl_params}
        self.assertEqual(param_dict.get("fs.file-max"), "2097152")
        self.assertEqual(param_dict.get("fs.inotify.max_user_watches"), "524288")
        self.assertEqual(param_dict.get("fs.inotify.max_user_instances"), "8192")
        self.assertEqual(param_dict.get("net.core.somaxconn"), "32768")
        self.assertEqual(param_dict.get("net.core.netdev_max_backlog"), "16384")
        self.assertEqual(param_dict.get("net.ipv4.tcp_max_syn_backlog"), "16384")

        # user-data.j2 includes 60-nvme-longhorn.rules
        user_data_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(user_data_path, "r", encoding="utf-8") as f:
            user_data_content = f.read()
        self.assertIn("60-nvme-longhorn.rules", user_data_content)
        self.assertIn("queue/scheduler", user_data_content)

    def test_storage_prereqs_engine_tracks(self):
        """Verifies v1 and v2 engine specific sysctl, module loading, and mode defaults."""
        defaults_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/storage_prereqs/defaults/main.yml"
        )
        with open(defaults_path, "r", encoding="utf-8") as f:
            defaults = yaml.safe_load(f)

        # 1 & 2. Defaults verification
        self.assertEqual(defaults.get("storage_engine_mode"), "v2")
        self.assertEqual(
            defaults.get("storage_engine_sysctl_file"),
            "/etc/sysctl.d/99-longhorn-engine.conf",
        )

        v1_params = defaults.get("storage_engine_v1_sysctl_parameters", [])
        v1_dict = {p["name"]: str(p["value"]) for p in v1_params}
        self.assertEqual(v1_dict.get("vm.dirty_background_ratio"), "5")
        self.assertEqual(v1_dict.get("vm.dirty_ratio"), "10")
        self.assertEqual(v1_dict.get("vm.nr_hugepages"), "0")
        self.assertEqual(v1_dict.get("net.core.rmem_max"), "16777216")
        self.assertEqual(v1_dict.get("net.core.wmem_max"), "16777216")
        self.assertEqual(v1_dict.get("net.ipv4.tcp_rmem"), "4096 87380 16777216")
        self.assertEqual(v1_dict.get("net.ipv4.tcp_wmem"), "4096 65536 16777216")

        v2_params = defaults.get("storage_engine_v2_sysctl_parameters", [])
        v2_dict = {p["name"]: str(p["value"]) for p in v2_params}
        self.assertIn("vm.nr_hugepages", v2_dict)
        self.assertIn("storage_hugepages_count", v2_dict["vm.nr_hugepages"])

        # 3. Tasks verification
        tasks_path = os.path.join(
            PROJECT_ROOT, "src/ansible/roles/storage_prereqs/tasks/main.yml"
        )
        with open(tasks_path, "r", encoding="utf-8") as f:
            tasks_content = f.read()

        # Engine sysctl configuration file
        self.assertIn("99-longhorn-engine.conf", tasks_content)
        self.assertIn("storage_engine_sysctl_file", tasks_content)

        # Track A (v1) checks
        self.assertIn("storage_engine_mode == 'v1'", tasks_content)
        self.assertIn("storage_engine_v1_sysctl_parameters", tasks_content)
        self.assertIn("Ensure Longhorn v2 modules file is absent for v1 engine", tasks_content)
        self.assertIn("Validate storage_engine_mode", tasks_content)

        # Track B (v2) checks
        self.assertIn("storage_engine_mode == 'v2'", tasks_content)
        self.assertIn("storage_engine_v2_sysctl_parameters", tasks_content)
        self.assertIn("storage_kernel_modules", tasks_content)
        self.assertIn("community.general.modprobe", tasks_content)

        # Sysctl reload check
        self.assertIn("/sbin/sysctl -p", tasks_content)
        self.assertIn("changed_when: false", tasks_content)



if __name__ == "__main__":
    unittest.main()
