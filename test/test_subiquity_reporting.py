#!/usr/bin/env python3

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

import os
import sys
import unittest
import tempfile

# Set up paths so we can import src/build modules cleanly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))

import render_templates

class TestSubiquityReporting(unittest.TestCase):
    def test_reporting_webhook_is_present_when_companion_true(self):
        """Validates that the webhook reporting and phone-home blocks are generated when GDC_COMPANION=TRUE."""
        env = {
            'GDC_COMPANION': 'TRUE',
            'ISO_VERSION': '1.0',
            'TEMPORARY_INSTALLER_PASSWORD': 'test',
            'UPSTREAM_PLAYBOOKS_REPO': 'test',
            'BOOTSTRAP_MACHINE_IP_CIDR': 'test',
            'BOOTSTRAP_MACHINE_GATEWAY': 'test',
            'BOOTSTRAP_K8S_IP_CIDR': 'test',
            'BOOTSTRAP_K8S_GATEWAY': 'test',
            'INSTALL_COMPANION_URL': 'test',
            'GITEA_BINARY_FILENAME': 'test',
            'NEXUS_PACKAGE_FILENAME': 'test',
            'JRE_PACKAGE_FILENAME': 'test',
            'companion_url': 'http://test'
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, 'nocloud'))
            template_dir = os.path.join(PROJECT_ROOT, "src/build/templates")
            render_templates.render_templates(template_dir, temp_dir, env)
            
            userdata_path = os.path.join(temp_dir, "nocloud/user-data")
            with open(userdata_path, "r") as f:
                content = f.read()
            
        self.assertIn("reporting:", content, "The 'reporting' block must exist in user-data when GDC_COMPANION=TRUE")
        self.assertIn("webhook:", content, "The 'webhook' configuration must exist inside reporting")
        self.assertIn("endpoint:", content, "The webhook must define an endpoint")
        self.assertIn("level: INFO", content, "The webhook log level must be INFO")
        self.assertIn("phone_home:", content, "The 'phone_home' block must exist in user-data when GDC_COMPANION=TRUE")
        self.assertIn("COMPANION_HEALTH=", content, "Companion health endpoint derivation must exist")
        self.assertIn("curl -s -f -I -m 5", content, "Probe must use silent fail-fast flags (-f -s -I -m 5)")
        self.assertIn("curl -s -f -k -I -m 5", content, "Probe must support -k fallback for internal/private CAs")
        self.assertIn(">/dev/null 2>&1", content, "Probe must use POSIX shell redirection >/dev/null 2>&1")
        self.assertNotIn("&>/dev/null", content, "Bashism &>/dev/null must not exist in user-data probe scripts")

    def test_reporting_webhook_is_absent_when_companion_false(self):
        """Validates that the webhook and phone-home are omitted when GDC_COMPANION is FALSE."""
        env = {
            'GDC_COMPANION': 'FALSE',
            'ISO_VERSION': '1.0',
            'TEMPORARY_INSTALLER_PASSWORD': 'test',
            'UPSTREAM_PLAYBOOKS_REPO': 'test',
            'BOOTSTRAP_MACHINE_IP_CIDR': 'test',
            'BOOTSTRAP_MACHINE_GATEWAY': 'test',
            'BOOTSTRAP_K8S_IP_CIDR': 'test',
            'BOOTSTRAP_K8S_GATEWAY': 'test',
            'INSTALL_COMPANION_URL': 'test',
            'GITEA_BINARY_FILENAME': 'test',
            'NEXUS_PACKAGE_FILENAME': 'test',
            'JRE_PACKAGE_FILENAME': 'test',
            'companion_url': 'http://test'
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, 'nocloud'))
            template_dir = os.path.join(PROJECT_ROOT, "src/build/templates")
            render_templates.render_templates(template_dir, temp_dir, env)
            
            userdata_path = os.path.join(temp_dir, "nocloud/user-data")
            with open(userdata_path, "r") as f:
                content = f.read()
            
        self.assertNotIn("reporting:", content, "The 'reporting' block must NOT exist in user-data when GDC_COMPANION=FALSE")
        self.assertNotIn("phone_home:", content, "The 'phone_home' block must NOT exist in user-data when GDC_COMPANION=FALSE")
        self.assertIn("Connectivity checking skipped", content, "The connectivity check should be skipped when GDC_COMPANION=FALSE")

    def test_autoinstall_network_dhcp_identifier_and_critical(self):
        """Validates that autoinstall network block enforces dhcp-identifier: mac and critical: true to prevent IP churn."""
        env = {
            'GDC_COMPANION': 'TRUE',
            'ISO_VERSION': '1.0',
            'TEMPORARY_INSTALLER_PASSWORD': 'test',
            'UPSTREAM_PLAYBOOKS_REPO': 'test',
            'BOOTSTRAP_MACHINE_IP_CIDR': 'test',
            'BOOTSTRAP_MACHINE_GATEWAY': 'test',
            'BOOTSTRAP_K8S_IP_CIDR': 'test',
            'BOOTSTRAP_K8S_GATEWAY': 'test',
            'INSTALL_COMPANION_URL': 'test',
            'GITEA_BINARY_FILENAME': 'test',
            'NEXUS_PACKAGE_FILENAME': 'test',
            'JRE_PACKAGE_FILENAME': 'test',
            'companion_url': 'http://test'
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, 'nocloud'))
            template_dir = os.path.join(PROJECT_ROOT, "src/build/templates")
            render_templates.render_templates(template_dir, temp_dir, env)
            
            userdata_path = os.path.join(temp_dir, "nocloud/user-data")
            with open(userdata_path, "r") as f:
                content = f.read()

        self.assertIn("dhcp-identifier: mac", content, "Autoinstall network config must set 'dhcp-identifier: mac' to preserve lease")
        self.assertIn("critical: true", content, "Autoinstall network config must set 'critical: true' to prevent link teardown")

    def test_bootcmd_tcp_keepalive_sysctl(self):
        """Validates that bootcmd configures aggressive TCP keepalives to prevent hang on dead sockets."""
        env = {
            'GDC_COMPANION': 'TRUE',
            'ISO_VERSION': '1.0',
            'TEMPORARY_INSTALLER_PASSWORD': 'test',
            'UPSTREAM_PLAYBOOKS_REPO': 'test',
            'BOOTSTRAP_MACHINE_IP_CIDR': 'test',
            'BOOTSTRAP_MACHINE_GATEWAY': 'test',
            'BOOTSTRAP_K8S_IP_CIDR': 'test',
            'BOOTSTRAP_K8S_GATEWAY': 'test',
            'INSTALL_COMPANION_URL': 'test',
            'GITEA_BINARY_FILENAME': 'test',
            'NEXUS_PACKAGE_FILENAME': 'test',
            'JRE_PACKAGE_FILENAME': 'test',
            'companion_url': 'http://test'
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, 'nocloud'))
            template_dir = os.path.join(PROJECT_ROOT, "src/build/templates")
            render_templates.render_templates(template_dir, temp_dir, env)
            
            userdata_path = os.path.join(temp_dir, "nocloud/user-data")
            with open(userdata_path, "r") as f:
                content = f.read()

        self.assertIn("sysctl -w net.ipv4.tcp_keepalive_time=15", content, "bootcmd must tune tcp_keepalive_time")
        self.assertIn("sysctl -w net.ipv4.tcp_retries2=5", content, "bootcmd must tune tcp_retries2")

    def test_vendor_data_rendered(self):
        """Validates that nocloud/vendor-data is generated to prevent cloud-init probe retries."""
        env = {
            'TEMPORARY_INSTALLER_PASSWORD': 'test',
            'UPSTREAM_PLAYBOOKS_REPO': 'test',
            'BOOTSTRAP_MACHINE_IP_CIDR': 'test',
            'BOOTSTRAP_MACHINE_GATEWAY': 'test',
            'BOOTSTRAP_K8S_IP_CIDR': 'test',
            'BOOTSTRAP_K8S_GATEWAY': 'test',
            'INSTALL_COMPANION_URL': 'test',
            'GITEA_BINARY_FILENAME': 'test',
            'NEXUS_PACKAGE_FILENAME': 'test',
            'JRE_PACKAGE_FILENAME': 'test'
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, 'nocloud'))
            template_dir = os.path.join(PROJECT_ROOT, "src/build/templates")
            render_templates.render_templates(template_dir, temp_dir, env)
            
            vendordata_path = os.path.join(temp_dir, "nocloud/vendor-data")
            self.assertTrue(os.path.exists(vendordata_path), "nocloud/vendor-data must exist")
            with open(vendordata_path, "r") as f:
                content = f.read()
            self.assertEqual(content, "#cloud-config\n", "vendor-data must contain '#cloud-config\\n'")

if __name__ == "__main__":
    unittest.main()
