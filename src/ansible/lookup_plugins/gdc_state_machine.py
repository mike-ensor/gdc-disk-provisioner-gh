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


def get_current_stage(
    state_dir: str = "/var/gdc-install/state",
    fallback_config_path: str = "/etc/gdc/fallback-config.json",
    fstab_path: str = "/etc/fstab",
) -> GdcStage:
    """Resolves the current active GDC lifecycle stage.

    Evaluates gates sequentially. Returns the first stage that is not yet completed.
    If a configured stop_stage has completed, returns GdcStage.COMPLETE.
    """
    # 1. Read stop stage if configured
    stop_stage_enum: Optional[GdcStage] = None
    if os.path.exists(fallback_config_path):
        try:
            with open(fallback_config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                stop_str = str(cfg.get("machine_state_stop_stage", "")).strip().upper()
                if stop_str in STOP_STAGE_MAP:
                    stop_stage_enum = STOP_STAGE_MAP[stop_str]
        except Exception:
            pass

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
