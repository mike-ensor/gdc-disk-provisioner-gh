# Specification: GDC Companion Microservice (Rust Stack)

**Spec Identifier:** `GDC-SPEC-007`  
**Status:** MIGRATED (Moved to separate peer repository `gdc-companion`)  
**Author:** GDC Disk Provisioner Architecture Team  

---

> [!NOTE]
> **Migration Notice:** The GDC Companion microservice has been officially migrated to its own dedicated repository (`gdc-companion`) to enforce clean modular decoupling between target OS bootloader ISOs and centralized management gateways. This specification remains here as an archival reference for the REST API contract and DB variable-merge logic required by the bootloader's telemetry reporting hooks.

---

## 1. Executive Summary & Purpose
The GDC Companion (`gdc-companion`) is a high-security, decoupled, database-backed REST microservice designed to coordinate and audit GDC node installations completely offline. 

By utilizing **Rust (Axum + SQLx + Serde)** as the official implementation stack, the service provides compile-time memory safety, ultra-low resource footprint (~15MB RAM idle), and zero runtime crashes. It functions as the secure orchestration bridge between booting nodes (running the custom GDC bootloader ISO) and cluster administrators, managing hardware registration, dynamic variables via a hierarchical deep-merge engine, and live installation logging.

The service is fully containerized inside a minimal `scratch` or distroless image, backed by CloudNativePG (CNPG) on PostgreSQL, and exposed secure-by-default through the Kubernetes Gateway API using Mutual TLS (mTLS).

---

## 2. Decoupled Service Architecture

```text
                  [ GDC COMPANION EDGE BOUNDARY ]
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         ▼                                                       ▼
  [ Port 80 (Public HTTP Route) ]               [ Port 443 (Secure mTLS Route) ]
  • TLS: None                                   • TLS: mTLS (Client Cert Mandated)
  • Endpoints:                                  • Endpoints:
    - `POST /v1/install-logs/public`              - `POST /v1/install-logs/secure`
    - `POST /v1/register` (Hardware / CSR)        - `WS /v1/install-logs/stream`
                                                  - `GET /v1/nodes/variables`
```

> [!NOTE]
> For the node-side client lifecycle, TPM EKCert hardware attestation, Step CA certificate issuance, and complete mTLS connection sequence to the Companion, refer to the consolidated guide in [`docs/TPM_ATTESTATION_AND_MTLS.md`](../TPM_ATTESTATION_AND_MTLS.md).

---

## 3. Relational Database Design & CloudNativePG

The backend database utilizes standard PostgreSQL with CloudNativePG (CNPG) operator control. Physical network parameters, hostnames, and hardware cryptographic IDs are strongly typed in columns, while dynamic custom variables reside in native `JSONB` columns.

### 3.1. Entity-Relationship (ER) Schema

#### 1. `globals` Table
Holds system-wide variables. It contains a single record.
* `id` (integer, Primary Key)
* `variables` (JSONB, system-wide key-value parameters)

#### 2. `fleets` Table
Represents groups of nodes (clusters or data racks).
* `id` (UUID, Primary Key)
* `name` (varchar, Unique)
* `google_org_id` (varchar)
* `variables` (JSONB, fleet-wide configuration parameters)

#### 3. `machines` Table
Represents individual physical servers.
* `id` (UUID, Primary Key)
* `hostname` (varchar, Unique)
* `customer_id` (varchar)
* `google_project_id` (varchar)
* `google_region` (varchar)
* `mac_address` (varchar, Unique, Indexed)
* `uuid` (UUID, Unique, Indexed)
* `cpu_cores` (integer, physical CPU core count)
* `ram_gib` (integer, physical RAM in GiB)
* `disks` (JSONB, representing a list of physical disks: `[{"disk_id": "/dev/sda", "size_gib": 500}, ...]`)
* `vrf_machine_cidr` (varchar)
* `vrf_machine_gateway` (varchar)
* `vrf_machine_dns` (varchar[], defaulting to `{"8.8.8.8", "8.8.4.4"}`)
* `vrf_k8s_cidr` (varchar)
* `vrf_k8s_gateway` (varchar)
* `vrf_k8s_dns` (varchar[], defaulting to `{"8.8.8.8", "8.8.4.4"}`)
* `fleet_id` (UUID, Foreign Key referencing `fleets(id)`)
* `status` (varchar, `"PENDING"`, `"APPROVED"`, or `"INSTALLED"`)
* `variables` (JSONB, node-specific variables overriding fleet/global keys)

---

### 3.2. CloudNativePG (CNPG) Cluster Definition

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: gdc-companion-db
  namespace: gdc-companion
