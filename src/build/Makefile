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
DEPENDENCY_CACHE_GCS_BUCKET := $(call get_env,DEPENDENCY_CACHE_GCS_BUCKET)
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

GCLOUD_SDK_FILENAME := $(call get_env,GCLOUD_SDK_FILENAME)
GCLOUD_SDK_SHA256 := $(call get_env,GCLOUD_SDK_SHA256)
GCLOUD_SDK_URL := $(call get_env,GCLOUD_SDK_URL)

STEP_CLI_FILENAME := $(call get_env,STEP_CLI_FILENAME)
STEP_CLI_SHA256 := $(call get_env,STEP_CLI_SHA256)
STEP_CLI_URL := $(call get_env,STEP_CLI_URL)

TEMPORARY_INSTALLER_PASSWORD := $(call get_env,TEMPORARY_INSTALLER_PASSWORD)
DEBUG_EXTRA_USER := $(call get_env,DEBUG_EXTRA_USER)
DEBUG_EXTRA_PASSWORD := $(call get_env,DEBUG_EXTRA_PASSWORD)
GDC_COMPANION := $(call get_env,GDC_COMPANION)
GCLOUD_PRESENT := $(shell command -v gcloud &>/dev/null && echo "true" || echo "false")
ANSIBLE_PLAYBOOK_HOME := $(call get_env,ANSIBLE_PLAYBOOK_HOME)
GDC_RELEASE_USER_NAME := $(call get_env,GDC_RELEASE_USER_NAME)
GDC_RELEASE_USER_EMAIL := $(call get_env,GDC_RELEASE_USER_EMAIL)

# Internal Paths and Workspace Definitions
WORKSPACE := ../../build-workspace
EXTRACT_DIR := $(WORKSPACE)/custom-iso
OUTPUT_DIR := $(WORKSPACE)/output
BUILD_META := $(WORKSPACE)/build_meta.env
VENV_DIR := ../../.venv
CACHE_DIR := ../../.cache
BIN_CACHE_DIR := $(CACHE_DIR)/binaries

# Timing and Stage Duration Logs
TIME_LOG := $(WORKSPACE)/stage_times.env
START_TIME = @mkdir -p $(WORKSPACE) && echo "START_$(1)=$$(date +%s)" >> $(TIME_LOG)
END_TIME = @echo "END_$(1)=$$(date +%s)" >> $(TIME_LOG)

# Versioning and Output Target Names
ifeq ($(GDC_COMPANION),false)
  COMPANION_SUFFIX := -no-comp
else ifeq ($(GDC_COMPANION),FALSE)
  COMPANION_SUFFIX := -no-comp
else ifeq ($(GDC_COMPANION),0)
  COMPANION_SUFFIX := -no-comp
else ifeq ($(GDC_COMPANION),no)
  COMPANION_SUFFIX := -no-comp
else ifeq ($(GDC_COMPANION),NO)
  COMPANION_SUFFIX := -no-comp
else
  COMPANION_SUFFIX :=
endif

ifeq ($(GDC_DEBUG_MODE),true)
FINAL_ISO_NAME := $(ISO_NAME_PREFIX)-v$(ISO_VERSION)$(COMPANION_SUFFIX)-debug.iso
else
FINAL_ISO_NAME := $(ISO_NAME_PREFIX)-v$(ISO_VERSION)$(COMPANION_SUFFIX).iso
endif
FINAL_ISO_PATH := $(OUTPUT_DIR)/$(FINAL_ISO_NAME)
PROVENANCE_MANIFEST := $(OUTPUT_DIR)/$(ISO_NAME_PREFIX)-v$(ISO_VERSION)-provenance.json

.PHONY: all help check-env venv deps pull-customer-deps extract-customer-deps apply-customer-deps extract hydrate validate assemble test-unit test-static test-dynamic deploy publish reports clean

