# Voxtral Notetaker - Lean Conference Transcription System

**Raspberry Pi based meeting transcription with Mistral Voxtral, Swiss German support, speaker recognition and memos (Mistral Small 4)**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-Compatible-green.svg)](https://www.raspberrypi.org/)
[![Mistral Voxtral](https://img.shields.io/badge/Mistral-Voxtral-orange.svg)](https://docs.mistral.ai/studio/audio/overview)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Core Features

### 🎤 Conference Microphone Support
- **Jabra Spider** and other conference microphones
- Automatic device detection
- Optimized for multi-speaker scenarios
- Noise reduction for clear audio

### 📝 Transcription
- **Mistral Voxtral** (`voxtral-mini-latest`) via the Mistral API
- **Swiss German (de-CH)** meetings, sent to the API as German
- Transcribed after the meeting, or on interruption ("Moment bitte")
- AI meeting summary with **Mistral Small 4** (`mistral-small-2603`)

### 👥 Speaker Recognition
- Speaker diarization by the Mistral API (no local model needed on the Pi)
- Optional local fallback with pyannote.audio
- Distinguishes between multiple speakers
- Speaker labeling in transcripts
- Works with chaotic discussions

### ☁️ Cloud Storage
- **Google Drive** integration
- **Dropbox** sync
- **Amazon S3** support
- Local storage fallback
- Automatic upload after meetings

### 📄 Meeting Notes
- Structured transcripts with speaker labels
- Confidence scores
- Duration tracking
- Multiple format support (WAV, MP3, etc.)

## 🚀 Quick Start

### Prerequisites
- Raspberry Pi (Pi 5 recommended; any model with USB works)
- Conference microphone (Jabra Spider recommended)
- Python 3.10+
- Mistral API key ([Mistral AI Studio](https://docs.mistral.ai/studio/audio/overview))

### Installation

```bash
# Clone the repository
git clone https://github.com/lucadesimoni/physical-notetaker.git
cd physical-notetaker

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install PyAudio (on Raspberry Pi)
sudo apt-get install portaudio19-dev python3-pyaudio
pip install pyaudio

# Mistral API key
export MISTRAL_API_KEY=your-key   # or set voxtral.api_key in config.yaml

# Optional: local speaker diarization instead of the API
# pip install ".[local-diarization]"
```

### Configuration

```bash
# Create default config
python -m voxtral_notetaker setup

# Edit config.yaml
nano config.yaml
```

Example `config.yaml`:
```yaml
audio:
  sample_rate: 16000
  channels: 1
  device_index: null  # Auto-detect Jabra
  noise_reduction: true

voxtral:
  api_key: ""        # or set MISTRAL_API_KEY
  base_url: "https://api.mistral.ai/v1"
  model: "voxtral-mini-latest"
  timeout: 30

storage:
  provider: local  # or google_drive, dropbox, s3, all
  local_path: "./recordings"
  auto_upload: true

diarization:
  enabled: true
  provider: mistral  # or pyannote (local model)
  max_speakers: 10
  hf_token: null  # Hugging Face token for pyannote (or set HF_TOKEN)

summary:
  enabled: true
  model: "mistral-small-2603"  # Mistral Small 4
  base_url: null   # defaults to voxtral.base_url
  api_key: null    # defaults to voxtral.api_key
  max_points: 8
```

### Usage

```bash
# List available audio devices
python -m voxtral_notetaker devices

# Start recording (Ctrl+C to stop and transcribe)
python -m voxtral_notetaker record

# Start recording with specific device
python -m voxtral_notetaker record --device 1

# Transcribe existing audio file
python -m voxtral_notetaker transcribe meeting.wav

# Transcribe with Swiss German
python -m voxtral_notetaker transcribe meeting.wav --language de-CH

# Disable speaker diarization (faster)
python -m voxtral_notetaker record --no-diarization

# Disable cloud upload
python -m voxtral_notetaker record --no-upload
```

## 🎯 Python API

```python
from voxtral_notetaker import Notetaker, Language

# Create notetaker
notetaker = Notetaker()

# Start recording
notetaker.start_recording("meeting.wav")

# ... during meeting ...

# Stop and transcribe with speaker recognition
result = notetaker.stop_and_transcribe()

print(f"Transcript: {result.transcript}")
print(f"Speakers: {result.speakers}")
print(f"Language: {result.language}")
print(result.memo.to_markdown())   # saved as result.memo_file

# Set custom speaker names
notetaker.set_speaker_name("SPEAKER_001", "John Doe")
notetaker.set_speaker_name("SPEAKER_002", "Jane Smith")

# Handle interruptions
interrupt_result = notetaker.interrupt()

# Close
notetaker.close()
```

## 📝 Meeting Memo & Actions

Speak commands during the meeting. After `record` stops, they are picked up
from the transcript and a memo is saved next to the recording
(`meeting_..._memo.md`) and uploaded with it.

| Say (German) | Say (English) | Result |
|---|---|---|
| *Mach eine Notiz: …* / *Notiz: …* | *Make a note: …* / *Note: …* | Note |
| *Erstell einen Task: …* / *Aufgabe: …* | *Create a task: …* / *To do: …* | Task |
| *Recherchiere für uns: …* | *Research: …* / *Look up: …* | Open question / research |
| *Fass bitte zusammen* | *Summarize the meeting* | Interim memo |

Commands must open a sentence ("Okay," / "Bitte" in front is fine), so
ordinary speech like "Ich suche noch einen Termin" is not mistaken for one.

Tasks are split into **owner** and **due date**:

- *"Zahlungsschnittstelle bis 10. November fertigstellen, Marco"* → Marco · Zahlungsschnittstelle fertigstellen · 10.11.
- *"Sabine erstellt den Kampagnenplan bis Ende Oktober"* → Sabine · 31.10.
- *"Send the slides by Friday, Anna"* → Anna · next Friday

Due dates understood: `10. November`, `15.11.`, `31.12.2026`, `Ende/Mitte/Anfang Oktober`,
`morgen`, `übermorgen`, `Freitag`, `Ende der Woche`, and English equivalents.

Create a memo from any transcript (try the included example):

```bash
python -m voxtral_notetaker memo examples/besprechung_app_launch.txt --date 2026-10-25 --title "App-Launch Planung"
```

```markdown
# Protokoll: App-Launch Planung

**Datum:** 25.10.2026
**Teilnehmende:** Anna, Marco, Sabine

## Notizen
- Backend zu 80 Prozent fertig, Zahlungsschnittstelle offen
- Kampagnenbudget 20'000 CHF bestätigt

## Offene Fragen / Recherche
- TWINT Integration Kosten und Aufwand für Schweizer Apps

## Aufgaben
| Wer | Was | Bis |
|---|---|---|
| Marco | Zahlungsschnittstelle fertigstellen | 10.11.2026 |
| Sabine | erstellt den Kampagnenplan | 31.10.2026 |
| – | Testserver für das Marketing bereitstellen | – |
```

With an API key configured, the memo also gets an AI **Zusammenfassung**
(summary) of the whole discussion. It uses an OpenAI-compatible
`/chat/completions` endpoint, by default Mistral Small 4 (`mistral-small-2603`). Use `--no-summary` to skip it.

## 📋 Transcript Format

With speaker recognition enabled, transcripts include speaker labels:

```
[John Doe] Let's start the meeting. We need to discuss the Q4 budget.

[Jane Smith] I've prepared the financial reports. The numbers look good.

[John Doe] Great. Can you walk us through the highlights?

[Jane Smith] Sure. Revenue is up 15% from last quarter...
```

## 🔧 Troubleshooting

### Microphone Not Detected
```bash
# Check connected devices
python -m voxtral_notetaker devices

# Check system audio
arecord -l
```

### PyAudio Installation Issues
```bash
# On Raspberry Pi
sudo apt-get install portaudio19-dev python3-pyaudio
pip install --force-reinstall pyaudio
```

### Mistral API Errors
- Verify `MISTRAL_API_KEY` (or `voxtral.api_key`) is correct
- Check internet connection and that `api.mistral.ai` is reachable
- Ensure sufficient credits
- If a model is rejected, set `voxtral.model` / `summary.model` to one listed in your Mistral account

### Speaker Diarization Not Working
With `diarization.provider: mistral` (default) speakers come from the API.
To use a local model instead, set `provider: pyannote` and:
```bash
# Install required packages
pip install ".[local-diarization]"

# pyannote models are gated: accept the terms for
# pyannote/speaker-diarization-3.1 on Hugging Face, then
export HF_TOKEN=your-hf-token   # or set diarization.hf_token in config.yaml

# First run downloads models (may take several minutes)
```

Cloud SDKs (boto3, Google, Dropbox), `noisereduce` and `pyannote.audio` are
loaded only when used, so the package still runs if one of them is missing.

## 📊 Performance

### Optimized for Raspberry Pi
- Lightweight audio processing
- Efficient noise reduction
- Minimal memory usage
- Works on all Raspberry Pi models

### Audio Settings
- **Sample Rate:** 16000 Hz (recommended for speech)
- **Channels:** 1 (mono)
- **Format:** WAV (uncompressed for best quality)

### Cloud Upload
- Automatic upload after each meeting
- Supports multiple providers
- Retains local copies by default

## 🔄 Interruption Handling

The system supports live interruptions:

```python
# During recording
notetaker.start_recording()

# When someone interrupts
interrupt_result = notetaker.interrupt()
print(interrupt_result.transcript)  # Shows what was said so far

# Continue recording
notetaker.start_recording()
```

## 🎨 Speaker Recognition

Automatically detects and labels speakers:

```python
result = notetaker.stop_and_transcribe()

# Get all speakers
print(f"Detected speakers: {result.speakers}")

# Get speaker segments with timestamps
for seg in result.speaker_segments:
    print(f"{seg['speaker_name']}: {seg['start']:.1f}s - {seg['end']:.1f}s")

# Set custom names
notetaker.set_speaker_name("SPEAKER_001", "Alice")
notetaker.set_speaker_name("SPEAKER_002", "Bob")
```

## ☁️ Cloud Storage Setup

### Google Drive
```yaml
storage:
  provider: google_drive
  google_credentials: "/path/to/credentials.json"
  google_folder_id: "your-folder-id"
```

### Dropbox
```yaml
storage:
  provider: dropbox
  dropbox_token: "your-access-token"
  dropbox_folder: "/VoxtralNotetaker"
```

### Amazon S3
```yaml
storage:
  provider: s3
  s3_bucket: "your-bucket"
  s3_region: "eu-central-1"
  s3_access_key: "your-access-key"
  s3_secret_key: "your-secret-key"
```

## 📝 Meeting Result Structure

```python
@dataclass
class MeetingResult:
    audio_file: str           # Path to audio file
    transcript: str          # Full transcript with speaker labels
    language: str            # Detected language
    confidence: float        # Transcription confidence (0-1)
    duration: float          # Duration in seconds
    start_time: datetime     # Meeting start time
    end_time: datetime       # Meeting end time
    speakers: List[str]      # List of speaker names/IDs
    speaker_segments: List[Dict]  # Segments with speaker info
    storage_results: List[UploadResult]  # Cloud upload results
```

## 🎯 Models

| Purpose | Default | Config |
|---|---|---|
| Transcription + speakers | `voxtral-mini-latest` | `voxtral.model` |
| Meeting summary | `mistral-small-2603` (Mistral Small 4) | `summary.model` |

Both run on Mistral's API, so the Raspberry Pi only records and processes audio.
Swiss German is transcribed as German; test with your own recordings.

## 📜 License

MIT License - see [LICENSE](LICENSE) for details

## 🧪 Tests

```bash
pip install pytest
python -m pytest tests
```

The tests need no microphone, network access or ML models.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

**Built for precise conference transcription on Raspberry Pi**

*Optimized for Jabra conference microphones, Swiss German, and multi-speaker scenarios* 🎤
