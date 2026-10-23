# GDC Specification: Kube-Bench Machine Report Schema & Collector Integration

**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Specification File:** `docs/specs/21-kube-bench-collector-and-report-schema.md`  
**Target Repository:** `gdc-disk-provisioner` & `gdc-collector`  
**Related Specifications:** `docs/specs/20-cis-security-bundle-and-hardening-harness.md`, `docs/report-schema.json`, `docs/BINARIES.md`  

---

## 1. Executive Summary & Architectural Decisions

### 1.1 Problem Statement
In Google Distributed Cloud (GDC) bare-metal environments, security auditing spans two distinct lifecycle layers:
1. **Operating System Layer (Host):** Evaluated during Stage 4 (`LINUX_READY`) via the CIS Linux Build Kit and CIS-CAT Assessor.
2. **Kubernetes Control Plane & Worker Layer (Cluster):** Evaluated during Stage 7 (`POST_CLUSTER`) via Aqua Security `kube-bench`.

To surface compliance metrics to operators, the GDC Companion dashboard, and external compliance auditors, `kube-bench` test outputs must be:
- Ingested into the standardized machine report (`report-schema.json`).
- Harvested by `gdc-collector` into a dedicated diagnostic archive location (`logs/cis/kube/`).

### 1.2 Architectural Decision: Report Schema Hierarchy
**Decision:** The machine report will structure CIS compliance as a **unified, two-tiered object** under the `"cis_benchmarks"` property:

```json
"cis_benchmarks": {
  "host_os": {
    "execution_status": "COMPLETED",
    "timestamp": "2026-10-21T18:00:00Z",
    "profiles": {
      "level_1_server": { "score_percentage": 92.4, ... },
      "level_2_server": { "score_percentage": 88.1, ... }
    }
  },
  "kubernetes": {
    "execution_status": "COMPLETED",
    "timestamp": "2026-10-21T18:35:00Z",
    "benchmark_version": "2.0",
    "summary": {
      "total_pass": 84,
      "total_fail": 3,
      "total_warn": 8,
      "total_info": 2
    },
    "report_path": "/opt/cis-benchmark/reports/kube-bench.json"
  }
}
```

#### Why a Sub-Object Structure is Superior:
1. **Single Pane of Glass:** Security auditors query one consolidated root (`cis_benchmarks`) for all technical security controls across the appliance rather than navigating disjoint top-level fields.
2. **Lifecycle Decoupling:** `cis_benchmarks.host_os` is populated during Stage 4 (`LINUX_READY`). At that stage, `cis_benchmarks.kubernetes` is initialized as `"PENDING"`. When Stage 7 (`POST_CLUSTER`) completes, `cis_benchmarks.kubernetes` transitions to `"COMPLETED"`.
3. **Semantic Disambiguation:** Clearly separates the CIS Ubuntu 24.04 LTS Benchmark from the CIS Kubernetes Benchmark 2.0 while maintaining schema cleanliness.

---

## 2. On-Host Execution & File Layout

### 2.1 File System Paths
| Component | Host Location | Description |
| :--- | :--- | :--- |
| **Executable Binary** | `/usr/local/bin/kube-bench` | Aqua Security CLI (Permissions `0755`, owned by `root:root`). |
| **Config Directory** | `/etc/kube-bench/cfg/` | Benchmark definitions, controls, and test YAMLs (specifically `cfg/cis-1.24/` or benchmark 2.0 mapping). |
| **Output JSON** | `/var/gdc-install/logs/cis/kube/kube-bench.json` | Machine-readable full test output. |
| **Output Plaintext** | `/var/gdc-install/logs/cis/kube/kube-bench.txt` | Human-readable test output with remediation instructions. |
| **Persistent Archive** | `/opt/cis-benchmark/reports/kube-bench.json` | Long-term copy preserved outside log rotation directories. |

### 2.2 Execution Command (Stage 7: `POST_CLUSTER`)
During Stage 7 (`POST_CLUSTER`), immediately following node readiness, CoreDNS verification, and ConfigSync initialization, the provisioner executes:

```bash
# 1. Ensure target directory exists
mkdir -p /var/gdc-install/logs/cis/kube /opt/cis-benchmark/reports

# 2. Execute structured JSON scan
/usr/local/bin/kube-bench run \
  --targets master,node \
  --benchmark 2.0 \
  --config-dir /etc/kube-bench/cfg \
  --include-test-output \
  --outputfile /var/gdc-install/logs/cis/kube/kube-bench.json \
  --json

# 3. Execute human-readable plaintext scan for operator diagnostics
/usr/local/bin/kube-bench run \
  --targets master,node \
  --benchmark 2.0 \
  --config-dir /etc/kube-bench/cfg \
  --include-test-output > /var/gdc-install/logs/cis/kube/kube-bench.txt 2>&1 || true

# 4. Copy persistent report for audit archives
cp -p /var/gdc-install/logs/cis/kube/kube-bench.json /opt/cis-benchmark/reports/kube-bench.json
```