spec:
  instances: 3
  imageName: ghcr.io/cloudnativepg/postgresql:16
  primaryUpdateStrategy: unsupervised
  
  storage:
    size: 20Gi
    storageClass: standard
    
  bootstrap:
    initdb:
      database: companion_db
      owner: companion_admin
      secret:
        name: companion-db-credentials
```

---

## 4. Hierarchical Recursive Variable Overrides

The variable engine resolves variables in the following precedence order:
$$\text{Global} \longrightarrow \text{Fleet} \longrightarrow \text{Machine}$$

Top-level structures are augmented, while duplicate keys are recursively overridden down to nested dictionary leaves. Lists/arrays are completely replaced.

### 4.1. The Merge Engine Implementation (Rust)

```rust
// gdc-companion/src/utils/merge.rs
use serde_json::Value;

pub fn deep_merge(base: &mut Value, override_val: &Value) {
    match (base, override_val) {
        // If both are JSON objects, recursively merge their fields
        (Value::Object(ref mut base_map), Value::Object(override_map)) => {
            for (k, v) in override_map {
                if base_map.contains_key(k) {
                    deep_merge(base_map.get_mut(k).unwrap(), v);
                } else {
                    base_map.insert(k.clone(), v.clone());
                }
            }
        }
        // For lists, arrays, strings, or numbers: the override_val entirely clobbers the base
        (base_val, override_val) => {
            *base_val = override_val.clone();
        }
    }
}
```

---

### 4.2. Automated Rust Unit Tests

```rust
// gdc-companion/src/utils/merge.rs

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

    // Test Case 1: Global only without any overridden values
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

    // Test Case 2: Global + Fleet without any overridden variables
    #[test]
    fn test_global_plus_fleet_no_overrides() {
        let mut base = get_default_global();
        let fleet_overrides = json!({});

        deep_merge(&mut base, &fleet_overrides);

        assert_eq!(base, get_default_global());
    }

    // Test Case 3: Global + Fleet with a NEW variable
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

    // Test Case 4: Global + Fleet with OVERRIDING a variable
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
        assert_eq!(base["vlan"]["priority"], 1); // Preserved
        assert_eq!(base["dns"], json!(["8.8.8.8", "8.8.4.4"])); // Preserved
    }

    // Test Case 5: Global + Fleet + Machine with multi-level overrides & augmentation
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

        assert_eq!(base["ntp"], "ntp.local-node.internal"); // Overrode both
        assert_eq!(base["dns"], json!(["1.1.1.1"])); // Array completely overridden
        assert_eq!(base["monitoring"]["enabled"], false); // Machine level
        assert_eq!(base["monitoring"]["interval_sec"], 30); // Fleet level preserved
        assert_eq!(base["vlan"]["id"], 999); // Machine level
        assert_eq!(base["vlan"]["priority"], 1); // Global level preserved
        assert_eq!(base["fleet_secret"], "fleet-token-123"); // Fleet augmentation preserved
        assert_eq!(base["local_debug"], true); // Machine augmentation added
    }
}
```

---

## 5. Decoupled REST API Contract (Rust + Serde)

We enforce strict separation of concerns: database entity structures are never exposed to the REST interface. Instead, clean **Serde DTOs** define the API serialization interface.

### 5.1. Axum Request/Response DTOs

```rust
// gdc-companion/src/schemas.rs
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Serialize, Deserialize)]
pub struct DiskConfigDTO {
    pub disk_id: String,
    pub size_gib: u64,
}

#[derive(Debug, Deserialize)]
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

#[derive(Debug, Serialize)]
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
    pub variables: Value, // Combined dynamic parameters derived via deep_merge
}
```

---

## 6. Kubernetes Gateway API Deployment Layout

We employ the Kubernetes Gateway API to terminate client certificates at the cluster edge.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: gdc-companion-gateway
  namespace: gdc-companion
spec:
  gatewayClassName: nginx-gateway-fabric
  listeners:
    - name: http-public
      port: 80
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
          
    - name: https-mtls
      port: 443
      protocol: HTTPS
      tls:
        mode: Terminate
        certificateRefs:
          - name: gdc-companion-server-tls
        frontendValidation:
          caCertificateRefs:
            - name: cert-manager-gdc-root-ca
      allowedRoutes:
        namespaces:
          from: Same
```

---

## 7. Operational Guidelines & Safety Procedures

A localized `GEMINI.md` within `gdc-companion/` regulates development quality.

### 7.1. Testing Verification Gate
Before any staged commit is applied or code is pushed to git, standard unit testing MUST run and pass successfully:
```bash
cargo test
```

### 7.2. Docker Container Target Caching
The Dockerfile for the microservice must utilize multi-stage builds. The release binary must compile statically using musl toolchains and be packaged inside an empty `scratch` or minimal `distroless` image to keep container sizes below **20MB** and ensure absolute zero host vulnerability exposure.
