# GDC Software-Only Provisioning Presentation & Video Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author a complete Marp Markdown presentation suite and YouTube video production script repository covering Google Distributed Cloud (GDC) Software-Only Provisioning (`gdc-disk-provisioner` node engine and `gdc-companion` Day-0/Day-1 provisioning gateway) across six enterprise personas.

**Architecture:** Create a version-controlled presentation suite under `docs/presentations/` leveraging Marp CLI with a customized Google brand CSS theme (`docs/presentations/common/theme.css`). Develop a flagship overview deck (`00-flagship-overview.marp.md`) featuring a 10-slide high-impact pitch and 12 modular chapter slides, accompanied by four focused persona deep-dive decks (`01-operator-guide.marp.md`, `02-developer-workbench.marp.md`, `03-observability-and-companion.marp.md`, `04-architecture-and-security.marp.md`). Every slide embeds structured presenter notes with `[VISUAL]`, `[VOICEOVER]`, and `[LIVE DEMO / TERMINAL CUE]` blocks for direct YouTube video recording.

**Tech Stack:** Marp Markdown (`marp-cli`, `@marp-team/marp-core`), CSS3 themes, Mermaid.js diagrams, Bash verification scripts, Python frontmatter validation.

---

### Task 1: Presentation Directory Scaffolding & Marp Theme (`common/theme.css`)

**Files:**
- Create: `docs/presentations/common/theme.css`
- Create: `docs/presentations/README.md`
- Test: `test/test_presentations_syntax.py`

- [x] **Step 1: Write the test verifying presentation directory structure and theme existence**

```python
# test/test_presentations_syntax.py
import os
import pytest

PRESENTATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "presentations")

def test_presentations_directory_and_theme():
    assert os.path.isdir(PRESENTATIONS_DIR), "docs/presentations/ directory must exist"
    theme_file = os.path.join(PRESENTATIONS_DIR, "common", "theme.css")
    assert os.path.isfile(theme_file), "common/theme.css must exist"
    with open(theme_file, "r") as f:
        content = f.read()
    assert "@theme gdc-brand" in content, "theme.css must define @theme gdc-brand"
    assert "--color-google-blue" in content, "theme.css must define Google blue brand variable"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest test/test_presentations_syntax.py -v`
Expected: FAIL (Directory or file not found)

- [x] **Step 3: Implement `theme.css` and presentation `README.md`**

Create `docs/presentations/common/theme.css`:
```css
/* @theme gdc-brand */
@import 'default';

:root {
  --color-google-blue: #1A73E8;
  --color-google-red: #EA4335;
  --color-google-yellow: #FBBC04;
  --color-google-green: #34A853;
  --color-dark-bg: #202124;
  --color-light-bg: #FFFFFF;
  --color-text-main: #3C4043;
  --color-text-header: #202124;
}

section {
  font-family: 'Google Sans', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
  color: var(--color-text-main);
  background-color: var(--color-light-bg);
  padding: 40px 60px;
}

section.lead {
  background-color: var(--color-dark-bg);
  color: #FFFFFF;
  text-align: center;
}

section.lead h1 {
  color: #FFFFFF;
}

h1 {
  color: var(--color-google-blue);
  font-size: 2.2rem;
  margin-bottom: 0.5rem;
}

h2 {
  color: var(--color-text-header);
  font-size: 1.6rem;
  border-bottom: 2px solid #E8EAED;
  padding-bottom: 6px;
}

h3 {
  color: var(--color-google-blue);
  font-size: 1.3rem;
}

.badge-provisioner {
  display: inline-block;
  background-color: #E8F0FE;
  color: #1A73E8;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 0.8rem;
  font-weight: bold;
}

.badge-companion {
  display: inline-block;
  background-color: #CEEAD6;
  color: #137333;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 0.8rem;
  font-weight: bold;
}

table {
  font-size: 0.85rem;
  width: 100%;
  border-collapse: collapse;
}

th {
  background-color: #F1F3F4;
  color: #202124;
  font-weight: bold;
  border: 1px solid #DADCE0;
  padding: 8px;
}

td {
  border: 1px solid #DADCE0;
  padding: 8px;
}

pre {
  background-color: #F8F9FA;
  border: 1px solid #DADCE0;
  border-radius: 6px;
  font-size: 0.75rem;
}
```