---

## 3. `gdc-collector` Bundle Ingestion Specification

### 3.1 Target Bundle Directory Mapping
`gdc-collector` packages diagnostic files into a compressed tarball (`gdc-diagnostics-*.tar.gz`) for transmission to the GDC Companion API.

The collector must ingest `/var/gdc-install/logs/cis/` into a standardized directory layout inside the archive root:

```
gdc-diagnostics-<boot_id>-<timestamp>/
└── logs/
    └── cis/
        ├── host/                       # Stage 4: CIS-CAT Assessor Logs & Reports
        │   ├── level-1-server/
        │   │   ├── cis-benchmark-level_1_server-summary.txt
        │   │   └── cis-benchmark-level_1_server-console.log
        │   └── level-2-server/
        │       ├── cis-benchmark-level_2_server-summary.txt
        │       └── cis-benchmark-level_2_server-console.log
        └── kube/                       # Stage 7: Kube-Bench Logs & Reports
            ├── kube-bench.json         # Raw structured test output
            └── kube-bench.txt          # Formatted console output with remediations
```

### 3.2 Collector Ingestion Rules
1. **Discovery Rule:** `gdc-collector` must scan `/var/gdc-install/logs/cis/kube/` for `kube-bench.json` and `kube-bench.txt`.
2. **Path Sanitization:** When archiving, the absolute path `/var/gdc-install/logs/cis/kube/` is stripped and placed under `logs/cis/kube/` in the bundle tarball.
3. **Size Safeguards:** Raw `kube-bench.json` is typically 50–150 KB. The collector enforces a max individual file threshold of `10MB` for any file in `logs/cis/kube/` to prevent log bloat.
4. **Failure Tolerance:** If `kube-bench.json` does not exist (e.g. collector run before Stage 7 completes), `logs/cis/kube/` is omitted without failing the overall collection process.

---

## 4. Machine Report Schema Specification (`report-schema.json`)

### 4.1 Schema Definition: `cis_kubernetes_benchmark_evidence`
In `docs/report-schema.json`, under `properties`:

```json
"cis_kubernetes_benchmark_evidence": {
  "type": "object",
  "description": "Results and summary metrics from the CIS Kubernetes benchmark scan (kube-bench).",
  "required": [
    "execution_status",
    "timestamp",
    "benchmark_version",
    "summary"
  ],
  "properties": {
    "execution_status": {
      "type": "string",
      "enum": [
        "PENDING",
        "IN_PROGRESS",
        "COMPLETED",
        "FAILED",
        "SKIPPED"
      ]
    },
    "timestamp": {
      "type": "string",
      "format": "date-time"
    },
    "benchmark_version": {
      "type": "string",
      "example": "2.0"
    },
    "summary": {
      "type": "object",
      "required": [
        "total_pass",
        "total_fail",
        "total_warn",
        "total_info"
      ],
      "properties": {
        "total_pass": {
          "type": "integer",
          "minimum": 0
        },
        "total_fail": {
          "type": "integer",
          "minimum": 0
        },
        "total_warn": {
          "type": "integer",
          "minimum": 0
        },
        "total_info": {
          "type": "integer",
          "minimum": 0
        }
      }
    },
    "report_path": {
      "type": "string",
      "example": "/opt/cis-benchmark/reports/kube-bench.json"
    }
  }
}
```

### 4.2 Machine Stages Progress Integration
In `docs/report-schema.json`, under `machine_stages_progress`:

1. **Stage 4 (`LINUX_READY`):**
   ```json
   "evidence": {
     "type": "object",
     "properties": {
       "cis_benchmarks": {
         "type": "object",
         "properties": {
           "host_os": { "$ref": "#/properties/cis_benchmarks_evidence" },
           "kubernetes": { "$ref": "#/properties/cis_kubernetes_benchmark_evidence" }
         }
       }
     }
   }
   ```
   *(Note: At Stage 4, `cis_benchmarks.kubernetes.execution_status` is `"PENDING"`).*

