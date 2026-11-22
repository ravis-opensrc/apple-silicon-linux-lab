# Apple Silicon Linux Kernel Lab

Fast, self-contained tooling to **build, boot, test (KUnit & selftests), and
step-debug** upstream Linux arm64 kernels on Apple Silicon Macs using Apple's
native `container` CLI and QEMU (`hvf` hardware acceleration).

Your kernel Git checkout is mounted **read-only** into the builder. Each
successful build exports a matching source snapshot, which the QEMU guest
mounts read-only at `/mnt/src` via `9p`. The lab never switches your branch or
writes build artifacts into the checkout.

## Features

- **Native arm64 builds via Apple `container` + `ccache`**: Debian 13 builder
  with persistent sparse build volume (`64 GiB`) and shared `ccache`.
- **Instant QEMU `virt` boot with HVF**: Boots Alpine arm64 in seconds with
  per-build `qcow2` overlays, auto-run KUnit, `cgroup2`, `debugfs`, `tracefs`,
  read-only matching build source at `/mnt/src`, and passwordless SSH.
- **Modular Kconfig fragments**: Base minimal `arm64` QEMU config
  (`configs/base.config`) plus optional subsystem fragments (e.g.,
  `configs/damon.config`) and debug overlay (`configs/debug.config`).
- **On-demand Lockdep & GDB/LLDB step debugging**: `build-linux --debug`
  enables Lockdep, `DEBUG_ATOMIC_SLEEP`, DWARF symbols, and exports `vmlinux`;
  `launch-linux --gdb` / `--gdb-wait` + `launch-linux --attach-gdb` attach
  `aarch64-elf-gdb` or macOS `lldb` with automatic source-path mapping.
- **Private local configuration**: All machine-specific paths live in a
  gitignored `config.yaml` (zero hardcoded paths in tracked files).

## Prerequisites

```bash
brew install container qemu
container system kernel set --recommended
```

For GDB kernel debugging, macOS `lldb` works out of the box; optionally install
`brew install aarch64-elf-gdb` for GNU GDB + Linux `vmlinux-gdb.py` helpers.

## Setup

```bash
git clone https://github.com/ravis-opensrc/apple-silicon-linux-lab.git
cd apple-silicon-linux-lab

# 1. Install wrappers into ~/.local/bin and create config.yaml
./scripts/install.sh

# 2. Edit config.yaml and set source.path to your Linux kernel checkout
$EDITOR config.yaml

# 3. Provision the Debian builder image and Alpine arm64 rootfs (one-time)
setup-linux-lab
```

*(Alternatively, `source ./aliases.sh` from `~/.zshrc` or `~/.bashrc`.)*

## Daily Workflow

```bash
# Build current working tree (including uncommitted edits)
build-linux

# Build a specific Git ref/commit without switching your checkout
build-linux origin/master

# Boot the most recent build (interactive serial console)
launch-linux

# Connect over SSH from a second terminal
launch-linux --ssh

# Automated boot + KUnit + smoke check (exits non-zero on failure)
launch-linux --smoke
```

Inside the guest, `/mnt/src` contains the exact source snapshot used by that
build, including local edits for a working-tree build. Run shell selftests from
their own directory so relative helpers resolve:

```sh
cd /mnt/src/tools/testing/selftests/damon
./sysfs.sh
```

Selftests that need compiled binaries must be built/staged separately into
writable guest storage; a read-only source mount is not an installed selftest
suite.

Exit the guest shell (or run `poweroff -f`) to shut down. QEMU's escape key is
**Ctrl-a, then x**.

## Lockdep & Step Debugging (GDB / LLDB)

```bash
# 1. Build with Lockdep, DEBUG_ATOMIC_SLEEP, DWARF debug info, and vmlinux
build-linux --debug

# 2. Terminal 1: launch QEMU with gdbstub (127.0.0.1:1234) and nokaslr
launch-linux --gdb             # boot immediately, attach anytime
launch-linux --gdb-wait        # pause at CPU reset for early-boot/KUnit breakpoints

# 3. Terminal 2: attach to the running VM and its matching source snapshot
launch-linux --attach-gdb
```

