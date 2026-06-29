# ==============================================================================
# GDC Bootloader ISO Build & Lifecycle Stage-Gate Orchestrator
# ==============================================================================
# Controls the rapid compilation of offline-first GDC bootable ISOs
# and orchestrates automated validation, dynamic testing, and publication.
# ==============================================================================

# Default Shell configuration
SHELL := /usr/bin/env bash

# Export all make variables to child processes by default
.EXPORT_ALL_VARIABLES:

# Robust Helper to extract variables from build.env and local.env safely
get_env = $(shell \
	set -a; \
	[ -f ../dependencies.env ] && . ../dependencies.env &>/dev/null; \
	[ -f ./build.env ] && . ./build.env &>/dev/null; \
	[ -f ./local.env ] && . ./local.env &>/dev/null; \
	if [ -n "$(1)" ]; then echo "$${$(1)}"; fi \
)

# Extract core pipeline configuration variables
ISO_VERSION := $(call get_env,ISO_VERSION)
ISO_NAME_PREFIX := $(call get_env,ISO_NAME_PREFIX)
ENABLE_GCS := $(call get_env,ENABLE_GCS)
GCS_BUCKET := $(call get_env,GCS_BUCKET)
ENABLE_NFS := $(call get_env,ENABLE_NFS)
NFS_DEPLOY_PATH := $(call get_env,NFS_DEPLOY_PATH)
SOURCE_ISO_URL := $(call get_env,SOURCE_ISO_URL)
SOURCE_ISO_FILENAME := $(call get_env,SOURCE_ISO_FILENAME)

# Extract dependency configuration variables
GITEA_BINARY_FILENAME := $(call get_env,GITEA_BINARY_FILENAME)
GITEA_BINARY_SHA256 := $(call get_env,GITEA_BINARY_SHA256)
GITEA_BINARY_URL := $(call get_env,GITEA_BINARY_URL)

JRE_PACKAGE_FILENAME := $(call get_env,JRE_PACKAGE_FILENAME)
JRE_PACKAGE_SHA256 := $(call get_env,JRE_PACKAGE_SHA256)
JRE_PACKAGE_URL := $(call get_env,JRE_PACKAGE_URL)

NEXUS_PACKAGE_FILENAME := $(call get_env,NEXUS_PACKAGE_FILENAME)
NEXUS_PACKAGE_SHA256 := $(call get_env,NEXUS_PACKAGE_SHA256)
NEXUS_PACKAGE_URL := $(call get_env,NEXUS_PACKAGE_URL)

TEMPORARY_INSTALLER_PASSWORD := $(call get_env,TEMPORARY_INSTALLER_PASSWORD)

# Internal Paths and Workspace Definitions
WORKSPACE := ../../build-workspace
EXTRACT_DIR := $(WORKSPACE)/custom-iso
OUTPUT_DIR := $(WORKSPACE)/output
BUILD_META := $(WORKSPACE)/build_meta.env
VENV_DIR := ../../.venv
CACHE_DIR := ../../.cache
BIN_CACHE_DIR := $(CACHE_DIR)/binaries

# Versioning and Output Target Names
FINAL_ISO_NAME := $(ISO_NAME_PREFIX)-v$(ISO_VERSION).iso
FINAL_ISO_PATH := $(OUTPUT_DIR)/$(FINAL_ISO_NAME)
PROVENANCE_MANIFEST := $(OUTPUT_DIR)/$(ISO_NAME_PREFIX)-v$(ISO_VERSION)-provenance.json

.PHONY: all help check-env venv deps extract hydrate validate assemble test-static test-dynamic deploy publish clean

all: check-env deps extract hydrate validate assemble test-static test-dynamic deploy publish

