# GEMINI: GDC Companion Manual

## 1. Architectural Guardrails
* **Strict Decoupled Isolation:** Communication with GDC booting nodes occurs strictly over Port 80 (HTTP) or Port 443 (mTLS) REST interfaces.
* **Zero Exception Crashes:** All handlers must return `Result<T, AppError>` to guarantee compile-time error propagation instead of panic-runtime dropouts.

## 2. Test Verification Gate
* Run `cargo test` and verify that all unit and integration tests pass green before committing or pushing changes.