Create `docs/presentations/README.md` detailing Marp rendering commands (`npx @marp-team/marp-cli@latest --html --theme common/theme.css <deck>.marp.md -o <deck>.html`).

- [x] **Step 4: Run test to verify it passes**

Run: `pytest test/test_presentations_syntax.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add docs/presentations/ test/test_presentations_syntax.py
git commit -m "feat(docs): scaffold presentations directory and Marp theme"
```

---

### Task 2: Flagship Overview Deck (`00-flagship-overview.marp.md`)

**Files:**
- Create: `docs/presentations/00-flagship-overview.marp.md`
- Test: `test/test_presentations_syntax.py`

- [ ] **Step 1: Write test verifying Flagship Deck structure and terminology**

Update `test/test_presentations_syntax.py` to add:
```python
def test_flagship_deck():
    flagship_path = os.path.join(PRESENTATIONS_DIR, "00-flagship-overview.marp.md")
    assert os.path.isfile(flagship_path), "00-flagship-overview.marp.md must exist"
    with open(flagship_path, "r") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower(), "Must NOT use airgapped, use Private Mode"
    assert "gdc-disk-provisioner" in content
    assert "gdc-companion" in content
    assert "[VOICEOVER]:" in content, "Presenter notes must have [VOICEOVER] script"
    assert "[VISUAL]:" in content, "Presenter notes must have [VISUAL] cue"
    # Ensure all 8 stages are listed
    for stage_num in range(1, 9):
        assert f"Stage {stage_num}" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_presentations_syntax.py -k test_flagship_deck -v`
Expected: FAIL (File not found)

- [ ] **Step 3: Implement `00-flagship-overview.marp.md`**

Write `docs/presentations/00-flagship-overview.marp.md`:
- Include Marp YAML frontmatter (`marp: true`, `theme: gdc-brand`, `size: 16:9`, `paginate: true`).
- **Part 1 (Slides 1–10):**
  - Slide 1: Title (GDC Software-Only Provisioning: Autonomous Bare-Metal at the Edge).
  - Slide 2: The Edge Reality & Planning for Network Outages.
  - Slide 3: Core Philosophy: 100% Offline-First in Private Mode.
  - Slide 4: Dual System Demarcation (`gdc-disk-provisioner` node engine vs `gdc-companion` Day-0/Day-1 config gateway).
  - Slide 5: The Persona Matrix (Operators, Developers, Viewers/Support, SecOps, Architects).
  - Slide 6: The 8-Stage Machine Overview with Mermaid flowchart.
  - Slide 7: Stage 1–3: The Hardware & Trust Foundation (DHCP, Subiquity, TPM 2.0 LUKS, UEFI boot order flip).
  - Slide 8: Stage 4–5: The Local Services Boundary (Loopback Gitea & Nexus, query to `gdc-companion`).
  - Slide 9: Stage 6–8: Offline Cluster Inception (`bmctl`) and Decentralized Day-2 Upkeep (`ansible-pull`).
  - Slide 10: Enterprise Outcomes (Zero console touch, outage resilience, hardware identity).
