# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss Standard German (Schweizer Hochdeutsch) for Swiss meetings.

Speech recognition knows only "German" and writes it the way Germany does.
In Switzerland the same Standard German is written with a few differences:

- no "ß": always "ss" ("Massnahme", "gross", "Strasse")
- quotation marks «so» instead of „so“
- Swiss words are correct Standard German there and stay as they are
  (Traktandum, Pendenz, Velo, parkieren, Spital, allfällig, Natel)

The spelling rules are applied exactly; the vocabulary is left to the
language models through SWISS_STYLE in their prompts.
"""

import re
from typing import Optional

# For prompts that write German text for a Swiss meeting
SWISS_STYLE = (
    "Schreibe Schweizer Hochdeutsch: immer «ss» statt «ß», Anführungszeichen «so», "
    "Schweizer Begriffe beibehalten (z. B. Traktandum, Pendenz, Velo, parkieren, "
    "Spital, allfällig) und nicht durch deutsche Wörter ersetzen."
)

_QUOTE = re.compile(r'[„“”"]([^„“”"\n]{1,300})[“”"]')


def is_swiss(language: Optional[str]) -> bool:
    """Is this a Swiss German meeting (language de-CH)?"""
    return (language or '').strip().lower() in ('de-ch', 'gsw')


def swiss_spelling(text: str) -> str:
    """Swiss spelling of Standard German text: ss for ß, «quotes»"""
    if not text:
        return text
    text = text.replace('ẞ', 'SS').replace('ß', 'ss')
    return _QUOTE.sub(r'«\1»', text)
