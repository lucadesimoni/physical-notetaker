"""
Core Notetaker - Lean implementation for conference transcription
"""

import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import NotetakerConfig, Language
from .audio import AudioRecorder, RecordingInfo
from .transcription import VoxtralTranscriber, TranscriptionResult
from .diarization import SpeakerDiarizer
from .storage import CloudStorage, UploadResult
from .commands import CommandParser, CommandExecutor, CommandResult
from .memo import Memo, Summarizer


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
    memo: Optional[Memo] = None
    memo_file: Optional[str] = None


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
        self.diarizer = SpeakerDiarizer(auth_token=self.config.diarization.hf_token)
        self.storage = CloudStorage(self.config.storage)
        self.summarizer = Summarizer(self.config.summary, self.config.voxtral)
        
        # State
        self._is_recording = False
        self._current_file: Optional[str] = None
        self._start_time: Optional[datetime] = None
        self._interrupted = False
        self._speaker_names: Dict[str, str] = {}
        
        # Command processing
        self._command_parser = CommandParser()
        self._command_executor = CommandExecutor(self)
    
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
        return asyncio.run(self.transcriber.transcribe(audio_file, language))
    
    def stop_and_transcribe(self, language: Language = Language.AUTO,
                            diarize: Optional[bool] = None) -> MeetingResult:
        """Stop recording and transcribe with speaker recognition"""
        recording = self.stop_recording()
        
        if not recording or not self._current_file:
            raise RuntimeError("No recording to transcribe")
        
        if diarize is None:
            diarize = self.config.diarization.enabled
        
        # Transcribe
        transcription = self.transcribe(self._current_file, language)
        
        # Diarization for speaker recognition
        speaker_segments = []
        speakers = []
        
        if diarize:
            segments = self.diarizer.diarize(
                self._current_file, max_speakers=self.config.diarization.max_speakers
            )
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
        
        end_time = datetime.now()
        duration = (end_time - self._start_time).total_seconds() if self._start_time else 0
        
        # Voice commands spoken during the meeting -> notes, tasks, research
        self._command_executor.extract_from_transcript(
            formatted_transcript, transcription.language, self._start_time
        )
        memo = self.build_memo(
            transcript=formatted_transcript,
            language=transcription.language,
            participants=speakers,
            date=self._start_time,
            duration_seconds=duration,
        )
        
        # Save transcript and memo next to the recording
        audio_path = Path(self._current_file)
        transcript_file = str(audio_path.with_suffix('.txt'))
        memo_file = str(audio_path.with_name(f"{audio_path.stem}_memo.md"))
        with open(transcript_file, 'w', encoding='utf-8') as f:
            f.write(formatted_transcript)
        with open(memo_file, 'w', encoding='utf-8') as f:
            f.write(memo.to_markdown())
        
        # Upload to cloud
        storage_results = []
        if self.config.storage.auto_upload:
            for path in (self._current_file, transcript_file, memo_file):
                storage_results.extend(self.storage.upload(path))
        
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
            storage_results=storage_results,
            memo=memo,
            memo_file=memo_file
        )
        
        self._current_file = None
        self._start_time = None
        
        return result
    
    def _format_transcript_with_speakers(self, text: str, 
                                         segments: List[Dict[str, Any]]) -> str:
        """Format transcript with speaker labels"""
        if not segments:
            return text
        
        # The transcript carries no timestamps, so approximate each segment's
        # share of the text by its position within the total audio duration.
        ordered = sorted(segments, key=lambda x: x['start'])
        total = max(seg['end'] for seg in ordered)
        if total <= 0:
            return text
        
        def boundary(t: float) -> int:
            # Snap to the next whitespace so words are never split
            idx = int(t / total * len(text))
            while 0 < idx < len(text) and not text[idx].isspace():
                idx += 1
            return idx
        
        lines = []
        prev_speaker = None
        for i, seg in enumerate(ordered):
            start_idx = boundary(seg['start'])
            end_idx = len(text) if i == len(ordered) - 1 else boundary(ordered[i + 1]['start'])
            chunk = text[start_idx:end_idx].strip()
            if not chunk:
                continue
            
            speaker = seg.get('speaker_name') or seg.get('speaker_id', 'Unknown')
            if speaker != prev_speaker:
                lines.append(f"[{speaker}] {chunk}")
                prev_speaker = speaker
            else:
                lines[-1] += f" {chunk}"
        
        return '\n'.join(lines) if lines else text
    
    def interrupt(self):
        """Handle interruption - pause and process immediately"""
        self._interrupted = True
        
        # Stop current recording
        start_time = self._start_time
        recording = self.stop_recording()
        self._current_file = None
        self._start_time = None
        
        if recording:
            # Quick transcribe for live feedback
            result = self.transcribe(recording.file_path)
            
            # Diarize
            segments = []
            if self.config.diarization.enabled:
                segments = self.diarizer.diarize(
                    recording.file_path, max_speakers=self.config.diarization.max_speakers
                )
            speakers = list(dict.fromkeys(
                self.diarizer.get_speaker_name(seg.speaker_id) for seg in segments
            ))
            
            return MeetingResult(
                audio_file=recording.file_path,
                transcript=result.text,
                language=result.language,
                confidence=result.confidence,
                duration=recording.duration,
                start_time=start_time or datetime.now(),
                end_time=datetime.now(),
                speakers=speakers,
                speaker_segments=[{
                    'start': s.start, 'end': s.end, 
                    'speaker_id': s.speaker_id,
                    'speaker_name': self.diarizer.get_speaker_name(s.speaker_id)
                } for s in segments]
            )
        
        return None
    
    def process_command(self, text: str, language: str = "auto",
                        speaker: Optional[str] = None) -> Optional[CommandResult]:
        """Process a voice command (German or English)"""
        return self._command_executor.execute(text, language, speaker=speaker)
    
    def extract_commands(self, transcript: str, language: str = "auto",
                         timestamp: Optional[datetime] = None) -> List[CommandResult]:
        """Collect notes, tasks and research spoken in a finished transcript"""
        return self._command_executor.extract_from_transcript(transcript, language, timestamp)
    
    def build_memo(self, transcript: Optional[str] = None, language: str = "de-CH",
                   title: Optional[str] = None, participants: Optional[List[str]] = None,
                   date: Optional[datetime] = None, duration_seconds: Optional[float] = None,
                   summarize: bool = True) -> Memo:
        """Build a meeting memo from everything captured so far"""
        date = date or self._start_time or datetime.now()
        if not title:
            title = ("Besprechung" if language.lower().startswith('de') else "Meeting") \
                + f" {date.strftime('%d.%m.%Y %H:%M')}"
        
        summary = []
        if summarize and transcript:
            summary = self.summarizer.summarize(transcript, language)
        
        if participants is None:
            participants = list(self._speaker_names.values())
        
        return Memo(
            title=title,
            language=language,
            date=date,
            participants=participants,
            duration_seconds=duration_seconds,
            summary=summary,
            notes=list(self.get_notes()),
            tasks=list(self.get_tasks()),
            research=list(self.get_research_queries()),
        )
    
    def get_notes(self) -> List[Dict[str, Any]]:
        """Get all notes created from voice commands"""
        return self._command_executor.get_notes()
    
    def get_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks created from voice commands"""
        return self._command_executor.get_tasks()
    
    def get_research_queries(self) -> List[Dict[str, Any]]:
        """Get all research queries from voice commands"""
        return self._command_executor.get_research_queries()
    
    def clear_commands(self):
        """Clear all saved commands"""
        self._command_executor.clear_all()
    
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
