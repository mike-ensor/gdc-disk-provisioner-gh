# Plan: Bootimus Asynchronous Extraction & Clobbering Resilience

## 1. Context & Problem Statement
The GDC ISO build pipeline utilizes a tool called `bootimus.py` to automatically register newly compiled `.iso` files into a remote PXE/HTTP booting environment. 

Due to the size of the GDC ISOs (~4-5GB), the Bootimus backend extraction process takes between 3 to 5 minutes to complete over the network. 

Currently, `bootimus.py` blocks synchronously in a `while True` loop, polling the Bootimus API until extraction reaches 100%. Once extraction completes, Bootimus contains a known bug where its backend daemon resets the image to an "empty/disabled" state, clobbering any custom boot parameters that were set. The `bootimus.py` script attempts to mitigate this by immediately firing a self-healing algorithm to lock the parameters back to `autoinstall`.

### The Vulnerability
When executed by automated CI/CD tools or agent shells that enforce strict global timeouts (e.g., 120 seconds), the `bootimus.py` script is forcefully killed by the parent process *before* the backend extraction finishes. Because the script dies prematurely, the protective self-healing loop never executes. When Bootimus finishes extracting minutes later, it wipes the parameters, leaving the image in a disabled/clobbered state indefinitely.

## 2. Proposed Solution (Option 1: The "Always Heal" Wrapper)
Instead of relying solely on `bootimus.py` to hold the connection open infinitely, the responsibility for guaranteeing stability should be moved higher up the stack to the orchestrator (e.g., the `Makefile` or deployment scripts).

The orchestrator will utilize the existing `test/bin/check-bootimus-settings.py` script, which natively imports and executes the `auto_heal_boot_params()` function from `bootimus.py`. 

By wrapping the auditor script in a robust retry loop with native Bash timeouts, the pipeline will guarantee that the database is healed *after* the extraction finishes, regardless of how long the initial `bootimus.py` script lived.

## 3. Implementation Details

### Target: `src/build/Makefile` (or equivalent orchestrator)
The `deploy` or `test-dynamic` stage will be updated to implement the polling loop:

```make
	@echo "[-] Ingesting ISO into Bootimus PXE environment..."
	@python3 src/build/bootimus.py $(FINAL_ISO_NAME) || true
	@echo "[-] Enforcing strict boot configuration lock (waiting for extraction to settle)..."
	@for i in {1..30}; do \
		if python3 test/bin/check-bootimus-settings.py; then \
			echo "[x] Bootimus configuration locked successfully."; \
			break; \
		fi; \
		echo "[-] Waiting 15s for extraction to settle... ($$i/30)"; \
		sleep 15; \
	done
```

### Impact
1. **Resilience:** The pipeline will survive rigid 2-minute script timeouts.
2. **Idempotency:** Because `check-bootimus-settings.py` uses self-healing logic, it will continuously poll the database and only exit with `0` (Success) when the parameters are permanently locked in and the image is fully extracted.
3. **Decoupling:** `bootimus.py` can eventually be refactored to trigger extraction asynchronously without needing to block, pushing validation logic entirely to the auditor script.