- **Part 2 (Slides 11–22):**
  - Slide 11: Chapter 1 Transition: The Operator Experience.
  - Slide 12: Operator Prerequisites & Turnup Sequence.
  - Slide 13: Chapter 2 Transition: Developer Inner Loop.
  - Slide 14: Developer Workflow (`build.sh`, `bootimus.py`, lab testing, AMD Zen 4 quirks).
  - Slide 15: Chapter 3 Transition: Observability & Health Monitoring.
  - Slide 16: Telemetry & Hardware Correlation (`build_id`, `mac`, state files).
  - Slide 17: Chapter 4 Transition: Zero-Trust Security in Private Mode.
  - Slide 18: Cryptographic Attestation (TPM 2.0 EKCert, Step CA, mTLS with MAC SAN, 1-hr GCP token broker).
  - Slide 19: Local Boundary Isolation & CIS Level 2 Hardening.
  - Slide 20: The Deep Dive Series Roadmap (Episodes 2–5 summary).
  - Slide 21: Summary & Repository Resources.
- Every slide must include `<!-- \n[VISUAL]: ...\n[VOICEOVER]: ...\n[LIVE DEMO / TERMINAL CUE]: ...\n-->`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_presentations_syntax.py -k test_flagship_deck -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/presentations/00-flagship-overview.marp.md test/test_presentations_syntax.py
git commit -m "feat(docs): add flagship overview presentation deck and video script"
```

---

### Task 3: Operator Guide Deck (`01-operator-guide.marp.md`)

**Files:**
- Create: `docs/presentations/01-operator-guide.marp.md`
- Test: `test/test_presentations_syntax.py`

- [ ] **Step 1: Write test verifying Operator Guide Deck**

Update `test/test_presentations_syntax.py`:
```python
def test_operator_deck():
    path = os.path.join(PRESENTATIONS_DIR, "01-operator-guide.marp.md")
    assert os.path.isfile(path), "01-operator-guide.marp.md must exist"
    with open(path, "r") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower()
    assert "Bootimus" in content
    assert "Smart Hands" in content
    assert "VLAN" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_presentations_syntax.py -k test_operator_deck -v`
Expected: FAIL

- [ ] **Step 3: Implement `01-operator-guide.marp.md`**

Write `docs/presentations/01-operator-guide.marp.md`:
- Slide breakdown (12–15 slides):
  - Operator Role Separation (Fleet Platform Engineer vs Smart Hands / Field Tech).
  - Infrastructure Baseline (DHCP reservations for Stage 1, VLAN boundaries for Stage 2+, DNS/NTP).
  - Setting up Bootimus PXE & fallback USB media creation.
  - Step-by-Step Node Boot Sequence (What Smart Hands see vs what Fleet Engineers monitor).
  - The Automated 2-Reboot cycle: Stage 1 (LiveCD Subiquity) $\rightarrow$ Stage 2 (TPM Sealing) $\rightarrow$ Stage 3 (Auto-Unlock verification).
  - Transitioning to production static VLANs (Stage 4 Linux Ready).
  - Gating cluster creation with `gdc-companion` and offline `bmctl` inception.
  - Day-2 autonomous drift management via `gdc-provision.timer` and `ansible-pull`.
  - Operational Runbooks: Triage, inspecting `/var/gdc-install/state/`, and automated node resets.
  - Full presenter notes (`[VISUAL]`, `[VOICEOVER]`, `[LIVE DEMO / TERMINAL CUE]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_presentations_syntax.py -k test_operator_deck -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/presentations/01-operator-guide.marp.md test/test_presentations_syntax.py
