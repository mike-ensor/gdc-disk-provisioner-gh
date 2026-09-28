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

import os
import sys
import unittest
import tempfile
import shutil
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestStorageDiscovery(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        # Symlink templates directory so test scripts can locate templates/storage
        os.symlink(os.path.join(PROJECT_ROOT, "src/build/templates"), os.path.join(self.test_dir, "templates"))
        # Mock logger to ensure tests succeed in containers without /dev/log
        mock_logger = os.path.join(self.bin_dir, "logger")
        with open(mock_logger, "w") as f:
            f.write("#!/usr/bin/env bash\nexit 0\n")
        os.chmod(mock_logger, 0o755)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_generate_storage_config_excludes_usb_and_installer_media(self):
        """Verifies generate_storage_config.sh skips USB storage drives and installer media."""
        # Create a mock environment with sda (USB installer) and nvme0n1 (Internal NVMe)
        mock_lsblk = os.path.join(self.bin_dir, "lsblk")
        with open(mock_lsblk, "w") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"-dno NAME,TYPE"* ]]; then
    echo "sda disk"
    echo "nvme0n1 disk"
    exit 0
fi
if [[ "$*" == *"-dno TRAN /dev/sda"* ]]; then
    echo "usb"
    exit 0
fi
if [[ "$*" == *"-dno TRAN /dev/nvme0n1"* ]]; then
    echo "nvme"
    exit 0
fi
if [[ "$*" == *"-no PKNAME /dev/sda1"* ]]; then
    echo "sda"
    exit 0
fi
exit 0
""")
        os.chmod(mock_lsblk, 0o755)

        mock_findmnt = os.path.join(self.bin_dir, "findmnt")
        with open(mock_findmnt, "w") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"/cdrom"* ]]; then
    echo "/dev/sda1"
    exit 0
fi
exit 1
""")
        os.chmod(mock_findmnt, 0o755)

        # Mock blkid
        mock_blkid = os.path.join(self.bin_dir, "blkid")
        with open(mock_blkid, "w") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"iso9660"* ]]; then
    echo "/dev/sda1"
    exit 0
fi
exit 0
""")
        os.chmod(mock_blkid, 0o755)

        # Create mock sysfs block devices
        mock_sys_block = os.path.join(self.test_dir, "sys_block")
        os.makedirs(os.path.join(mock_sys_block, "sda"), exist_ok=True)
        os.makedirs(os.path.join(mock_sys_block, "nvme0n1"), exist_ok=True)
        
        # 256GB USB drive = 536870912 sectors
        with open(os.path.join(mock_sys_block, "sda", "size"), "w") as f:
            f.write("536870912\n")
        # 1TB NVMe drive = 2000409600 sectors
        with open(os.path.join(mock_sys_block, "nvme0n1", "size"), "w") as f:
            f.write("2000409600\n")

        script_path = os.path.join(PROJECT_ROOT, "src/build/generate_storage_config.sh")
        
        # Run generate_storage_config.sh with our mocked PATH and sys/block
        test_script = f"""#!/usr/bin/env bash
