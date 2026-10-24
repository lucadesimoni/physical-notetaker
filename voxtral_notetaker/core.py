"""
Core Notetaker - Lean implementation for conference transcription
"""

import os
import time
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import NotetakerConfig, Language
from .audio import AudioRecorder, RecordingInfo
from .transcription import VoxtralTranscriber, TranscriptionResult
from .diarization import SpeakerDiarizer, SpeakerSegment
from .storage import CloudStorage, UploadResult


@dataclass
class MeetingResult:
    """Meeting transcription result"""
    audio_file: str
    transcript: str
    language: str
    confidence: float
    duration: float
    start_time: datetime
    end_time: datetime
    speakers: List[str] = field(default_factory=list)
    speaker_segments: List[Dict[str, Any]] = field(default_factory=list)
    storage_results: List[UploadResult] = field(default_factory=list)


class Notetaker:
    """
    Main notetaker class for conference transcription
    Supports live transcription, interruptions, speaker recognition, and cloud storage
    """
    
    def __init__(self, config: Optional[NotetakerConfig] = None):
        self.config = config or NotetakerConfig()
        
        # Components
        self.audio = AudioRecorder(self.config.audio)
        self.transcriber = VoxtralTranscriber(self.config.voxtral)
        self.diarizer = SpeakerDiarizer()
        self.storage = CloudStorage(self.config.storage)
        
        # State
        self._is_recording = False
        self._current_file: Optional[str] = None
        self._start_time: Optional[datetime] = None
        self._interrupted = False
        self._speaker_names: Dict[str, str] = {}
    
    def start_recording(self, output_file: Optional[str] = None) -> bool:
        """Start recording from conference microphone"""
        if self._is_recording:
            return False
        
        if not output_file:
            output_file = f"meeting_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        
        success = self.audio.start_recording(output_file)
        if success:
            self._is_recording = True
            self._current_file = output_file
            self._start_time = datetime.now()
            self._interrupted = False
        
        return success
    
    def stop_recording(self) -> Optional[RecordingInfo]:
        """Stop recording"""
        if not self._is_recording:
            return None
        
        result = self.audio.stop_recording()
        self._is_recording = False
        return result
    
    def transcribe(self, audio_file: str, language: Language = Language.AUTO) -> TranscriptionResult:
        """Transcribe audio file"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                self.transcriber.transcribe(audio_file, language)
            )
            return result
        finally:
            loop.close()
    
    def stop_and_transcribe(self, language: Language = Language.AUTO) -> MeetingResult:
        """Stop recording and transcribe with speaker recognition"""
        recording = self.stop_recording()
        
        if not recording or not self._current_file:
            raise RuntimeError("No recording to transcribe")
        
        # Transcribe
        transcription = self.transcribe(self._current_file, language)
        
        # Diarization for speaker recognition
        speaker_segments = []
        speakers = []
        
        if self.config.voxtral.enable_swiss_german:
            segments = self.diarizer.diarize(self._current_file)
            for seg in segments:
                speaker_name = self.diarizer.get_speaker_name(seg.speaker_id)
                speaker_segments.append({
                    'start': seg.start,
                    'end': seg.end,
                    'speaker_id': seg.speaker_id,
                    'speaker_name': speaker_name
                })
                if speaker_name not in speakers:
                    speakers.append(speaker_name)
        
        # Format transcript with speakers
        formatted_transcript = self._format_transcript_with_speakers(
            transcription.text, speaker_segments
        )
        
        # Upload to cloud
        storage_results = []
        if self.config.storage.auto_upload:
            storage_results = self.storage.upload(self._current_file)
            
            # Also upload transcript
            transcript_file = f"{Path(self._current_file).stem}.txt"
            with open(transcript_file, 'w', encoding='utf-8') as f:
                f.write(formatted_transcript)
            storage_results.extend(self.storage.upload(transcript_file))
        
        end_time = datetime.now()
        duration = (end_time - self._start_time).total_seconds() if self._start_time else 0
        
        result = MeetingResult(
            audio_file=self._current_file,
            transcript=formatted_transcript,
            language=transcription.language,
            confidence=transcription.confidence,
            duration=duration,
            start_time=self._start_time or datetime.now(),
            end_time=end_time,
            speakers=speakers,
            speaker_segments=speaker_segments,
            storage_results=storage_results
        )
        
        self._current_file = None
        self._start_time = None
        
        return result
    
    def _format_transcript_with_speakers(self, text: str, 
                                         segments: List[Dict[str, Any]]) -> str:
        """Format transcript with speaker labels"""
        if not segments:
            return text
        
        lines = []
        current_pos = 0
        
        for seg in sorted(segments, key=lambda x: x['start']):
            # Add text before this segment
            start_idx = int(seg['start'] * 150)  # Approx words per minute
            if start_idx > current_pos:
                lines.append(text[current_pos:start_idx])
            
            # Add speaker label
            speaker = seg.get('speaker_name', seg.get('speaker_id', 'Unknown'))
            lines.append(f"\n[{speaker}]")
            
            current_pos = int(seg['end'] * 150)
        
        # Add remaining text
        if current_pos < len(text):
            lines.append(text[current_pos:])
        
        return ''.join(lines)
    
    def interrupt(self):
        """Handle interruption - pause and process immediately"""
        self._interrupted = True
        
        # Stop current recording
        recording = self.stop_recording()
        
        if recording:
            # Quick transcribe for live feedback
            result = self.transcribe(recording.file_path)
            
            # Diarize
            segments = self.diarizer.diarize(recording.file_path)
            speakers = list(set(seg.speaker_id for seg in segments))
            
            return MeetingResult(
                audio_file=recording.file_path,
                transcript=result.text,
                language=result.language,
                confidence=result.confidence,
                duration=recording.duration,
                start_time=datetime.fromtimestamp(os.path.getmtime(recording.file_path)),
                end_time=datetime.now(),
                speakers=speakers,
                speaker_segments=[{
                    'start': s.start, 'end': s.end, 
                    'speaker_id': s.speaker_id,
                    'speaker_name': self.diarizer.get_speaker_name(s.speaker_id)
                } for s in segments]
            )
        
        return None
    
    def set_speaker_name(self, speaker_id: str, name: str):
        """Set custom name for a speaker"""
        self.diarizer.set_speaker_name(speaker_id, name)
        self._speaker_names[speaker_id] = name
    
    def get_available_devices(self) -> List[dict]:
        """Get available audio devices"""
        return self.audio.get_available_devices()
    
    def set_device(self, device_index: int):
        """Set audio input device"""
        self.audio.close()
        self.config.audio.device_index = device_index
        self.audio = AudioRecorder(self.config.audio)
    
    def close(self):
        """Close all resources"""
        self.audio.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