*(Tip: if you need deterministic early-boot single-stepping or hardware
watchpoints on arm64, run `LINUX_QEMU_ACCEL=tcg launch-linux --gdb-wait`.)*

## Configuration (`config.yaml`)

See [`config.yaml.example`](config.yaml.example) for all available options:

- `source.path`: Path to your Linux kernel Git checkout.
- `source.sparsebundle` / `source.mountpoint`: Optional macOS case-sensitive
  sparsebundle auto-mount (useful on default case-insensitive APFS volumes).
- `kernel.fragments`: List of Kconfig fragments merged into `allnoconfig`.
- `kernel.optional_kconfigs`: Symbols automatically enabled if defined in the
  target tree's `Kconfig` files.
- `kernel.required_kconfigs`: Symbols verified to be `=y` after resolution.
- `vm.*`: vCPUs, memory, accelerator (`hvf` / `tcg`), SSH/GDB ports, and
  `--smoke` check paths.

Precedence: **CLI flags** > **Environment variables** (`LINUX_SOURCE`,
`LINUX_BUILD_JOBS`, `LINUX_VM_CPUS`, `LINUX_VM_MEMORY`, `LINUX_QEMU_ACCEL`,
`LINUX_SSH_PORT`, `LINUX_GDB_PORT`, `LINUX_DEBUG_CONFIG`, `LINUX_KERNEL_ARGS`,
`LINUX_LAB_CONFIG`) > **`config.yaml`** > **Built-in defaults**.

## License

Licensed under the [GNU General Public License v3.0](LICENSE).

## Build generations and source provenance

Each successful build creates `.state/builds/<key>/runs/<generation>/` with
`Image`, resolved `config`, `System.map`, optional debug `vmlinux`, logs and a
`manifest.json`. `build-linux` atomically publishes that generation as the
latest only after compilation and source export both succeed. Older generations
are retained. An existing legacy build without a manifest must be rebuilt once.

Source snapshots default to `<source.path parent>/.linux-lab-sources/`, beside
the kernel checkout on its case-sensitive filesystem. Override this with
`source.snapshots_dir` or `LINUX_LAB_SNAPSHOTS`; the destination must also be
case-sensitive and outside the kernel checkout. Snapshots consume roughly one source-tree copy per build and
are retained with their generation. Do not edit or remove snapshots, build
artifacts or backing images while a VM/debugger uses them. Cleanup is manual.

The guest root disk remains persistent per build key and base-image version,
so rebuilding `current` does not discard installed guest tools. Existing disks
are preserved; the updated smoke init uses a new `lab-v6` base image.

`.state/guest.json` records the live QEMU PID, generation, matching source and
GDB port. `--attach-gdb` uses this record, even if a newer build has completed.
An optional ref argument must match the running guest. Debug symbols/source
from a different build are never selected via `last-build`.

Absolute and space-containing fragment paths are supported: fragments are
staged into the artifact directory before the container starts. Do not edit
the checkout while it is being copied for a working-tree build.

## Smoke checks and regression tests

`launch-linux --smoke` verifies the guest status, configured KUnit output, and
actual `9p`, `cgroup2`, `debugfs` and `tracefs` mounts. It defaults to a 180-second
wall-clock deadline. Set `vm.smoke_timeout` or `LINUX_SMOKE_TIMEOUT` to change it;
a timeout stops QEMU and returns status **124**. `--gdb-wait` cannot be combined
with `--smoke`. Set `vm.smoke_kunit_pattern: ""` to omit the KUnit-presence check;
reported KUnit failures still fail the smoke test.

Signal handlers stop/wait for owned children before releasing locks. If a build
container is interrupted, the lab requests its shutdown as well as terminating
the CLI. No other containers are stopped.

Run host regression tests without containers, a kernel build or a VM:

```sh
python3 -B -m unittest discover -s tests -v
bash -n bin/* scripts/*.sh
sh -n scripts/guest-init.sh
```

The mocked workflow tests cover source provenance, running-VM symbol selection,
absolute/spaced fragments, explicit empty config values, failed KUnit checks,
smoke deadlines and interrupted-container cleanup. GitHub Actions runs them on
pull requests and pushes. Real HVF/SSH/kernel checks still require an Apple
Silicon Mac.