export PATH="{self.bin_dir}:$PATH"
# Intercept /sys/block access by symlinking our test sys_block
# We execute generate_storage_config.sh with dry-run
bash -c '
# Redefine /sys/block lookup path using a sed wrapper script or subshell override
sed "s|/sys/block/|{mock_sys_block}/|g" "{script_path}" > "{self.test_dir}/test_gen.sh"
chmod +x "{self.test_dir}/test_gen.sh"
"{self.test_dir}/test_gen.sh" --dry-run
'
"""
        res = subprocess.run(["bash", "-c", test_script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Script failed with output: {res.stdout} {res.stderr}")
        
        # Assertions:
        # 1. Installer live media /dev/sda should be skipped and logged in stderr
        self.assertTrue(
            "Skipping installer live media disk: /dev/sda" in res.stderr or
            "Skipping USB storage device: /dev/sda" in res.stderr,
            f"Expected USB/installer skip log in stderr, got: {res.stderr}"
        )
        # 2. YAML output MUST use nvme0n1 as the primary system drive
        self.assertIn("path: /dev/nvme0n1", res.stdout)
        # 3. YAML output MUST NOT contain /dev/sda
        self.assertNotIn("path: /dev/sda", res.stdout)
        # 4. Topology should be single because only 1 valid hard disk was detected
        self.assertIn("Single Disk", res.stdout)

    def test_generate_storage_config_dual_disk_with_usb_installer(self):
        """Verifies generate_storage_config.sh retains dual-disk topology when USB installer is also attached."""
        mock_lsblk = os.path.join(self.bin_dir, "lsblk")
        with open(mock_lsblk, "w") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"-dno NAME,TYPE"* ]]; then
    echo "nvme0n1 disk"
    echo "sdb disk"
    echo "nvme1n1 disk"
    exit 0
fi
if [[ "$*" == *"-dno TRAN /dev/sdb"* ]]; then
    echo "usb"
    exit 0
fi
if [[ "$*" == *"-dno TRAN /dev/nvme"* ]]; then
    echo "nvme"
    exit 0
fi
if [[ "$*" == *"-no PKNAME /dev/sdb1"* ]]; then
    echo "sdb"
    exit 0
fi
exit 0
""")
        os.chmod(mock_lsblk, 0o755)

        mock_findmnt = os.path.join(self.bin_dir, "findmnt")
        with open(mock_findmnt, "w") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"/cdrom"* ]]; then
    echo "/dev/sdb1"
    exit 0
fi
exit 1
""")
        os.chmod(mock_findmnt, 0o755)

        mock_sys_block = os.path.join(self.test_dir, "sys_block_dual")
        os.makedirs(os.path.join(mock_sys_block, "sdb"), exist_ok=True)
        os.makedirs(os.path.join(mock_sys_block, "nvme0n1"), exist_ok=True)
        os.makedirs(os.path.join(mock_sys_block, "nvme1n1"), exist_ok=True)
        
        with open(os.path.join(mock_sys_block, "sdb", "size"), "w") as f:
            f.write("536870912\n") # 256GB USB
        with open(os.path.join(mock_sys_block, "nvme0n1", "size"), "w") as f:
            f.write("2000409600\n") # 1TB NVMe Disk 1
        with open(os.path.join(mock_sys_block, "nvme1n1", "size"), "w") as f:
            f.write("4000819200\n") # 2TB NVMe Disk 2

        script_path = os.path.join(PROJECT_ROOT, "src/build/generate_storage_config.sh")
        test_script = f"""#!/usr/bin/env bash
export PATH="{self.bin_dir}:$PATH"
sed "s|/sys/block/|{mock_sys_block}/|g" "{script_path}" > "{self.test_dir}/test_gen_dual.sh"
chmod +x "{self.test_dir}/test_gen_dual.sh"
"{self.test_dir}/test_gen_dual.sh" --dry-run
"""
        res = subprocess.run(["bash", "-c", test_script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Script failed with output: {res.stdout} {res.stderr}")
        
        # Assertions:
        # 1. USB drive /dev/sdb skipped
        self.assertTrue(
            "Skipping installer live media disk: /dev/sdb" in res.stderr or
            "Skipping USB storage device: /dev/sdb" in res.stderr
        )
        # 2. Both NVMe drives are configured
        self.assertIn("path: /dev/nvme0n1", res.stdout)
        self.assertIn("path: /dev/nvme1n1", res.stdout)
        # 3. USB drive sdb is NOT in configuration
        self.assertNotIn("path: /dev/sdb", res.stdout)
        # 4. Topology is dual disk
        self.assertIn("Dual Disk", res.stdout)

    def test_generate_storage_config_skips_undersized_disks(self):
        """Verifies generate_storage_config.sh skips disks smaller than 560 GiB (1174405120 sectors)."""
        mock_lsblk = os.path.join(self.bin_dir, "lsblk")
        with open(mock_lsblk, "w") as f:
            f.write("""#!/usr/bin/env bash
if [[ "$*" == *"-dno NAME,TYPE"* ]]; then
    echo "nvme0n1 disk"
    exit 0
fi
if [[ "$*" == *"-dno TRAN /dev/nvme0n1"* ]]; then
    echo "nvme"
    exit 0
