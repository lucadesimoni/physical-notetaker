"""
Unit tests for Voxtral Notetaker (no hardware, network or ML models required)
"""

import asyncio
import wave

import httpx
import numpy as np
import pytest
from click.testing import CliRunner

from voxtral_notetaker import Notetaker, NotetakerConfig, CommandParser, CommandType, Language
from voxtral_notetaker.audio import AudioRecorder, repair_wav, wav_duration
from voxtral_notetaker.cli import cli
from voxtral_notetaker.config import AudioConfig, StorageConfig, StorageProvider, VoxtralConfig
from voxtral_notetaker.storage import CloudStorage
from voxtral_notetaker.transcription import VoxtralTranscriber


@pytest.fixture
def parser():
    return CommandParser()


@pytest.mark.parametrize("text,expected", [
    ("Mach eine Notiz: Besprechung um 14 Uhr", "Besprechung um 14 Uhr"),
    ("Notiz: Wichtiger Punkt", "Wichtiger Punkt"),
    ("Schreib das auf: Termin vereinbaren", "Termin vereinbaren"),
    ("Merke dir: Follow-up mit Team", "Follow-up mit Team"),
])
def test_german_notes(parser, text, expected):
    cmd = parser.parse(text, "de-CH")
    assert cmd.command_type == CommandType.NOTE
    assert cmd.parameters["content"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Erstell einen Task: Dokument erstellen", "Dokument erstellen"),
    ("Aufgabe: Code review durchführen", "Code review durchführen"),
    ("Task hinzufügen: Präsentation vorbereiten", "Präsentation vorbereiten"),
])
def test_german_tasks_keep_content(parser, text, expected):
    cmd = parser.parse(text, "de-CH")
    assert cmd.command_type == CommandType.TASK
    assert cmd.parameters["content"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Recherchiere für uns: Marktanalyse", "Marktanalyse"),
    ("Nachschlagen: Python 3.12 Features", "Python 3.12 Features"),
])
def test_german_research(parser, text, expected):
    cmd = parser.parse(text, "de-CH")
    assert cmd.command_type == CommandType.RESEARCH
    assert cmd.parameters["query"] == expected


@pytest.mark.parametrize("text,cmd_type", [
    ("Make a note: Meeting at 2pm", CommandType.NOTE),
    ("Create a task: Write documentation", CommandType.TASK),
    ("To do: Call client", CommandType.TASK),
    ("Look up: Python 3.12 features", CommandType.RESEARCH),
    ("Search for: Best practices", CommandType.RESEARCH),
    ("Start recording", CommandType.RECORDING),
    ("Hold on", CommandType.INTERRUPT),
    ("One moment", CommandType.INTERRUPT),
    ("Cancel that", CommandType.CANCEL),
])
def test_english_commands(parser, text, cmd_type):
    assert parser.parse(text, "en").command_type == cmd_type


@pytest.mark.parametrize("text,action", [
    ("Start die Aufnahme", "start"),
    ("Aufnahme stoppen", "stop"),
    ("Pause die Aufnahme", "pause"),
])
def test_german_recording(parser, text, action):
    cmd = parser.parse(text, "de-CH")
    assert cmd.command_type == CommandType.RECORDING
    assert cmd.parameters["action"] == action


@pytest.mark.parametrize("text,lang", [
    ("Mach eine Notiz", "de-CH"),
    ("Recherchiere für uns", "de-CH"),
    ("Make a note under the table", "en"),
    ("We found the submit button", "en"),
])
def test_language_detection(parser, text, lang):
    assert parser._detect_language(text) == lang


def test_no_false_positive_substrings(parser):
    # "stop" inside "nonstop" and "suche" inside "besuche" must not trigger commands
    assert parser.parse("Wir arbeiten nonstop", "de-CH") is None
    assert parser.parse("Ich besuche morgen Basel", "de-CH") is None


def test_executor_stores_note():
    with Notetaker(NotetakerConfig()) as nt:
        result = nt.process_command("Make a note: Budget approved", "en")
        assert result.success and result.action == "CREATE_NOTE"
        assert nt.get_notes()[0]["content"] == "Budget approved"


def test_config_roundtrip(tmp_path):
    config = NotetakerConfig()
    config.voxtral.api_key = "abc"
    config.diarization.max_speakers = 4
    path = tmp_path / "config.yaml"
    config.save(str(path))
    loaded = NotetakerConfig.load(str(path))
    assert loaded.voxtral.api_key == "abc"
    assert loaded.diarization.max_speakers == 4


