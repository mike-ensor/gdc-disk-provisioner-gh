#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"

RENDER_PDF=false

for arg in "$@"; do
    case "$arg" in
        --pdf)
            RENDER_PDF=true
            ;;
        -h|--help)
            echo "Usage: $0 [--pdf]"
            echo "Options:"
            echo "  --pdf        Also compile decks to PDF format"
            echo "  -h, --help   Show this help message"
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument '$arg'" >&2
            echo "Usage: $0 [--pdf]" >&2
            exit 1
            ;;
    esac
done

echo "=================================================="
echo "    GDC Presentation Deck Compiler & Validator    "
echo "=================================================="

# 1. Check for Marp CLI
echo "[1/4] Checking Marp CLI availability..."
if command -v marp >/dev/null 2>&1; then
    MARP_CMD=(marp)
    echo "Using system Marp CLI: $(command -v marp)"
elif command -v npx >/dev/null 2>&1; then
    MARP_CMD=(npx @marp-team/marp-cli@latest)
    echo "Using Marp via npx (@marp-team/marp-cli@latest)"
else
    echo "ERROR: Neither 'marp' nor 'npx' is available on PATH." >&2
    echo "Please install Marp CLI ('npm install -g @marp-team/marp-cli') or Node.js with npx." >&2
    exit 1
fi

# 2. Compile Mermaid diagrams if needed
echo "[2/5] Checking and compiling Mermaid diagrams (.mmd -> .svg)..."
if compgen -G "${SCRIPT_DIR}/common/assets/*.mmd" > /dev/null; then
    for mmd in "${SCRIPT_DIR}/common/assets/"*.mmd; do
        svg="${mmd%.mmd}.svg"
        if [ ! -f "$svg" ] || [ "$mmd" -nt "$svg" ]; then
            echo "  Compiling $(basename "$mmd") -> $(basename "$svg")"
            if command -v mmdc >/dev/null 2>&1; then
                mmdc -i "$mmd" -o "$svg" -b transparent
            elif command -v npx >/dev/null 2>&1; then
                npx -y @mermaid-js/mermaid-cli -i "$mmd" -o "$svg" -b transparent
            fi
        fi
    done
fi

# 3. Create output directory
echo "[3/5] Ensuring output directory exists..."
mkdir -p "${DIST_DIR}"
echo "Output directory: ${DIST_DIR}"

