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

if __name__ == "__main__":
    unittest.main()
