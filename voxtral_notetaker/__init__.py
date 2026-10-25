"""
Voxtral Notetaker - Lean Raspberry Pi meeting transcription system
Uses Voxtral 4 for superior transcription with Swiss German support
"""

__version__ = "1.0.0"

from .core import Notetaker
from .config import Config, NotetakerConfig, Language
from .audio import AudioRecorder
from .commands import CommandParser, CommandExecutor, CommandType, VoiceCommand, CommandResult
from .memo import Memo, Summarizer
from .actions import parse_task_details

__all__ = [
    "Notetaker", 
    "Config", 
    "NotetakerConfig", 
    "Language", 
    "AudioRecorder",
    "CommandParser",
    "CommandExecutor",
    "CommandType",
    "VoiceCommand",
    "CommandResult",
    "Memo",
    "Summarizer",
    "parse_task_details",
]
