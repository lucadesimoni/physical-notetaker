"""
Lean configuration for Voxtral Notetaker
"""

import os
from typing import Optional, List
from dataclasses import dataclass, field, fields
from enum import Enum

import yaml

from .fsutil import atomic_replace


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
    # Accurate model for the final meeting transcript, memo and speaker labels
    model: str = "voxtral-small-transcribe-3-0"  # Voxtral Small Transcribe 3
    # Fast, cheaper model for quick interim transcripts ("Moment bitte")
    fast_model: str = "voxtral-mini-transcribe-3-0"  # Voxtral Mini Transcribe 3
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
    # Name speakers from introductions like "Ich bin Anna" / "My name is Anna"
    detect_names: bool = True


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
class EmailConfig:
    """Send the memo by email after each meeting"""
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # or the NOTETAKER_SMTP_PASSWORD environment variable
    use_tls: bool = True     # STARTTLS on smtp_port (port 465 uses SSL automatically)
    from_email: str = ""
    to_emails: List[str] = field(default_factory=list)
    attach_transcript: bool = True
    attach_audio: bool = False

    def resolved_password(self) -> str:
        return self.smtp_password or os.environ.get("NOTETAKER_SMTP_PASSWORD", "")

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.smtp_host and self.to_emails)


@dataclass
class DeviceConfig:
    """Physical controls and feedback for the meeting device"""
    beeps: bool = True                 # play tones through the speakerphone
    beep_volume: float = 0.3
    voice: bool = True                 # spoken announcements (espeak-ng or Piper)
    piper_model: str = ""              # optional Piper voice (.onnx) for a nicer voice
    long_press_seconds: float = 3.0    # hold the button: the device says its address
    button_gpio: Optional[int] = None  # GPIO pin of a start/stop push button
    led_gpio: Optional[int] = None     # GPIO pin of a status LED
    # Buttons on a USB device (e.g. the speakerphone's call button), via evdev
    input_device: str = "jabra"        # match on the input device name; "" disables
    input_keys: List[str] = field(default_factory=lambda: ["KEY_PHONE", "KEY_PLAYPAUSE"])


@dataclass
class ServiceConfig:
    """Background service: autostart, crash recovery and the processing queue"""
    recordings_dir: str = "./recordings"
    language: str = "auto"              # meeting language: auto, de, de-CH, en
    ui_language: str = "de"             # web page and announcements: de or en
    retry_interval_seconds: int = 300   # first retry after a failure; doubles up to 1 hour
    max_attempts: int = 0               # 0 = keep retrying network errors
    keep_audio_days: int = 30           # delete audio of finished meetings after N days (0 = never)
    min_free_mb: int = 500              # free space to keep; oldest finished audio goes first
    live_commands: bool = True          # confirm voice commands during the meeting
    live_interval_seconds: int = 30     # how often new audio is checked (fast Mini model)


@dataclass
class WebConfig:
    """Setup and status page for a phone or laptop on the same network"""
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    pin: str = ""  # required to change settings; chosen on the first visit
    # No network at boot: open a Wi-Fi hotspot so a phone can reach the setup page
    setup_hotspot: bool = True
    hotspot_ssid: str = "Notetaker-Setup"
    hotspot_password: str = "notetaker"  # at least 8 characters (WPA2)


SECTIONS = {
    'audio': AudioConfig,
    'voxtral': VoxtralConfig,
    'storage': StorageConfig,
    'diarization': DiarizationConfig,
    'summary': SummaryConfig,
    'email': EmailConfig,
    'device': DeviceConfig,
    'service': ServiceConfig,
    'web': WebConfig,
}


def _section_to_dict(section) -> dict:
    out = {}
    for f in fields(section):
        value = getattr(section, f.name)
        out[f.name] = value.value if isinstance(value, Enum) else value
    return out


def _section_from_dict(cls, data: Optional[dict]):
    """Build a section from YAML data; missing or empty keys keep their default"""
    data = data or {}
    kwargs = {}
    for f in fields(cls):
        value = data.get(f.name)
        if value is None:
            continue
        if isinstance(f.default, Enum):
            value = type(f.default)(value)
        kwargs[f.name] = value
    return cls(**kwargs)


@dataclass
class NotetakerConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    voxtral: VoxtralConfig = field(default_factory=VoxtralConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    summary: SummaryConfig = field(default_factory=SummaryConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)
    web: WebConfig = field(default_factory=WebConfig)
    max_recording_minutes: int = 120

    def save(self, path: str = "config.yaml"):
        tmp = f"{path}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False, allow_unicode=True)
        atomic_replace(tmp, path)  # never leave a half-written config behind

    @classmethod
    def load(cls, path: str = "config.yaml") -> 'NotetakerConfig':
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data or {})

    def to_dict(self):
        out = {name: _section_to_dict(getattr(self, name)) for name in SECTIONS}
        out['max_recording_minutes'] = self.max_recording_minutes
        return out

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        sections = {name: _section_from_dict(section_cls, data.get(name))
                    for name, section_cls in SECTIONS.items()}
        return cls(**sections, max_recording_minutes=data.get('max_recording_minutes') or 120)


def find_config_path(path: Optional[str] = None) -> str:
    """The config file to use: explicit path, $NOTETAKER_CONFIG, or ./config.yaml"""
    if path:
        return path
    if os.environ.get("NOTETAKER_CONFIG"):
        return os.environ["NOTETAKER_CONFIG"]
    for p in ['config.yaml', 'config.yml']:
        if os.path.exists(p):
            return p
    return 'config.yaml'


def load_config(path: Optional[str] = None) -> NotetakerConfig:
    path = find_config_path(path)
    if os.path.exists(path):
        return NotetakerConfig.load(path)
    return NotetakerConfig()


Config = NotetakerConfig
