#!/usr/bin/env bash

# Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0

set -x

pkill -f qemu-system-x86_64 || true
pkill -f swtpm || true
rm -rf /tmp/gdc-swtpm/ /tmp/gdc-qemu-*.qcow2 /tmp/gdc-qemu-serial.log

mkdir -p /tmp/gdc-swtpm/
swtpm socket --tpmstate dir=/tmp/gdc-swtpm/ --tpm2 --ctrl type=unixio,path=/tmp/gdc-swtpm/swtpm-sock --daemon

qemu-img create -f qcow2 /tmp/gdc-qemu-sys.qcow2 250G
qemu-img create -f qcow2 /tmp/gdc-qemu-data.qcow2 350G

qemu-system-x86_64 \
  -enable-kvm \
  -m 4096 \
  -smp 4 \
  -drive file=/tmp/gdc-qemu-sys.qcow2,if=virtio,cache=writeback \
  -drive file=/tmp/gdc-qemu-data.qcow2,if=virtio,cache=writeback \
  -cdrom .cache/isos/gdc-bootstrap-ubuntu-24.04-v0.1.124-debug.iso \
  -boot d \
  -nographic \
  -serial file:/tmp/gdc-qemu-serial.log \
  -netdev user,id=mgmtnet,net=192.168.120.0/24,hostfwd=tcp:127.0.0.1:2222-:22 \
  -device virtio-net-pci,netdev=mgmtnet \
  -chardev socket,id=chrtpm,path=/tmp/gdc-swtpm/swtpm-sock \
  -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0 \
  &> /tmp/qemu-stderr.log &
disown
