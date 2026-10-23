# In-cluster PKI with cert-manager, ClusterIssuer, and HTTPRoute

This guide explains how Google Distributed Cloud (GDC) bare-metal appliances transition from host-level certificate management to Kubernetes-native Public Key Infrastructure (PKI). You'll find concrete architectural flows and manifest codeblocks for seeding the Sub-CA, minting certificates with `cert-manager`, and securing ingress traffic through Gateway API `HTTPRoute` resources.

---

## Seeding the ClusterIssuer during turnup and post-cluster stages

GDC bare-metal provisioning follows a staged lifecycle managed by Ansible and `bmctl`. Managing certificates requires passing identity across two distinct security boundaries: first from cloud storage to bare-metal disk, then from bare-metal disk into the Kubernetes control plane.

```text
 ┌────────────────────────────────────────────────────────┐
 │ Stage 4 & 5: CLUSTER_READY                             │
 │ • pki_ingest.yml fetches Sub-CA from Secret Manager    │
 │ • Files written to /etc/ssl/sub-ca/ and trust store    │
 └───────────────────────────┬────────────────────────────┘
                             │
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │ Stage 6: CLUSTER_TURNUP                                │
 │ • bmctl bootstrap Kind container initializes           │
 │ • Anthos Bare Metal control plane installed            │
 └───────────────────────────┬────────────────────────────┘
                             │
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │ Stage 7: POST_CLUSTER                                  │
 │ • cert_manager_pki.yml slurps host certs & keys        │
 │ • Secret gdc-sub-ca-keypair created in cert-manager    │
 │ • ClusterIssuer gdc-ca-issuer deployed                │
 └────────────────────────────────────────────────────────┘
```

### Stage 5 (CLUSTER_READY): Host-level credential retrieval

Before Kubernetes exists, the appliance needs certificates to terminate TLS on the local Nexus container registry (`nexus.internal.gdc.local:443`). During `CLUSTER_READY`, the `pki_ingest.yml` task runs:

1. Retrieves the Sub-CA JSON payload from Google Cloud Secret Manager (or from the ISO fallback cache if running in demo mode).
2. Installs the corporate root certificate to `/usr/local/share/ca-certificates/gdc-enterprise-root.crt` (`0644 root:root`) and executes `update-ca-certificates`.
3. Writes the Sub-CA certificate to `/etc/ssl/sub-ca/sub-ca.crt` (`0644 root:root`).
4. Writes the Sub-CA private key to `/etc/ssl/sub-ca/sub-ca.key` with strict permissions (`0400 root:root`).

### Stage 6 (CLUSTER_TURNUP): Control plane inception

During Stage 6, `bmctl create cluster` deploys an ephemeral Kind bootstrap container that joins the target physical nodes into an operational Kubernetes control plane. Because container sandboxes don't mount host certificates directly, the cluster turnup process relies on the local Nexus registry using the host-level certificates minted in Stage 5.

### Stage 7 (POST_CLUSTER): Handover to Kubernetes

Once node status reads `Ready` and CoreDNS finishes rolling out, `stage_post_cluster.yml` calls `src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml`. This playbook reads the host certificates and injects them into Kubernetes.

Here's the exact automation pattern executed during Stage 7:

```yaml
# src/ansible/roles/post_cluster/tasks/cert_manager_pki.yml
- name: "GDC-K8S-PKI | Ingest and Handover Sub-CA to In-Cluster cert-manager"
  when:
    - gdc_nexus_tls_enabled | default(true) | bool
  tags: ["corp-cert"]
  block:
    - name: "GDC-K8S-PKI | Slurp Sub-CA certificate from host"
      ansible.builtin.slurp:
        src: "/etc/ssl/sub-ca/sub-ca.crt"
      register: slurped_sub_ca_cert

    - name: "GDC-K8S-PKI | Slurp Enterprise Root CA certificate from host"
      ansible.builtin.slurp:
        src: "/usr/local/share/ca-certificates/gdc-enterprise-root.crt"
      register: slurped_enterprise_root_cert

    - name: "GDC-K8S-PKI | Slurp Sub-CA private key from host"
      ansible.builtin.slurp:
        src: "/etc/ssl/sub-ca/sub-ca.key"
      register: slurped_sub_ca_key
      no_log: true

    - name: "GDC-K8S-PKI | Ensure cert-manager namespace exists"
      ansible.builtin.command:
        cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f -"
        stdin: |
          apiVersion: v1
          kind: Namespace
          metadata:
            name: cert-manager
      changed_when: false

    - name: "GDC-K8S-PKI | Seed Sub-CA TLS secret into cert-manager"
      ansible.builtin.command:
        cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f -"
        stdin: |
          apiVersion: v1
          kind: Secret
          metadata:
            name: gdc-sub-ca-keypair
            namespace: cert-manager
          type: kubernetes.io/tls
          data:
            tls.crt: "{{ ([slurped_sub_ca_cert.content | b64decode | trim, slurped_enterprise_root_cert.content | b64decode | trim] | join('\n')) | b64encode }}"
            tls.key: "{{ slurped_sub_ca_key.content }}"
      no_log: true

    - name: "GDC-K8S-PKI | Deploy gdc-ca-issuer ClusterIssuer"
      ansible.builtin.command:
        cmd: "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f -"
        stdin: |
          apiVersion: cert-manager.io/v1
          kind: ClusterIssuer
          metadata:
            name: gdc-ca-issuer
          spec:
            ca:
              secretName: gdc-sub-ca-keypair
      register: deploy_issuer_res
      changed_when: "'created' in deploy_issuer_res.stdout or 'configured' in deploy_issuer_res.stdout"
      ignore_errors: true
```