2. **Stage 7 (`POST_VALIDATION` / `POST_CLUSTER`):**
   ```json
   "evidence": {
     "type": "object",
     "properties": {
       "kubernetes_nodes_ready": { "type": "boolean" },
       "coredns_operational": { "type": "boolean" },
       "storage_classes_present": { "type": "boolean" },
       "config_sync": { "type": "object" },
       "cis_benchmarks": {
         "type": "object",
         "properties": {
           "kubernetes": { "$ref": "#/properties/cis_kubernetes_benchmark_evidence" }
         }
       }
     }
   }
   ```

---

## 5. Ansible Implementation Guidance

An implementing agent should execute the following steps:

### 5.1 Parse Kube-Bench Summary
In `src/ansible/roles/post_cluster/tasks/main.yml`, add task:

```yaml
- name: "GDC-CIS-K8S | Ensure Kube-Bench output directory exists"
  ansible.builtin.file:
    path: /var/gdc-install/logs/cis/kube
    state: directory
    owner: root
    group: root
    mode: '0750'

- name: "GDC-CIS-K8S | Execute CIS Kubernetes Benchmark via kube-bench"
  ansible.builtin.command: >-
    /usr/local/bin/kube-bench run
    --targets master,node
    --benchmark 2.0
    --config-dir /etc/kube-bench/cfg
    --include-test-output
    --outputfile /var/gdc-install/logs/cis/kube/kube-bench.json
    --json
  register: kube_bench_run
  failed_when: false
  changed_when: true

- name: "GDC-CIS-K8S | Generate human-readable plaintext report"
  ansible.builtin.shell: >-
    /usr/local/bin/kube-bench run
    --targets master,node
    --benchmark 2.0
    --config-dir /etc/kube-bench/cfg
    --include-test-output > /var/gdc-install/logs/cis/kube/kube-bench.txt 2>&1
  failed_when: false
  changed_when: false

- name: "GDC-CIS-K8S | Copy persistent audit report"
  ansible.builtin.copy:
    src: /var/gdc-install/logs/cis/kube/kube-bench.json
    dest: /opt/cis-benchmark/reports/kube-bench.json
    remote_src: true
    owner: root
    group: root
    mode: '0640'
  ignore_errors: true

- name: "GDC-CIS-K8S | Slurp and parse kube-bench summary facts"
  ansible.builtin.shell: |
    python3 -c '
    import json, sys
    try:
        with open("/var/gdc-install/logs/cis/kube/kube-bench.json") as f:
            data = json.load(f)
        total_pass = sum(c.get("pass", 0) for c in data.get("Controls", []))
        total_fail = sum(c.get("fail", 0) for c in data.get("Controls", []))
        total_warn = sum(c.get("warn", 0) for c in data.get("Controls", []))
        total_info = sum(c.get("info", 0) for c in data.get("Controls", []))
        out = {
            "execution_status": "COMPLETED",
            "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
            "benchmark_version": "2.0",
            "summary": {
                "total_pass": total_pass,
                "total_fail": total_fail,
                "total_warn": total_warn,
                "total_info": total_info
            },
            "report_path": "/opt/cis-benchmark/reports/kube-bench.json"
        }
    except Exception as e:
        out = {
            "execution_status": "FAILED",
            "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
            "benchmark_version": "2.0",
            "error": str(e)
        }
    print(json.dumps(out))
    '
  register: kube_bench_parsed
  changed_when: false

- name: "GDC-EVIDENCE | Update PostCluster Evidence with Kube-Bench Results"
  ansible.builtin.set_fact:
    post_cluster_evidence: >-
      {{
        post_cluster_evidence | combine({
          'cis_benchmarks': {
            'kubernetes': (kube_bench_parsed.stdout | from_json)
          }
        }, recursive=True)
      }}
```

---

## 6. Verification & Acceptance Checklist

To verify this specification is implemented correctly:
- [ ] `/usr/local/bin/kube-bench` is executable and returns version without errors.
- [ ] `/etc/kube-bench/cfg/` contains configuration YAMLs.
- [ ] During Stage 7 (`POST_CLUSTER`), `kube-bench run --targets master,node --benchmark 2.0` completes.
- [ ] `/var/gdc-install/logs/cis/kube/kube-bench.json` is generated with valid JSON.
- [ ] `/var/gdc-install/state/post-validation.json` contains `evidence.cis_benchmarks.kubernetes` matching `cis_kubernetes_benchmark_evidence` schema.
- [ ] Running `gdc-collector --stage post-cluster` produces a `.tar.gz` containing `logs/cis/kube/kube-bench.json` and `logs/cis/kube/kube-bench.txt`.
