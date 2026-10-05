# Sample GDC Custom Playbook Burn-In Bundle

This directory provides a functional reference example of a custom playbook bundle conforming to `GDC-SPEC-017`.

## Packaging this Bundle
To generate a `.tar.gz` bundle for sideloading or serving via `gdc-companion`:

```bash
tar -czvf /var/gdc-install/custom-bundle.tar.gz -C custom-data/examples/burnin-bundle/ .
sha256sum /var/gdc-install/custom-bundle.tar.gz
```