all: check-env deps pull-customer-deps extract-customer-deps apply-customer-deps extract hydrate validate assemble test-static test-dynamic deploy publish reports

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
	$(call START_TIME,check-env)
	@echo "[-] [Stage: check-env] Verifying system dependencies and local adapters..."
	@for cmd in xorriso curl rsync python3 yamllint pylint shellcheck; do \
		if ! command -v $$cmd &>/dev/null; then \
			echo "[!] Critical Error: Required tool '$$cmd' is not installed." >&2; \
			exit 1; \
			$(call END_TIME,check-env); \
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
	$(call END_TIME,check-env)

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
	$(call START_TIME,deps)
	@echo "[-] [Stage: pre-artifact] Verifying GDC local service hub binaries cache..."
	@mkdir -p $(BIN_CACHE_DIR)
	@mkdir -p $(CACHE_DIR)/isos
	@# GCS Pull Cache Phase
	@if [ "$(ENABLE_GCS)" = "true" ] && [ "$(GCLOUD_PRESENT)" = "true" ]; then \
		echo "  [-] GCS cache active. Pulling artifacts from $(DEPENDENCY_CACHE_GCS_BUCKET)..."; \
		BUCKET_NAME=$$(echo "$(DEPENDENCY_CACHE_GCS_BUCKET)" | sed 's/^gs:\/\///'); \
		if [ -n "$$BUCKET_NAME" ]; then \
			for file in "$(SOURCE_ISO_FILENAME)" "gdc-collector" "$(GITEA_BINARY_FILENAME)" "$(JRE_PACKAGE_FILENAME)" "$(NEXUS_PACKAGE_FILENAME)" "$(GCLOUD_SDK_FILENAME)" "$(STEP_CLI_FILENAME)"; do \
				if [ "$$file" = "$(SOURCE_ISO_FILENAME)" ]; then \
					local_path="$(CACHE_DIR)/isos/$$file"; \
					gcs_path="gs://$$BUCKET_NAME/source/$$file"; \
				else \
					local_path="$(BIN_CACHE_DIR)/$$file"; \
					gcs_path="gs://$$BUCKET_NAME/binaries/$$file"; \
				fi; \
				if [ ! -f "$$local_path" ]; then \
					echo "    [-] Checking GCS for $$file..."; \
					if gcloud storage objects describe "$$gcs_path" &>/dev/null; then \
						echo "    [x] Downloading $$file from GCS..."; \
						gcloud storage cp "$$gcs_path" "$$local_path"; \
						python3 -c "import json, os; f='$(CACHE_DIR)/binary_sources.json'; d=json.load(open(f)) if os.path.exists(f) else {}; d['$$file']='GCS Cache'; json.dump(d, open(f, 'w'))" 2>/dev/null; \
					else \
						echo "    [-] $$file not found in GCS. Will download from public mirror."; \
					fi; \
				fi; \
			done; \
		fi; \
	fi
	@# 1. Base OS ISO
	@if [ ! -f "$(CACHE_DIR)/isos/$(SOURCE_ISO_FILENAME)" ]; then \
		echo "  [-] Base operating system ISO cache missing. Downloading from: $(SOURCE_ISO_URL)..."; \
		curl -L -o "$(CACHE_DIR)/isos/$(SOURCE_ISO_FILENAME)" "$(SOURCE_ISO_URL)"; \
		python3 -c "import json, os; f='$(CACHE_DIR)/binary_sources.json'; d=json.load(open(f)) if os.path.exists(f) else {}; d['$(SOURCE_ISO_FILENAME)']='Upstream Network'; json.dump(d, open(f, 'w'))" 2>/dev/null; \
	fi
	@# 2. Gitea Binary
	@if [ ! -f "$(BIN_CACHE_DIR)/$(GITEA_BINARY_FILENAME)" ]; then \
		echo "  [-] Gitea cache missing. Downloading from: $(GITEA_BINARY_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(GITEA_BINARY_FILENAME)" "$(GITEA_BINARY_URL)"; \
		python3 -c "import json, os; f='$(CACHE_DIR)/binary_sources.json'; d=json.load(open(f)) if os.path.exists(f) else {}; d['$(GITEA_BINARY_FILENAME)']='Upstream Network'; json.dump(d, open(f, 'w'))" 2>/dev/null; \
	fi
	@echo "  [-] Verifying Gitea binary integrity..."
	@echo "$(GITEA_BINARY_SHA256)  $(BIN_CACHE_DIR)/$(GITEA_BINARY_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Gitea binary hash mismatch!" >&2; exit 1)
	@echo "  [x] Gitea binary integrity verified."
	@# 3. Java JRE
	@if [ ! -f "$(BIN_CACHE_DIR)/$(JRE_PACKAGE_FILENAME)" ]; then \
		echo "  [-] Java JRE cache missing. Downloading from: $(JRE_PACKAGE_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(JRE_PACKAGE_FILENAME)" "$(JRE_PACKAGE_URL)"; \
		python3 -c "import json, os; f='$(CACHE_DIR)/binary_sources.json'; d=json.load(open(f)) if os.path.exists(f) else {}; d['$(JRE_PACKAGE_FILENAME)']='Upstream Network'; json.dump(d, open(f, 'w'))" 2>/dev/null; \
	fi
	@echo "  [-] Verifying Java JRE binary integrity..."
	@echo "$(JRE_PACKAGE_SHA256)  $(BIN_CACHE_DIR)/$(JRE_PACKAGE_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Java JRE package hash mismatch!" >&2; exit 1)
	@echo "  [x] Java JRE binary integrity verified."
	@# 4. Sonatype Nexus
	@if [ ! -f "$(BIN_CACHE_DIR)/$(NEXUS_PACKAGE_FILENAME)" ]; then \
		echo "  [-] Nexus cache missing. Downloading from: $(NEXUS_PACKAGE_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(NEXUS_PACKAGE_FILENAME)" "$(NEXUS_PACKAGE_URL)"; \
		python3 -c "import json, os; f='$(CACHE_DIR)/binary_sources.json'; d=json.load(open(f)) if os.path.exists(f) else {}; d['$(NEXUS_PACKAGE_FILENAME)']='Upstream Network'; json.dump(d, open(f, 'w'))" 2>/dev/null; \
	fi
	@echo "  [-] Verifying Sonatype Nexus integrity..."
	@echo "$(NEXUS_PACKAGE_SHA256)  $(BIN_CACHE_DIR)/$(NEXUS_PACKAGE_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Sonatype Nexus package hash mismatch!" >&2; exit 1)
	@echo "  [x] Sonatype Nexus binary integrity verified."
	@# 5. Google Cloud SDK
	@if [ ! -f "$(BIN_CACHE_DIR)/$(GCLOUD_SDK_FILENAME)" ]; then \
		echo "  [-] Google Cloud SDK cache missing. Downloading from: $(GCLOUD_SDK_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(GCLOUD_SDK_FILENAME)" "$(GCLOUD_SDK_URL)"; \
		python3 -c "import json, os; f='$(CACHE_DIR)/binary_sources.json'; d=json.load(open(f)) if os.path.exists(f) else {}; d['$(GCLOUD_SDK_FILENAME)']='Upstream Network'; json.dump(d, open(f, 'w'))" 2>/dev/null; \
	fi
	@echo "  [-] Verifying Google Cloud SDK integrity..."
	@echo "$(GCLOUD_SDK_SHA256)  $(BIN_CACHE_DIR)/$(GCLOUD_SDK_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Google Cloud SDK package hash mismatch!" >&2; exit 1)
	@echo "  [x] Google Cloud SDK binary integrity verified."
	@# 6. Smallstep CLI
	@if [ ! -f "$(BIN_CACHE_DIR)/$(STEP_CLI_FILENAME)" ]; then \
		echo "  [-] Smallstep CLI cache missing. Downloading from: $(STEP_CLI_URL)..."; \
		curl -L -o "$(BIN_CACHE_DIR)/$(STEP_CLI_FILENAME)" "$(STEP_CLI_URL)"; \
		python3 -c "import json, os; f='$(CACHE_DIR)/binary_sources.json'; d=json.load(open(f)) if os.path.exists(f) else {}; d['$(STEP_CLI_FILENAME)']='Upstream Network'; json.dump(d, open(f, 'w'))" 2>/dev/null; \
	fi
	@echo "  [-] Verifying Smallstep CLI integrity..."
	@echo "$(STEP_CLI_SHA256)  $(BIN_CACHE_DIR)/$(STEP_CLI_FILENAME)" | sha256sum --check --status || (echo "[!] ERROR: Smallstep CLI package hash mismatch!" >&2; exit 1)
	@echo "  [x] Smallstep CLI binary integrity verified."
	@# GCS Seed Cache Phase
	@if [ "$(ENABLE_GCS)" = "true" ] && [ "$(GCLOUD_PRESENT)" = "true" ]; then \
		echo "  [-] Synchronizing verified local cache back to GCS..."; \
		BUCKET_NAME=$$(echo "$(DEPENDENCY_CACHE_GCS_BUCKET)" | sed 's/^gs:\/\///'); \
		if [ -n "$$BUCKET_NAME" ]; then \
			for file in "gdc-collector" "$(GITEA_BINARY_FILENAME)" "$(JRE_PACKAGE_FILENAME)" "$(NEXUS_PACKAGE_FILENAME)" "$(GCLOUD_SDK_FILENAME)" "$(STEP_CLI_FILENAME)"; do \
				local_path="$(BIN_CACHE_DIR)/$$file"; \
				gcs_path="gs://$$BUCKET_NAME/binaries/$$file"; \
				if [ -f "$$local_path" ]; then \
					if ! gcloud storage objects describe "$$gcs_path" &>/dev/null; then \
						echo "    [-] Seeding $$file back to GCS cache..."; \
						gcloud storage cp "$$local_path" "$$gcs_path"; \
					fi; \
				fi; \
			done; \
			local_iso="$(CACHE_DIR)/isos/$(SOURCE_ISO_FILENAME)"; \
			gcs_iso="gs://$$BUCKET_NAME/source/$(SOURCE_ISO_FILENAME)"; \
			if [ -f "$$local_iso" ] && ! gcloud storage objects describe "$$gcs_iso" &>/dev/null; then \
				echo "    [-] Seeding base ISO back to GCS source..."; \
				gcloud storage cp "$$local_iso" "$$gcs_iso"; \
			fi; \
		fi; \
	fi
	$(call END_TIME,deps)

