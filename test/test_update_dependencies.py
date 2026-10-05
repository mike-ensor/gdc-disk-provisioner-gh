#!/usr/bin/env python3
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

"""Unit tests for GDC Dependency and Package Update Engine."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.build import update_dependencies


class TestUpdateDependenciesEngine(unittest.TestCase):
    def setUp(self):
        self.sample_deps = {
            "KUBESTR_VERSION": "0.4.48",
            "KUBESTR_PACKAGE_URL": "https://github.com/kastenhq/kubestr/releases/download/v0.4.48/kubestr_0.4.48_Linux_amd64.tar.gz",
            "KUBESTR_PACKAGE_FILENAME": "kubestr_0.4.48_Linux_amd64.tar.gz",
            "KUBESTR_PACKAGE_SHA256": "e0ca0b73037954d47dc35bade49b8539b8f2beb1d00d4459bcf4163f4959f074",
            "HELM_VERSION": "3.22.0",
            "HELM_PACKAGE_URL": "https://get.helm.sh/helm-v3.22.0-linux-amd64.tar.gz",
            "HELM_PACKAGE_FILENAME": "helm-v3.22.0-linux-amd64.tar.gz",
            "HELM_PACKAGE_SHA256": "1e4ab49e429626cf6c6958d914248b78c9730803c2751b87627e171dc800e7bb",
            "GITEA_BINARY_FILENAME": "gitea-1.22.1-linux-amd64",
            "STEP_CLI_FILENAME": "step-cli_0.26.1_amd64.deb",
            "GCLOUD_SDK_FILENAME": "google-cloud-cli-575.0.0-linux-x86_64.tar.gz",
            "JRE_PACKAGE_FILENAME": "OpenJDK17U-jre_x64_linux_hotspot_17.0.11_9.tar.gz",
            "NEXUS_PACKAGE_FILENAME": "nexus-3.69.0-02-unix.tar.gz",
        }

    def test_parse_env_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("# Sample env\n")
            tf.write("FOO=bar\n")
            tf.write("export BAZ=\"qux\"\n")
            tf.write("SPACED = 'value with spaces'\n")
            tf.flush()
            temp_path = tf.name

        try:
            parsed = update_dependencies.parse_env_file(temp_path)
            self.assertEqual(parsed.get("FOO"), "bar")
            self.assertEqual(parsed.get("BAZ"), "qux")
            self.assertEqual(parsed.get("SPACED"), "value with spaces")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("src.build.update_dependencies.http_get_json")
    def test_check_upstream_versions(self, mock_get_json):
        def side_effect(url, timeout=15):
            if "kubestr/releases/latest" in url:
                return {"tag_name": "v0.4.49"}
            elif "helm/releases" in url:
                return [{"tag_name": "v3.22.0", "prerelease": False}]
            elif "gitea/tags" in url:
                return [{"name": "v1.22.6"}]
            elif "smallstep/cli/releases/latest" in url:
                return {"tag_name": "v0.31.0"}
            elif "components-2.json" in url:
                return {"version": "587.0.0"}
            elif "adoptium.net" in url:
                return [{"release_name": "jdk-17.0.20.1+1"}]
            elif "nexus-public/tags" in url:
                return [{"name": "release-3.96.4-01"}]
            return {}

        mock_get_json.side_effect = side_effect
        results = update_dependencies.check_upstream_versions(self.sample_deps)

        self.assertIn("kubestr", results)
        self.assertEqual(results["kubestr"]["current"], "0.4.48")
        self.assertEqual(results["kubestr"]["latest"], "0.4.49")
        self.assertTrue(results["kubestr"]["update_available"])

        self.assertIn("helm", results)
        self.assertEqual(results["helm"]["current"], "3.22.0")
        self.assertEqual(results["helm"]["latest"], "3.22.0")
        self.assertFalse(results["helm"]["update_available"])

        self.assertIn("gitea", results)
        self.assertEqual(results["gitea"]["latest"], "1.22.6")
        self.assertTrue(results["gitea"]["update_available"])

    def test_update_dependencies_env_rewrites_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("KUBESTR_VERSION=0.4.48\n")
            tf.write("KUBESTR_PACKAGE_URL=https://old.url/kubestr.tar.gz\n")
            tf.write("KUBESTR_PACKAGE_FILENAME=old-kubestr.tar.gz\n")
            tf.write("KUBESTR_PACKAGE_SHA256=oldsha256\n")
            tf.flush()
            temp_path = tf.name

        try:
            with patch.object(update_dependencies, "DEPS_ENV_PATH", temp_path):
                new_info = {
                    "latest": "0.4.49",
                    "url": "https://new.url/kubestr_0.4.49.tar.gz",
                    "filename": "kubestr_0.4.49.tar.gz",
                    "sha256": "newsha256sum12345",
                }
                success = update_dependencies.update_dependencies_env("kubestr", new_info)
                self.assertTrue(success)

                with open(temp_path, "r", encoding="utf-8") as f:
                    updated = f.read()

                self.assertIn("KUBESTR_VERSION=0.4.49", updated)
                self.assertIn("KUBESTR_PACKAGE_URL=https://new.url/kubestr_0.4.49.tar.gz", updated)
                self.assertIn("KUBESTR_PACKAGE_FILENAME=kubestr_0.4.49.tar.gz", updated)
                self.assertIn("KUBESTR_PACKAGE_SHA256=newsha256sum12345", updated)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(temp_path + ".bak"):
                os.remove(temp_path + ".bak")

    def test_add_package_dependency_without_install(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("packages_to_include:\n  platform_required:\n    - curl\n  customer_added: []\n")
            tf.flush()
            temp_pkg_path = tf.name

        try:
            with patch.object(update_dependencies, "PACKAGES_CONFIG_PATH", temp_pkg_path):
                ok = update_dependencies.add_package_dependency("dnsmasq", install=False)
                self.assertTrue(ok)

                with open(temp_pkg_path, "r", encoding="utf-8") as f:
                    updated = f.read()

                self.assertIn("customer_added:\n    - \"dnsmasq\"", updated)
        finally:
            if os.path.exists(temp_pkg_path):
                os.remove(temp_pkg_path)

    def test_add_package_dependency_with_install(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tf_pkg, \
             tempfile.NamedTemporaryFile("w", delete=False) as tf_vars, \
             tempfile.NamedTemporaryFile("w", delete=False) as tf_j2:
            tf_pkg.write("packages_to_include:\n  platform_required:\n    - curl\n  customer_added: []\n")
            tf_vars.write("customer_install_packages: []\n")
            tf_j2.write("customer_install_packages: []\n")
            tf_pkg.flush()
            tf_vars.flush()
            tf_j2.flush()
            p_pkg, p_vars, p_j2 = tf_pkg.name, tf_vars.name, tf_j2.name

        try:
            with patch.object(update_dependencies, "PACKAGES_CONFIG_PATH", p_pkg), \
                 patch.object(update_dependencies, "ANSIBLE_VARS_PATH", p_vars), \
                 patch.object(update_dependencies, "ANSIBLE_VARS_J2_PATH", p_j2):
                ok = update_dependencies.add_package_dependency("dnsmasq", install=True)
                self.assertTrue(ok)

                with open(p_pkg, "r", encoding="utf-8") as f:
                    self.assertIn("customer_added:\n    - \"dnsmasq\"", f.read())
                with open(p_vars, "r", encoding="utf-8") as f:
                    self.assertIn("customer_install_packages:\n  - \"dnsmasq\"", f.read())
                with open(p_j2, "r", encoding="utf-8") as f:
                    self.assertIn("customer_install_packages:\n  - \"dnsmasq\"", f.read())
        finally:
            for p in [p_pkg, p_vars, p_j2]:
                if os.path.exists(p):
                    os.remove(p)

    def test_add_binary_dependency(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write('# Comment\nCACHED_BINARY_FILES="gdc-collector"\n')
            tf.flush()
            temp_deps_path = tf.name

        try:
            with patch.object(update_dependencies, "DEPS_ENV_PATH", temp_deps_path):
                ok = update_dependencies.add_binary_dependency(
                    name="custom-cli",
                    version="1.5.0",
                    url="https://example.com/custom-cli-v1.5.0.tar.gz",
                    sha256="abc12345def67890",
                )
                self.assertTrue(ok)

                with open(temp_deps_path, "r", encoding="utf-8") as f:
                    updated = f.read()

                self.assertIn("CUSTOM_CLI_VERSION=1.5.0", updated)
                self.assertIn("CUSTOM_CLI_PACKAGE_URL=https://example.com/custom-cli-v1.5.0.tar.gz", updated)
                self.assertIn("CUSTOM_CLI_PACKAGE_FILENAME=custom-cli-v1.5.0.tar.gz", updated)
                self.assertIn("CUSTOM_CLI_PACKAGE_SHA256=abc12345def67890", updated)
                self.assertIn("${CUSTOM_CLI_PACKAGE_FILENAME}", updated)
        finally:
            if os.path.exists(temp_deps_path):
                os.remove(temp_deps_path)
            if os.path.exists(temp_deps_path + ".bak"):
                os.remove(temp_deps_path + ".bak")


if __name__ == "__main__":
    unittest.main()