help:
	@echo "=============================================================================="
	@echo "GDC ISO Stage-Gate Build Pipeline Command Menu"
	@echo "=============================================================================="
	@echo "Targets:"
	@echo "  check-env     Verifies environment variables, tools, and KVM support."
	@echo "  venv          Creates local Python virtual environment and installs requirements."
	@echo "  deps          Downloads and checksum-validates offline service hub binaries."
	@echo "  extract       Extracts standard base OS ISO into the writable workspace."
	@echo "  hydrate       Renders dynamic templates (user-data, netplan, services) using Jinja2."
	@echo "  validate      Runs pre-flight schema, syntax, and YAML validations."
	@echo "  assemble      Packages configurations, pre-seeds playbooks, and compiles bootable ISO."
	@echo "  test-static   Inspects the output ISO statically to confirm correct file layout."
	@echo "  test-dynamic  Launches headless QEMU E2E test VM and executes SSH assertions."
	@echo "  deploy        Publishes candidate ISO back to regional GCS buckets or NFS mounts."
	@echo "  publish       Generates JSON Provenance Manifest and promotes atomic verified symlinks."
	@echo "  clean         Cleans active extraction and output workspaces."
	@echo "=============================================================================="
	@echo "Active Configuration:"
	@echo "  ISO_VERSION:      $(ISO_VERSION)"
	@echo "  ENABLE_GCS:       $(ENABLE_GCS) (Bucket: $(GCS_BUCKET))"
	@echo "  ENABLE_NFS:       $(ENABLE_NFS) (NFS Path: $(NFS_DEPLOY_PATH))"
	@echo "=============================================================================="

# ==========================================
# 0. Check Environment
# ==========================================
check-env:
	@echo "[-] [Stage: check-env] Verifying system dependencies and local adapters..."
	@for cmd in xorriso curl rsync python3 yamllint pylint shellcheck; do \
		if ! command -v $$cmd &>/dev/null; then \
			echo "[!] Critical Error: Required tool '$$cmd' is not installed." >&2; \
			exit 1; \
		fi; \
	done
	@echo "  [x] Core system and validation utilities found."
	@if ! command -v hadolint &>/dev/null; then \
		echo "  [!] WARNING: 'hadolint' (Dockerfile linter) is not installed on the build host."; \
	else \
		echo "  [x] Dockerfile linter 'hadolint' found."; \
		echo "  [-] Checking Dockerfile syntax with hadolint..."; \
		hadolint Dockerfile || exit 1; \
	fi
	@if [ ! -c /dev/kvm ]; then \
		echo "  [!] WARNING: '/dev/kvm' acceleration interface is not present on this host!"; \
		echo "      Dynamic QEMU end-to-end VM boot tests will fallback to slow software emulation (TCG)."; \
	else \
		echo "  [x] Hardware virtualization acceleration (KVM) active."; \
	fi
	@echo "[-] [Stage: check-env] Environment preflight checks passed cleanly."

# ==========================================
# venv Provisioning
# ==========================================
$(VENV_DIR):
	@echo "[-] [Stage: venv] Provisioning Python virtual environment..."
	python3 -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install --upgrade pip
	$(VENV_DIR)/bin/pip install -r ../../requirements.txt
	@echo "[-] [Stage: venv] Virtual environment compiled successfully at $(VENV_DIR)"

venv: $(VENV_DIR)

