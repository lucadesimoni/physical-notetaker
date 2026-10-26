"""
Wi-Fi setup through NetworkManager (nmcli), as on Raspberry Pi OS Bookworm
"""

import shutil
import logging
import subprocess
from typing import List, Tuple

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