# 4. Pre-flight Terminology Check
echo "[4/5] Running pre-flight terminology check..."
terminology_errors=0
for deck in "${SCRIPT_DIR}"/*.marp.md; do
    [ -e "$deck" ] || continue
    deck_name="$(basename "$deck")"
    if grep -Eni "airgapped" "$deck" >/dev/null 2>&1; then
        echo "ERROR: Forbidden term 'airgapped' detected in ${deck_name}:" >&2
        grep -Eni --color=always "airgapped" "$deck" >&2 || true
        terminology_errors=$((terminology_errors + 1))
    fi
done

if [ "$terminology_errors" -gt 0 ]; then
    echo "FAILURE: Terminology check failed. Use 'Private Mode' instead of 'airgapped'." >&2
    exit 1
fi
echo "Terminology check passed: 0 forbidden terms found."

# 5. Pre-flight Slide Structure Check
echo "[5/5] Running pre-flight slide structure check..."
python3 - <<'EOF' "${SCRIPT_DIR}"
import sys
import os
import glob
import re

script_dir = sys.argv[1]
decks = sorted(glob.glob(os.path.join(script_dir, "*.marp.md")))

if not decks:
    print(f"ERROR: No *.marp.md decks found in {script_dir}", file=sys.stderr)
    sys.exit(1)

has_error = False
for deck in decks:
    deck_name = os.path.basename(deck)
    with open(deck, "r", encoding="utf-8") as f:
        content = f.read()

    parts = re.split(r"\r?\n---\r?\n", content)
    if len(parts) <= 1:
        print(f"ERROR: {deck_name} does not contain multiple slides separated by '---'", file=sys.stderr)
        has_error = True
        continue

    slides = parts[1:]
    for idx, slide in enumerate(slides, start=1):
        if not slide.strip():
            print(f"ERROR: {deck_name} - Slide {idx} is empty", file=sys.stderr)
            has_error = True
            continue

        text_outside_notes = re.sub(r"<!--(?!\s*_\w+:).*?-->", "", slide, flags=re.DOTALL).strip()
        if not text_outside_notes:
            print(f"ERROR: {deck_name} - Slide {idx} has no content text outside presenter notes", file=sys.stderr)
            has_error = True

        # Mermaid fence validation: Check that every opening ```mermaid block has a matching closing ``` fence
        in_mermaid = False
        for line in slide.splitlines():
            if not in_mermaid:
                if re.match(r"^\s*```mermaid\b", line):
                    in_mermaid = True
            else:
                if re.match(r"^\s*```+\s*$", line):
                    in_mermaid = False
                elif re.match(r"^\s*```mermaid\b", line):
                    print(f"ERROR: {deck_name} - Slide {idx} has unclosed ```mermaid block", file=sys.stderr)
                    has_error = True
        if in_mermaid:
            print(f"ERROR: {deck_name} - Slide {idx} has unclosed ```mermaid block", file=sys.stderr)
            has_error = True

        # Slide note checks: Verify each slide contains the actual note tokens,
        # ignoring any Marp directive comments <!--\s*_\w+:.*?-->.
        slide_without_directives = re.sub(r"<!--\s*_\w+:.*?-->", "", slide, flags=re.DOTALL)
        notes = re.findall(r"<!--(.*?)-->", slide_without_directives, flags=re.DOTALL)
        if not notes or not any(n.strip() for n in notes):
            print(f"ERROR: {deck_name} - Slide {idx} is missing presenter notes", file=sys.stderr)
            has_error = True
        else:
            notes_text = "\n".join(notes)
            for token in ["[VISUAL]:", "[VOICEOVER]:", "[LIVE DEMO / TERMINAL CUE]:"]:
                if token not in notes_text:
                    print(f"ERROR: {deck_name} - Slide {idx} presenter notes missing '{token}'", file=sys.stderr)
                    has_error = True

if has_error:
    print("FAILURE: Slide structure check failed.", file=sys.stderr)
    sys.exit(1)

print(f"Slide structure check passed: All {len(decks)} decks verified.")
EOF

# 5. Compile decks
echo "=================================================="
echo "Compiling presentation decks..."
echo "=================================================="

cd "${SCRIPT_DIR}"

compiled_html=()
compiled_pdf=()

for deck_path in *.marp.md; do
    [ -e "$deck_path" ] || continue
    deck_base="$(basename "$deck_path")"
    name="${deck_base%.marp.md}"

    echo "Compiling HTML: ${deck_base} -> dist/${name}.html"
    "${MARP_CMD[@]}" "${deck_path}" --html --theme common/theme.css -o "dist/${name}.html"
    compiled_html+=("dist/${name}.html")

    if [ "$RENDER_PDF" = true ]; then
        echo "Compiling PDF:  ${deck_base} -> dist/${name}.pdf"
        "${MARP_CMD[@]}" "${deck_path}" --html --theme common/theme.css --pdf --allow-local-files -o "dist/${name}.pdf"
        compiled_pdf+=("dist/${name}.pdf")
    fi
done

# 6. Summary Report
echo ""
echo "=================================================="
echo "          COMPILATION SUMMARY REPORT              "
echo "=================================================="
echo "Output Directory: ${DIST_DIR}"
echo ""
echo "HTML Decks Compiled (${#compiled_html[@]}):"
for f in "${compiled_html[@]}"; do
    echo "  [OK] ${f}"
done

if [ "$RENDER_PDF" = true ]; then
    echo ""
    echo "PDF Decks Compiled (${#compiled_pdf[@]}):"
    for f in "${compiled_pdf[@]}"; do
        echo "  [OK] ${f}"
    done
fi

echo "=================================================="
echo "All decks successfully validated and compiled!"
echo "=================================================="