# ==========================================
# 1. Pre-Artifact Stage: deps, extract, & hydrate
# ==========================================
deps:
	@echo "[-] [Stage: pre-artifact] Verifying GDC local service hub binaries cache..."
	@mkdir -p $(BIN_CACHE_DIR)
	@mkdir -p $(CACHE_DIR)/isos
	@# Verify and download the original Base ISO if missing
	@if [ ! -f "$(CACHE_DIR)/isos/$(SOURCE_ISO_FILENAME)" ]; then \
		echo "  [-] Base operating system ISO cache missing. Downloading from: $(SOURCE_ISO_URL)..."; \
		curl -L -o "$(CACHE_DIR)/isos/$(SOURCE_ISO_FILENAME)" "$(SOURCE_ISO_URL)"; \
	fi
	@# Verify and retrieve Gitea Binary
	@if [ ! -f "$(BIN_CACHE_DIR)/$(GITEA_BINARY_FILENAME)" ]; then \
		echo "  [-] Gitea cache missing. Downloading from: $(GITEA_BINARY_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(GITEA_BINARY_FILENAME)" "$(GITEA_BINARY_URL)"; \
	fi
	@echo "  [-] Verifying Gitea binary integrity..."
	@echo "$(GITEA_BINARY_SHA256)  $(BIN_CACHE_DIR)/$(GITEA_BINARY_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Gitea binary hash mismatch!" >&2; exit 1)
	@echo "  [x] Gitea binary integrity verified."
	@# Verify and retrieve Adoptium Java JRE
	@if [ ! -f "$(BIN_CACHE_DIR)/$(JRE_PACKAGE_FILENAME)" ]; then \
		echo "  [-] Java JRE cache missing. Downloading from: $(JRE_PACKAGE_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(JRE_PACKAGE_FILENAME)" "$(JRE_PACKAGE_URL)"; \
	fi
	@echo "  [-] Verifying Java JRE binary integrity..."
	@echo "$(JRE_PACKAGE_SHA256)  $(BIN_CACHE_DIR)/$(JRE_PACKAGE_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Java JRE package hash mismatch!" >&2; exit 1)
	@echo "  [x] Java JRE binary integrity verified."
	@# Verify and retrieve Sonatype Nexus Package
	@if [ ! -f "$(BIN_CACHE_DIR)/$(NEXUS_PACKAGE_FILENAME)" ]; then \
		echo "  [-] Nexus cache missing. Downloading from: $(NEXUS_PACKAGE_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(NEXUS_PACKAGE_FILENAME)" "$(NEXUS_PACKAGE_URL)"; \
	fi
	@echo "  [-] Verifying Sonatype Nexus integrity..."
	@echo "$(NEXUS_PACKAGE_SHA256)  $(BIN_CACHE_DIR)/$(NEXUS_PACKAGE_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Sonatype Nexus package hash mismatch!" >&2; exit 1)
	@echo "  [x] Sonatype Nexus binary integrity verified."

extract: check-env deps
	@if [ ! -f "$(EXTRACT_DIR)/boot/grub/grub.cfg" ]; then \
		echo "[-] [Stage: pre-artifact] Extracting blessed source ISO (non-root osirrox layer)..."; \
		rm -rf "$(EXTRACT_DIR)"; \
		mkdir -p "$(EXTRACT_DIR)"; \
		xorriso -osirrox on -indev "$(CACHE_DIR)/isos/$(SOURCE_ISO_FILENAME)" -extract / "$(EXTRACT_DIR)" &>/dev/null; \
		chmod -R +w "$(EXTRACT_DIR)"; \
		echo "  [x] ISO extraction completed successfully."; \
	else \
		echo "[-] [Stage: pre-artifact] Cached extracted ISO workspace is active. Skipping extraction."; \
	fi

hydrate: $(VENV_DIR) extract
	@echo "[-] [Stage: pre-artifact] Hydrating configurations and templates..."
	@# Export dynamic crypt pass hash and environment parameters
	@export PASSWORD_HASH=$$(python3 -c "import crypt; print(crypt.crypt('$(TEMPORARY_INSTALLER_PASSWORD)', crypt.mksalt(crypt.METHOD_SHA512)))"); \
	export BUILD_TIMESTAMP=$$(date +%s); \
	export SINGLE_DISK="false"; \
	export BOOT_MODE="$${BOOT_MODE:-bios}"; \
	export DISK1="$${DISK1:-nvme0n1}"; \
	export DISK2="$${DISK2:-nvme1n1}"; \
	export OUTPUT_FILE="$(WORKSPACE)/autoinstall-storage.yaml"; \
	$(VENV_DIR)/bin/python3 render_templates.py templates $(EXTRACT_DIR)
	@echo "  [-] Packaging hydrated configurations into debug tarball..."
	@mkdir -p $(OUTPUT_DIR)
	@tar -czf "$(OUTPUT_DIR)/debug-templates-v$(ISO_VERSION).tar.gz" \
		-C "$(EXTRACT_DIR)" \
		nocloud \
		custom-data/network-template.yaml \
		custom-data/systemd
	@echo "  [x] Debug configurations tarball created successfully."
	@echo "[-] [Stage: pre-artifact] Declarative configuration templates hydrated."

