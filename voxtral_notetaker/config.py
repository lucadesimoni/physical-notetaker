"""
Lean configuration for Voxtral Notetaker
"""

import os
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

import yaml


class Language(Enum):
    EN = "en"
    DE = "de"
    DE_CH = "de-CH"
    AUTO = "auto"


class StorageProvider(Enum):
    LOCAL = "local"
    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"
    S3 = "s3"
    ALL = "all"


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    device_index: Optional[int] = None
    noise_reduction: bool = True


@dataclass
class VoxtralConfig:
    api_key: str = ""
    base_url: str = "https://api.mistral.ai/v1"
    model: str = "voxtral-small-transcribe-3-0"  # Voxtral Small Transcribe 3
    timeout: int = 30
    max_retries: int = 3
    
    def resolved_api_key(self) -> str:
        """API key from config, or the MISTRAL_API_KEY environment variable"""
        return self.api_key or os.environ.get("MISTRAL_API_KEY", "")


@dataclass
class StorageConfig:
    provider: StorageProvider = StorageProvider.LOCAL
    local_path: str = "./recordings"
    google_credentials: Optional[str] = None
    google_folder_id: Optional[str] = None
    dropbox_token: Optional[str] = None
    dropbox_folder: str = "/VoxtralNotetaker"
    s3_bucket: Optional[str] = None
    s3_region: str = "eu-central-1"
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    auto_upload: bool = True


@dataclass
class DiarizationConfig:
    enabled: bool = True
    provider: str = "mistral"  # "mistral" (API, no local model) or "pyannote" (local)
    max_speakers: int = 10
    hf_token: Optional[str] = None


@dataclass
class SummaryConfig:
    """AI summary for the meeting memo (OpenAI-compatible chat API, e.g. Mistral)"""
    enabled: bool = True
    model: str = "mistral-small-2603"  # Mistral Small 4
    base_url: Optional[str] = None  # defaults to voxtral.base_url
    api_key: Optional[str] = None   # defaults to voxtral.api_key
    max_points: int = 8
    timeout: int = 60


@dataclass
class NotetakerConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    voxtral: VoxtralConfig = field(default_factory=VoxtralConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    summary: SummaryConfig = field(default_factory=SummaryConfig)
    max_recording_minutes: int = 120
    
    def save(self, path: str = "config.yaml"):
        with open(path, 'w') as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False)
    
    @classmethod
    def load(cls, path: str = "config.yaml") -> 'NotetakerConfig':
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data or {})
    
    def to_dict(self):
        return {
            'audio': {
                'sample_rate': self.audio.sample_rate,
                'channels': self.audio.channels,
                'device_index': self.audio.device_index,
                'noise_reduction': self.audio.noise_reduction,
            },
            'voxtral': {
                'api_key': self.voxtral.api_key,
                'base_url': self.voxtral.base_url,
                'model': self.voxtral.model,
                'timeout': self.voxtral.timeout,
                'max_retries': self.voxtral.max_retries,
            },
            'storage': {
                'provider': self.storage.provider.value,
                'local_path': self.storage.local_path,
                'google_credentials': self.storage.google_credentials,
                'google_folder_id': self.storage.google_folder_id,
                'dropbox_token': self.storage.dropbox_token,
                'dropbox_folder': self.storage.dropbox_folder,
                's3_bucket': self.storage.s3_bucket,
                's3_region': self.storage.s3_region,
                's3_access_key': self.storage.s3_access_key,
                's3_secret_key': self.storage.s3_secret_key,
                'auto_upload': self.storage.auto_upload,
            },
            'diarization': {
                'enabled': self.diarization.enabled,
                'provider': self.diarization.provider,
                'max_speakers': self.diarization.max_speakers,
                'hf_token': self.diarization.hf_token,
            },
            'summary': {
                'enabled': self.summary.enabled,
                'model': self.summary.model,
                'base_url': self.summary.base_url,
                'api_key': self.summary.api_key,
                'max_points': self.summary.max_points,
                'timeout': self.summary.timeout,
            },
            'max_recording_minutes': self.max_recording_minutes,
        }
    
    @classmethod
    def from_dict(cls, data):
        # Treat empty sections (e.g. "audio:" with no keys) as missing
        data = dict(data or {})
        for section in ('audio', 'voxtral', 'storage', 'diarization', 'summary'):
            data[section] = data.get(section) or {}
        audio = AudioConfig(
            sample_rate=data.get('audio', {}).get('sample_rate', 16000),
            channels=data.get('audio', {}).get('channels', 1),
            device_index=data.get('audio', {}).get('device_index'),
            noise_reduction=data.get('audio', {}).get('noise_reduction', True),
        )
        
        voxtral = VoxtralConfig(
            api_key=data.get('voxtral', {}).get('api_key', ''),
            base_url=data.get('voxtral', {}).get('base_url', 'https://api.mistral.ai/v1'),
            model=data.get('voxtral', {}).get('model', 'voxtral-small-transcribe-3-0'),
            timeout=data.get('voxtral', {}).get('timeout', 30),
            max_retries=data.get('voxtral', {}).get('max_retries', 3),
        )
        
        storage = StorageConfig(
            provider=StorageProvider(data.get('storage', {}).get('provider', 'local')),
            local_path=data.get('storage', {}).get('local_path', './recordings'),
            google_credentials=data.get('storage', {}).get('google_credentials'),
            google_folder_id=data.get('storage', {}).get('google_folder_id'),
            dropbox_token=data.get('storage', {}).get('dropbox_token'),
            dropbox_folder=data.get('storage', {}).get('dropbox_folder', '/VoxtralNotetaker'),
            s3_bucket=data.get('storage', {}).get('s3_bucket'),
            s3_region=data.get('storage', {}).get('s3_region', 'eu-central-1'),
            s3_access_key=data.get('storage', {}).get('s3_access_key'),
            s3_secret_key=data.get('storage', {}).get('s3_secret_key'),
            auto_upload=data.get('storage', {}).get('auto_upload', True),
        )
        
        diarization = DiarizationConfig(
            enabled=data.get('diarization', {}).get('enabled', True),
            provider=data.get('diarization', {}).get('provider', 'mistral'),
            max_speakers=data.get('diarization', {}).get('max_speakers', 10),
            hf_token=data.get('diarization', {}).get('hf_token'),
        )
        
        summary = SummaryConfig(
            enabled=data['summary'].get('enabled', True),
            model=data['summary'].get('model', 'mistral-small-2603'),
            base_url=data['summary'].get('base_url'),
            api_key=data['summary'].get('api_key'),
            max_points=data['summary'].get('max_points', 8),
            timeout=data['summary'].get('timeout', 60),
        )
        
        return cls(
            audio=audio,
            voxtral=voxtral,
            storage=storage,
            diarization=diarization,
            summary=summary,
            max_recording_minutes=data.get('max_recording_minutes', 120),
        )


def load_config(path: Optional[str] = None) -> NotetakerConfig:
    if path and os.path.exists(path):
        return NotetakerConfig.load(path)
    for p in ['config.yaml', 'config.yml']:
        if os.path.exists(p):
            return NotetakerConfig.load(p)
    return NotetakerConfig()


Config = NotetakerConfig
