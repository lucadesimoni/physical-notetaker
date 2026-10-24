"""
Speaker diarization module for voice recognition and distinction
"""

import os
import numpy as np
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
from pathlib import Path

from pyannote.audio import Pipeline
from pyannote.audio.core import Segment, Annotation

from .config import DiarizationConfig


@dataclass
class SpeakerSegment:
    """Represents a segment of audio with a speaker"""
    start: float  # Start time in seconds
    end: float    # End time in seconds
    speaker_id: str
    speaker_name: Optional[str] = None
    confidence: float = 0.0


@dataclass
class DiarizationResult:
    """Result of speaker diarization"""
    segments: List[SpeakerSegment]
    total_speakers: int
    audio_duration: float
    processing_time: float
    metadata: Optional[Dict[str, Any]] = None


class SpeakerDiarizer:
    """Speaker diarization using pyannote.audio"""
    
    def __init__(self, config: DiarizationConfig):
        self.config = config
        self._pipeline: Optional[Pipeline] = None
        self._speaker_names: Dict[str, str] = {}
        self._initialized = False
    
    def _initialize_pipeline(self):
        """Initialize the pyannote pipeline"""
        if self._initialized:
            return
        
        try:
            # Use the pretrained speaker diarization pipeline
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=None  # Public model
            )
            self._initialized = True
            print("Speaker diarization pipeline initialized")
        except Exception as e:
            print(f"Failed to initialize diarization pipeline: {e}")
            print("Speaker diarization will be disabled")
            self.config.enabled = False
    
    def diarize(self, audio_file: str) -> DiarizationResult:
        """Perform speaker diarization on an audio file"""
        if not self.config.enabled:
            return DiarizationResult(
                segments=[],
                total_speakers=0,
                audio_duration=0.0,
                processing_time=0.0,
                metadata={'enabled': False}
            )
        
        self._initialize_pipeline()
        
        if not self._pipeline:
            return DiarizationResult(
                segments=[],
                total_speakers=0,
                audio_duration=0.0,
                processing_time=0.0,
                metadata={'error': 'Pipeline not initialized'}
            )
        
        try:
            import time
            start_time = time.time()
            
            # Load audio file
            from pyannote.audio import Audio
            audio = Audio()
            
            # Check if file exists
            if not os.path.exists(audio_file):
                raise FileNotFoundError(f"Audio file not found: {audio_file}")
            
            # Get audio duration
            waveform, sample_rate = audio.crop(audio_file)
            audio_duration = len(waveform) / sample_rate
            
            # Apply diarization pipeline
            # Set minimum and maximum number of speakers
            diarization = self._pipeline(
                audio_file,
                min_speakers=self.config.min_speakers,
                max_speakers=self.config.max_speakers,
            )
            
            processing_time = time.time() - start_time
            
            # Convert to SpeakerSegment list
            segments = self._convert_to_segments(diarization)
            
            # Count unique speakers
            unique_speakers = set(seg.speaker_id for seg in segments)
            
            return DiarizationResult(
                segments=segments,
                total_speakers=len(unique_speakers),
                audio_duration=audio_duration,
                processing_time=processing_time,
                metadata={
                    'model': 'pyannote/speaker-diarization-3.1',
                    'sample_rate': sample_rate,
                }
            )
            
        except Exception as e:
            print(f"Diarization failed: {e}")
            return DiarizationResult(
                segments=[],
                total_speakers=0,
                audio_duration=0.0,
                processing_time=0.0,
                metadata={'error': str(e)}
            )
    
    def diarize_audio(self, audio_data: np.ndarray, sample_rate: int) -> DiarizationResult:
        """Perform speaker diarization on audio data"""
        import tempfile
        import wave
        
        # Save audio to temporary file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            temp_file = f.name
            
            with wave.open(temp_file, 'wb') as wf:
                wf.setnchannels(1 if len(audio_data.shape) == 1 else audio_data.shape[1])
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data.tobytes())
        
        try:
            result = self.diarize(temp_file)
            return result
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def _convert_to_segments(self, diarization: Annotation) -> List[SpeakerSegment]:
        """Convert pyannote Annotation to SpeakerSegment list"""
        segments = []
        
        for segment, _, speaker_id in diarization.itertracks(yield_label=True):
            # Get speaker name if available
            speaker_name = self._speaker_names.get(speaker_id, None)
            
            segments.append(SpeakerSegment(
                start=segment.start,
                end=segment.end,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                confidence=1.0  # pyannote doesn't provide confidence by default
            ))
        
        return segments
    
    def set_speaker_names(self, names: Dict[str, str]):
        """Set custom names for speaker IDs"""
        self._speaker_names = names
    
    def get_speaker_names(self) -> Dict[str, str]:
        """Get current speaker names mapping"""
        return self._speaker_names
    
    def merge_overlapping_segments(self, segments: List[SpeakerSegment], 
                                 threshold: float = 0.5) -> List[SpeakerSegment]:
        """Merge overlapping segments from the same speaker"""
        if not segments:
            return segments
        
        # Sort by start time
        sorted_segments = sorted(segments, key=lambda x: x.start)
        merged = []
        
        current = sorted_segments[0]
        for segment in sorted_segments[1:]:
            # Check if segments overlap or are very close
            if (segment.start - current.end) < threshold and segment.speaker_id == current.speaker_id:
                # Merge segments
                current = SpeakerSegment(
                    start=current.start,
                    end=max(current.end, segment.end),
                    speaker_id=current.speaker_id,
                    speaker_name=current.speaker_name,
                    confidence=max(current.confidence, segment.confidence)
                )
            else:
                merged.append(current)
                current = segment
        
        merged.append(current)
        return merged
    
    def assign_speaker_names_auto(self, result: DiarizationResult, 
                                   names: List[str]) -> DiarizationResult:
        """Automatically assign names to speakers"""
        if len(names) < result.total_speakers:
            print(f"Warning: Only {len(names)} names provided for {result.total_speakers} speakers")
        
        # Create mapping
        speaker_ids = sorted(set(seg.speaker_id for seg in result.segments))
        name_mapping = {}
        
        for i, speaker_id in enumerate(speaker_ids[:len(names)]):
            name_mapping[speaker_id] = names[i]
        
        # Update segments
        updated_segments = []
        for seg in result.segments:
            updated_seg = SpeakerSegment(
                start=seg.start,
                end=seg.end,
                speaker_id=seg.speaker_id,
                speaker_name=name_mapping.get(seg.speaker_id, seg.speaker_name),
                confidence=seg.confidence
            )
            updated_segments.append(updated_seg)
        
        return DiarizationResult(
            segments=updated_segments,
            total_speakers=result.total_speakers,
            audio_duration=result.audio_duration,
            processing_time=result.processing_time,
            metadata=result.metadata
        )


