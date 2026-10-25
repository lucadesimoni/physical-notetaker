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
from voxtral_notetaker.audio import AudioRecorder
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


def test_stop_recording_saves_captured_audio(tmp_path):
    recorder = AudioRecorder(AudioConfig(noise_reduction=False))
    out = tmp_path / "rec.wav"
    # Simulate an in-progress recording without real hardware
    recorder._is_recording = True
    recorder._output_file = str(out)
    recorder._start_time = 0.0
    recorder._audio_data = [np.zeros(1600, dtype=np.int16).tobytes()]
    info = recorder.stop_recording()
    assert info.file_path == str(out)
    with wave.open(str(out)) as wf:
        assert wf.getnframes() == 1600
    recorder.close()
