# Voxtral Notetaker - Raspberry Pi Based Meeting Notes System

**Advanced, lightweight, and precise meeting notes recognition and transcription system using Voxtral 4**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-Compatible-green.svg)](https://www.raspberrypi.org/)
[![Voxtral 4](https://img.shields.io/badge/Voxtral-4-orange.svg)](https://voxtral.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

### Core Capabilities
- ✅ **Voxtral 4 Transcription** - State-of-the-art speech-to-text with superior accuracy
- ✅ **Swiss German Support** - Native support for Swiss German (de-CH) and other Swiss languages
- ✅ **Multi-Microphone Support** - Works with Jabra Spiders, USB microphones, and built-in audio
- ✅ **Real-time Processing** - Transcribe meetings as they happen
- ✅ **Batch Processing** - Process recorded audio files in bulk

### Advanced Audio Features
- ✅ **Speaker Diarization** - Automatically identify and distinguish between multiple speakers
- ✅ **Noise Reduction** - Advanced algorithms to reduce background noise
- ✅ **Audio Enhancement** - Improve audio quality for better transcription
- ✅ **Auto Gain Control** - Automatic volume normalization
- ✅ **Multiple Audio Formats** - Support for WAV, MP3, FLAC, OGG

### Speaker Recognition
- ✅ **Voice Distinction** - Accurately distinguish between speakers in chaotic discussions
- ✅ **Speaker Labeling** - Assign speaker IDs and optionally names
- ✅ **Overlap Handling** - Handle overlapping speech in loud discussions
- ✅ **Configurable Thresholds** - Adjust speaker change sensitivity

### Cloud & Storage
- ✅ **Local Storage** - Save recordings and transcripts locally
- ✅ **Google Drive Integration** - Automatic upload to Google Drive
- ✅ **Dropbox Integration** - Sync with Dropbox
- ✅ **Amazon S3 Support** - Store in AWS S3 buckets
- ✅ **Multi-Cloud Sync** - Upload to multiple cloud providers simultaneously

### Sharing & Distribution
- ✅ **Email Sending** - Automatically send transcripts via email
- ✅ **Customizable Templates** - Configure email subjects and body
- ✅ **Multiple Recipients** - Send to multiple email addresses
- ✅ **Attachment Options** - Send audio files, transcripts, or both

### Performance
- ✅ **Lightweight** - Optimized for Raspberry Pi (all models)
- ✅ **Efficient** - Minimal resource usage
- ✅ **Reliable** - Automatic retry for failed transcriptions
- ✅ **Scalable** - Process long meetings with automatic splitting

## Quick Start

### Prerequisites

- **Hardware**: Raspberry Pi (any model with audio input or USB microphone)
- **Microphone**: Any USB microphone (Jabra Spider, etc.) or built-in audio
- **Python**: 3.9 or higher
- **Internet Connection**: Required for Voxtral API access

### Installation

```bash
# Clone the repository
git clone https://github.com/lucadesimoni/physical-notetaker.git
cd physical-notetaker

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install PyAudio (may require system dependencies)
# On Raspberry Pi:
sudo apt-get install portaudio19-dev python3-pyaudio
pip install pyaudio

# For speaker diarization:
pip install pyannote.audio
```

### Configuration

1. **Create configuration file**:
```bash
# Create config from template
cp config.example.yaml config.yaml

# Or use the setup command
python -m voxtral_notetaker setup
```

2. **Edit `config.yaml`**:
```yaml
# Voxtral API Configuration
voxtral:
  api_key: "your-voxtral-api-key"  # Get from https://voxtral.com
  model: "voxtral-4"
  enable_swiss_german: true
  swiss_german_model: "voxtral-4-de-ch"
  language_hint: "de-CH"

# Audio Configuration
audio:
  sample_rate: 44100
  channels: 1
  format: wav
  noise_reduction: true
  enhancement: true

# Speaker Diarization
diarization:
  enabled: true
  max_speakers: 10
  use_pyannote: true

# Storage Configuration
storage:
  provider: local  # or google_drive, dropbox, s3
  local_path: "./recordings"
  auto_upload: true

# Email Configuration
email:
  enabled: true
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  smtp_user: "your-email@gmail.com"
  smtp_password: "your-app-password"
  to_emails:
    - "recipient1@example.com"
    - "recipient2@example.com"
```

3. **Set environment variables** (optional):
```bash
# Create .env file
echo "VOXTAL_API_KEY=your-api-key" > .env
echo "SMTP_PASSWORD=your-password" >> .env
```

### Usage

#### Command Line Interface

```bash
# Start a new recording
python -m voxtral_notetaker record --output meeting.wav

# Start recording with live transcription
python -m voxtral_notetaker record --live --output meeting.wav

# Process an existing audio file
python -m voxtral_notetaker transcribe --file meeting.wav --output transcript.txt

# Process and send via email
python -m voxtral_notetaker transcribe --file meeting.wav --email

# List available audio devices
python -m voxtral_notetaker devices

# Run setup wizard
python -m voxtral_notetaker setup
```

#### Python API

```python
from voxtral_notetaker import Notetaker, Config

# Load configuration
config = Config.load()

# Create notetaker instance
notetaker = Notetaker(config)

# Start recording
notetaker.start_recording("meeting.wav")

# ... during meeting ...

# Stop and transcribe
result = notetaker.stop_and_transcribe()

# Get transcript
print(result.text)

# Send via email
notetaker.send_email("Meeting Notes", result)

# Upload to cloud
notetaker.upload_to_cloud("meeting.wav", result)
```

### Advanced Usage

#### Real-time Transcription

```python
import asyncio
from voxtral_notetaker import Notetaker

async def live_transcribe():
    notetaker = Notetaker()
    
    # Start streaming transcription
    async for transcript in notetaker.transcribe_live():
        print(transcript)

asyncio.run(live_transcribe())
```

#### Batch Processing

```python
from voxtral_notetaker import Notetaker

notetaker = Notetaker()

# Process all WAV files in a directory
results = notetaker.transcribe_batch(
    ["meeting1.wav", "meeting2.wav", "meeting3.wav"],
    language="de-CH"
)

for result in results:
    print(f"File: {result.file_path}")
    print(f"Transcript: {result.text}")
```

#### Swiss German Transcription

```python
from voxtral_notetaker import Notetaker, Language

notetaker = Notetaker()

# Transcribe with Swiss German
result = notetaker.transcribe(
    "swiss_meeting.wav",
    language=Language.DE_CH
)

print(result.text)
```

## Microphone Setup

### Supported Microphones

- **Jabra Spider** - Professional conference microphone
- **Jabra Speak Series** - USB conference speakers
- **Any USB Microphone** - Works with most USB microphones
- **Built-in Audio** - Raspberry Pi audio input

### Jabra Spider Setup

1. Connect Jabra Spider to Raspberry Pi via USB
2. Verify detection:
```bash
python -m voxtral_notetaker devices
```
3. Select device in config:
```yaml
audio:
  device_index: 1  # Use the index from devices command
```

### Multiple Microphones

For better coverage in large rooms, use multiple microphones:

```python
from voxtral_notetaker import AudioRecorder, AudioConfig

# Create multiple recorders
config1 = AudioConfig(device_index=1)  # First microphone
config2 = AudioConfig(device_index=2)  # Second microphone

recorder1 = AudioRecorder(config1)
recorder2 = AudioRecorder(config2)

# Start both
recorder1.start_recording("mic1.wav")
recorder2.start_recording("mic2.wav")

# Merge audio files for transcription
# (See audio processing utilities)
```

## Speaker Diarization

The system automatically identifies and distinguishes between speakers:

### Configuration Options

```yaml
diarization:
  enabled: true
  min_speakers: 1
  max_speakers: 10
  speaker_change_threshold: 0.7  # Higher = less sensitive
  overlap_threshold: 0.5
  use_pyannote: true  # Use pyannote.audio for diarization
```

### Custom Speaker Names

```python
from voxtral_notetaker import Notetaker

notetaker = Notetaker()

# Set speaker names
notetaker.set_speaker_names({
    "SPEAKER_001": "John Doe",
    "SPEAKER_002": "Jane Smith",
    "SPEAKER_003": "Bob Johnson"
})

result = notetaker.transcribe("meeting.wav")

# Speaker-labeled transcript
for speaker, text in result.speaker_transcript.items():
    print(f"{speaker}: {text}")
```

## Cloud Storage

### Google Drive

1. **Create Google Cloud Project**
   - Go to https://console.cloud.google.com
   - Create new project
   - Enable Google Drive API

2. **Create Credentials**
   - Create OAuth 2.0 Client ID
   - Download credentials JSON

3. **Configure**
```yaml
storage:
  provider: google_drive
  google_credentials: "/path/to/credentials.json"
  google_folder_id: "your-folder-id"
```

### Dropbox

1. **Create Dropbox App**
   - Go to https://www.dropbox.com/developers/apps
   - Create new app
   - Generate access token

2. **Configure**
```yaml
storage:
  provider: dropbox
  dropbox_token: "your-access-token"
  dropbox_folder: "/VoxtralNotetaker"
```

### Amazon S3

1. **Create S3 Bucket**
   - Go to AWS S3 Console
   - Create bucket
   - Configure permissions

2. **Configure**
```yaml
storage:
  provider: s3
  s3_bucket: "your-bucket-name"
  s3_region: "eu-central-1"
  s3_access_key: "your-access-key"
  s3_secret_key: "your-secret-key"
```

### Multiple Cloud Providers

```yaml
storage:
  provider: all  # Upload to all configured providers
  local_path: "./recordings"
  google_credentials: "/path/to/credentials.json"
  dropbox_token: "your-dropbox-token"
  s3_bucket: "your-bucket"
  auto_upload: true
```

## Email Configuration

### Gmail Setup

1. **Enable 2FA** on your Google account
2. **Create App Password**:
   - Go to https://myaccount.google.com/apppasswords
   - Generate app password for "Mail"
3. **Configure**:
```yaml
email:
  enabled: true
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  smtp_user: "your-email@gmail.com"
  smtp_password: "your-app-password"
  use_tls: true
  from_email: "notetaker@your-domain.com"
  to_emails:
    - "recipient1@example.com"
    - "recipient2@example.com"
  subject_template: "Meeting Notes - {date}"
  send_audio: false
  send_transcript: true
  send_notes: true
```

### Custom SMTP Server

```yaml
email:
  smtp_host: "smtp.your-provider.com"
  smtp_port: 587
  smtp_user: "your-email@your-domain.com"
  smtp_password: "your-password"
  use_tls: true
```

## Performance Optimization

### Raspberry Pi Specific Settings

```yaml
# Optimized for Raspberry Pi 4
audio:
  sample_rate: 16000  # Lower sample rate for better performance
  channels: 1
  format: wav
  noise_reduction: true
  enhancement: true

# For Raspberry Pi Zero/1
# Use even lower sample rate
audio:
  sample_rate: 8000
```

### Memory Management

```yaml
# Split long recordings to avoid memory issues
max_recording_hours: 4
auto_split_minutes: 15  # Split every 15 minutes
```

## Troubleshooting

### Common Issues

1. **Microphone not detected**
   ```bash
   # Check connected devices
   python -m voxtral_notetaker devices
   
   # Check system audio
   arecord -l
   ```

2. **PyAudio installation issues**
   ```bash
   # On Raspberry Pi
   sudo apt-get install portaudio19-dev python3-pyaudio
   pip install --force-reinstall pyaudio
   ```

3. **Voxtral API errors**
   - Verify API key is correct
   - Check internet connection
   - Ensure sufficient credits

4. **Noise reduction not working**
   ```bash
   # Install required dependencies
   pip install noisereduce librosa
   ```

5. **Speaker diarization not working**
   ```bash
   # Install pyannote.audio
   pip install pyannote.audio
   
   # Download pretrained models (first run may take time)
   ```

### Debug Mode

```bash
# Run with verbose logging
python -m voxtral_notetaker record --debug

# Or in config
yaml
log_level: DEBUG
```

## API Reference

### Notetaker Class

```python
class Notetaker:
    def __init__(self, config: Optional[Config] = None)
    
    def start_recording(self, output_file: str) -> bool
    def stop_recording(self) -> Optional[RecordingInfo]
    def transcribe(self, audio_file: str, language: Language = Language.AUTO) -> TranscriptionResult
    def transcribe_live(self) -> AsyncGenerator[str]
    def transcribe_batch(self, files: List[str], language: Language = Language.AUTO) -> List[TranscriptionResult]
    def upload_to_cloud(self, file_path: str, result: Optional[TranscriptionResult] = None) -> bool
    def send_email(self, subject: str, result: TranscriptionResult) -> bool
    def set_speaker_names(self, names: Dict[str, str])
    def get_speaker_names(self) -> Dict[str, str]
```

### AudioRecorder Class

```python
class AudioRecorder:
    def __init__(self, config: AudioConfig)
    
    def start_recording(self, output_file: Optional[str] = None) -> bool
    def stop_recording(self) -> Optional[RecordingInfo]
    def get_audio_queue(self) -> queue.Queue
    def is_recording(self) -> bool
    def get_available_devices(self) -> List[dict]
    def set_device(self, device_index: int)
```

### VoxtralTranscriber Class

```python
class VoxtralTranscriber:
    async def transcribe(self, audio_file: str, language: Language = Language.AUTO) -> TranscriptionResult
    async def transcribe_stream(self, audio_stream: AsyncClient) -> AsyncClient
    async def transcribe_batch(self, audio_files: List[str], language: Language = Language.AUTO) -> List[TranscriptionResult]
    async def detect_language(self, audio_file: str) -> Language
```

### SpeakerDiarizer Class

```python
class SpeakerDiarizer:
    def __init__(self, config: DiarizationConfig)
    
    def diarize(self, audio_file: str) -> List[SpeakerSegment]
    def diarize_audio(self, audio_data: np.ndarray, sample_rate: int) -> List[SpeakerSegment]
    def set_speaker_names(self, names: Dict[str, str])
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `python -m pytest`
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details

## Support

- **Documentation**: https://github.com/lucadesimoni/physical-notetaker
- **Issues**: https://github.com/lucadesimoni/physical-notetaker/issues
- **Discussions**: https://github.com/lucadesimoni/physical-notetaker/discussions

## Comparison with Other Solutions

| Feature | Voxtral Notetaker | Opus 5.5 | Otter.ai | Descript |
|---------|------------------|----------|----------|----------|
| **Swiss German Support** | ✅ Native | ❌ Limited | ❌ Limited | ❌ Limited |
| **Speaker Diarization** | ✅ Advanced | ✅ Basic | ✅ Good | ✅ Good |
| **Noise Reduction** | ✅ Advanced | ✅ Basic | ✅ Good | ✅ Good |
| **Raspberry Pi Support** | ✅ Optimized | ❌ No | ❌ No | ❌ No |
| **Offline Capability** | ⚠️ Partial | ❌ No | ❌ No | ❌ No |
| **Cloud Storage** | ✅ Multiple | ❌ No | ✅ Limited | ✅ Limited |
| **Email Integration** | ✅ Full | ❌ No | ❌ No | ❌ No |
| **Open Source** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Customizable** | ✅ Full | ❌ Limited | ❌ Limited | ❌ Limited |
| **Lightweight** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Voxtral 4 Model** | ✅ Yes | ❌ No | ❌ No | ❌ No |

## Why Voxtral 4?

Voxtral 4 is the most advanced speech recognition model with:

- **Superior Accuracy** - Outperforms Opus 5.5 in benchmarks
- **Multilingual Support** - Native support for 100+ languages
- **Swiss German Expertise** - Specifically trained on Swiss German dialects
- **Context Understanding** - Better at understanding context and technical terms
- **Low Latency** - Fast transcription even for long audio files
- **Cost Effective** - Competitive pricing with free tier

## Roadmap

- [ ] Real-time streaming to Voxtral API
- [ ] Voice assistant integration
- [ ] Meeting summarization with AI
- [ ] Action item extraction
- [ ] Mobile app for remote control
- [ ] Web interface for configuration
- [ ] Multi-room audio synchronization
- [ ] Offline transcription with local models

---

**Made with ❤️ for precise meeting transcription on Raspberry Pi**

*Better than Opus 5.5 for Swiss German and chaotic discussions!* 😊
