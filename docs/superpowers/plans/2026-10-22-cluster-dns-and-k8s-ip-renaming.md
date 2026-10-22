# ClusterDNS Automatic Application and K8S_NETWORK_IP Renaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `MACHINE_IP` to `K8S_NETWORK_IP` (with backward compatibility) and enable scoped `ClusterDNS` by default in `bin/cluster/create_cluster.sh`.

**Architecture:** Update `create_cluster.sh` CLI options, facts parsing, and environment variables to prioritize `K8S_NETWORK_IP` while maintaining full compatibility with `MACHINE_IP` and `--ip`. Enable `ClusterDNS` by default (targeting `.gdc.local` and `.internal.gdc.local` without hijacking `upstreamNameservers`), honoring explicit `false` from facts and `--no-cluster-dns` flag. Verify with unit tests in `test/test_cluster_turnup.py` and `test/test_cli_help_consistency.py`.

**Tech Stack:** Bash, Linux, Kubernetes, Anthos Bare Metal, Python 3.12 (unittest), YAML.

---

### Task 1: Update CLI Parsing, Environment, and Variable Aliasing in `create_cluster.sh`

**Files:**
- Modify: `bin/cluster/create_cluster.sh`
- Test: `test/test_cluster_turnup.py`

- [ ] **Step 1: Write unit tests in `test/test_cluster_turnup.py` verifying `--k8s-ip` and `K8S_NETWORK_IP`**

Add tests to `test/test_cluster_turnup.py`:
- `test_k8s_network_ip_cli_parameter`: passing `--k8s-ip 192.168.10.20` populates both `K8S_NETWORK_IP` and `MACHINE_IP`.
- `test_k8s_network_ip_env_variable`: setting `K8S_NETWORK_IP="192.168.10.21"` populates both variables.
- `test_machine_ip_backward_compatibility`: setting legacy `MACHINE_IP="192.168.10.22"` or `--ip 192.168.10.22` continues to work.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_cluster_turnup.py -k k8s_network_ip`
Expected: FAIL (option `--k8s-ip` unknown or not populated).

- [ ] **Step 3: Update `bin/cluster/create_cluster.sh` with `K8S_NETWORK_IP` support**

In `bin/cluster/create_cluster.sh`:
1. Environment defaults:
   ```bash
   ENV_K8S_NETWORK_IP="${K8S_NETWORK_IP:-${ENV_K8S_NETWORK_IP:-${MACHINE_IP:-${ENV_MACHINE_IP:-}}}}"
   ```
2. CLI variables:
   ```bash
   CLI_K8S_NETWORK_IP=""
   CLI_MACHINE_IP=""
   ```
3. Usage text:
   Document `--k8s-ip <IP>` as primary, `--ip <IP>` as backward-compatible alias.
4. CLI parser:
   ```bash
   --k8s-ip)
       CLI_K8S_NETWORK_IP="$2"
       shift 2
       ;;
   --ip)
       CLI_MACHINE_IP="$2"
       shift 2
       ;;
   ```
5. Facts resolution:
   ```bash
   FACT_K8S_NETWORK_IP=""
   if [[ -n "${FACT_IP_CIDR:-}" ]]; then
       FACT_K8S_NETWORK_IP="${FACT_IP_CIDR%%/*}"
   fi
   ```
6. Resolution hierarchy & exports:
   ```bash
   K8S_NETWORK_IP="${CLI_K8S_NETWORK_IP:-${CLI_MACHINE_IP:-${ENV_K8S_NETWORK_IP:-${FACT_K8S_NETWORK_IP:-}}}}"
   export K8S_NETWORK_IP
   export MACHINE_IP="${K8S_NETWORK_IP}"
   ```
7. Missing check & banner:
   ```bash
   [[ -z "${K8S_NETWORK_IP}" ]] && MISSING_VARS+=("K8S_NETWORK_IP (or --k8s-ip / --ip / MACHINE_IP)")
   ```
   Update status banner:
   ```bash
   printf "  %-35s %s\n" "K8s Network IP:" "${K8S_NETWORK_IP}"
   ```
8. Control plane node binding:
   ```yaml
   controlPlane:
     nodePoolSpec:
       nodes:
         - address: ${K8S_NETWORK_IP}
   ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest test/test_cluster_turnup.py -k k8s_network_ip`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add bin/cluster/create_cluster.sh test/test_cluster_turnup.py
git commit -m "feat(cluster): adopt K8S_NETWORK_IP with backward-compatible MACHINE_IP aliases"
```

---

### Task 2: Implement Scoped Automatic `ClusterDNS` in `create_cluster.sh`

**Files:**
- Modify: `bin/cluster/create_cluster.sh`
- Test: `test/test_cluster_turnup.py`

- [ ] **Step 1: Write unit tests in `test/test_cluster_turnup.py` for default and scoped `ClusterDNS`**

