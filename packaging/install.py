#!/usr/bin/env python3
"""Install a private offline bundle in a user prefix, with menu and CLI launchers."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import uuid

MARKER = "# Managed by BeamFix user installer"


def desktop_quote(value):
    # Desktop Entry Exec quoting is different from shell quoting.
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def write_atomic(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.beamfix-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or later is required.')
    if os.geteuid() == 0:
        parser.error('Run as your desktop user, without sudo.')
    prefix = args.prefix.expanduser().resolve()
    root = prefix / 'share/beamfix'
    manifest = root / 'installation.json'
    paths = [prefix / 'bin/beamfix', prefix / 'bin/beamfix-gui', prefix / 'share/applications/beamfix.desktop']
    # Refuse to overwrite unrelated commands, desktop entries, or symbolic links.
    for path in paths:
        if path.is_symlink() or (path.exists() and MARKER not in path.read_text()):
            parser.error(f'Refusing to replace an unrelated file: {path}')
    previous = None
    if manifest.exists():
        previous = json.loads(manifest.read_text()).get('bundle')
        if not isinstance(previous, str) or '/' in previous or not previous.startswith('app-'):
            parser.error('Invalid installation manifest; leave it in place and inspect it manually.')
    if args.uninstall:
        if not previous:
            parser.error('No managed BeamFix installation was found at this prefix.')
        for path in paths:
            path.unlink(missing_ok=True)
        bundle = root / previous
        if bundle.is_dir() and not bundle.is_symlink():
            shutil.rmtree(bundle)
        manifest.unlink()
        print('Removed the managed launchers, menu entry and application bundle. Saved reports are untouched.')
        return
    source = Path(__file__).resolve().parent
    if not (source / 'beamfix/cli.py').is_file():
        parser.error('Run install.py from the extracted BeamFix portable bundle.')
    root.mkdir(parents=True, exist_ok=True)
    name = 'app-' + uuid.uuid4().hex
    bundle = root / name
    bundle.mkdir()
    shutil.copytree(source / 'beamfix', bundle / 'beamfix', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(source / 'launch.py', bundle / 'launch.py')
    command = shlex.quote(sys.executable) + ' ' + shlex.quote(str(bundle / 'launch.py'))
    write_atomic(paths[0], '#!/bin/sh\n' + MARKER + '\nexec ' + command + ' "$@"\n', 0o755)
    write_atomic(paths[1], '#!/bin/sh\n' + MARKER + '\nexec ' + command + ' gui "$@"\n', 0o755)
    desktop = ('[Desktop Entry]\n' + MARKER + '\nType=Application\nName=BeamFix\n'
               'Comment=Local projector diagnostics and guided fixes\n'
               'Exec=' + desktop_quote(paths[1]) + '\nTerminal=false\nCategories=Utility;\n'
               'Icon=video-display\nStartupNotify=false\n')
    write_atomic(paths[2], desktop)
    write_atomic(manifest, json.dumps({'bundle': name}, indent=2) + '\n')
    if previous:
        old = root / previous
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
    print(f'Installed BeamFix. Open it from the application menu or run {paths[1]}.')
    print(f'CLI: {paths[0]} doctor')
    if str(prefix / 'bin') not in os.environ.get('PATH', '').split(os.pathsep):
        print(f'For short CLI commands, add {prefix / "bin"} to PATH, or use the full path above.')
    print(f'Uninstall: {shlex.quote(sys.executable)} {shlex.quote(str(source / "install.py"))} --prefix {shlex.quote(str(prefix))} --uninstall')


if __name__ == '__main__':
    main()
