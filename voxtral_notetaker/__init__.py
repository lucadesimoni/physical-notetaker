"""
Voxtral Notetaker - Advanced Raspberry Pi based note taking system
Uses Voxtral 4 for superior transcription with Swiss German support
and advanced speaker diarization for chaotic discussions.
"""

__version__ = "1.0.0"
__author__ = "Physical Notetaker Team"

from .core import Notetaker
from .audio import AudioRecorder, AudioProcessor
from .transcription import VoxtralTranscriber
from .diarization import SpeakerDiarizer
from .storage import CloudStorage
from .email import EmailSender
from .config import Config, NotetakerConfig

__all__ = [
    "Notetaker",
    "AudioRecorder",
    "AudioProcessor",
    "VoxtralTranscriber",
    "SpeakerDiarizer",
    "CloudStorage",
    "EmailSender",
    "Config",
    "NotetakerConfig",
]
