"""
Tests for the usability features: German texts, spoken prompts, disk cleanup,
live voice commands, renaming speakers, finding the device
"""

import os
import time
import wave
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from voxtral_notetaker import Notetaker, NotetakerConfig
from voxtral_notetaker import disk
from voxtral_notetaker.device import Controls, Feedback, Voice
from voxtral_notetaker.i18n import t, TEXTS
from voxtral_notetaker.jobs import DONE, PENDING, JobStore
from voxtral_notetaker.live import LiveListener, read_new_audio
from voxtral_notetaker.network import speakable_address
from voxtral_notetaker.transcription import TranscriptionResult, TranscriptSegment
from voxtral_notetaker.web import start_web_server

from test_service import SilentFeedback, make_service, write_wav, get, post


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    c = NotetakerConfig()
    c.voxtral.api_key = "key"
    c.service.recordings_dir = str(tmp_path / "rec")
    c.storage.local_path = str(tmp_path / "rec")
    c.storage.auto_upload = False
    return c


# --- German / English texts ---------------------------------------------------

def test_texts_complete_and_german_default():
    assert set(TEXTS['de']) == set(TEXTS['en'])
    assert t('start_meeting') == "● Besprechung starten"
    assert t('start_meeting', 'en') == "● Start meeting"
    assert t('ev_recovered', 'de-CH', n=2) == "2 Aufnahme(n) nach Neustart wiederhergestellt"
    assert t('unknown_key') == 'unknown_key'


def test_web_page_in_german(config, tmp_path):
    svc = make_service(config, tmp_path)
    server = start_web_server(svc, host="127.0.0.1", port=0)
    try:
        html = get(f"http://127.0.0.1:{server.server_address[1]}/")[1]
        assert 'lang="de"' in html and "Besprechung starten" in html and "Speicher:" in html
    finally:
        server.shutdown()


# --- spoken prompts -------------------------------------------------------------

@pytest.mark.skipif(not shutil.which('espeak-ng'), reason="espeak-ng not installed")
def test_voice_synthesizes_and_caches(tmp_path):
    voice = Voice('de', cache_dir=str(tmp_path))
    path = voice.wav_for(t('say_start'))
    assert path and voice.wav_for(t('say_start')) == path
    with wave.open(path) as wf:
        assert wf.getnframes() / wf.getframerate() > 1.0


def test_voice_unavailable_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    assert not Voice('de', cache_dir=str(tmp_path)).available
    feedback = Feedback(NotetakerConfig().device)
    assert feedback.voice is None
    feedback.recording()  # no sound output, no crash
    feedback.close()


def test_feedback_messages():
    fb = SilentFeedback()
    fb.recording()
    assert fb.events == ['recording']
    # The recording announcement includes the consent notice
    assert "aufgezeichnet" in t('say_start')
    assert "E-Mail" in t('say_stop_email')


# --- disk cleanup ---------------------------------------------------------------

def _done_job(store, name, age_days, size=1000):
    path = os.path.join(store.directory, f"{name}.wav")
    write_wav(path, 0.1)
    memo = path.replace('.wav', '_memo.md')
    open(memo, 'w').write("memo")
    job = store.create(path, status=DONE)
    job.memo_file = memo
    store.save(job)
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))
    return job


def test_cleanup_deletes_old_finished_audio_only(config):
    store = JobStore(config.service.recordings_dir)
    old = _done_job(store, "old", 40)
    recent = _done_job(store, "recent", 2)
    pending_path = os.path.join(store.directory, "pending.wav")
    write_wav(pending_path, 0.1)
    os.utime(pending_path, (0, 0))  # very old but not processed yet
    store.create(pending_path, status=PENDING)

    deleted = disk.cleanup(store, config)
    assert [j.id for j in deleted] == ["old"]
    assert not os.path.exists(old.audio_file) and os.path.exists(old.memo_file)
    assert os.path.exists(recent.audio_file) and os.path.exists(pending_path)
    assert store.get("old").audio_deleted


def test_cleanup_frees_space_oldest_first(config, monkeypatch):
    config.service.keep_audio_days = 0  # never by age
    store = JobStore(config.service.recordings_dir)
    for i, age in enumerate([5, 3, 1]):
        _done_job(store, f"m{i}", age)
    free = {"n": 0}
    monkeypatch.setattr(disk, "free_bytes",
                        lambda p: free["n"] * disk.MB)

    def fake_remove(path, _remove=os.remove):
        _remove(path)
        free["n"] += 300

    monkeypatch.setattr(os, "remove", fake_remove)
    deleted = disk.cleanup(store, config)
    assert [j.id for j in deleted] == ["m0", "m1"]  # oldest first, until 500 MB free