git commit -m "feat(docs): add operator guide presentation deck and video script"
```

---

### Task 4: Developer Workbench Deck (`02-developer-workbench.marp.md`)

**Files:**
- Create: `docs/presentations/02-developer-workbench.marp.md`
- Test: `test/test_presentations_syntax.py`

- [ ] **Step 1: Write test verifying Developer Workbench Deck**

Update `test/test_presentations_syntax.py`:
```python
def test_developer_deck():
    path = os.path.join(PRESENTATIONS_DIR, "02-developer-workbench.marp.md")
    assert os.path.isfile(path), "02-developer-workbench.marp.md must exist"
    with open(path, "r") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower()
    assert "remaster.sh" in content
    assert "bootimus.py" in content
    assert "Zen 4" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_presentations_syntax.py -k test_developer_deck -v`
Expected: FAIL

- [ ] **Step 3: Implement `02-developer-workbench.marp.md`**

Write `docs/presentations/02-developer-workbench.marp.md`:
- Slide breakdown (12–15 slides):
  - Developer Architecture & Subsystems.
  - Workstation & Lab Setup (`build.env`, test targets, lab environments like `barn`).
  - Remastering Engine Internals (`build.sh`, `remaster.sh`, `xorriso`, Subiquity autoinstall templating).
  - Bundling Offline Boundary Repositories: Cloning bare Git repos into `/custom-data/gitea/` and apt/container mirrors into Nexus.
  - The Fast Inner Loop: Compiling ISOs, deploying via `./src/build/bootimus.py --next-boot ...`.
  - Conquering Bare-Metal Hardware Quirks: AMD Zen 4 kernel flags (`modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp`), NVMe probe races, and UEFI `efibootmgr` manipulations.
  - Diagnostics Agent & Automated RCA: Running diagnostics against live nodes and generating markdown RCA reports.
  - Full presenter notes (`[VISUAL]`, `[VOICEOVER]`, `[LIVE DEMO / TERMINAL CUE]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_presentations_syntax.py -k test_developer_deck -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/presentations/02-developer-workbench.marp.md test/test_presentations_syntax.py
