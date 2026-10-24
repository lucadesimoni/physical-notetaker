"""
Lean Voxtral 4 transcription with Swiss German support
"""

import os
import time
import asyncio
from typing import Optional, List, Tuple
from dataclasses import dataclass

import httpx
from httpx import AsyncClient, HTTPStatusError

from .config import VoxtralConfig, Language


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    duration: float
    speaker_labels: Optional[List[str]] = None


class VoxtralTranscriber:
    """Voxtral API client for transcription"""
    
    def __init__(self, config: VoxtralConfig):
        self.config = config
        self.client = AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout,
            headers={'Authorization': f'Bearer {config.api_key}'}
        )
    
    async def transcribe(self, audio_file: str, 
                        language: Language = Language.AUTO) -> TranscriptionResult:
        """Transcribe audio file"""
        model = self._get_model(language)
        
        for attempt in range(self.config.timeout // 5):
            try:
                with open(audio_file, 'rb') as f:
                    audio_data = f.read()
                
                start = time.time()
                response = await self.client.post(
                    '/audio/transcriptions',
                    data={'model': model, 'language': language.value},
                    files={'file': (os.path.basename(audio_file), audio_data)}
                )
                response.raise_for_status()
                
                data = response.json()
                return TranscriptionResult(
                    text=data.get('text', ''),
                    language=data.get('language', language.value),
                    confidence=data.get('confidence', 0.0),
                    duration=time.time() - start
                )
            except HTTPStatusError as e:
                if e.response.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except Exception as e:
                if attempt == self.config.timeout // 5 - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        
        raise RuntimeError("Transcription failed")
    
    def _get_model(self, language: Language) -> str:
        if language == Language.DE_CH:
            return "voxtral-4-de-ch"
        return self.config.model
    
    async def close(self):
        await self.client.aclose()
