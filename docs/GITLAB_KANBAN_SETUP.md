# GitLab Kanban Board & Scoped Labels Setup Guide

A standardized blueprint for provisioning lifecycle labels and configuring Kanban Issue Boards across GitLab projects.

---

## 1. Core Architecture & Label Types

GitLab supports **Scoped Labels** (`scope::value`) which enforce mutual exclusivity. Moving an issue between board lists automatically swaps the active label in that scope, preventing contradictory states (e.g. an issue cannot be both `workflow::ready` and `workflow::in progress`).

Labels are categorized into three orthogonal dimensions:
1. **Workflow (`workflow::*`)**: Represents the development stage (mapped 1:1 to Kanban columns).
2. **Work Type (`type::*`)**: Represents the nature of the work item (card badges).
3. **Priority (`priority::*`)**: Urgency and scheduling priority.

---

## 2. Complete Label Palette

### A. Workflow Labels (`workflow::*`) — Board Columns

| Label | Hex Code | Swatch | Meaning & Usage |
| :--- | :--- | :--- | :--- |
| `workflow::new` | `#8F8F8F` | 🔘 Slate Grey | Incoming, untriaged, or newly created backlog item. |
| `workflow::ready` | `#428BCA` | 🔵 Sky Blue | Acceptance criteria defined and groomed; ready for pickup. |
| `workflow::in progress` | `#1F75CB` | 🔷 Cobalt Blue | Branch created; developer is actively working on implementation. |
| `workflow::in review` | `#6F42C1` | 🟣 Purple | Merge Request open; peer review and CI pipeline running. |
| `workflow::reopened` | `#F0AD4E` | 🟠 Amber Orange | MR rejected, bug failed verification, or closed issue reopened. |
| `workflow::verification` | `#17A2B8` | 🟢 Cyan / Teal | Merged to default branch; awaiting release or smoke testing. |
| `workflow::blocked` | `#D9534F` | 🔴 Crimson Red | Work stopped due to an external dependency, blocker, or bug. |

### B. Work Type Labels (`type::*`) — Card Badges

| Label | Hex Code | Swatch | Description |
| :--- | :--- | :--- | :--- |
| `type::defect` | `#DC3545` | 🔴 High-Vis Red | Software defects, regressions, bugs, or unexpected behavior. |
| `type::feature` | `#28A745` | 🟢 Forest Green | New functionality, extensions, or product enhancements. |
| `type::maintenance` | `#6C757D` | ⚪ Slate Grey | Tech debt, dependency upgrades, refactoring, CI/CD, build tools. |
| `type::docs` | `#00A389` | 🌿 Mint / Teal | Architecture specs, manuals, inline documentation, runbooks. |

### C. Priority Labels (`priority::*`) — Urgency Badges

| Label | Hex Code | Swatch | Description |
| :--- | :--- | :--- | :--- |
| `priority::P1` | `#B60205` | 🚨 Deep Red | Critical / Production blocker (immediate action required). |
| `priority::P2` | `#E99695` | 🌸 Light Red | High urgency (must be resolved in current iteration/milestone). |
| `priority::P3` | `#FEEFB3` | 🟡 Pale Yellow | Normal priority (scheduled standard work). |
| `priority::P4` | `#E6E6E6` | ⚪ Light Grey | Low priority (backlog / opportunistic enhancement). |

---

## 3. Configuring the Issue Board (GitLab UI)

Follow these steps in any target GitLab repository:

1. Navigate to **Plan** ➔ **Issue Boards** (or **Issues** ➔ **Boards** depending on GitLab version).
2. Select or create your primary board (e.g. `Development Board`).
3. Click **Create list** / **Add list** and select **Label list**.
4. Add lists in the following chronological sequence:
   1. `workflow::ready`
   2. `workflow::in progress`
   3. `workflow::in review`
   4. `workflow::reopened`
   5. `workflow::verification`
5. Note on edge columns:
   - **Open list (Leftmost default column)**: Displays newly created issues (`workflow::new` or unlabelled items).
   - **Closed list (Rightmost default column)**: Displays completed/closed issues. Dragging a card here marks it as done.
6. **Optional Filtered Boards:**
   - **Bug Triage Board**: Create an additional board with a board-level filter set to `Label = type::defect`.
   - **Sprint/Milestone Board**: Set the board filter to `Current Milestone`.

---

## 4. Automated Provisioning Script (`glab` CLI)

Run this portable shell script to provision all labels into any target repository in one step.

### Usage
```bash
# Target the current git repository:
./setup-gitlab-labels.sh

# Or target a specific remote project:
./setup-gitlab-labels.sh my-org/subgroup/my-project
```

### Script: `setup-gitlab-labels.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_REPO="${1:-}"

if [ -n "$TARGET_REPO" ]; then
  REPO_FLAG=(-R "$TARGET_REPO")
  echo "Targeting repository: $TARGET_REPO"
else
  REPO_FLAG=()
  echo "Targeting current repository context"
fi

create_label() {
  local name="$1"
  local color="$2"
  local desc="$3"
  echo "Creating label: $name ($color)..."
  glab label create -n "$name" -c "$color" -d "$desc" "${REPO_FLAG[@]}" 2>/dev/null || \
    echo "  -> Note: Label '$name' may already exist; skipping."
}

echo "=== Provisioning Workflow Lifecycle Labels ==="
create_label "workflow::new"          "#8F8F8F" "Awaiting triage and refinement"
create_label "workflow::ready"        "#428BCA" "Refined and ready to be picked up"
create_label "workflow::in progress"  "#1F75CB" "Active development underway"
create_label "workflow::in review"    "#6F42C1" "Merge Request under review / testing"
create_label "workflow::reopened"     "#F0AD4E" "Failed verification or reopened"
create_label "workflow::verification" "#17A2B8" "Merged, awaiting release / staging verification"
create_label "workflow::blocked"      "#D9534F" "Blocked by an external dependency"

echo "=== Provisioning Work Type Labels ==="
create_label "type::defect"           "#DC3545" "Bugs and system errors"
create_label "type::feature"          "#28A745" "New features and enhancements"
create_label "type::maintenance"      "#6C757D" "Refactoring, CI/CD, and tech debt"
create_label "type::docs"             "#00A389" "Documentation and specifications"

echo "=== Provisioning Priority Labels ==="
create_label "priority::P1"           "#B60205" "P1 - Critical / Blocker"
create_label "priority::P2"           "#E99695" "P2 - High Priority"
create_label "priority::P3"           "#FEEFB3" "P3 - Normal Priority"
create_label "priority::P4"           "#E6E6E6" "P4 - Low Priority"

echo "=== Label provisioning complete! ==="
```

---

## 5. GitLab Quick Actions Cheat Sheet

Developers and agents can apply these states directly from issue descriptions, MR descriptions, or comments using GitLab quick actions:

```markdown
/label ~"workflow::in progress" ~"type::feature" ~"priority::P3"
/estimate 4h
/assign @username
```

To indicate a blocked item:
```markdown
/label ~"workflow::blocked"
```

To transition to code review:
```markdown
/label ~"workflow::in review"
```
*(Because scoped labels are mutually exclusive, adding `~"workflow::in review"` automatically removes `~"workflow::in progress"`).*
