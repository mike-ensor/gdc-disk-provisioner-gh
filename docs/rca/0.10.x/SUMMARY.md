# GDC Release 0.10.x Root Cause Analysis (RCA) Index

This directory documents post-mortems and root cause analyses for incidents identified during the `v0.10.x` release cycle of the Google Distributed Cloud (GDC) Bare Metal Disk Provisioner and Companion services.

---

## Incidents Documented

| Incident ID | Date | Affected Nodes | Severity | Summary | Link |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GDC-RCA-2026-10-06-01** | 2026-10-06 | `192.168.9.242`, `.243`, `.246`, `.234` | **Critical** | Cluster turnup stalls caused by `/bin/sh` pipefail syntax error in GPU probe; Ada Lovelace open driver mandate; false-positive preflight failures on `/var/lib/etcd` in `gdc-collector`. | [RCA-v0.10.7-turnup-and-collector-failures.md](./RCA-v0.10.7-turnup-and-collector-failures.md) |
