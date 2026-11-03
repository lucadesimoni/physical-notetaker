# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss German clean-up: turn dialect left in a transcript into Standard German.

Speech recognition writes Swiss German partly in dialect ("Mir händ das
gescht bschproche"). A language model rewrites each line in Standard German
("Wir haben das gestern besprochen") without changing content, names or
numbers. Commands, tasks, dates and the memo all work better on the result.

Safe by design: lines go out numbered and without speaker labels, and any
line the model drops, merges or inflates keeps its original text.
"""

import re
import logging
from typing import List, Optional

import httpx

from .config import NotetakerConfig

log = logging.getLogger(__name__)

CHUNK_LINES = 40
# A cleaned line may be somewhat longer (dialect is terse), not a paragraph
MAX_GROWTH = 2.5
_NUMBERED = re.compile(r'^\s*(\d+)\s*[|:.)]\s?(.*)$')

PROMPT = (
    "Du bekommst Zeilen aus dem Transkript einer Besprechung in der Schweiz. Die "
    "Spracherkennung hat Schweizerdeutsch teilweise in Mundart geschrieben.\n"
    "Schreibe jede Zeile in korrektem Hochdeutsch, so wie es die sprechende Person "
    "auf Hochdeutsch gesagt hätte.\n"
    "Regeln:\n"
    "- Inhalt, Bedeutung, Zahlen, Daten, Namen und Fachbegriffe unverändert lassen.\n"
    "- Nichts hinzufügen, nichts weglassen, nicht zusammenfassen, keine Erklärungen.\n"
    "- Zeilen, die schon Hochdeutsch oder Englisch sind, unverändert lassen.\n"
    "- Befehle sinngemäss übernehmen, z. B. «Mach es Notiz:» → «Mach eine Notiz:», "
    "«Erstell en Task:» → «Erstell einen Task:», «bis am Friitig» → «bis Freitag».\n"
    "- Jede Zeile beginnt mit ihrer Nummer und «|». Gib genau dieselben Nummern in "
    "derselben Reihenfolge zurück, eine Zeile pro Nummer, im Format «Nummer|Text».\n"
)


def should_clean(config: NotetakerConfig, detected_language: Optional[str]) -> bool:
    """Swiss German meetings, or German ones when the language is automatic"""
    if not config.voxtral.dialect_cleanup:
        return False
    meeting = (config.service.language or 'auto').lower()
    if meeting == 'de-ch':
        return True
    return meeting == 'auto' and (detected_language or '').lower().startswith('de')


def _endpoint(config: NotetakerConfig):
    summary = config.summary
    base_url = summary.base_url or config.voxtral.base_url
    api_key = summary.api_key or config.voxtral.resolved_api_key()
    return f"{base_url.rstrip('/')}/chat/completions", api_key, summary.model


def _clean_chunk(lines: List[str], config: NotetakerConfig) -> List[str]:
    url, api_key, model = _endpoint(config)
    vocabulary = ", ".join(config.voxtral.vocabulary)
    system = PROMPT + (f"- Schreibweise dieser Namen und Begriffe beachten: {vocabulary}\n"
                       if vocabulary else "")
    numbered = "\n".join(f"{i}|{line}" for i, line in enumerate(lines, 1))
    response = httpx.post(
        url,
        headers={'Authorization': f'Bearer {api_key}'},
        json={
            'model': model,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': numbered}],
            'temperature': 0.0,
        },
        timeout=config.summary.timeout,
    )
    response.raise_for_status()
    content = response.json()['choices'][0]['message']['content']
    return merge_cleaned(lines, content)


def merge_cleaned(lines: List[str], content: str) -> List[str]:
    """Take the model's numbered lines; keep the original wherever they look wrong"""
    cleaned = {}
    for raw in content.splitlines():
        match = _NUMBERED.match(raw)
        if match:
            number = int(match.group(1))
            if 1 <= number <= len(lines) and number not in cleaned:
                cleaned[number] = match.group(2).strip()
    result = []
    for i, original in enumerate(lines, 1):
        new = cleaned.get(i)
        if not new or len(new) > max(40, len(original) * MAX_GROWTH):
            result.append(original)  # missing, empty or suspiciously long
        else:
            result.append(new)
    return result


def clean_lines(lines: List[str], config: NotetakerConfig) -> List[str]:
    """
    Standard German version of each line. On any error the original lines are
    returned: the clean-up improves a memo but must never cost one.
    """
    if not lines or not config.voxtral.resolved_api_key():
        return list(lines)
    out: List[str] = []
    for start in range(0, len(lines), CHUNK_LINES):
        chunk = lines[start:start + CHUNK_LINES]
        try:
            out.extend(_clean_chunk(chunk, config))
        except Exception as e:
            log.warning("Swiss German clean-up skipped for %d line(s): %s", len(chunk), e)
            out.extend(chunk)
    return out