CUSTOMER_STAGING := $(WORKSPACE)/customer-staging
CUSTOMER_CACHE_DIR := $(CACHE_DIR)/customer
CUSTOMER_ASSETS_TARBALL := $(CUSTOMER_CACHE_DIR)/customer-assets.tar.gz

pull-customer-deps:
	$(call START_TIME,pull-customer-deps)
	@echo "[-] [Stage: pull-customer-deps] Checking for customer supplied assets..."
	@mkdir -p $(CUSTOMER_CACHE_DIR)
	@if [ -n "$(_CUSTOMER_ASSETS_URI)" ]; then \
		echo "  [-] Found _CUSTOMER_ASSETS_URI: $(_CUSTOMER_ASSETS_URI)"; \
		if [[ "$(_CUSTOMER_ASSETS_URI)" =~ ^gs:// ]]; then \
			echo "  [-] Downloading customer assets from GCS..."; \
			gcloud storage cp "$(_CUSTOMER_ASSETS_URI)" "$(CUSTOMER_ASSETS_TARBALL)"; \
		elif [[ "$(_CUSTOMER_ASSETS_URI)" =~ ^https?:// ]]; then \
			echo "  [-] Downloading customer assets from HTTPS..."; \
			curl -f -L -o "$(CUSTOMER_ASSETS_TARBALL)" "$(_CUSTOMER_ASSETS_URI)"; \
		else \
			echo "  [-] Copying local customer assets..."; \
			cp "$(_CUSTOMER_ASSETS_URI)" "$(CUSTOMER_ASSETS_TARBALL)"; \
		fi; \
		echo "  [x] Customer assets downloaded successfully."; \
	else \
		echo "  [-] No custom assets URI specified. Skipping customer pull."; \
	fi
	$(call END_TIME,pull-customer-deps)

extract-customer-deps: pull-customer-deps
	$(call START_TIME,extract-customer-deps)
	@echo "[-] [Stage: extract-customer-deps] Extracting customer supplied binaries..."
	@if [ -f "$(CUSTOMER_ASSETS_TARBALL)" ]; then \
		rm -rf "$(CUSTOMER_STAGING)"; \
		mkdir -p "$(CUSTOMER_STAGING)"; \
		echo "  [-] Unpacking $(CUSTOMER_ASSETS_TARBALL) to staging..."; \
		tar -xzf "$(CUSTOMER_ASSETS_TARBALL)" -C "$(CUSTOMER_STAGING)"; \
		echo "  [x] Extraction complete."; \
	else \
		echo "  [-] No customer tarball found. Skipping extraction."; \
	fi
	$(call END_TIME,extract-customer-deps)

apply-customer-deps: extract-customer-deps
	$(call START_TIME,apply-customer-deps)
	@echo "[-] [Stage: apply-customer-deps] Applying customer supplied assets to ISO cache..."
	@if [ -d "$(CUSTOMER_STAGING)" ]; then \
		echo "  [-] Scanning $(CUSTOMER_STAGING) for .deb packages..."; \
		mkdir -p $(CACHE_DIR)/packages; \
		find "$(CUSTOMER_STAGING)" -name "*.deb" -exec cp {} "$(CACHE_DIR)/packages/" \;; \
		echo "  [x] Customer packages applied successfully."; \
	else \
		echo "  [-] No staging directory found. Skipping apply."; \
	fi
	$(call END_TIME,apply-customer-deps)

extract: check-env deps apply-customer-deps
	$(call START_TIME,extract)
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
	$(call END_TIME,extract)

hydrate: $(VENV_DIR) extract
	$(call START_TIME,hydrate)
	@echo "[-] [Stage: pre-artifact] Hydrating configurations and templates..."
	@# Export dynamic crypt pass hash and environment parameters
	@export PASSWORD_HASH=$$(python3 -c "import crypt; print(crypt.crypt('$(TEMPORARY_INSTALLER_PASSWORD)', crypt.mksalt(crypt.METHOD_SHA512)))"); \
	export BUILD_TIMESTAMP=$$(date +%s); \
	export SINGLE_DISK="$${SINGLE_DISK:-true}"; \
	export BOOT_MODE="$${BOOT_MODE:-bios}"; \
	export DISK1="$${DISK1:-nvme0n1}"; \
	export DISK2="$${DISK2:-nvme1n1}"; \
	export GDC_COMPANION="$${GDC_COMPANION:-TRUE}"; \
	export DEBUG_EXTRA_USER="$(DEBUG_EXTRA_USER)"; \
	export DEBUG_EXTRA_PASSWORD="$(DEBUG_EXTRA_PASSWORD)"; \
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
	$(call END_TIME,hydrate)

# ==========================================
# 2. Validate Stage: validate
# ==========================================
validate: $(VENV_DIR) hydrate
	$(call START_TIME,validate)
	@echo "[-] [Stage: validate-artifact] Running pre-flight validations and schema checks..."
	@# 1. Verification script call
	@if [ -f "../../test/bin/validate-hydrated-files.sh" ]; then \
		../../test/bin/validate-hydrated-files.sh "$(EXTRACT_DIR)" || exit 1; \
	fi
	@# 1b. GDC comprehensive artifacts static validation
	@$(VENV_DIR)/bin/python3 ../../test/validate_artifacts.py "$(EXTRACT_DIR)" "$(WORKSPACE)" || exit 1
	@# 1c. GDC template hydration unit tests
	@$(VENV_DIR)/bin/python3 ../../test/test_template_hydration.py || (echo "[!] ERROR: Template hydration unit tests failed!" >&2; exit 1)
	@# 1d. GDC core build script unit tests
	@$(VENV_DIR)/bin/python3 ../../test/test_gdc_build_scripts.py || (echo "[!] ERROR: Build script unit tests failed!" >&2; exit 1)
	@# 2. Python linter checks
	@$(VENV_DIR)/bin/python3 -m py_compile render_templates.py || (echo "[!] ERROR: render_templates.py compilation check failed!" >&2; exit 1)
	@$(VENV_DIR)/bin/python3 -m py_compile configure_netplan.py || (echo "[!] ERROR: configure_netplan.py compilation check failed!" >&2; exit 1)
	@# 3. Shell scripts validations
	@if command -v shellcheck &>/dev/null; then \
		echo "  [-] Running shellcheck against dynamic shell scripts..."; \
		shellcheck generate_storage_config.sh || (echo "[!] ERROR: generate_storage_config.sh shellcheck failed!" >&2; exit 1); \
	else \
		echo "  [!] Note: 'shellcheck' is not installed locally. Skipping bash script linting."; \
	fi
	@echo "[-] [Stage: validate-artifact] All validation gates passed cleanly."
	$(call END_TIME,validate)

# ==========================================
# 3. Assemble Stage: assemble
# ==========================================
assemble: validate
	$(call START_TIME,assemble)
	@echo "[-] [Stage: assemble-artifact] Invoking remastering engine..."
	./remaster.sh --auto-approve
	@echo "[-] [Stage: assemble-artifact] Finished assembling custom bootloader ISO."
	$(call END_TIME,assemble)

# ==========================================
# 4. Test Stage: test-unit, test-static & test-dynamic
# ==========================================
test-unit: $(VENV_DIR)
	@echo "[-] Running GDC template hydration unit tests..."
	@$(VENV_DIR)/bin/python3 ../../test/test_template_hydration.py
	@echo "[-] Running GDC build script unit tests..."
	@$(VENV_DIR)/bin/python3 ../../test/test_gdc_build_scripts.py

test-static: assemble
	$(call START_TIME,test-static)
	@$(VENV_DIR)/bin/python3 ../../test/bin/run_all_tests.py
	$(call END_TIME,test-static)

test-dynamic: test-static
	$(call START_TIME,test-dynamic)
	@echo "[-] [Stage: test-artifact] Launching dynamic headless QEMU E2E test VM..."
	../../test/run_qemu_e2e.sh
	$(call END_TIME,test-dynamic)

# ==========================================
# 5. Release Stage: deploy
# ==========================================
deploy:
	$(call START_TIME,deploy)
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
		gcloud config set storage/parallel_composite_upload_enabled False; \
		gcloud storage cp "$${ISO_OUTPUT_PATH}" "$(GCS_BUCKET)/sync/$${ISO_OUTPUT_NAME}"; \
		if [ -f "$(OUTPUT_DIR)/debug-templates-v$(ISO_VERSION).tar.gz" ]; then \
			echo "  [-] Uploading debug configurations tarball to GCS under debug/..."; \
			gcloud storage cp "$(OUTPUT_DIR)/debug-templates-v$(ISO_VERSION).tar.gz" "$(GCS_BUCKET)/debug/debug-templates-v$(ISO_VERSION).tar.gz"; \
		fi; \
		echo "  [-] Verifying GCS upload integrity..."; \
		REMOTE_SIZE=$$(gcloud storage objects describe "$(GCS_BUCKET)/sync/$${ISO_OUTPUT_NAME}" --format="value(size)" 2>/dev/null || echo "0"); \
		LOCAL_SIZE=$$(stat -c %s "$${ISO_OUTPUT_PATH}" 2>/dev/null || stat -f %z "$${ISO_OUTPUT_PATH}" 2>/dev/null || echo "-1"); \
		if [ "$$REMOTE_SIZE" -eq 0 ] || [ "$$REMOTE_SIZE" -ne "$$LOCAL_SIZE" ]; then \
			echo "[!] CRITICAL ERROR: GCS Upload Verification Failed!" >&2; \
			echo "    Remote size ($$REMOTE_SIZE) does not match local size ($$LOCAL_SIZE)." >&2; \
			exit 1; \
		fi; \
		echo "  [x] GCS upload integrity verified successfully."; \
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
	$(call END_TIME,deploy)

# ==========================================
# 6. Publish Stage: publish
# ==========================================
publish:
	$(call START_TIME,publish)
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
	echo "    }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"google_cloud_sdk\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"version\": \"575.0.0\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"filename\": \"$(GCLOUD_SDK_FILENAME)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"sha256\": \"$(GCLOUD_SDK_SHA256)\"" >> "$(PROVENANCE_MANIFEST)"; \
	echo "    }," >> "$(PROVENANCE_MANIFEST)"; \
	echo "    \"step_cli\": {" >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"version\": \"0.26.1\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"filename\": \"$(STEP_CLI_FILENAME)\"," >> "$(PROVENANCE_MANIFEST)"; \
	echo "      \"sha256\": \"$(STEP_CLI_SHA256)\"" >> "$(PROVENANCE_MANIFEST)"; \
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
	$(call END_TIME,publish)

# ==========================================
# 7. Reports Stage: reports
# ==========================================
reports:
	$(call START_TIME,reports)
	@echo "[-] [Stage: compile-reports] Compiling canonical reports..."
	@python3 ../../test/bin/generate_build_report.py \
		--local \
		--iso-version "$(ISO_VERSION)" \
		--status "SUCCESS" \
		--gcs-bucket "$(GCS_BUCKET)" \
		--upload
	$(call END_TIME,reports)

# ==========================================
# Cleanup
# ==========================================
clean:
	@echo "[-] Cleaning active compilation workspaces..."
	rm -rf $(EXTRACT_DIR)
	rm -rf $(OUTPUT_DIR)
	rm -f $(BUILD_META)
	@echo "[-] Workspace cleaned. Downloaded cache files in '.cache/' have been preserved."
