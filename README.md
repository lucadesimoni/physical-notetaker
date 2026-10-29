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
- **Mistral Voxtral Small Transcribe 3** (`voxtral-small-transcribe-3-0`) via the Mistral API
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

## 🟢 Using the Device

Nothing to install or type for meeting participants:

1. **Press the button** (on the device, or the call button of the speakerphone).
   The device says *"Aufnahme gestartet. Diese Besprechung wird aufgezeichnet."*
   (everyone knows they are recorded), and the light is on.
2. Optionally, everyone introduces themselves: *"Ich bin Anna"*, *"Mein Name ist Marco"*.
   The memo then uses real names.
3. Talk normally. Say *"Mach eine Notiz: …"* or *"Erstell einen Task: … bis Freitag, Marco"*.
   About half a minute later the device confirms: *"Notiz notiert"* / *"Aufgabe notiert"*.
4. **Press the button again** at the end, or say *"Beende die Aufnahme"*.
   The device says *"Aufnahme gespeichert. Das Protokoll kommt per E-Mail."*
5. The **memo arrives by email**, and is on the device's web page.

Names wrong in the memo? Open the meeting on the web page, correct the names and
press *Protokoll neu erstellen*. Nothing is transcribed again for this.

What happens if…

| Situation | What the device does |
|---|---|
| Power cut / crash mid-meeting | The recording is on the SD card up to the last ~2 seconds; it is repaired and processed after restart |
| No internet after the meeting | The memo is created automatically when the connection is back (retries with growing pauses) |
| Wrong API key / email password | The web page shows *Bitte prüfen* with the reason; fix it in Settings and it retries |
| Meeting runs too long | Announcement 5 minutes before the limit (default 120 min), then it stops and saves |
| Microphone unplugged | *"Mikrofon nicht gefunden"* and a message on the web page |
| SD card filling up | Audio of finished meetings is deleted after 30 days (memos stay); if space still runs low, oldest audio first. A full card stops and saves the recording |
| Don't know the address | Hold the button for 3 seconds: the device says its address |

Without a speech engine the device uses tones instead: rising = recording,
falling = saved, three low tones = problem.
Light: on = recording, slow blink = creating memo, fast blink = problem.

The web page and announcements are in German by default; switch to English
in Settings (*Sprache des Geräts*).

## 🔌 Device Setup (one time)

On the Raspberry Pi (Raspberry Pi OS Bookworm or newer):

```bash
git clone https://github.com/lucadesimoni/physical-notetaker.git
cd physical-notetaker
sudo ./deploy/install.sh
```

The installer names the device `notetaker` and starts it on every boot. Then on
your phone (**same Wi-Fi as the device**), open **`http://notetaker.local`**, or scan
the QR code the installer shows:

1. Choose a PIN (protects the settings)
2. Paste your Mistral API key
3. Optional: email addresses for the memos and your SMTP server
4. Print the sticker (*Aufkleber mit QR-Code*) and put it on the device: it
   explains the button and links to the page

The phone must be in the same network as the device. If `notetaker.local` does
not open (some Android phones), use the IP address on the sticker, or hold the
button for 3 seconds and the device says it.

**No Wi-Fi yet?** Start the Pi without a network. After about a minute it opens
the Wi-Fi **Notetaker-Setup** (password `notetaker`). Connect your phone and open
`http://10.42.0.1`, then enter your Wi-Fi in Settings.

**Buttons:** the speakerphone's call button works if Linux reports it as a key.
Check with `sudo evtest` (press the button; `KEY_PHONE`/`KEY_PLAYPAUSE` are
used by default, see `device.input_keys`). For a dedicated button, wire a push
button between a GPIO pin and GND and set `device.button_gpio` (e.g. `17`);
an LED with a resistor on `device.led_gpio` (e.g. `27`).

**Nicer voice:** announcements use `espeak-ng` (robotic but clear). For a natural
voice install [Piper](https://github.com/rhasspy/piper) and set
`device.piper_model` to a German voice model (`.onnx`).

Useful commands on the Pi:

```bash
journalctl -u notetaker -f                     # live log
~/notetaker/venv/bin/notetaker queue           # recordings and their status
~/notetaker/venv/bin/notetaker retry           # retry everything that failed
~/notetaker/venv/bin/notetaker process FILE.wav --speaker speaker_0=Anna  # redo a memo (add --fresh to transcribe again)
```

## 🪟 Testing on Windows

Try everything with a laptop and the Jabra before setting up a Raspberry Pi:

1. Install **Python 3.12** from [python.org](https://www.python.org/downloads/windows/)
   (tick *Add python.exe to PATH*). Versions 3.10 - 3.13 work; 3.12 is safest for
   the microphone package.
2. Download the repository (*Code → Download ZIP*, then unzip) or `git clone` it.
3. Plug in the Jabra and **double-click `windows\start-notetaker.bat`**.
   The first start installs the packages (a few minutes), then the web page
   opens at `http://localhost:8080`.
4. In *Einstellungen*: choose a PIN and enter your Mistral API key.
5. Press **Enter** in the black window (or *Besprechung starten* on the page),
   talk, press **Enter** again. The page shows which microphone was used and,
   shortly after, the memo.

On Windows the announcements use the built-in Windows voice (for German, a
German voice must be installed: *Settings → Time & language → Speech*), or
eSpeak NG if installed. The Jabra's buttons, GPIO and the Wi-Fi hotspot are
Raspberry Pi features and are switched off. If Windows asks about network
access, allow it to open the page from your phone (`http://<PC address>:8080`).

Starting again later takes seconds. To start fresh, delete `config.yaml`
(settings) or the `venv` folder (installed packages).

## 🚀 Quick Start (developers)

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
  model: "voxtral-small-transcribe-3-0"      # final transcript
  fast_model: "voxtral-mini-transcribe-3-0"  # quick interim transcripts
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

# Quick, cheaper transcription with the Mini model
python -m voxtral_notetaker transcribe meeting.wav --fast

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

Speakers are also named automatically from introductions such as *"Ich bin Anna"*,
*"Mein Name ist Marco"*, *"I bi d'Sabine"* or *"My name is Tom"*. Job titles
(*"Ich bin Projektleiter"*) and dates (*"Ich bin Mitte Oktober weg"*) are ignored,
and a name is never given to two speakers. Turn it off with
`diarization.detect_names: false`.

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
| Final transcript, speakers, memo | `voxtral-small-transcribe-3-0` (Voxtral Small Transcribe 3) | `voxtral.model` |
| Quick interim transcript ("Moment bitte", `transcribe --fast`) | `voxtral-mini-transcribe-3-0` (Voxtral Mini Transcribe 3) | `voxtral.fast_model` |
| Meeting summary | `mistral-small-2603` (Mistral Small 4) | `summary.model` |

The accurate Small model is used where quality matters (the memo, tasks and
speaker names come from it); the cheaper, faster Mini model where speed matters.
Voxtral 3 is in public preview, so check both IDs in your Mistral model list.
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
