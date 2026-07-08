#!/usr/bin/env bash
# ==============================================================================
# GDC Bootloader ISO Offline Packages Pre-seeding Script (Wrapper)
# ==============================================================================
# Backward-compatible shell wrapper forwarding options and execution bounds
# straight to the modular Python 3 pre-seeding engine.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/preseed_packages.py" "$@"
