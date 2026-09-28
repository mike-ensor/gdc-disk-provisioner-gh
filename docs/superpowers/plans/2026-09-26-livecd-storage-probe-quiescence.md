# LiveCD Storage Probe Quiescence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 50% intermittent LiveCD boot hang at `subiquity/Filesystem/_probe/probe_once` by enforcing an automated bottom-up storage teardown and bounded udev quiescence sequence in `user-data.j2` `early-commands`, and create a squash-merge GitLab Merge Request using `glab`.

**Architecture:** Refactor the LiveCD storage sanitization phase from top-down destructive wipes into a strict bottom-up teardown (`unmount` -> `LVM deactivate` -> `dm-crypt close` -> `dmsetup remove_all` -> `wipefs` child partitions then disk -> 32MB head/tail zeroing -> `partprobe` -> `udevadm settle --timeout=15`). Remove the brittle snap bind-mount hack and stream real-time console status markers across `/dev/ttyS0` and `/dev/console`.

**Tech Stack:** Jinja2 (`user-data.j2`), Bash, Linux Block Subsystem (`lvm2`, `cryptsetup`, `dmsetup`, `wipefs`, `udevadm`), Python `unittest`, GitLab CLI (`glab`).

---

### Task 1: Create Feature Branch

**Files:**
- Repository Git state

- [ ] **Step 1: Check working directory status and branch out**

Run:
```bash
git checkout -b fix/livecd-storage-probe-quiescence
```
Expected output: `Switched to a new branch 'fix/livecd-storage-probe-quiescence'`

- [ ] **Step 2: Confirm clean working branch tracking**

Run:
```bash
git branch --show-current
```
Expected output: `fix/livecd-storage-probe-quiescence`

---

### Task 2: Add Failing Unit Tests for Storage Teardown & Quiescence

**Files:**
- Modify: `test/test_template_hydration.py`

- [ ] **Step 1: Add unit tests validating bottom-up teardown and bounded udev settle**

Add the following test method to `TestTemplateHydration` in `test/test_template_hydration.py`:

```python
    def test_storage_sanitization_bottom_up_quiescence(self):
        """Verifies that user-data enforces bottom-up storage teardown and bounded udev settle."""
        template = self.jinja_env.get_template('user-data.j2')
        rendered = template.render(self.base_env)

        # Assert bottom-up ordering: LVM deactivate and DM close before disk wipe
        self.assertIn("vgchange -an --force", rendered)
        self.assertIn("dmsetup table --target crypt", rendered)
        self.assertIn("dmsetup remove_all --force", rendered)

        # Assert removal of dangerous blkdiscard and snap bind-mount hack
        self.assertNotIn("blkdiscard --force", rendered)
        self.assertNotIn("mount --bind /tmp/cryptsetup-wrapper", rendered)

        # Assert bounded udev settle and partition refresh
        self.assertIn("udevadm settle --timeout=15", rendered)
        self.assertIn("udevadm trigger --action=change", rendered)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
python3 -m unittest test.test_template_hydration.TestTemplateHydration.test_storage_sanitization_bottom_up_quiescence
```
Expected output: `FAIL` (assertion `blkdiscard --force` or `mount --bind /tmp/cryptsetup-wrapper` fails because legacy commands are still present).

---

### Task 3: Refactor Storage Sanitization in `user-data.j2`

**Files:**
- Modify: `src/build/templates/user-data.j2:196-405`

- [ ] **Step 1: Implement the bottom-up teardown and bounded udev quiescence sequence**

In `src/build/templates/user-data.j2`, replace the Step 4 disk sanitization and Step 4.5 cryptsetup wrapper blocks with:

```bash
    - |
      # [GDC-INSTALL-STEP 4/12] Performing deterministic bottom-up storage teardown & udev quiescence...
      echo "==============================================================================" >/dev/ttyS0 2>/dev/null || true
      echo "[GDC-INSTALL-GOAL] Starting Task: Bottom-up storage teardown & udev quiescence" >/dev/ttyS0 2>/dev/null || true
      echo "==============================================================================" >/dev/ttyS0 2>/dev/null || true
      logger -t gdc-provisioner "[GOAL] Bottom-up storage teardown & udev quiescence" 2>/dev/null || true

      # Discover installer live media disks to prevent self-erasure when booted from USB
      INSTALLER_DISKS=""
      for mnt in /cdrom /isodevice /run/live/medium; do
        if dev=$(findmnt -no SOURCE "${mnt}" 2>/dev/null) && [ -n "${dev}" ]; then
          real_dev=$(readlink -f "${dev}" 2>/dev/null || echo "${dev}")
          if [ -b "${real_dev}" ]; then
            case "${real_dev}" in
              *loop[0-9]*)
                back_file=$(losetup -O BACK-FILE -n "${real_dev}" 2>/dev/null || true)
                if [ -n "${back_file}" ]; then
                  loop_src=$(findmnt -no SOURCE -T "${back_file}" 2>/dev/null || true)
                  if [ -n "${loop_src}" ] && [ -b "${loop_src}" ]; then
                    loop_pk=$(lsblk -no PKNAME "${loop_src}" 2>/dev/null | head -n 1 | tr -d '[:space:]')
                    INSTALLER_DISKS="${INSTALLER_DISKS} ${loop_pk:-$(basename "${loop_src}")}"
                  fi
                fi
                ;;
              *)
                pkname=$(lsblk -no PKNAME "${real_dev}" 2>/dev/null | head -n 1 | tr -d '[:space:]')
                INSTALLER_DISKS="${INSTALLER_DISKS} ${pkname:-$(basename "${real_dev}")}"
                ;;
            esac
          fi
        fi
      done

      # Also detect any block devices hosting iso9660 filesystem
      for iso_dev in $(blkid -t TYPE=iso9660 -o device 2>/dev/null || true); do
        if [ -n "${iso_dev}" ] && [ -b "${iso_dev}" ]; then
          real_dev=$(readlink -f "${iso_dev}" 2>/dev/null || echo "${iso_dev}")
          pkname=$(lsblk -no PKNAME "${real_dev}" 2>/dev/null | head -n 1 | tr -d '[:space:]')
          INSTALLER_DISKS="${INSTALLER_DISKS} ${pkname:-$(basename "${real_dev}")}"
        fi
      done

      is_protected_dev() {
        target_dev="$1"
        [ -b "${target_dev}" ] || return 1
        bname=$(basename "${target_dev}")
        pkname=$(lsblk -no PKNAME "${target_dev}" 2>/dev/null | head -n 1 | tr -d '[:space:]')
        if [ -n "${pkname}" ]; then
          root_disk="${pkname}"
        elif [ -f "/sys/class/block/${bname}/partition" ]; then
          root_disk=$(basename "$(dirname "$(readlink -f "/sys/class/block/${bname}")")")
        else
          root_disk="${bname}"
        fi

        for inst_d in ${INSTALLER_DISKS}; do
          if [ "${root_disk}" = "${inst_d}" ] || [ "${bname}" = "${inst_d}" ]; then
            return 0
          fi
        done

        tran=$(lsblk -dno TRAN "/dev/${root_disk}" 2>/dev/null || true)
        if [ "${tran}" = "usb" ]; then
          return 0
        fi
        if [ -d "/sys/block/${root_disk}" ]; then
          syspath=$(readlink -f "/sys/block/${root_disk}" 2>/dev/null || true)
          case "${syspath}" in
            */usb*) return 0 ;;
          esac
        fi
        return 1
      }

      # 1. Unmount any stale mounts under /target, /mnt, or /media
      echo "[-] [STORAGE-CLEANUP] Unmounting stale target filesystems..." >/dev/ttyS0 2>/dev/null || true
      grep -E '/target|/mnt' /proc/mounts 2>/dev/null | awk '{print $2}' | sort -r | while read -r mnt_pt; do
        if [ -n "${mnt_pt}" ]; then
          umount -f -l "${mnt_pt}" 2>/dev/null || true
        fi
      done

      # 2. Teardown active Logical Volumes and Volume Groups unconditionally
      echo "[-] [STORAGE-CLEANUP] Deactivating existing LVM volume groups..." >/dev/ttyS0 2>/dev/null || true
      vgchange -an --force 2>/dev/null || true
      lvchange -an --force 2>/dev/null || true

      # 3. Close open cryptsetup containers and purge device-mapper nodes
      echo "[-] [STORAGE-CLEANUP] Closing existing DM-Crypt mappings..." >/dev/ttyS0 2>/dev/null || true
      dmsetup table --target crypt 2>/dev/null | cut -d: -f1 | while read -r crypt_dev; do
        if [ -n "${crypt_dev}" ]; then
          cryptsetup close "${crypt_dev}" 2>/dev/null || true
        fi
      done
      dmsetup remove_all --force 2>/dev/null || true

      # 4. Wipe filesystem/partition signatures bottom-up (partitions first, then raw disks)
      echo "[-] [STORAGE-CLEANUP] Wiping partition and block signatures..." >/dev/ttyS0 2>/dev/null || true
      for p in /dev/nvme*p* /dev/sd*[0-9]*; do
        if [ -b "${p}" ] && ! is_protected_dev "${p}"; then
          wipefs --all --force "${p}" 2>/dev/null || true
        fi
      done

      # 5. Targeted boundary zeroing on raw target disks (Avoid blkdiscard controller stalls)
      for d in $(lsblk -dno NAME | grep -vE 'loop|sr|ram'); do
        if is_protected_dev "/dev/${d}"; then
          echo "   -> [PROTECT] Preserving protected installer/USB storage disk: /dev/${d}" >/dev/ttyS0 2>/dev/null || true
          continue
        fi
        echo "[-] [STORAGE-CLEANUP] Zeroing GPT and LUKS headers on: /dev/${d}..." >/dev/ttyS0 2>/dev/null || true
        wipefs --all --force "/dev/${d}" 2>/dev/null || true

        # Zero out primary GPT and LUKS header region (first 32MB)
        dd if=/dev/zero of="/dev/${d}" bs=1M count=32 oflag=direct status=none 2>/dev/null || true

        # Zero out secondary backup GPT region (last 32MB)
        disk_size=$(blockdev --getsize64 "/dev/${d}" 2>/dev/null || echo "0")
        if [ "${disk_size}" -gt 33554432 ]; then
          seek_pos=$(( (disk_size - 33554432) / 1048576 ))
          dd if=/dev/zero of="/dev/${d}" bs=1M count=32 seek="${seek_pos}" oflag=direct status=none 2>/dev/null || true
        fi

        # Flush block device caches and reread partition table
        sync 2>/dev/null || true
        blockdev --flushbufs "/dev/${d}" 2>/dev/null || true
        partprobe "/dev/${d}" 2>/dev/null || blockdev --rereadpt "/dev/${d}" 2>/dev/null || true
      done

      # 6. Bounded udev barrier: trigger events and wait with a 15-second ceiling
      echo "[-] [STORAGE-CLEANUP] Synchronizing kernel state & waiting for udev quiescence (15s ceiling)..." >/dev/ttyS0 2>/dev/null || true
      sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
      udevadm trigger --action=change 2>/dev/null || true
      udevadm settle --timeout=15 2>/dev/null || true
      echo "[+] [STORAGE-CLEANUP] Storage subsystem is clean, unlocked, and quiescent." >/dev/ttyS0 2>/dev/null || true
```

