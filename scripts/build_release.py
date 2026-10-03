#!/usr/bin/env python3
"""Build a dependency-free offline bundle plus standard wheel/source packages."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from beamfix import __version__


def main():
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    name = f'beamfix-{__version__}'
    # Remove only the disposable setuptools build cache so deleted assets cannot ship.
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    # Use installed build tools only; never fetch dependencies during this build.
    subprocess.run([sys.executable, '-c',
        'from setuptools.build_meta import build_wheel, build_sdist; build_wheel("dist"); build_sdist("dist")'],
        cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='beamfix-build-') as temporary:
        bundle = Path(temporary) / name
        bundle.mkdir()
        shutil.copytree(ROOT / 'beamfix', bundle / 'beamfix', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for filename in ('launch.py', 'install.py'):
            shutil.copy2(ROOT / 'packaging' / filename, bundle / filename)
        for filename in ('README.md', 'LICENSE', 'NOTICE', 'LICENSING.md', 'CONTRIBUTING.md'):
            shutil.copy2(ROOT / filename, bundle / filename)
        shutil.copytree(ROOT / 'docs', bundle / 'docs')
        (bundle / 'START-HERE.txt').write_text(
            f'BeamFix {__version__} — Linux, Python 3.11+ and a browser\n\n'
            'Free software under GPL-3.0-only, without warranty. See LICENSE and NOTICE.\n\n'
            'Run without installation, from this folder:\n'
            '  python3 launch.py gui\n'
            '  python3 launch.py doctor\n'
            '  python3 launch.py troubleshoot --try-fix\n\n'
            'Install offline for this user, including the application-menu entry:\n'
            '  python3 install.py\n\n'
            'Uninstall (keep this extracted installer):\n'
            '  python3 install.py --uninstall\n\n'
            'No sudo, pip or Internet access is needed. Optional desktop tools are\n'
            'not bundled. See docs/graphical-interface.md for compatibility and field checks.\n')
        archive = dist / f'{name}-linux-portable.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(bundle, arcname=name)
    artifacts = [archive, dist / f'{name}.tar.gz', dist / f'beamfix-{__version__}-py3-none-any.whl']
    (dist / f'{name}-SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in artifacts))
    for path in artifacts:
        print(f'{path} ({path.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
