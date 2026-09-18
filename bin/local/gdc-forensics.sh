#!/usr/bin/env bash
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

set -euo pipefail

usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Unified GDC Forensics & Installer Diagnostics CLI.

Commands:
  fetch     Remotely trigger forensics collection on target node and pull archive locally
  collect   Gather installer, cloud-init, and system logs on local node into a tarball
  inspect   Extract a forensics tarball and run automated diagnostic analysis

Run '$(basename "$0") <command> --help' for detailed options on any command.
EOF
    exit "${1:-0}"
}

# ==============================================================================
# SUBCOMMAND: collect (Runs on the node)
# ==============================================================================
cmd_collect() {
    local dest_dir="/tmp"

    collect_usage() {
        cat <<EOF
Usage: $(basename "$0") collect [OPTIONS]

Gathers all installer, cloud-init, partitioning, and kernel logs on the host
into an archive for offline analysis.

Options:
  --dest, --output-dir <DIR>  Output directory for the tarball (default: /tmp)
  -h, --help                  Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dest|--output-dir)
                dest_dir="$2"
                shift 2
                ;;
            -h|--help)
                collect_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for collect" >&2
                collect_usage 1
                ;;
        esac
    done

    local forensics_dir="${dest_dir}/gdc-installer-forensics-$(date +%Y%m%d%H%M%S)"
    mkdir -p "${forensics_dir}"

    echo "[-] Gathering forensics in ${forensics_dir}..."

    # 1. Installer Logs
    if [[ -d /var/log/installer ]]; then
        cp -r /var/log/installer "${forensics_dir}/" 2>/dev/null || true
    else
        echo "[-] No /var/log/installer found."
    fi

    # 2. Cloud-init Logs
    [[ -f /var/log/cloud-init.log ]] && cp /var/log/cloud-init.log "${forensics_dir}/" || true
    [[ -f /var/log/cloud-init-output.log ]] && cp /var/log/cloud-init-output.log "${forensics_dir}/" || true

    # 3. System info
    lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE > "${forensics_dir}/lsblk.txt" 2>/dev/null || true
    dmesg > "${forensics_dir}/dmesg.txt" 2>/dev/null || true
    [[ -f /proc/cmdline ]] && cat /proc/cmdline > "${forensics_dir}/cmdline.txt" || true

    # 4. Injected configs
    for f in /autoinstall.yaml /run/autoinstall-storage.yaml /etc/gdc/fallback-config.json; do
        if [[ -f "$f" ]]; then
            cp "$f" "${forensics_dir}/" || true
        fi
    done

    # 5. Archive
    local tarball="${forensics_dir}.tar.gz"
    tar -czf "${tarball}" -C "${dest_dir}" "$(basename "${forensics_dir}")"
    rm -rf "${forensics_dir}"

    echo "[x] Forensics gathered successfully: ${tarball}"
}

# ==============================================================================
# SUBCOMMAND: fetch (Runs from workstation targeting remote node)
# ==============================================================================
cmd_fetch() {
    local node_ip=""
    local user="root"
    local ssh_key=""
    local output_dir="./"
    local auto_inspect=false

    fetch_usage() {
        cat <<EOF
Usage: $(basename "$0") fetch --node <IP> [OPTIONS]

Connects to target node via SSH, executes forensics collection, and downloads
the archive to your local workstation.

Required Arguments:
  --node <IP>                 Target node IP address (alias: --ip)

Optional Arguments:
  --user <USER>               SSH username (default: root, fallback: gdc-admin)
  --key <KEY_PATH>            Path to SSH private key
  --output-dir, --dest <DIR>  Local directory to save archive (default: ./)
  --inspect                   Automatically run 'inspect' on the fetched archive
  -h, --help                  Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --node|--ip)
                node_ip="$2"
                shift 2
                ;;
            --user)
                user="$2"
                shift 2
                ;;
            --key)
                ssh_key="$2"
                shift 2
                ;;
            --output-dir|--dest)
                output_dir="$2"
                shift 2
                ;;
            --inspect)
                auto_inspect=true
                shift
                ;;
            -h|--help)
                fetch_usage 0
                ;;
            *)
                echo "Error: Unknown argument '$1' for fetch" >&2
                fetch_usage 1
                ;;
        esac
    done

    if [[ -z "${node_ip}" ]]; then
        echo "Error: --node argument is required." >&2
        fetch_usage 1
    fi

    local ssh_opts=(-o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null")
    if [[ -n "${ssh_key}" ]]; then
        ssh_opts+=(-i "${ssh_key}")
    fi

    echo "[-] Deploying forensics collector to ${node_ip}..."
    local remote_script="/tmp/gdc-forensics.sh"
    scp "${ssh_opts[@]}" "$0" "${user}@${node_ip}:${remote_script}"
    ssh "${ssh_opts[@]}" "${user}@${node_ip}" "chmod +x ${remote_script}"

    echo "[-] Executing forensics collection on ${node_ip}..."
    ssh "${ssh_opts[@]}" "${user}@${node_ip}" "sudo ${remote_script} collect"

    echo "[-] Pulling forensics archive to local machine (${output_dir})..."
    mkdir -p "${output_dir}"
    scp "${ssh_opts[@]}" "${user}@${node_ip}:/tmp/gdc-installer-forensics-*.tar.gz" "${output_dir}/"

    echo "[-] Cleaning up remote artifacts..."
    ssh "${ssh_opts[@]}" "${user}@${node_ip}" "sudo rm -f ${remote_script} /tmp/gdc-installer-forensics-*.tar.gz"

    local local_archive
    local_archive=$(ls -t "${output_dir}"/gdc-installer-forensics-*.tar.gz 2>/dev/null | head -n 1 || true)
    echo "[x] Forensics collected successfully: ${local_archive}"

    if [[ "${auto_inspect}" == "true" && -n "${local_archive}" ]]; then
        echo ""
        cmd_inspect "--archive" "${local_archive}"
    fi
}

