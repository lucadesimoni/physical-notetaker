# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Voxtral transcription via the Mistral API, with optional speaker diarization
"""

import os
import json
import time
import asyncio
from typing import Optional, List
from dataclasses import dataclass, field, asdict

import httpx
from httpx import AsyncClient, HTTPStatusError

from .config import VoxtralConfig, Language
from .fsutil import atomic_replace


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker_id: Optional[str] = None


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: Optional[float]
    duration: float
    segments: List[TranscriptSegment] = field(default_factory=list)
    
    @property
    def has_speakers(self) -> bool:
        return any(seg.speaker_id for seg in self.segments)


def save_transcription(result: TranscriptionResult, path: str):
    """Keep the raw transcription, so a memo can be remade without paying again"""
    tmp = f"{path}.tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(asdict(result), f, ensure_ascii=False)
    atomic_replace(tmp, path)


def load_transcription(path: str) -> Optional[TranscriptionResult]:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        data['segments'] = [TranscriptSegment(**seg) for seg in data.get('segments') or []]
        return TranscriptionResult(**data)
    except (OSError, ValueError, TypeError):
        return None


# Mistral expects ISO 639-1 codes; Swiss German is transcribed as German
API_LANGUAGE = {Language.EN: 'en', Language.DE: 'de', Language.DE_CH: 'de'}


class VoxtralTranscriber:
    """Mistral audio transcription client (POST /audio/transcriptions)"""
    
    def __init__(self, config: VoxtralConfig):
        self.config = config
    
    def _make_client(self) -> AsyncClient:
        # A fresh client per call: callers may run each transcription in its own event loop
        api_key = self.config.resolved_api_key()
        return AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers={'Authorization': f'Bearer {api_key}', 'x-api-key': api_key}
        )
    
    def _form(self, language: Language, diarize: bool, fast: bool = False) -> dict:
        model = self.config.fast_model if fast and self.config.fast_model else self.config.model
        form = {'model': model}
        if diarize:
            # Speaker labels come with segment timestamps, which the API does
            # not combine with a fixed language, so the language is auto-detected
            form['diarize'] = 'true'
            form['timestamp_granularities'] = 'segment'
        elif language in API_LANGUAGE:
            form['language'] = API_LANGUAGE[language]
        return form
    
    async def transcribe(self, audio_file: str, language: Language = Language.AUTO,
                         diarize: bool = False, fast: bool = False) -> TranscriptionResult:
        """Transcribe audio file (fast=True uses the cheaper fast_model)"""
        with open(audio_file, 'rb') as f:
            audio_data = f.read()
        
        form = self._form(language, diarize, fast)
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
                    return self._parse(response.json(), language, time.time() - start)
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
    
    @staticmethod
    def _parse(data: dict, language: Language, duration: float) -> TranscriptionResult:
        segments = []
        for seg in data.get('segments') or []:
            speaker = seg.get('speaker_id', seg.get('speaker'))
            segments.append(TranscriptSegment(
                start=float(seg.get('start', 0.0)),
                end=float(seg.get('end', 0.0)),
                text=(seg.get('text') or '').strip(),
                speaker_id=str(speaker) if speaker is not None else None,
            ))
        
        text = data.get('text') or ' '.join(seg.text for seg in segments)
        return TranscriptionResult(
            text=text.strip(),
            language=data.get('language') or language.value,
            confidence=data.get('confidence'),
            duration=duration,
            segments=segments,
        )
    
    async def close(self):
        pass
