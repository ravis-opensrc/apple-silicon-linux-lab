#!/usr/bin/env python3
# Own the lifetime of a container CLI or QEMU child, including timeout cleanup.
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log')
    parser.add_argument('--timeout', type=float)
    parser.add_argument('--container-name')
    parser.add_argument('--guest-state')
    parser.add_argument('--manifest')
    parser.add_argument('--gdb-port', type=int, default=0)
    parser.add_argument('--ssh-port', type=int, default=0)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('Missing child command')
    received = 0
    process = None

    def interrupted(number, _frame):
        nonlocal received
        received = number
        if process and process.poll() is None:
            process.terminate()

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    log = open(args.log, 'wb') if args.log else None
    process = subprocess.Popen(command, stdout=subprocess.PIPE if log else None,
                               stderr=subprocess.STDOUT if log else None)
    copier = None
    if log:
        def copy_output():
            for block in iter(lambda: process.stdout.read1(65536), b''):
                log.write(block); log.flush()
                try:
                    sys.stdout.buffer.write(block); sys.stdout.buffer.flush()
                except BrokenPipeError:
                    pass
        copier = threading.Thread(target=copy_output, daemon=True)
        copier.start()
    record = Path(args.guest_state) if args.guest_state else None
    if record:
        data = json.loads(Path(args.manifest).read_text())
        data.update(pid=process.pid, gdb_port=args.gdb_port, ssh_port=args.ssh_port)
        temporary = record.with_name('guest.json.new')
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        os.replace(temporary, record)
    status = 1
    try:
        status = process.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f'Command exceeded {args.timeout:g} seconds; stopping it.', file=sys.stderr)
        received = 0
        status = 124
        process.terminate()
    finally:
        if received or process.poll() is None:
            if args.container_name:
                subprocess.run(['container', 'stop', '--time', '10', args.container_name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        if copier:
            copier.join(timeout=5)
        if log:
            log.close()
        if record and record.exists():
            current = json.loads(record.read_text())
            if current.get('pid') == process.pid:
                record.unlink()
    return 128 + received if received else (status if status >= 0 else 128 - status)


if __name__ == '__main__':
    raise SystemExit(main())
