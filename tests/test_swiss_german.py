# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss German: vocabulary hints, dialect clean-up, dialect commands and dates
"""

import asyncio
import re
from datetime import date, datetime

import httpx
import pytest

from voxtral_notetaker import CommandParser, Notetaker, NotetakerConfig
from voxtral_notetaker.actions import parse_task_details
from voxtral_notetaker.config import Language, VoxtralConfig
from voxtral_notetaker.dialect import clean_lines, has_dialect, merge_cleaned, should_clean
from voxtral_notetaker.transcription import (TranscriptionResult, TranscriptSegment,
                                             VoxtralTranscriber, context_terms)

REF = datetime(2026, 11, 3)  # a Tuesday


# --- vocabulary hints (context_bias) ---------------------------------------------------

def _transcriber(tmp_path, replies, vocabulary):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    requests = []

    def handler(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    config = VoxtralConfig(api_key="k", vocabulary=vocabulary)
    t = VoxtralTranscriber(config)
    transport = httpx.MockTransport(handler)
    t._make_client = lambda: httpx.AsyncClient(base_url=config.base_url, transport=transport)
    return t, str(audio), requests


def _fields(request):
    body = request.content.decode("utf-8", "replace")
    return re.findall(r'name="context_bias"\r\n\r\n([^\r]*)', body)


def test_vocabulary_sent_as_one_field_per_term(tmp_path):
    t, audio, requests = _transcriber(tmp_path, [(200, {"text": "ok"})],
                                      ["Anna Meier", "TWINT", "twint", " Outthinkx "])
    asyncio.run(t.transcribe(audio, Language.DE_CH))
    assert _fields(requests[0]) == ["Anna Meier", "TWINT", "Outthinkx"]


def test_vocabulary_rejection_never_costs_a_transcription(tmp_path):
    t, audio, requests = _transcriber(tmp_path, [(422, {"detail": "context_bias"}),
                                                 (200, {"text": "Grüezi"})], ["TWINT"])
    result = asyncio.run(t.transcribe(audio, Language.DE_CH))
    assert result.text == "Grüezi"
    assert _fields(requests[0]) == ["TWINT"] and _fields(requests[1]) == []
    # Remembered: the next transcription does not send the vocabulary again
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "x"})

    transport = httpx.MockTransport(handler)
    t._make_client = lambda: httpx.AsyncClient(base_url=t.config.base_url, transport=transport)
    asyncio.run(t.transcribe(audio, Language.DE_CH))
    assert len(requests) == 3 and _fields(requests[-1]) == []


def test_no_vocabulary_no_field(tmp_path):
    t, audio, requests = _transcriber(tmp_path, [(200, {"text": "ok"})], [])
    asyncio.run(t.transcribe(audio, Language.DE_CH))
    assert _fields(requests[0]) == []


def test_context_terms_limits():
    terms = context_terms([f"term{i}" for i in range(150)], ["x" * 300])
    assert len(terms) == 100 and all(len(t) <= 100 for t in terms)


# --- dialect clean-up -------------------------------------------------------------------

def test_merge_keeps_original_when_model_misbehaves():
    lines = ["Mir händ das gescht bschproche.", "Okay.", "Das isch fix."]
    content = ("1|Wir haben das gestern besprochen.\n"
               "3|Das ist fix. Und hier noch eine lange Erfindung, die niemand gesagt hat, "
               "mit vielen zusätzlichen Wörtern.\n"
               "9|ausserhalb")
    assert merge_cleaned(lines, content) == [
        "Wir haben das gestern besprochen.",  # cleaned
        "Okay.",                              # missing -> original
        "Das isch fix.",                      # inflated -> original
    ]


def test_merge_keeps_continuation_lines_and_rejects_lost_content():
    long = "Das isch so. " * 20
    # The model split line 1 over several lines: still one line, nothing lost
    content = "1|Das ist so.\n" + "\n".join(["Das ist so."] * 19)
    assert merge_cleaned([long], content) == [" ".join(["Das ist so."] * 20)]
    # Only the first sentence came back: keep the original
    assert merge_cleaned([long], "1|Das ist so.") == [long]


@pytest.mark.parametrize("text,dialect", [
    ("Mir händ das gescht bschproche.", True),
    ("Grüezi zäme, ich bi d'Anna.", True),
    ("Offerte schicke bis am Friitig.", True),
    ("Das ist so nicht der Fall.", False),
    ("Herr Präsident, liebe Kolleginnen und Kollegen. Es ist so.", False),
    ("Let us meet on Monday.", False),
])
def test_has_dialect(text, dialect):
    assert has_dialect(text) is dialect


def _fake_llm(monkeypatch, translate, calls=None):
    def fake_post(url, headers, json, timeout):
        if calls is not None:
            calls.append(json)
        lines = json["messages"][1]["content"].splitlines()
        out = "\n".join(f"{n}|{translate(text)}" for n, text in (l.split("|", 1) for l in lines))
        return httpx.Response(200, json={"choices": [{"message": {"content": out}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)


DIALECT = {
    "Grüezi zäme, ich bi d'Anna.": "Grüezi zusammen, ich bin Anna.",
    "Mach es Notiz: Budget isch fix.": "Mach eine Notiz: Das Budget ist fix.",
    "Erstell en Task: Offerte schicke bis am Friitig, Marco.":
        "Erstell einen Task: Offerte schicken bis Freitag, Marco.",
}


def test_clean_lines_in_chunks_with_vocabulary(monkeypatch):
    config = NotetakerConfig()
    config.voxtral.api_key = "k"
    config.voxtral.vocabulary = ["TWINT"]
    calls = []
    _fake_llm(monkeypatch, lambda s: s.upper(), calls)
    lines = [f"zeile {i} isch fix" for i in range(85)] + ["Das ist schon Hochdeutsch."]
    assert clean_lines(lines, config) == [l.upper() for l in lines[:85]] + [lines[85]]
    assert len(calls) == 3  # chunks of 40, only lines with dialect
    assert calls[0]["model"] == "mistral-small-2603"
    assert "TWINT" in calls[0]["messages"][0]["content"]


def test_clean_lines_falls_back_on_error():
    config = NotetakerConfig()
    config.voxtral.api_key = "k"
    # httpx.post is blocked in tests (conftest): clean-up keeps the original
    assert clean_lines(["Mir händ Zyt."], config) == ["Mir händ Zyt."]


@pytest.mark.parametrize("meeting,detected,cleanup,expected", [
    ("de-CH", "de", True, True),
    ("de-CH", "en", True, True),
    ("auto", "de", True, True),
    ("auto", "en", True, False),
    ("de", "de", True, False),
    ("de-CH", "de", False, False),
])
def test_should_clean(meeting, detected, cleanup, expected):
    config = NotetakerConfig()
    config.service.language = meeting
    config.voxtral.dialect_cleanup = cleanup
    assert should_clean(config, detected) is expected


def test_meeting_pipeline_cleans_dialect(tmp_path, monkeypatch):
    config = NotetakerConfig()
    config.voxtral.api_key = "k"
    config.storage.auto_upload = False
    config.summary.enabled = False
    nt = Notetaker(config)
    audio = tmp_path / "m.wav"
    audio.write_bytes(b"RIFF")
    raw = list(DIALECT)
    monkeypatch.setattr(nt, "transcribe", lambda f, lang, diarize=False, fast=False:
                        TranscriptionResult(text="", language="de", confidence=None, duration=3,
                                            segments=[TranscriptSegment(i, i + 1, text, f"speaker_{i % 2}")
                                                      for i, text in enumerate(raw)]))
    _fake_llm(monkeypatch, lambda s: DIALECT.get(s, s))
    result = nt.process_recording(str(audio), start_time=REF)

    # Name found in the dialect introduction ("ich bi d'Anna")
    assert result.speakers[0] == "Anna"
    lines = result.transcript.splitlines()
    assert lines[0] == "[Anna] Grüezi zusammen, ich bin Anna."
    assert "Mach eine Notiz: Das Budget ist fix." in result.transcript
    assert [n["content"] for n in result.memo.notes] == ["Das Budget ist fix"]
    task = result.memo.tasks[0]
    assert (task["owner"], task["title"], task["due_date"]) == \
        ("Marco", "Offerte schicken", date(2026, 11, 6))
    nt.close()


# --- dialect commands (live, before any clean-up) ---------------------------------------

@pytest.mark.parametrize("text,kind,content", [
    ("Mach es Notiz: Budget isch fix.", "note", "Budget isch fix"),
    ("Ja, mach e Notiz: Termin am Mäntig.", "note", "Termin am Mäntig"),
    ("Schriib das uf: Offerte bis Friitig.", "note", "Offerte bis Friitig"),
    ("Erstell en Task: Server bstelle.", "task", "Server bstelle"),
    ("Ufgab: Sabine macht de Plan.", "task", "Sabine macht de Plan"),
    ("Lueg mol nach: TWINT Chöschte.", "research", "TWINT Chöschte"),
])
def test_swiss_german_commands(text, kind, content):
    command = CommandParser().parse(text, "auto", strict=True)
    assert command.command_type.value == kind
    assert command.language == "de-CH"
    assert (command.parameters.get("content") or command.parameters.get("query")) == content


@pytest.mark.parametrize("text,action", [
    ("Beend d'Ufnahm.", "stop"),
    ("Ufnahm stoppe.", "stop"),
    ("Start d'Ufnahm.", "start"),
])
def test_swiss_german_recording_commands(text, action):
    command = CommandParser().parse(text, "de-CH", strict=True)
    assert command.parameters["action"] == action


@pytest.mark.parametrize("text", [
    "Mir händ das gescht bschproche.",
    "Ich such no en Termin.",
    "Das isch halt so.",
])
def test_ordinary_swiss_german_is_not_a_command(text):
    assert CommandParser().parse(text, "de-CH", strict=True) is None


# --- Swiss dates -------------------------------------------------------------------

@pytest.mark.parametrize("text,due", [
    ("Server bstelle bis am Zischtig", date(2026, 11, 10)),
    ("Offerte schicke bis am Friitig", date(2026, 11, 6)),
    ("Bricht abgä bis Ändi Novämber", date(2026, 11, 30)),
    ("Budget prüefe bis morn", date(2026, 11, 4)),
    ("Plan mache bis Ändi vo de Wuche", date(2026, 11, 6)),
    ("Kampagneplan bis Mitti Dezämber", date(2026, 12, 15)),
])
def test_swiss_due_dates(text, due):
    assert parse_task_details(text, [], REF)["due_date"] == due


def test_device_announcements_removed_from_transcript(tmp_path, monkeypatch):
    config = NotetakerConfig()
    config.storage.auto_upload = False
    config.voxtral.dialect_cleanup = False
    config.summary.enabled = False
    nt = Notetaker(config)
    audio = tmp_path / "m.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr(nt, "transcribe", lambda f, lang, diarize=False, fast=False:
                        TranscriptionResult(text="", language="de", confidence=None, duration=3,
                                            segments=[
                                                TranscriptSegment(0, 1, "Aufnahme gestartet, diese Besprechung wird aufgezeichnet.", "speaker_0"),
                                                TranscriptSegment(1, 2, "Kannst du mit mir reden?", "speaker_1"),
                                                TranscriptSegment(2, 3, "Notiz notiert. Gut, weiter.", "speaker_0"),
                                            ]))
    result = nt.process_recording(str(audio), start_time=REF)
    assert "Aufnahme gestartet" not in result.transcript
    assert "Notiz notiert" not in result.transcript
    assert "Kannst du mit mir reden?" in result.transcript and "Gut, weiter." in result.transcript
    nt.close()