The seeded Kubernetes Secret contains the combined certificate bundle (`sub-ca.crt` followed by `gdc-enterprise-root.crt`) under `tls.crt`. Clients connecting to in-cluster workloads receive the intermediate certificate along with the leaf, letting them trace trust back to the corporate root without missing intermediate cert errors.

---

## How cert-manager issues certificates using the ClusterIssuer

A `ClusterIssuer` is a cluster-scoped resource. Any namespace can reference `gdc-ca-issuer` without needing an issuer copied into each namespace.

### The issuance lifecycle

When an application team defines a `Certificate` resource, `cert-manager` drives the reconciliation flow:

```text
 ┌───────────────────────────┐
 │ 1. Apply Certificate CRD  │
 └─────────────┬─────────────┘
               │
               ▼
 ┌───────────────────────────┐
 │ 2. cert-manager generates │
 │    private key & CSR      │
 └─────────────┬─────────────┘
               │
               ▼
 ┌───────────────────────────┐
 │ 3. CertificateRequest     │
 │    created                │
 └─────────────┬─────────────┘
               │
               ▼
 ┌───────────────────────────┐
 │ 4. CA Issuer signs CSR    │
 │    with gdc-sub-ca-keypair│
 └─────────────┬─────────────┘
               │
               ▼
 ┌───────────────────────────┐
 │ 5. Destination Secret     │
 │    written with tls.crt   │
 └───────────────────────────┘
```

1. **Private key generation**: `cert-manager` generates a private key according to spec (e.g. RSA 2048 or ECDSA P-256) inside the target namespace.
2. **CSR creation**: A `CertificateRequest` resource is created containing the x509 CSR.
3. **Signing execution**: The CA signer reconciler retrieves the `gdc-sub-ca-keypair` Secret from the `cert-manager` namespace, decrypts the Sub-CA key, signs the CSR, and attaches the intermediate CA chain.
4. **Secret population**: The signed certificate, CA cert, and private key get written to the destination Secret.

### Example: Requesting a workload certificate

Here's an example manifest requesting a TLS certificate for a service running in the `production-apps` namespace:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: billing-api-tls
  namespace: production-apps
spec:
  # Destination Secret where cert-manager writes the keypair
  secretName: billing-api-tls-secret
  duration: 2160h # 90 days validity
  renewBefore: 720h # Renew automatically 30 days before expiry

  # Reference the ClusterIssuer created in Stage 7
  issuerRef:
    name: gdc-ca-issuer
    kind: ClusterIssuer
    group: cert-manager.io

  # Subject Alternative Names (SANs)
  commonName: billing.internal.gdc.local
  dnsNames:
    - billing.internal.gdc.local
    - billing.gdc.local
    - billing-api.production-apps.svc.cluster.local
    - billing-api.production-apps.svc

  # Key algorithm parameters
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always

  usages:
    - digital signature
    - key encipherment
    - server auth
    - client auth
```

### Inspecting the issued certificate

Verify the status and properties using standard `kubectl` commands:

```bash
# Check if cert-manager marked the Certificate Ready
kubectl get certificate billing-api-tls -n production-apps

# View event history and renewal conditions
kubectl describe certificate billing-api-tls -n production-apps

# Verify the resulting Secret contains the expected keys
kubectl get secret billing-api-tls-secret -n production-apps -o jsonpath='{.data}' | jq 'keys'
# Output: ["ca.crt", "tls.crt", "tls.key"]

# Inspect the certificate dates and SANs directly from the Secret
kubectl get secret billing-api-tls-secret -n production-apps -o jsonpath='{.data.tls\.crt}' \
  | base64 -d \
  | openssl x509 -text -noout | grep -E "(Issuer|Subject:|Not After|DNS:)"
