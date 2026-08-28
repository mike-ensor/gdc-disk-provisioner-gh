#!/usr/bin/env python3

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

def audit_states(state_dir: str = "/var/gdc-install/state") -> None:
    state_path = Path(state_dir)
    if not state_path.exists():
        print(f"Error: State directory {state_dir} does not exist.")
        return

    states = []
    for state_file in state_path.glob("*.json"):
        try:
            with open(state_file, "r") as f:
                data = json.load(f)
                states.append({
                    "stage": state_file.stem,
                    "status": data.get("status", "UNKNOWN"),
                    "timestamp": data.get("timestamp", "N/A")
                })
        except json.JSONDecodeError as e:
            print(f"Warning: Could not parse {state_file}: {e}")
            continue
    
    states.sort(key=lambda x: x["stage"])
    
    print(f"{'Stage':<20} | {'Status':<10} | {'Timestamp'}")
    print("-" * 50)
    for s in states:
        status = s['status'].upper()
        status_padded = f"{status:<10}"
        # Simple terminal colors if output is a TTY
        if sys.stdout.isatty():
            if status == "FAILED":
                status_padded = f"\033[91m{status_padded}\033[0m"
            elif status == "PENDING":
                status_padded = f"\033[93m{status_padded}\033[0m"
        print(f"{s['stage']:<20} | {status_padded} | {s['timestamp']}")

if __name__ == "__main__":
    audit_states()