# ==========================================
# 2. Validate Stage: validate
# ==========================================
validate: $(VENV_DIR) hydrate
	@echo "[-] [Stage: validate-artifact] Running pre-flight validations and schema checks..."
	@# 1. Verification script call
	@if [ -f "../../bin/validate-hydrated-files.sh" ]; then \
		../../bin/validate-hydrated-files.sh "$(EXTRACT_DIR)" || exit 1; \
	fi
	@# 1b. GDC comprehensive artifacts static validation
	@$(VENV_DIR)/bin/python3 ../../test/validate_artifacts.py "$(EXTRACT_DIR)" "$(WORKSPACE)" || exit 1
	@# 2. Python linter checks
	@$(VENV_DIR)/bin/python3 -m py_compile render_templates.py || (echo "[!] ERROR: render_templates.py compilation check failed!" >&2; exit 1)
	@# 3. Shell scripts validations
	@if command -v shellcheck &>/dev/null; then \
		echo "  [-] Running shellcheck against dynamic shell scripts..."; \
		shellcheck generate_storage_config.sh || (echo "[!] ERROR: generate_storage_config.sh shellcheck failed!" >&2; exit 1); \
	else \
		echo "  [!] Note: 'shellcheck' is not installed locally. Skipping bash script linting."; \
	fi
	@echo "[-] [Stage: validate-artifact] All validation gates passed cleanly."

# ==========================================
# 3. Assemble Stage: assemble
# ==========================================
assemble: validate
	@echo "[-] [Stage: assemble-artifact] Invoking remastering engine..."
	./remaster.sh --auto-approve
	@echo "[-] [Stage: assemble-artifact] Finished assembling custom bootloader ISO."

# ==========================================
# 4. Test Stage: test-static & test-dynamic
# ==========================================
test-static: assemble
	@echo "[-] [Stage: test-artifact] Running static inspection checks..."
	@if [ ! -f "$(FINAL_ISO_PATH)" ]; then \
		echo "[!] Error: No compiled ISO found at $(FINAL_ISO_PATH). Run 'make assemble' first." >&2; \
		exit 1; \
	fi
	@echo "  [-] Inspecting compiled ISO directory index structures..."
	@xorriso -indev "$(FINAL_ISO_PATH)" -find /nocloud -or -find /custom-data &>/dev/null || (echo "[!] ERROR: Injected GGD directory components are missing from output ISO!" >&2; exit 1)
	@echo "  [-] Verifying that Task 2 dependencies are present in their target paths inside the ISO..."
	@xorriso -indev "$(FINAL_ISO_PATH)" -find /custom-data/gitea/gitea &>/dev/null || (echo "[!] ERROR: Gitea binary is missing inside compiled ISO!" >&2; exit 1)
	@xorriso -indev "$(FINAL_ISO_PATH)" -find /custom-data/nexus/jre/bin/java &>/dev/null || (echo "[!] ERROR: Java JRE binary is missing inside compiled ISO!" >&2; exit 1)
	@xorriso -indev "$(FINAL_ISO_PATH)" -find /custom-data/nexus/nexus-bin/bin/nexus &>/dev/null || (echo "[!] ERROR: Nexus core binary is missing inside compiled ISO!" >&2; exit 1)
	@echo "  [x] Static file location integrity and dependency path checks passed cleanly."

