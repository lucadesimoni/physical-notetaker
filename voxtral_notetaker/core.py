"""
Core notetaker module that ties everything together
"""

import os
import asyncio
import time
from typing import Optional, Dict, Any, List, AsyncGenerator, Union
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import NotetakerConfig, Language, AudioConfig, StorageConfig, EmailConfig
from .audio import AudioRecorder, AudioProcessor, RecordingInfo
from .transcription import VoxtralTranscriber, TranscriptionResult, TranscriptionPostProcessor
from .diarization import SpeakerDiarizer, DiarizationResult
from .storage import CloudStorage, UploadResult
from .email import EmailSender, EmailResult


@dataclass
class MeetingResult:
    """Complete result of a meeting recording and transcription"""
    audio_file: str
    transcript: str
    language: str
    confidence: float
    duration: float
    start_time: datetime
    end_time: datetime
    speaker_segments: List[Any] = field(default_factory=list)
    storage_results: List[UploadResult] = field(default_factory=list)
    email_result: Optional[EmailResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Notetaker:
    """Main notetaker class that coordinates all components"""
    
    def __init__(self, config: Optional[NotetakerConfig] = None):
        # Load or create configuration
        if config:
            self.config = config
        else:
            from .config import load_config
            self.config = load_config()
        
        # Initialize components
        self.audio_recorder = AudioRecorder(self.config.audio)
        self.audio_processor = AudioProcessor(self.config.audio)
        self.transcriber = VoxtralTranscriber(self.config.voxtral)
        self.diarizer = SpeakerDiarizer(self.config.diarization)
        self.storage = CloudStorage(self.config.storage)
        self.email_sender = EmailSender(self.config.email)
        self.post_processor = TranscriptionPostProcessor()
        
        # State
        self._is_recording = False
        self._current_recording: Optional[str] = None
        self._current_start_time: Optional[datetime] = None
        self._speaker_names: Dict[str, str] = {}
    
    def start_recording(self, output_file: Optional[str] = None) -> bool:
        """Start audio recording"""
        if self._is_recording:
            print("Already recording")
            return False
        
        # Determine output file
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"recording_{timestamp}.wav"
        
        # Ensure directory exists
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        
        # Start recording
        success = self.audio_recorder.start_recording(output_file)
        
        if success:
            self._is_recording = True
            self._current_recording = output_file
            self._current_start_time = datetime.now()
            print(f"Started recording to {output_file}")
        
        return success
    
    def stop_recording(self) -> Optional[RecordingInfo]:
        """Stop audio recording"""
        if not self._is_recording:
            print("Not recording")
            return None
        
        result = self.audio_recorder.stop_recording()
        
        if result:
            self._is_recording = False
            self._current_recording = None
            print(f"Stopped recording. Duration: {result.duration:.1f} seconds")
        
        return result
    
    def transcribe(self, audio_file: str, 
                   language: Language = Language.AUTO) -> TranscriptionResult:
        """Transcribe an audio file"""
        import asyncio
        
        # Run async transcription
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            self._transcribe_async(audio_file, language)
        )
        
        return result
    
    async def _transcribe_async(self, audio_file: str, 
                                language: Language = Language.AUTO) -> TranscriptionResult:
        """Async transcription"""
        # Detect language if auto
        if language == Language.AUTO:
            language = await self.transcriber.detect_language(audio_file)
        
        # Transcribe
        result = await self.transcriber.transcribe(audio_file, language)
        
        return result
    
    def stop_and_transcribe(self, language: Language = Language.AUTO) -> MeetingResult:
        """Stop recording and transcribe the audio"""
        # Stop recording
        recording_info = self.stop_recording()
        
        if not recording_info or not self._current_recording:
            raise RuntimeError("No recording to transcribe")
        
        audio_file = self._current_recording
        
        # Transcribe
        transcription = self.transcribe(audio_file, language)
        
        # Perform diarization
        diarization: Optional[DiarizationResult] = None
        if self.config.diarization.enabled:
            diarizer = SpeakerDiarizer(self.config.diarization)
            diarization = diarizer.diarize(audio_file)
        
        # Format transcript with speaker info if available
        formatted_transcript = self.post_processor.format_transcript(
            transcription,
            include_timestamps=True,
            include_speakers=diarization is not None
        )
        
        # Upload to cloud
        storage_results = []
        if self.config.storage.auto_upload:
            storage_results = self.storage.upload(audio_file)
        
        # Create meeting result
        result = MeetingResult(
            audio_file=audio_file,
            transcript=formatted_transcript,
            language=transcription.language,
            confidence=transcription.confidence,
            duration=transcription.duration,
            start_time=self._current_start_time or datetime.now(),
            end_time=datetime.now(),
            speaker_segments=diarization.segments if diarization else [],
            storage_results=storage_results,
            metadata={
                'model': transcription.metadata.get('model'),
                'diarization_enabled': self.config.diarization.enabled,
                'total_speakers': diarization.total_speakers if diarization else 0
            }
        )
        
        # Clear current recording
        self._current_recording = None
        self._current_start_time = None
        
        return result
    
    async def transcribe_live(self, language: Language = Language.AUTO) -> AsyncGenerator[str, None]:
        """Live transcription with streaming"""
        if not self._is_recording:
            self.start_recording()
        
        audio_queue = self.audio_recorder.get_audio_queue()
        
        # For live transcription, we need to buffer audio and send in chunks
        # This is a simplified implementation
        buffer = bytearray()
        last_yield = time.time()
        
        while self._is_recording:
            try:
                # Get audio chunk
                chunk = audio_queue.get(timeout=1.0)
                buffer.extend(chunk.data)
                
                # Every 5 seconds, transcribe the buffer
                if time.time() - last_yield >= 5.0:
                    # Save buffer to temp file
                    temp_file = f"temp_{time.time()}.wav"
                    info = self.audio_processor.save_audio(
                        np.frombuffer(buffer, dtype=np.int16),
                        self.config.audio.sample_rate,
                        temp_file,
                        self.config.audio.format
                    )
                    
                    # Transcribe
                    result = await self.transcriber.transcribe(temp_file, language)
                    
                    # Yield transcript
                    yield result.text
                    
                    # Clean up
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                    
                    # Reset buffer
                    buffer = bytearray()
                    last_yield = time.time()
                    
            except Exception as e:
                print(f"Live transcription error: {e}")
                yield f"[Error: {e}]"
                break
    
    def transcribe_batch(self, files: List[str], 
                        language: Language = Language.AUTO) -> List[MeetingResult]:
        """Transcribe multiple audio files"""
        import asyncio
        
        results = []
        
        for audio_file in files:
            try:
                # Transcribe
                transcription = self.transcribe(audio_file, language)
                
                # Perform diarization
                diarization: Optional[DiarizationResult] = None
                if self.config.diarization.enabled:
                    diarizer = SpeakerDiarizer(self.config.diarization)
                    diarization = diarizer.diarize(audio_file)
                
                # Format transcript
                formatted_transcript = self.post_processor.format_transcript(
                    transcription,
                    include_timestamps=True,
                    include_speakers=diarization is not None
                )
                
                # Upload to cloud
                storage_results = []
                if self.config.storage.auto_upload:
                    storage_results = self.storage.upload(audio_file)
                
                # Create meeting result
                result = MeetingResult(
                    audio_file=audio_file,
                    transcript=formatted_transcript,
                    language=transcription.language,
                    confidence=transcription.confidence,
                    duration=transcription.duration,
                    start_time=datetime.fromtimestamp(os.path.getmtime(audio_file)),
                    end_time=datetime.now(),
                    speaker_segments=diarization.segments if diarization else [],
                    storage_results=storage_results,
                    metadata={
                        'model': transcription.metadata.get('model'),
                        'diarization_enabled': self.config.diarization.enabled,
                        'total_speakers': diarization.total_speakers if diarization else 0
                    }
                )
                
                results.append(result)
                
            except Exception as e:
                print(f"Failed to process {audio_file}: {e}")
                results.append(MeetingResult(
                    audio_file=audio_file,
                    transcript=f"Error: {e}",
                    language="",
                    confidence=0.0,
                    duration=0.0,
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    metadata={'error': str(e)}
                ))
        
        return results
    
    def upload_to_cloud(self, file_path: str, 
                       result: Optional[MeetingResult] = None) -> List[UploadResult]:
        """Upload file to cloud storage"""
        return self.storage.upload(file_path)
    
    def send_email(self, subject: str, 
                   result: Optional[Union[MeetingResult, TranscriptionResult]] = None,
                   to_emails: Optional[List[str]] = None) -> EmailResult:
        """Send email with meeting results"""
        
        if result is None:
            # Just send a simple email
            return self.email_sender.send(
                subject=subject,
                body="Meeting notes email",
                to_emails=to_emails
            )
        
        # Check if it's a MeetingResult or TranscriptionResult
        if isinstance(result, MeetingResult):
            # Create a simple transcription result for email
            from .transcription import TranscriptionResult
            transcription = TranscriptionResult(
                text=result.transcript,
                language=result.language,
                confidence=result.confidence,
                duration=result.duration
            )
            return self.email_sender.send_transcription(transcription, subject, to_emails)
        else:
            return self.email_sender.send_transcription(result, subject, to_emails)
    
    def set_speaker_names(self, names: Dict[str, str]):
        """Set custom names for speaker IDs"""
        self._speaker_names = names
        self.diarizer.set_speaker_names(names)
    
    def get_speaker_names(self) -> Dict[str, str]:
        """Get current speaker names mapping"""
        return self._speaker_names
    
    def get_available_devices(self) -> List[dict]:
        """Get list of available audio input devices"""
        return self.audio_recorder.get_available_devices()
    
    def set_audio_device(self, device_index: int):
        """Set the audio input device"""
        self.audio_recorder.set_device(device_index)
        self.config.audio.device_index = device_index
    
    def get_config(self) -> NotetakerConfig:
        """Get current configuration"""
        return self.config
    
    def save_config(self, path: str = "config.yaml"):
        """Save current configuration"""
        self.config.save(path)
    
    def close(self):
        """Close all resources"""
        self.audio_recorder.close()
        # Note: Async close for transcriber needs to be handled separately
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Convenience function
import numpy as np

def create_notetaker(**kwargs) -> Notetaker:
    """Create a notetaker instance with custom configuration"""
    config = NotetakerConfig()
    
    # Update config from kwargs
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    
    return Notetaker(config)
