#!/bin/bash
export PATH="$PATH:/opt/homebrew/bin:/opt/homebrew/sbin"
LAB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LAB_SETTINGS=$(python3 "$LAB_DIR/scripts/load-config.py" "$LAB_DIR") || return 1
eval "$LAB_SETTINGS"
unset LAB_SETTINGS

die() { echo "$*" >&2; exit 1; }
require_tool() { command -v "$1" >/dev/null || die "Missing $1; install with: brew install container qemu"; }
if [[ -n "${LAB_SPARSEBUNDLE:-}" && -n "${LAB_MOUNTPOINT:-}" && -n "${LAB_SOURCE:-}" ]]; then
  if [[ ! -d "$LAB_SOURCE" && -e "$LAB_SPARSEBUNDLE" ]] && ! mount | grep -Fq "on $LAB_MOUNTPOINT "; then
    mkdir -p "$LAB_MOUNTPOINT"
    /usr/bin/hdiutil attach "$LAB_SPARSEBUNDLE" -mountpoint "$LAB_MOUNTPOINT" -quiet || die 'Could not mount source volume.'
  fi
fi
mkdir -p "$LAB_STATE/builds"
require_source() {
  [[ -n "${LAB_SOURCE:-}" && -d "$LAB_SOURCE" ]] || die 'Set source.path to an existing kernel checkout.'
}
acquire_lock() {
  local lockdir=$1 msg=$2 pid=""
  if ! mkdir "$lockdir" 2>/dev/null; then
    [[ ! -f "$lockdir/pid" ]] || pid=$(cat "$lockdir/pid")
    case "$pid" in ''|*[!0-9]*) die "$msg (lock: $lockdir)." ;; esac
    if kill -0 "$pid" 2>/dev/null; then die "$msg (lock: $lockdir)."; fi
    rm -f "$lockdir/pid"
    rmdir "$lockdir" || die "Cannot reclaim $lockdir."
    mkdir "$lockdir" || die "$msg (lock: $lockdir)."
  fi
  printf '%s\n' "$$" > "$lockdir/pid"
}
release_lock() {
  rm -f "$1/pid"
  rmdir "$1" 2>/dev/null || true
}
LAB_CHILD_PID=""
install_lifecycle() {
  LAB_LOCK=$1
  trap 'release_lock "$LAB_LOCK"' EXIT
  trap 'stop_owned 130' INT
  trap 'stop_owned 143' TERM
  trap 'stop_owned 129' HUP
}
stop_owned() {
  trap '' INT TERM HUP
  if [[ -n "$LAB_CHILD_PID" ]]; then
    kill -TERM "$LAB_CHILD_PID" 2>/dev/null || true
    wait "$LAB_CHILD_PID" 2>/dev/null || true
  fi
  exit "$1"
}
run_owned() {
  local status=0
  "$@" <&0 &
  LAB_CHILD_PID=$!
  printf '%s\n' "$LAB_CHILD_PID" > "$LAB_LOCK/pid"
  wait "$LAB_CHILD_PID" || status=$?
  LAB_CHILD_PID=""
  printf '%s\n' "$$" > "$LAB_LOCK/pid"
  return "$status"
}
resolve_build() {
  local ref=$1
  require_source
  if [[ $ref == current ]]; then
    LAB_KEY=working; LAB_MODE=working
    LAB_COMMIT=$(git -C "$LAB_SOURCE" rev-parse HEAD)
  else
    LAB_COMMIT=$(git -C "$LAB_SOURCE" rev-parse --verify "$ref^{commit}")
    LAB_KEY="ref-${LAB_COMMIT:0:12}"; LAB_MODE=ref
  fi
  LAB_GROUP="$LAB_STATE/builds/$LAB_KEY"
}
select_artifacts() {
  local settings
  settings=$(python3 "$LAB_DIR/scripts/lab-state.py" select "$LAB_STATE" "${1:-}") || die "No usable build generation; run build-linux for this ref."
  eval "$settings"
}
