# GDC-SPEC-015: Dual Console Routing and Dynamic Debug Terminal Allocation

## 1. Problem Statement & Background

During bare-metal installations of the GDC Offline Bootloader ISO, operators viewing the physical monitor or IPMI BMC video display (VGA/HDMI/KVM) observe that console output halts completely at approximately ~262 seconds:

```text
[ 261.917926] nouveau 0000:02:00.0: unknown chipset (1b3000a1)
[ 262.006964] i915 0000:00:02.0: [drm] *ERROR* Unexpected child device config size 40 (expected 39 for VBT version 261)
```

Although the machine has not hung—and is actively partitioning disks, running Curtin, and extracting OS payloads—the monitor remains permanently frozen on the last printed kernel `dmesg` line. This creates the false impression that the bootloader crashed or deadlocked during early initialization.

This is a low-priority enhancement primarily intended to assist lab operators and field engineers during early-stage development and hardware bring-up.

---

## 2. Root Cause Analysis

### 2.1. Kernel Console Multiplexing vs. User-Space `/dev/console`
The Linux kernel handles multiple `console=` parameters with asymmetric behavior:
1. **Kernel Messages (`printk` / `dmesg`):** Broadcast to **all** declared consoles simultaneously. Both `tty1` (or `tty0`) and `ttyS0` receive every kernel boot log.
2. **User-Space Primary Console (`/dev/console`):** Attached **only to the last** console specified on the kernel command line.

In current builds, the kernel parameters specify:
```text
console=tty1 console=ttyS0,115200
```
Because `console=ttyS0,115200` is the final parameter, `/dev/console` is bound to the serial port. Once the kernel completes its driver initialization at ~262 seconds and hands execution to user space, `systemd`, `cloud-init`, and Subiquity direct their primary standard streams exclusively to `ttyS0`.

### 2.2. Single-Target Installer Log Redirection
In `src/build/templates/user-data.j2`, the installer explicitly streams the live Subiquity debug log only to the serial device:
```bash
touch /var/log/installer/subiquity-server-debug.log
tail -f /var/log/installer/subiquity-server-debug.log > /dev/ttyS0 2>/dev/null &
```
Because this log is not mirrored to the active virtual terminal (`/dev/tty0` or `/dev/tty1`), the physical display receives zero updates while Subiquity partitions disks and unpacks filesystems.

---

## 3. Goals & Non-Goals

### Goals
* **Live Display Parity:** Ensure lab operators and field engineers viewing physical displays or IPMI KVM sessions see live installation progress in real time.
* **Mode-Specific Precedence:** Evaluate dynamic console ordering where Debug builds prioritize the physical screen, while Production builds prioritize serial consoles.
* **Zero Production Impact:** Maintain headless serial-first automation in production datacenter environments.

### Non-Goals
* Removing serial logging from production builds.
* Modifying upstream Subiquity internals or TUI terminal allocations.

---

## 4. Architectural Alternatives & Proposed Designs

### Option A: Dual-Tee Log Streaming (Recommended & Least Invasive)
Regardless of which device is assigned as `/dev/console`, update `user-data.j2` to broadcast the live installer debug stream across both serial and the active screen:
```bash
touch /var/log/installer/subiquity-server-debug.log
tail -f /var/log/installer/subiquity-server-debug.log | tee /dev/ttyS0 > /dev/tty0 2>/dev/null &
```
* **Why `/dev/tty0` instead of `/dev/tty1`:** `tty0` is an alias for whichever virtual console is currently active in the foreground, ensuring output displays even if Subiquity switches consoles.
* **Pros:** Simple, robust, works regardless of kernel parameter order, and prevents the "frozen screen" appearance.

### Option B: Dynamic Kernel Command-Line Inversion
In `src/build/render_templates.py` and `src/build/bootimus.py`, dynamically generate the kernel console parameter order based on `GDC_DEBUG_MODE`:
* **When `GDC_DEBUG_MODE=true` (Development / Lab ISO):**
  ```text
  console=ttyS0,115200 console=tty0
  ```
  *(Places `tty0` last, designating the physical screen as `/dev/console` for all interactive prompts and systemd status updates).*
* **When `GDC_DEBUG_MODE=false` (Production ISO):**
  ```text
  console=tty0 console=ttyS0,115200
  ```
  *(Places `ttyS0` last, preserving standard headless IPMI Serial-over-LAN behavior).*

### Option C: Combined Approach (Full Dual Visibility)
Combine Option A (dual-teeing log tail to `/dev/tty0` and `/dev/ttyS0`) with Option B (flipping primary console in debug builds). In addition, inject `systemd.show_status=yes` in debug builds so systemd unit startup messages remain visible on both terminals.

---

## 5. Verification Plan

1. **QEMU Multi-Console Emulation:**
   * Boot the generated ISO in QEMU with both `-display curses/gtk` (VGA) and `-serial mon:stdio`.
   * Confirm that both the VGA window and the host terminal print continuous output beyond 262s without freezing.
2. **Bare-Metal BMC KVM vs. Serial Test:**
   * Boot the node with IPMI Web KVM and IPMI Serial-over-LAN connected concurrently.
   * Verify neither interface experiences a blackout during the block-meta / curtin-install phase.
