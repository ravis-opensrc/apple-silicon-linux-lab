#!/bin/bash
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
LAB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

eval "$(python3 "$LAB_DIR/scripts/load-config.py" "$LAB_DIR")"

die() { echo "$*" >&2; exit 1; }
require_tool() { command -v "$1" >/dev/null || die "Missing $1; install with: brew install container qemu"; }

# Optional macOS case-sensitive sparsebundle auto-mount (configured via config.yaml)
if [[ -n "${LAB_SPARSEBUNDLE:-}" && -n "${LAB_MOUNTPOINT:-}" && -n "${LAB_SOURCE:-}" ]]; then
  if [[ ! -d "$LAB_SOURCE" && -e "$LAB_SPARSEBUNDLE" ]] && ! mount | grep -q "on $LAB_MOUNTPOINT "; then
    mkdir -p "$LAB_MOUNTPOINT"
    /usr/bin/hdiutil attach "$LAB_SPARSEBUNDLE" -mountpoint "$LAB_MOUNTPOINT" -quiet >/dev/null 2>&1 || true
  fi
fi

mkdir -p "$LAB_STATE/builds"

require_source() {
  [[ -n "${LAB_SOURCE:-}" ]] || die "No kernel source configured. Copy $LAB_DIR/config.yaml.example to $LAB_DIR/config.yaml and set source.path (or pass LINUX_SOURCE)."
  [[ -d "$LAB_SOURCE" ]] || die "Kernel source directory not found: $LAB_SOURCE"
}

acquire_lock() {
  local lockdir=$1
  local msg=$2
  if ! mkdir "$lockdir" 2>/dev/null; then
    local pid=""
    [[ -f "$lockdir/pid" ]] && pid=$(cat "$lockdir/pid" 2>/dev/null || true)
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      rm -rf "$lockdir"
      mkdir "$lockdir" 2>/dev/null || die "$msg (lock: $lockdir)."
    else
      die "$msg (lock: $lockdir)."
    fi
  fi
  printf '%s\n' "$$" > "$lockdir/pid"
}

release_lock() {
  local lockdir=$1
  rm -f "$lockdir/pid"
  rmdir "$lockdir" 2>/dev/null || true
}

resolve_build() {
  local ref=$1
  require_source
  if [[ $ref == current ]]; then
    LAB_KEY=working
    LAB_MODE=working
    LAB_COMMIT=$(git -C "$LAB_SOURCE" rev-parse HEAD)
  else
    LAB_COMMIT=$(git -C "$LAB_SOURCE" rev-parse --verify "$ref^{commit}")
    LAB_KEY="ref-${LAB_COMMIT:0:12}"
    LAB_MODE=ref
  fi
  LAB_ARTIFACTS="$LAB_STATE/builds/$LAB_KEY"
}
