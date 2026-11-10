# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss German clean-up: turn dialect left in a transcript into Standard German.

Speech recognition writes Swiss German partly in dialect ("Mir händ das
gescht bschproche"). A language model rewrites each line in Standard German
("Wir haben das gestern besprochen") without changing content, names or
numbers. Commands, tasks, dates and the memo all work better on the result.

Safe by design: only lines with dialect words are sent (a benchmark on the
SPC_R test set showed that rewriting lines already in Standard German makes
them worse); they go out numbered and without speaker labels, and any line
the model drops, shortens, merges or inflates keeps its original text.
"""

import re
import logging
from typing import List, Optional

import httpx

from .config import NotetakerConfig
from .swiss import SWISS_STYLE

log = logging.getLogger(__name__)

CHUNK_LINES = 40
# A cleaned line may be somewhat longer (dialect is terse), not a paragraph
MAX_GROWTH = 2.5
# ... or shorter: a much shorter line lost content
MIN_SHRINK = 0.6
_NUMBERED = re.compile(r'^\s*(\d+)\s*[|:.)]\s?(.*)$')

# Words that only occur in Swiss German, not in Standard German. Lines with
# none of them are left as the speech recognition wrote them.
DIALECT_WORDS = frozenset("""
    isch händ hend hät hesch hets bisch chasch chan chunt chunnt chömed chönd
    chönnt gönd gaht gahts gsi gsii gseh gsait gmacht gha nöd nüd nüt nüüt nid
    nit öppis öpper öppe chli chlii scho hüt morn gescht geschter jetz zäme
    ois eus üs öis euse öise wämmer wämer simmer hämmer gäll gälled vill bim
    dur gäge wüsst weisch säg säge luege lueg mached tüend tuet friitig mäntig
    zischtig ziischtig mittwuch donnschtig samschtig sunntig wuche ändi mitti
    novämber dezämber auguscht gömmer gemmer bstelle
""".split())
# Short words that are dialect too, but also names or other languages (not
# "es", "merci", "mache": those are Standard German as well):
# a line needs two of them
WEAK_DIALECT_WORDS = frozenset("bi cha mer en e uf vo ufe abe ine use grüezi".split())
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


PROMPT = (
    "Du bekommst Zeilen aus dem Transkript einer Besprechung in der Schweiz. Die "
    "Spracherkennung hat Schweizerdeutsch teilweise in Mundart geschrieben.\n"
    "Schreibe jede Zeile in korrektem Hochdeutsch, so wie es die sprechende Person "
    "auf Hochdeutsch gesagt hätte.\n"
    "Regeln:\n"
    "- Inhalt, Bedeutung, Zahlen, Daten, Namen und Fachbegriffe unverändert lassen.\n"
    "- Nichts hinzufügen, nichts weglassen, nicht zusammenfassen, keine Erklärungen.\n"
    "- Nur Mundartwörter und Mundart-Grammatik ändern. Was schon Hochdeutsch ist, "
    "Wort für Wort stehen lassen, nicht umformulieren oder glätten.\n"
    "- Zeilen, die schon Hochdeutsch oder Englisch sind, unverändert lassen.\n"
    "- Befehle sinngemäss übernehmen, z. B. «Mach es Notiz:» → «Mach eine Notiz:», "
    "«Erstell en Task:» → «Erstell einen Task:», «bis am Friitig» → «bis Freitag».\n"
    f"- {SWISS_STYLE}\n"
    "- Jede Zeile beginnt mit ihrer Nummer und «|». Gib genau dieselben Nummern in "
    "derselben Reihenfolge zurück, eine Zeile pro Nummer, im Format «Nummer|Text».\n"
)


def has_dialect(line: str) -> bool:
    """Does the line contain words that only exist in Swiss German?"""
    words = [w.lower() for w in _WORD.findall(line)]
    if any(w in DIALECT_WORDS or w.startswith("d'") for w in words):
        return True
    return sum(1 for w in words if w in WEAK_DIALECT_WORDS) >= 2


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
    current = None
    for raw in content.splitlines():
        match = _NUMBERED.match(raw)
        if match and 1 <= int(match.group(1)) <= len(lines) and int(match.group(1)) not in cleaned:
            current = int(match.group(1))
            cleaned[current] = match.group(2).strip()
        elif current is not None and raw.strip():
            # The model split a long line: the continuation belongs to it
            cleaned[current] = f"{cleaned[current]} {raw.strip()}"
    result = []
    for i, original in enumerate(lines, 1):
        new = cleaned.get(i)
        if (not new or len(new) > max(40, len(original) * MAX_GROWTH)
                or len(new) < len(original) * MIN_SHRINK):
            result.append(original)  # missing, empty, suspiciously long or short
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
    out: List[str] = list(lines)
    todo = [i for i, line in enumerate(lines) if has_dialect(line)]
    for start in range(0, len(todo), CHUNK_LINES):
        indexes = todo[start:start + CHUNK_LINES]
        chunk = [lines[i] for i in indexes]
        try:
            for i, new in zip(indexes, _clean_chunk(chunk, config)):
                out[i] = new
        except Exception as e:
            log.warning("Swiss German clean-up skipped for %d line(s): %s", len(chunk), e)
    changed = sum(1 for old, new in zip(lines, out) if old != new)
    log.info("Swiss German clean-up: %d of %d line(s) changed", changed, len(lines))
    return out
