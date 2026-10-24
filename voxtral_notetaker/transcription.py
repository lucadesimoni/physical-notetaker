"""
Voxtral 4 transcription module with Swiss German support
"""

import os
import json
import time
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from pathlib import Path

import httpx
from httpx import AsyncClient, HTTPStatusError

from .config import VoxtralConfig, Language


@dataclass
class TranscriptionResult:
    """Result of transcription"""
    text: str
    language: str
    confidence: float
    duration: float
    timestamps: Optional[List[Tuple[float, float, str]]] = None  # (start, end, text)
    speaker_labels: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class Speaker:
    """Speaker information"""
    id: str
    name: Optional[str] = None
    confidence: float = 0.0


class VoxtralTranscriber:
    """Voxtral API client for transcription"""
    
    def __init__(self, config: VoxtralConfig):
        self.config = config
        self.client = AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout,
            headers={
                'Authorization': f'Bearer {config.api_key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        self._retry_count = 0
    
    async def transcribe(self, 
                       audio_file: str, 
                       language: Language = Language.AUTO,
                       prompt: Optional[str] = None,
                       temperature: Optional[float] = None) -> TranscriptionResult:
        """Transcribe audio file using Voxtral API"""
        
        # Determine model based on language
        model = self._get_model(language)
        
        # Prepare request
        payload = {
            'model': model,
            'temperature': temperature or self.config.temperature,
        }
        
        if prompt:
            payload['prompt'] = prompt
        
        # Add Swiss German hint if enabled
        if self.config.enable_swiss_german and language in [Language.DE_CH, Language.AUTO]:
            payload['language_hint'] = self.config.language_hint
        
        # Read audio file
        try:
            with open(audio_file, 'rb') as f:
                audio_data = f.read()
        except Exception as e:
            raise ValueError(f"Failed to read audio file: {e}")
        
        # Prepare files for multipart request
        files = {
            'file': (os.path.basename(audio_file), audio_data)
        }
        
        # Send request with retry logic
        for attempt in range(self.config.max_retries):
            try:
                start_time = time.time()
                
                response = await self.client.post(
                    '/audio/transcriptions',
                    data={'model': model, **payload},
                    files=files
                )
                
                response.raise_for_status()
                
                result_data = response.json()
                
                duration = time.time() - start_time
                
                # Parse result
                text = result_data.get('text', '')
                detected_language = result_data.get('language', language.value)
                confidence = result_data.get('confidence', 0.0)
                
                return TranscriptionResult(
                    text=text,
                    language=detected_language,
                    confidence=confidence,
                    duration=duration,
                    timestamps=self._parse_timestamps(result_data),
                    speaker_labels=self._parse_speaker_labels(result_data),
                    metadata={'model': model, 'attempt': attempt + 1}
                )
                
            except HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    wait_time = 2 ** attempt
                    print(f"Rate limited, waiting {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                elif e.response.status_code >= 500:  # Server error
                    wait_time = 2 ** attempt
                    print(f"Server error, retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except Exception as e:
                if attempt == self.config.max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                print(f"Error: {e}, retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
        
        raise RuntimeError("Failed to transcribe after maximum retries")
    
    async def transcribe_stream(self, 
                               audio_stream: AsyncClient,
                               language: Language = Language.AUTO,
                               prompt: Optional[str] = None) -> AsyncClient:
        """Create streaming transcription"""
        model = self._get_model(language)
        
        payload = {
            'model': model,
            'temperature': self.config.temperature,
        }
        
        if prompt:
            payload['prompt'] = prompt
        
        if self.config.enable_swiss_german and language in [Language.DE_CH, Language.AUTO]:
            payload['language_hint'] = self.config.language_hint
        
        # Create streaming request
        response = await self.client.post(
            '/audio/transcriptions/stream',
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        
        response.raise_for_status()
        return response
    
    async def transcribe_batch(self, 
                             audio_files: List[str],
                             language: Language = Language.AUTO) -> List[TranscriptionResult]:
        """Transcribe multiple audio files in batch"""
        tasks = []
        for audio_file in audio_files:
            task = asyncio.create_task(
                self.transcribe(audio_file, language)
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        final_results = []
        for result in results:
            if isinstance(result, Exception):
                print(f"Failed to transcribe: {result}")
                final_results.append(TranscriptionResult(
                    text="",
                    language=language.value,
                    confidence=0.0,
                    duration=0.0,
                    metadata={'error': str(result)}
                ))
            else:
                final_results.append(result)
        
        return final_results
    
    def _get_model(self, language: Language) -> str:
        """Get the appropriate model for the language"""
        if language == Language.DE_CH:
            return self.config.swiss_german_model
        elif language in [Language.DE, Language.FR_CH, Language.IT_CH]:
            # Use multilingual model
            return f"{self.config.model}-multilingual"
        return self.config.model
    
    def _parse_timestamps(self, data: Dict[str, Any]) -> Optional[List[Tuple[float, float, str]]]:
        """Parse word-level timestamps"""
        if 'timestamps' not in data:
            return None
        
        timestamps = []
        for ts in data['timestamps']:
            timestamps.append((
                ts.get('start', 0.0),
                ts.get('end', 0.0),
                ts.get('text', '')
            ))
        return timestamps
    
    def _parse_speaker_labels(self, data: Dict[str, Any]) -> Optional[List[str]]:
        """Parse speaker labels"""
        if 'speaker_labels' not in data:
            return None
        return data['speaker_labels']
    
    async def detect_language(self, audio_file: str) -> Language:
        """Detect language from audio file"""
        try:
            # Use a small sample for language detection
            result = await self.transcribe(
                audio_file,
                language=Language.AUTO,
                prompt="Detect the language being spoken."
            )
            
            detected = result.language
            
            # Map to Language enum
            if detected == 'de-CH':
                return Language.DE_CH
            elif detected == 'de':
                return Language.DE
            elif detected == 'fr-CH':
                return Language.FR_CH
            elif detected == 'fr':
                return Language.FR
            elif detected == 'it-CH':
                return Language.IT_CH
            elif detected == 'it':
                return Language.IT
            else:
                return Language.EN
                
        except Exception as e:
            print(f"Language detection failed: {e}")
            return Language.AUTO
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class TranscriptionPostProcessor:
    """Post-process transcription results"""
    
    def __init__(self):
        self._swiss_german_corrections = {
            # Common Swiss German to Standard German corrections
            'ch': 'k',  # "Ch" at end of words
            'ä': 'ae',
            'ö': 'oe',
            'ü': 'ue',
            'ß': 'ss',
        }
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove multiple spaces
        text = ' '.join(text.split())
        
        # Trim whitespace
        text = text.strip()
        
        return text
    
    def format_transcript(self, result: TranscriptionResult, 
                         include_timestamps: bool = True,
                         include_speakers: bool = True) -> str:
        """Format transcription result as readable text"""
        lines = []
        
        if include_timestamps and result.timestamps:
            for start, end, text in result.timestamps:
                time_str = f"[{self._format_time(start)} - {self._format_time(end)}]"
                if include_speakers and result.speaker_labels:
                    speaker = result.speaker_labels[0] if result.speaker_labels else "Unknown"
                    lines.append(f"{time_str} {speaker}: {text}")
                else:
                    lines.append(f"{time_str} {text}")
        else:
            if include_speakers and result.speaker_labels:
                # Group by speaker
                speaker_texts = {}
                for i, label in enumerate(result.speaker_labels):
                    if label not in speaker_texts:
                        speaker_texts[label] = []
                    if result.timestamps and i < len(result.timestamps):
                        speaker_texts[label].append(result.timestamps[i][2])
                    else:
                        speaker_texts[label].append("")
                
                for speaker, texts in speaker_texts.items():
                    lines.append(f"\n{speaker}:")
                    for text in texts:
                        lines.append(f"  {text}")
            else:
                lines.append(result.text)
        
        return '\n'.join(lines)
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def extract_key_points(self, text: str, max_points: int = 5) -> List[str]:
        """Extract key points from transcription"""
        # Simple implementation - split by paragraphs and take first sentences
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        key_points = []
        
        for para in paragraphs[:max_points]:
            sentences = [s.strip() for s in para.split('.') if s.strip()]
            if sentences:
                key_points.append(sentences[0] + '.')
        
        return key_points
    
    def generate_summary(self, result: TranscriptionResult, 
                        max_length: int = 500) -> str:
        """Generate a summary of the transcription"""
        text = result.text
        
        if len(text) <= max_length:
            return text
        
        # Simple summary: first paragraph + last paragraph
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        
        if len(paragraphs) <= 1:
            return text[:max_length] + "..."
        
        summary = paragraphs[0]
        if len(summary) < max_length - 100:
            summary += " ... " + paragraphs[-1]
        
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."
        
        return summary