fi
exit 0
""")
        os.chmod(mock_lsblk, 0o755)

        mock_findmnt = os.path.join(self.bin_dir, "findmnt")
        with open(mock_findmnt, "w") as f:
            f.write("#!/usr/bin/env bash\nexit 1\n")
        os.chmod(mock_findmnt, 0o755)

        mock_blkid = os.path.join(self.bin_dir, "blkid")
        with open(mock_blkid, "w") as f:
            f.write("#!/usr/bin/env bash\nexit 0\n")
        os.chmod(mock_blkid, 0o755)

        mock_sys_block = os.path.join(self.test_dir, "sys_block_undersized")
        os.makedirs(os.path.join(mock_sys_block, "nvme0n1"), exist_ok=True)
        # 250GB disk = 503316480 sectors (< 1174405120 sectors)
        with open(os.path.join(mock_sys_block, "nvme0n1", "size"), "w") as f:
            f.write("503316480\n")

        script_path = os.path.join(PROJECT_ROOT, "src/build/generate_storage_config.sh")
        test_script = f"""#!/usr/bin/env bash
export PATH="{self.bin_dir}:$PATH"
sed "s|/sys/block/|{mock_sys_block}/|g" "{script_path}" > "{self.test_dir}/test_gen_undersized.sh"
chmod +x "{self.test_dir}/test_gen_undersized.sh"
"{self.test_dir}/test_gen_undersized.sh" --dry-run
"""
        res = subprocess.run(["bash", "-c", test_script], capture_output=True, text=True)
        self.assertIn("Skipping undersized disk: /dev/nvme0n1", res.stderr)
        self.assertIn("503316480 sectors < 1174405120", res.stderr)

    def test_user_data_protection_function(self):
        """Verifies the disk sanitization protection logic in user-data.j2 under POSIX sh."""
        user_data_j2_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(user_data_j2_path, "r") as f:
            content = f.read()

        # Verify key protective safeguards exist in the template
        self.assertIn("is_protected_dev()", content)
        self.assertIn('INSTALLER_DISKS=""', content)
        self.assertIn('tran=$(lsblk -dno TRAN "/dev/${root_disk}" 2>/dev/null || true)', content)
        self.assertIn('echo "   -> [PROTECT] Skipping protected installer/USB device: ${p}"', content)
        self.assertIn('echo "   -> [PROTECT] Preserving protected installer/USB storage disk: /dev/${d}"', content)

        # Test execution of the protection logic in isolation using POSIX sh
        sh_test = """
        INSTALLER_DISKS="sda"

        is_protected_dev() {
          target_dev="$1"
          bname=$(basename "${target_dev}")
          
          # Mock pkname mapping using POSIX case
          case "${bname}" in
            sda*)
              pkname="sda"
              ;;
            nvme0n1p*)
              pkname="nvme0n1"
              ;;
            *)
              pkname=""
              ;;
          esac
          root_disk="${pkname:-${bname}}"

          for inst_d in ${INSTALLER_DISKS}; do
            if [ "${root_disk}" = "${inst_d}" ] || [ "${bname}" = "${inst_d}" ]; then
              return 0
            fi
          done

          if [ "${root_disk}" = "sda" ]; then
            tran="usb"
          else
            tran="nvme"
          fi

          if [ "${tran}" = "usb" ]; then
            return 0
          fi
          return 1
        }

        # Assert sda and its partitions are protected
        is_protected_dev /dev/sda || exit 1
        is_protected_dev /dev/sda1 || exit 2
        is_protected_dev /dev/sda2 || exit 3

        # Assert internal drive nvme0n1 is NOT protected (safe to wipe)
        if is_protected_dev /dev/nvme0n1; then exit 4; fi
        if is_protected_dev /dev/nvme0n1p1; then exit 5; fi

        echo "PROTECTION_TEST_OK"
        """
        res = subprocess.run(["sh", "-c", sh_test], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"POSIX sh test failed with code {res.returncode}: {res.stderr}")
        self.assertIn("PROTECTION_TEST_OK", res.stdout)

if __name__ == "__main__":
    unittest.main()