def test_config_handles_empty_file_and_sections(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("")
    assert NotetakerConfig.load(str(path)).audio.sample_rate == 16000
    path.write_text("audio:\nstorage:\n")
    assert NotetakerConfig.load(str(path)).storage.provider == StorageProvider.LOCAL


def test_save_wav_writes_int16_after_noise_reduction(tmp_path):
    recorder = AudioRecorder(AudioConfig())
    # Float data (as returned by noise reduction) must be stored as 16-bit PCM
    samples = np.array([0.0, 1000.0, -1000.0, 50000.0], dtype=np.float64)
    out = tmp_path / "out.wav"
    recorder._save_wav(samples, 16000, str(out))
    with wave.open(str(out)) as wf:
        assert wf.getnframes() == 4
    recorder.close()
    recorder.close()  # closing twice must not raise


def test_local_storage(tmp_path):
    src = tmp_path / "meeting.txt"
    src.write_text("hello")
    storage = CloudStorage(StorageConfig(local_path=str(tmp_path / "out")))
    [result] = storage.upload(str(src))
    assert result.success
    assert (tmp_path / "out" / "meeting.txt").read_text() == "hello"


def test_format_transcript_with_speakers():
    nt = Notetaker(NotetakerConfig())
    text = "Hello everyone. Thanks Alice, let's start."
    segments = [
        {"start": 0.0, "end": 2.0, "speaker_id": "S0", "speaker_name": "Alice"},
        {"start": 2.0, "end": 4.0, "speaker_id": "S1", "speaker_name": "Bob"},
    ]
    formatted = nt._format_transcript_with_speakers(text, segments)
    lines = formatted.split("\n")
    assert lines[0].startswith("[Alice]") and lines[1].startswith("[Bob]")
    # No text is lost
    assert formatted.replace("[Alice] ", "").replace("[Bob] ", "").replace("\n", " ") \
        .split() == text.split()
    nt.close()


def test_transcriber_works_across_event_loops(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "hi", "language": "en", "confidence": 0.9})

    transcriber = VoxtralTranscriber(VoxtralConfig(api_key="k", base_url="https://x.test"))
    transport = httpx.MockTransport(handler)
    transcriber._make_client = lambda: httpx.AsyncClient(base_url="https://x.test", transport=transport)

    # Two separate event loops, as Notetaker.transcribe does per call
    for _ in range(2):
        result = asyncio.run(transcriber.transcribe(str(audio), Language.AUTO))
        assert result.text == "hi"
    assert len(requests) == 2
    # "auto" must not be sent as a literal language code
    assert b'name="language"\r\n\r\nauto' not in requests[0].content


def test_cli_setup_and_help(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli, ["--help"]).exit_code == 0
    assert runner.invoke(cli, ["setup"]).exit_code == 0
    assert (tmp_path / "config.yaml").exists()


def _start_fake_recording(recorder, path):
    # Simulate an in-progress recording without real hardware
    recorder._open_file(str(path))
    recorder._output_file = str(path)
    recorder._start_time = 0.0
    recorder._is_recording = True


def test_recording_streams_to_disk(tmp_path):
    recorder = AudioRecorder(AudioConfig(noise_reduction=False))
    out = tmp_path / "rec.wav"
    _start_fake_recording(recorder, out)
    for _ in range(10):
        recorder._write(np.zeros(1600, dtype=np.int16).tobytes(), 1600)
    # Readable while the recording is still running
    recorder._file.flush()
    with wave.open(str(out)) as wf:
        assert wf.getnframes() == 16000
    info = recorder.stop_recording()
    assert info.file_path == str(out)
    assert info.duration == pytest.approx(1.0)
    with wave.open(str(out)) as wf:
        assert wf.getnframes() == 16000
    recorder.close()


def test_recording_survives_power_cut(tmp_path):
    recorder = AudioRecorder(AudioConfig(noise_reduction=False))
    out = tmp_path / "rec.wav"
    _start_fake_recording(recorder, out)
    recorder._write(np.ones(16000, dtype=np.int16).tobytes(), 16000)
    recorder._file.flush()
    # Power cut: more audio reached the disk than the header says, last frame partial
    with open(out, "ab") as f:
        f.write(b"\x01\x00" * 8000 + b"\x01")
    assert repair_wav(str(out))
    with wave.open(str(out)) as wf:
        assert wf.getnframes() == 24000
    assert wav_duration(str(out)) == pytest.approx(1.5)


def test_repair_rejects_non_wav(tmp_path):
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"not audio at all" * 10)
    assert not repair_wav(str(bad))


def _capture_transcription(tmp_path, reply, **call):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=reply)

    config = VoxtralConfig(api_key="secret")
    transcriber = VoxtralTranscriber(config)
    transport = httpx.MockTransport(handler)
    real_client = transcriber._make_client
    transcriber._make_client = lambda: httpx.AsyncClient(
        base_url=config.base_url, transport=transport, headers=real_client().headers)
    result = asyncio.run(transcriber.transcribe(str(audio), **call))
    return result, requests[0]


def test_mistral_request_defaults(tmp_path):
    result, request = _capture_transcription(
        tmp_path, {"text": "Grüezi", "language": "de"}, language=Language.DE_CH)
    assert str(request.url) == "https://api.mistral.ai/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer secret"
    body = request.content.decode("utf-8", "replace")
    assert 'name="model"\r\n\r\nvoxtral-small-transcribe-3-0' in body
    assert 'name="language"\r\n\r\nde\r\n' in body  # Swiss German sent as "de"
    assert "diarize" not in body
    assert result.text == "Grüezi" and result.confidence is None


