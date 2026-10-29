# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Tests for task details, transcript command extraction and memo generation
"""

from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from voxtral_notetaker import Notetaker, NotetakerConfig
from voxtral_notetaker.actions import parse_task_details, resolve_due_date
from voxtral_notetaker.cli import cli
from voxtral_notetaker.commands import split_transcript
from voxtral_notetaker.memo import Memo, Summarizer
from voxtral_notetaker.transcription import TranscriptionResult


REF = datetime(2026, 10, 25)  # a Sunday
SAMPLE = Path(__file__).parent.parent / "examples" / "besprechung_app_launch.txt"


@pytest.mark.parametrize("text,participants,title,owner,due", [
    ("Zahlungsschnittstelle bis 10. November fertigstellen, Marco", ["Anna", "Marco"],
     "Zahlungsschnittstelle fertigstellen", "Marco", date(2026, 11, 10)),
    ("Sabine erstellt den Kampagnenplan bis Ende Oktober", [],
     "erstellt den Kampagnenplan", "Sabine", date(2026, 10, 31)),
    ("Offerte an Anna schicken bis Freitag", ["Anna"],
     "Offerte schicken", "Anna", date(2026, 10, 30)),
    ("Testserver für das Marketing bereitstellen", ["Anna"],
     "Testserver für das Marketing bereitstellen", None, None),
    ("Bericht bis 15.11. abgeben", [], "Bericht abgeben", None, date(2026, 11, 15)),
    ("Budget prüfen bis Mitte Januar", [], "Budget prüfen", None, date(2027, 1, 15)),
    ("Send the contract to the client by Friday, Marco", [],
     "Send the contract to the client", "Marco", date(2026, 10, 30)),
    ("Marco will review the code by November 3rd", [],
     "review the code", "Marco", date(2026, 11, 3)),
    ("Prepare slides by end of the week", [], "Prepare slides", None, date(2026, 10, 30)),
])
def test_parse_task_details(text, participants, title, owner, due):
    details = parse_task_details(text, participants, REF)
    assert details["title"] == title
    assert details["owner"] == owner
    assert details["due_date"] == due


def test_explicit_owner_kept_with_unnamed_speakers():
    details = parse_task_details("Offerte senden, Marco", ["SPEAKER_00"], REF)
    assert details["owner"] == "Marco"


@pytest.mark.parametrize("text,expected", [
    ("morgen", date(2026, 10, 26)),
    ("übermorgen", date(2026, 10, 27)),
    ("31.12.2026", date(2026, 12, 31)),
    ("1. März", date(2027, 3, 1)),  # already past this year -> next year
    ("10.13.", None),               # invalid date stays unresolved
])
def test_resolve_due_date(text, expected):
    assert resolve_due_date(text, REF.date()) == expected


def test_split_transcript_keeps_dates_together():
    pairs = split_transcript("[Marco] Das wird knapp. Task: Fertig bis 10. November, Marco.")
    assert pairs == [("Marco", "Das wird knapp"),
                     ("Marco", "Task: Fertig bis 10. November, Marco.")]


@pytest.fixture
def sample_memo():
    transcript = SAMPLE.read_text(encoding="utf-8")
    nt = Notetaker(NotetakerConfig())
    for name in ("Anna", "Marco", "Sabine"):
        nt.set_speaker_name(name, name)
    nt.extract_commands(transcript, "de-CH", REF)
    memo = nt.build_memo(transcript, "de-CH", title="App-Launch Planung", date=REF)
    nt.close()
    return memo


def test_sample_meeting_memo(sample_memo):
    assert [n["content"] for n in sample_memo.notes] == [
        "Backend zu 80 Prozent fertig, Zahlungsschnittstelle offen",
        "Kampagnenbudget 20'000 CHF bestätigt",
    ]
    assert [r["query"] for r in sample_memo.research] == [
        "TWINT Integration Kosten und Aufwand für Schweizer Apps",
    ]
    tasks = [(t["owner"], t["title"], t["due_date"]) for t in sample_memo.tasks]
    assert tasks == [
        ("Marco", "Zahlungsschnittstelle fertigstellen", date(2026, 11, 10)),
        ("Sabine", "erstellt den Kampagnenplan", date(2026, 10, 31)),
        (None, "Testserver für das Marketing bereitstellen", None),
    ]
    assert sample_memo.tasks[2]["requested_by"] == "Marco"

    md = sample_memo.to_markdown()
    assert "# Protokoll: App-Launch Planung" in md
    assert "| Marco | Zahlungsschnittstelle fertigstellen | 10.11.2026 |" in md
    assert "| – | Testserver für das Marketing bereitstellen | – |" in md
    assert "Aufgaben:" in sample_memo.to_text()


def test_transcript_extraction_skips_items_captured_live():
    nt = Notetaker(NotetakerConfig())
    nt.process_command("Notiz: Budget bestätigt", "de-CH", speaker="Anna")
    nt.extract_commands("[Anna] Notiz: Budget bestätigt.\n[Anna] Notiz: Neuer Punkt.", "de-CH")
    assert [n["content"] for n in nt.get_notes()] == ["Budget bestätigt", "Neuer Punkt"]
    nt.close()


def test_transcript_extraction_ignores_recording_controls():
    nt = Notetaker(NotetakerConfig())
    nt.interrupt = lambda: pytest.fail("interrupt must not run while reading a transcript")
    results = nt.extract_commands("Moment bitte. Beende die Aufnahme.", "de-CH")
    assert results == []
    nt.close()


def test_summarize_command_returns_interim_memo():
    nt = Notetaker(NotetakerConfig())
    nt.process_command("Aufgabe: Offerte senden bis Freitag", "de-CH")
    result = nt.process_command("Fass bitte zusammen", "de-CH")
    assert result.action == "SUMMARIZE"
    assert "1 Aufgaben" in result.response
    assert "Offerte senden" in result.data["memo"]
    nt.close()


def test_english_memo():
    memo = Memo(title="Kickoff", language="en", date=REF,
                tasks=[{"content": "x", "title": "Send slides", "owner": "Ann",
                        "due_date": date(2026, 11, 2)}])
    md = memo.to_markdown()
    assert "# Meeting Notes: Kickoff" in md
    assert "| Ann | Send slides | 2026-11-02 |" in md
    assert "_None_" in md  # no notes


def test_summarizer(monkeypatch):
    config = NotetakerConfig()
    config.voxtral.api_key = "key"
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, json=json)
        reply = "Hier ist die Zusammenfassung:\n- Launch im Dezember\n- Budget CHF 20'000"
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    points = Summarizer(config.summary, config.voxtral).summarize("[Anna] Hallo", "de-CH")
    assert points == ["Launch im Dezember", "Budget CHF 20'000"]
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["model"] == config.summary.model


def test_summarizer_skipped_without_key():
    config = NotetakerConfig()
    assert Summarizer(config.summary, config.voxtral).summarize("text", "de") == []


def test_stop_and_transcribe_writes_memo(tmp_path, monkeypatch):
    config = NotetakerConfig()
    config.storage.local_path = str(tmp_path / "cloud")
    config.diarization.enabled = False
    nt = Notetaker(config)

    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF")
    nt._is_recording = True
    nt._current_file = str(audio)
    nt._start_time = REF
    monkeypatch.setattr(nt.audio, "stop_recording", lambda: object())
    monkeypatch.setattr(nt, "transcribe", lambda f, lang: TranscriptionResult(
        text="Mach eine Notiz: Launch im Dezember. Aufgabe: Offerte senden bis morgen, Anna.",
        language="de-CH", confidence=0.9, duration=1.0))

    result = nt.stop_and_transcribe()
    memo_md = (tmp_path / "meeting_memo.md").read_text(encoding="utf-8")
    assert result.memo_file == str(tmp_path / "meeting_memo.md")
    assert "- Launch im Dezember" in memo_md
    assert "| Anna | Offerte senden | 26.10.2026 |" in memo_md
    assert (tmp_path / "cloud" / "meeting_memo.md").exists()
    nt.close()


def test_cli_memo(tmp_path):
    transcript = tmp_path / "meeting.txt"
    transcript.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    result = CliRunner().invoke(cli, ["memo", str(transcript), "--date", "2026-10-25",
                                      "--title", "App-Launch", "--no-summary"])
    assert result.exit_code == 0, result.output
    memo = (tmp_path / "meeting_memo.md").read_text(encoding="utf-8")
    assert "**Teilnehmende:** Anna, Marco, Sabine" in memo
    assert "| Sabine | erstellt den Kampagnenplan | 31.10.2026 |" in memo


@pytest.mark.parametrize("sentence", [
    "Ich suche noch einen freien Termin nächste Woche.",
    "Wir sollten das nachschlagen, bevor wir entscheiden.",
    "Let me search my inbox for that email.",
    "I'll google it later.",
    "Let me make a note of that.",
])
def test_ordinary_speech_in_transcript_is_not_a_command(sentence):
    nt = Notetaker(NotetakerConfig())
    assert nt.extract_commands(sentence, "auto") == []
    nt.close()


@pytest.mark.parametrize("sentence", [
    "Okay, mach eine Notiz: Budget ist fix.",
    "Bitte erstell einen Task: Offerte senden.",
    "Das wird knapp. Erstell einen Task: Server bestellen.",
])
def test_commands_with_lead_in_are_found_in_transcript(sentence):
    nt = Notetaker(NotetakerConfig())
    assert len(nt.extract_commands(sentence, "de-CH")) == 1
    nt.close()
