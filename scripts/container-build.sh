#!/bin/bash
set -euo pipefail
key=$1
mode=$2
jobs=$3
debug_cfg=${4:-0}
localversion=${5:--linux-lab}
kbuild_user=${6:-builder}
kbuild_host=${7:-apple-container}
opt_kconfigs=${8:-}
req_kconfigs=${9:-}

mkdir -p "/work/$key/src" "/work/$key/out" /work/ccache
src="/work/$key/src"
out="/work/$key/out"
if [[ $mode == working ]]; then
  # Work on a copy, including local edits, without writing into the checkout.
  rsync -a --delete --exclude=.git --exclude=.config --exclude=.config.old \
    --exclude=include/config --exclude=include/generated \
    /checkout/ "$src/"
else
  if [[ ! -f "$src/.lab-snapshot-ready" ]]; then
    tar -xf /artifacts/source.tar -C "$src"
    touch "$src/.lab-snapshot-ready"
  fi
fi

cp /artifacts/requested.config "$out/requested.config"
enabled_optional=$(python3 - "$src" "$opt_kconfigs" <<'KCONFIG'
import pathlib, re, sys
symbols = set()
for path in pathlib.Path(sys.argv[1]).rglob('Kconfig*'):
    if path.is_file():
        symbols.update(re.findall(r'^\s*(?:menu)?config\s+([A-Z0-9_]+)\s*$', path.read_text(errors='replace'), re.M))
print(' '.join(name for name in sys.argv[2].split() if name in symbols))
KCONFIG
)
for sym in $enabled_optional; do
  printf 'CONFIG_%s=y\n' "$sym" >> "$out/requested.config"
done

export CCACHE_DIR=/work/ccache
export CCACHE_BASEDIR="$src"
export CCACHE_MAXSIZE=5G
export KBUILD_BUILD_USER="$kbuild_user"
export KBUILD_BUILD_HOST="$kbuild_host"
args=(-C "$src" O="$out" ARCH=arm64 'CC=ccache gcc' "LOCALVERSION=$localversion")
if [[ ! -f "$out/.config" ]] || ! cmp -s "$out/requested.config" "$out/applied.config"; then
  make "${args[@]}" KCONFIG_ALLCONFIG="$out/requested.config" allnoconfig
  cp "$out/requested.config" "$out/applied.config"
else
  make "${args[@]}" olddefconfig
fi

required="PERF_EVENTS KUNIT KUNIT_AUTORUN_ENABLED KUNIT_DEBUGFS TRACING VIRTIO_BLK EXT4_FS SERIAL_AMBA_PL011_CONSOLE NETWORK_FILESYSTEMS NET_9P NET_9P_VIRTIO 9P_FS $req_kconfigs $enabled_optional"
if [[ $debug_cfg == 1 ]]; then
  required="$required PROVE_LOCKING DEBUG_ATOMIC_SLEEP DEBUG_INFO"
fi
for symbol in $required; do
  grep -qx "CONFIG_${symbol}=y" "$out/.config" || {
    echo "Required CONFIG_${symbol}=y missing after Kconfig resolution" >&2; exit 1;
  }
done

make "${args[@]}" -j"$jobs" Image
cp "$out/arch/arm64/boot/Image" /artifacts/Image.new
cp "$out/.config" /artifacts/config.new
cp "$out/System.map" /artifacts/System.map.new
make -s "${args[@]}" kernelrelease > /artifacts/kernelrelease.new
if [[ $debug_cfg == 1 ]]; then
  cp "$out/vmlinux" /artifacts/vmlinux.new
fi
for artifact in Image config System.map kernelrelease; do
  mv "/artifacts/$artifact.new" "/artifacts/$artifact"
done
if [[ $debug_cfg == 1 ]]; then
  mv /artifacts/vmlinux.new /artifacts/vmlinux
else
  rm -f /artifacts/vmlinux /artifacts/vmlinux.new
fi
tar -cf /artifacts/source.tar.new -C "$src" .
mv /artifacts/source.tar.new /artifacts/source.tar
echo 'Kernel built successfully.'
