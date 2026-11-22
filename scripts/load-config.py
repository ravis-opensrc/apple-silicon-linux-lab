#!/usr/bin/env python3
"""Minimal zero-dependency YAML loader for apple-silicon-linux-lab.

Parses two-level mappings and string lists from config.yaml using only the
Python standard library (no PyYAML required on macOS) and emits shell-safe
LAB_* variable assignments.
"""

import os
import json
import pathlib
import shlex
import subprocess
import sys


def strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx]
    return line


def parse_scalar(raw: str) -> str:
    val = raw.strip()
    if len(val) >= 2 and ((val[0] == val[-1] == '"') or (val[0] == val[-1] == "'")):
        return val[1:-1]
    return val


def load_simple_yaml(path: pathlib.Path) -> dict:
    data: dict = {}
    if not path.is_file():
        return data
    section = None
    list_key = None
    for raw_line in path.read_text().splitlines():
        line = strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1].strip()
            data.setdefault(section, {})
            list_key = None
        elif indent > 0 and stripped.startswith("- "):
            if section is None or list_key is None:
                continue
            item = parse_scalar(stripped[2:])
            if item:
                data[section].setdefault(list_key, []).append(item)
        elif indent > 0 and ":" in stripped:
            if section is None:
                continue
            key, rest = stripped.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            if rest == "" or rest == "[]":
                data[section][key] = []
                list_key = key
            else:
                data[section][key] = parse_scalar(rest)
                list_key = None
    return data


def expand_path(val: str) -> str:
    if not val:
        return ""
    return os.path.expanduser(os.path.expandvars(val))


def detect_ncpu() -> str:
    try:
        out = subprocess.check_output(["sysctl", "-n", "hw.ncpu"], text=True).strip()
        if out.isdigit() and int(out) > 0:
            return out
    except Exception:
        pass
    return str(os.cpu_count() or 4)


