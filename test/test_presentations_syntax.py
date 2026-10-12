"""Unit tests for presentation suite syntax and Marp styling."""
import os
import re

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

    # Parse slides (split by \n---\n). The first block after header is Slide 1.
    parts = content.split("\n---\n")
    header = parts[0]
    slides = parts[1:]

    expected_slide_count = 22
    assert len(slides) == expected_slide_count, (
        f"Expected exactly {expected_slide_count} slides without trailing blank slides, got {len(slides)}"
    )

    for i, slide in enumerate(slides, start=1):
        stripped = slide.strip()
        assert stripped, f"Slide {i} must not be empty"

        # Verify every content slide has non-empty text outside presenter notes
        text_outside_notes = re.sub(r"<!--(?!\s*_class).*?-->", "", slide, flags=re.DOTALL).strip()
        assert text_outside_notes, f"Slide {i} has no content text outside presenter notes"

        # Verify every content slide contains its own <!-- comment with required sections
        assert "<!--" in slide, f"Slide {i} must contain presenter notes opening '<!--'"
        assert "[VISUAL]:" in slide, f"Slide {i} must contain '[VISUAL]:' presenter notes"
        assert "[VOICEOVER]:" in slide, f"Slide {i} must contain '[VOICEOVER]:' presenter notes"
        assert (
            "[LIVE DEMO / TERMINAL CUE]:" in slide
        ), f"Slide {i} must contain '[LIVE DEMO / TERMINAL CUE]:' presenter notes"


def test_operator_deck():
    path = os.path.join(PRESENTATIONS_DIR, "01-operator-guide.marp.md")
    assert os.path.isfile(path), "01-operator-guide.marp.md must exist"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower(), "Must NOT use airgapped, use Private Mode"
    assert "Bootimus" in content
    assert "Smart Hands" in content
    assert "VLAN" in content

    # Verify per-slide Marp scoping
    raw_slides = content.split("\n---\n")
    # First item is frontmatter
    slides = raw_slides[1:]
    assert len(slides) == 15, "01-operator-guide.marp.md must contain exactly 15 slides"
    for i, slide in enumerate(slides, start=1):
        clean_slide = slide.strip()
        assert clean_slide, f"Slide {i} cannot be blank"

        text_outside_notes = re.sub(
            r"<!--(?! _class:).*?-->", "", slide, flags=re.DOTALL
        ).strip()
        assert text_outside_notes, f"Slide {i} has no content text outside presenter notes"

        assert "[VISUAL]:" in slide, f"Slide {i} missing [VISUAL]:"
        assert "[VOICEOVER]:" in slide, f"Slide {i} missing [VOICEOVER]:"
        assert "[LIVE DEMO / TERMINAL CUE]:" in slide, f"Slide {i} missing [LIVE DEMO / TERMINAL CUE]:"


def test_developer_deck():
    path = os.path.join(PRESENTATIONS_DIR, "02-developer-workbench.marp.md")
    assert os.path.isfile(path), "02-developer-workbench.marp.md must exist"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower(), "Must NOT use airgapped, use Private Mode"
    assert "remaster.sh" in content
    assert "bootimus.py" in content
    assert "Zen 4" in content

    # Verify per-slide Marp scoping
    raw_slides = content.split("\n---\n")
    slides = raw_slides[1:]
    assert len(slides) >= 12, "Must contain at least 12 slides"
    for i, slide in enumerate(slides, start=1):
        clean_slide = slide.strip()
        assert clean_slide, f"Slide {i} cannot be blank"
        text_outside_notes = re.sub(
            r"<!--(?! _class:).*?-->", "", slide, flags=re.DOTALL
        ).strip()
        assert text_outside_notes, f"Slide {i} has no content text outside presenter notes"
        assert "[VISUAL]:" in slide, f"Slide {i} missing [VISUAL]:"
        assert "[VOICEOVER]:" in slide, f"Slide {i} missing [VOICEOVER]:"
        assert "[LIVE DEMO / TERMINAL CUE]:" in slide, f"Slide {i} missing [LIVE DEMO / TERMINAL CUE]:"


