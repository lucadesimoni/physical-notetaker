# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss place names in a transcript: marked when they are certain.

Certain means: the transcript has exactly an official name (municipalities
and localities, data/swiss_places.txt) in a place context: after "in",
"nach", "aus" ..., in a list after one ("in Wolfhalden, Linthal und
Lutzenberg"), or as a multi-word official name ("Küssnacht am Rigi").
Nothing is guessed from similar-sounding words, so "Frau von Gunten" or
"ein Scherz" stay as they are, and names that are also ordinary words
("Dorf", "Wald") are never marked. The pipeline marks only names the speech
recognition itself wrote, never ones a language model put in.
"""

import os
import re
from functools import lru_cache
from typing import Iterable, List, Optional, Tuple

MARK = "📍"

# German names used in Swiss German speech for places listed in French or Italian
EXONYMS = ["Genf", "Neuenburg", "Freiburg", "Sitten", "Siders", "Delsberg", "Pruntrut",
           "Biel", "Bellenz", "Lauis", "Milden", "Peterlingen", "Wiflisburg", "Iferten"]

# Words after which a name is a place
CONTEXT = {"in", "im", "nach", "aus", "bei", "durch", "ab", "bis", "zwischen", "über", "via",
           "richtung", "gemeinde", "kanton", "stadt", "dorf", "region", "raum", "ort",
           "von", "vom", "gegen", "um", "z", "uf", "vo", "ufe", "go"}
# ... except "von" after these words: a surname ("Frau von Gunten")
SURNAME_BEFORE_VON = {"herr", "herrn", "frau", "familie", "dr", "prof", "fam"}
# Places that are also ordinary German words: never certain
COMMON_WORDS = {"Dorf", "Wald", "Berg", "Au", "Egg", "Horn", "Rain", "Feld", "Buch", "See",
                "Bach", "Matt", "Grund", "Hof", "Holz", "Ried", "Moos", "Stein", "Tal", "Weiler",
                "Brücke", "Mühle", "Bad", "Kirche", "Schwand", "Boden", "Brunnen", "Hub", "Scherz",
                "Ins", "Root", "Zell", "Hirschen", "Sonne", "Halten", "Hagen", "Schachen",
                "Ebnet", "Weid", "Rot"}
LIST_JOIN = {",", "und", "oder", "sowie", "bis", "nach", "u", "un"}

_DATA = os.path.join(os.path.dirname(__file__), "data", "swiss_places.txt")
_SUFFIX = re.compile(r"\s+(?:\([^)]*\)|[A-Z]{2})$")  # "Aesch (BL)", "Abtwil AG"


@lru_cache(maxsize=1)
def place_names() -> frozenset:
    """Official names plus the forms people say ("Abtwil" for "Abtwil AG")"""
    names = set(EXONYMS)
    with open(_DATA, encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            names.add(name)
            short = _SUFFIX.sub("", name)
            if short != name:
                names.add(short)
            if "/" in name:  # "Sils im Engadin/Segl", "Biel/Bienne"
                names.update(part.strip() for part in name.split("/") if part.strip())
    # Swiss spelling is used in transcripts: "ss" for "ß"
    names.update({n.replace("ß", "ss") for n in names})
    return frozenset(n for n in names if len(n) >= 3 and n not in COMMON_WORDS)


_WORD = re.compile(r"[^\W\d_][\w.'-]*")


@lru_cache(maxsize=1)
def _index() -> dict:
    """First word -> the names starting with it, as word lists, longest first"""
    index: dict = {}
    for name in place_names():
        words = name.split()
        index.setdefault(words[0], []).append(words)
    for names in index.values():
        names.sort(key=len, reverse=True)
    return index


def _matches(text: str):
    """(start, end, name) of every official name in text, the longest at each word"""
    words = list(_WORD.finditer(text))
    index = _index()
    i = 0
    while i < len(words):
        start = words[i].start()
        hit = None
        if not (start and text[start - 1] == MARK[-1]):  # already marked
            for candidate in index.get(words[i].group(0).rstrip(".'-"), ()) or \
                    index.get(words[i].group(0), ()):
                n = len(candidate)
                if i + n > len(words):
                    continue
                said = [w.group(0) for w in words[i:i + n]]
                # The last word may carry the sentence's full stop: "nach Bern."
                if said[:-1] == candidate[:-1] and said[-1] in (candidate[-1],
                                                               candidate[-1] + "."):
                    hit = (start, words[i + n - 1].start() + len(candidate[-1]), n)
                    break
        if hit:
            yield hit[0], hit[1], text[hit[0]:hit[1]]
            i += hit[2]
        else:
            i += 1


_TOKEN = re.compile(r"[\w']+|,")


def _words_before(text: str, start: int, count: int = 2) -> List[str]:
    tokens = _TOKEN.findall(text[max(0, start - 80):start])
    return [t.lower().strip("'") for t in tokens[-count:]]


def find_places(text: str) -> List[Tuple[int, int, str]]:
    """(start, end, name) of the places in text that are certain"""
    found: List[Tuple[int, int, str]] = []
    last_end = None
    for start, end, name in _matches(text):
        before = _words_before(text, start)
        previous = before[-1] if before else ""
        certain = False
        if " " in name:
            certain = True  # multi-word official name
        elif previous in CONTEXT:
            certain = not (previous == "von" and len(before) > 1
                           and before[-2] in SURNAME_BEFORE_VON)
        elif previous in LIST_JOIN and last_end is not None:
            # A list of places: only words between the previous place and this one
            between = text[last_end:start]
            certain = len(_TOKEN.findall(between)) <= 2 and not re.search(r"[.!?]", between)
        if certain:
            found.append((start, end, name))
            last_end = end
    return found


def _mark_text(text: str, allowed: Optional[set] = None) -> str:
    out, position = [], 0
    for start, end, name in find_places(text):
        if allowed is not None and name not in allowed:
            continue
        out.append(text[position:start])
        out.append(MARK + name)
        position = end
    out.append(text[position:])
    return "".join(out)


def mark_places(transcript: str, allowed: Optional[Iterable[str]] = None) -> str:
    """
    Mark certain places with 📍, line by line, never inside "[Speaker]" labels.
    With allowed, only those names are marked (e.g. the ones the speech
    recognition wrote, not ones the dialect clean-up put in).
    """
    allowed = set(allowed) if allowed is not None else None
    lines = []
    for line in transcript.split("\n"):
        label = re.match(r"^\s*\[[^\]]*\]\s*", line)
        head = label.group(0) if label else ""
        lines.append(head + _mark_text(line[len(head):], allowed))
    return "\n".join(lines)


def places_in(transcript: str) -> List[str]:
    """The certain places of a transcript, once each, in order of mention"""
    seen: List[str] = []
    for line in transcript.split("\n"):
        label = re.match(r"^\s*\[[^\]]*\]\s*", line)
        for _, _, name in find_places(line[label.end() if label else 0:]):
            if name not in seen:
                seen.append(name)
    return seen
