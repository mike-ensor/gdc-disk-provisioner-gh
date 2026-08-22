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
# GDC Dynamic Test Execution & Results Exporter
# ==============================================================================
# Dynamically discovers and executes all python unit tests, monitors static
# artifact validations, and serializes all results to test_results.json.
# ==============================================================================

import os
import sys
import json
import time
import unittest
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.join(PROJECT_ROOT, "build-workspace")
RESULTS_JSON = os.path.join(WORKSPACE, "test_results.json")

class JSONTestResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.results = []
        self.start_times = {}

    def startTest(self, test):
        super().startTest(test)
        self.start_times[test] = time.time()

    def addSuccess(self, test):
        super().addSuccess(test)
        duration = time.time() - self.start_times.get(test, time.time())
        doc = test.shortDescription() or test._testMethodDoc or "No description provided."
        self.results.append({
            "file": os.path.basename(sys.modules[test.__class__.__module__].__file__ or ""),
            "class": test.__class__.__name__,
            "test_case": test._testMethodName,
            "verification_criterion": doc.strip(),
            "status": "PASSED",
            "duration_seconds": round(duration, 3)
        })

    def addFailure(self, test, err):
        super().addFailure(test, err)
        duration = time.time() - self.start_times.get(test, time.time())
        doc = test.shortDescription() or test._testMethodDoc or "No description provided."
        self.results.append({
            "file": os.path.basename(sys.modules[test.__class__.__module__].__file__ or ""),
            "class": test.__class__.__name__,
            "test_case": test._testMethodName,
            "verification_criterion": doc.strip(),
            "status": "FAILED",
            "duration_seconds": round(duration, 3),
            "error": str(err[1])
        })

    def addError(self, test, err):
        super().addError(test, err)
        duration = time.time() - self.start_times.get(test, time.time())
        doc = test.shortDescription() or test._testMethodDoc or "No description provided."
        self.results.append({
            "file": os.path.basename(sys.modules[test.__class__.__module__].__file__ or ""),
            "class": test.__class__.__name__,
            "test_case": test._testMethodName,
            "verification_criterion": doc.strip(),
            "status": "FAILED",
            "duration_seconds": round(duration, 3),
            "error": str(err[1])
        })

def run_script_test(script_path, args, test_case_name, verification_criterion):
    """Executes a non-unittest verification script as a subprocess and captures results."""
    start_time = time.time()
    full_path = os.path.join(PROJECT_ROOT, script_path)
    
    if not os.path.exists(full_path):
        return {
            "file": os.path.basename(script_path),
            "class": "ScriptValidation",
            "test_case": test_case_name,
            "verification_criterion": verification_criterion,
            "status": "SKIPPED",
            "duration_seconds": 0.0,
            "error": "Script missing on host"
        }
        
    try:
        cmd = [full_path] + args
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        duration = time.time() - start_time
        status = "PASSED" if res.returncode == 0 else "FAILED"
        return {
            "file": os.path.basename(script_path),
            "class": "ScriptValidation",
            "test_case": test_case_name,
            "verification_criterion": verification_criterion,
            "status": status,
            "duration_seconds": round(duration, 3),
            "error": res.stderr.strip() if res.returncode != 0 else ""
        }
    except Exception as e:
        duration = time.time() - start_time
        return {
            "file": os.path.basename(script_path),
            "class": "ScriptValidation",
            "test_case": test_case_name,
            "verification_criterion": verification_criterion,
            "status": "FAILED",
            "duration_seconds": round(duration, 3),
            "error": str(e)
        }

def main():
    print("==============================================================================")
    print(" GDC DYNAMIC TEST RUNNER & EXPORTER")
    print("==============================================================================")
    os.makedirs(WORKSPACE, exist_ok=True)
    
    # 1. Discover and run all unittest-compatible test cases
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.join(PROJECT_ROOT, "test"), pattern="test_*.py")
    
    runner = unittest.TextTestRunner(resultclass=JSONTestResult, verbosity=1)
    result = runner.run(suite)
    
    test_results = getattr(result, "results", [])
    
    # 2. Run static layout and artifacts checks
    print("[-] Running static verification checks...")
    extract_dir = os.path.join(WORKSPACE, "custom-iso")
    
    # validate_artifacts.py
    artifact_res = run_script_test(
        "test/validate_artifacts.py", [extract_dir, WORKSPACE],
        "validate_artifacts",
        "Performs strict schema, netplan dry-run, and systemd unit verification on staged files."
    )
    test_results.append(artifact_res)
    
    # validate_iso_static.py (Runs on the generated output ISO if present)
    iso_res = run_script_test(
        "test/validate_iso_static.py", [],
        "validate_iso_static",
        "Verifies checksums of external dependencies, scans filesystem layout, and checks user-data boot parameters."
    )
    test_results.append(iso_res)

    # 3. Write results to JSON
    with open(RESULTS_JSON, "w") as jf:
        json.dump(test_results, jf, indent=2)
        
    print("==============================================================================")
    print(f"[x] Dynamic test execution complete! Outcomes exported to: {RESULTS_JSON}")
    print("==============================================================================")
    
    # Exit with code 0 to allow report compilation even on test failures, 
    # as the report itself needs to publish the failure states!
    sys.exit(0)

if __name__ == "__main__":
    main()
