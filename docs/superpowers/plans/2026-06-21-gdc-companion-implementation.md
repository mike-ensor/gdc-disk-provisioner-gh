# GDC Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a secure, fully decoupled Rust-based microservice `gdc-companion` using Axum, SQLx, and Serde that handles hardware registration, dynamic configuration overrides, and log streaming for booting GDC nodes.

**Architecture:** Exposes Port 80 for public endpoints (CSR registration, unauthenticated log streams) and Port 443 for mTLS endpoints (dynamic configuration values and authenticated log streams), backed by PostgreSQL and CloudNativePG (CNPG).

**Tech Stack:** Rust 1.75+, Axum 0.7, Serde 1.0, serde_json, Tokio 1.35, SQLx 0.7 (Postgres).

## Global Constraints
- **Directory Isolation:** The folder `gdc-companion/` must be 100% self-contained and decoupled. Do not import or refer to files under `/src/` of the main project.
- **Strict Verification Gate:** `cargo test` must be run and pass successfully before any code is marked as complete.
- **Zero Raw Credentials:** No raw secrets or database passwords may be stored statically. Secret configuration must go through Kubernetes Env variables.

---

### Task 1: Scaffolding, Isolation, and Documentation Setup

**Files:**
- Create: `gdc-companion/Cargo.toml`
- Create: `gdc-companion/.gitignore`
- Create: `gdc-companion/GEMINI.md`
- Create: `gdc-companion/docs/architecture.md`
- Create: `gdc-companion/docs/principles.md`
- Create: `gdc-companion/docs/testing.md`
- Create: `gdc-companion/docs/installing.md`
- Create: `gdc-companion/docs/integrating.md`
- Create: `gdc-companion/src/lib.rs`
- Create: `gdc-companion/src/main.rs`

**Interfaces:**
- Consumes: None (starting workspace from scratch)
- Produces: Base Cargo workspace ready for Axum compile

- [ ] **Step 1: Write Cargo.toml definition**
  Create `gdc-companion/Cargo.toml`:
  ```toml
  [package]
  name = "gdc-companion"
  version = "0.1.0"
  edition = "2021"

  [dependencies]
  axum = { version = "0.7", features = ["ws"] }
  tokio = { version = "1.35", features = ["full"] }
  serde = { version = "1.0", features = ["derive"] }
  serde_json = "1.0"
  sqlx = { version = "0.7", features = ["runtime-tokio-native-tls", "postgres", "uuid", "chrono"] }
  uuid = { version = "1.6", features = ["v4", "serde"] }
  chrono = { version = "0.4", features = ["serde"] }
  tower-http = { version = "0.5", features = ["trace"] }
  tracing = "0.1"
  tracing-subscriber = "0.3"

  [dev-dependencies]
  tokio-test = "0.4"
  ```

- [ ] **Step 2: Create .gitignore file**
  Create `gdc-companion/.gitignore`:
  ```ignore
  /target/
  **/*.rs.bk
  Cargo.lock
  .env
  ```

