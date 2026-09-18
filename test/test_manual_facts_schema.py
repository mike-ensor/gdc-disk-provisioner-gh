import json
import os
import unittest
import jsonschema

SCHEMA_PATH = "/d/projects/google/gdc-companion/docs/machine-schema.json"
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

class TestManualFactsSchema(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(SCHEMA_PATH), f"Schema not found at {SCHEMA_PATH}")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_valid_manual_fact_fixture(self):
        valid_path = os.path.join(FIXTURES_DIR, "valid-gdc-fact-manual.json")
        self.assertTrue(os.path.exists(valid_path), f"Fixture missing: {valid_path}")
        with open(valid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Validate should not raise ValidationError
        jsonschema.validate(instance=data, schema=self.schema)

    def test_invalid_manual_fact_fixture(self):
        invalid_path = os.path.join(FIXTURES_DIR, "invalid-gdc-fact-manual.json")
        self.assertTrue(os.path.exists(invalid_path), f"Fixture missing: {invalid_path}")
        with open(invalid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=data, schema=self.schema)

if __name__ == "__main__":
    unittest.main()
