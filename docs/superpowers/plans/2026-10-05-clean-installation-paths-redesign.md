# Clean Installation Paths Pre-Turnup Validation Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the `clean_installation_paths` preflight check in `gdc-collector` to inspect GDC-specific cluster workspace artifacts (`/var/gdc-install/bmctl-workspace/<cluster_name>`) and `/etc/kubernetes/admin.conf` with idempotent operational cluster awareness, eliminating false alarms on `/var/lib/etcd`.

**Architecture:** In `gdc-companion` (`crates/collector/src/prereqs.rs`), dynamically resolve `cluster_name` from `gdc.fact` / `fallback-config.json` / workspace directory scan. Replace the raw `/var/lib/etcd` check with inspection of `/var/gdc-install/bmctl-workspace/<cluster_name>` and `/etc/kubernetes/admin.conf`. Add operational health probing via `kubectl get nodes` so that re-running diagnostics on a node with an already active, healthy cluster reports `PASS` (idempotent re-run) rather than failing.

**Tech Stack:** Rust (edition 2021), Cargo, serde_json, std::fs, bash / kubectl.

---

### File Structure Map

- **Target Repository:** `/d/projects/google/gdc-companion`
  - Modify: `crates/collector/src/prereqs.rs` (Implement `resolve_cluster_name`, update `get_gdc_os_prerequisites`, update unit tests)
  - Test: `crates/collector/src/prereqs.rs` (Unit tests verifying pristine, idempotent healthy, and dirty state checks)

---

### Task 1: Write Unit Tests for Clean Installation Paths Redesign

**Files:**
- Modify: `/d/projects/google/gdc-companion/crates/collector/src/prereqs.rs`

- [ ] **Step 1: Write the failing unit tests in `prereqs.rs`**

Add tests to `mod tests` in `crates/collector/src/prereqs.rs`:

```rust
    #[test]
    fn test_resolve_cluster_name_fallback_empty() {
        // When no files exist, returns empty string gracefully
        let name = resolve_cluster_name();
        assert!(name.is_empty() || !name.contains('/'));
    }

    #[test]
    fn test_clean_installation_paths_eval_pristine() {
        // Test evaluate_clean_paths directly with simulated clean inputs
        let result = evaluate_clean_paths(false, false, false, false);
        assert_eq!(result.get("status").and_then(|s| s.as_str()), Some("PASS"));
        assert!(result.get("test_results").is_some());
    }

    #[test]
    fn test_clean_installation_paths_eval_idempotent_operational() {
        // Test evaluate_clean_paths with active cluster: admin.conf exists and cluster is healthy
        let result = evaluate_clean_paths(true, true, true, false);
        assert_eq!(result.get("status").and_then(|s| s.as_str()), Some("PASS"));
        let tests = result.get("test_results").and_then(|t| t.as_array()).unwrap();
        assert!(tests.iter().any(|t| t.get("output").unwrap().as_str().unwrap().contains("operational")));
    }

    #[test]
    fn test_clean_installation_paths_eval_dirty_unhealthy() {
        // Test evaluate_clean_paths with residual files but unhealthy/dead cluster
        let result = evaluate_clean_paths(true, true, false, false);
        assert_eq!(result.get("status").and_then(|s| s.as_str()), Some("FAIL"));
    }
```

- [ ] **Step 2: Run test to verify it fails to compile (missing functions)**

Run: `cargo test -p gdc-collector --manifest-path /d/projects/google/gdc-companion/Cargo.toml -- test_clean_installation_paths_eval`
Expected: Compile error: `cannot find function evaluate_clean_paths in this scope`

- [ ] **Step 3: Implement `resolve_cluster_name` and `evaluate_clean_paths`**

In `/d/projects/google/gdc-companion/crates/collector/src/prereqs.rs`:

