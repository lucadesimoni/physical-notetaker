# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Build the release downloads into dist/:

  notetaker-windows-v<version>.zip         unzip, double-click "Notetaker starten.bat"
  notetaker-raspberry-pi-v<version>.tar.gz  unpack, sudo ./install.sh

Only files tracked by git go in (never a local config.yaml with an API key,
recordings or a venv), and only what users need: no tests or CI files.

    python scripts/package_release.py
"""

import io
import os
import re
import sys
import tarfile
import zipfile
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMMON = ('voxtral_notetaker/', 'examples/', 'setup.py', 'requirements.txt', 'README.md',
          'LICENSE', 'CHANGELOG.md', 'config.example.yaml')
WINDOWS = COMMON + ('windows/',)
RASPBERRY_PI = COMMON + ('deploy/',)

WINDOWS_STARTER = (
    "@echo off\r\n"
    "rem SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0\r\n"
    "rem Copyright (c) 2026 Outthinkx by Luca De Simoni\r\n"
    "rem Double-click to start the Meeting Notetaker\r\n"
    "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0windows\\start-notetaker.ps1\"\r\n"
    "if errorlevel 1 pause\r\n"
)

PI_INSTALLER = (
    "#!/usr/bin/env bash\n"
    "# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0\n"
    "# Copyright (c) 2026 Outthinkx by Luca De Simoni\n"
    "# Set up the Meeting Notetaker on this Raspberry Pi: sudo ./install.sh\n"
    "exec \"$(dirname \"$0\")/deploy/install.sh\" \"$@\"\n"
)


def version() -> str:
    with open(os.path.join(ROOT, 'voxtral_notetaker', '__init__.py'), encoding='utf-8') as f:
        return re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)


def tracked_files(prefixes) -> list:
    out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout.split('\n')
    return sorted(p for p in out if p and p.startswith(prefixes))


def build_windows(ver: str, dist: str) -> str:
    top = f"notetaker-v{ver}"
    path = os.path.join(dist, f"notetaker-windows-v{ver}.zip")
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in tracked_files(WINDOWS):
            z.write(os.path.join(ROOT, name), f"{top}/{name}")
        z.writestr(f"{top}/Notetaker starten.bat", WINDOWS_STARTER)
    return path


def build_raspberry_pi(ver: str, dist: str) -> str:
    top = f"notetaker-v{ver}"
    path = os.path.join(dist, f"notetaker-raspberry-pi-v{ver}.tar.gz")
    with tarfile.open(path, 'w:gz') as t:
        for name in tracked_files(RASPBERRY_PI):
            info = t.gettarinfo(os.path.join(ROOT, name), f"{top}/{name}")
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            if name.endswith('.sh'):
                info.mode = 0o755
            with open(os.path.join(ROOT, name), 'rb') as f:
                t.addfile(info, f)
        data = PI_INSTALLER.encode()
        info = tarfile.TarInfo(f"{top}/install.sh")
        info.size, info.mode = len(data), 0o755
        t.addfile(info, io.BytesIO(data))
    return path


def main() -> int:
    ver = version()
    tag = os.environ.get('GITHUB_REF_NAME', '')
    if tag.startswith('v') and tag != f"v{ver}":
        print(f"Tag {tag} does not match the package version {ver}", file=sys.stderr)
        return 1
    dist = os.path.join(ROOT, 'dist')
    os.makedirs(dist, exist_ok=True)
    for path in (build_windows(ver, dist), build_raspberry_pi(ver, dist)):
        print(f"{os.path.relpath(path, ROOT)}  ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