class SimpleDiarizer:
    """Simple fallback diarization using energy-based VAD"""
    
    def __init__(self, config: DiarizationConfig):
        self.config = config
    
    def diarize(self, audio_file: str) -> DiarizationResult:
        """Simple diarization based on voice activity detection"""
        try:
            import librosa
            import time
            
            start_time = time.time()
            
            # Load audio
            y, sr = librosa.load(audio_file, sr=None, mono=True)
            
            # Simple VAD using energy
            frames = librosa.util.frame(y, frame_length=2048, hop_length=512)
            energy = np.sum(librosa.feature.rms(y=y, frame_length=2048, hop_length=512), axis=0)
            
            # Normalize energy
            energy = (energy - np.min(energy)) / (np.max(energy) - np.min(energy) + 1e-10)
            
            # Detect speech segments (energy > threshold)
            threshold = 0.1
            speech_frames = energy > threshold
            
            # Convert frames to segments
            segments = []
            current_start = None
            
            for i, is_speech in enumerate(speech_frames):
                if is_speech and current_start is None:
                    current_start = i * 512 / sr  # Convert frame to seconds
                elif not is_speech and current_start is not None:
                    end = i * 512 / sr
                    segments.append(SpeakerSegment(
                        start=current_start,
                        end=end,
                        speaker_id="SPEAKER_001",
                        confidence=0.5
                    ))
                    current_start = None
            
            if current_start is not None:
                end = len(y) / sr
                segments.append(SpeakerSegment(
                    start=current_start,
                    end=end,
                    speaker_id="SPEAKER_001",
                    confidence=0.5
                ))
            
            processing_time = time.time() - start_time
            audio_duration = len(y) / sr
            
            return DiarizationResult(
                segments=segments,
                total_speakers=1,
                audio_duration=audio_duration,
                processing_time=processing_time,
                metadata={'method': 'simple_vad'}
            )
            
        except Exception as e:
            print(f"Simple diarization failed: {e}")
            return DiarizationResult(
                segments=[],
                total_speakers=0,
                audio_duration=0.0,
                processing_time=0.0,
                metadata={'error': str(e)}
            )
