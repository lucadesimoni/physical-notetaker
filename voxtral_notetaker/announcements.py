# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Remove the device's own announcements from a transcript.

The speakerphone that plays "Aufnahme gestartet. Diese Besprechung wird
aufgezeichnet." is also the microphone, so the announcement ends up in the
recording. Sentences that closely match one of the device's phrases are dropped.
"""

import re
from difflib import SequenceMatcher
from typing import List

from .i18n import device_phrases

# How closely a transcribed sentence must match a device phrase to be dropped
SIMILARITY = 0.85


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


_PHRASES = [_norm(p) for p in device_phrases()]


def is_announcement(sentence: str) -> bool:
    norm = _norm(sentence)
    if not norm:
        return False
    return any(SequenceMatcher(None, norm, phrase).ratio() >= SIMILARITY for phrase in _PHRASES)


def strip_announcements(text: str) -> str:
    """The text without sentences the device said itself"""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept: List[str] = [s for s in sentences if s and not is_announcement(s)]
    return " ".join(kept)
