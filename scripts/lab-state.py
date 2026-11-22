#!/usr/bin/env python3
# Host-side build provenance, fragment staging and atomic publication.
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys


def emit(values):
    for key, value in values.items():
        print(f'{key}={shlex.quote(str(value))}')


def atomic_json(path, value):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temporary, path)


def main():
    command, *args = sys.argv[1:]
    if command == 'validate-snapshots':
        source, snapshots = (Path(value).resolve() for value in args)
        if snapshots == source or source in snapshots.parents:
            raise SystemExit('Source snapshots must be outside the kernel checkout.')
    elif command == 'stage':
        lab, artifact, fragments, debug = args
        chunks = []
        for filename in json.loads(fragments):
            source = Path(os.path.expandvars(filename)).expanduser()
            if not source.is_absolute():
                source = Path(lab) / source
            chunks.append(source.read_text())
        if debug == '1':
            chunks.append((Path(lab) / 'configs/debug.config').read_text())
        (Path(artifact) / 'requested.config').write_text('\n'.join(chunks) + '\n')
    elif command == 'publish':
        state, artifact, key, commit, source, debug = args
        artifact = Path(artifact).resolve()
        manifest = {'version': 1, 'key': key, 'commit': commit,
                    'artifacts': str(artifact), 'source': str(Path(source).resolve()),
                    'container_source': f'/work/{key}/src', 'debug': debug == '1',
                    'config_sha256': hashlib.sha256((artifact / 'config').read_bytes()).hexdigest()}
        atomic_json(artifact / 'manifest.json', manifest)
        latest = artifact.parent.parent / 'latest'
        temporary = latest.with_name('latest.new')
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(artifact)
        os.replace(temporary, latest)
        last = Path(state) / 'last-build'
        temp = last.with_name('last-build.new')
        temp.write_text(str(artifact) + '\n')
        os.replace(temp, last)
    elif command == 'select':
        state, key = args
        candidate = (Path(state) / 'builds' / key / 'latest') if key else Path((Path(state) / 'last-build').read_text().strip())
        manifest = json.loads((candidate / 'manifest.json').read_text())
        emit({'LAB_ARTIFACTS': manifest['artifacts'], 'LAB_KEY': manifest['key'],
              'LAB_BUILD_SOURCE': manifest['source'], 'LAB_CONTAINER_SOURCE': manifest['container_source']})
    elif command == 'active':
        state = Path(args[0])
        record = json.loads((state / 'guest.json').read_text())
        os.kill(record['pid'], 0)
        if not record['gdb_port']:
            raise SystemExit('The running VM was not launched with --gdb or --gdb-wait.')
        emit({'LAB_ARTIFACTS': record['artifacts'], 'LAB_KEY': record['key'],
              'LAB_BUILD_SOURCE': record['source'], 'LAB_CONTAINER_SOURCE': record['container_source'],
              'LAB_ACTIVE_GDB_PORT': record['gdb_port']})
    else:
        raise SystemExit(f'Unknown operation: {command}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f'Lab state unavailable: {error}. Rebuild the selected ref if necessary.')
