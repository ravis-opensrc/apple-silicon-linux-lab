#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends build-essential bc bison flex \
  libssl-dev libelf-dev cpio rsync kmod python3 ccache curl ca-certificates \
  e2fsprogs xz-utils zstd git
apt-get clean
rm -rf /var/lib/apt/lists/*
