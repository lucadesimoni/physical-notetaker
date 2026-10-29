# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Meeting memo generation: notes, tasks and research collected during a meeting,
plus an optional AI summary of the transcript
"""

import re
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

import httpx

from .config import SummaryConfig, VoxtralConfig


LABELS = {
    'de': {
        'title': 'Protokoll',
        'date': 'Datum',
        'duration': 'Dauer',
        'participants': 'Teilnehmende',
        'summary': 'Zusammenfassung',
        'notes': 'Notizen',
        'research': 'Offene Fragen / Recherche',
        'tasks': 'Aufgaben',
        'who': 'Wer',
        'what': 'Was',
        'due': 'Bis',
        'none': 'Keine',
        'minutes': 'Min.',
    },
    'en': {
        'title': 'Meeting Notes',
        'date': 'Date',
        'duration': 'Duration',
        'participants': 'Participants',
        'summary': 'Summary',
        'notes': 'Notes',
        'research': 'Open Questions / Research',
        'tasks': 'Action Items',
        'who': 'Who',
        'what': 'What',
        'due': 'Due',
        'none': 'None',
        'minutes': 'min',
    },
}


def _lang_key(language: str) -> str:
    return 'de' if language and language.lower().startswith('de') else 'en'


def _format_date(day: date, lang: str) -> str:
    return day.strftime('%d.%m.%Y') if lang == 'de' else day.isoformat()


def _cell(text: str) -> str:
    # Keep Markdown tables intact
    return text.replace('|', '\\|').replace('\n', ' ')


@dataclass
class Memo:
    """A structured meeting memo"""
    title: str
    language: str
    date: datetime
    participants: List[str] = field(default_factory=list)
    duration_seconds: Optional[float] = None
    summary: List[str] = field(default_factory=list)
    notes: List[Dict[str, Any]] = field(default_factory=list)
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    research: List[Dict[str, Any]] = field(default_factory=list)

    def _due(self, task: Dict[str, Any], lang: str) -> str:
        if task.get('due_date'):
            return _format_date(task['due_date'], lang)
        return task.get('due') or '–'

    def to_markdown(self) -> str:
        lang = _lang_key(self.language)
        L = LABELS[lang]
        lines = [f"# {L['title']}: {self.title}", ""]

        meta = [f"**{L['date']}:** {_format_date(self.date.date(), lang)}"]
        if self.duration_seconds:
            meta.append(f"**{L['duration']}:** {round(self.duration_seconds / 60)} {L['minutes']}")
        if self.participants:
            meta.append(f"**{L['participants']}:** {', '.join(self.participants)}")
        lines += ['  \n'.join(meta), ""]

        if self.summary:
            lines += [f"## {L['summary']}", ""]
            lines += [f"- {point}" for point in self.summary]
            lines.append("")

        lines += [f"## {L['notes']}", ""]
        lines += [f"- {n['content']}" for n in self.notes] or [f"_{L['none']}_"]
        lines.append("")

        if self.research:
            lines += [f"## {L['research']}", ""]
            lines += [f"- {r['query']}" for r in self.research]
            lines.append("")

        lines += [f"## {L['tasks']}", ""]
        if self.tasks:
            lines += [f"| {L['who']} | {L['what']} | {L['due']} |", "|---|---|---|"]
            for task in self.tasks:
                lines.append(
                    f"| {_cell(task.get('owner') or '–')} "
                    f"| {_cell(task.get('title') or task['content'])} "
                    f"| {_cell(self._due(task, lang))} |"
                )
        else:
            lines.append(f"_{L['none']}_")
        lines.append("")

        return '\n'.join(lines)

    def to_text(self) -> str:
        """Plain-text version, e.g. for an email body"""
        lang = _lang_key(self.language)
        L = LABELS[lang]
        lines = [f"{L['title']}: {self.title}",
                 f"{L['date']}: {_format_date(self.date.date(), lang)}"]
        if self.participants:
            lines.append(f"{L['participants']}: {', '.join(self.participants)}")
        lines.append("")

        if self.summary:
            lines += [f"{L['summary']}:"] + [f"  - {p}" for p in self.summary] + [""]

        lines.append(f"{L['notes']}:")
        lines += [f"  - {n['content']}" for n in self.notes] or [f"  {L['none']}"]
        lines.append("")

        if self.research:
            lines += [f"{L['research']}:"] + [f"  - {r['query']}" for r in self.research] + [""]

        lines.append(f"{L['tasks']}:")
        if self.tasks:
            for task in self.tasks:
                owner = task.get('owner') or '–'
                lines.append(f"  - [{owner}] {task.get('title') or task['content']} "
                             f"({L['due']}: {self._due(task, lang)})")
        else:
            lines.append(f"  {L['none']}")

        return '\n'.join(lines) + '\n'


SUMMARY_PROMPTS = {
    'de': (
        "Du erstellst Sitzungsprotokolle. Fasse das folgende Gesprächsprotokoll in "
        "höchstens {max_points} kurzen Stichpunkten auf Deutsch zusammen. Nenne "
        "Entscheidungen, Zahlen und Termine. Antworte nur mit Stichpunkten, jeder "
        "beginnt mit \"- \"."
    ),
    'en': (
        "You write meeting minutes. Summarize the following transcript in at most "
        "{max_points} short bullet points in English. Include decisions, figures and "
        "dates. Reply only with bullet points, each starting with \"- \"."
    ),
}


class Summarizer:
    """Summarizes a transcript via an OpenAI-compatible chat completions API (e.g. Mistral)"""

    def __init__(self, config: SummaryConfig, voxtral: VoxtralConfig):
        self.config = config
        self.base_url = config.base_url or voxtral.base_url
        self.api_key = config.api_key or voxtral.resolved_api_key()

    @property
    def available(self) -> bool:
        return bool(self.config.enabled and self.api_key and self.config.model)

    def summarize(self, transcript: str, language: str) -> List[str]:
        """Return summary bullet points, or an empty list if unavailable or on error"""
        if not self.available or not transcript.strip():
            return []

        lang = _lang_key(language)
        system = SUMMARY_PROMPTS[lang].format(max_points=self.config.max_points)
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={'Authorization': f'Bearer {self.api_key}'},
                json={
                    'model': self.config.model,
                    'messages': [
                        {'role': 'system', 'content': system},
                        {'role': 'user', 'content': transcript},
                    ],
                    'temperature': 0.2,
                },
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"Summary failed: {e}")
            return []

        bullet = re.compile(r'^\s*(?:[-*•]|\d+[.)])\s+')
        lines = [line for line in content.splitlines() if line.strip()]
        # Ignore a preamble like "Hier ist die Zusammenfassung:" when bullets are present
        if any(bullet.match(line) for line in lines):
            lines = [line for line in lines if bullet.match(line)]
        points = [bullet.sub('', line).strip() for line in lines]
        return [p for p in points if p][:self.config.max_points]
