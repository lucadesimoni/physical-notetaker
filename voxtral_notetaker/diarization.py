# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Lean speaker diarization for voice recognition
"""

import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker_id: str


class SpeakerDiarizer:
    """Speaker diarization using pyannote.audio"""
    
    def __init__(self, auth_token: Optional[str] = None):
        self._auth_token = auth_token or os.environ.get("HF_TOKEN")
        self._pipeline: Optional[Any] = None
        self._initialized = False
        self._speaker_names: Dict[str, str] = {}
    
    def _init_pipeline(self):
        """Initialize diarization pipeline"""
        if self._initialized:
            return
        # Only attempt initialization once, even if it fails
        self._initialized = True
        try:
            from pyannote.audio import Pipeline
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=self._auth_token
            )
        except Exception as e:
            print(f"Diarization disabled: {e}")
            self._pipeline = None
    
    def diarize(self, audio_file: str, max_speakers: int = 10) -> List[SpeakerSegment]:
        """Perform speaker diarization"""
        if not self._initialized:
            self._init_pipeline()
        
        if not self._pipeline:
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
