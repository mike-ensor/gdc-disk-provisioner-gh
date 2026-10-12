#!/usr/bin/env python3

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

# ==============================================================================
# GDC Endpoints Connectivity & DNS Preflight Checker
# ==============================================================================
# Performs high-speed concurrent DNS resolution and TCP/UDP socket checks
# across Google APIs, container registries, and local platform endpoints.
# Supports YAML manifests with 'system' vs 'platform' scopes and 'always' vs
# 'once.<stage>' execution cadences.
# ==============================================================================

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import os
import re
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    yaml = None

DEFAULT_DOMAINS = [
    "accounts.google.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "connectgateway.googleapis.com",
    "containerregistry.googleapis.com",
    "gkeconnect.googleapis.com",
    "gkehub.googleapis.com",
    "gkeonprem.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "gkeonprem.mtls.googleapis.com",
    "oauth2.googleapis.com",
    "securetoken.googleapis.com",
    "servicecontrol.googleapis.com",
    "serviceusage.googleapis.com",
    "stackdriver.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
    "www.googleapis.com",
    "gcr.io",
    "k8s.gcr.io",
    "logging.gdce.googleapis.com",
    "storage.gdce.googleapis.com",
]


def clean_raw_target_string(entry: str) -> Optional[str]:
    """Cleans raw string from YAML, handling un-hydrated Jinja default expressions."""
    if not entry or not isinstance(entry, str):
        return None
    s = entry.strip()
    if not s:
        return None

    # Handle un-hydrated Jinja expressions like "{{ var | default('val') }}" or default(['val'])
    if "{{" in s and "}}" in s:
        match = re.search(r"default\(\s*(?:\[\s*)?['\"]([^'\"]+)['\"]", s)
        if match:
            return match.group(1).strip()
        # Strip braces if simple variable name
        inner = re.sub(r"[{}\s]", "", s)
        return inner if inner else None

    return s


def parse_endpoint_url(url_str: str, service_name: str, test_name: str) -> Optional[dict]:
    """Parses a URL or hostname string into a standardized target dictionary."""
    cleaned = clean_raw_target_string(url_str)
    if not cleaned or " " in cleaned:
        return None

    try:
        # Check if URL scheme is present
        if "://" in cleaned:
            parsed = urlparse(cleaned)
            hostname = parsed.hostname
            if not hostname:
                return None
            port = parsed.port or (443 if parsed.scheme == "https" else (123 if parsed.scheme == "ntp" else 80))
            is_ntp = parsed.scheme == "ntp" or port == 123
        else:
            # Bare domain or domain:port
            if ":" in cleaned and not cleaned.endswith("]"):
                parts = cleaned.split(":")
                hostname = parts[0]
                port = int(parts[1])
            else:
                hostname = cleaned
                port = 123 if ("time" in hostname or "ntp" in hostname) else 443
            is_ntp = port == 123

        return {
            "test_name": test_name,
            "service_label": service_name,
            "service": test_name.replace("endpoint_connect_", ""),
            "domain": hostname,
            "port": port,
            "url": cleaned if "://" in cleaned else None,
            "is_ntp": is_ntp,
        }
    except Exception:
        return None