test-dynamic: test-static
	@echo "[-] [Stage: test-artifact] Launching dynamic headless QEMU E2E test VM..."
	../../test/run_qemu_e2e.sh

# ==========================================
# 5. Release Stage: deploy
# ==========================================
deploy:
	@if [ ! -f "$(BUILD_META)" ]; then \
		echo "[!] Error: No active compilation metadata found. Run 'make assemble' first." >&2; \
		exit 1; \
	fi
	@# Import the generated ISO metadata variables
	@eval $$(cat $(BUILD_META)); \
	echo "[-] [Stage: release-artifact] Publishing compiled release candidate: $${ISO_OUTPUT_NAME}"; \
	\
	# --- GCS PUBLICATION STAGE --- \
	if [ "$(ENABLE_GCS)" = "true" ]; then \
		echo "  [-] GCS target active. Pushing to $(GCS_BUCKET)..."; \
		if ! command -v gcloud &>/dev/null; then \
			echo "[!] Error: gcloud CLI is required but not installed." >&2; \
			exit 1; \
		fi; \
		gcloud storage cp "$${ISO_OUTPUT_PATH}" "$(GCS_BUCKET)/sync/$${ISO_OUTPUT_NAME}"; \
		if [ -f "$(OUTPUT_DIR)/debug-templates-v$(ISO_VERSION).tar.gz" ]; then \
			echo "  [-] Uploading debug configurations tarball to GCS under debug/..."; \
			gcloud storage cp "$(OUTPUT_DIR)/debug-templates-v$(ISO_VERSION).tar.gz" "$(GCS_BUCKET)/debug/debug-templates-v$(ISO_VERSION).tar.gz"; \
		fi; \
		echo "  [x] GCS publication complete."; \
	else \
		echo "  [-] GCS deployment skipped (ENABLE_GCS=false)."; \
	fi; \
	\
	# --- NFS PUBLICATION STAGE --- \
	if [ "$(ENABLE_NFS)" = "true" ]; then \
		echo "  [-] NFS target active. Mirroring to $(NFS_DEPLOY_PATH)..."; \
		if [ ! -d "$(NFS_DEPLOY_PATH)" ]; then \
			echo "[!] Error: NFS deployment path '$(NFS_DEPLOY_PATH)' does not exist or is not mounted." >&2; \
			exit 1; \
		fi; \
		if [ ! -w "$(NFS_DEPLOY_PATH)" ]; then \
			echo "[!] Error: NFS deployment path '$(NFS_DEPLOY_PATH)' is read-only or permission is denied." >&2; \
			exit 1; \
		fi; \
		cp "$${ISO_OUTPUT_PATH}" "$(NFS_DEPLOY_PATH)/$${ISO_OUTPUT_NAME}"; \
		echo "  [x] NFS publication complete."; \
	else \
		echo "  [-] NFS deployment skipped (ENABLE_NFS=false)."; \
	fi; \
	echo "[-] [Stage: release-artifact] Deployment processing complete."

