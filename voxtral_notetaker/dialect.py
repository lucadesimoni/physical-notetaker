# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss German clean-up: turn dialect left in a transcript into Standard German.

Speech recognition writes Swiss German partly in dialect ("Mir händ das
gescht bschproche"). A language model rewrites each line in Standard German
("Wir haben das gestern besprochen") without changing content, names or
numbers. Commands, tasks, dates and the memo all work better on the result.

Safe by design: lines go out numbered and without speaker labels; any line
the model drops, shortens a lot, merges or inflates keeps its original text.
A line without dialect words keeps its text unless much of it changed: a
benchmark (SPC_R parliament speeches, Swiss German city sentences in 8
dialects) showed that polishing lines already in Standard German makes them
less exact, while rewriting dialect lines makes them much better.
"""

import os
import re
import difflib
from functools import lru_cache
import logging
from typing import Dict, List, Optional

import httpx

from .chat import message_text
from .config import NotetakerConfig
from .swiss import SWISS_STYLE
from .places import place_hints

log = logging.getLogger(__name__)

CHUNK_LINES = 40
# A cleaned line may be somewhat longer (dialect is terse), not a paragraph
MAX_GROWTH = 2.5
# ... or shorter: a much shorter line lost content
MIN_SHRINK = 0.6
# A line without dialect words takes the model's version only if at least
# this share of its words changed (dialect rewritten, not Standard German polished)
MIN_CHANGE = 0.3
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
    bsuech bsueche giut gültet vergliich schtartä schtoppä ändä wohnä
    lueged chunsch gisch nimmsch muesch gseit gloffe gfahre trunke
""".split())
# Dialect nouns, written with a capital letter like all nouns
DIALECT_NOUNS = frozenset("""
    Kaffi Foti Fotti Summer Wuche Wucheend Wochenänd Ziit Ziet Huus Chind Auti Charte
    Sitzig Ufgab Ufgabe Bricht Lüüt Gschäft Znüni Zmittag Zvieri Ztrinke Bsuech Tschopä
""".split())
# Short dialect words that also occur in other languages: a line needs two of
# them, written in lower case ("I use" is English, "i ha" is dialect)
WEAK_DIALECT_WORDS = frozenset("bi cha mer en e uf vo ufe abe ine grüezi ha i ä mini".split())
# Dialect articles before a noun ("S Ticket", "D Charte") and "Mir mache ..."
_DIALECT_PATTERN = re.compile(r"(?:^|[.!?:,]\s+|\s)(?:S|D)\s[A-ZÄÖÜ][a-zäöü]|^\s*Mir\s[a-zäöü]+e\b")
_CORPUS_WORDS = os.path.join(os.path.dirname(__file__), "data", "swiss_german_words.txt")
_CORPUS_NOUNS = os.path.join(os.path.dirname(__file__), "data", "swiss_german_nouns.txt")
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


PLACE_RULE = (
    "- Ortsnamen: Die Spracherkennung verhört kleine Schweizer Orte oft. Für diese "
    "Wörter sind ähnlich klingende amtliche Ortsnamen bekannt. Schreibe einen davon nur, "
    "wenn er eindeutig zum Gesagten passt; sonst lass das Wort, wie es ist. Rate nie einen "
    "anderen Ort, der nicht in der Liste steht:\n"
)


def _word_file(path: str) -> frozenset:
    try:
        with open(path, encoding="utf-8") as f:
            return frozenset(w.strip() for w in f if w.strip() and not w.startswith("#"))
    except OSError:
        return frozenset()


@lru_cache(maxsize=1)
def _corpus_words() -> frozenset:
    """Dialect words from the Swiss German Wikipedia and Wiktionary (data/swiss_german_words.txt)"""
    return _word_file(_CORPUS_WORDS)


@lru_cache(maxsize=1)
def _corpus_nouns() -> frozenset:
    """Dialect nouns from Wiktionary (data/swiss_german_nouns.txt), plus DIALECT_NOUNS"""
    return _word_file(_CORPUS_NOUNS) | DIALECT_NOUNS


