# GDC Software-Only Provisioning Presentation & Video Suite

This directory contains the Marp Markdown slide decks and video production scripts for Google Distributed Cloud (GDC) Software-Only Provisioning.

## Overview

The presentation suite covers autonomous bare-metal edge provisioning across six enterprise personas (Fleet Infrastructure Engineers, Smart Hands Technicians, Systems Software Engineers, Site Reliability Engineers, Support Analysts, and Security Officers). Each deck features 16:9 widescreen slides and embedded presenter notes (`[VISUAL]`, `[VOICEOVER]`, `[LIVE DEMO / TERMINAL CUE]`) designed for dual-use live delivery and YouTube video recording.

## Directory Structure

```
docs/presentations/
├── README.md                              # Presentation suite documentation and viewing guide
├── common/
│   ├── theme.css                          # Custom Marp styling (@theme gdc-brand)
│   └── assets/                            # Shared diagrams, badges, and media assets
├── 00-flagship-overview.marp.md           # Flagship Deck: High-impact pitch & modular chapters
├── 01-operator-guide.marp.md              # Deep Dive 1: Fleet Engineers & Smart Hands (Bare-metal lifecycle)
├── 02-developer-workbench.marp.md         # Deep Dive 2: Remastering Engine & Dev Inner Loop (build.sh & PXE)
├── 03-observability-and-companion.marp.md # Deep Dive 3: Telemetry, Webhooks & Health Monitoring
└── 04-architecture-and-security.marp.md   # Deep Dive 4: TPM 2.0, Step-CA, mTLS & Private Mode
```

## Prerequisites

- Node.js (v18+) with `npx`, or global `@marp-team/marp-cli`:
  ```bash
  npm install -g @marp-team/marp-cli
  ```
- Google Chrome, Chromium, or Edge (required by Marp CLI for PDF/PPTX export).

## Viewing and Exporting Decks

### Interactive Preview (Live Reload Server)

To start Marp in preview server mode with live reloading:

```bash
npx @marp-team/marp-cli@latest -s docs/presentations --theme docs/presentations/common/theme.css
```

Open your browser to `http://localhost:8080/`.

### Export to HTML

To generate standalone HTML presentations:

```bash
npx @marp-team/marp-cli@latest --html --theme docs/presentations/common/theme.css docs/presentations/00-flagship-overview.marp.md -o docs/presentations/00-flagship-overview.html
```

Or batch-convert all markdown decks in the directory:

```bash
npx @marp-team/marp-cli@latest --html --theme docs/presentations/common/theme.css docs/presentations/*.marp.md
```

### Export to PDF

To export to high-resolution PDF for offline sharing or printing:

```bash
npx @marp-team/marp-cli@latest --pdf --allow-local-files --theme docs/presentations/common/theme.css docs/presentations/00-flagship-overview.marp.md -o docs/presentations/00-flagship-overview.pdf
```

### Export to PowerPoint (PPTX)

```bash
npx @marp-team/marp-cli@latest --pptx --allow-local-files --theme docs/presentations/common/theme.css docs/presentations/00-flagship-overview.marp.md -o docs/presentations/00-flagship-overview.pptx
```

## Theme Details

The custom Marp theme `gdc-brand` is located at `common/theme.css`. It extends Marp's default theme with:
- Google brand color palette (`--color-google-blue`, `--color-google-red`, `--color-google-yellow`, `--color-google-green`, `--color-dark-bg`, `--color-light-bg`).
- Standard typography using Google Sans and Roboto.
- System boundary badges:
  - `<span class="badge-provisioner">gdc-disk-provisioner</span>` (Blue / Node engine)
  - `<span class="badge-companion">gdc-companion</span>` (Green / Day-0 & Day-1 config gateway)
- Consistent table, code block, and lead-slide layouts.
