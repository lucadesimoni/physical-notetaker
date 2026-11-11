# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Names learned from past meetings, and English passages redone in German
"""

import wave
from datetime import datetime

import numpy as np
import pytest

from voxtral_notetaker import Notetaker, NotetakerConfig
from voxtral_notetaker.config import Language
from voxtral_notetaker.jobs import DONE, PENDING, JobProcessor, JobStore
from voxtral_notetaker.language_check import cut_wav, looks_english, looks_german
from voxtral_notetaker.transcription import TranscriptionResult, TranscriptSegment
from voxtral_notetaker.vocabulary import is_name, learned_names, task_owners

from test_service import FakeNotetaker, write_wav


# --- learned names ----------------------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ("Anna", True), ("Anna Meier", True), ("Hans-Peter", True), ("Zoë", True),
    ("speaker_0", False), ("Speaker 1", False), ("Unknown", False), ("–", False),
    ("Wer", False), ("x", False), ("anna", False),
])
def test_is_name(text, name):
    assert is_name(text) is name


def _memo(path, owners):
    rows = "\n".join(f"| {o} | Etwas | – |" for o in owners)
    path.write_text(f"# Memo\n\n## Notizen\n\n- x\n\n## Aufgaben\n\n| Wer | Was | Bis |\n"
                    f"|---|---|---|\n{rows}\n", encoding="utf-8")
    return str(path)


def test_task_owners(tmp_path):
    assert task_owners(_memo(tmp_path / "m.md", ["Marco", "–"])) == ["Marco", "–"]
    assert task_owners(str(tmp_path / "missing.md")) == []


def test_learned_names_ranked(tmp_path):
    class J:
        def __init__(self, speakers=None, overrides=None, memo=None):
            self.speakers, self.speaker_overrides, self.memo_file = speakers or {}, overrides or {}, memo
    jobs = [  # newest first
        J({"speaker_0": "Anna", "speaker_1": "speaker_1"}),
        J({"speaker_0": "Reto"}, {"speaker_1": "Sabine Keller"}),
        J({"speaker_0": "Anna"}, memo=_memo(tmp_path / "m.md", ["Marco"])),
    ]
    assert learned_names(jobs) == ["Anna", "Sabine Keller", "Reto", "Marco"]


def test_jobs_use_learned_names(tmp_path):
    config = NotetakerConfig()
    config.voxtral.api_key = "k"
    config.voxtral.vocabulary = ["TWINT"]
    config.service.recordings_dir = str(tmp_path / "rec")
    config.storage.auto_upload = False
    store = JobStore(config.service.recordings_dir)
    old = store.create(str(tmp_path / "rec" / "meeting_20261101_090000.wav"), status=DONE)
    old.speaker_overrides = {"speaker_0": "Sabine Keller"}
    store.save(old)
    seen = []

    class Recording(FakeNotetaker):
        def __init__(self, cfg):
            super().__init__(cfg)
            seen.append(list(cfg.voxtral.vocabulary))

    path = store.new_recording_path()
    write_wav(path)
    job = JobProcessor(config, store, Recording).process(store.create(path, status=PENDING))
    assert job.status == DONE
    assert seen[-1] == ["TWINT", "Sabine Keller"]
    assert config.voxtral.vocabulary == ["TWINT"]  # the settings themselves are unchanged

    config.voxtral.learn_vocabulary = False
    path = store.new_recording_path()
    write_wav(path)
    JobProcessor(config, store, Recording).process(store.create(path, status=PENDING))
    assert seen[-1] == ["TWINT"]


# --- English passages in German meetings -------------------------------------------

@pytest.mark.parametrize("text,english", [
    ("If I'm in the eating.", True),
    ("I want a inbuilt brick.", True),
    ("Ich wohne in Belpberg.", False),
    ("Das Meeting ist on hold, aber wir machen weiter.", False),
    ("Merci vielmals.", False),
    ("Nous sommes d'accord avec le projet.", False),  # French: not a flip to English
    ("OK.", False),
])
def test_looks_english(text, english):
    assert looks_english(text) is english


def _tone_wav(path, seconds=3.0, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16).tobytes())


def test_cut_wav(tmp_path):
    source, part = tmp_path / "a.wav", tmp_path / "b.wav"
    _tone_wav(source)
    assert cut_wav(str(source), 1.0, 2.0, str(part))
    with wave.open(str(part)) as wf:
        assert wf.getnframes() == pytest.approx(16000 * 1.6, abs=2)  # 1 s + 0.3 s each side


def _meeting(tmp_path, monkeypatch, language="de-CH", flips=True):
    config = NotetakerConfig()
    config.service.language = language
    config.storage.auto_upload = False
    config.summary.enabled = False
    config.voxtral.dialect_cleanup = False
    config.voxtral.fix_language_flips = flips
    nt = Notetaker(config)
    audio = tmp_path / "m.wav"
    _tone_wav(audio, 4.0)
    calls = []

    def transcribe(path, lang, diarize=False, fast=False):
        calls.append(lang)
        if diarize:
            return TranscriptionResult(text="", language="de", confidence=None, duration=4, segments=[
                TranscriptSegment(0, 2, "Grüezi mitenand, wir fangen an.", "speaker_0"),
                TranscriptSegment(2, 4, "I want a inbuilt brick.", "speaker_1")])
        return TranscriptionResult(text="Ich wohne in Bautbrück.", language="de",
                                   confidence=None, duration=2)

    monkeypatch.setattr(nt, "transcribe", transcribe)
    result = nt.process_recording(str(audio), language=Language(language), diarize=True,
                                  start_time=datetime(2026, 11, 3))
    nt.close()
    return result, calls


def test_english_passage_redone_in_german(tmp_path, monkeypatch):
    result, calls = _meeting(tmp_path, monkeypatch)
    assert calls == [Language.DE_CH, Language.DE]  # one redo, German fixed
    assert "Ich wohne in Bautbrück." in result.transcript
    assert "inbuilt brick" not in result.transcript
    assert "Grüezi mitenand" in result.transcript


def test_english_kept_when_turned_off_or_english_meeting(tmp_path, monkeypatch):
    result, calls = _meeting(tmp_path, monkeypatch, flips=False)
    assert len(calls) == 1 and "inbuilt brick" in result.transcript
    (tmp_path / "en").mkdir()
    result, calls = _meeting(tmp_path / "en", monkeypatch, language="en")
    assert len(calls) == 1 and "inbuilt brick" in result.transcript


def test_looks_german():
    assert looks_german("Ich wohne in Bautbrück.")
    assert not looks_german("Evtl.") and not looks_german("If I'm in the eating.")