```

---

## Mounting the TLS certificate to an HTTPRoute

Kubernetes Gateway API separates network infrastructure from application routing. Unlike legacy Ingress resources where TLS termination, hosts, and paths sit inside a single YAML object, Gateway API divides responsibilities:

- **Cluster Operator**: Manages the `Gateway` resource, sets up network listeners on port 443, and attaches the TLS Secret produced by `cert-manager`.
- **Application Developer**: Authors the `HTTPRoute` resource, attaches to the `Gateway` via `parentRefs`, and configures path routing rules.

```text
 ┌────────────────────────────────────────────────────────┐
 │ Certificate (cert-manager.io)                          │
 │ generates: Secret billing-api-tls-secret               │
 └───────────────────────────┬────────────────────────────┘
                             │ referenced by
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │ Gateway (gateway.networking.k8s.io)                    │
 │ listener: port 443 / HTTPS                             │
 │ certificateRefs: billing-api-tls-secret                │
 └───────────────────────────┬────────────────────────────┘
                             │ attached via parentRefs
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │ HTTPRoute (gateway.networking.k8s.io)                  │
 │ hostnames: ["billing.internal.gdc.local"]              │
 │ rules: /api/v1 -> Service billing-service:8080         │
 └────────────────────────────────────────────────────────┘
```

### Pattern 1: Same-namespace Gateway and HTTPRoute

When your `Gateway` and `HTTPRoute` share the same namespace, configuration stays straightforward.

#### 1. The Gateway definition

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: edge-gateway
  namespace: production-apps
spec:
  gatewayClassName: gdc-gateway-class
  listeners:
    - name: https-billing
      protocol: HTTPS
      port: 443
      hostname: "billing.internal.gdc.local"
      tls:
        mode: Terminate
        certificateRefs:
          - group: ""
            kind: Secret
            name: billing-api-tls-secret
      allowedRoutes:
        namespaces:
          from: Same
```

#### 2. The HTTPRoute definition

The `HTTPRoute` connects to the `Gateway` listener by referencing its name and listener section:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: billing-api-route
  namespace: production-apps
spec:
  parentRefs:
    - name: edge-gateway
      sectionName: https-billing
  hostnames:
    - "billing.internal.gdc.local"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api/v1
      backendRefs:
        - name: billing-service
          port: 8080
          weight: 100
```

---

### Pattern 2: Shared cluster Gateway with cross-namespace ReferenceGrant

In production clusters, platform administrators often run a shared `Gateway` in an ingress or system namespace (like `gdc-system`), while product teams manage `HTTPRoute` resources in their own application namespaces.

Because the `Gateway` in `gdc-system` needs access to read a `Secret` or bind routes across namespace boundaries, Gateway API requires an explicit `ReferenceGrant`.

#### 1. The shared Gateway in `gdc-system`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shared-cluster-gateway
  namespace: gdc-system
spec:
  gatewayClassName: gdc-gateway-class
  listeners:
    - name: https-wildcard
      protocol: HTTPS
      port: 443
      hostname: "*.internal.gdc.local"
      tls:
        mode: Terminate
        certificateRefs:
          - group: ""
            kind: Secret
            name: billing-api-tls-secret
            namespace: production-apps
      allowedRoutes:
        namespaces:
          from: All
```

#### 2. The ReferenceGrant in `production-apps`

Without this grant, the `Gateway` controller will fail with an authorization error and refuse to mount the Secret:

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-read-tls-secret
  namespace: production-apps
spec:
  from:
    # Allow Gateways from gdc-system to consume resources
    - group: gateway.networking.k8s.io
      kind: Gateway
      namespace: gdc-system
  to:
    # Allow access to Secret resources in this namespace
    - group: ""
      kind: Secret
      name: billing-api-tls-secret
```

#### 3. The cross-namespace HTTPRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: billing-api-route
  namespace: production-apps
spec:
  parentRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: shared-cluster-gateway
      namespace: gdc-system
      sectionName: https-wildcard
  hostnames:
    - "billing.internal.gdc.local"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: billing-service
          port: 8080
```

---

## Verifying end-to-end TLS routing

Once you've applied the manifests, run through this four-step diagnostic sequence to confirm everything functions properly:

```bash
# 1. Verify Gateway accepted listener and bound certificate
kubectl get gateway shared-cluster-gateway -n gdc-system -o yaml | grep -A 8 "listeners:"

# 2. Check HTTPRoute parent status
kubectl get httproute billing-api-route -n production-apps -o jsonpath='{.status.parents}' | jq .

# 3. Confirm route attaches with Accepted and ResolvedRefs conditions set to True
kubectl describe httproute billing-api-route -n production-apps

# 4. Test TLS handshake and endpoint response using curl with the Corporate Root CA
curl -Iv https://billing.internal.gdc.local/api/v1/health \
  --cacert /usr/local/share/ca-certificates/gdc-enterprise-root.crt
```

If the handshake succeeds with `SSL certificate verify ok`, your in-cluster microservices are securely reachable via Gateway API TLS termination backed by `cert-manager` and the Stage 7 `ClusterIssuer`.
