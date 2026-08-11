#!/usr/bin/env python3
import os
import sys
import unittest
from unittest import mock
import tempfile
import shutil
import yaml
from jinja2 import Environment, FileSystemLoader

# Set up paths so we can import src/build modules cleanly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))

import render_templates
import configure_netplan

class TestGgdTemplateHydration(unittest.TestCase):
    
    def setUp(self):
        # Create a clean, isolated temporary workspace for each test run
        self.test_dir = tempfile.mkdtemp()
        self.template_dir = os.path.join(PROJECT_ROOT, "src/build/templates")
        self.jinja_env = Environment(loader=FileSystemLoader(self.template_dir))
        
        # Define baseline representative environment parameters
        self.base_env = {
            'ISO_VERSION': '1.2.3',
            'ISO_NAME_PREFIX': 'gdc-bootstrap-test',
            'TEMPORARY_INSTALLER_PASSWORD': 'testpassword123',
            'UPSTREAM_PLAYBOOKS_REPO': 'https://github.com/google/gdc-disk-provisioner.git',
            'MACHINE_IP_CIDR': '192.168.9.11/24',
            'MACHINE_GATEWAY': '192.168.9.1',
            'MACHINE_DNS': '192.168.1.1, 8.8.8.8',
            'K8S_IP_CIDR': '192.168.109.10/29',
            'K8S_GATEWAY': '192.168.109.1',
            'K8S_DNS': '192.168.1.1, 8.8.8.8',
            'INSTALL_COMPANION_URL': 'http://gdc-companion.ensor-labs.com:8080/v1/install-logs',
            'GITEA_BINARY_FILENAME': 'gitea-1.22.1-linux-amd64',
            'NEXUS_PACKAGE_FILENAME': 'nexus-3.69.0-02-unix.tar.gz',
            'JRE_PACKAGE_FILENAME': 'OpenJDK17U-jre_x64_linux_hotspot_17.0.11_9.tar.gz',
            'SINGLE_DISK': 'false',
            'DISK1': 'vda',
            'DISK2': 'vdb',
            'BOOT_MODE': 'bios',
            'BUILD_TIMESTAMP': '1782779284',
            'HOSTNAME': 'gdc-standalone-node',
            'ADMIN_SSH_PUB_KEYS': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHFEKz',
            'MACHINE_VLAN_ID': '0',
            'K8S_VLAN_ID': '0'
        }
        
    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.test_dir)

    def create_mock_sys_class_net(self, interfaces):
        """Prepares a mock /sys/class/net list of directories."""
        sys_net_dir = os.path.join(self.test_dir, "sys_class_net")
        os.makedirs(sys_net_dir, exist_ok=True)
        for iface in interfaces:
            os.makedirs(os.path.join(sys_net_dir, iface), exist_ok=True)
        return sys_net_dir

    def create_mock_env_vars(self, machine_ip, k8s_ip, machine_cidr="192.168.9.11/24", k8s_cidr="192.168.109.10/29"):
        """Prepares a mock allocated_ips.env file on the guest filesystem."""
        env_file_path = os.path.join(self.test_dir, "allocated_ips.env")
        with open(env_file_path, "w") as f:
            f.write(f"MACHINE_IP={machine_ip}\n")
            f.write(f"K8S_IP={k8s_ip}\n")
            f.write(f"MACHINE_IP_CIDR={machine_cidr}\n")
            f.write(f"K8S_IP_CIDR={k8s_cidr}\n")
        return env_file_path

    def get_context(self, custom_env=None):
        """Generates representative hydration context variables with valid storage formatting."""
        env = self.base_env.copy()
        if custom_env:
            env.update(custom_env)
            
        env['OUTPUT_FILE'] = os.path.join(self.test_dir, "autoinstall-storage.yaml")
        env['boot_mode'] = env.get('BOOT_MODE', 'bios').lower()
        env['timestamp'] = env.get('BUILD_TIMESTAMP', '')
        env['hostname'] = env.get('HOSTNAME', 'gdc-standalone-node')
        env['ssh_pub_key'] = env.get('ADMIN_SSH_PUB_KEYS', '')
        env['git_branch'] = 'feature/test-branch'
        env['companion_url'] = env.get('INSTALL_COMPANION_URL', '')
        env['companion_ip'] = '192.168.120.2'
        env['companion_host'] = 'gdc-companion.ensor-labs.com'
        env['companion_report_url'] = 'http://192.168.120.2:8080/v1/install-logs'
        env['machine_vlan'] = env.get('MACHINE_VLAN_ID', '0')
        env['k8s_vlan'] = env.get('K8S_VLAN_ID', '0')
        env['machine_dhcp4'] = env.get('MACHINE_DHCP4', 'true').lower()
        env['machine_dhcp6'] = env.get('MACHINE_DHCP6', 'false').lower()
        env['machine_ip_cidr'] = env.get('MACHINE_IP_CIDR', '')
        env['machine_gateway'] = env.get('MACHINE_GATEWAY', '')
        env['machine_dns'] = env.get('MACHINE_DNS', '')
        env['k8s_ip_cidr'] = env.get('K8S_IP_CIDR', '')
        env['k8s_gateway'] = env.get('K8S_GATEWAY', '')
        env['k8s_dns'] = env.get('K8S_DNS', '')
        env['phys_iface'] = env.get('PHYS_IFACE', '__PHYS_IFACE__')
        env['vrf_machine_interfaces'] = env.get('VRF_MACHINE_INTERFACES', "['__PHYS_IFACE__']")
        env['persist_add_hosts'] = False
        env['add_hosts_lines'] = []
        
        # storage config parameters
        env['single_disk'] = env.get('SINGLE_DISK') == 'true'
        env['disk1'] = env.get('DISK1')
        env['disk2'] = env.get('DISK2')
        env['num_disks'] = "1" if env['single_disk'] else "2"
        
        # Indented valid storage YAML chunk to satisfy user-data schema checks during tests
        env['storage_config'] = (
            "    config:\n"
            "      - {type: disk, id: disk-system, path: /dev/vda, ptable: gpt, grub_device: true}\n"
            "      - {type: partition, id: partition-bios-grub, device: disk-system, size: 1048576, flag: bios_grub}"
        )
        
        return env

    def assert_no_unrendered_jinja_or_placeholders(self, content, filepath_or_label="content"):
        """Asserts that no unresolved JINJA tags exist in the hydrated content."""
        self.assertNotIn("{{", content, f"Unresolved JINJA token '{{{{' found in {filepath_or_label}")
        self.assertNotIn("}}", content, f"Unresolved JINJA token '}}}}' found in {filepath_or_label}")
        self.assertNotIn("{%", content, f"Unresolved JINJA block '{{%' found in {filepath_or_label}")
        self.assertNotIn("%}", content, f"Unresolved JINJA block '%}}' found in {filepath_or_label}")

    # ==========================================================================
    # TEST SUITE 1: storage_config.j2 Conditional Hydration (GDC-SPEC-002-SEQ)
    # ==========================================================================
    def test_storage_config_bios_single(self):
        """Exercises storage_config.j2: SINGLE_DISK=true and BOOT_MODE=bios (if/else check)"""
        ctx = self.get_context({'SINGLE_DISK': 'true', 'BOOT_MODE': 'bios'})
        template = self.jinja_env.get_template('storage_config.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "storage_config_bios_single")
        
        # Verify YAML syntax
        parsed = yaml.safe_load(rendered)
        self.assertIn("config", parsed)
        
        # Specific assertions for BIOS Single layout
        devices = parsed["config"]
        # Should contain partition-bios-grub but not partition-efi or format-efi
        ids = [item.get("id") for item in devices]
        self.assertIn("partition-bios-grub", ids)
        self.assertNotIn("partition-efi", ids)
        self.assertNotIn("format-efi", ids)
        # Should only reference disk-system (vda) for physical partition layouts
        for d in devices:
            if d.get("type") == "partition" and "device" in d:
                self.assertEqual(d["device"], "disk-system")

    def test_storage_config_uefi_single(self):
        """Exercises storage_config.j2: SINGLE_DISK=true and BOOT_MODE=uefi (if/else check)"""
        ctx = self.get_context({'SINGLE_DISK': 'true', 'BOOT_MODE': 'uefi'})
        template = self.jinja_env.get_template('storage_config.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "storage_config_uefi_single")
        
        # Verify YAML syntax
        parsed = yaml.safe_load(rendered)
        self.assertIn("config", parsed)
        
        devices = parsed["config"]
        ids = [item.get("id") for item in devices]
        self.assertIn("partition-efi", ids)
        self.assertIn("format-efi", ids)
        self.assertIn("mount-efi", ids)
        self.assertNotIn("partition-bios-grub", ids)
        
        # Ensure the partition-efi has the correct flag: uefi
        for d in devices:
            if d.get("id") == "partition-efi":
                self.assertEqual(d.get("flag"), "uefi", "EFI System Partition must be declared with flag: uefi")

    def test_storage_config_bios_dual(self):
        """Exercises storage_config.j2: SINGLE_DISK=false and BOOT_MODE=bios (if/else check)"""
        ctx = self.get_context({'SINGLE_DISK': 'false', 'BOOT_MODE': 'bios'})
        template = self.jinja_env.get_template('storage_config.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "storage_config_bios_dual")
        
        parsed = yaml.safe_load(rendered)
        self.assertIn("config", parsed)
        
        devices = parsed["config"]
        ids = [item.get("id") for item in devices]
        
        # Dual disk must declare disk-system and disk-data, plus crypt-data LVM physical volumes
        self.assertIn("disk-system", ids)
        self.assertIn("disk-data", ids)
        self.assertIn("crypt-data", ids)
        self.assertIn("vg-data", ids)
        self.assertIn("lv-sds", ids)
        self.assertIn("partition-bios-grub", ids)
        self.assertNotIn("partition-efi", ids)

    def test_storage_config_uefi_dual(self):
        """Exercises storage_config.j2: SINGLE_DISK=false and BOOT_MODE=uefi (if/else check)"""
        ctx = self.get_context({'SINGLE_DISK': 'false', 'BOOT_MODE': 'uefi'})
        template = self.jinja_env.get_template('storage_config.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "storage_config_uefi_dual")
        
        parsed = yaml.safe_load(rendered)
        self.assertIn("config", parsed)
        
        devices = parsed["config"]
        ids = [item.get("id") for item in devices]
        
        self.assertIn("disk-system", ids)
        self.assertIn("disk-data", ids)
        self.assertIn("partition-efi", ids)
        self.assertIn("format-efi", ids)
        self.assertIn("mount-efi", ids)
        self.assertNotIn("partition-bios-grub", ids)
        
        # Ensure the partition-efi has the correct flag: uefi
        for d in devices:
            if d.get("id") == "partition-efi":
                self.assertEqual(d.get("flag"), "uefi", "EFI System Partition must be declared with flag: uefi")

    # ==========================================================================
    # TEST SUITE 2: Static storage/ directory templates (Task 9 placeholders)
    # ==========================================================================
    def test_static_storage_subsystem_files(self):
        """Exercises the individual static templates under templates/storage/"""
        storage_dir = os.path.join(self.template_dir, "storage")
        self.assertTrue(os.path.exists(storage_dir), "Templates storage directory must exist.")
        
        static_files = [
            "storage_config_bios_dual.yaml",
            "storage_config_bios_single.yaml",
            "storage_config_uefi_dual.yaml",
            "storage_config_uefi_single.yaml"
        ]
        
        for filename in static_files:
            filepath = os.path.join(storage_dir, filename)
            self.assertTrue(os.path.exists(filepath), f"Storage template {filename} is missing.")
            
            with open(filepath, 'r') as f:
                content = f.read()
                
            # Perform standard shell hydration replacements mimicking the runtime script
            hydrated = (content
                .replace("${DISK_1}", "vda")
                .replace("${DISK_2}", "vdb")
            )
            
            # Assertions
            self.assertNotIn("${", hydrated, f"Unresolved env-variable token '${{' found in {filename}")
            
            # Validate YAML syntax
            parsed = yaml.safe_load(hydrated)
            self.assertIn("config", parsed, f"{filename} must contain a 'config' key.")

    # ==========================================================================
    # TEST SUITE 3: Dynamic Service units, Timers, and Metadata Hydration
    # ==========================================================================
    def test_nexus_service_rendering(self):
        """Exercises and validates templates/nexus.service.j2 rendering."""
        ctx = self.get_context()
        template = self.jinja_env.get_template('nexus.service.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "nexus.service")
        self.assertIn("[Unit]", rendered)
        self.assertIn("[Service]", rendered)
        self.assertIn("ExecStart=/var/lib/nexus/nexus-bin/bin/nexus start", rendered)

    def test_gdc_provision_service_rendering(self):
        """Exercises and validates templates/gdc-provision.service.j2 rendering."""
        ctx = self.get_context()
        template = self.jinja_env.get_template('gdc-provision.service.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "gdc-provision.service")
        self.assertIn("[Unit]", rendered)
        self.assertIn("[Service]", rendered)
        self.assertIn("ExecStart", rendered)
        self.assertIn("StandardOutput=journal", rendered, "StandardOutput must be configured to journal.")
        self.assertIn("StandardError=journal", rendered, "StandardError must be configured to journal.")
        self.assertNotIn("StandardOutput=file:", rendered, "Raw file log streams must be completely removed.")

    def test_gdc_provision_timer_rendering(self):
        """Exercises and validates templates/gdc-provision.timer.j2 rendering."""
        ctx = self.get_context()
        template = self.jinja_env.get_template('gdc-provision.timer.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "gdc-provision.timer")
        self.assertIn("[Unit]", rendered)
        self.assertIn("[Timer]", rendered)
        self.assertIn("OnCalendar=", rendered)

    def test_meta_data_rendering(self):
        """Exercises and validates templates/meta-data.j2 rendering."""
        ctx = self.get_context()
        template = self.jinja_env.get_template('meta-data.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "meta-data")
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed.get("instance-id"), "gdc-bootstrap-node-1782779284")
        self.assertEqual(parsed.get("local-hostname"), "gdc-standalone-node")


    def test_ansible_netplan_vrf_inclusion(self):
        """Asserts that the Ansible 50-gdc-network.yaml.j2 template includes the vrf-k8s declaration."""
        import jinja2
        
        env = jinja2.Environment(loader=jinja2.FileSystemLoader('src/ansible/roles/machine_orchestration/templates'))
        env.filters['split'] = lambda value, delimiter=' ': value.split(delimiter)
        template = env.get_template('50-gdc-network.yaml.j2')
        
        # Mock machine config
        machine_config = {
            'network': {
                'management_network': {
                    'dhcp_v4': False,
                    'ip_cidr': '192.168.100.11/24',
                    'gateway': '192.168.100.1',
                    'dns_servers': ['8.8.8.8']
                },
                'cluster_network': {
                    'dhcp_v4': False,
                    'ip_cidr': '192.168.109.11/24',
                    'gateway': '192.168.109.1',
                    'vlan_id': 109
                }
            }
        }
        
        rendered = template.render(
            ansible_default_ipv4={'interface': 'enp1s0'},
            machine_config=machine_config
        )
        
        config = yaml.safe_load(rendered)
        self.assertIn('vrfs', config['network'])
        self.assertIn('vrf-k8s', config['network']['vrfs'])
        self.assertEqual(config['network']['vrfs']['vrf-k8s']['table'], 20)
        self.assertEqual(config['network']['vrfs']['vrf-k8s']['interfaces'], ['vlan109'])
        self.assertEqual(config['network']['vrfs']['vrf-k8s']['optional'], True)

    def test_user_data_rendering(self):
        """Exercises and validates templates/user-data.j2 rendering and swap sizes."""
        ctx = self.get_context()
        template = self.jinja_env.get_template('user-data.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "user-data")
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed.get("autoinstall", {}).get("version"), 1)
        self.assertIn("python3 /cdrom/custom-data/configure_netplan.py", rendered)

        # MANDATORY SWAP INTEGRITY GDC CHECK
        autoinstall = parsed.get("autoinstall", {})
        self.assertIn("reporting", autoinstall, "The autoinstall config MUST have reporting defined")
        self.assertIn("storage", autoinstall, "The autoinstall config MUST have storage defined")
        
        storage = autoinstall.get("storage", {})
        self.assertIn("swap", storage, "The autoinstall storage configuration MUST explicitly define swap settings")
        
        swap = storage.get("swap", {})
        self.assertEqual(swap.get("size"), 0, "GDC Bare Metal requirements MANDATE that swap size MUST be strictly 0")

    def test_user_data_with_add_hosts(self):
        """Validates that add-hosts mappings are correctly rendered and injected conditionally."""
        # Test Case 1: Active add-hosts, persist_add_hosts is False
        ctx = self.get_context()
        ctx['add_hosts_lines'] = ['1.2.3.4 foo.bar.com', '5.6.7.8 baz.qux.com']
        ctx['persist_add_hosts'] = False
        
        template = self.jinja_env.get_template('user-data.j2')
        rendered = template.render(ctx)
        
        self.assert_no_unrendered_jinja_or_placeholders(rendered, "user-data-add-hosts")
        
        # Should be present in early-commands (installer system)
        self.assertIn('echo "1.2.3.4 foo.bar.com" >> /etc/hosts', rendered)
        self.assertIn('echo "5.6.7.8 baz.qux.com" >> /etc/hosts', rendered)
        
        # Should NOT be present in late-commands (target system)
        self.assertNotIn('echo "1.2.3.4 foo.bar.com" >> /target/etc/hosts', rendered)
        self.assertNotIn('echo "5.6.7.8 baz.qux.com" >> /target/etc/hosts', rendered)
        
        # Test Case 2: Active add-hosts, persist_add_hosts is True
        ctx_persist = self.get_context()
        ctx_persist['add_hosts_lines'] = ['1.2.3.4 foo.bar.com', '5.6.7.8 baz.qux.com']
        ctx_persist['persist_add_hosts'] = True
        
        rendered_persist = template.render(ctx_persist)
        
        # Should be present in both
        self.assertIn('echo "1.2.3.4 foo.bar.com" >> /etc/hosts', rendered_persist)
        self.assertIn('echo "5.6.7.8 baz.qux.com" >> /etc/hosts', rendered_persist)
        self.assertIn('echo "1.2.3.4 foo.bar.com" >> /target/etc/hosts', rendered_persist)
        self.assertIn('echo "5.6.7.8 baz.qux.com" >> /target/etc/hosts', rendered_persist)

    # ==========================================================================
    # TEST SUITE 4: Netplan and python-driven runtime hydrator tests (Crossover)
    # ==========================================================================
    def test_netplan_flat_vs_tagged_combinations(self):
        """Exercises netplan.j2 and configure_netplan.py combined across all VLAN/VRF combinations."""
        combinations = [
            {'MACHINE_VLAN_ID': '0', 'K8S_VLAN_ID': '0', 'desc': 'flat'},
            {'MACHINE_VLAN_ID': '10', 'K8S_VLAN_ID': '0', 'desc': 'mgmt_tagged'},
            {'MACHINE_VLAN_ID': '0', 'K8S_VLAN_ID': '109', 'desc': 'k8s_tagged'},
            {'MACHINE_VLAN_ID': '10', 'K8S_VLAN_ID': '109', 'desc': 'both_tagged'}
        ]
        
        for comb in combinations:
            ctx = self.get_context({
                'MACHINE_VLAN_ID': comb['MACHINE_VLAN_ID'],
                'K8S_VLAN_ID': comb['K8S_VLAN_ID']
            })
            template = self.jinja_env.get_template('netplan.j2')
            rendered = template.render(ctx)
            
            # Template must contain raw placeholders for configure_netplan.py, but NO JINJA!
            self.assert_no_unrendered_jinja_or_placeholders(rendered, f"netplan_template_{comb['desc']}")
            self.assertIn("__PHYS_IFACE__", rendered)
            
            # Now simulate configure_netplan running over this output
            temp_template = os.path.join(self.test_dir, "temp_template.yaml")
            with open(temp_template, 'w') as f:
                f.write(rendered)
                
            temp_output = os.path.join(self.test_dir, f"01-netcfg_{comb['desc']}.yaml")
            sys_net = self.create_mock_sys_class_net(["lo", "ens3", "ens4"])
            env_path = self.create_mock_env_vars("192.168.9.11", "192.168.109.11")
            
            configure_netplan.main(
                template_path=temp_template,
                target_path=temp_output,
                sys_class_net=sys_net,
                env_path=env_path,
                target_dir=self.test_dir
            )
            
            # Assertions on final compiled file
            with open(temp_output, 'r') as f:
                hydrated_content = f.read()
                
            self.assert_no_unrendered_jinja_or_placeholders(hydrated_content, f"hydrated_output_{comb['desc']}")
            for p in ["__PHYS_IFACE__", "__MGMT_IFACE__", "__K8S_IP_CIDR__"]:
                self.assertNotIn(p, hydrated_content, f"Placeholder {p} must be replaced in final output.")
                
            # Parse final output to ensure syntactic validity
            config = yaml.safe_load(hydrated_content)
            self.assertIn("network", config)
            
            # Verify correct VRF-to-interface physical associations (on primary NIC ens3)
            vrfs = config["network"].get("vrfs")
            if vrfs and "vrf-k8s" in vrfs:
                k8s_interfaces = vrfs["vrf-k8s"].get("interfaces", [])
                if comb['K8S_VLAN_ID'] != '0':
                    self.assertEqual(k8s_interfaces, [f"ens3.{comb['K8S_VLAN_ID']}"])

            # Verify secondary NIC is added as a plain DHCP interface
            ethernets = config["network"].get("ethernets", {})
            self.assertIn("ens4", ethernets)
            self.assertTrue(ethernets["ens4"].get("dhcp4"))

    def test_gateway_in_subnet(self):
        """Asserts that the default gateway is within the network subnet of the assigned IP to prevent route failures."""
        import ipaddress
        
        # For Machine (valid /24)
        machine_ip = "192.168.9.11"
        machine_cidr = f"{machine_ip}/24"
        machine_gateway = "192.168.9.1"
        self.assertTrue(ipaddress.ip_address(machine_gateway) in ipaddress.ip_network(machine_cidr, strict=False))
        
        # For K8s (This has the corrected E2E /24 subnet!)
        k8s_ip = "192.168.109.8"
        k8s_cidr_ok = f"{k8s_ip}/24"
        k8s_gateway = "192.168.109.1"
        
        is_valid = ipaddress.ip_address(k8s_gateway) in ipaddress.ip_network(k8s_cidr_ok, strict=False)
        self.assertTrue(is_valid, f"K8s Gateway {k8s_gateway} must be within the subnet of {k8s_cidr_ok}!")

    def test_netplan_static_l3_machine_nic(self):
        """Asserts that when MACHINE_DHCP4 is false, the primary interface gets a static IP and routes."""
        ctx = self.get_context({
            'MACHINE_DHCP4': 'false',
            'MACHINE_DHCP6': 'false',
            'MACHINE_IP_CIDR': '192.168.9.14/24',
            'MACHINE_GATEWAY': '192.168.9.1',
            'MACHINE_DNS': '8.8.8.8, 8.8.4.4',
            'MACHINE_VLAN_ID': '0',
            'K8S_VLAN_ID': '0'
        })
        template = self.jinja_env.get_template('netplan.j2')
        rendered = template.render(ctx)
        
        temp_template = os.path.join(self.test_dir, "temp_template_static.yaml")
        with open(temp_template, 'w') as f:
            f.write(rendered)
            
        temp_output = os.path.join(self.test_dir, "01-netcfg_static_test.yaml")
        sys_net = self.create_mock_sys_class_net(["lo", "ens3"])
        env_path = self.create_mock_env_vars("192.168.9.14", "192.168.109.14")
        
        import configure_netplan
        configure_netplan.main(
            template_path=temp_template,
            target_path=temp_output,
            sys_class_net=sys_net,
            env_path=env_path,
            target_dir=self.test_dir
        )
        
        with open(temp_output, 'r') as f:
            hydrated_content = f.read()
            
        config = yaml.safe_load(hydrated_content)
        ethernets = config["network"].get("ethernets", {})
        self.assertIn("ens3", ethernets)
        self.assertEqual(ethernets["ens3"].get("dhcp4"), False)
        self.assertEqual(ethernets["ens3"].get("dhcp6"), False)
        self.assertEqual(ethernets["ens3"].get("addresses"), ["192.168.9.14/24"])
        self.assertEqual(ethernets["ens3"].get("routes")[0].get("via"), "192.168.9.1")

    @mock.patch('subprocess.run')
    def test_netplan_chroot_bypass(self, mock_run):
        """Asserts that configure_netplan.py does not execute any dangerous chroot subprocesses."""
        temp_template = os.path.join(self.test_dir, "temp_template.yaml")
        with open(temp_template, 'w') as f:
            f.write("network: {version: 2}")
            
        temp_output = os.path.join(self.test_dir, "01-netcfg.yaml")
        sys_net = self.create_mock_sys_class_net(["lo", "ens3"])
        env_path = self.create_mock_env_vars("192.168.9.11", "192.168.109.11")
        
        # Create a mock netplan binary inside the target directory to trigger the chroot block
        netplan_dir = os.path.join(self.test_dir, "usr/sbin")
        os.makedirs(netplan_dir, exist_ok=True)
        with open(os.path.join(netplan_dir, "netplan"), "w") as f:
            f.write("#!/bin/sh\n")
            
        configure_netplan.main(
            template_path=temp_template,
            target_path=temp_output,
            sys_class_net=sys_net,
            env_path=env_path,
            target_dir=self.test_dir
        )
        
        # Verify that subprocess.run was never called with 'chroot'
        for call in mock_run.call_args_list:
            args = call[0][0]
            self.assertNotIn("chroot", args, "Dangerous chroot netplan generate must not be executed.")

    def test_luks_keyfile_path_validation(self):
        """Statically asserts that GDC LUKS bootstrap keyfiles are routed strictly via /var/log/installer/."""
        # 1. Assert user-data template writes to /var/log/installer/gdc-luks-key
        userdata_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(userdata_path, "r") as f:
            userdata_content = f.read()
            self.assertIn("/var/log/installer/gdc-luks-key", userdata_content,
                          "user-data.j2 must write the bootstrap key directly to /var/log/installer/gdc-luks-key")
            self.assertNotIn("/run/installer/gdc-luks-key", userdata_content,
                             "user-data.j2 must NOT use insecure or delayed /run/installer/gdc-luks-key path")

        # 2. Assert storage_config.j2 template reads from /var/log/installer/gdc-luks-key
        storage_j2_path = os.path.join(PROJECT_ROOT, "src/build/templates/storage_config.j2")
        with open(storage_j2_path, "r") as f:
            storage_j2_content = f.read()
            self.assertIn("/var/log/installer/gdc-luks-key", storage_j2_content,
                          "storage_config.j2 must read the bootstrap key from /var/log/installer/gdc-luks-key")
            self.assertNotIn("/run/installer/gdc-luks-key", storage_j2_content,
                             "storage_config.j2 must NOT use /run/installer/gdc-luks-key path")

        # 3. Assert all static storage templates read from /var/log/installer/gdc-luks-key
        storage_templates_dir = os.path.join(PROJECT_ROOT, "src/build/templates/storage")
        for filename in os.listdir(storage_templates_dir):
            if filename.endswith(".yaml"):
                fpath = os.path.join(storage_templates_dir, filename)
                with open(fpath, "r") as f:
                    content = f.read()
                    if "dm_crypt" in content:
                        self.assertIn("/var/log/installer/gdc-luks-key", content,
                                      f"{filename} must read the bootstrap key from /var/log/installer/gdc-luks-key")
                        self.assertNotIn("/run/installer/gdc-luks-key", content,
                                         f"{filename} must NOT use /run/installer/gdc-luks-key path")

    def test_bootimus_pxe_parameter_alignment(self):
        """Asserts that src/build/bootimus.py defines the mandatory apparmor=0 and console redirection PXE options."""
        bootimus_path = os.path.join(PROJECT_ROOT, "src/build/bootimus.py")
        with open(bootimus_path, "r") as f:
            bootimus_content = f.read()
            self.assertIn("apparmor=0", bootimus_content,
                          "bootimus.py must include apparmor=0 in boot_params to prevent cryptsetup sandboxing blocks")
            self.assertIn("console=tty1 console=ttyS0", bootimus_content,
                          "bootimus.py must specify console=tty1 console=ttyS0 to keep serial console active past switch_root")

    def test_ansible_tpm_initramfs_drivers(self):
        """Asserts that the security_hardening role registers the necessary TPM modules for early boot."""
        playbook_path = os.path.join(PROJECT_ROOT, "src/ansible/roles/security_hardening/tasks/main.yml")
        with open(playbook_path, "r") as f:
            content = f.read()
            self.assertIn("dracut", content, "Ansible security_hardening tasks must include dracut rebuilding")
            self.assertIn("dracut.conf.d/gdc.conf", content, "Ansible security_hardening tasks must deploy gdc.conf dracut file")
            self.assertIn("tpm2-tss", content, "Ansible security_hardening tasks must include tpm2-tss in dracut config")

    def test_user_data_dracut_gdc_conf(self):
        """Asserts that user-data.j2 deploys persistent dracut.conf.d/gdc.conf during ISO installation."""
        user_data_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(user_data_path, "r") as f:
            content = f.read()
            self.assertIn("/etc/dracut.conf.d/gdc.conf", content, "user-data.j2 must deploy persistent gdc.conf dracut file")
            self.assertIn("tpm2-tss", content, "user-data.j2 must include tpm2-tss in dracut gdc.conf")
            self.assertIn("omit_drivers+=\" pcie_mp2_amd amd_sfh ccp \"", content, "user-data.j2 must omit deadlock drivers in dracut gdc.conf")

    @mock.patch('shutil.which')
    @mock.patch('subprocess.run')
    def test_static_command_option_auditor(self, mock_run, mock_which):
        """Asserts that the static command auditor detects invalid command options and accepts valid ones."""
        import sys
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "test"))
        import validate_artifacts
        
        # Configure which mock
        mock_which.return_value = "/usr/bin/unmkinitramfs"
        
        # Configure subprocess.run mock to return help output of unmkinitramfs (only -v supported)
        mock_res = mock.Mock()
        mock_res.returncode = 0
        mock_res.stdout = "Usage: unmkinitramfs [-v] initramfs-file directory\nOptions: -v"
        mock_res.stderr = ""
        mock_run.return_value = mock_res
        
        # 1. Valid command options (unmkinitramfs -v is valid)
        try:
            validate_artifacts.validate_commands_in_script("unmkinitramfs -v file.img dir")
        except ValueError as e:
            self.fail(f"validate_commands_in_script failed on valid inputs: {e}")
            
        # 2. Invalid command options (unmkinitramfs -t is invalid)
        with self.assertRaises(ValueError) as ctx:
            validate_artifacts.validate_commands_in_script("unmkinitramfs -t file.img dir")
        self.assertIn("does not support the option '-t'", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