def check_target(
    target: dict,
    timeout: float = 2.0,
    dns_retries: int = 1,
    dns_retry_delay: float = 1.0,
) -> dict:
    """Executes DNS resolution and TCP/UDP socket connectivity verification for a target."""
    test_name = target["test_name"]
    domain = target["domain"]
    port = target.get("port", 443)
    service_label = target.get("service_label")
    url = target.get("url")
    is_ntp = target.get("is_ntp", False)
    scope = target.get("scope", "system")
    cadence = target.get("cadence", "always")
    target_stage = target.get("target_stage")
    current_stage = target.get("current_stage", "preflight")

    # If test is marked as not scheduled for this stage, emit SKIPPED immediately
    if target.get("skip_execution", False):
        return {
            "test_name": test_name,
            "category": "network",
            "status": "SKIPPED",
            "severity": "INFO",
            "notes": (
                f"Check deferred: designated for stage '{target_stage}' "
                f"(current stage: '{current_stage}')."
            ),
            "remediation_hint": f"No action required. This check will be evaluated during stage '{target_stage}'.",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_ms": 0,
            "meta": {
                "scope": scope,
                "cadence": cadence,
                "executed": False,
                "target_stage": target_stage,
                "current_stage": current_stage,
                "domain": domain,
                "port": port,
                "url": url,
                "dns_resolved": None,
                "resolved_ip": None,
                "tcp_connected": None,
            },
        }

    t0 = time.time()
    dns_resolved = False
    resolved_ip = None
    connected = False
    err_msg = ""
    attempts_made = 0

    # Determine retry count based on target scope (platform endpoints get configured retries)
    effective_retries = dns_retries if scope == "platform" else 1

    for attempt in range(1, effective_retries + 1):
        attempts_made = attempt
        try:
            ip = socket.gethostbyname(domain)
            dns_resolved = True
            resolved_ip = ip

            if is_ntp:
                # UDP socket check: send basic packet or test reachability
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(timeout)
                    s.connect((ip, port))
                    connected = True
            else:
                with socket.create_connection((ip, port), timeout=timeout):
                    connected = True
            break
        except Exception as e:
            err_msg = str(e)
            if attempt < effective_retries:
                time.sleep(dns_retry_delay)

    duration_ms = int((time.time() - t0) * 1000)

    proto_label = "UDP" if is_ntp else "TCP"
    fallback_recommended = False

    if connected:
        status = "PASS"
        if service_label:
            notes = f"{service_label} ({domain}:{port}): Resolved to {resolved_ip} and connected via {proto_label}/{port} successfully."
            remediation_hint = f"Endpoint {domain}:{port} is reachable."
        else:
            notes = f"Resolved to {resolved_ip} and connected via {proto_label}/{port} successfully."
            remediation_hint = f"Check DNS server resolution and outbound firewall rules for {domain}:{port}."
    elif dns_resolved:
        status = "WARN"
        if service_label:
            notes = (
                f"{service_label} ({domain}:{port}): DNS resolved to {resolved_ip}, "
                f"but {proto_label}/{port} connection failed: {err_msg} (Host unreachable or port {port} closed)."
            )
            remediation_hint = f"Check network routing, default gateway reachability, and firewall rules for {resolved_ip}:{port} ({domain})."
        else:
            notes = f"DNS resolved to {resolved_ip}, but {proto_label}/{port} connection failed: {err_msg}"
            remediation_hint = f"Check DNS server resolution and outbound firewall rules for {domain}:{port}."
        if scope == "platform":
            fallback_recommended = True
    else:
        status = "WARN"
        if service_label:
            retry_note = f" after {attempts_made} attempts" if attempts_made > 1 else ""
            notes = (
                f"{service_label} ({domain}:{port}): DNS resolution failed{retry_note}: {err_msg}. "
                f"Host '{domain}' could not be resolved by DNS nameservers or /etc/hosts."
            )
            remediation_hint = f"Verify DNS nameserver configuration or ensure '{domain}' is mapped in /etc/hosts (via src/build/add-hosts)."
        else:
            notes = f"DNS resolution failed: {err_msg}"
            remediation_hint = f"Check DNS server resolution and outbound firewall rules for {domain}:{port}."
        if scope == "platform":
            fallback_recommended = True

    meta = {
        "scope": scope,
        "cadence": cadence,
        "executed": True,
        "domain": domain,
        "port": port,
        "dns_resolved": dns_resolved,
        "resolved_ip": resolved_ip,
        "tcp_connected": connected if not is_ntp else None,
        "udp_connected": connected if is_ntp else None,
        "attempts": attempts_made,
    }
    if fallback_recommended:
        meta["fallback_recommended"] = True
    if url:
        meta["url"] = url
    if target_stage:
        meta["target_stage"] = target_stage
    if "service" in target:
        meta["service"] = target["service"]

    return {
        "test_name": test_name,
        "category": "network",
        "status": status,
        "severity": "WARNING" if status != "PASS" else "INFO",
        "notes": notes,
        "remediation_hint": remediation_hint,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": duration_ms,
        "meta": meta,
    }


