# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0
"""GDC Node Lifecycle State Machine and Gate Resolution Engine."""

from enum import Enum
import json
import os
from typing import List, Optional


class GdcStage(str, Enum):
    """Canonical GDC node lifecycle stages."""

    LIVECD = "live-cd"
    FIRST_BOOT = "first-boot"
    SECOND_BOOT = "second-boot"
    LINUX_READY = "linux-ready"
    CLUSTER_READY = "cluster-ready"
    CLUSTER_TURNUP = "cluster-turnup"
    POST_CLUSTER = "post-cluster"
    UPKEEP = "upkeep"
    COMPLETE = "complete"


# Map from stop_stage string representations to canonical GdcStage
STOP_STAGE_MAP = {
    "LIVECD": GdcStage.LIVECD,
    "LIVE_CD": GdcStage.LIVECD,
    "LIVE-CD": GdcStage.LIVECD,
    "FIRST_BOOT": GdcStage.FIRST_BOOT,
    "FIRST-BOOT": GdcStage.FIRST_BOOT,
    "SECOND_BOOT": GdcStage.SECOND_BOOT,
    "SECOND-BOOT": GdcStage.SECOND_BOOT,
    "LINUX_READY": GdcStage.LINUX_READY,
    "LINUX-READY": GdcStage.LINUX_READY,
    "CLUSTER_READY": GdcStage.CLUSTER_READY,
    "CLUSTER-READY": GdcStage.CLUSTER_READY,
    "CLUSTER_TURNUP": GdcStage.CLUSTER_TURNUP,
    "CLUSTER-TURNUP": GdcStage.CLUSTER_TURNUP,
    "POST_CLUSTER": GdcStage.POST_CLUSTER,
    "POST-CLUSTER": GdcStage.POST_CLUSTER,
    "POST_VALIDATION": GdcStage.POST_CLUSTER,
    "POST-VALIDATION": GdcStage.POST_CLUSTER,
    "UPDATE_UPKEEP": GdcStage.UPKEEP,
    "UPDATE-UPKEEP": GdcStage.UPKEEP,
    "UPKEEP": GdcStage.UPKEEP,
}

# Gate definitions: (Stage Enum, List of acceptable state filenames)
GDC_GATE_SEQUENCE = [
    (GdcStage.LIVECD, ["live-cd.json"]),
    (GdcStage.FIRST_BOOT, ["first-boot.json"]),
    (GdcStage.SECOND_BOOT, ["second-boot.json"]),
    (GdcStage.LINUX_READY, ["linux-ready.json"]),
    (GdcStage.CLUSTER_READY, ["cluster-ready.json"]),
    (GdcStage.CLUSTER_TURNUP, ["cluster-turnup.json"]),
    (GdcStage.POST_CLUSTER, ["post-validation.json", "post-cluster.json"]),
    (GdcStage.UPKEEP, ["update-upkeep.json", "upkeep.json"]),
]


def _is_stage_file_completed(state_dir: str, filenames: List[str]) -> bool:
    """Checks whether any matching state file exists and has status == 'completed'."""
    for fn in filenames:
        path = os.path.join(state_dir, fn)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and str(data.get("status", "")).lower() == "completed":
                        return True
            except Exception:
                continue
    return False