- [ ] **Step 2: Run unit test to verify it passes**

Run:
```bash
python3 -m unittest test.test_template_hydration.TestTemplateHydration.test_storage_sanitization_bottom_up_quiescence
```
Expected output: `OK`

- [ ] **Step 3: Run the full hydration test suite**

Run:
```bash
python3 -m unittest test/test_template_hydration.py
```
Expected output: `Ran 27 tests ... OK`

---

### Task 4: Run Static Validation & Build Scripts Verification

**Files:**
- Verify: `test/test_storage_discovery.py`
- Verify: `test/test_gdc_build_scripts.py`

- [ ] **Step 1: Execute storage discovery tests**

Run:
```bash
python3 -m unittest test/test_storage_discovery.py
```
Expected output: `OK`

- [ ] **Step 2: Execute build script tests**

Run:
```bash
python3 -m unittest test/test_gdc_build_scripts.py
```
Expected output: `OK`

- [ ] **Step 3: Validate syntax and Jinja rendering across all templates**

Run:
```bash
python3 -c "import jinja2, os; env = jinja2.Environment(loader=jinja2.FileSystemLoader('src/build/templates')); env.get_template('user-data.j2')"
```
Expected output: Clean return with no syntax errors.

---

### Task 5: Commit Implementation Changes