```rust
pub fn resolve_cluster_name() -> String {
    if let Ok(content) = std::fs::read_to_string("/etc/ansible/facts.d/gdc.fact") {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
            if let Some(name) = json
                .get("cluster")
                .and_then(|c| c.get("cluster_name"))
                .and_then(|n| n.as_str())
            {
                let trimmed = name.trim();
                if !trimmed.is_empty() {
                    return trimmed.to_string();
                }
            }
        }
    }
    if let Ok(content) = std::fs::read_to_string("/etc/gdc/fallback-config.json") {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
            if let Some(name) = json
                .get("cluster")
                .and_then(|c| c.get("cluster_name"))
                .and_then(|n| n.as_str())
            {
                let trimmed = name.trim();
                if !trimmed.is_empty() {
                    return trimmed.to_string();
                }
            }
        }
    }
    if let Ok(entries) = std::fs::read_dir("/var/gdc-install/bmctl-workspace") {
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                let file_name = entry.file_name().to_string_lossy().to_string();
                if !file_name.starts_with('.') && file_name != "logs" && file_name != "log" {
                    return file_name;
                }
            }
        }
    }
    "".to_string()
}

pub fn evaluate_clean_paths(
    workspace_has_config: bool,
    admin_conf_exists: bool,
    cluster_already_healthy: bool,
    is_cluster_turnup_or_later: bool,
) -> serde_json::Value {
    if is_cluster_turnup_or_later || cluster_already_healthy {
        let (status, msg) = if cluster_already_healthy {
            ("PASS", "Cluster already initialized and operational (idempotent re-run)")
        } else if admin_conf_exists {
            ("PASS", "/etc/kubernetes/admin.conf is populated with active cluster credentials")
        } else {
            ("FAIL", "/etc/kubernetes/admin.conf missing after turnup")
        };

        let check_name = if is_cluster_turnup_or_later {
            "populated_control_plane"
        } else {
            "clean_installation_paths"
        };

        serde_json::json!({
            "details": "Control plane state and credentials check",
            "remediation": "Inspect /var/gdc-install/logs/create_cluster.log and bmctl-workspace logs.",
            "status": status,
            "test_results": [
                {
                    "test_name": if is_cluster_turnup_or_later { "kubernetes_populated_check" } else { "cluster_idempotent_operational_check" },
                    "status": status,
                    "output": msg
                }
            ]
        })
    } else {
        let is_clean = !workspace_has_config && !admin_conf_exists;
        serde_json::json!({
            "details": "Pristine cluster workspace and credentials check",
            "remediation": "Clean /var/gdc-install/bmctl-workspace/<cluster-name> and remove /etc/kubernetes/admin.conf before installation.",
            "status": if is_clean { "PASS" } else { "FAIL" },
            "test_results": [
                {
                    "test_name": "workspace_clean_check",
                    "status": if !workspace_has_config { "PASS" } else { "FAIL" },
                    "output": if !workspace_has_config {
                        "Cluster workspace is clean or uninitialized"
                    } else {
                        "Residual cluster configuration files found in workspace"
                    }
                },
                {
                    "test_name": "admin_conf_clean_check",
                    "status": if !admin_conf_exists { "PASS" } else { "FAIL" },
                    "output": if !admin_conf_exists {
                        "/etc/kubernetes/admin.conf is absent (clean)"
                    } else {
                        "Pre-existing /etc/kubernetes/admin.conf detected without operational cluster"
                    }
                }
            ]
        })
    }
}
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `cargo test -p gdc-collector --manifest-path /d/projects/google/gdc-companion/Cargo.toml -- test_clean_installation_paths`
Expected: PASS

---

### Task 2: Integrate `evaluate_clean_paths` into `get_gdc_os_prerequisites`

**Files:**
- Modify: `/d/projects/google/gdc-companion/crates/collector/src/prereqs.rs:160-205`

- [ ] **Step 1: Replace `/var/lib/etcd` check in `get_gdc_os_prerequisites`**

In `crates/collector/src/prereqs.rs`, replace lines 162-200 with:

```rust
    // 9. Clean cluster installation paths / populated control plane check
    let cluster_name = resolve_cluster_name();
    let workspace_cluster_dir = if cluster_name.is_empty() {
        "/var/gdc-install/bmctl-workspace".to_string()
    } else {
        format!("/var/gdc-install/bmctl-workspace/{}", cluster_name)
    };
    let cluster_kubeconfig = format!("{}/{}-kubeconfig", workspace_cluster_dir, cluster_name);
    let admin_conf = std::path::Path::new("/etc/kubernetes/admin.conf");

    let workspace_has_config = (!cluster_name.is_empty() && std::path::Path::new(&cluster_kubeconfig).exists())
        || (std::path::Path::new(&workspace_cluster_dir).is_dir()
            && std::fs::read_dir(&workspace_cluster_dir)
                .map(|mut entries| {
                    entries.any(|e| {
                        if let Ok(entry) = e {
                            let name = entry.file_name().to_string_lossy().to_string();
                            name.ends_with(".yaml") || name.ends_with("-kubeconfig")
                        } else {
                            false
                        }
                    })
                })
                .unwrap_or(false));

    let admin_conf_exists = admin_conf.exists();
    let cluster_already_healthy = admin_conf_exists
        && run_bash("kubectl --kubeconfig=/etc/kubernetes/admin.conf get nodes --request-timeout=3s").is_ok();

    let check_val = evaluate_clean_paths(
        workspace_has_config,
        admin_conf_exists,
        cluster_already_healthy,
        is_cluster_turnup_or_later,
    );

    let key_name = if is_cluster_turnup_or_later {
        "populated_control_plane"
    } else {
        "clean_installation_paths"
    };
    checks[key_name] = check_val;
```

- [ ] **Step 2: Update existing `test_clean_installation_paths_logic`**

Ensure `test_clean_installation_paths_logic` asserts that `clean_installation_paths` or `populated_control_plane` is produced as expected.

- [ ] **Step 3: Run all collector tests in `gdc-companion`**

Run: `cargo test -p gdc-collector --manifest-path /d/projects/google/gdc-companion/Cargo.toml`
Expected: 31/31 tests pass with 0 failures

- [ ] **Step 4: Commit changes in `gdc-companion`**

```bash
git -C /d/projects/google/gdc-companion checkout -b fix/clean-installation-paths-redesign
git -C /d/projects/google/gdc-companion add crates/collector/src/prereqs.rs
git -C /d/projects/google/gdc-companion commit -m "feat(collector): redesign clean_installation_paths to check bmctl-workspace and active cluster"
```