def test_unsent_email_with_audio_attachment_keeps_audio(config):
    config.email.enabled = True
    config.email.smtp_host = "smtp"
    config.email.to_emails = ["a@example.com"]
    config.email.attach_audio = True
    store = JobStore(config.service.recordings_dir)
    _done_job(store, "old", 40)
    assert disk.cleanup(store, config) == []


def test_start_refused_when_storage_full(config, tmp_path, monkeypatch):
    import voxtral_notetaker.service as service_mod
    monkeypatch.setattr(service_mod, "free_bytes", lambda p: 10 * disk.MB)
    svc = make_service(config, tmp_path)
    assert not svc.start_meeting()
    assert 'error' in svc.feedback.events


def test_recording_stopped_when_storage_runs_out(config, tmp_path, monkeypatch):
    import voxtral_notetaker.service as service_mod
    svc = make_service(config, tmp_path)
    svc.start_meeting()
    monkeypatch.setattr(service_mod, "free_bytes", lambda p: 10 * disk.MB)
    svc._last_disk_check = 0
    svc.tick()
    assert not svc.is_recording
    assert svc.store.all()[0].status == PENDING  # saved and queued


# --- live voice commands -----------------------------------------------------------

def test_read_new_audio_is_incremental(tmp_path):
    src = tmp_path / "rec.wav"
    write_wav(src, 2.0)
    out = tmp_path / "chunk.wav"
    end = read_new_audio(str(src), 0, str(out))
    assert end == 32000
    assert read_new_audio(str(src), end, str(out)) == 0  # nothing new


def _live(config, tmp_path, texts):
    items, stops = [], []
    audio = tmp_path / "rec.wav"
    write_wav(audio, 1.0)
    listener = LiveListener(config, str(audio), Notetaker,
                            on_item=lambda kind, text: items.append((kind, text)),
                            on_stop=lambda: stops.append(1))
    listener._notetaker = Notetaker(config)
    calls = []

    def fake_transcribe(f, lang, diarize=False, fast=False):
        calls.append(fast)
        return TranscriptionResult(text=texts.pop(0), language="de", confidence=None, duration=1)

    listener._notetaker.transcribe = fake_transcribe
    return listener, audio, items, stops, calls


def test_live_commands_confirmed_once(config, tmp_path):
    listener, audio, items, stops, calls = _live(config, tmp_path, [
        "Gut. Mach eine Notiz: Budget ist fix. Ich suche noch einen Termin.",
        "Mach eine Notiz: Budget ist fix. Erstell einen Task: Offerte senden bis Freitag.",
    ])
    assert listener.check_once() == 1
    write_wav(audio, 2.0)  # the recording grew
    assert listener.check_once() == 1  # the repeated note (overlap) is not confirmed again
    assert items == [("note", "Budget ist fix"), ("task", "Offerte senden bis Freitag")]
    assert calls == [True, True]  # fast Mini model
    assert stops == []
    listener.stop()


def test_live_voice_stop(config, tmp_path):
    listener, audio, items, stops, _ = _live(config, tmp_path, ["Danke allen. Beende die Aufnahme."])
    listener.check_once()
    assert stops == [1]
    listener.stop()


def test_live_skipped_without_api_key(config, tmp_path):
    config.voxtral.api_key = ""
    listener, *_ = _live(config, tmp_path, ["Notiz: x."])
    assert listener.check_once() == 0
    listener.stop()


def test_service_confirms_live_items(config, tmp_path):
    svc = make_service(config, tmp_path)
    svc._live_item("task", "Offerte senden")
    assert svc.feedback.events == ['confirm']
    assert svc.status()['live_items'] == [("task", "Offerte senden")]


# --- renaming speakers / remaking memos ------------------------------------------------

