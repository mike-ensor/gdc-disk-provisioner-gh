import os
import pytest

PRESENTATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "presentations")

def test_presentations_directory_and_theme():
    assert os.path.isdir(PRESENTATIONS_DIR), "docs/presentations/ directory must exist"
    theme_file = os.path.join(PRESENTATIONS_DIR, "common", "theme.css")
    assert os.path.isfile(theme_file), "common/theme.css must exist"
    with open(theme_file, "r") as f:
        content = f.read()
    assert "@theme gdc-brand" in content, "theme.css must define @theme gdc-brand"
    assert "--color-google-blue" in content, "theme.css must define Google blue brand variable"
