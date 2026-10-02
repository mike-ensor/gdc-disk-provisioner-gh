#!/usr/bin/env bash
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# GDC Dependency & Package Update CLI (Workstation & CI/CD Utility)
# ==============================================================================
# Audits upstream releases, updates pinned binary signatures in dependencies.env,
# executes the Ubuntu 24.04 Noble package pre-seeding pipeline, and synchronizes
# offline assets to Google Cloud Storage.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENGINE_SCRIPT="${REPO_ROOT}/src/build/update_dependencies.py"

usage() {
    cat <<EOF
Usage: $(basename "$0") [command] [options]

GDC Dependency & Offline Package Manager for Workstations and CI/CD Pipelines.

Commands:
  check                  Audit upstream releases against pinned versions in dependencies.env (default)
  update-binaries        Download and update cryptographic hashes for all outdated binaries
  update-binary <NAME>   Update a specific binary (e.g. kubestr, helm, gitea, step-cli, google-cloud-sdk)
  update-packages        Re-resolve and pre-seed Ubuntu 24.04 Noble .deb packages into .cache/packages/
  add-dependency         Add a new dependency (--type [pkg|binary], --name <NAME>, etc.)
  add-pkg <NAME>         Add a Debian package to packages_config.yaml (supports --install, --preseed)
  add-binary             Add a standalone binary to dependencies.env (needs --name, --version, --url)
  sync-gcs               Upload local cached binaries and packages to GCS dependency bucket
  all                    Run full cycle: check, update binaries, pre-seed packages, and sync to GCS

Options:
  --docker               Run package pre-seeding inside an isolated 'ubuntu:24.04' container
  --install              For packages: configure Ansible to pre-install package on target machine OS
  --preseed              For packages: immediately run preseed pipeline after adding to config
  --markdown             Format audit output as Markdown (ideal for GitLab MRs / CI logs)
  --json                 Output audit results as JSON
  --ci                   CI Gate mode: exits with 2 if any upstream updates are available
  --gcs-bucket <BUCKET>  Override target GCS bucket (default: from src/build/build.env)
  -h, --help             Show this help message

Examples:
  $(basename "$0") check
  $(basename "$0") check --markdown
  $(basename "$0") add-pkg dnsmasq --install
  $(basename "$0") add-binary --name mytool --version 1.0.0 --url https://example.com/mytool.tar.gz
  $(basename "$0") update-binary kubestr
  $(basename "$0") update-packages --docker
  $(basename "$0") sync-gcs
EOF
    exit "${1:-0}"
}

if [[ $# -eq 0 ]]; then
    python3 "${ENGINE_SCRIPT}" --check
    exit 0
fi

COMMAND="${1:-}"
case "${COMMAND}" in
    -h|--help|help)
        usage 0
        ;;
    check)
        shift
        python3 "${ENGINE_SCRIPT}" --check "$@"
        ;;
    update-binaries)
        shift
        python3 "${ENGINE_SCRIPT}" --update-all-binaries "$@"
        ;;
    update-binary)
        shift
        if [[ $# -eq 0 ]]; then
            echo "ERROR: Missing binary name. Example: $(basename "$0") update-binary kubestr" >&2
            exit 1
        fi
        BIN_NAME="$1"
        shift
        python3 "${ENGINE_SCRIPT}" --update-binary "${BIN_NAME}" "$@"
        ;;
    update-packages)
        shift
        python3 "${ENGINE_SCRIPT}" --update-packages "$@"
        ;;
    add-dependency)
        shift
        python3 "${ENGINE_SCRIPT}" add-dependency "$@"
        ;;
    add-pkg)
        shift
        if [[ $# -eq 0 ]]; then
            echo "ERROR: Missing package name. Example: $(basename "$0") add-pkg dnsmasq" >&2
            exit 1
        fi
        PKG_NAME="$1"
        shift
        python3 "${ENGINE_SCRIPT}" add-dependency --type pkg --name "${PKG_NAME}" "$@"
        ;;
    add-binary)
        shift
        python3 "${ENGINE_SCRIPT}" add-dependency --type binary "$@"
        ;;
    sync-gcs)
        shift
        python3 "${ENGINE_SCRIPT}" --sync-gcs "$@"
        ;;
    all)
        shift
        python3 "${ENGINE_SCRIPT}" --update-all-binaries --update-packages --sync-gcs "$@"
        ;;
    *)
        # Forward directly to Python engine if using flags
        python3 "${ENGINE_SCRIPT}" "$@"
        ;;
esac