def test_memo_remade_from_cache_with_new_names(config, monkeypatch):
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path(datetime(2026, 10, 26, 9))
    write_wav(path, 1.0)
    calls = []

    class CountingNotetaker(Notetaker):
        def transcribe(self, f, lang=None, diarize=False, fast=False):
            calls.append(f)
            return TranscriptionResult(text="", language="de", confidence=None, duration=1,
                                       segments=[
                                           TranscriptSegment(0, 1, "Grüezi zusammen.", "speaker_0"),
                                           TranscriptSegment(1, 2, "Mein Name ist Marco.", "speaker_1"),
                                       ])

    svc = make_service(config, Path(store.directory))
    svc.notetaker_factory = CountingNotetaker
    store.create(path, status=PENDING)
    svc.process_due()
    job = store.all()[0]
    assert job.status == DONE
    assert job.speakers == {"speaker_0": "speaker_0", "speaker_1": "Marco"}

    assert svc.remake_memo(job.id, {"speaker_0": "Anna", "speaker_1": "Marco"})
    svc.process_due()
    job = store.get(job.id)
    memo = open(job.memo_file, encoding="utf-8").read()
    assert "**Teilnehmende:** Anna, Marco" in memo
    assert len(calls) == 1  # transcribed once, the remake used the cache

    # Works even after the audio was deleted
    os.remove(job.audio_file)
    assert svc.remake_memo(job.id, {"speaker_0": "Annina"})
    svc.process_due()
    assert store.get(job.id).status == DONE
    assert "Annina" in open(store.get(job.id).memo_file, encoding="utf-8").read()


def test_rename_form_on_meeting_page(config, tmp_path):
    config.service.ui_language = "en"
    svc = make_service(config, tmp_path)
    store = svc.store
    path = store.new_recording_path()
    write_wav(path)
    job = store.create(path, status=DONE)
    job.speakers = {"speaker_0": "speaker_0"}
    job.memo_file = path.replace(".wav", "_memo.md")
    open(job.memo_file, "w").write("# Memo")
    store.save(job)
    server = start_web_server(svc, host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        html = get(f"{base}/meeting/{job.id}")[1]
        assert 'name="name_0"' in html and "Create memo again" in html
        status, html = post(f"{base}/meeting/{job.id}/speakers",
                            {"id_0": "speaker_0", "name_0": "Anna"})
        assert "Creating the memo again" in html
        job = store.get(job.id)
        assert job.speaker_overrides == {"speaker_0": "Anna"} and job.status == PENDING
    finally:
        server.shutdown()


def test_remake_refused_while_recording(config, tmp_path):
    svc = make_service(config, tmp_path)
    svc.start_meeting()
    assert not svc.remake_memo(svc.store.all()[0].id, {"speaker_0": "Anna"})
    svc.stop_meeting()


# --- finding the device ---------------------------------------------------------------

def test_sticker_page_has_qr_codes(config, tmp_path):
    pytest.importorskip("segno")
    svc = make_service(config, tmp_path)
    server = start_web_server(svc, host="127.0.0.1", port=0)
    try:
        html = get(f"http://127.0.0.1:{server.server_address[1]}/sticker")[1]
        assert html.count("<svg") >= 1 and ".local" in html
        assert "Taste drücken" in html
    finally:
        server.shutdown()


def test_speakable_address():
    assert speakable_address("192.168.1.23", 80) == "1 9 2 Punkt 1 6 8 Punkt 1 Punkt 2 3"
    assert speakable_address("10.0.0.5", 8080, "en") == "1 0 dot 0 dot 0 dot 5, port 8 0 8 0"


def test_long_press_says_address_short_press_toggles():
    presses, long_presses = [], []
    device = NotetakerConfig().device
    controls = Controls(device, lambda: presses.append(1), on_long_press=lambda: long_presses.append(1))
    controls.key_event("jabra", "KEY_PHONE", 1, now=100.0)
    controls.key_event("jabra", "KEY_PHONE", 0, now=100.2)   # short
    controls._last_press = 0
    controls.key_event("jabra", "KEY_PHONE", 1, now=200.0)
    controls.key_event("jabra", "KEY_PHONE", 2, now=201.0)   # auto-repeat ignored
    controls.key_event("jabra", "KEY_PHONE", 0, now=203.5)   # held 3.5 s
    controls.key_event("jabra", "KEY_VOLUMEUP", 1, now=300.0)  # other keys ignored
    controls.key_event("jabra", "KEY_VOLUMEUP", 0, now=300.1)
    assert presses == [1] and long_presses == [1]


def test_announce_address(config, tmp_path, monkeypatch):
    svc = make_service(config, tmp_path)
    said = []
    svc.feedback = SilentFeedback()
    svc.feedback.say_address = lambda text: said.append(text)
    monkeypatch.setattr("voxtral_notetaker.network.local_ip", lambda: "192.168.1.5")
    config.web.port = 80
    svc.announce_address()
    assert said == ["1 9 2 Punkt 1 6 8 Punkt 1 Punkt 5"]