- [ ] **Step 3: Create governance manuals & architectural documentation**
  Create `gdc-companion/GEMINI.md`:
  ```markdown
  # GEMINI: GDC Companion Manual

  ## 1. Architectural Guardrails
  * **Strict Decoupled Isolation:** Communication with GDC booting nodes occurs strictly over Port 80 (HTTP) or Port 443 (mTLS) REST interfaces.
  * **Zero Exception Crashes:** All handlers must return `Result<T, AppError>` to guarantee compile-time error propagation instead of panic-runtime dropouts.

  ## 2. Test Verification Gate
  * Run `cargo test` and verify that all unit and integration tests pass green before committing or pushing changes.
  ```

  Create `gdc-companion/docs/architecture.md`:
  ```markdown
  # Architectural Overview
  Describes GDC Companion microservice routing and database topology. 
  It utilizes Axum for asynchronous HTTP/WS streams and SQLx to interact with PostgreSQL.
  ```

  Create `gdc-companion/docs/principles.md`:
  ```markdown
  # Coding Principles
  All codebase contributions must adhere to compile-time memory safety, strict Serde DTO isolation, and explicit error handling.
  ```

  Create `gdc-companion/docs/testing.md`:
  ```markdown
  # Testing Guidelines
  Define unit tests under conditional config modules `#[cfg(test)]`. Integration testing lives in `/tests`.
  ```

  Create `gdc-companion/docs/installing.md`:
  ```markdown
  # Installation Guide
  Deploys onto GDC clusters using the CloudNativePG (CNPG) operator and standard Gateway API routing.
  ```

  Create `gdc-companion/docs/integrating.md`:
  ```markdown
  # Integration Matrix
  Detailed contracts representing early-commands Subiquity webhooks, registration CSR endpoints, and mTLS variable retrieves.
  ```

- [ ] **Step 4: Create base source files**
  Create `gdc-companion/src/lib.rs` (empty file).
  Create `gdc-companion/src/main.rs`:
  ```rust
  fn main() {
      println!("Hello from GDC Companion!");
  }
  ```

- [ ] **Step 5: Run compilation test to verify setup**
  Run: `cargo check --manifest-path gdc-companion/Cargo.toml`
  Expected Output: Successful compilation check without errors.

- [ ] **Step 6: Commit workspace scaffolding**
  Run:
  ```bash
  git add gdc-companion/
  git commit -m "chore: scaffold gdc-companion workspace and manuals"
  ```

---

### Task 2: Recursive Deep Merge Engine & Automated Unit Tests

**Files:**
- Create: `gdc-companion/src/utils/mod.rs`
- Create: `gdc-companion/src/utils/merge.rs`
- Modify: `gdc-companion/src/lib.rs`

**Interfaces:**
- Consumes: `serde_json::Value` (Standard crate type)
- Produces: `pub fn deep_merge(base: &mut Value, override_val: &Value)` inside library utils mod.

- [ ] **Step 1: Implement the recursive merge engine with conditional tests**
  Create `gdc-companion/src/utils/merge.rs`:
  ```rust
  use serde_json::Value;

  pub fn deep_merge(base: &mut Value, override_val: &Value) {
      match (base, override_val) {
          (Value::Object(ref mut base_map), Value::Object(override_map)) => {
              for (k, v) in override_map {
                  if base_map.contains_key(k) {
                      deep_merge(base_map.get_mut(k).unwrap(), v);
                  } else {
                      base_map.insert(k.clone(), v.clone());
                  }
              }
          }
          (base_val, override_val) => {
              *base_val = override_val.clone();
          }
      }
  }

  #[cfg(test)]
  mod tests {
      use super::*;
      use serde_json::json;

      fn get_default_global() -> Value {
          json!({
              "vlan": {
                  "id": 100,
                  "priority": 1
              },
              "dns": ["8.8.8.8", "8.8.4.4"],
              "ntp": "time.google.com",
              "monitoring": {
                  "enabled": true,
                  "interval_sec": 60
              }
          })
      }

      #[test]
      fn test_global_only() {
          let mut base = get_default_global();
          let fleet_overrides = json!({});
          let machine_overrides = json!({});

          deep_merge(&mut base, &fleet_overrides);
          deep_merge(&mut base, &machine_overrides);

          assert_eq!(base, get_default_global());
          assert_eq!(base["vlan"]["id"], 100);
          assert_eq!(base["monitoring"]["interval_sec"], 60);
      }

      #[test]
      fn test_global_plus_fleet_no_overrides() {
          let mut base = get_default_global();
          let fleet_overrides = json!({});

          deep_merge(&mut base, &fleet_overrides);

          assert_eq!(base, get_default_global());
      }

      #[test]
      fn test_global_plus_fleet_with_new_variable() {
          let mut base = get_default_global();
          let fleet_overrides = json!({
              "nexus_mirror_url": "https://nexus.fleet.example.com"
          });

          deep_merge(&mut base, &fleet_overrides);

          assert_eq!(base["ntp"], "time.google.com");
          assert_eq!(base["vlan"]["id"], 100);
          assert_eq!(base["nexus_mirror_url"], "https://nexus.fleet.example.com");
      }

      #[test]
      fn test_global_plus_fleet_with_overridden_variable() {
          let mut base = get_default_global();
          let fleet_overrides = json!({
              "ntp": "ntp.fleet.google.internal",
              "vlan": {
                  "id": 200
              }
          });

          deep_merge(&mut base, &fleet_overrides);

          assert_eq!(base["ntp"], "ntp.fleet.google.internal");
          assert_eq!(base["vlan"]["id"], 200);
          assert_eq!(base["vlan"]["priority"], 1);
          assert_eq!(base["dns"], json!(["8.8.8.8", "8.8.4.4"]));
      }

      #[test]
      fn test_machine_level_override_and_augmentation() {
          let mut base = get_default_global();
          let fleet_overrides = json!({
              "ntp": "ntp.fleet.google.internal",
              "monitoring": {
                  "interval_sec": 30
              },
              "fleet_secret": "fleet-token-123"
          });

          let machine_overrides = json!({
              "dns": ["1.1.1.1"],
              "ntp": "ntp.local-node.internal",
              "monitoring": {
                  "enabled": false
              },
              "vlan": {
                  "id": 999
              },
              "local_debug": true
          });

          deep_merge(&mut base, &fleet_overrides);
          deep_merge(&mut base, &machine_overrides);

          assert_eq!(base["ntp"], "ntp.local-node.internal");
          assert_eq!(base["dns"], json!(["1.1.1.1"]));
          assert_eq!(base["monitoring"]["enabled"], false);
          assert_eq!(base["monitoring"]["interval_sec"], 30);
          assert_eq!(base["vlan"]["id"], 999);
          assert_eq!(base["vlan"]["priority"], 1);
          assert_eq!(base["fleet_secret"], "fleet-token-123");
          assert_eq!(base["local_debug"], true);
      }
  }
  ```

- [ ] **Step 2: Create utility mod index**
  Create `gdc-companion/src/utils/mod.rs`:
  ```rust
  pub mod merge;
  ```

- [ ] **Step 3: Register utilities in library root**
  Modify `gdc-companion/src/lib.rs`:
  ```rust
  pub mod utils;
  ```

- [ ] **Step 4: Run test suite to verify tests pass**
  Run: `cargo test --manifest-path gdc-companion/Cargo.toml`
  Expected Output: `test result: ok. 5 passed; 0 failed;`

- [ ] **Step 5: Commit recursive merge logic**
  Run:
  ```bash
  git add gdc-companion/src/lib.rs gdc-companion/src/utils/
  git commit -m "feat: implement recursive JSONB deep merge engine with 5 automated test cases"
  ```

---

### Task 3: REST API DTOs and Serde Schemas

**Files:**
- Create: `gdc-companion/src/schemas.rs`
- Modify: `gdc-companion/src/lib.rs`

**Interfaces:**
- Consumes: None
- Produces: `DiskConfigDTO`, `MachineCreateDTO`, and `ResolvedConfigurationDTO` structs.

- [ ] **Step 1: Write Serde schema structs**
  Create `gdc-companion/src/schemas.rs`:
  ```rust
  use serde::{Deserialize, Serialize};
  use serde_json::Value;
  use uuid::Uuid;

  #[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
  pub struct DiskConfigDTO {
      pub disk_id: String,
      pub size_gib: u64,
  }

  #[derive(Debug, Deserialize, Clone)]
  pub struct MachineCreateDTO {
      pub hostname: String,
      pub customer_id: String,
      pub google_project_id: String,
      pub google_region: String,
      pub mac_address: String,
      pub uuid: Uuid,
      pub cpu_cores: u32,
      pub ram_gib: u32,
      pub disks: Vec<DiskConfigDTO>,
      pub vrf_machine_cidr: String,
      pub vrf_machine_gateway: String,
      pub vrf_machine_dns: Option<Vec<String>>,
      pub vrf_k8s_cidr: String,
      pub vrf_k8s_gateway: String,
      pub vrf_k8s_dns: Option<Vec<String>>,
      pub fleet_id: Uuid,
      pub variables: Value,
  }

  #[derive(Debug, Serialize, Clone, PartialEq)]
  pub struct ResolvedConfigurationDTO {
      pub hostname: String,
      pub customer_id: String,
      pub google_project_id: String,
      pub google_region: String,
      pub google_org_id: String,
      pub fleet_name: String,
      pub cpu_cores: u32,
      pub ram_gib: u32,
      pub disks: Vec<DiskConfigDTO>,
      pub vrf_machine_cidr: String,
      pub vrf_machine_gateway: String,
      pub vrf_machine_dns: Vec<String>,
      pub vrf_k8s_cidr: String,
      pub vrf_k8s_gateway: String,
      pub vrf_k8s_dns: Vec<String>,
      pub variables: Value,
  }

  #[cfg(test)]
  mod tests {
      use super::*;
      use serde_json::json;

      #[test]
      fn test_dto_serialization_flow() {
          let dto = ResolvedConfigurationDTO {
              hostname: "gdc-node-03".to_string(),
              customer_id: "cust-908".to_string(),
              google_project_id: "gdc-prod".to_string(),
              google_region: "us-central1".to_string(),
              google_org_id: "12345678".to_string(),
              fleet_name: "rack1".to_string(),
              cpu_cores: 32,
              ram_gib: 128,
              disks: vec![DiskConfigDTO { disk_id: "/dev/sda".to_string(), size_gib: 500 }],
              vrf_machine_cidr: "192.168.9.11/24".to_string(),
              vrf_machine_gateway: "192.168.9.1".to_string(),
              vrf_machine_dns: vec!["8.8.8.8".to_string()],
              vrf_k8s_cidr: "10.0.0.5/24".to_string(),
              vrf_k8s_gateway: "10.0.0.1".to_string(),
              vrf_k8s_dns: vec!["8.8.4.4".to_string()],
              variables: json!({"vlan": 100}),
          };

          let serialized = serde_json::to_string(&dto).unwrap();
          let deserialized: ResolvedConfigurationDTO = serde_json::from_str(&serialized).unwrap();
          assert_eq!(deserialized, dto);
      }
  }
  ```

- [ ] **Step 2: Export schemas in library root**
  Modify `gdc-companion/src/lib.rs`:
  ```rust
  pub mod utils;
  pub mod schemas;
  ```

- [ ] **Step 3: Run cargo test to confirm Serde behavior**
  Run: `cargo test --manifest-path gdc-companion/Cargo.toml`
  Expected Output: `6 passed; 0 failed`

- [ ] **Step 4: Commit DTO definitions**
  Run:
  ```bash
  git add gdc-companion/src/schemas.rs gdc-companion/src/lib.rs
  git commit -m "feat: define strictly typed Pydantic-equivalent Serde schemas & DTOs"
  ```
