#!/usr/bin/env python3
import os
import sys
import unittest
from unittest import mock
import yaml

# Set up paths so we can import src/build modules cleanly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src/build"))

from render_templates import render_templates

class TestSubiquityReporting(unittest.TestCase):
    def test_reporting_webhook_is_present(self):
        """Validates that the webhook reporting block is correctly generated in user-data."""
        userdata_path = os.path.join(PROJECT_ROOT, "src/build/templates/user-data.j2")
        with open(userdata_path, "r") as f:
            content = f.read()
            
        self.assertIn("reporting:", content, "The 'reporting' block must exist in user-data")
        self.assertIn("webhook:", content, "The 'webhook' configuration must exist inside reporting")
        self.assertIn("endpoint:", content, "The webhook must define an endpoint")
        self.assertIn("level: INFO", content, "The webhook log level must be INFO")

if __name__ == "__main__":
    unittest.main()