git commit -m "feat(docs): add developer workbench presentation deck and video script"
```

---

### Task 5: Observability & Telemetry Deck (`03-observability-and-companion.marp.md`)

**Files:**
- Create: `docs/presentations/03-observability-and-companion.marp.md`
- Test: `test/test_presentations_syntax.py`

- [ ] **Step 1: Write test verifying Observability Deck**

Update `test/test_presentations_syntax.py`:
```python
def test_observability_deck():
    path = os.path.join(PRESENTATIONS_DIR, "03-observability-and-companion.marp.md")
    assert os.path.isfile(path), "03-observability-and-companion.marp.md must exist"
    with open(path, "r") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower()
    assert "build_id" in content
    assert "mac" in content
    assert "/var/gdc-install/state" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_presentations_syntax.py -k test_observability_deck -v`
Expected: FAIL

- [ ] **Step 3: Implement `03-observability-and-companion.marp.md`**

Write `docs/presentations/03-observability-and-companion.marp.md`:
- Slide breakdown (12–15 slides):
  - Observability in Outage-Resilient Edge Environments: Why passive phone-home/webhooks beat active SSH polling.
  - The Telemetry Contract: Parameters (`build_id`, `mac`, `version`, `logname`).
  - Hardware Identity Correlation: Using immutable primary MAC addresses to track nodes across dynamic, ephemeral kernel `build_id`s.
  - Live Webhook Stream: Ingesting events during Stage 1 Subiquity into `gdc-companion`.
  - Gating & State Checks: Stage 5 queries to `gdc-companion` for cluster parameters.
  - Node-Local State Persistence: Exploring `/var/gdc-install/state/*.json` (JSON state caches, step records, idempotency keys).
  - Triage Decision Tree: Root cause identification (Network/DHCP drop, TPM unsealing failure, NodeAgent stall, `bmctl` timeout).
  - Full presenter notes (`[VISUAL]`, `[VOICEOVER]`, `[LIVE DEMO / TERMINAL CUE]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_presentations_syntax.py -k test_observability_deck -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/presentations/03-observability-and-companion.marp.md test/test_presentations_syntax.py
git commit -m "feat(docs): add observability and telemetry presentation deck and video script"
```

---

### Task 6: Architecture & Security Deck (`04-architecture-and-security.marp.md`)

**Files:**
- Create: `docs/presentations/04-architecture-and-security.marp.md`
- Test: `test/test_presentations_syntax.py`

- [ ] **Step 1: Write test verifying Architecture & Security Deck**

Update `test/test_presentations_syntax.py`:
```python
def test_security_deck():
    path = os.path.join(PRESENTATIONS_DIR, "04-architecture-and-security.marp.md")
    assert os.path.isfile(path), "04-architecture-and-security.marp.md must exist"
    with open(path, "r") as f:
        content = f.read()
    assert "theme: gdc-brand" in content
    assert "Private Mode" in content
    assert "airgapped" not in content.lower()
    assert "Step CA" in content or "step-ca" in content.lower()
    assert "mTLS" in content
    assert "EKCert" in content
    assert "LUKS" in content
    assert "TPM 2.0" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_presentations_syntax.py -k test_security_deck -v`
Expected: FAIL

- [ ] **Step 3: Implement `04-architecture-and-security.marp.md`**

Write `docs/presentations/04-architecture-and-security.marp.md`:
- Slide breakdown (14–16 slides):
  - Architecture Principles: Evolutionary boundaries, Hub-and-Spoke sideloading, Private Mode as baseline.
  - The Hardware Trust Anchor: TPM 2.0 Endorsement Key Certificate (EKCert) as factory-issued birth certificate.
  - Measured Boot & Full Disk Encryption: Dynamic LVM partitioning and TPM-sealed LUKS (zero plaintext keys on disk).
  - The Zero-Touch Digital Passport Architecture:
    - Node generates non-exportable hardware key in TPM KMS.
    - Submits CSR + EKCert proof to **Step CA** via `step-cli`.
    - Step CA verifies manufacturer root signatures and mints `client.crt` with node MAC in Subject SAN.
  - Mutual TLS (mTLS) with `gdc-companion`:
    - Two-way verification over port 443.
    - Companion validates `client.crt` against Step CA root and checks SAN matches registered MAC.
  - Temporary Cloud Token Brokering: 1-hour ephemeral GCP tokens; no permanent cloud secrets on node storage.
  - Local Boundary Defense: Loopback-isolated Gitea (port 3000) and Nexus (port 8081/5001).
  - Host Hardening: CIS Level 2 benchmarks and NodeAgent firewall shielding.
  - Enterprise Scale & Zero-Drift Guarantees.
  - Full presenter notes (`[VISUAL]`, `[VOICEOVER]`, `[LIVE DEMO / TERMINAL CUE]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_presentations_syntax.py -k test_security_deck -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/presentations/04-architecture-and-security.marp.md test/test_presentations_syntax.py
git commit -m "feat(docs): add architecture and security presentation deck and video script"
```

---

### Task 7: Automated Compilation & Quality Verification Script

**Files:**
- Create: `docs/presentations/render_decks.sh`
- Test: `test/test_presentations_syntax.py`

- [ ] **Step 1: Write test verifying build script and markdown compilation validation**

Update `test/test_presentations_syntax.py`:
```python
def test_render_script_exists_and_executable():
    script_path = os.path.join(PRESENTATIONS_DIR, "render_decks.sh")
    assert os.path.isfile(script_path), "render_decks.sh must exist"
    assert os.access(script_path, os.X_OK), "render_decks.sh must be executable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_presentations_syntax.py -k test_render_script -v`
Expected: FAIL

- [ ] **Step 3: Implement `render_decks.sh`**

Create `docs/presentations/render_decks.sh`:
- Script checks for `npx @marp-team/marp-cli` availability.
- Iterates over all `*.marp.md` decks.
- Runs syntax checks and exports HTML outputs into `docs/presentations/dist/`.
- Validates that no forbidden terms ("airgapped") exist in any deck.
- Verifies that all Mermaid blocks are closed properly.

- [ ] **Step 4: Run full test suite and test rendering script**

Run: `pytest test/test_presentations_syntax.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add docs/presentations/render_decks.sh test/test_presentations_syntax.py
git commit -m "feat(docs): add automated presentation render script and test suite"
```
