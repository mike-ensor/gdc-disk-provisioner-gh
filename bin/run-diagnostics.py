#!/usr/bin/env python3
import os
import sys

# Add agents/diagnostics_agent to the sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../agents/diagnostics_agent")))

import run  # type: ignore

if __name__ == "__main__":
    run.main()