def load_manifest(config_input: str) -> dict:
    """Loads a YAML or JSON manifest from a file path or string."""
    content = ""
    if os.path.exists(config_input):
        with open(config_input, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = config_input

    if yaml is not None:
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return json.loads(content)


STAGE_ORDER = {
    "livecd": 0,
    "live_cd": 0,
    "live-cd": 0,
    "preflight": 0,
    "first_boot": 1,
    "first-boot": 1,
    "second_boot": 2,
    "second-boot": 2,
    "linux_ready": 3,
    "linux-ready": 3,
    "cluster_ready": 4,
    "cluster-ready": 4,
    "cluster_turnup": 5,
    "cluster-turnup": 5,
    "post_cluster": 6,
    "post-cluster": 6,
    "post_validation": 6,
    "post-validation": 6,
    "upkeep": 7,
    "update_upkeep": 7,
    "update-upkeep": 7,
    "complete": 8,
    "all": 999,
    "*": 999,
}


def build_targets_from_manifest(manifest: dict, current_stage: str = "preflight") -> List[dict]:
    """Constructs test target specifications from a loaded manifest and stage filter."""
    targets = []
    current_stage_normalized = current_stage.lower().strip()
    is_all_stage = current_stage_normalized in ("all", "*")
    current_idx = STAGE_ORDER.get(current_stage_normalized, 0)

    for scope in ("system", "platform"):
        scope_data = manifest.get(scope, {})
        if not isinstance(scope_data, dict):
            continue

        # 1. 'always' cadence
        always_list = scope_data.get("always", [])
        if isinstance(always_list, list):
            for raw_item in always_list:
                items_to_process = raw_item if isinstance(raw_item, list) else [raw_item]
                for item in items_to_process:
                    if not item:
                        continue
                    test_id = f"endpoint_connect_{clean_raw_target_string(str(item))}"
                    label = "GDC Platform" if scope == "platform" else "Google API"
                    parsed = parse_endpoint_url(str(item), label, test_id)
                    if parsed:
                        parsed["scope"] = scope
                        parsed["cadence"] = "always"
                        parsed["skip_execution"] = False
                        parsed["current_stage"] = current_stage_normalized
                        targets.append(parsed)

        # 2. 'once' cadence grouped by stage
        once_dict = scope_data.get("once", {})
        if isinstance(once_dict, dict):
            for stage_name, stage_items in once_dict.items():
                if not isinstance(stage_items, list):
                    continue
                stage_normalized = stage_name.lower().strip()
                target_idx = STAGE_ORDER.get(stage_normalized, 999)
                should_execute = is_all_stage or (target_idx <= current_idx)

                for raw_item in stage_items:
                    items_to_process = raw_item if isinstance(raw_item, list) else [raw_item]
                    for item in items_to_process:
                        if not item:
                            continue
                        cleaned = clean_raw_target_string(str(item))
                        if not cleaned:
                            continue

                        # Generate friendly test_name
                        if "companion" in cleaned.lower():
                            test_id = "endpoint_connect_companion"
                            label = "GDC Companion"
                        elif "step-ca" in cleaned.lower() or "step_ca" in cleaned.lower():
                            test_id = "endpoint_connect_step_ca"
                            label = "Step CA"
                        else:
                            test_id = f"endpoint_connect_{cleaned}"
                            label = "GDC Platform" if scope == "platform" else "Google API"

                        parsed = parse_endpoint_url(str(item), label, test_id)
                        if parsed:
                            parsed["scope"] = scope
                            parsed["cadence"] = "once"
                            parsed["target_stage"] = stage_normalized
                            parsed["current_stage"] = current_stage_normalized
                            parsed["skip_execution"] = not should_execute
                            targets.append(parsed)

    return targets


def main():
    parser = argparse.ArgumentParser(description="Check Google and GDC endpoint connectivity")
    parser.add_argument("--config", help="Path to YAML/JSON endpoints manifest or inline string")
    parser.add_argument("--stage", default="preflight", help="Lifecycle stage (e.g. preflight, first-boot, second-boot, cluster-ready, all)")
    parser.add_argument("--dns-retries", type=int, default=5, help="Number of DNS retries for platform targets")
    parser.add_argument("--dns-retry-delay", type=float, default=2.0, help="Delay between DNS retries in seconds")
    parser.add_argument("--companion-url", help="GDC Companion URL override/fallback")
    parser.add_argument("--step-ca-url", help="Step CA URL override/fallback")
    parser.add_argument("--timeout", type=float, default=2.0, help="Socket connect timeout in seconds")
    parser.add_argument("--max-workers", type=int, default=12, help="Thread pool worker count")
    args = parser.parse_args()

    targets = []

    # 1. If --config provided or default manifest exists, build from manifest
    config_path = args.config
    if not config_path:
        default_manifest = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vars", "endpoints.yml"))
        if os.path.exists(default_manifest):
            config_path = default_manifest

    if config_path:
        try:
            manifest_data = load_manifest(config_path)
            targets = build_targets_from_manifest(manifest_data, current_stage=args.stage)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to load manifest from '{config_path}': {e}\n")

    # 2. CLI fallback / backwards compatibility if manifest not loaded or empty
    if not targets:
        companion_target = parse_endpoint_url(args.companion_url, "GDC Companion", "endpoint_connect_companion")
        if companion_target:
            companion_target["scope"] = "platform"
            companion_target["cadence"] = "always"
            companion_target["skip_execution"] = False
            targets.append(companion_target)

        step_ca_target = parse_endpoint_url(args.step_ca_url, "Step CA", "endpoint_connect_step_ca")
        if step_ca_target:
            step_ca_target["scope"] = "platform"
            step_ca_target["cadence"] = "always"
            step_ca_target["skip_execution"] = False
            targets.append(step_ca_target)

        for domain in DEFAULT_DOMAINS:
            targets.append({
                "test_name": f"endpoint_connect_{domain}",
                "domain": domain,
                "port": 443,
                "service_label": None,
                "url": None,
                "scope": "system",
                "cadence": "always",
                "skip_execution": False,
            })
    else:
        # If explicit CLI URLs were passed, ensure they override/update the manifest targets
        if args.companion_url:
            comp = parse_endpoint_url(args.companion_url, "GDC Companion", "endpoint_connect_companion")
            if comp:
                existing = next((t for t in targets if t["test_name"] == "endpoint_connect_companion"), None)
                if existing:
                    existing["domain"] = comp["domain"]
                    existing["port"] = comp["port"]
                    existing["url"] = comp["url"]
                else:
                    comp["scope"] = "platform"
                    comp["cadence"] = "once"
                    comp["target_stage"] = "second-boot"
                    comp["skip_execution"] = args.stage not in ("all", "second-boot")
                    targets.append(comp)

        if args.step_ca_url:
            step = parse_endpoint_url(args.step_ca_url, "Step CA", "endpoint_connect_step_ca")
            if step:
                existing = next((t for t in targets if t["test_name"] == "endpoint_connect_step_ca"), None)
                if existing:
                    existing["domain"] = step["domain"]
                    existing["port"] = step["port"]
                    existing["url"] = step["url"]
                else:
                    step["scope"] = "platform"
                    step["cadence"] = "once"
                    step["target_stage"] = "second-boot"
                    step["skip_execution"] = args.stage not in ("all", "second-boot")
                    targets.append(step)

    checker = partial(
        check_target,
        timeout=args.timeout,
        dns_retries=args.dns_retries,
        dns_retry_delay=args.dns_retry_delay,
    )
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        results = list(executor.map(checker, targets))

    print(json.dumps(results))


if __name__ == "__main__":
    main()
