# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss place names as a help for transcribing.

Speech recognition often mishears small Swiss places, above all in dialect:
"Meltigen" for Meltingen, "Guttenbad" for Gontenbad. For each word in a
place context ("in", "nach", "vo", "uf" ...) that is not an official name,
the most similar official names (data/swiss_places.txt) are looked up and
given to the dialect clean-up as hints. The language model picks one only
where it fits what was said, and otherwise leaves the word: it is told not
to guess other places ("Genpe" must not become "Genf").
"""

import difflib
import os
import re
from functools import lru_cache
from typing import Dict, List

# German names used in Swiss German speech for places listed in French or Italian
EXONYMS = ["Genf", "Neuenburg", "Freiburg", "Sitten", "Siders", "Delsberg", "Pruntrut",
           "Biel", "Bellenz", "Lauis", "Milden", "Peterlingen", "Wiflisburg", "Iferten"]

# Words after which a capitalised word is probably a place (Standard German and dialect)
CONTEXT = {"in", "im", "nach", "noch", "no", "aus", "us", "bei", "bi", "durch", "dur", "duur",
           "duerch", "ab", "bis", "zwischen", "zwüsche", "über", "via", "von", "vom", "vo",
           "uf", "z", "go", "gegen", "gege", "richtung", "gemeinde", "kanton", "dorf", "ort"}
LIST_JOIN = {",", "und", "un", "u", "oder", "sowie"}
# Capitalised words that are not places even after "in" ("in Zukunft", "im Herbst")
NOT_PLACES = {"Zukunft", "Ordnung", "Bezug", "Frage", "Kraft", "Sachen", "Folge", "Zusammenarbeit",
              "Herbst", "Winter", "Sommer", "Frühling", "Januar", "Februar", "März", "April",
              "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember",
              "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"}

MAX_HINTS = 30
_DATA = os.path.join(os.path.dirname(__file__), "data", "swiss_places.txt")
_SUFFIX = re.compile(r"\s+(?:\([^)]*\)|[A-Z]{2})$")  # "Aesch (BL)", "Abtwil AG"
_TOKEN = re.compile(r"[^\W\d_][\w'.-]*|,")


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
    names.update({n.replace("ß", "ss") for n in names})  # Swiss spelling
    return frozenset(n for n in names if len(n) >= 3)


def _sound(word: str) -> str:
    """A rough spoken form, so that spelling and dialect differences matter less"""
    w = word.lower().replace("ß", "ss")
    for a, b in (("ä", "e"), ("ö", "o"), ("ü", "u"), ("é", "e"), ("è", "e"), ("y", "i"),
                 ("ie", "i"), ("ck", "k"), ("tz", "z"), ("dt", "t"), ("th", "t"), ("ph", "f")):
        w = w.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", w)


@lru_cache(maxsize=1)
def _by_sound() -> Dict[str, List[str]]:
    """Spoken form of a name's first word -> official names (langnau -> Langnau am Albis, ...)"""
    index: Dict[str, List[str]] = {}
    for name in sorted(place_names()):
        index.setdefault(_sound(name.split()[0]), []).append(name)
    return index


def candidates(word: str, count: int = 3, cutoff: float = 0.7) -> List[str]:
    """Official names that sound most like word"""
    index = _by_sound()
    out: List[str] = []
    for key in difflib.get_close_matches(_sound(word), list(index), n=count, cutoff=cutoff):
        out.extend(index[key])
    return out[:count + 2]


def place_words(text: str) -> List[str]:
    """Capitalised words in a place context: after "in", "nach", "vo" ... or in a list after one"""
    tokens = _TOKEN.findall(text)
    found: List[str] = []
    in_list = False
    for i, token in enumerate(tokens):
        word = token.rstrip(".")
        previous = tokens[i - 1].lower() if i else ""
        if i and word[:1].isupper() and word not in NOT_PLACES and \
                (previous in CONTEXT or (in_list and previous in LIST_JOIN)):
            found.append(word)
            in_list = True
        elif token not in LIST_JOIN:
            in_list = in_list and word[:1].isupper()
    return found


def place_hints(lines: List[str]) -> Dict[str, List[str]]:
    """
    For words in a place context that are not exactly an official name: the
    official names they may have been ("Meltigen": Meltingen, Merligen, ...)
    """
    names = place_names()
    hints: Dict[str, List[str]] = {}
    for line in lines:
        for word in place_words(line):
            if word in hints:
                continue
            if word in names:
                continue  # heard as an official name: trusted
            found = candidates(word)
            if found:
                hints[word] = found
            if len(hints) >= MAX_HINTS:
                return hints
    return hints
