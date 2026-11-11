# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Names learned from past meetings, as hints for the transcription.

Misheard names are the most common real error. The speech recognition takes
up to 100 hint terms; besides the ones entered in the settings, the names of
recent meetings are used: speaker names corrected on a meeting page (counted
twice: someone checked them), speaker names found in introductions, and task
owners in the memo. Names seen in several meetings and recently come first.
"""

import re
from collections import Counter
from typing import Iterable, List

MAX_JOBS = 50       # recent meetings looked at
MAX_LEARNED = 40    # learned names among the 100 hints

_NAME = re.compile(r"^[A-ZÄÖÜÉÈÀ][\wäöüéèàçß'.-]*(?: [A-ZÄÖÜÉÈÀ][\wäöüéèàçß'.-]*){0,3}$")
_NOT_NAMES = {"unknown", "unbekannt", "wer", "who", "speaker", "sprecher", "–", "-"}


def is_name(text: str) -> bool:
    """A real name, not a speaker id like speaker_0 or a table header"""
    text = (text or "").strip()
    return (2 <= len(text) <= 40 and bool(_NAME.match(text)) and "_" not in text
            and not any(ch.isdigit() for ch in text) and text.lower() not in _NOT_NAMES)


def task_owners(memo_file: str) -> List[str]:
    """Owners in the tasks table of a memo (Markdown)"""
    owners = []
    try:
        with open(memo_file, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, TypeError):
        return owners
    in_tasks = False
    for line in lines:
        if line.startswith("## "):
            in_tasks = line[3:].strip() in ("Aufgaben", "Tasks")
        elif in_tasks and line.startswith("|") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and cells[0] not in ("Wer", "Who"):
                owners.append(cells[0])
    return owners


def learned_names(jobs: Iterable, limit: int = MAX_LEARNED) -> List[str]:
    """Names from recent meetings (newest first), most frequent first"""
    counts: Counter = Counter()
    first_seen = {}
    for rank, job in enumerate(list(jobs)[:MAX_JOBS]):
        names = (list(job.speaker_overrides.values()) * 2 + list(job.speakers.values())
                 + task_owners(job.memo_file))
        for name in names:
            name = " ".join(str(name).split())
            if is_name(name):
                counts[name] += 1
                first_seen.setdefault(name, rank)
    ranked = sorted(counts, key=lambda n: (-counts[n], first_seen[n]))
    return ranked[:limit]
