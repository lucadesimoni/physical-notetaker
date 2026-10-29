# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Extract owner and due date from spoken task text (German and English)
"""

import re
import calendar
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Iterable


GERMAN_MONTHS = {
    'januar': 1, 'jänner': 1, 'februar': 2, 'märz': 3, 'maerz': 3, 'april': 4,
    'mai': 5, 'juni': 6, 'juli': 7, 'august': 8, 'september': 9, 'oktober': 10,
    'november': 11, 'dezember': 12,
}

ENGLISH_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}

GERMAN_WEEKDAYS = {
    'montag': 0, 'dienstag': 1, 'mittwoch': 2, 'donnerstag': 3, 'freitag': 4,
    'samstag': 5, 'sonntag': 6,
}

ENGLISH_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}

_DE_MONTH = '|'.join(GERMAN_MONTHS)
_EN_MONTH = '|'.join(ENGLISH_MONTHS)
_DE_WEEKDAY = '|'.join(GERMAN_WEEKDAYS)
_EN_WEEKDAY = '|'.join(ENGLISH_WEEKDAYS)

# Due-date expressions, introduced by "bis (zum|am|spätestens)" / "by|until|due"
DUE_PATTERNS = [
    re.compile(
        r'\bbis\s+(?:zum\s+|am\s+|spätestens\s+(?:am\s+)?)?(?P<due>'
        rf'\d{{1,2}}\.\s*(?:{_DE_MONTH})(?:\s+\d{{4}})?'
        r'|\d{1,2}\.\d{1,2}\.(?:\d{2,4})?'
        rf'|(?:ende|anfang|mitte)\s+(?:{_DE_MONTH})'
        r'|ende\s+(?:der|dieser|nächster|naechster)\s+woche'
        r'|nächste\s+woche|naechste\s+woche|übermorgen|uebermorgen|morgen|heute'
        rf'|(?:nächsten\s+|naechsten\s+)?(?:{_DE_WEEKDAY})'
        r')(?!\w)',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:by|until|due(?:\s+on|\s+by)?)\s+(?:the\s+)?(?P<due>'
        rf'(?:{_EN_MONTH})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?'
        rf'|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_EN_MONTH})(?:\s+\d{{4}})?'
        r'|end\s+of\s+(?:the\s+)?(?:week|month)'
        rf'|end\s+of\s+(?:{_EN_MONTH})'
        r'|next\s+week|tomorrow|today'
        rf'|(?:next\s+)?(?:{_EN_WEEKDAY})'
        r')\b',
        re.IGNORECASE,
    ),
]

# A verb in 3rd person singular after a capitalized subject: "Sabine erstellt ..."
_GERMAN_SUBJECT = re.compile(r'^(?P<owner>[A-ZÄÖÜ][a-zäöüß]+)\s+[a-zäöüß]+t\b')
_ENGLISH_SUBJECT = re.compile(
    r'^(?P<owner>[A-Z][a-z]+)\s+(?:will|should|must|needs\s+to|has\s+to|is\s+going\s+to)\b'
)
# Trailing ", Marco" at the end of the task
_TRAILING_OWNER = re.compile(r',\s*(?P<owner>[A-ZÄÖÜ][\wäöüß-]+)\s*$')
# "für Marco", "an Marco", "assigned to Marco", "for Marco"
_ASSIGNEE = re.compile(
    r'\b(?:für|fuer|an|for|assigned\s+to|assign\s+to)\s+(?P<owner>[A-ZÄÖÜ][\wäöüß-]+)\b'
)


def _next_year_if_past(day: date, reference: date) -> date:
    if day < reference:
        try:
            return day.replace(year=day.year + 1)
        except ValueError:  # 29 February
            return day.replace(year=day.year + 1, day=28)
    return day


def _next_weekday(weekday: int, reference: date) -> date:
    days_ahead = (weekday - reference.weekday()) % 7 or 7
    return reference + timedelta(days=days_ahead)


def _end_of_week(reference: date) -> date:
    # Friday of the current week (or the next one if it's already the weekend)
    days_ahead = (4 - reference.weekday()) % 7
    return reference + timedelta(days=days_ahead)


def resolve_due_date(due_text: str, reference: Optional[date] = None) -> Optional[date]:
    """Turn a spoken due date ("10. November", "Ende Oktober", "Friday") into a date"""
    reference = reference or date.today()
    text = due_text.lower().strip().rstrip('.')
    text = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', text)

    match = re.fullmatch(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?', text)
    if match:
        day, month, year = match.groups()
        year = int(year) + 2000 if year and len(year) == 2 else int(year) if year else None
        try:
            parsed = date(year or reference.year, int(month), int(day))
        except ValueError:
            return None
        return parsed if year else _next_year_if_past(parsed, reference)

    months = {**GERMAN_MONTHS, **ENGLISH_MONTHS}
    match = (re.fullmatch(r'(\d{1,2})\.?\s*(?:of\s+)?([a-zäöü]+)(?:,?\s+(\d{4}))?', text)
             or re.fullmatch(r'([a-zäöü]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?', text))
    if match:
        a, b, year = match.groups()
        day, month_name = (a, b) if a.isdigit() else (b, a)
        if month_name in months:
            try:
                parsed = date(int(year) if year else reference.year, months[month_name], int(day))
            except ValueError:
                return None
            return parsed if year else _next_year_if_past(parsed, reference)

    match = re.fullmatch(r'(ende|anfang|mitte|end\s+of)\s+([a-zäöü]+)', text)
    if match and match.group(2) in months:
        month = months[match.group(2)]
        which = match.group(1)
        if which in ('ende', 'end of') or which.startswith('end'):
            day = calendar.monthrange(reference.year, month)[1]
        elif which == 'mitte':
            day = 15
        else:
            day = 1
        return _next_year_if_past(date(reference.year, month, day), reference)

    if text in ('heute', 'today'):
        return reference
    if text in ('morgen', 'tomorrow'):
        return reference + timedelta(days=1)
    if text in ('übermorgen', 'uebermorgen'):
        return reference + timedelta(days=2)
    if re.fullmatch(r'ende\s+(der|dieser)\s+woche|end\s+of\s+(the\s+)?week', text):
        return _end_of_week(reference)
    if re.fullmatch(r'ende\s+(nächster|naechster)\s+woche', text):
        return _end_of_week(reference) + timedelta(days=7)
    if re.fullmatch(r'end\s+of\s+(the\s+)?month', text):
        return date(reference.year, reference.month,
                    calendar.monthrange(reference.year, reference.month)[1])

    weekdays = {**GERMAN_WEEKDAYS, **ENGLISH_WEEKDAYS}
    match = re.fullmatch(r'(?:nächsten\s+|naechsten\s+|next\s+)?([a-z]+)', text)
    if match and match.group(1) in weekdays:
        return _next_weekday(weekdays[match.group(1)], reference)

    return None


def _known(name: str, participants: List[str]) -> Optional[str]:
    for participant in participants:
        if participant.lower() == name.lower():
            return participant
    return None


def parse_task_details(content: str, participants: Optional[Iterable[str]] = None,
                       reference: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Split task text into title, owner and due date.

    "Zahlungsschnittstelle bis 10. November fertigstellen, Marco"
      -> title "Zahlungsschnittstelle fertigstellen", owner "Marco", due 10.11.
    """
    participants = [p for p in (participants or []) if p]
    ref_date = (reference or datetime.now()).date()
    title = content.strip()

    due_text = None
    due_date = None
    for pattern in DUE_PATTERNS:
        match = pattern.search(title)
        if match:
            due_text = match.group('due')
            due_date = resolve_due_date(due_text, ref_date)
            title = (title[:match.start()] + ' ' + title[match.end():])
            break

    owner = None
    match = _TRAILING_OWNER.search(title)
    if match:
        owner = _known(match.group('owner'), participants) or match.group('owner')
        title = title[:match.start()]

    if not owner:
        first_word = title.split()[0] if title.split() else ''
        subject = _GERMAN_SUBJECT.match(title) or _ENGLISH_SUBJECT.match(title)
        if _known(first_word, participants):
            owner = _known(first_word, participants)
        elif subject:
            owner = subject.group('owner')
        if owner:
            # "Sabine erstellt den Kampagnenplan" -> "erstellt den Kampagnenplan"
            title = title[len(first_word):]
            # "Marco will review the code" -> "review the code"
            title = re.sub(r'^\s*(?:will|should|must|needs\s+to|has\s+to|is\s+going\s+to)\s+',
                           '', title)

    # "für Marco" is only an owner when Marco is a known participant
    # ("für das Marketing" is not)
    if not owner and participants:
        for match in _ASSIGNEE.finditer(title):
            known = _known(match.group('owner'), participants)
            if known:
                owner = known
                title = title[:match.start()] + title[match.end():]
                break

    title = re.sub(r'\s{2,}', ' ', title).strip(' \t,.;:-')

    return {
        'title': title or content.strip(),
        'owner': owner,
        'due': due_text,
        'due_date': due_date,
    }
