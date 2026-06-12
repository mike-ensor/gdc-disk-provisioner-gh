# ==============================================================================
# GDC Bootloader ISO Build & Deployment Orchestrator
# ==============================================================================
# Controls the rapid compilation of offline-first GDC bootable ISOs
# and orchestrates automated publishing to Google Cloud Storage (GCS) and NFS.
# ==============================================================================

# Default Shell configuration
SHELL := /usr/bin/env bash

# Load Environment Configuration
ENV_FILE := build.env
ifneq ("$(wildcard $(ENV_FILE))","")
    include $(ENV_FILE)
    export $(shell sed 's/=.*//' $(ENV_FILE))
endif

# Internal Paths
WORKSPACE := ../../build-workspace
BUILD_META := $(WORKSPACE)/build_meta.env

.PHONY: all help build deploy clean

all: build deploy

help:
	@echo "=============================================================================="
	@echo "GDC ISO Build Pipeline Command Menu"
	@echo "=============================================================================="
	@echo "Targets:"
	@echo "  build         Downloads original base ISO, customizes bootloader, injects "
	@echo "                autoinstall configs, and outputs a custom bootable GDC ISO."
	@echo "  deploy        Publishes the compiled versioned ISO to the configured target"
	@echo "                destinations (GCS and/or NFS) as defined in build.env."
	@echo "  all           Runs 'build' and then automatically triggers 'deploy'."
	@echo "  clean         Cleans extraction and output workspaces (retains downloaded caches)."
	@echo "=============================================================================="
	@echo "Active Configuration in build.env:"
	@echo "  ISO_VERSION:      $(ISO_VERSION)"
	@echo "  ENABLE_GCS:       $(ENABLE_GCS) (Bucket: $(GCS_BUCKET))"
	@echo "  ENABLE_NFS:       $(ENABLE_NFS) (NFS Path: $(NFS_DEPLOY_PATH))"
	@echo "=============================================================================="

build:
	@echo "[-] Launching GDC ISO Remastering Engine..."
	./remaster.sh

deploy:
	@if [ ! -f "$(BUILD_META)" ]; then \
		echo "[!] Error: No active compilation metadata found. Run 'make build' first." >&2; \
		exit 1; \
	fi
	@# Import the generated ISO metadata variables
	@eval $$(cat $(BUILD_META)); \
	echo "[-] Beginning publication phase for: $${ISO_OUTPUT_NAME}"; \
	\
	# --- GCS PUBLICATION STAGE --- \
	if [ "$(ENABLE_GCS)" = "true" ]; then \
		echo "[-] GCS target active. Pushing to $(GCS_BUCKET)..."; \
		if ! command -v gcloud &>/dev/null; then \
			echo "[!] Error: gcloud CLI is required but not installed." >&2; \
			exit 1; \
		fi; \
		gcloud storage cp "$${ISO_OUTPUT_PATH}" "$(GCS_BUCKET)/$${ISO_OUTPUT_NAME}"; \
		echo "[-] GCS publication complete."; \
	else \
		echo "[-] GCS deployment skipped (ENABLE_GCS=false)."; \
	fi; \
	\
	# --- NFS PUBLICATION STAGE --- \
	if [ "$(ENABLE_NFS)" = "true" ]; then \
		echo "[-] NFS target active. Mirroring to $(NFS_DEPLOY_PATH)..."; \
		if [ ! -d "$(NFS_DEPLOY_PATH)" ]; then \
			echo "[!] Error: NFS deployment path '$(NFS_DEPLOY_PATH)' does not exist or is not mounted." >&2; \
			exit 1; \
		fi; \
		if [ ! -w "$(NFS_DEPLOY_PATH)" ]; then \
			echo "[!] Error: NFS deployment path '$(NFS_DEPLOY_PATH)' is read-only or permission is denied." >&2; \
			exit 1; \
		fi; \
		cp "$${ISO_OUTPUT_PATH}" "$(NFS_DEPLOY_PATH)/$${ISO_OUTPUT_NAME}"; \
		echo "[-] NFS publication complete."; \
	else \
		echo "[-] NFS deployment skipped (ENABLE_NFS=false)."; \
	fi; \
	echo "[-] Deployment processing finished successfully."

clean:
	@echo "[-] Cleaning active workspace..."
	rm -rf $(WORKSPACE)/custom-iso
	rm -rf $(WORKSPACE)/output
	rm -f $(WORKSPACE)/build_meta.env
	@echo "[-] Workspace cleaned. Downloaded cache files in '.cache/' have been preserved."
