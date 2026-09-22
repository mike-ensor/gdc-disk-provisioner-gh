# GDC Companion API Update Specification: Dynamic Boot Identification

## Overview
The GDC ISO installation process is transitioning from using a static, build-time generated `session` ID to a dynamic, ephemeral `boot_id` generated at boot time. Additionally, the primary network interface's MAC address is now being transmitted to provide hardware-level correlation.

This specification details the changes required in the `gdc-companion` API to accommodate the updated webhook and phone-home payloads originating from the ISO's `user-data`.

## Endpoint Changes

Both the `phone_home` and `reporting.webhook` endpoints within the ISO have been updated.

**Previous Format:**
`?version={{ ISO_VERSION }}&session={{ boot_session_id }}&logname=<phone-home|webhook>`

**New Format:**
`?version={{ ISO_VERSION }}&build_id=@@BUILD_ID@@&mac=@@PRIMARY_MAC@@&logname=<phone-home|webhook>`

## Parameter Details

The `gdc-companion` must be updated to accept and process the following query parameters on its logging/reporting endpoints (e.g., `/public` and `/secure`):

### Removed Parameters
*   **`session`**: This parameter has been completely removed. It previously contained an 8-digit integer (e.g., `12345678`) generated randomly during the ISO build process.

### New/Modified Parameters

| Parameter | Data Type | Expected Value Format | Description |
| :--- | :--- | :--- | :--- |
| `build_id` | String | 32-character hexadecimal string (no hyphens) | Replaces `session`. This is the kernel's `boot_id` (`/proc/sys/kernel/random/boot_id`), with hyphens stripped. It is unique per boot cycle of the ISO. Example: `8e6c738e4a9e4e67b2d5a3c9f1e8a4d2` |
| `mac` | String | 12-character hexadecimal string (no colons) | The MAC address of the primary active network interface on the booting node, with colons stripped. Example: `001a2b3c4d5e` |
| `version` | String | Semantic versioning string | Unchanged. The version of the ISO being installed. Example: `v1.2.3` |
| `logname` | String | Literal string | Unchanged. Identifies the source of the log. Expected values are typically `phone-home` or `webhook`. |

## Expected Behavior Updates in gdc-companion

1.  **Ingestion/Parsing:** Update the API handlers to extract `build_id` and `mac` instead of `session`.
2.  **Correlation:** Any internal logic, database schema, or logging aggregation that previously relied on `session` to group installation events must be updated to use `build_id`.
3.  **Hardware Tracking:** The new `mac` parameter should be stored/logged to allow correlation of multiple boot attempts (`build_id`s) to the same physical hardware node.
4.  **Backwards Compatibility (Optional but Recommended):** If the `gdc-companion` must support older ISOs during a transition period, the API should handle requests containing *either* `session` OR (`build_id` and `mac`).