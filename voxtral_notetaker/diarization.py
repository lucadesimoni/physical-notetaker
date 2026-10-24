"""
Lean speaker diarization for voice recognition
"""

import os
import numpy as np
from typing import Optional, List, Dict
from dataclasses import dataclass

from pyannote.audio import Pipeline


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker_id: str


class SpeakerDiarizer:
    """Speaker diarization using pyannote.audio"""
    
    def __init__(self):
        self._pipeline: Optional[Pipeline] = None
        self._initialized = False
        self._speaker_names: Dict[str, str] = {}
    
    def _init_pipeline(self):
        """Initialize diarization pipeline"""
        if self._initialized:
            return
        try:
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1"
            )
            self._initialized = True
        except Exception as e:
            print(f"Diarization disabled: {e}")
            self._initialized = False
    
    def diarize(self, audio_file: str, max_speakers: int = 10) -> List[SpeakerSegment]:
        """Perform speaker diarization"""
        if not self._initialized:
            self._init_pipeline()
        
        if not self._pipeline or not self._initialized:
            return []
        
        try:
            diarization = self._pipeline(audio_file, max_speakers=max_speakers)
            
            segments = []
            for segment, _, speaker_id in diarization.itertracks(yield_label=True):
                segments.append(SpeakerSegment(
                    start=segment.start,
                    end=segment.end,
                    speaker_id=speaker_id
                ))
            
            return segments
        except Exception as e:
            print(f"Diarization failed: {e}")
            return []
    
    def set_speaker_name(self, speaker_id: str, name: str):
        """Set a custom name for a speaker"""
        self._speaker_names[speaker_id] = name
    
    def get_speaker_name(self, speaker_id: str) -> str:
        """Get speaker name or ID"""
        return self._speaker_names.get(speaker_id, speaker_id)