def test_mistral_diarization_request_and_segments(tmp_path):
    reply = {"text": "Hallo zusammen. Danke Anna.", "language": "de", "segments": [
        {"start": 0.0, "end": 1.5, "text": "Hallo zusammen.", "speaker_id": "speaker_0"},
        {"start": 1.5, "end": 3.0, "text": "Danke Anna.", "speaker_id": "speaker_1"},
    ]}
    result, request = _capture_transcription(
        tmp_path, reply, language=Language.DE_CH, diarize=True)
    body = request.content.decode("utf-8", "replace")
    assert 'name="diarize"\r\n\r\ntrue' in body
    assert 'name="timestamp_granularities"\r\n\r\nsegment' in body
    assert 'name="language"' not in body  # not combinable with timestamps
    assert result.has_speakers
    assert [s.speaker_id for s in result.segments] == ["speaker_0", "speaker_1"]


def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "from-env")
    assert VoxtralConfig().resolved_api_key() == "from-env"
    assert VoxtralConfig(api_key="explicit").resolved_api_key() == "explicit"


def test_default_models():
    config = NotetakerConfig()
    assert config.voxtral.base_url == "https://api.mistral.ai/v1"
    assert config.summary.model == "mistral-small-2603"  # Mistral Small 4
    assert config.diarization.provider == "mistral"


def test_stop_and_transcribe_uses_api_speaker_labels(tmp_path, monkeypatch):
    from voxtral_notetaker.transcription import TranscriptionResult, TranscriptSegment

    config = NotetakerConfig()
    config.storage.auto_upload = False
    nt = Notetaker(config)
    nt.set_speaker_name("speaker_0", "Anna")
    nt.set_speaker_name("speaker_1", "Marco")
    monkeypatch.setattr(nt.diarizer, "diarize",
                        lambda *a, **k: pytest.fail("local diarization must not run"))

    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF")
    nt._is_recording = True
    nt._current_file = str(audio)
    monkeypatch.setattr(nt.audio, "stop_recording", lambda: object())
    calls = []

    def fake_transcribe(f, lang, diarize=False):
        calls.append(diarize)
        return TranscriptionResult(text="", language="de", confidence=None, duration=1.0, segments=[
            TranscriptSegment(0, 2, "Mach eine Notiz: Budget fix.", "speaker_0"),
            TranscriptSegment(2, 4, "Erstell einen Task: Server bestellen bis Freitag.", "speaker_1"),
            TranscriptSegment(4, 5, "Gut.", "speaker_1"),
        ])

    monkeypatch.setattr(nt, "transcribe", fake_transcribe)
    result = nt.stop_and_transcribe()

    assert calls == [True]
    assert result.speakers == ["Anna", "Marco"]
    assert result.transcript.split("\n") == [
        "[Anna] Mach eine Notiz: Budget fix.",
        "[Marco] Erstell einen Task: Server bestellen bis Freitag. Gut.",
    ]
    assert result.memo.participants == ["Anna", "Marco"]
    assert result.memo.tasks[0]["requested_by"] == "Marco"
    nt.close()


def test_fast_model_used_on_request(tmp_path):
    _, request = _capture_transcription(tmp_path, {"text": "ok"}, fast=True)
    body = request.content.decode("utf-8", "replace")
    assert 'name="model"\r\n\r\nvoxtral-mini-transcribe-3-0' in body


def test_interrupt_uses_fast_model_and_final_uses_accurate(tmp_path, monkeypatch):
    from voxtral_notetaker.audio import RecordingInfo
    from voxtral_notetaker.transcription import TranscriptionResult

    config = NotetakerConfig()
    config.storage.auto_upload = False
    config.diarization.enabled = False
    nt = Notetaker(config)
    calls = []

    def fake_transcribe(f, lang=Language.AUTO, diarize=False, fast=False):
        calls.append(fast)
        return TranscriptionResult(text="Hallo", language="de", confidence=None, duration=0.1)

    monkeypatch.setattr(nt, "transcribe", fake_transcribe)
    audio = tmp_path / "part.wav"
    audio.write_bytes(b"RIFF")
    info = RecordingInfo(file_path=str(audio), duration=1.0, sample_rate=16000)

    # "Moment bitte" -> quick interim transcript with the fast model
    nt._is_recording = True
    monkeypatch.setattr(nt.audio, "stop_recording", lambda: info)
    assert nt.interrupt().transcript == "Hallo"

    # End of meeting -> accurate model
    nt._is_recording = True
    nt._current_file = str(audio)
    nt.stop_and_transcribe()
    assert calls == [True, False]
    nt.close()


def test_fast_model_config_roundtrip(tmp_path):
    config = NotetakerConfig()
    config.voxtral.fast_model = "custom-mini"
    path = tmp_path / "c.yaml"
    config.save(str(path))
    assert NotetakerConfig.load(str(path)).voxtral.fast_model == "custom-mini"
