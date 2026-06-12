# Specification: GDC Offline ISO Build & Remastering Pipeline

**Spec Identifier:** `GDC-SPEC-001`  
**Status:** DRAFT  
**Author:** GDC Disk Provisioner Architecture Team  

---

## 1. Overview & Purpose
The GDC ISO build pipeline is an automated, Infrastructure-as-Code (IaC) remastering process. It converts a standard, official Ubuntu 24.04 LTS server ISO into a fully customized, offline-first bootloader. The output ISO contains the pre-configured automated installation schemas (`subiquity`/`cloud-init`), pre-baked binary stores (Gitea and Nexus), and a pre-packaged suite of Ansible playbooks.

This allows complete deployment without an active internet connection.

---

## 2. ISO Remastering Filesystem Layout
The remastering pipeline extracts the source ISO, adds custom layers, and outputs a bootable hybrid ISO image. The structured workspace layout is defined as follows:

```text
/d/projects/google/gdc-disk-provisioner/
├── src/build/
│   ├── Makefile                    # Main pipeline coordinator
│   ├── remaster.sh                 # Active assembly shell script
│   └── grub.cfg                    # Custom GRUB boot options template
└── build-workspace/
    ├── base-iso/                   # Mounted/Extracted original Ubuntu ISO
    └── custom-iso/                 # remux root directory
        ├── EFI/                    # Copied EFI BIOS boot sector
        ├── boot/                   # GRUB loader system
        ├── nocloud/                # Cloud-init Auto-installation folder
        │   ├── user-data           # Subiquity YAML directives
        │   └── meta-data           # Virtual platform metadata
        └── custom-data/            # Remaster payload folder
            ├── gitea/              # Ephemeral/Persistent Git server
            │   ├── gitea           # Standalone Gitea Go binary
            │   └── repos/          # Local bare repositories
            │       └── bootstrap-playbooks.git
            ├── nexus/              # Sonatype Nexus Repository Manager
            │   ├── nexus-bin/      # Standalone Nexus and Java 8/17 JVM
            │   └── blobs/          # Pre-seeded cache repositories
            │       ├── apt-hosted/
            │       ├── docker-hosted/
            │       └── llm-raw/
            └── systemd/            # Live environment service unit files
                ├── live-gitea.service
                └── live-nexus.service
```

---

## 3. Pre-Seeding Caches and Repositories

### 3.1. Gitea Repository Pre-Seeding
During the build phase, our local configuration playbooks are pre-packaged as a **bare Git repository**:
1. Create a bare git folder in the custom ISO path:
   ```bash
   git init --bare build-workspace/custom-iso/custom-data/gitea/repos/bootstrap-playbooks.git
   ```
2. Set the default branch to `main`:
   ```bash
   git -C build-workspace/custom-iso/custom-data/gitea/repos/bootstrap-playbooks.git symbolic-ref HEAD refs/heads/main
   ```
3. Push the active playbooks from the host workspace (`src/ansible`) directly into the bare repository:
   ```bash
   git push build-workspace/custom-iso/custom-data/gitea/repos/bootstrap-playbooks.git main:main
   ```

### 3.2. Nexus Offline Blob Pre-Seeding
We seed the raw blobs directly into Nexus's filesystem store on the ISO:
* **APT Cache:** Run a helper container to download GDC dependency packages and write them to the local blob file format under `/custom-data/nexus/blobs/apt-hosted/`.
* **Docker Registry:** Pre-load container images (e.g. `gitea/gitea:latest`, python runners, local tools), write them into the Docker hosted database blobs.
* **LLM Cache:** Download Hugging Face models (e.g. Llama-3, Gemma-2) and structure them inside `/custom-data/nexus/blobs/llm-raw/`.

---

## 4. RAM Execution (Live OverlayFS Strategy)
Since the booted ISO filesystem is read-only, we utilize `systemd` scripts on the Live ISO to run Gitea and Nexus inside writeable memory overlays (`tmpfs`).

When the ISO boots, `live-gitea.service` and `live-nexus.service` execute the following before launching their respective servers:

```bash
#!/bin/bash
# Prepare a writeable workspace in RAM
mkdir -p /tmp/gitea-ram/upper /tmp/gitea-ram/work /var/lib/gitea

# Mount Gitea in RAM using an OverlayFS
mount -t overlay overlay \
  -o lowerdir=/cdrom/custom-data/gitea,\
upperdir=/tmp/gitea-ram/upper,\
workdir=/tmp/gitea-ram/work \
  /var/lib/gitea

# Launch the Gitea service using the mounted path
/var/lib/gitea/gitea web --config /var/lib/gitea/app.ini &
```

*This process is repeated identically for Nexus, mounting `/cdrom/custom-data/nexus` to `/var/lib/nexus` and allocating a 4GB RAM swap reservation.*

---

## 5. Xorriso ISO Repack Command
The final build step of the Makefile executes `xorriso` to output a hybrid ISO that supports both legacy BIOS and UEFI booting from USB flash drives and optical media:

```bash
xorriso -as mkisofs -r -V "GDC-BOOTSTRAP" \
  -J -b boot/grub/efi.img -c boot.catalog \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -elt-torito-alt-boot -e boot/grub/efi.img -no-emul-boot \
  -isohybrid-gpt-basdat \
  -o build-workspace/gdc-bootstrap-ubuntu-24.04.iso \
  build-workspace/custom-iso/
```

---

## 6. Build Pipeline Verification Metrics
1. **ISO Syntactic Check:** Ensure `/custom-iso/nocloud/user-data` validates against `cloud-init` autoinstall schema checks.
2. **Deterministic Hash:** Re-running the build with unchanged files must yield an ISO with an identical SHA-256 hash.
3. **Boot Test:** Verify the generated ISO boots cleanly in a QEMU-KVM environment.
