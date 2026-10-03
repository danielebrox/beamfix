#!/usr/bin/env python3
"""Smoke-test the built offline package in a temporary user prefix."""
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from beamfix import __version__


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True, **kwargs)


def main():
    wheel = ROOT / f'dist/beamfix-{__version__}-py3-none-any.whl'
    expected = {f'beamfix/web/{name}' for name in ('index.html','style.css','app.js','no_signal.svg',
                                                  'black.svg','desktop.svg','room_monitors_only.svg')}
    with zipfile.ZipFile(wheel) as archive:
        assert expected <= set(archive.namelist())
    with tempfile.TemporaryDirectory(prefix='beamfix-release-') as directory:
        temp = Path(directory)
        with tarfile.open(ROOT / f'dist/beamfix-{__version__}-linux-portable.tar.gz') as archive:
            # Artifacts are built from this checkout; require one expected root.
            assert all(m.name == f'beamfix-{__version__}' or m.name.startswith(f'beamfix-{__version__}/')
                       for m in archive.getmembers())
            archive.extractall(temp)
        bundle = temp / f'beamfix-{__version__}'
        prefix = temp / 'prefix with spaces'
        assert __version__ in run(sys.executable, bundle/'launch.py','--version',cwd=temp).stdout
        run(sys.executable, bundle/'install.py','--prefix',prefix)
        assert __version__ in run(prefix/'bin/beamfix','--version',cwd=temp).stdout
        assert '--demo' in run(prefix/'bin/beamfix-gui','--help',cwd=temp).stdout
        if shutil.which('desktop-file-validate'):
            run('desktop-file-validate',prefix/'share/applications/beamfix.desktop')
        run(sys.executable, bundle/'install.py','--prefix',prefix)
        assert len(list((prefix/'share/beamfix').glob('app-*'))) == 1
        run(sys.executable, bundle/'install.py','--prefix',prefix,'--uninstall')
        assert not (prefix/'bin/beamfix').exists()
        (prefix/'bin/beamfix').write_text('unrelated command\n')
        refused = subprocess.run([sys.executable,str(bundle/'install.py'),'--prefix',str(prefix)],capture_output=True,text=True)
        assert refused.returncode != 0 and 'unrelated' in refused.stderr
        assert (prefix/'bin/beamfix').read_text() == 'unrelated command\n'
    print('Wheel assets, portable CLI, user install, menu, update, removal and collision checks passed.')


if __name__ == '__main__':
    main()
