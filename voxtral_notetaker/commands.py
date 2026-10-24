"""
Voice Command System for Voxtral Notetaker
Handles interruptions and voice commands in German and English
"""

import re
import time
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


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
        r'merken',
        r'notiz:',
    ]
    
    GERMAN_TASK_PATTERNS = [
        r'erstell\s+(einen|den|die)?\s*task',
        r'erstell\s+(eine|die)?\s*aufgabe',
        r'mach\s+(einen|den|die)?\s*task',
        r'task\s+erstellen',
        r'aufgabe\s+erstellen',
        r'aufgabe\s+hinzufuegen',
        r'task\s+hinzufuegen',
        r'aufgabe:',
        r'task:',
    ]
    
    GERMAN_RESEARCH_PATTERNS = [
        r'recherchiere',
        r'recherchieren',
        r'suche',
        r'googeln',
        r'googel',
        r'nachschlagen',
        r'informationen\s+findet',
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
    
    def __init__(self):
        self._custom_commands: Dict[str, Callable] = {}
    
    def parse(self, text: str, language: str = "auto") -> Optional[VoiceCommand]:
        """Parse text to detect voice commands"""
        text = text.lower().strip()
        
        if not text:
            return None
        
        # Remove punctuation for matching
        clean_text = re.sub(r'[^\w\s:]', '', text)
        
        # Detect language if auto
        if language == "auto":
            language = self._detect_language(text)
        
        # Try German patterns first if language is German
        if language in ['de', 'de-CH']:
            # Check for note
            for pattern in self.GERMAN_NOTE_PATTERNS:
                if re.search(pattern, clean_text, re.IGNORECASE):
                    return self._create_note_command(text, language)
            
            # Check for task
            for pattern in self.GERMAN_TASK_PATTERNS:
                if re.search(pattern, clean_text, re.IGNORECASE):
                    return self._create_task_command(text, language)
            
            # Check for research
            for pattern in self.GERMAN_RESEARCH_PATTERNS:
                if re.search(pattern, clean_text, re.IGNORECASE):
                    return self._create_research_command(text, language)
            
            # Check for recording commands
            for action, patterns in self.GERMAN_RECORDING_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, clean_text, re.IGNORECASE):
                        return self._create_recording_command(text, language, action)
        
        # Try English patterns
        for pattern in self.ENGLISH_NOTE_PATTERNS:
            if re.search(pattern, clean_text, re.IGNORECASE):
                return self._create_note_command(text, language)
        
        for pattern in self.ENGLISH_TASK_PATTERNS:
            if re.search(pattern, clean_text, re.IGNORECASE):
                return self._create_task_command(text, language)
        
        for pattern in self.ENGLISH_RESEARCH_PATTERNS:
            if re.search(pattern, clean_text, re.IGNORECASE):
                return self._create_research_command(text, language)
        
        for action, patterns in self.ENGLISH_RECORDING_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, clean_text, re.IGNORECASE):
                    return self._create_recording_command(text, language, action)
        
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
    
    def _detect_language(self, text: str) -> str:
        """Detect language from text"""
        # Simple heuristic: check for German words
        german_words = ['der', 'die', 'das', 'und', 'oder', 'für', 'mit', 'von']
        
        for word in german_words:
            if word in text.lower():
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
            ]
        
        for phrase in interrupt_phrases:
            if phrase in text.lower():
                return True
        
        return False
    
    def _is_cancel(self, text: str, language: str) -> bool:
        """Check if text is a cancel command"""
        if language in ['de', 'de-CH']:
            cancel_phrases = ['abbrechen', 'abbruch', 'stornieren', 'cancel']
        else:
            cancel_phrases = ['cancel', 'abort', 'stop']
        
        for phrase in cancel_phrases:
            if phrase in text.lower():
                return True
        
        return False
    
    def _create_note_command(self, text: str, language: str) -> VoiceCommand:
        """Create a note command"""
        # Extract the note text
        note_text = self._extract_content(text, language, 'note')
        
        return VoiceCommand(
            command_type=CommandType.NOTE,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'content': note_text, 'original_text': text}
        )
    
    def _create_task_command(self, text: str, language: str) -> VoiceCommand:
        """Create a task command"""
        # Extract the task text
        task_text = self._extract_content(text, language, 'task')
        
        return VoiceCommand(
            command_type=CommandType.TASK,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'content': task_text, 'original_text': text}
        )
    
    def _create_research_command(self, text: str, language: str) -> VoiceCommand:
        """Create a research command"""
        # Extract the research query
        query = self._extract_content(text, language, 'research')
        
        return VoiceCommand(
            command_type=CommandType.RESEARCH,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'query': query, 'original_text': text}
        )
    
    def _create_recording_command(self, text: str, language: str, action: str) -> VoiceCommand:
        """Create a recording control command"""
        return VoiceCommand(
            command_type=CommandType.RECORDING,
            text=text,
            language=language,
            confidence=0.9,
            parameters={'action': action, 'original_text': text}
        )
    
    def _extract_content(self, text: str, language: str, command_type: str) -> str:
        """Extract the actual content from a command"""
        # Remove command keywords
        if language in ['de', 'de-CH']:
            if command_type == 'note':
                keywords = ['mach eine notiz', 'erstell eine notiz', 'notiz:', 'aufschreiben', 'merken']
            elif command_type == 'task':
                keywords = ['erstell einen task', 'mach einen task', 'task:', 'aufgabe:', 'erstellen']
            elif command_type == 'research':
                keywords = ['recherchiere', 'suche', 'googeln', 'nachschlagen', 'findet heraus']
            else:
                keywords = []
        else:
            if command_type == 'note':
                keywords = ['make a note', 'create a note', 'note:', 'write this down']
            elif command_type == 'task':
                keywords = ['create a task', 'make a task', 'task:', 'to do:', 'reminder:']
            elif command_type == 'research':
                keywords = ['research', 'search', 'look up', 'google', 'find out']
            else:
                keywords = []
        
        # Remove keywords
        for keyword in keywords:
            text = text.replace(keyword, '').strip()
        
        # Remove punctuation and clean up
        text = re.sub(r'^[^a-zA-ZäöüßÄÖÜ]+', '', text)
        text = re.sub(r'[^\w\säöüßÄÖÜ]', '', text)
        text = text.strip()
        
        return text


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
    
    def execute(self, text: str, language: str = "auto") -> Optional[CommandResult]:
        """Parse and execute a voice command"""
        command = self._parser.parse(text, language)
        
        if not command:
            return None
        
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
            'original_text': command.parameters.get('original_text', command.text)
        }
        
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
        # This would trigger summarization of current meeting
        if command.language in ['de', 'de-CH']:
            response = "Zusammenfassung wird erstellt..."
        else:
            response = "Creating summary..."
        
        return CommandResult(
            success=True,
            command=command.text,
            response=response,
            action="SUMMARIZE"
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