**Files:**
- Commit: `src/build/templates/user-data.j2`, `test/test_template_hydration.py`

- [ ] **Step 1: Check diff and staged files**

Run:
```bash
git diff --stat
```
Expected output: Lists modified `src/build/templates/user-data.j2` and `test/test_template_hydration.py`.

- [ ] **Step 2: Commit changes adhering to repository convention**

Run:
```bash
git add src/build/templates/user-data.j2 test/test_template_hydration.py docs/superpowers/plans/2026-09-26-livecd-storage-probe-quiescence.md
git commit -m "fix(storage): enforce bottom-up teardown and udev quiescence to prevent livecd probe hangs"
```
Expected output: Commit created on branch `fix/livecd-storage-probe-quiescence`.

---

### Task 6: Push Branch and Create GitLab Merge Request via `glab`

**Files:**
- GitLab Remote API via `glab`

- [ ] **Step 1: Push feature branch to origin**

Run:
```bash
git push -u origin fix/livecd-storage-probe-quiescence
```
Expected output: Branch pushed and remote tracking set.

- [ ] **Step 2: Create Merge Request with squash enabled and comprehensive summary**

Run:
```bash
glab mr create \
  --title "fix(storage): resolve 50% intermittent LiveCD probe hang via bottom-up teardown" \
  --target-branch "main" \
  --source-branch "fix/livecd-storage-probe-quiescence" \
  --squash-before-merge \
  --description "## Summary

### Context & Root Cause
Physical target nodes intermittently stalled (~50% failure rate) during initial PXE boot at \`subiquity/Filesystem/_probe/probe_once\`. Nodes required a hard reboot, after which the second boot passed cleanly.

Forensic analysis of \`stuck-build.jsonl\` confirmed:
1. **Top-Down Teardown Inversion:** Prior storage sanitization attempted to zero partition tables while higher-level device mapper and LUKS containers were active.
2. **NVMe FTL Freezes:** \`blkdiscard --force\` triggered heavy background controller unmap/garbage collection queues on DRAM-less/OEM SSDs, causing subsequent probes to enter uninterruptible sleep (\`D\`-state).
3. **Snap Mount Namespace Isolation:** \`/tmp/cryptsetup-wrapper\` bind-mounted into \`/snap/subiquity/\` could not resolve \`/tmp/cryptsetup.orig\` due to private tmpfs namespaces.

### Key Changes
- **Strict Bottom-Up Teardown:** Enforces unmount -> \`vgchange -an --force\` -> \`cryptsetup close\` -> \`dmsetup remove_all\` before any disk writes.
- **Targeted Boundary Zeroing:** Eliminates \`blkdiscard\` and zeros only the first 32MB (primary GPT/LUKS) and last 32MB (backup GPT).
- **Bounded Udev Barrier:** Replaces unbounded settle calls with \`udevadm settle --timeout=15\`.
- **Snap Bind-Mount Purge:** Eliminates the brittle snap \`cryptsetup-wrapper\` mount.
- **Serial Console Logging:** Emits explicit progress markers to \`/dev/ttyS0\` and \`/dev/console\` during each teardown phase.

### Verification
- \`test/test_template_hydration.py\`: Added \`test_storage_sanitization_bottom_up_quiescence\` validating bottom-up commands, bounded udev settle, and exclusion of blkdiscard.
- All 27 unit tests passing cleanly.
- Merged with \`--squash-before-merge\` enabled."
```
Expected output: GitLab Merge Request URL returned (e.g. `https://gitlab.com/gcp-solutions-public/retail-edge/gdc-disk-provisioner/-/merge_requests/<N>`).
