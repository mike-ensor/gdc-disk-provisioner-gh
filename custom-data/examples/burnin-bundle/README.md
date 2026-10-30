# Sample GDC Custom Playbook Burn-In Bundle

This directory provides a functional reference example of a custom playbook lifecycle extension bundle conforming to `GDC-SPEC-017` and the declarative hierarchical bundle architecture.

## Directory Layout

```text
burnin-bundle/
├── manifest.yaml             # Declarative bundle specification and stage authority
├── VERSION                   # Semantic version string matching manifest.yaml (1.0.0)
├── requirements.yml          # Optional Ansible Galaxy dependencies
├── README.md                 # Bundle documentation and instructions
├── cluster_turnup/           # Post-hook stage executed after cluster turnup
│   ├── playbook.yaml         # Stage playbook tasks
│   ├── bin/                  # Stage binaries & scripts
│   ├── oci/                  # Container images for air-gapped loading
│   └── pkg/                  # OS packages (RPM/DEB)
└── post_cluster/             # Final validation & burn-in workload stage
    ├── playbook.yaml         # Burn-in workload deployment & validation tasks
    ├── bin/                  # Stage binaries & scripts
    ├── oci/                  # Container images for air-gapped loading
    └── pkg/                  # OS packages (RPM/DEB)
```

## Packaging this Bundle

To generate a `.tar.gz` bundle for sideloading or serving via `gdc-companion`:

```bash
tar -czvf /var/gdc-install/custom-bundle.tar.gz -C custom-data/examples/burnin-bundle/ .
sha256sum /var/gdc-install/custom-bundle.tar.gz
```
