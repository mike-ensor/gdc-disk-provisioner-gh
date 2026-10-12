"""Unit tests for presentation suite syntax and Marp styling."""
import os

PRESENTATIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "docs", "presentations"
)


def test_presentations_directory_and_theme():
    """Verify presentation directory hierarchy and Marp theme definition."""
    assert os.path.isdir(PRESENTATIONS_DIR), "docs/presentations/ directory must exist"
    theme_file = os.path.join(PRESENTATIONS_DIR, "common", "theme.css")
    assert os.path.isfile(theme_file), "common/theme.css must exist"
    with open(theme_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "@theme gdc-brand" in content, "theme.css must define @theme gdc-brand"
    assert (
        "--color-google-blue" in content
    ), "theme.css must define Google blue brand variable"


def test_flagship_deck():
    flagship_path = os.path.join(PRESENTATIONS_DIR, "00-flagship-overview.marp.md")
    assert os.path.isfile(flagship_path), "00-flagship-overview.marp.md must exist"
    with open(flagship_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower(), "Must NOT use airgapped, use Private Mode"
    assert "gdc-disk-provisioner" in content
    assert "gdc-companion" in content
    assert "[VOICEOVER]:" in content, "Presenter notes must have [VOICEOVER] script"
    assert "[VISUAL]:" in content, "Presenter notes must have [VISUAL] cue"
    # Ensure all 8 stages are listed
    for stage_num in range(1, 9):
        assert f"Stage {stage_num}" in content


