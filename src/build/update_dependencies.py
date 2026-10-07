#!/usr/bin/env python3
# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

"""GDC Dependency & Package Update Helper.

Audits, updates, and synchronizes upstream binaries and offline Debian packages
required for building GDC Bare Metal installation ISOs and offline cache bundles.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
DEPS_ENV_PATH = os.path.join(REPO_ROOT, "src/dependencies.env")
BUILD_ENV_PATH = os.path.join(REPO_ROOT, "src/build/build.env")
PACKAGES_CONFIG_PATH = os.path.join(REPO_ROOT, "src/build/packages_config.yaml")
ANSIBLE_VARS_PATH = os.path.join(REPO_ROOT, "src/ansible/vars/all.yml")
ANSIBLE_VARS_J2_PATH = os.path.join(REPO_ROOT, "src/ansible/vars/all.yml.j2")
CACHE_DIR = os.path.join(REPO_ROOT, ".cache")
BIN_CACHE_DIR = os.path.join(CACHE_DIR, "binaries")
PKG_CACHE_DIR = os.path.join(CACHE_DIR, "packages")

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (GDC-Dependency-Updater/1.0)"}


def parse_env_file(filepath):
    """Parses standard key=value and export key=value shell environment files."""
    env = {}
    if not os.path.exists(filepath):
        return env
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if (val.startswith('"') and val.endswith('"')) or (
                        val.startswith("'") and val.endswith("'")
                    ):
                        val = val[1:-1]
                    env[key] = val
    except Exception as e:
        sys.stderr.write(f"[!] Warning: Failed to parse '{filepath}': {e}\n")
    return env


def http_get_json(url, timeout=15):
    """Fetches JSON payload with custom user agent and timeout."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_text(url, timeout=15):
    """Fetches text payload with custom user agent and timeout."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def check_upstream_versions(current_deps):
    """Queries public upstream registries to discover latest versions for all binaries."""
    results = {}

    # 1. Kubestr
    curr_kubestr = current_deps.get("KUBESTR_VERSION", "unknown")
    try:
        data = http_get_json("https://api.github.com/repos/kastenhq/kubestr/releases/latest")
        tag = data.get("tag_name", "").lstrip("v")
        results["kubestr"] = {
            "current": curr_kubestr,
            "latest": tag,
            "update_available": tag != curr_kubestr and tag != "",
            "repo": "kastenhq/kubestr",
            "url": f"https://github.com/kastenhq/kubestr/releases/download/v{tag}/kubestr_{tag}_Linux_amd64.tar.gz",
            "filename": f"kubestr_{tag}_Linux_amd64.tar.gz",
        }
    except Exception as e:
        results["kubestr"] = {"current": curr_kubestr, "latest": f"Error: {e}", "update_available": False}

    # 2. Helm (Track Helm 3 LTS series)
    curr_helm = current_deps.get("HELM_VERSION", "unknown")
    try:
        releases = http_get_json("https://api.github.com/repos/helm/helm/releases?per_page=15")
        helm3_tags = [
            r["tag_name"].lstrip("v")
            for r in releases
            if not r.get("prerelease") and r.get("tag_name", "").startswith("v3.")
        ]
        latest_helm3 = helm3_tags[0] if helm3_tags else curr_helm
        results["helm"] = {
            "current": curr_helm,
            "latest": latest_helm3,
            "update_available": latest_helm3 != curr_helm,
            "repo": "helm/helm",
            "url": f"https://get.helm.sh/helm-v{latest_helm3}-linux-amd64.tar.gz",
            "filename": f"helm-v{latest_helm3}-linux-amd64.tar.gz",
        }
    except Exception as e:
        results["helm"] = {"current": curr_helm, "latest": f"Error: {e}", "update_available": False}

    # 3. Gitea (Track 1.22.x LTS series)
    curr_gitea = "1.22.1"
    gitea_fn = current_deps.get("GITEA_BINARY_FILENAME", "")
    m = re.search(r"gitea-(\d+\.\d+\.\d+)-linux-amd64", gitea_fn)
    if m:
        curr_gitea = m.group(1)
    try:
        tags_data = http_get_json("https://api.github.com/repos/go-gitea/gitea/tags?per_page=100")
        v1_22 = [
            t["name"].lstrip("v")
            for t in tags_data
            if t["name"].startswith("v1.22.") and not any(x in t["name"] for x in ["rc", "alpha", "beta"])
        ]
        latest_gitea_122 = v1_22[0] if v1_22 else curr_gitea
        results["gitea"] = {
            "current": curr_gitea,
            "latest": latest_gitea_122,
            "update_available": latest_gitea_122 != curr_gitea,
            "repo": "go-gitea/gitea",
            "url": f"https://github.com/go-gitea/gitea/releases/download/v{latest_gitea_122}/gitea-{latest_gitea_122}-linux-amd64",
            "filename": f"gitea-{latest_gitea_122}-linux-amd64",
        }
    except Exception as e:
        results["gitea"] = {"current": curr_gitea, "latest": f"Error: {e}", "update_available": False}

    # 4. Step CLI
    step_fn = current_deps.get("STEP_CLI_FILENAME", "")
    m_step = re.search(r"step-cli_([\d.]+)", step_fn)
    curr_step = m_step.group(1) if m_step else "0.26.1"
    try:
        data = http_get_json("https://api.github.com/repos/smallstep/cli/releases/latest")
        tag = data.get("tag_name", "").lstrip("v")
        results["step-cli"] = {
            "current": curr_step,
            "latest": tag,
            "update_available": tag != curr_step and tag != "",
            "repo": "smallstep/cli",
            "url": f"https://github.com/smallstep/cli/releases/download/v{tag}/step-cli_{tag}_amd64.deb",
            "filename": f"step-cli_{tag}_amd64.deb",
        }
    except Exception as e:
        results["step-cli"] = {"current": curr_step, "latest": f"Error: {e}", "update_available": False}

    # 5. Google Cloud SDK
    gcloud_fn = current_deps.get("GCLOUD_SDK_FILENAME", "")
    m_gc = re.search(r"google-cloud-cli-([\d.]+)-linux-x86_64", gcloud_fn)
    curr_gcloud = m_gc.group(1) if m_gc else "575.0.0"
    try:
        data = http_get_json("https://dl.google.com/dl/cloudsdk/channels/rapid/components-2.json")
        latest_gcloud = data.get("version", curr_gcloud)
        results["google-cloud-sdk"] = {
            "current": curr_gcloud,
            "latest": latest_gcloud,
            "update_available": latest_gcloud != curr_gcloud,
            "repo": "google-cloud-sdk",
            "url": f"https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-{latest_gcloud}-linux-x86_64.tar.gz",
            "filename": f"google-cloud-cli-{latest_gcloud}-linux-x86_64.tar.gz",
        }
    except Exception as e:
        results["google-cloud-sdk"] = {"current": curr_gcloud, "latest": f"Error: {e}", "update_available": False}

    # 6. Temurin 17 JRE
    jre_fn = current_deps.get("JRE_PACKAGE_FILENAME", "")
    m_jre = re.search(r"OpenJDK17U-jre_x64_linux_hotspot_([\w.%+-]+)\.tar\.gz", jre_fn)
    curr_jre = m_jre.group(1).replace("%2B", "+") if m_jre else "17.0.11_9"
    try:
        data = http_get_json(
            "https://api.adoptium.net/v3/assets/feature_releases/17/ga?image_type=jre&architecture=x64&os=linux&page_size=1"
        )
        latest_jre = data[0]["release_name"].replace("jdk-", "").replace("+", "_")
        latest_tag = data[0]["release_name"].replace("+", "%2B")
        results["openjdk-17-jre"] = {
            "current": curr_jre,
            "latest": latest_jre,
            "update_available": latest_jre != curr_jre,
            "repo": "adoptium/temurin17-binaries",
            "url": f"https://github.com/adoptium/temurin17-binaries/releases/download/{latest_tag}/OpenJDK17U-jre_x64_linux_hotspot_{latest_jre}.tar.gz",
            "filename": f"OpenJDK17U-jre_x64_linux_hotspot_{latest_jre}.tar.gz",
        }
    except Exception as e:
        results["openjdk-17-jre"] = {"current": curr_jre, "latest": f"Error: {e}", "update_available": False}

    # 7. Sonatype Nexus
    nexus_fn = current_deps.get("NEXUS_PACKAGE_FILENAME", "")
    m_nx = re.search(r"nexus-([\d.-]+)-unix\.tar\.gz", nexus_fn)
    curr_nexus = m_nx.group(1) if m_nx else "3.69.0-02"
    try:
        tags = http_get_json("https://api.github.com/repos/sonatype/nexus-public/tags?per_page=5")
        latest_nexus = tags[0]["name"].replace("release-", "")
        results["nexus"] = {
            "current": curr_nexus,
            "latest": latest_nexus,
            "update_available": latest_nexus != curr_nexus,
            "repo": "Sonatype Official",
            "url": f"https://download.sonatype.com/nexus/3/nexus-{latest_nexus}-unix.tar.gz",
            "filename": f"nexus-{latest_nexus}-unix.tar.gz",
        }
    except Exception as e:
        results["nexus"] = {"current": curr_nexus, "latest": f"Error: {e}", "update_available": False}

    # 8. ORAS CLI
    curr_oras = current_deps.get("ORAS_VERSION", "unknown")
    try:
        data = http_get_json("https://api.github.com/repos/oras-project/oras/releases/latest")
        tag = data.get("tag_name", "").lstrip("v")
        results["oras"] = {
            "current": curr_oras,
            "latest": tag,
            "update_available": tag != curr_oras and tag != "",
            "repo": "oras-project/oras",
            "url": f"https://github.com/oras-project/oras/releases/download/v{tag}/oras_{tag}_linux_amd64.tar.gz",
            "filename": f"oras_{tag}_linux_amd64.tar.gz",
        }
    except Exception as e:
        results["oras"] = {"current": curr_oras, "latest": f"Error: {e}", "update_available": False}

    return results


def print_audit_table(results, as_markdown=False):
    """Prints a formatted ASCII or Markdown table summarizing version status."""
    if as_markdown:
        print("| Binary | Pinned Version | Latest Upstream | Status | Target Package |")
        print("|---|---|---|---|---|")
        for name, data in results.items():
            status = "**UPDATE AVAILABLE**" if data.get("update_available") else "UP TO DATE"
            print(
                f"| `{name}` | `{data.get('current')}` | `{data.get('latest')}` | {status} | `{data.get('filename', '-')}` |"
            )
    else:
        print("==========================================================================================")
        print(" GDC OFFLINE BINARY DEPENDENCIES AUDIT")
        print("==========================================================================================")
        print(f"{'BINARY':<18} {'CURRENT':<14} {'LATEST':<16} {'STATUS':<20} {'PACKAGE'}")
        print("-" * 90)
        for name, data in results.items():
            status = "[!] UPDATE READY" if data.get("update_available") else "[x] UP TO DATE"
            print(
                f"{name:<18} {data.get('current', '-'):<14} {data.get('latest', '-'):<16} {status:<20} {data.get('filename', '-')}"
            )
        print("==========================================================================================")


def compute_url_sha256(url):
    """Downloads a file to a temporary location and calculates its SHA-256."""
    sys.stderr.write(f"[-] Downloading asset to compute SHA-256: {url}...\n")
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    hasher = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=120) as resp:
        while chunk := resp.read(65536):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    sys.stderr.write(f"  [x] Computed SHA-256: {digest}\n")
    return digest


def update_dependencies_env(binary_name, new_info):
    """Rewrites the specified binary entry in src/dependencies.env with new version, url, and sha256."""
    if not os.path.exists(DEPS_ENV_PATH):
        sys.stderr.write(f"ERROR: {DEPS_ENV_PATH} not found.\n")
        return False

    with open(DEPS_ENV_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Backup original
    backup_path = DEPS_ENV_PATH + ".bak"
    shutil.copy(DEPS_ENV_PATH, backup_path)
    print(f"[-] Created backup of dependencies.env at: {backup_path}")

    url = new_info.get("url")
    filename = new_info.get("filename")
    latest_ver = new_info.get("latest")
    sha256 = new_info.get("sha256") or compute_url_sha256(url)

    if binary_name == "kubestr":
        content = re.sub(r"KUBESTR_VERSION=.*", f"KUBESTR_VERSION={latest_ver}", content)
        content = re.sub(r"KUBESTR_PACKAGE_URL=.*", f"KUBESTR_PACKAGE_URL={url}", content)
        content = re.sub(r"KUBESTR_PACKAGE_FILENAME=.*", f"KUBESTR_PACKAGE_FILENAME={filename}", content)
        content = re.sub(r"KUBESTR_PACKAGE_SHA256=.*", f"KUBESTR_PACKAGE_SHA256={sha256}", content)
    elif binary_name == "oras":
        content = re.sub(r"ORAS_VERSION=.*", f"ORAS_VERSION={latest_ver}", content)
        content = re.sub(r"ORAS_PACKAGE_URL=.*", f"ORAS_PACKAGE_URL={url}", content)
        content = re.sub(r"ORAS_PACKAGE_FILENAME=.*", f"ORAS_PACKAGE_FILENAME={filename}", content)
        content = re.sub(r"ORAS_PACKAGE_SHA256=.*", f"ORAS_PACKAGE_SHA256={sha256}", content)
    elif binary_name == "helm":
        content = re.sub(r"HELM_VERSION=.*", f"HELM_VERSION={latest_ver}", content)
        content = re.sub(r"HELM_PACKAGE_URL=.*", f"HELM_PACKAGE_URL={url}", content)
        content = re.sub(r"HELM_PACKAGE_FILENAME=.*", f"HELM_PACKAGE_FILENAME={filename}", content)
        content = re.sub(r"HELM_PACKAGE_SHA256=.*", f"HELM_PACKAGE_SHA256={sha256}", content)
    elif binary_name == "gitea":
        content = re.sub(r"GITEA_BINARY_URL=.*", f"GITEA_BINARY_URL={url}", content)
        content = re.sub(r"GITEA_BINARY_FILENAME=.*", f"GITEA_BINARY_FILENAME={filename}", content)
        content = re.sub(r"GITEA_BINARY_SHA256=.*", f"GITEA_BINARY_SHA256={sha256}", content)
    elif binary_name == "step-cli":
        content = re.sub(r"STEP_CLI_URL=.*", f"STEP_CLI_URL={url}", content)
        content = re.sub(r"STEP_CLI_FILENAME=.*", f"STEP_CLI_FILENAME={filename}", content)
        content = re.sub(r"STEP_CLI_SHA256=.*", f"STEP_CLI_SHA256={sha256}", content)
    elif binary_name == "google-cloud-sdk":
        content = re.sub(r"GCLOUD_SDK_URL=.*", f"GCLOUD_SDK_URL={url}", content)
        content = re.sub(r"GCLOUD_SDK_FILENAME=.*", f"GCLOUD_SDK_FILENAME={filename}", content)
        content = re.sub(r"GCLOUD_SDK_SHA256=.*", f"GCLOUD_SDK_SHA256={sha256}", content)
    elif binary_name == "openjdk-17-jre":
        content = re.sub(r"JRE_PACKAGE_URL=.*", f"JRE_PACKAGE_URL={url}", content)
        content = re.sub(r"JRE_PACKAGE_FILENAME=.*", f"JRE_PACKAGE_FILENAME={filename}", content)
        content = re.sub(r"JRE_PACKAGE_SHA256=.*", f"JRE_PACKAGE_SHA256={sha256}", content)
    elif binary_name == "nexus":
        content = re.sub(r"NEXUS_PACKAGE_URL=.*", f"NEXUS_PACKAGE_URL={url}", content)
        content = re.sub(r"NEXUS_PACKAGE_FILENAME=.*", f"NEXUS_PACKAGE_FILENAME={filename}", content)
        content = re.sub(r"NEXUS_PACKAGE_SHA256=.*", f"NEXUS_PACKAGE_SHA256={sha256}", content)
    else:
        sys.stderr.write(f"ERROR: Unknown binary target '{binary_name}'.\n")
        return False

    with open(DEPS_ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[x] Successfully updated '{binary_name}' in src/dependencies.env.")
    return True


def add_package_dependency(pkg_name, install=False):
    """Adds a Debian package to packages_config.yaml and optionally all.yml."""
    pkg = pkg_name.strip().lower()
    if not re.match(r"^[a-z0-9][a-z0-9+.-]+$", pkg):
        sys.stderr.write(f"ERROR: Invalid Debian package name '{pkg}'.\n")
        return False

    if not os.path.exists(PACKAGES_CONFIG_PATH):
        sys.stderr.write(f"ERROR: {PACKAGES_CONFIG_PATH} not found.\n")
        return False

    with open(PACKAGES_CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already present
    if f'"{pkg}"' in content or f"'{pkg}'" in content or f"- {pkg}" in content:
        print(f"[-] Notice: Package '{pkg}' is already declared in packages_config.yaml.")
    else:
        # Idempotent replacement preserving comments and structure
        if "customer_added: []" in content:
            content = content.replace("customer_added: []", f"customer_added:\n    - \"{pkg}\"")
        elif "customer_added:" in content:
            content = re.sub(
                r"(customer_added:\s*\n)",
                rf"\1    - \"{pkg}\"\n",
                content,
                count=1,
            )
        else:
            sys.stderr.write(f"ERROR: 'customer_added' section not found in {PACKAGES_CONFIG_PATH}.\n")
            return False

        with open(PACKAGES_CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[x] Added '{pkg}' to packages_to_include.customer_added in packages_config.yaml.")

    if install:
        for v_path in [ANSIBLE_VARS_PATH, ANSIBLE_VARS_J2_PATH]:
            if os.path.exists(v_path):
                with open(v_path, "r", encoding="utf-8") as f:
                    v_content = f.read()
                if f'"{pkg}"' in v_content or f"'{pkg}'" in v_content or f"- {pkg}" in v_content:
                    print(f"[-] Notice: Package '{pkg}' is already in {os.path.basename(v_path)}.")
                else:
                    if "customer_install_packages: []" in v_content:
                        v_content = v_content.replace(
                            "customer_install_packages: []",
                            f"customer_install_packages:\n  - \"{pkg}\"",
                        )
                    elif "customer_install_packages:" in v_content:
                        v_content = re.sub(
                            r"(customer_install_packages:\s*\n)",
                            rf"\1  - \"{pkg}\"\n",
                            v_content,
                            count=1,
                        )
                    with open(v_path, "w", encoding="utf-8") as f:
                        f.write(v_content)
                    print(f"[x] Added '{pkg}' to customer_install_packages in {os.path.basename(v_path)}.")

    return True


def add_binary_dependency(name, version, url, sha256=None, filename=None, subpath=None):
    """Adds a new binary dependency to dependencies.env with calculated SHA-256."""
    name_clean = name.strip().lower()
    name_upper = name_clean.replace("-", "_").upper()

    if not filename:
        filename = url.rstrip("/").split("/")[-1]

    if not sha256:
        print(f"[-] Calculating SHA-256 for {url}...")
        sha256 = compute_url_sha256(url)

    if not os.path.exists(DEPS_ENV_PATH):
        sys.stderr.write(f"ERROR: {DEPS_ENV_PATH} not found.\n")
        return False

    with open(DEPS_ENV_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Backup original
    backup_path = DEPS_ENV_PATH + ".bak"
    shutil.copy(DEPS_ENV_PATH, backup_path)

    # Check if already present
    if f"{name_upper}_PACKAGE_URL=" in content or f"{name_upper}_BINARY_URL=" in content:
        print(f"[-] Notice: Binary '{name_clean}' already defined in dependencies.env. Updating...")
        content = re.sub(rf"{name_upper}_VERSION=.*", f"{name_upper}_VERSION={version}", content)
        content = re.sub(rf"{name_upper}_PACKAGE_URL=.*", f"{name_upper}_PACKAGE_URL={url}", content)
        content = re.sub(rf"{name_upper}_PACKAGE_FILENAME=.*", f"{name_upper}_PACKAGE_FILENAME={filename}", content)
        content = re.sub(rf"{name_upper}_PACKAGE_SHA256=.*", f"{name_upper}_PACKAGE_SHA256={sha256}", content)
    else:
        new_block = (
            f"\n# ------------------------------------------------------------------------------\n"
            f"# {name_upper} CLI (Added by update-dependencies)\n"
            f"# ------------------------------------------------------------------------------\n"
            f"# Desired Location inside ISO: /custom-data/tools/{name_clean}\n"
            f"{name_upper}_VERSION={version}\n"
            f"{name_upper}_PACKAGE_URL={url}\n"
            f"{name_upper}_PACKAGE_FILENAME={filename}\n"
            f"{name_upper}_PACKAGE_SHA256={sha256}\n"
            f"{name_upper}_ISO_DEST_DIR=/custom-data/tools/{name_clean}\n"
        )
        # Insert before CACHED_BINARY_FILES
        match = re.search(r"(# -+\s*\n# \d+\.\s*LIST OF CACHED BINARY FILES)", content)
        if match:
            idx = match.start()
            content = content[:idx] + new_block + "\n" + content[idx:]
        else:
            content += new_block

        # Append to CACHED_BINARY_FILES
        var_ref = f"${{{name_upper}_PACKAGE_FILENAME}}"
        if var_ref not in content:
            content = re.sub(
                r'(CACHED_BINARY_FILES="[^"]*)(")',
                rf"\1 {var_ref}\2",
                content,
            )

    with open(DEPS_ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[x] Successfully added binary '{name_clean}' (v{version}) to src/dependencies.env.")
    return True


def run_preseed_debian_packages(use_docker=False, enable_gcs=False, bucket_name=None):
    """Executes the Debian package resolution pipeline natively or inside an Ubuntu 24.04 container."""
    print("[-] Starting Debian Package Pre-seeding Pipeline for Ubuntu 24.04 (Noble)...")
    if use_docker:
        print("  [-] Executing via isolated Docker container 'ubuntu:24.04'...")
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{REPO_ROOT}:/workspace",
            "-w",
            "/workspace",
            "-e",
            f"DEPENDENCY_CACHE_GCS_BUCKET={bucket_name or ''}",
            "-e",
            f"ENABLE_GCS={'true' if enable_gcs else 'false'}",
            "ubuntu:24.04",
            "bash",
            "-c",
            "apt-get update -qq && apt-get install -y -qq python3 python3-yaml sudo && ./src/build/preseed_packages.sh",
        ]
        subprocess.run(cmd, check=True)
    else:
        script_path = os.path.join(REPO_ROOT, "src/build/preseed_packages.sh")
        env = os.environ.copy()
        if bucket_name:
            env["DEPENDENCY_CACHE_GCS_BUCKET"] = bucket_name
        env["ENABLE_GCS"] = "true" if enable_gcs else "false"
        subprocess.run(["bash", script_path], cwd=REPO_ROOT, env=env, check=True)


def sync_to_gcs(bucket_name):
    """Synchronizes downloaded binaries and Debian packages to the specified GCS bucket."""
    clean_bucket = bucket_name.replace("gs://", "").rstrip("/")
    print(f"[-] Synchronizing offline dependencies to GCS: gs://{clean_bucket}/ ...")

    # 1. Binaries
    if os.path.exists(BIN_CACHE_DIR) and os.listdir(BIN_CACHE_DIR):
        print(f"  [-] Uploading binaries from {BIN_CACHE_DIR} to gs://{clean_bucket}/binaries/ ...")
        subprocess.run(
            ["gcloud", "storage", "cp", f"{BIN_CACHE_DIR}/*", f"gs://{clean_bucket}/binaries/", "--quiet"],
            check=True,
        )

    # 2. Packages
    if os.path.exists(PKG_CACHE_DIR) and glob.glob(os.path.join(PKG_CACHE_DIR, "*.deb")):
        print(f"  [-] Uploading debian packages from {PKG_CACHE_DIR} to gs://{clean_bucket}/packages/ ...")
        subprocess.run(
            ["gcloud", "storage", "cp", f"{PKG_CACHE_DIR}/*.deb", f"gs://{clean_bucket}/packages/", "--quiet"],
            check=True,
        )

    print("  [x] GCS cache synchronization complete.")


def main():
    parser = argparse.ArgumentParser(
        description="GDC Dependency & Offline Package Update Engine for CI/CD and Local Workstations."
    )
    parser.add_argument(
        "subcommand",
        nargs="?",
        choices=["check", "update-binaries", "update-packages", "add-dependency", "sync-gcs", "all"],
        help="Optional subcommand (e.g. check, add-dependency, update-packages).",
    )
    parser.add_argument(
        "--type",
        choices=["pkg", "binary"],
        help="Dependency type for add-dependency ('pkg' or 'binary').",
    )
    parser.add_argument(
        "--name",
        help="Dependency name (e.g. dnsmasq, mytool).",
    )
    parser.add_argument(
        "--version",
        help="Binary version (for binary dependencies).",
    )
    parser.add_argument(
        "--url",
        help="Download URL (for binary dependencies).",
    )
    parser.add_argument(
        "--sha256",
        help="SHA-256 hash (optional, auto-computed from URL if omitted).",
    )
    parser.add_argument(
        "--filename",
        help="Filename override (optional, defaults to basename of URL).",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        default=False,
        help="For packages: also add to customer_install_packages in Ansible so it is pre-installed on boot.",
    )
    parser.add_argument(
        "--preseed",
        action="store_true",
        default=False,
        help="For packages: immediately run the preseed pipeline to download .deb files.",
    )
    parser.add_argument(
        "--add-pkg",
        metavar="PKG_NAME",
        help="Shorthand for add-dependency --type pkg --name <PKG_NAME>.",
    )
    parser.add_argument(
        "--add-binary",
        metavar="BIN_NAME",
        help="Shorthand for add-dependency --type binary --name <BIN_NAME>.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Check upstream version status without making modifications.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output check audit results in structured JSON format.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        default=False,
        help="Output check audit results as a Markdown table (ideal for MR descriptions/logs).",
    )
    parser.add_argument(
        "--update-binary",
        metavar="BINARY_NAME",
        help="Update a specific binary in dependencies.env (e.g., kubestr, helm, gitea, step-cli).",
    )
    parser.add_argument(
        "--update-all-binaries",
        action="store_true",
        default=False,
        help="Update all binaries in dependencies.env where a newer stable upstream release exists.",
    )
    parser.add_argument(
        "--update-packages",
        action="store_true",
        default=False,
        help="Run the Noble 24.04 Debian package resolution pipeline to refresh .deb files.",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        default=False,
        help="Execute Debian package resolution inside an isolated 'ubuntu:24.04' Docker container.",
    )
    parser.add_argument(
        "--sync-gcs",
        action="store_true",
        default=False,
        help="Synchronize cached binaries and packages to the GCS bucket.",
    )
    parser.add_argument(
        "--gcs-bucket",
        help="Override target GCS bucket for --sync-gcs (default: from build.env).",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        default=False,
        help="Run in CI gate mode: exits with 2 if any binary updates are available.",
    )

    args = parser.parse_args()

    deps_env = parse_env_file(DEPS_ENV_PATH)
    build_env = parse_env_file(BUILD_ENV_PATH)
    bucket = args.gcs_bucket or build_env.get("DEPENDENCY_CACHE_GCS_BUCKET", "gdc-disk-provisioner-isos")

    # Handle add-dependency
    is_add = (
        (args.subcommand == "add-dependency")
        or bool(args.add_pkg)
        or bool(args.add_binary)
        or (args.type is not None)
    )
    if is_add:
        dep_type = args.type
        name = args.name
        if args.add_pkg:
            dep_type = "pkg"
            name = args.add_pkg
        elif args.add_binary:
            dep_type = "binary"
            name = args.add_binary

        if not dep_type or not name:
            sys.stderr.write("ERROR: Both --type (pkg|binary) and --name are required for add-dependency.\n")
            sys.exit(1)

        if dep_type == "pkg":
            ok = add_package_dependency(name, install=args.install)
            if not ok:
                sys.exit(1)
            if args.preseed:
                run_preseed_debian_packages(
                    use_docker=args.docker,
                    enable_gcs=args.sync_gcs,
                    bucket_name=bucket,
                )
            sys.exit(0)
        elif dep_type == "binary":
            if not args.version or not args.url:
                sys.stderr.write("ERROR: --version and --url are required when adding a binary dependency.\n")
                sys.exit(1)
            ok = add_binary_dependency(
                name=name,
                version=args.version,
                url=args.url,
                sha256=args.sha256,
                filename=args.filename,
                subpath=args.filename,
            )
            if not ok:
                sys.exit(1)
            sys.exit(0)

    # Subcommand mapping
    if args.subcommand == "check":
        args.check = True
    elif args.subcommand == "update-binaries":
        args.update_all_binaries = True
    elif args.subcommand == "update-packages":
        args.update_packages = True
    elif args.subcommand == "sync-gcs":
        args.sync_gcs = True
    elif args.subcommand == "all":
        args.update_all_binaries = True
        args.update_packages = True
        args.sync_gcs = True

    # If no action flags passed, default to check
    if not (
        args.check
        or args.update_binary
        or args.update_all_binaries
        or args.update_packages
        or args.sync_gcs
        or args.ci
    ):
        args.check = True

    results = {}
    if args.check or args.ci or args.update_binary or args.update_all_binaries:
        results = check_upstream_versions(deps_env)

    if args.json:
        print(json.dumps(results, indent=2))
    elif args.check or args.ci:
        print_audit_table(results, as_markdown=args.markdown)

    # Handle Binary Updates
    if args.update_binary:
        target = args.update_binary.lower()
        if target not in results:
            sys.stderr.write(f"ERROR: Unknown or unsupported binary '{target}'. Available: {list(results.keys())}\n")
            sys.exit(1)
        update_dependencies_env(target, results[target])
    elif args.update_all_binaries:
        updated_any = False
        for target, data in results.items():
            if data.get("update_available"):
                print(f"[-] Updating '{target}' to {data.get('latest')}...")
                if update_dependencies_env(target, data):
                    updated_any = True
        if not updated_any:
            print("[x] All binaries are already at the latest compatible versions.")

    # Handle Debian Package Updates
    if args.update_packages:
        run_preseed_debian_packages(
            use_docker=args.docker,
            enable_gcs=args.sync_gcs,
            bucket_name=bucket,
        )

    # Handle GCS Synchronization
    if args.sync_gcs and not args.update_packages:
        sync_to_gcs(bucket)

    # CI Mode gate check
    if args.ci:
        has_updates = any(v.get("update_available") for v in results.values())
        if has_updates:
            sys.stderr.write("\n[!] CI Gate Notice: Upstream dependency updates are available.\n")
            sys.exit(2)
        else:
            print("\n[x] CI Gate Pass: All dependencies match upstream baselines.")
            sys.exit(0)


if __name__ == "__main__":
    main()
