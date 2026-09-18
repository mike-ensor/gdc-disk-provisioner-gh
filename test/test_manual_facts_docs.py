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

"""Unit tests verifying documentation for manual facts and state reset."""

import os
import unittest

DOC_PATH = os.path.join(
    os.path.dirname(__file__),
    "../docs/on-device-ansible.md"
)

class TestManualFactsDocs(unittest.TestCase):
    def test_doc_mentions_manual_facts_and_companion_export(self):
        self.assertTrue(os.path.exists(DOC_PATH))
        with open(DOC_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("gdc-fact-manual.json", content)
        self.assertIn("gdc-node-ops.sh", content)
        self.assertIn("push-facts", content)
        self.assertIn("Share / Download JSON", content)
        self.assertIn("machine-schema.json", content)
        self.assertIn("/var/gdc-install/state/cluster-ready.json", content)

if __name__ == "__main__":
    unittest.main()
