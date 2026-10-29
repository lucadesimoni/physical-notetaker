# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Voxtral Notetaker - Lean Raspberry Pi meeting transcription system
Uses Mistral Voxtral for transcription and Mistral Small 4 for meeting summaries
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