def main() -> None:
    lab_dir = pathlib.Path(sys.argv[1]).resolve()
    cfg_candidates = []
    if os.environ.get("LINUX_LAB_CONFIG"):
        explicit = pathlib.Path(expand_path(os.environ["LINUX_LAB_CONFIG"]))
        if not explicit.is_file():
            raise SystemExit(f"Configuration file not found: {explicit}")
        cfg_candidates.append(explicit)
    cfg_candidates.append(lab_dir / "config.yaml")
    cfg_candidates.append(pathlib.Path.home() / ".config" / "linux-lab" / "config.yaml")

    cfg_path = next((p for p in cfg_candidates if p.is_file()), None)
    cfg = load_simple_yaml(cfg_path) if cfg_path else {}

    def get_val(sec: str, key: str, default: str = "") -> str:
        v = cfg.get(sec, {}).get(key, default)
        if isinstance(v, list):
            return " ".join(v)
        return str(v) if v is not None else default

    def get_list(sec: str, key: str, default: list) -> list:
        v = cfg.get(sec, {}).get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            return v.split()
        return default

    source_path = expand_path(
        os.environ.get("LINUX_SOURCE") or get_val("source", "path", "")
    )
    sparsebundle = expand_path(get_val("source", "sparsebundle", ""))
    mountpoint = expand_path(get_val("source", "mountpoint", ""))

    state_dir = expand_path(
        os.environ.get("LINUX_LAB_STATE") or get_val("state", "dir", "")
    ) or str(lab_dir / ".state")

    jobs = os.environ.get("LINUX_BUILD_JOBS") or get_val("build", "jobs", "0")
    if not str(jobs).isdigit() or int(jobs) <= 0:
        jobs = detect_ncpu()

    memory = os.environ.get("LINUX_BUILD_MEMORY") or get_val("build", "memory", "8G")
    localversion = os.environ.get("LINUX_LOCALVERSION") or get_val("build", "localversion", "-linux-lab")
    kbuild_user = os.environ.get("KBUILD_BUILD_USER") or get_val("build", "kbuild_user", "") or os.environ.get("USER", "builder")
    kbuild_host = os.environ.get("KBUILD_BUILD_HOST") or get_val("build", "kbuild_host", "apple-container")

    image = os.environ.get("LINUX_LAB_IMAGE") or get_val("container", "image", "local/linux-lab-builder:debian13-v1")
    volume = os.environ.get("LINUX_LAB_VOLUME") or get_val("container", "volume", "linux-lab-work")

    fragments = get_list("kernel", "fragments", ["configs/base.config"])
    opt_kconfigs = get_list("kernel", "optional_kconfigs", [])
    req_kconfigs = get_list("kernel", "required_kconfigs", [])

    vm_hostname = os.environ.get("LINUX_VM_HOSTNAME") or get_val("vm", "hostname", "linux-lab")
    vm_cpus = os.environ.get("LINUX_VM_CPUS") or get_val("vm", "cpus", "4")
    vm_memory = os.environ.get("LINUX_VM_MEMORY") or get_val("vm", "memory", "4G")
    vm_accel = os.environ.get("LINUX_QEMU_ACCEL") or get_val("vm", "accel", "hvf")
    ssh_port = os.environ.get("LINUX_SSH_PORT") or get_val("vm", "ssh_port", "2222")
    gdb_port = os.environ.get("LINUX_GDB_PORT") or get_val("vm", "gdb_port", "1234")
    rootfs_name = os.environ.get("LINUX_ROOTFS_NAME") or get_val("vm", "rootfs_name", "alpine-3.24.4-lab-v6.raw")
    extra_args = os.environ.get("LINUX_KERNEL_ARGS") or get_val("vm", "extra_kernel_args", "")
    smoke_paths = get_list("vm", "smoke_check_paths", [])
    smoke_kunit = get_val("vm", "smoke_kunit_pattern", "# Subtest:")

    exports = {
        "LAB_CONFIG_FILE": str(cfg_path) if cfg_path else "",
        "LAB_SOURCE": source_path,
        "LAB_SPARSEBUNDLE": sparsebundle,
        "LAB_MOUNTPOINT": mountpoint,
        "LAB_STATE": state_dir,
        "LAB_IMAGE": image,
        "LAB_VOLUME": volume,
        "LAB_JOBS": str(jobs),
        "LAB_MEMORY": memory,
        "LAB_LOCALVERSION": localversion,
        "LAB_KBUILD_USER": kbuild_user,
        "LAB_KBUILD_HOST": kbuild_host,
        "LAB_CONFIG_FRAGMENTS_JSON": json.dumps(fragments),
        "LAB_SNAPSHOT_DIR": expand_path(os.environ.get("LINUX_LAB_SNAPSHOTS") or get_val("source", "snapshots_dir", "")) or str(pathlib.Path(source_path).parent / ".linux-lab-sources"),
        "LAB_OPTIONAL_KCONFIGS": " ".join(opt_kconfigs),
        "LAB_REQUIRED_KCONFIGS": " ".join(req_kconfigs),
        "LAB_VM_HOSTNAME": vm_hostname,
        "LAB_VM_CPUS": str(vm_cpus),
        "LAB_VM_MEMORY": vm_memory,
        "LAB_VM_ACCEL": vm_accel,
        "LAB_SSH_PORT": str(ssh_port),
        "LAB_GDB_PORT": str(gdb_port),
        "LAB_ROOTFS_NAME": rootfs_name,
        "LAB_EXTRA_KERNEL_ARGS": extra_args,
        "LAB_SMOKE_CHECK_PATHS": ",".join(smoke_paths),
        "LAB_SMOKE_KUNIT_PATTERN": smoke_kunit,
        "LAB_SMOKE_TIMEOUT": os.environ.get("LINUX_SMOKE_TIMEOUT") or get_val("vm", "smoke_timeout", "180"),
    }
    for k, v in exports.items():
        print(f"{k}={shlex.quote(v)}")


if __name__ == "__main__":
    main()