def get_stop_stage(
    variables: Optional[dict] = None,
    candidate_config_paths: Optional[List[str]] = None,
    explicit_stop_stage: Optional[str] = None,
) -> str:
    """Resolves the normalized machine state stop stage.

    Precedence:
    1. explicit_stop_stage parameter
    2. variables (from Ansible context: stop_stage, MACHINE_STATE_STOP_STAGE, machine_config)
    3. os.environ['MACHINE_STATE_STOP_STAGE'] or os.environ['STOP_STAGE']
    4. Candidate configuration files on disk in priority order:
       - /var/gdc-install/state/gdc-fact-manual.json
       - /var/gdc-install/state/gdc-machine-facts-manual.json
       - /etc/ansible/facts.d/gdc.fact
       - /etc/gdc/machine-info-mock.json
       - /etc/gdc/fallback-config.json

    Returns:
        Canonical uppercase underscore string (e.g. 'CLUSTER_READY') or empty string.
    """
    raw_val: Optional[str] = None

    # 1. Explicit argument
    if explicit_stop_stage and str(explicit_stop_stage).strip():
        raw_val = str(explicit_stop_stage).strip()

    # 2. Ansible context variables
    if not raw_val and variables:
        for k in ("stop_stage", "MACHINE_STATE_STOP_STAGE"):
            v = variables.get(k)
            if v and str(v).strip():
                raw_val = str(v).strip()
                break
        if not raw_val and "machine_config" in variables:
            mc = variables.get("machine_config")
            if isinstance(mc, dict):
                v = mc.get("machine_state_stop_stage") or mc.get("stop_stage")
                if v and str(v).strip():
                    raw_val = str(v).strip()

    # 3. Candidate configuration files on disk
    if not raw_val:
        paths = candidate_config_paths or [
            "/var/gdc-install/state/gdc-fact-manual.json",
            "/var/gdc-install/state/gdc-machine-facts-manual.json",
            "/etc/ansible/facts.d/gdc.fact",
            "/etc/gdc/machine-info-mock.json",
            "/etc/gdc/fallback-config.json",
        ]
        for path in paths:
            if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    if isinstance(cfg, dict):
                        # Top-level check
                        v = cfg.get("machine_state_stop_stage") or cfg.get("stop_stage")
                        # Nested variables check (for companion API style payloads)
                        if not v and isinstance(cfg.get("variables"), dict):
                            v = cfg["variables"].get("machine_state_stop_stage") or cfg["variables"].get("stop_stage")
                        if v and str(v).strip():
                            raw_val = str(v).strip()
                            break
                except Exception:
                    continue

    # 4. Environment variables
    if not raw_val:
        env_val = os.environ.get("MACHINE_STATE_STOP_STAGE") or os.environ.get("STOP_STAGE")
        if env_val and env_val.strip():
            raw_val = env_val.strip()

    if not raw_val:
        return ""

    cleaned = raw_val.strip().upper().replace("-", "_")
    if cleaned in STOP_STAGE_MAP:
        return STOP_STAGE_MAP[cleaned].name
    return ""


def get_current_stage(
    state_dir: str = "/var/gdc-install/state",
    fallback_config_path: str = "/etc/gdc/fallback-config.json",
    fstab_path: str = "/etc/fstab",
    stop_stage: Optional[str] = None,
    variables: Optional[dict] = None,
) -> GdcStage:
    """Resolves the current active GDC lifecycle stage.

    Evaluates gates sequentially. Returns the first stage that is not yet completed.
    If a configured stop_stage has completed, returns GdcStage.COMPLETE.
    """
    # 1. Resolve stop stage if configured
    stop_stage_enum: Optional[GdcStage] = None
    candidate_paths = [
        "/var/gdc-install/state/gdc-fact-manual.json",
        "/var/gdc-install/state/gdc-machine-facts-manual.json",
        "/etc/ansible/facts.d/gdc.fact",
        "/etc/gdc/machine-info-mock.json",
    ]
    if fallback_config_path and fallback_config_path not in candidate_paths:
        candidate_paths.append(fallback_config_path)

    resolved_stop = get_stop_stage(
        variables=variables,
        candidate_config_paths=candidate_paths,
        explicit_stop_stage=stop_stage,
    )
    if resolved_stop and resolved_stop in STOP_STAGE_MAP:
        stop_stage_enum = STOP_STAGE_MAP[resolved_stop]

    # 2. Evaluate stage sequence
    for stage_enum, filenames in GDC_GATE_SEQUENCE:
        is_completed = False

        if stage_enum == GdcStage.LIVECD:
            # LiveCD is complete if state file exists or host fstab exists
            if _is_stage_file_completed(state_dir, filenames) or os.path.exists(fstab_path):
                is_completed = True
        else:
            is_completed = _is_stage_file_completed(state_dir, filenames)

        if not is_completed:
            return stage_enum

        # If this stage completed and matched the stop target, halt further execution
        if stop_stage_enum is not None and stage_enum == stop_stage_enum:
            return GdcStage.COMPLETE

    return GdcStage.COMPLETE
