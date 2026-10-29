# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Voice Command System for Voxtral Notetaker
Handles interruptions and voice commands in German and English
"""

import re
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .actions import parse_task_details


class CommandType(Enum):
    """Types of voice commands"""
    NOTE = "note"
    TASK = "task"
    RESEARCH = "research"
    RECORDING = "recording"
    TRANSCRIBE = "transcribe"
    SUMMARIZE = "summarize"
    HELP = "help"
    INTERRUPT = "interrupt"
    CANCEL = "cancel"


@dataclass
class VoiceCommand:
    """Represents a parsed voice command"""
    command_type: CommandType
    text: str
    language: str
    confidence: float
    timestamp: datetime = field(default_factory=datetime.now)
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """Result of executing a voice command"""
    success: bool
    command: str
    response: str
    action: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class CommandParser:
    """
    Parses voice input to detect commands
    Supports German and English
    """
    
    # German command patterns
    GERMAN_NOTE_PATTERNS = [
        r'mach\s+(eine|die)?\s*notiz',
        r'erstell\s+(eine|die)?\s*notiz',
        r'notiz\s+erstellen',
        r'notieren',
        r'aufschreiben',
        r'schreib\s+(das|es)\s+auf',
        r'merke(n)?\b',
        r'notiz:',
    ]
    
    GERMAN_TASK_PATTERNS = [
        r'erstell\s+(einen|den|die)?\s*task',
        r'erstell\s+(eine|die)?\s*aufgabe',
        r'mach\s+(einen|den|die)?\s*task',
        r'task\s+erstellen',
        r'aufgabe\s+erstellen',
        r'aufgabe\s+hinzuf(ü|ue)gen',
        r'task\s+hinzuf(ü|ue)gen',
        r'aufgabe:',
        r'task:',
    ]
    
    GERMAN_RESEARCH_PATTERNS = [
        r'recherchieren',
        r'recherchiere',
        r'suche\b',
        r'googeln',
        r'googel',
        r'nachschlagen',
        r'informationen\s+finden',
        r'findet\s+heraus',
        r'recherche:',
        r'suche:',
    ]
    
    GERMAN_RECORDING_PATTERNS = {
        'start': [
            r'start\s+(die|eine)?\s*aufnahme',
            r'start\s+recording',
            r'aufnahme\s+starten',
            r'beginne\s+(die|eine)?\s*aufnahme',
            r'recording\s+starten',
        ],
        'stop': [
            r'stop\s+(die|eine)?\s*aufnahme',
            r'stop\s+recording',
            r'aufnahme\s+stoppen',
            r'beende\s+(die|eine)?\s*aufnahme',
            r'recording\s+stoppen',
        ],
        'pause': [
            r'pause\s+(die|eine)?\s*aufnahme',
            r'aufnahme\s+pausieren',
            r'pausieren',
        ],
    }
    
    # English command patterns
    ENGLISH_NOTE_PATTERNS = [
        r'make\s+(a|the)?\s*note',
        r'create\s+(a|the)?\s*note',
        r'take\s+(a|the)?\s*note',
        r'note\s+this',
        r'note:',
        r'write\s+this\s+down',
    ]
    
    ENGLISH_TASK_PATTERNS = [
        r'create\s+(a|the)?\s*task',
        r'make\s+(a|the)?\s*task',
        r'add\s+(a|the)?\s*task',
        r'task:',
        r'to\s+do:',
        r'reminder:',
    ]
    
    ENGLISH_RESEARCH_PATTERNS = [
        r'research',
        r'search',
        r'look\s+up',
        r'google',
        r'find\s+out',
        r'find\s+information',
        r'research:',
        r'search:',
    ]
    
    GERMAN_SUMMARY_PATTERNS = [
        r'fass(e)?\s+(das|es|alles|bitte)?\s*zusammen',
        r'erstell(e)?\s+(eine|die)\s+zusammenfassung',
        r'zusammenfassung\s+erstellen',
    ]
    
    ENGLISH_SUMMARY_PATTERNS = [
        r'summari[sz]e\s+(the|this)\s+meeting',
        r'summari[sz]e\s+(it|that|everything)',
        r'create\s+(a|the)\s+summary',
        r'give\s+(me|us)\s+a\s+summary',
    ]
    
    ENGLISH_RECORDING_PATTERNS = {
        'start': [
            r'start\s+recording',
            r'begin\s+recording',
            r'start\s+the\s+meeting',
        ],
        'stop': [
            r'stop\s+recording',
            r'end\s+recording',
            r'stop\s+the\s+meeting',
        ],
        'pause': [
            r'pause\s+recording',
            r'pause\s+the\s+meeting',
        ],
    }
    
    # Words that may precede a command: "Okay, mach eine Notiz", "Please create a task"
    LEAD_IN = re.compile(
        r'^(?:\s*(?:okay|ok|also|so|und|dann|jetzt|gut|bitte|please|and|then|now|alright)'
        r'[,:]?\s+)*',
        re.IGNORECASE,
    )
    
    def __init__(self):
        self._custom_commands: Dict[str, Callable] = {}
    
    def parse(self, text: str, language: str = "auto", strict: bool = False) -> Optional[VoiceCommand]:
        """
        Parse text to detect voice commands.
        
        With strict=True the command phrase must open the sentence, so that
        ordinary speech ("Ich suche noch einen Termin") is not taken as a command.
        """
        text = text.strip()
        
        if not text:
            return None
        
        # Detect language if auto
        if language == "auto":
            language = self._detect_language(text)
        
        groups = []
        # Try German patterns first if language is German
        if language in ['de', 'de-CH']:
            groups += [
                (self.GERMAN_SUMMARY_PATTERNS, self._create_summary_command),
                (self.GERMAN_NOTE_PATTERNS, self._create_note_command),
                (self.GERMAN_TASK_PATTERNS, self._create_task_command),
                (self.GERMAN_RESEARCH_PATTERNS, self._create_research_command),
            ]
            groups += [
                (patterns, self._recording_factory(action))
                for action, patterns in self.GERMAN_RECORDING_PATTERNS.items()
            ]
        
        # Try English patterns
        groups += [
            (self.ENGLISH_SUMMARY_PATTERNS, self._create_summary_command),
            (self.ENGLISH_NOTE_PATTERNS, self._create_note_command),
            (self.ENGLISH_TASK_PATTERNS, self._create_task_command),
            (self.ENGLISH_RESEARCH_PATTERNS, self._create_research_command),
        ]
        groups += [
            (patterns, self._recording_factory(action))
            for action, patterns in self.ENGLISH_RECORDING_PATTERNS.items()
        ]
        
        command_start = self.LEAD_IN.match(text).end()
        for patterns, factory in groups:
            for pattern in patterns:
                match = re.search(r'\b' + pattern, text, re.IGNORECASE)
                if match and (not strict or match.start() == command_start):
                    return factory(text, language, match)
        
        if strict:
            return None
        
        # Check for interruptions
        if self._is_interruption(text, language):
            return VoiceCommand(
                command_type=CommandType.INTERRUPT,
                text=text,
                language=language,
                confidence=0.9,
                parameters={'reason': 'user_interruption'}
            )
        
        # Check for cancel
        if self._is_cancel(text, language):
            return VoiceCommand(
                command_type=CommandType.CANCEL,
                text=text,
                language=language,
                confidence=0.9,
                parameters={}
            )
        
        return None
    
    @staticmethod
    def _contains_word(text: str, phrases: List[str]) -> bool:
        """Check whether any phrase occurs in text as a whole word"""
        return any(
            re.search(r'\b' + re.escape(phrase) + r'\b', text, re.IGNORECASE)
            for phrase in phrases
        )
    
    def _detect_language(self, text: str) -> str:
        """Detect language from text"""
        # Simple heuristic: check for common German words and command verbs
        german_words = [
            'der', 'die', 'das', 'und', 'oder', 'für', 'mit', 'von', 'uns', 'bitte',
            'ein', 'eine', 'einen', 'mach', 'erstell', 'erstelle', 'notiz', 'aufgabe',
            'recherchiere', 'suche', 'aufnahme', 'warten', 'unterbrechen', 'abbrechen',
        ]
        
        if self._contains_word(text, german_words):
            return 'de-CH'
        
        return 'en'
    
    def _is_interruption(self, text: str, language: str) -> bool:
        """Check if text is an interruption"""
        if language in ['de', 'de-CH']:
            interrupt_phrases = [
                'moment',
                'warten',
                'halten',
                'stop',
                'pause',
                'unterbrechen',
            ]
        else:
            interrupt_phrases = [
                'wait',
                'hold on',
                'stop',
                'pause',
                'interrupt',
                'moment',
            ]
        
        return self._contains_word(text, interrupt_phrases)
    
    def _is_cancel(self, text: str, language: str) -> bool:
        """Check if text is a cancel command"""
        if language in ['de', 'de-CH']:
            cancel_phrases = ['abbrechen', 'abbruch', 'stornieren', 'cancel']
        else:
            cancel_phrases = ['cancel', 'abort', 'stop']
        
        return self._contains_word(text, cancel_phrases)
    
    def _create_note_command(self, text: str, language: str, match: re.Match) -> VoiceCommand:
        """Create a note command"""
        # Extract the note text
        note_text = self._extract_content(text, match)
        
        return VoiceCommand(
            command_type=CommandType.NOTE,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'content': note_text, 'original_text': text}
        )
    
    def _create_task_command(self, text: str, language: str, match: re.Match) -> VoiceCommand:
        """Create a task command"""
        # Extract the task text
        task_text = self._extract_content(text, match)
        
        return VoiceCommand(
            command_type=CommandType.TASK,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'content': task_text, 'original_text': text}
        )
    
    def _create_research_command(self, text: str, language: str, match: re.Match) -> VoiceCommand:
        """Create a research command"""
        # Extract the research query
        query = self._extract_content(text, match)
        
        return VoiceCommand(
            command_type=CommandType.RESEARCH,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'query': query, 'original_text': text}
        )
    
    def _create_summary_command(self, text: str, language: str, match: re.Match) -> VoiceCommand:
        """Create a summarize command"""
        return VoiceCommand(
            command_type=CommandType.SUMMARIZE,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'original_text': text}
        )
    
    def _recording_factory(self, action: str) -> Callable[[str, str, re.Match], VoiceCommand]:
        return lambda text, language, match: self._create_recording_command(text, language, action)
    
    def _create_recording_command(self, text: str, language: str, action: str) -> VoiceCommand:
        """Create a recording control command"""
        return VoiceCommand(
            command_type=CommandType.RECORDING,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'action': action, 'original_text': text}
        )
    
    def _extract_content(self, text: str, match: re.Match) -> str:
        """Extract the actual content following the command phrase"""
        content = text[match.end():]
        
        # "Recherchiere für uns: Marktanalyse" -> "Marktanalyse"
        if ':' in content:
            content = content.split(':', 1)[1]
        
        # Strip leftover separators, keep punctuation inside the content
        return content.strip(' \t\n:,.;-!?')


class CommandExecutor:
    """
    Executes voice commands
    """
    
    def __init__(self, notetaker):
        self.notetaker = notetaker
        self._notes: List[Dict[str, Any]] = []
        self._tasks: List[Dict[str, Any]] = []
        self._research_queries: List[Dict[str, Any]] = []
        self._parser = CommandParser()
    
    # Commands that only collect content and can safely be replayed from a transcript
    CONTENT_COMMANDS = (CommandType.NOTE, CommandType.TASK, CommandType.RESEARCH)
    
    def execute(self, text: str, language: str = "auto", speaker: Optional[str] = None,
                timestamp: Optional[datetime] = None) -> Optional[CommandResult]:
        """Parse and execute a voice command"""
        command = self._parse(text, language, speaker, timestamp)
        if not command:
            return None
        return self._dispatch(command)
    
    def extract_from_transcript(self, transcript: str, language: str = "auto",
                                timestamp: Optional[datetime] = None) -> List[CommandResult]:
        """
        Find note, task and research commands in a finished transcript.
        
        Lines may carry a speaker label ("[Anna] Mach eine Notiz: ...").
        Recording controls and interruptions are ignored, and items already
        captured live are not added twice.
        """
        results = []
        for speaker, sentence in split_transcript(transcript):
            command = self._parse(sentence, language, speaker, timestamp, strict=True)
            if not command or command.command_type not in self.CONTENT_COMMANDS:
                continue
            if self._is_duplicate(command):
                continue
            result = self._dispatch(command)
            if result:
                results.append(result)
        return results
    
    def _parse(self, text: str, language: str, speaker: Optional[str],
               timestamp: Optional[datetime], strict: bool = False) -> Optional[VoiceCommand]:
        command = self._parser.parse(text, language, strict=strict)
        if command:
            command.parameters['speaker'] = speaker
            if timestamp:
                command.timestamp = timestamp
        return command
    
    def _is_duplicate(self, command: VoiceCommand) -> bool:
        def norm(value: str) -> str:
            return re.sub(r'\W+', ' ', value or '').strip().lower()
        
        if command.command_type == CommandType.RESEARCH:
            existing, key, new = self._research_queries, 'query', command.parameters.get('query')
        elif command.command_type == CommandType.TASK:
            existing, key, new = self._tasks, 'content', command.parameters.get('content')
        else:
            existing, key, new = self._notes, 'content', command.parameters.get('content')
        return any(norm(item[key]) == norm(new) for item in existing)
    
    def _participants(self) -> List[str]:
        names = getattr(self.notetaker, '_speaker_names', None) or {}
        return list(names.values())
    
    def _dispatch(self, command: VoiceCommand) -> Optional[CommandResult]:
        # Execute based on command type
        if command.command_type == CommandType.NOTE:
            return self._execute_note(command)
        elif command.command_type == CommandType.TASK:
            return self._execute_task(command)
        elif command.command_type == CommandType.RESEARCH:
            return self._execute_research(command)
        elif command.command_type == CommandType.RECORDING:
            return self._execute_recording(command)
        elif command.command_type == CommandType.INTERRUPT:
            return self._execute_interrupt(command)
        elif command.command_type == CommandType.CANCEL:
            return self._execute_cancel(command)
        elif command.command_type == CommandType.SUMMARIZE:
            return self._execute_summarize(command)
        
        return None
    
    def _execute_note(self, command: VoiceCommand) -> CommandResult:
        """Execute a note command"""
        content = command.parameters.get('content', command.text)
        
        if not content:
            return CommandResult(
                success=False,
                command=command.text,
                response="Kein Notiztext erkannt / No note content detected"
            )
        
        # Save note
        note = {
            'content': content,
            'language': command.language,
            'timestamp': command.timestamp,
            'speaker': command.parameters.get('speaker'),
            'original_text': command.parameters.get('original_text', command.text)
        }
        
        self._notes.append(note)
        
        # Create response in the same language
        if command.language in ['de', 'de-CH']:
            response = f"Notiz erstellt: {content[:50]}..."
        else:
            response = f"Note created: {content[:50]}..."
        
        return CommandResult(
            success=True,
            command=command.text,
            response=response,
            action="CREATE_NOTE",
            data={'note': note}
        )
    
    def _execute_task(self, command: VoiceCommand) -> CommandResult:
        """Execute a task command"""
        content = command.parameters.get('content', command.text)
        
        if not content:
            return CommandResult(
                success=False,
                command=command.text,
                response="Kein Aufgabentext erkannt / No task content detected"
            )
        
        # Save task
        task = {
            'content': content,
            'language': command.language,
            'timestamp': command.timestamp,
            'status': 'open',
            'requested_by': command.parameters.get('speaker'),
            'original_text': command.parameters.get('original_text', command.text)
        }
        participants = self._participants()
        speaker = command.parameters.get('speaker')
        if speaker and speaker not in participants:
            participants.append(speaker)
        task.update(parse_task_details(content, participants, command.timestamp))
        
        self._tasks.append(task)
        
        # Create response
        if command.language in ['de', 'de-CH']:
            response = f"Aufgabe erstellt: {content[:50]}..."
        else:
            response = f"Task created: {content[:50]}..."
        
        return CommandResult(
            success=True,
            command=command.text,
            response=response,
            action="CREATE_TASK",
            data={'task': task}
        )
    
    def _execute_research(self, command: VoiceCommand) -> CommandResult:
        """Execute a research command"""
        query = command.parameters.get('query', command.text)
        
        if not query:
            return CommandResult(
                success=False,
                command=command.text,
                response="Keine Suchanfrage erkannt / No research query detected"
            )
        
        # Save research query
        research = {
            'query': query,
            'language': command.language,
            'timestamp': command.timestamp,
            'status': 'queued',
            'requested_by': command.parameters.get('speaker'),
            'original_text': command.parameters.get('original_text', command.text)
        }
        
        self._research_queries.append(research)
        
        # Create response
        if command.language in ['de', 'de-CH']:
            response = f"Recherche gestartet: {query[:50]}..."
        else:
            response = f"Research started: {query[:50]}..."
        
        return CommandResult(
            success=True,
            command=command.text,
            response=response,
            action="START_RESEARCH",
            data={'research': research}
        )
    
    def _execute_recording(self, command: VoiceCommand) -> CommandResult:
        """Execute a recording control command"""
        action = command.parameters.get('action', 'unknown')
        
        if action == 'start':
            if command.language in ['de', 'de-CH']:
                response = "Aufnahme gestartet"
            else:
                response = "Recording started"
            
            # Note: Actual recording would be started by the notetaker
            return CommandResult(
                success=True,
                command=command.text,
                response=response,
                action="START_RECORDING"
            )
        
        elif action == 'stop':
            if command.language in ['de', 'de-CH']:
                response = "Aufnahme beendet"
            else:
                response = "Recording stopped"
            
            return CommandResult(
                success=True,
                command=command.text,
                response=response,
                action="STOP_RECORDING"
            )
        
        elif action == 'pause':
            if command.language in ['de', 'de-CH']:
                response = "Aufnahme pausiert"
            else:
                response = "Recording paused"
            
            return CommandResult(
                success=True,
                command=command.text,
                response=response,
                action="PAUSE_RECORDING"
            )
        
        return CommandResult(
            success=False,
            command=command.text,
            response="Unbekannte Aktion / Unknown action"
        )
    
    def _execute_interrupt(self, command: VoiceCommand) -> CommandResult:
        """Execute an interrupt command"""
        # Trigger interruption in notetaker
        result = self.notetaker.interrupt()
        
        if result:
            if command.language in ['de', 'de-CH']:
                response = f"Unterbrochen. Bisher: {result.transcript[:50]}..."
            else:
                response = f"Interrupted. So far: {result.transcript[:50]}..."
        else:
            if command.language in ['de', 'de-CH']:
                response = "Unterbrechung erkannt"
            else:
                response = "Interruption acknowledged"
        
        return CommandResult(
            success=True,
            command=command.text,
            response=response,
            action="INTERRUPT"
        )
    
    def _execute_cancel(self, command: VoiceCommand) -> CommandResult:
        """Execute a cancel command"""
        # Clear pending actions
        self._notes = []
        self._tasks = []
        self._research_queries = []
        
        if command.language in ['de', 'de-CH']:
            response = "Aktion abgebrochen"
        else:
            response = "Action cancelled"
        
        return CommandResult(
            success=True,
            command=command.text,
            response=response,
            action="CANCEL"
        )
    
    def _execute_summarize(self, command: VoiceCommand) -> CommandResult:
        """Execute a summarize command"""
        # Interim memo of everything captured so far
        memo = None
        if hasattr(self.notetaker, 'build_memo'):
            memo = self.notetaker.build_memo(language=command.language, summarize=False)
        
        counts = (len(self._notes), len(self._tasks), len(self._research_queries))
        if command.language in ['de', 'de-CH']:
            response = "Zwischenstand: {} Notizen, {} Aufgaben, {} Recherchen".format(*counts)
        else:
            response = "So far: {} notes, {} tasks, {} research items".format(*counts)
        
        return CommandResult(
            success=True,
            command=command.text,
            response=response,
            action="SUMMARIZE",
            data={'memo': memo.to_markdown() if memo else None}
        )
    
    def get_notes(self) -> List[Dict[str, Any]]:
        """Get all created notes"""
        return self._notes
    
    def get_tasks(self) -> List[Dict[str, Any]]:
        """Get all created tasks"""
        return self._tasks
    
    def get_research_queries(self) -> List[Dict[str, Any]]:
        """Get all research queries"""
        return self._research_queries
    
    def clear_all(self):
        """Clear all saved commands"""
        self._notes = []
        self._tasks = []
        self._research_queries = []


_SPEAKER_LINE = re.compile(r'^\s*\[(?P<speaker>[^\]]+)\]\s*(?P<text>.*)$')
# Sentence end, but not the dot in "10. November" or "15.11."
_SENTENCE_END = re.compile(r'(?<!\d)[.!?]+\s+')


def split_transcript(transcript: str) -> List[tuple]:
    """Split a transcript into (speaker, sentence) pairs"""
    pairs = []
    speaker = None
    for line in transcript.splitlines():
        if not line.strip():
            continue
        match = _SPEAKER_LINE.match(line)
        if match:
            speaker, line = match.group('speaker').strip(), match.group('text')
        for sentence in _SENTENCE_END.split(line):
            if sentence.strip():
                pairs.append((speaker, sentence.strip()))
    return pairs