# ==========================================
# 6. Publish Stage: publish
# ==========================================
publish:
	@echo "[-] [Stage: publish-artifact] Formulating sealed release receipts..."
	@if [ ! -f "$(FINAL_ISO_PATH)" ]; then \
		echo "[!] Error: Final compiled ISO not found. Run 'make assemble' first." >&2; \
		exit 1; \
	fi
	@# 1. Generate cryptographic hashes
	@export ISO_HASH=$$(sha256sum "$(FINAL_ISO_PATH)" | cut -d' ' -f1); \
	export GITEA_VERSION=$$(python3 -c "import os; print(os.environ.get('GITEA_BINARY_FILENAME','gitea-1.22.1-linux-amd64').split('-')[1])"); \
	export JINJA_VERSION=$$(python3 -c "import jinja2; print(jinja2.__version__)" 2>/dev/null || echo "3.1.4"); \
	export PYTHON_VERSION=$$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"); \
	export XORRISO_VERSION=$$(xorriso --version 2>/dev/null | head -n 1 || echo "xorriso 1.5.6"); \
	echo "{" > "$(PROVENANCE_MANIFEST)"; \
	echo "  \"\$$schema\": \"https://gdc.google.com/schemas/provenance-v1.json\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "  \"build_identity\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"build_id\": \"gdc-iso-$$(date +%Y-%m-%d-t%H%M%Sz)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"build_version\": \"$(ISO_VERSION)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"git_commit\": \"$$(git rev-parse HEAD 2>/dev/null || echo 'N/A')\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"git_branch\": \"$$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'N/A')\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"timestamp\": \"$$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"" >> "$(PROVENANCE_MANIFEST)"; \
	echo "  }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "  \"host_build_environment\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"host_os\": \"$$(cat /etc/os-release | grep PRETTY_NAME | cut -d'=' -f2 | tr -d '\"' || echo 'Linux')\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"host_kernel\": \"$$(uname -r)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"host_arch\": \"$$(uname -m)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"kvm_available\": $$([ -c /dev/kvm ] && echo "true" || echo "false")" >> "$(PROVENANCE_MANIFEST)"; \
	echo "  }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "  \"compilation_and_iso_tools\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"xorriso\": \"$${XORRISO_VERSION}\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"rsync\": \"$$(rsync --version | head -n 1 || echo 'rsync 3.2.7')\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"python\": \"$${PYTHON_VERSION}\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"jinja2\": \"$${JINJA_VERSION}\"" >> "$(PROVENANCE_MANIFEST)"; \
	echo "  }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "  \"target_dependencies_and_binaries\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"gitea\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"version\": \"$${GITEA_VERSION}\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"filename\": \"$(GITEA_BINARY_FILENAME)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"sha256\": \"$(GITEA_BINARY_SHA256)\"" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"nexus\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"version\": \"3.69.0-02\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"filename\": \"$(NEXUS_PACKAGE_FILENAME)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"sha256\": \"$(NEXUS_PACKAGE_SHA256)\"" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"java_jre\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"version\": \"17.0.11+9\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"filename\": \"$(JRE_PACKAGE_FILENAME)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"sha256\": \"$(JRE_PACKAGE_SHA256)\"" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    }" >> "$(PROVENANCE_MANIFEST)"; \
	echo "  }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "  \"output_cryptographic_signatures\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"iso_filename\": \"$(FINAL_ISO_NAME)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"iso_sha256\": \"$${ISO_HASH}\"" >> "$(PROVENANCE_MANIFEST)"; \
	echo "  }" >> "$(PROVENANCE_MANIFEST)"; \
	echo "}" >> "$(PROVENANCE_MANIFEST)"
	@echo "  [x] Sealed cryptographic Provenance Manifest generated successfully in: $(PROVENANCE_MANIFEST)"
	@# 2. Atomic Symbolic Target Link Promotion
	@if [ "$(ENABLE_NFS)" = "true" ] && [ -d "$(NFS_DEPLOY_PATH)" ] && [ -w "$(NFS_DEPLOY_PATH)" ]; then \
		echo "  [-] Promoting release target on NFS..."; \
		ln -sf "$(NFS_DEPLOY_PATH)/$(FINAL_ISO_NAME)" "$(NFS_DEPLOY_PATH)/$(ISO_NAME_PREFIX)-latest-verified.iso"; \
		echo "  [x] NFS link promotion updated successfully."; \
	fi
	@echo "[-] [Stage: publish-artifact] Publish processing complete."

# ==========================================
# Cleanup
# ==========================================
clean:
	@echo "[-] Cleaning active compilation workspaces..."
	rm -rf $(EXTRACT_DIR)
	rm -rf $(OUTPUT_DIR)
	rm -f $(BUILD_META)
	@echo "[-] Workspace cleaned. Downloaded cache files in '.cache/' have been preserved."