def has_dialect(line: str) -> bool:
    """Does the line contain words that only exist in Swiss German?"""
    found = _WORD.findall(line)
    words = [w.lower() for w in found]
    if any(w in DIALECT_WORDS or w.startswith("d'") for w in words):
        return True
    if any(w in _corpus_nouns() for w in found) or _DIALECT_PATTERN.search(line):
        return True
    # Corpus words are written in lower case (capitalised words are names)
    corpus = _corpus_words()
    if any(w.lower() in corpus for i, w in enumerate(found) if i == 0 or w[:1].islower()):
        return True
    return sum(1 for w in found if w in WEAK_DIALECT_WORDS) >= 2


def changed_share(old: str, new: str) -> float:
    """Share of words that differ between two versions of a line (0..1)"""
    a, b = old.lower().split(), new.lower().split()
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def _only_place_fixes(old: str, new: str, hints: Dict[str, List[str]]) -> bool:
    """Is every change a misheard place replaced by one of its official names?"""
    a, b = old.split(), new.split()
    changes = [op for op in difflib.SequenceMatcher(None, a, b).get_opcodes() if op[0] != 'equal']
    if not changes:
        return False
    for tag, i1, i2, j1, j2 in changes:
        heard = ' '.join(a[i1:i2]).strip('.,;:!?')
        written = ' '.join(b[j1:j2]).strip('.,;:!?')
        if tag != 'replace' or written not in hints.get(heard, ()):
            return False
    return True


def accept_change(old: str, new: str, hints: Optional[Dict[str, List[str]]] = None) -> bool:
    """
    Keep the model's version only where the line was dialect (it has dialect
    words, or much of it changed) or where a misheard place got its official
    name. Small edits to Standard German (polishing, rewording) are not taken:
    measured, they make the transcript less exact.
    """
    if new == old:
        return False
    return (has_dialect(old) or changed_share(old, new) >= MIN_CHANGE
            or _only_place_fixes(old, new, hints or {}))


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
    model = config.voxtral.dialect_model or summary.model
    return f"{base_url.rstrip('/')}/chat/completions", api_key, model


def _clean_chunk(lines: List[str], config: NotetakerConfig,
                 hints: Optional[Dict[str, List[str]]] = None) -> List[str]:
    url, api_key, model = _endpoint(config)
    vocabulary = ", ".join(config.voxtral.vocabulary)
    system = PROMPT + (f"- Schreibweise dieser Namen und Begriffe beachten: {vocabulary}\n"
                       if vocabulary else "")
    if hints:
        system += PLACE_RULE + "".join(f"  «{heard}»: {', '.join(names)}\n"
                                       for heard, names in hints.items())
    numbered = "\n".join(f"{i}|{line}" for i, line in enumerate(lines, 1))
    response = httpx.post(
        url,
        headers={'Authorization': f'Bearer {api_key}'},
        json={
            'model': model,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': numbered}],
            'temperature': 0.0,
            'top_p': 1,  # some models (Mistral Large 4) refuse greedy sampling otherwise
        },
        timeout=config.summary.timeout,
    )
    response.raise_for_status()
    content = message_text(response.json())
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
    for start in range(0, len(lines), CHUNK_LINES):
        chunk = lines[start:start + CHUNK_LINES]
        hints = place_hints(chunk) if config.voxtral.place_hints else {}
        try:
            cleaned = _clean_chunk(chunk, config, hints)
        except Exception as e:
            log.warning("Swiss German clean-up skipped for %d line(s): %s", len(chunk), e)
            continue
        for i, (old, new) in enumerate(zip(chunk, cleaned), start):
            if accept_change(old, new, hints):
                out[i] = new
    changed = sum(1 for old, new in zip(lines, out) if old != new)
    log.info("Swiss German clean-up: %d of %d line(s) changed", changed, len(lines))
    return out
