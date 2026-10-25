"""
Lean Voxtral 4 transcription with Swiss German support
"""

import os
import time
import asyncio
from typing import Optional, List
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
    
    def _make_client(self) -> AsyncClient:
        # A fresh client per call: callers may run each transcription in its own event loop
        return AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers={'Authorization': f'Bearer {self.config.api_key}'}
        )
    
    async def transcribe(self, audio_file: str, 
                        language: Language = Language.AUTO) -> TranscriptionResult:
        """Transcribe audio file"""
        model = self._get_model(language)
        
        with open(audio_file, 'rb') as f:
            audio_data = f.read()
        
        form = {'model': model}
        if language != Language.AUTO:
            form['language'] = language.value
        elif self.config.enable_swiss_german and self.config.language_hint:
            form['language_hint'] = self.config.language_hint
        
        retries = max(1, self.config.max_retries)
        async with self._make_client() as client:
            for attempt in range(retries):
                last_attempt = attempt == retries - 1
                try:
                    start = time.time()
                    response = await client.post(
                        '/audio/transcriptions',
                        data=form,
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
                    if e.response.status_code != 429 and e.response.status_code < 500:
                        raise
                    if last_attempt:
                        raise
                except httpx.TransportError:
                    if last_attempt:
                        raise
                await asyncio.sleep(2 ** attempt)
        
        raise RuntimeError("Transcription failed")
    
    def _get_model(self, language: Language) -> str:
        if language == Language.DE_CH and self.config.enable_swiss_german:
            return self.config.swiss_german_model
        return self.config.model
    
    async def close(self):
        pass