# ==============================================================================
# SUBCOMMAND: inspect (Runs locally on a tarball)
# ==============================================================================
cmd_inspect() {
    local tarball=""

    inspect_usage() {
        cat <<EOF
Usage: $(basename "$0") inspect [OPTIONS] [TARBALL_ARCHIVE]

Extracts a forensics tarball and performs automated diagnostic analysis.

Arguments / Options:
  --archive <FILE>   Path to gdc-installer-forensics-*.tar.gz archive (or passed as argument)
  -h, --help         Display this help message
EOF
        exit "${1:-0}"
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --archive)
                tarball="$2"
                shift 2
                ;;
            -h|--help)
                inspect_usage 0
                ;;
            *)
                if [[ -z "${tarball}" && -f "$1" ]]; then
                    tarball="$1"
                    shift
                else
                    echo "Error: Unknown argument '$1' for inspect" >&2
                    inspect_usage 1
                fi
                ;;
        esac
    done

    if [[ -z "${tarball}" ]]; then
        echo "Error: --archive argument is required." >&2
        inspect_usage 1
    fi

    if [[ ! -f "${tarball}" ]]; then
        echo "Error: Archive '${tarball}' not found." >&2
        exit 1
    fi

    local extract_dir
    extract_dir=$(mktemp -d "/tmp/crash-analysis-XXXXXX")
    echo "[-] Extracting ${tarball} to ${extract_dir}..."
    tar -xzf "${tarball}" -C "${extract_dir}"

    local forensic_root
    forensic_root=$(find "${extract_dir}" -maxdepth 1 -mindepth 1 -type d | head -n 1 || echo "${extract_dir}")

    echo "[-] Analyzing forensics in ${forensic_root}..."

    echo "=============================================================================="
    echo " CHECK: Kernel Command Line (Boot Params)"
    echo "=============================================================================="
    if [[ -f "${forensic_root}/cmdline.txt" ]]; then
        cat "${forensic_root}/cmdline.txt"
        echo -e "\n"
        if grep -q "ds=nocloud;s=/cdrom/nocloud/" "${forensic_root}/cmdline.txt"; then
            echo "[x] Boot parameters look correct (offline seed ds=nocloud)."
        else
            echo "[!] WARNING: Boot parameters are likely wrong (missing ds=nocloud seed)."
        fi
    else
        echo "[!] No cmdline.txt found."
    fi

    echo -e "\n=============================================================================="
    echo " CHECK: Subiquity Config Application Errors"
    echo "=============================================================================="
    local subiquity_log="${forensic_root}/installer/subiquity-server-debug.log"
    if [[ -f "${subiquity_log}" ]]; then
        grep -Ei "apply_autoinstall_config|error|exception|fail" "${subiquity_log}" | tail -n 20 || echo "[-] No errors matched in subiquity log."
    else
        echo "[-] Installer log not present."
    fi

    echo -e "\n=============================================================================="
    echo " CHECK: Injected Configuration Files"
    echo "=============================================================================="
    for f in autoinstall.yaml autoinstall-storage.yaml fallback-config.json; do
        if [[ -f "${forensic_root}/$f" ]]; then
            echo "[x] Found ${f}"
        else
            echo "[-] Missing ${f} in forensics bundle."
        fi
    done

    echo -e "\n[x] Inspection complete. Analysis artifacts preserved at ${extract_dir}."
}

# ==============================================================================
# MAIN ROUTING
# ==============================================================================
if [[ $# -eq 0 ]]; then
    usage 1
fi

COMMAND="$1"
shift

case "${COMMAND}" in
    collect)
        cmd_collect "$@"
        ;;
    fetch)
        cmd_fetch "$@"
        ;;
    inspect)
        cmd_inspect "$@"
        ;;
    -h|--help|help)
        usage 0
        ;;
    *)
        echo "Error: Unknown command '${COMMAND}'" >&2
        usage 1
        ;;
esac
