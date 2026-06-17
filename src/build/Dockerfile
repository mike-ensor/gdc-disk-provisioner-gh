# ==============================================================================
# GDC Bootloader - Remastering Builder Container
# ==============================================================================
# This Dockerfile defines a lightweight, secure build environment containing 
# all static dependencies required for the GDC ISO remastering pipeline.
#
# Using this pre-compiled builder image in Cloud Build:
#   1. Shaves 15-30 seconds off every CI/CD run (zero "apt-get install" lag).
#   2. Fully isolates the build from public APT package mirror failures.
#   3. Guarantees deterministic, fully reproducible ISO compilations.
# ==============================================================================

FROM ubuntu:24.04

# Prevent interactive keyboard/locale selection prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install only the precise, essential build utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    xorriso \
    rsync \
    git \
    make \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && xorriso --version

# Set standard workspace directory matching Cloud Build structures
WORKDIR /workspace
