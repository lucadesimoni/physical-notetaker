# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Name speakers from how they introduce themselves ("Ich bin Anna", "My name is Marco")
"""

import re
from typing import Dict, Iterable, Optional, Tuple


# Strong phrases: what follows is almost always a name
_STRONG = (
    r"mein\s+name\s+ist|ich\s+heisse|ich\s+heiße|ich\s+heiss|i\s+heisse|"
    r"hier\s+spricht|my\s+name\s+is|my\s+name's|call\s+me"
)
# Weak phrases: "Ich bin Anna" but also "Ich bin Projektleiter"
_WEAK = r"ich\s+bin|i\s+bi|ich\s+bi|hier\s+ist|i'm|i\s+am|this\s+is|it's"

_NAME = r"(?P<name>[A-ZÄÖÜ][a-zäöüéèàß]+(?:-[A-ZÄÖÜ][a-zäöüéèàß]+)?)"
# Swiss German article before names: "I bi d'Anna", "Ich bin de Marco"
_ARTICLE = r"(?:(?:d'|d’|de\s+|dr\s+|der\s+|die\s+)\s*)?"

STRONG_INTRO = re.compile(rf"\b(?:{_STRONG})\s+{_ARTICLE}{_NAME}\b", re.IGNORECASE)
WEAK_INTRO = re.compile(rf"(?:^|[.!?,]\s*|\b(?:hallo|hoi|grüezi|hi|hello|ja|also|okay)\b[,]?\s*)"
                        rf"(?:{_WEAK})\s+{_ARTICLE}{_NAME}\b", re.IGNORECASE)

# Capitalized words after "Ich bin …" that are roles, not names
NOT_NAMES = {
    'projektleiter', 'projektleiterin', 'teamleiter', 'teamleiterin', 'chef', 'chefin',
    'entwickler', 'entwicklerin', 'designer', 'designerin', 'manager', 'managerin',
    'berater', 'beraterin', 'ingenieur', 'ingenieurin', 'praktikant', 'praktikantin',
    'student', 'studentin', 'kunde', 'kundin', 'leiter', 'leiterin', 'verantwortlich',
    'zuständig', 'neu', 'hier', 'da', 'dabei', 'sicher', 'einverstanden', 'fertig',
    'dafür', 'dagegen', 'gespannt', 'froh', 'mir', 'nicht', 'auch', 'jetzt', 'eben',
    'developer', 'engineer', 'the', 'a', 'an', 'here', 'sure', 'not', 'just', 'new',
    'sorry', 'fine', 'good', 'happy', 'responsible', 'online', 'back', 'done', 'ready',
    'marketing', 'sales', 'finance', 'it', 'hr', 'support', 'product', 'cto', 'ceo', 'cfo',
    # "Ich bin Mitte Oktober weg", "Ich bin Montag im Büro"
    'mitte', 'ende', 'anfang', 'heute', 'morgen', 'gestern', 'montag', 'dienstag', 'mittwoch',
    'donnerstag', 'freitag', 'samstag', 'sonntag', 'januar', 'februar', 'märz', 'april',
    'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'dezember',
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
    'today', 'tomorrow', 'yesterday', 'im', 'in', 'am', 'um', 'bei', 'at', 'on', 'from',
}


def find_introduced_name(text: str) -> Optional[str]:
    """Return the name in an introduction, or None"""
    for pattern in (STRONG_INTRO, WEAK_INTRO):
        for match in pattern.finditer(text):
            name = match.group('name')
            if name.lower() in NOT_NAMES or len(name) < 2:
                continue
            # Weak phrases require the name to be written capitalized
            if pattern is WEAK_INTRO and not name[0].isupper():
                continue
            return name[0].upper() + name[1:]
    return None


def detect_speaker_names(segments: Iterable[Tuple[str, str]],
                         known: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Map speaker ids to names from introductions.

    segments: (speaker_id, text) in spoken order. Speakers already in `known`
    keep their name, and a name is never given to two speakers.
    """
    known = dict(known or {})
    names: Dict[str, str] = {}
    taken = {name.lower() for name in known.values()}
    for speaker_id, text in segments:
        if not speaker_id or speaker_id in known or speaker_id in names or not text:
            continue
        name = find_introduced_name(text)
        if name and name.lower() not in taken:
            names[speaker_id] = name
            taken.add(name.lower())
    return names
