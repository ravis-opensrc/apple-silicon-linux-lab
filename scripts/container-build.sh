#!/bin/bash
set -euo pipefail
key=$1
mode=$2
jobs=$3
debug_cfg=${4:-0}
localversion=${5:--linux-lab}
kbuild_user=${6:-builder}
kbuild_host=${7:-apple-container}
fragments=${8:-configs/base.config}
opt_kconfigs=${9:-}
req_kconfigs=${10:-}

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

: > "$out/requested.config"
for frag in $fragments; do
  if [[ $frag == /* ]]; then
    frag_path=$frag
  else
    frag_path="/lab/$frag"
  fi
  [[ -f "$frag_path" ]] || { echo "Missing Kconfig fragment: $frag_path" >&2; exit 1; }
  cat "$frag_path" >> "$out/requested.config"
  printf '\n' >> "$out/requested.config"
done

enabled_optional=""
for sym in $opt_kconfigs; do
  if find "$src" -name Kconfig -exec grep -q "^config ${sym}$" {} + 2>/dev/null; then
    echo "CONFIG_${sym}=y" >> "$out/requested.config"
    enabled_optional="$enabled_optional $sym"
  fi
done

if [[ $debug_cfg == 1 ]]; then
  cat /lab/configs/debug.config >> "$out/requested.config"
  printf '\n' >> "$out/requested.config"
fi

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
echo 'Kernel built successfully.'
