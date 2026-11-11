# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss places in the transcript: marked only when certain
"""

from datetime import datetime

import httpx
import pytest

from voxtral_notetaker import Notetaker, NotetakerConfig
from voxtral_notetaker.places import mark_places, places_in
from voxtral_notetaker.transcription import TranscriptionResult, TranscriptSegment


@pytest.mark.parametrize("text,marked", [
    ("Im Herbst fahre ich nach Hindelbank, dann nach Léchelles.",
     "Im Herbst fahre ich nach 📍Hindelbank, dann nach 📍Léchelles."),
    # A list after a place word
    ("Der Wettbewerb findet in Wolfhalden, Linthal und Lutzenberg statt.",
     "Der Wettbewerb findet in 📍Wolfhalden, 📍Linthal und 📍Lutzenberg statt."),
    # Multi-word official names need no place word
    ("Treffpunkt: Küssnacht am Rigi.", "Treffpunkt: 📍Küssnacht am Rigi."),
    ("Wir fahren nach St. Gallen.", "Wir fahren nach 📍St. Gallen."),
    # German names of French-speaking towns
    ("Morgen bin ich in Genf.", "Morgen bin ich in 📍Genf."),
    # Not certain: surname, ordinary words, no place context, part of a word
    ("Frau von Gunten kommt später.", "Frau von Gunten kommt später."),
    ("Das war ein Scherz.", "Das war ein Scherz."),
    ("Wir gehen in den Wald und ins Dorf.", "Wir gehen in den Wald und ins Dorf."),
    ("Hindelbank hat angerufen.", "Hindelbank hat angerufen."),
    ("Ich war am Zürichsee.", "Ich war am Zürichsee."),
    # Already marked: not marked twice
    ("nach 📍Bern", "nach 📍Bern"),
])
def test_mark_places(text, marked):
    assert mark_places(text) == marked


def test_speaker_labels_are_never_marked():
    text = "[Wil] Ich wohne in Wil."
    assert mark_places(text) == "[Wil] Ich wohne in 📍Wil."
    assert places_in(text) == ["Wil"]


def test_only_allowed_names_are_marked():
    text = "Wir fahren von Pratteln nach Genf."
    assert mark_places(text, allowed=["Pratteln"]) == "Wir fahren von 📍Pratteln nach Genf."


def test_meeting_marks_places_heard_not_guessed(tmp_path, monkeypatch):
    config = NotetakerConfig()
    config.voxtral.api_key = "k"
    config.storage.auto_upload = False
    config.summary.enabled = False
    nt = Notetaker(config)
    audio = tmp_path / "m.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr(nt, "transcribe", lambda f, lang, diarize=False, fast=False:
                        TranscriptionResult(text="", language="de", confidence=None, duration=2,
                                            segments=[
                                                TranscriptSegment(0, 1, "Mir fahre vo Pratteln uf Genpe.", "speaker_0"),
                                            ]))

    # The clean-up makes "Genpe" (Gempen) into "Genf": a guess, never marked
    def fake_post(url, headers, json, timeout):
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "1|Wir fahren von Pratteln nach Genf."}}]},
            request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    result = nt.process_recording(str(audio), start_time=datetime(2026, 11, 3))
    nt.close()
    assert "von 📍Pratteln nach Genf." in result.transcript
    assert result.memo.places == ["Pratteln"]
    assert "**Orte:** Pratteln" in result.memo.to_markdown()


def test_marking_can_be_turned_off(tmp_path, monkeypatch):
    config = NotetakerConfig()
    config.storage.auto_upload = False
    config.summary.enabled = False
    config.voxtral.dialect_cleanup = False
    config.voxtral.mark_places = False
    nt = Notetaker(config)
    audio = tmp_path / "m.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr(nt, "transcribe", lambda f, lang, diarize=False, fast=False:
                        TranscriptionResult(text="Wir fahren nach Bern.", language="de",
                                            confidence=None, duration=1, segments=[]))
    result = nt.process_recording(str(audio), start_time=datetime(2026, 11, 3))
    nt.close()
    assert "📍" not in result.transcript and result.memo.places == []
