# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
File helpers that also behave on Windows
"""

import os
import time

# Windows refuses to replace a file while another thread has it open (e.g. the
# web page reading a status file). Such locks last milliseconds: retry briefly.
REPLACE_ATTEMPTS = 20
REPLACE_WAIT_SECONDS = 0.05


def atomic_replace(src: str, dst: str):
    """os.replace that retries while the target is briefly locked"""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)


def read_text(path: str) -> str:
    """
    Read a text file, retrying while Windows briefly locks it: a reader that
    opens a file while another thread replaces it gets PermissionError.
    """
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            with open(path, encoding='utf-8') as f:
                return f.read()
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)
    return ''  # not reached
