"""
Lean configuration for Voxtral Notetaker
"""

import os
from typing import Optional, List
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


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    device_index: Optional[int] = None
    noise_reduction: bool = True


@dataclass
class VoxtralConfig:
    api_key: str = ""
    base_url: str = "https://api.voxtral.com/v1"
    model: str = "voxtral-4"
    timeout: int = 30
    enable_swiss_german: bool = True
    language_hint: str = "de-CH"


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
class NotetakerConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    voxtral: VoxtralConfig = field(default_factory=VoxtralConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    max_recording_minutes: int = 120
    
    def save(self, path: str = "config.yaml"):
        with open(path, 'w') as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False)
    
    @classmethod
    def load(cls, path: str = "config.yaml") -> 'NotetakerConfig':
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)
    
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
                'enable_swiss_german': self.voxtral.enable_swiss_german,
                'language_hint': self.voxtral.language_hint,
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
            'max_recording_minutes': self.max_recording_minutes,
        }
    
    @classmethod
    def from_dict(cls, data):
        audio = AudioConfig(
            sample_rate=data.get('audio', {}).get('sample_rate', 16000),
            channels=data.get('audio', {}).get('channels', 1),
            device_index=data.get('audio', {}).get('device_index'),
            noise_reduction=data.get('audio', {}).get('noise_reduction', True),
        )
        
        voxtral = VoxtralConfig(
            api_key=data.get('voxtral', {}).get('api_key', ''),
            base_url=data.get('voxtral', {}).get('base_url', 'https://api.voxtral.com/v1'),
            model=data.get('voxtral', {}).get('model', 'voxtral-4'),
            timeout=data.get('voxtral', {}).get('timeout', 30),
            enable_swiss_german=data.get('voxtral', {}).get('enable_swiss_german', True),
            language_hint=data.get('voxtral', {}).get('language_hint', 'de-CH'),
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
        
        return cls(
            audio=audio,
            voxtral=voxtral,
            storage=storage,
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
