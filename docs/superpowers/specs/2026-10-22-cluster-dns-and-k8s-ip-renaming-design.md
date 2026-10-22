# ClusterDNS Automatic Application and K8S_NETWORK_IP Renaming Design Spec

- **Author:** Google Distributed Cloud (GDC) Edge Team
- **Date:** 2026-10-22
- **Status:** Approved
- **Scope:** `bin/cluster/create_cluster.sh`, `test/test_cluster_turnup.py`, `test/test_cli_help_consistency.py`

---

## 1. Executive Summary

In Google Distributed Cloud (GDC) bare-metal edge deployments, nodes frequently utilize two distinct network planes:
1. **Management Network** (e.g. BMC/iLO, OS deployment, and out-of-band administration).
2. **Cluster Network** (e.g. a dedicated VLAN where Anthos control plane nodes, VIPs, and workloads reside).

Historically, `bin/cluster/create_cluster.sh` used the ambiguous identifier `MACHINE_IP` to represent the node's control plane address. Furthermore, the `ClusterDNS` resource (which enables in-cluster pods and GitOps reconcilers to resolve local domains such as `nexus.internal.gdc.local` through the host's `dnsmasq` instance) was disabled by default.

This design introduces two coordinated architectural improvements:
1. **Semantic Renaming with Backward Compatibility:** Adopts `K8S_NETWORK_IP` as the primary identifier across CLI arguments, environment variables, and configuration hydration, while maintaining full backward-compatible aliases for `MACHINE_IP` and `--ip`.
2. **Safe Automatic `ClusterDNS` Enablement:** Applies the `ClusterDNS` custom resource by default, strictly scoped to `.gdc.local` and `.internal.gdc.local`, omitting general `upstreamNameservers` to eliminate any risk of disrupting standard external DNS lookups. An explicit `false` setting in facts (`machine-info.json`) or via `--no-cluster-dns` completely disables `ClusterDNS`.

---

## 2. Motivation & Problem Statement

### 2.1. Ambiguity of `MACHINE_IP`
`MACHINE_IP` implies the host machine's base operating system or management interface IP. In practice, `create_cluster.sh` extracts the IP from `.network.cluster_network.ip_cidr` (the Kubernetes cluster network) and binds the Anthos control plane node to it. Renaming this to `K8S_NETWORK_IP` clarifies its specific role as the node's Kubernetes cluster network address.

### 2.2. Workload DNS Resolution Failures
Without `ClusterDNS`, pods and Config Sync reconcilers inside the cluster cannot resolve local edge service hubs (`nexus.internal.gdc.local`, `git.internal.gdc.local`) because Kubernetes CoreDNS only knows how to resolve cluster-internal service names (`*.cluster.local`) and forwards external queries to upstream resolvers. By applying `ClusterDNS` for `gdc.local` and `internal.gdc.local`, lookups for local endpoints are automatically routed to the host's `dnsmasq` daemon listening at `${K8S_NETWORK_IP}:53`.

---

## 3. Detailed Architecture & Design

### 3.1. Variable Hierarchy & Aliasing Contract

The script supports both `K8S_NETWORK_IP` (primary) and `MACHINE_IP` (legacy alias) across all configuration tiers:

```
[CLI Flags]                 [Environment Variables]       [Facts File (machine-info.json)]
--k8s-ip <IP>      ──►      K8S_NETWORK_IP        ──►      .network.cluster_network.ip_cidr
--ip <IP> (legacy) ──►      MACHINE_IP (legacy)   ──►      .network.management_network.ip_cidr (fallback)
```

#### Precedence Order:
1. **CLI Arguments**: `--k8s-ip <IP>` > `--ip <IP>`
2. **Environment Variables**: `K8S_NETWORK_IP` > `MACHINE_IP`
3. **Facts File**: `.network.cluster_network.ip_cidr` > `.network.management_network.ip_cidr`

#### Export & Compatibility:
Both variables are exported into the script environment to ensure backward compatibility with any subshells, hooks, or child scripts:
```bash
export K8S_NETWORK_IP
export MACHINE_IP="${K8S_NETWORK_IP}"
```

### 3.2. Scoped `ClusterDNS` Specification

`ClusterDNS` defaults to `true` unless explicitly disabled. When enabled, it applies:

```yaml
apiVersion: networking.gke.io/v1alpha1
kind: ClusterDNS
metadata:
  name: default
spec:
  domains:
  - name: gdc.local
    nameservers:
    - serverIP: ${K8S_NETWORK_IP}
  - name: internal.gdc.local
    nameservers:
    - serverIP: ${K8S_NETWORK_IP}
```

#### Key Architecture Principles:
- **No Upstream Hijacking:** `spec.upstreamNameservers` is intentionally omitted. CoreDNS continues to handle non-GDC internet/corporate lookups via default upstream resolvers, preventing resolution blackholes.
- **Explicit Disablement:** If `.cluster.networking.configure_cluster_dns: false` or `.cluster.configure_cluster_dns: false` is defined in `machine-info.json`, or if `--no-cluster-dns` / `--disable-cluster-dns` is passed on the CLI, `ClusterDNS` is completely skipped.
- **CRD Establishment Wait Loop:** Before applying the manifest, the script polls for up to 60 seconds (`clusterdnses.networking.gke.io` CRD) to ensure the Anthos Bare Metal operator has registered the CRD. If the CRD is not found within the timeout, a warning is logged and execution proceeds without halting turnup.

---

## 4. CLI Arguments and Options

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--k8s-ip <IP>` | String | Auto-detected from facts | Kubernetes cluster network node IP (primary) |
| `--ip <IP>` | String | Auto-detected from facts | Backward-compatible alias for `--k8s-ip` |
| `--cluster-dns`, `--configure-cluster-dns` | Flag | `true` | Explicitly enable local `ClusterDNS` forwarding (default) |
| `--no-cluster-dns`, `--disable-cluster-dns` | Flag | `false` | Explicitly disable `ClusterDNS` manifest creation |

---

## 5. Verification & Testing Strategy

1. **CLI Flag & Fact Parsing Unit Tests (`test/test_cluster_turnup.py`):**
   - Verify `--k8s-ip` populates `K8S_NETWORK_IP` and `MACHINE_IP`.
   - Verify legacy `--ip` populates both variables identically.
   - Verify `ClusterDNS` defaults to `true` when omitted from facts and CLI.
   - Verify `.cluster.networking.configure_cluster_dns: false` in facts disables `ClusterDNS`.
   - Verify `--no-cluster-dns` flag disables `ClusterDNS`.
2. **Manifest Structure Validation:**
   - Verify the rendered `cluster-dns.yaml` contains `spec.domains` pointing to `gdc.local` and `internal.gdc.local` at `${K8S_NETWORK_IP}`.
   - Verify `upstreamNameservers` is not present in the generated manifest.
3. **CLI Help Consistency (`test/test_cli_help_consistency.py`):**
   - Verify `--help` output reflects `--k8s-ip`, `--ip`, `--cluster-dns`, and `--no-cluster-dns`.
4. **Dry-Run Syntax Verification:**
   - Run `bin/cluster/create_cluster.sh --dry-run` to verify non-destructive simulation under `set -euo pipefail`.
