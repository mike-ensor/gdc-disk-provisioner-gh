# Specification: Dynamic Cluster Admin RBAC Binding

**Spec Identifier:** `GDC-SPEC-2026-09-27-DYNAMIC-ADMIN-RBAC`  
**Status:** APPROVED  
**Date:** 2026-09-27  
**Author:** GDC Core Platform Engineering  

---

## 1. Executive Summary

During Google Distributed Cloud (GDC) Bare Metal standalone cluster turnup, administrative users must be granted immediate cluster access upon inception. Previously, `bin/cluster/create_cluster.sh` only supported a single administrator email via `ADMIN_USER_EMAIL` (or `--admin-email` / `.cluster.admin_user_email`), creating a ClusterRoleBinding named `gdc-primary-cluster-admins`.

This specification defines the ingestion of a list of admin emails from facts (`.cluster.cluster_admin_emails`) and the automated generation of two distinct Kubernetes `ClusterRoleBinding` resources:
1. `automated-admin-email`: Bound to the single administrator email passed via `--admin-email` or legacy environment variables.
2. `dynamic-installed-cluster-admin-list`: Bound to the full array of administrator emails defined in the machine facts file (`.cluster.cluster_admin_emails`).

---

## 2. Requirements & Constraints

1. **Facts Parsing (`get_json_array`)**:
   - The script must extract the string array at `.cluster.cluster_admin_emails` from `$FACTS_FILE`.
   - The helper must support both `jq` (primary) and `python3` (fallback) when `jq` is unavailable.
   - Whitespace and empty entries must be stripped.
2. **ClusterRoleBinding Generation**:
   - `automated-admin-email`:
     - Applied when `ADMIN_USER_EMAIL` is non-empty.
     - Written to `${CLUSTER_CONFIG_DIR}/cluster-admin-automated.yaml`.
     - Subjects: single `User` matching `${ADMIN_USER_EMAIL}`.
   - `dynamic-installed-cluster-admin-list`:
     - Applied when `CLUSTER_ADMIN_EMAILS` has at least one valid entry.
     - Written to `${CLUSTER_CONFIG_DIR}/cluster-admins-dynamic.yaml`.
     - Subjects: multiple `User` entries, one for each email in `CLUSTER_ADMIN_EMAILS`.
3. **Empty List & Missing Fields**:
   - If `.cluster.cluster_admin_emails` is empty (`[]`) or omitted, skip `dynamic-installed-cluster-admin-list` creation with a clean informational log.
   - If `ADMIN_USER_EMAIL` is omitted, skip `automated-admin-email` creation with a clean informational log.
4. **Offline & Zero-External-Dependency**:
   - Retain complete compatibility with offline GDC nodes without requiring new external CLI tools or internet access.
5. **Dry-Run Telemetry**:
   - When `--dry-run` is passed, display the count and list of discovered admin emails in the header and execution summary without applying resources.

---

## 3. Detailed Architecture & Design

### 3.1. Dual JSON Array Extraction Helper

```bash
get_json_array() {
    local file="$1"
    local jsonpath="$2"
    if [[ ! -f "$file" ]]; then
        return
    fi
    if command -v jq >/dev/null 2>&1; then
        jq -r "${jsonpath} // [] | .[]" "$file" 2>/dev/null || true
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "
import json
try:
    with open('$file') as f:
        data = json.load(f)
    keys = '$jsonpath'.strip('.').split('.')
    val = data
    for k in keys:
        if val is None or not isinstance(val, dict):
            val = None
            break
        val = val.get(k)
    if isinstance(val, list):
        for item in val:
            if item is not None and str(item).strip():
                print(str(item).strip())
except Exception:
    pass
" 2>/dev/null || true
    fi
}
```

### 3.2. Facts Ingestion

```bash
CLUSTER_ADMIN_EMAILS=()

if [[ -n "${FACTS_FILE}" && -f "${FACTS_FILE}" ]]; then
    # ... existing facts ...
    while IFS= read -r email; do
        [[ -n "${email}" ]] && CLUSTER_ADMIN_EMAILS+=("${email}")
    done < <(get_json_array "${FACTS_FILE}" ".cluster.cluster_admin_emails")
fi
```

### 3.3. Post-Creation RBAC Application

#### 3.3.1. `automated-admin-email`
```bash
if [ -n "${ADMIN_USER_EMAIL:-}" ]; then
    echo "[-] ADMIN_USER_EMAIL is defined (${ADMIN_USER_EMAIL}). Creating ClusterRoleBinding 'automated-admin-email'..."
    ADMIN_EMAIL_FILE="${CLUSTER_CONFIG_DIR}/cluster-admin-automated.yaml"
    cat <<EOF >"${ADMIN_EMAIL_FILE}"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: automated-admin-email
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ${ADMIN_USER_EMAIL}
EOF
    sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f "${ADMIN_EMAIL_FILE}"
    echo "[OK] ClusterRoleBinding 'automated-admin-email' for ${ADMIN_USER_EMAIL} created."
else
    echo "[-] ADMIN_USER_EMAIL is not defined. Skipping automated-admin-email creation."
fi
```

#### 3.3.2. `dynamic-installed-cluster-admin-list`
```bash
if [ ${#CLUSTER_ADMIN_EMAILS[@]} -gt 0 ]; then
    echo "[-] Applying dynamic cluster admin email list (${#CLUSTER_ADMIN_EMAILS[@]} users)..."
    DYNAMIC_ADMINS_FILE="${CLUSTER_CONFIG_DIR}/cluster-admins-dynamic.yaml"
    cat <<EOF >"${DYNAMIC_ADMINS_FILE}"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dynamic-installed-cluster-admin-list
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
EOF
    for admin_email in "${CLUSTER_ADMIN_EMAILS[@]}"; do
        cat <<EOF >>"${DYNAMIC_ADMINS_FILE}"
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: ${admin_email}
EOF
    done
    sudo KUBECONFIG="/etc/kubernetes/admin.conf" kubectl apply -f "${DYNAMIC_ADMINS_FILE}"
    echo "[OK] ClusterRoleBinding 'dynamic-installed-cluster-admin-list' applied successfully."
else
    echo "[-] No cluster admin emails defined in facts. Skipping dynamic-installed-cluster-admin-list creation."
fi
```

---

## 4. Verification Plan

1. **Facts Parsing Test**:
   - Provide a mock facts JSON with `.cluster.cluster_admin_emails: ["user1@example.com", "user2@example.com"]`.
   - Verify both `jq` and `python3` paths extract identical arrays.
2. **Dry-run Execution**:
   - Run `create_cluster.sh --dry-run --facts <mock-facts>` and check printed admin emails.
3. **Empty Array Handling**:
   - Test with `.cluster.cluster_admin_emails: []` and ensure no errors are thrown and skip message is emitted.
4. **Documentation**:
   - Update `docs/CREATE_CLUSTER.md` referencing the updated bindings.