Add tests:
- `test_cluster_dns_default_enabled`: when neither CLI nor facts specify `configure_cluster_dns`, it evaluates to `true`.
- `test_cluster_dns_facts_disabled`: when `.cluster.networking.configure_cluster_dns: false` is in facts, it evaluates to `false`.
- `test_cluster_dns_cli_flags`: `--no-cluster-dns` disables it; `--cluster-dns` enables it.
- `test_cluster_dns_manifest_scoped`: verifies generated `cluster-dns.yaml` has `gdc.local` and `internal.gdc.local` with `${K8S_NETWORK_IP}`, and does **not** contain `upstreamNameservers`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test/test_cluster_turnup.py -k cluster_dns`
Expected: FAIL (default is currently false; manifest still has `upstreamNameservers`).

- [ ] **Step 3: Update `bin/cluster/create_cluster.sh` for scoped ClusterDNS**

1. Defaults & options:
   ```bash
   ENV_CONFIGURE_CLUSTER_DNS="${CONFIGURE_CLUSTER_DNS:-}"
   CLI_CONFIGURE_CLUSTER_DNS=""
   ```
2. Parser:
   ```bash
   --cluster-dns|--configure-cluster-dns)
       CLI_CONFIGURE_CLUSTER_DNS="true"
       shift
       ;;
   --no-cluster-dns|--disable-cluster-dns)
       CLI_CONFIGURE_CLUSTER_DNS="false"
       shift
       ;;
   ```
3. Precedence resolution:
   ```bash
   CONFIGURE_CLUSTER_DNS="${CLI_CONFIGURE_CLUSTER_DNS:-${ENV_CONFIGURE_CLUSTER_DNS:-${FACT_CONFIGURE_CLUSTER_DNS:-true}}}"
   if [[ "${CONFIGURE_CLUSTER_DNS}" != "false" ]]; then
       CONFIGURE_CLUSTER_DNS="true"
   else
       CONFIGURE_CLUSTER_DNS="false"
   fi
   ```
4. Scoped manifest generation and CRD wait:
   ```bash
   # 5d. Configure ClusterDNS for local Nexus / GDC domain resolution
   if [[ "${CONFIGURE_CLUSTER_DNS}" == "true" ]]; then
       echo "[-] Configuring default ClusterDNS for local GDC domains (-> ${K8S_NETWORK_IP})..."
       CLUSTER_DNS_FILE="${CLUSTER_CONFIG_DIR}/cluster-dns.yaml"
       cat <<EOF >"${CLUSTER_DNS_FILE}"
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
   EOF
       echo "[-] Waiting for ClusterDNS CRD to be established..."
       crd_found=false
       for _ in {1..30}; do
           if sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl get crd clusterdnses.networking.gke.io &>/dev/null; then
               crd_found=true
               break
           fi
           sleep 2
       done

       if [[ "${crd_found}" == "true" ]]; then
           if sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f "${CLUSTER_DNS_FILE}"; then
               echo "[OK] ClusterDNS 'default' configured with local GDC domains (-> ${K8S_NETWORK_IP})."
           else
               echo "[!] Warning: Failed to apply ClusterDNS manifest."
           fi
       else
           echo "[!] Warning: Timed out waiting for clusterdnses.networking.gke.io CRD. Skipping ClusterDNS application."
       fi
   else
       echo "[-] Configure ClusterDNS disabled. Skipping ClusterDNS configuration."
   fi
   ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest test/test_cluster_turnup.py -k cluster_dns`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add bin/cluster/create_cluster.sh test/test_cluster_turnup.py
git commit -m "feat(cluster): enable scoped ClusterDNS by default with CRD readiness check"
```

---

### Task 3: Regression Suite, Help Consistency & End-to-End Validation

**Files:**
- Modify: `test/test_cli_help_consistency.py`
- Test: entire test suite

- [ ] **Step 1: Run CLI help consistency test and verify new flags appear**

Run: `python3 -m unittest test/test_cli_help_consistency.py`
Ensure `--k8s-ip`, `--cluster-dns`, and `--no-cluster-dns` are documented and `--ip` remains tested.

- [ ] **Step 2: Run full turnup test suite**

Run: `python3 -m unittest test/test_cluster_turnup.py`
Expected: All tests pass.

- [ ] **Step 3: Run dry-run simulation of create_cluster.sh**

Run: `bin/cluster/create_cluster.sh --dry-run -y --name test-cluster --project test-proj --k8s-ip 192.168.1.10 --vip 192.168.1.11 --ingress 192.168.1.12 --lb-range 192.168.1.13-192.168.1.20`
Expected: Exits 0 with dry-run output and no unbound variable errors.

- [ ] **Step 4: Commit test updates**

```bash
git add test/test_cli_help_consistency.py test/test_cluster_turnup.py
git commit -m "test(cluster): add comprehensive test coverage for ClusterDNS and K8S_NETWORK_IP"
```
