"""
Configuration management for Voxtral Notetaker
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import yaml
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv


load_dotenv()


class Language(Enum):
    """Supported languages with Swiss German variants"""
    EN = "en"
    DE = "de"
    DE_CH = "de-CH"  # Swiss German
    FR = "fr"
    FR_CH = "fr-CH"  # Swiss French
    IT = "it"
    IT_CH = "it-CH"  # Swiss Italian
    AUTO = "auto"


class StorageProvider(Enum):
    """Cloud storage providers"""
    LOCAL = "local"
    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"
    S3 = "s3"
    ALL = "all"


class AudioFormat(Enum):
    """Audio recording formats"""
    WAV = "wav"
    MP3 = "mp3"
    FLAC = "flac"
    OGG = "ogg"


@dataclass
class AudioConfig:
    """Audio recording configuration"""
    sample_rate: int = 44100
    channels: int = 1
    format: AudioFormat = AudioFormat.WAV
    chunk_size: int = 1024
    device_index: Optional[int] = None
    auto_gain: bool = True
    noise_reduction: bool = True
    enhancement: bool = True


@dataclass
class VoxtralConfig:
    """Voxtral API configuration"""
    api_key: str = Field(default="", env="VOXTAL_API_KEY")
    base_url: str = "https://api.voxtral.com/v1"
    model: str = "voxtral-4"
    timeout: int = 30
    max_retries: int = 3
    temperature: float = 0.7
    
    # Swiss German specific settings
    enable_swiss_german: bool = True
    swiss_german_model: str = "voxtral-4-de-ch"
    language_hint: str = "de-CH"


@dataclass
class DiarizationConfig:
    """Speaker diarization configuration"""
    enabled: bool = True
    min_speakers: int = 1
    max_speakers: int = 10
    speaker_change_threshold: float = 0.7
    overlap_threshold: float = 0.5
    use_pyannote: bool = True


@dataclass
class StorageConfig:
    """Cloud storage configuration"""
    provider: StorageProvider = StorageProvider.LOCAL
    local_path: str = "./recordings"
    
    # Google Drive
    google_credentials: Optional[str] = None
    google_folder_id: Optional[str] = None
    
    # Dropbox
    dropbox_token: Optional[str] = None
    dropbox_folder: str = "/VoxtralNotetaker"
    
    # S3
    s3_bucket: Optional[str] = None
    s3_region: str = "eu-central-1"
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    
    auto_upload: bool = True
    retain_local: bool = True


@dataclass
class EmailConfig:
    """Email sending configuration"""
    enabled: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    use_tls: bool = True
    
    from_email: str = "notetaker@voxtral.local"
    to_emails: list = field(default_factory=list)
    cc_emails: list = field(default_factory=list)
    bcc_emails: list = field(default_factory=list)
    
    subject_template: str = "Meeting Notes - {date}"
    body_template: str = "Please find attached the meeting notes from {date}.\n\n{transcript}"
    
    send_audio: bool = False
    send_transcript: bool = True
    send_notes: bool = True


@dataclass
class NotetakerConfig:
    """Main configuration class"""
    name: str = "Voxtral Notetaker"
    audio: AudioConfig = field(default_factory=AudioConfig)
    voxtral: VoxtralConfig = field(default_factory=VoxtralConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    
    # Performance settings
    max_recording_hours: int = 8
    auto_split_minutes: int = 30
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "voxtral_notetaker.log"
    
    def save(self, path: str = "config.yaml"):
        """Save configuration to YAML file"""
        with open(path, 'w') as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)
    
    @classmethod
    def load(cls, path: str = "config.yaml") -> 'NotetakerConfig':
        """Load configuration from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'audio': {
                'sample_rate': self.audio.sample_rate,
                'channels': self.audio.channels,
                'format': self.audio.format.value,
                'chunk_size': self.audio.chunk_size,
                'device_index': self.audio.device_index,
                'auto_gain': self.audio.auto_gain,
                'noise_reduction': self.audio.noise_reduction,
                'enhancement': self.audio.enhancement,
            },
            'voxtral': {
                'api_key': self.voxtral.api_key,
                'base_url': self.voxtral.base_url,
                'model': self.voxtral.model,
                'timeout': self.voxtral.timeout,
                'max_retries': self.voxtral.max_retries,
                'temperature': self.voxtral.temperature,
                'enable_swiss_german': self.voxtral.enable_swiss_german,
                'swiss_german_model': self.voxtral.swiss_german_model,
                'language_hint': self.voxtral.language_hint,
            },
            'diarization': {
                'enabled': self.diarization.enabled,
                'min_speakers': self.diarization.min_speakers,
                'max_speakers': self.diarization.max_speakers,
                'speaker_change_threshold': self.diarization.speaker_change_threshold,
                'overlap_threshold': self.diarization.overlap_threshold,
                'use_pyannote': self.diarization.use_pyannote,
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
                'retain_local': self.storage.retain_local,
            },
            'email': {
                'enabled': self.email.enabled,
                'smtp_host': self.email.smtp_host,
                'smtp_port': self.email.smtp_port,
                'smtp_user': self.email.smtp_user,
                'smtp_password': self.email.smtp_password,
                'use_tls': self.email.use_tls,
                'from_email': self.email.from_email,
                'to_emails': self.email.to_emails,
                'cc_emails': self.email.cc_emails,
                'bcc_emails': self.email.bcc_emails,
                'subject_template': self.email.subject_template,
                'body_template': self.email.body_template,
                'send_audio': self.email.send_audio,
                'send_transcript': self.email.send_transcript,
                'send_notes': self.email.send_notes,
            },
            'max_recording_hours': self.max_recording_hours,
            'auto_split_minutes': self.auto_split_minutes,
            'log_level': self.log_level,
            'log_file': self.log_file,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NotetakerConfig':
        """Create from dictionary"""
        audio_data = data.get('audio', {})
        audio = AudioConfig(
            sample_rate=audio_data.get('sample_rate', 44100),
            channels=audio_data.get('channels', 1),
            format=AudioFormat(audio_data.get('format', 'wav')),
            chunk_size=audio_data.get('chunk_size', 1024),
            device_index=audio_data.get('device_index'),
            auto_gain=audio_data.get('auto_gain', True),
            noise_reduction=audio_data.get('noise_reduction', True),
            enhancement=audio_data.get('enhancement', True),
        )
        
        voxtral_data = data.get('voxtral', {})
        voxtral = VoxtralConfig(
            api_key=voxtral_data.get('api_key', ''),
            base_url=voxtral_data.get('base_url', 'https://api.voxtral.com/v1'),
            model=voxtral_data.get('model', 'voxtral-4'),
            timeout=voxtral_data.get('timeout', 30),
            max_retries=voxtral_data.get('max_retries', 3),
            temperature=voxtral_data.get('temperature', 0.7),
            enable_swiss_german=voxtral_data.get('enable_swiss_german', True),
            swiss_german_model=voxtral_data.get('swiss_german_model', 'voxtral-4-de-ch'),
            language_hint=voxtral_data.get('language_hint', 'de-CH'),
        )
        
        diarization_data = data.get('diarization', {})
        diarization = DiarizationConfig(
            enabled=diarization_data.get('enabled', True),
            min_speakers=diarization_data.get('min_speakers', 1),
            max_speakers=diarization_data.get('max_speakers', 10),
            speaker_change_threshold=diarization_data.get('speaker_change_threshold', 0.7),
            overlap_threshold=diarization_data.get('overlap_threshold', 0.5),
            use_pyannote=diarization_data.get('use_pyannote', True),
        )
        
        storage_data = data.get('storage', {})
        storage = StorageConfig(
            provider=StorageProvider(storage_data.get('provider', 'local')),
            local_path=storage_data.get('local_path', './recordings'),
            google_credentials=storage_data.get('google_credentials'),
            google_folder_id=storage_data.get('google_folder_id'),
            dropbox_token=storage_data.get('dropbox_token'),
            dropbox_folder=storage_data.get('dropbox_folder', '/VoxtralNotetaker'),
            s3_bucket=storage_data.get('s3_bucket'),
            s3_region=storage_data.get('s3_region', 'eu-central-1'),
            s3_access_key=storage_data.get('s3_access_key'),
            s3_secret_key=storage_data.get('s3_secret_key'),
            auto_upload=storage_data.get('auto_upload', True),
            retain_local=storage_data.get('retain_local', True),
        )
        
        email_data = data.get('email', {})
        email = EmailConfig(
            enabled=email_data.get('enabled', True),
            smtp_host=email_data.get('smtp_host', 'smtp.gmail.com'),
            smtp_port=email_data.get('smtp_port', 587),
            smtp_user=email_data.get('smtp_user'),
            smtp_password=email_data.get('smtp_password'),
            use_tls=email_data.get('use_tls', True),
            from_email=email_data.get('from_email', 'notetaker@voxtral.local'),
            to_emails=email_data.get('to_emails', []),
            cc_emails=email_data.get('cc_emails', []),
            bcc_emails=email_data.get('bcc_emails', []),
            subject_template=email_data.get('subject_template', 'Meeting Notes - {date}'),
            body_template=email_data.get('body_template', 'Please find attached the meeting notes from {date}.\n\n{transcript}'),
            send_audio=email_data.get('send_audio', False),
            send_transcript=email_data.get('send_transcript', True),
            send_notes=email_data.get('send_notes', True),
        )
        
        return cls(
            name=data.get('name', 'Voxtral Notetaker'),
            audio=audio,
            voxtral=voxtral,
            diarization=diarization,
            storage=storage,
            email=email,
            max_recording_hours=data.get('max_recording_hours', 8),
            auto_split_minutes=data.get('auto_split_minutes', 30),
            log_level=data.get('log_level', 'INFO'),
            log_file=data.get('log_file', 'voxtral_notetaker.log'),
        )


# Global configuration instance
config = NotetakerConfig()


def load_config(path: Optional[str] = None) -> NotetakerConfig:
    """Load configuration from file or create default"""
    global config
    
    if path:
        if os.path.exists(path):
            config = NotetakerConfig.load(path)
        else:
            config = NotetakerConfig()
            config.save(path)
    else:
        # Try to load from default locations
        for p in ['config.yaml', 'config.yml', '/etc/voxtral_notetaker.yaml']:
            if os.path.exists(p):
                config = NotetakerConfig.load(p)
                break
        else:
            config = NotetakerConfig()
    
    return config
