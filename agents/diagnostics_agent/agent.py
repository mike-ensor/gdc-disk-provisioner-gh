# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

import os
import json
try:
    from google.adk import Agent, SequentialAgent  # type: ignore
except ImportError:
    # Fallback mock classes for static linting when ADK is not locally installed
    class Agent:
        def __init__(self, *args, **kwargs): pass
    class SequentialAgent:
        def __init__(self, *args, **kwargs): pass

from .tools import (
    scan_network_for_ips,
    probe_node_state,
    fetch_diagnostics_tarball,
    extract_and_analyze_tarball
)

# 1. DiscoveryAgent
discovery_agent = Agent(
    name="DiscoveryAgent",
    model="gemini-3-flash-preview",
    instruction="""
    You are the GDC Network Discovery Assistant.
    Your goal is to find the machine's IP if it is not provided.
    Use scan_network_for_ips. Once you have the IP, run probe_node_state to determine if the node is booted, recovery, or crashed.
    """,
    tools=[scan_network_for_ips, probe_node_state],
    output_key="discovery_status"
)

# 2. CollectionAgent
collection_agent = Agent(
    name="CollectionAgent",
    model="gemini-3-flash-preview",
    instruction="""
    You are the GDC Diagnostic Collector Assistant.
    Your goal is to retrieve the diagnostics tarball from the node.
    Use fetch_diagnostics_tarball, passing the IP from discovery_status and the optional download_url.
    """,
    tools=[fetch_diagnostics_tarball],
    output_key="tarball_path"
)

# 3. AnalysisAgent
analysis_agent = Agent(
    name="AnalysisAgent",
    model="gemini-3-flash-preview",
    instruction="""
    You are the GDC Diagnostics Analyst.
    Extract and parse the logs using extract_and_analyze_tarball.
    Identify any failures related to:
    - TPM 2.0 unsealing or missing keyfile.
    - VRF Netplan routing or table exists conflicts.
    - Sonatype Nexus JVM SIGABRT crashes during uploads.
    - Missing packages on noble targets (such as systemd-initramfs).
    Also, extract the booted GDC ISO Version and list all active SSH users and their authentication comments.
    """,
    tools=[extract_and_analyze_tarball],
    output_key="analysis_data"
)

# 4. RcaWriterAgent
rca_writer_agent = Agent(
    name="RcaWriterAgent",
    model="gemini-3-flash-preview",
    instruction="""
    You are an expert Root Cause Analysis (RCA) writer.
    Consolidate log facts, and compile a structured Root Cause Analysis Markdown report.
    
    CRITICAL SPECIFICATIONS:
    - Include the GDC ISO Version (from analysis_data.iso_version) inside the Header.
    - Include the list of authorized SSH users and their key comments in the Access & Authentication section.
    - Title format: RCA-v<iso_version>.md
    - List primary recommended fixes ordered by severity.
    - Write the final document to 'docs/rca/nexus-jvm-crash/RCA-v<iso_version>.md'.
    """
)

# Assemble Sequential Team
diagnostics_team = SequentialAgent(
    name="GDCDiagnosticsTeam",
    sub_agents=[discovery_agent, collection_agent, analysis_agent, rca_writer_agent]
)
