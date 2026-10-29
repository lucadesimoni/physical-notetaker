# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Wi-Fi setup through NetworkManager (nmcli), as on Raspberry Pi OS Bookworm
"""

import socket
import shutil
import logging
import subprocess
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


def has_nmcli() -> bool:
    return shutil.which('nmcli') is not None


def _nmcli(args: List[str], timeout: int = 60) -> Tuple[bool, str]:
    if not has_nmcli():
        return False, "nmcli not available"
    try:
        result = subprocess.run(['nmcli', *args], capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    output = (result.stdout or result.stderr).strip()
    return result.returncode == 0, output


def connectivity() -> str:
    """'full', 'limited', 'portal', 'none' or 'unknown'"""
    ok, output = _nmcli(['networking', 'connectivity', 'check'], timeout=20)
    return output if ok and output else 'unknown'


def connect_wifi(ssid: str, password: str) -> Tuple[bool, str]:
    args = ['device', 'wifi', 'connect', ssid]
    if password:
        args += ['password', password]
    ok, output = _nmcli(args)
    log.info("Wi-Fi connect to %r: %s", ssid, output)
    return ok, output


def start_hotspot(ssid: str, password: str) -> bool:
    ok, output = _nmcli(['device', 'wifi', 'hotspot', 'ssid', ssid, 'password', password])
    log.info("Setup hotspot %r: %s", ssid, output)
    return ok


def local_ip() -> Optional[str]:
    """The device's address in the local network (no packet is sent)"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 80))  # TEST-NET address: only selects the route
            ip = s.getsockname()[0]
            return None if ip.startswith('127.') else ip
    except OSError:
        return None


def device_urls(port: int) -> List[str]:
    """Addresses a phone can open: name.local first, then the IP address"""
    suffix = '' if port == 80 else f':{port}'
    urls = [f"http://{socket.gethostname()}.local{suffix}"]
    ip = local_ip()
    if ip:
        urls.append(f"http://{ip}{suffix}")
    return urls


def speakable_address(ip: str, port: int, lang: str = 'de') -> str:
    """'192.168.1.23' -> '1 9 2 Punkt 1 6 8 Punkt 1 Punkt 2 3' (clear when spoken)"""
    dot = ' Punkt ' if lang.startswith('de') else ' dot '
    text = dot.join(' '.join(part) for part in ip.split('.'))
    if port != 80:
        text += (', Port ' if lang.startswith('de') else ', port ') + ' '.join(str(port))
    return text
