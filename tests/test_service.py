# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Tests for the always-on device: queue, retry, service, email, speakers, web page
"""

import json
import time
import wave
import smtplib
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from email import message_from_bytes
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from voxtral_notetaker import NotetakerConfig
from voxtral_notetaker.audio import RecordingInfo
from voxtral_notetaker.device import Controls, Feedback
from voxtral_notetaker.jobs import (DONE, FAILED, PENDING, RECORDING, JobProcessor, JobStore,
                                    classify_error, describe_error)
from voxtral_notetaker.notify import build_memo_email, memo_subject
from voxtral_notetaker.service import NotetakerService
from voxtral_notetaker.speakers import detect_speaker_names, find_introduced_name
from voxtral_notetaker.web import start_web_server


def write_wav(path, seconds=1.0, rate=16000):
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(np.zeros(int(seconds * rate), dtype=np.int16).tobytes())


def http_error(code):
    request = httpx.Request("POST", "https://api.mistral.ai/v1/audio/transcriptions")
    return httpx.HTTPStatusError("err", request=request,
                                 response=httpx.Response(code, request=request, text="nope"))


class FakeNotetaker:
    """Stands in for Notetaker: records a short WAV and 'transcribes' it"""
    fail_with = None
    processed = []

    def __init__(self, config):
        self.config = config
        self.path = None

    def start_recording(self, path):
        self.path = path
        write_wav(path, 0.5)
        return True

    def stop_recording(self):
        return RecordingInfo(file_path=self.path, duration=0.5, sample_rate=16000)

    def process_recording(self, audio_file, **kwargs):
        if FakeNotetaker.fail_with:
            raise FakeNotetaker.fail_with
        FakeNotetaker.processed.append(audio_file)
        memo = audio_file.replace('.wav', '_memo.md')
        transcript = audio_file.replace('.wav', '.txt')
        with open(memo, 'w') as f:
            f.write("# Protokoll: Test\n")
        with open(transcript, 'w') as f:
            f.write("[Anna] Hallo")
        return SimpleNamespace(memo_file=memo, transcript_file=transcript,
                               memo=SimpleNamespace(title="Besprechung Test"),
                               language="de", duration=0.5)

    def close(self):
        pass


class SilentFeedback:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        return lambda *a, **k: self.events.append(name)


@pytest.fixture(autouse=True)
def reset_fake():
    FakeNotetaker.fail_with = None
    FakeNotetaker.processed = []


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    c = NotetakerConfig()
    c.voxtral.api_key = "key"
    c.service.recordings_dir = str(tmp_path / "rec")
    c.storage.local_path = str(tmp_path / "cloud")
    c.service.retry_interval_seconds = 60
    c.service.ui_language = "en"
    return c


# --- queue -----------------------------------------------------------------

def test_recover_repairs_interrupted_recording(tmp_path, config):
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path(datetime(2026, 10, 26, 9, 0))
    write_wav(path, 2.0)
    store.create(path, status=RECORDING)
    with open(path, 'ab') as f:  # audio written after the last header update
        f.write(b'\x00\x00' * 16000)
    # a recording copied in by hand, without a job file
    write_wav(tmp_path / "rec" / "manual.wav", 1.0)

    recovered = store.recover()
    assert len(recovered) == 2
    jobs = {j.id: j for j in store.all()}
    assert jobs['meeting_20261026_090000'].status == PENDING
    assert jobs['meeting_20261026_090000'].duration == pytest.approx(3.0)
    assert jobs['manual'].status == PENDING


def test_job_done_with_upload_and_email(config, monkeypatch):
    config.email.enabled = True
    config.email.smtp_host = "smtp.test"
    config.email.to_emails = ["team@example.com"]
    sent = []
    monkeypatch.setattr("voxtral_notetaker.jobs.send_email", lambda cfg, msg: sent.append(msg))
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path()
    write_wav(path)
    job = store.create(path, status=PENDING)

    job = JobProcessor(config, store, FakeNotetaker).process(job)
    assert job.status == DONE and job.uploaded and job.emailed
    assert sent[0]['Subject'] == "Protokoll: Besprechung Test"
    assert sent[0]['To'] == "team@example.com"
    names = [p.get_filename() for p in sent[0].iter_attachments()]
    assert names == [job.id + "_memo.md", job.id + ".txt"]


def test_network_error_is_retried_with_backoff(config):
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path()
    write_wav(path)
    job = store.create(path, status=PENDING)
    FakeNotetaker.fail_with = httpx.ConnectError("offline")

    processor = JobProcessor(config, store, FakeNotetaker)
    job = processor.process(job)
    assert job.status == PENDING and "No connection" in job.last_error
    first_delay = job.next_attempt_at - time.time()
    assert 55 < first_delay <= 60
    assert store.due() == []  # not before the retry time

    job = processor.process(job)
    assert 115 < job.next_attempt_at - time.time() <= 120  # doubled

    FakeNotetaker.fail_with = None
    job = processor.process(job)
    assert job.status == DONE


def test_rejected_api_key_needs_the_user(config):
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path()
    write_wav(path)
    job = store.create(path, status=PENDING)
    FakeNotetaker.fail_with = http_error(401)

    job = JobProcessor(config, store, FakeNotetaker).process(job)
    assert job.status == FAILED
    assert "API key rejected" in job.last_error
    assert store.retry() == 1
    assert store.get(job.id).status == PENDING


def test_missing_api_key_fails_with_clear_message(config):
    config.voxtral.api_key = ""
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path()
    write_wav(path)
    job = JobProcessor(config, store, FakeNotetaker).process(store.create(path, status=PENDING))
    assert job.status == FAILED and "No Mistral API key" in job.last_error


def test_failed_email_does_not_redo_transcription(config, monkeypatch):
    config.email.enabled = True
    config.email.smtp_host = "smtp.test"
    config.email.to_emails = ["a@example.com"]
    calls = []

    def flaky_send(cfg, msg):
        calls.append(1)
        if len(calls) == 1:
            raise smtplib.SMTPServerDisconnected("gone")

    monkeypatch.setattr("voxtral_notetaker.jobs.send_email", flaky_send)
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path()
    write_wav(path)
    processor = JobProcessor(config, store, FakeNotetaker)
    job = processor.process(store.create(path, status=PENDING))
    assert job.status == PENDING and not job.emailed
    job = processor.process(job)
    assert job.status == DONE and job.emailed
    assert len(FakeNotetaker.processed) == 1  # transcribed only once


@pytest.mark.parametrize("error,temporary", [
    (httpx.ConnectError("x"), True),
    (http_error(429), True),
    (http_error(503), True),
    (http_error(400), False),
    (http_error(403), False),
    (smtplib.SMTPAuthenticationError(535, b"bad"), False),
    (ValueError("broken"), False),
])
def test_classify_error(error, temporary):
    assert classify_error(error) is temporary
    assert describe_error(error)


# --- service ---------------------------------------------------------------

def make_service(config, tmp_path):
    return NotetakerService(config=config, config_path=str(tmp_path / "config.yaml"),
                            notetaker_factory=FakeNotetaker, feedback=SilentFeedback(),
                            poll_seconds=0.05)


def test_button_toggles_and_memo_is_created(config, tmp_path):
    svc = make_service(config, tmp_path)
    svc.toggle()
    assert svc.is_recording
    assert svc.store.all()[0].status == RECORDING
    svc.toggle()
    assert not svc.is_recording
    assert svc.process_due() == 1
    job = svc.store.all()[0]
    assert job.status == DONE and job.memo_file
    assert svc.feedback.events[:2] == ['recording', 'stopped']


def test_recording_stops_at_time_limit(config, tmp_path):
    config.max_recording_minutes = 10
    svc = make_service(config, tmp_path)
    svc.start_meeting()
    svc._recording_since = time.time() - 6 * 60
    svc.tick()
    assert svc.is_recording and 'warning' in svc.feedback.events
    svc._recording_since = time.time() - 10 * 60
    svc.tick()
    assert not svc.is_recording
    assert svc.store.all()[0].status == PENDING


def test_microphone_missing_gives_error_feedback(config, tmp_path):
    class NoMic(FakeNotetaker):
        def start_recording(self, path):
            return False

    svc = make_service(config, tmp_path)
    svc.notetaker_factory = NoMic
    assert not svc.start_meeting()
    assert 'error' in svc.feedback.events
    assert "microphone" in svc.last_event


def test_shutdown_saves_running_recording(config, tmp_path):
    svc = make_service(config, tmp_path)
    svc.start_meeting()
    svc.shutdown()
    assert svc.store.all()[0].status == PENDING  # processed after restart


def test_worker_thread_processes_in_background(config, tmp_path):
    svc = make_service(config, tmp_path)
    svc.start(web=False, controls=False)
    try:
        svc.toggle()
        svc.toggle()
        deadline = time.time() + 5
        while time.time() < deadline and svc.store.all()[0].status != DONE:
            time.sleep(0.05)
        assert svc.store.all()[0].status == DONE
    finally:
        svc.shutdown()


# --- email -----------------------------------------------------------------

def test_memo_email_keeps_body_and_attachments(tmp_path, config, monkeypatch):
    memo = tmp_path / "m_memo.md"
    memo.write_text("# Protokoll")
    big = tmp_path / "big.wav"
    big.write_bytes(b"0" * 100)
    monkeypatch.setattr("voxtral_notetaker.notify.MAX_ATTACHMENT_BYTES", 50)
    config.email.to_emails = ["a@example.com", "b@example.com"]
    config.email.from_email = "device@example.com"
    msg = build_memo_email(config.email, "Protokoll: X", "Body text", [str(memo), str(big)])
    parsed = message_from_bytes(msg.as_bytes())
    assert parsed['To'] == "a@example.com, b@example.com"
    body = msg.get_body().get_content()
    assert "Body text" in body and "big.wav" in body  # too large -> mentioned, not attached
    assert [p.get_filename() for p in msg.iter_attachments()] == ["m_memo.md"]


def test_memo_subject_language():
    assert memo_subject("X", "de-CH") == "Protokoll: X"
    assert memo_subject("X", "en") == "Meeting notes: X"


# --- speakers ----------------------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ("Hallo zusammen, ich bin Anna und leite das Projekt.", "Anna"),
    ("Mein Name ist Marco.", "Marco"),
    ("I bi d'Sabine vom Marketing.", "Sabine"),
    ("Hi, I'm Tom from sales.", "Tom"),
    ("Ich bin Anna-Lena.", "Anna-Lena"),
    ("Ich bin Projektleiter hier.", None),
    ("Ich bin froh, dass alle da sind.", None),
    ("Ich bin Mitte Oktober weg.", None),
    ("Wir haben das Budget, ich bin Marketing.", None),
])
def test_find_introduced_name(text, name):
    assert find_introduced_name(text) == name


def test_detect_speaker_names_unique_and_respects_known():
    names = detect_speaker_names([
        ("s0", "Hallo, ich bin Anna."),
        ("s1", "Und ich bin Anna auch."),   # name already taken
        ("s1", "Mein Name ist Marco."),
        ("s2", "Ich bin Lisa."),
    ], known={"s2": "Elisabeth"})
    assert names == {"s0": "Anna", "s1": "Marco"}


def test_process_recording_names_speakers(tmp_path, monkeypatch):
    from voxtral_notetaker import Notetaker
    from voxtral_notetaker.transcription import TranscriptionResult, TranscriptSegment

    config = NotetakerConfig()
    config.storage.auto_upload = False
    nt = Notetaker(config)
    audio = tmp_path / "m.wav"
    write_wav(audio)
    monkeypatch.setattr(nt, "transcribe", lambda f, lang, diarize=False, fast=False:
                        TranscriptionResult(text="", language="de", confidence=None, duration=1,
                                            segments=[
                                                TranscriptSegment(0, 1, "Grüezi, ich bin Anna.", "speaker_0"),
                                                TranscriptSegment(1, 2, "Mein Name ist Marco.", "speaker_1"),
                                                TranscriptSegment(2, 3, "Notiz: Budget fix.", "speaker_0"),
                                            ]))
    result = nt.process_recording(str(audio), start_time=datetime(2026, 10, 26, 9))
    assert result.speakers == ["Anna", "Marco"]
    assert result.transcript.splitlines()[0] == "[Anna] Grüezi, ich bin Anna."
    assert "**Teilnehmende:** Anna, Marco" in result.memo.to_markdown()
    assert result.memo.notes[0]["speaker"] == "Anna"
    nt.close()


# --- device ------------------------------------------------------------------

def test_tones_are_audible_and_bounded():
    fb = Feedback.__new__(Feedback)
    fb.config = NotetakerConfig().device
    fb.sample_rate = 16000
    samples = fb.tone_samples('start')
    assert len(samples) == int(16000 * 0.12) + int(16000 * 0.18)
    assert 0 < np.abs(samples).max() <= 32767 * fb.config.beep_volume + 1


def test_controls_debounce():
    presses = []
    controls = Controls(NotetakerConfig().device, lambda: presses.append(1))
    controls._pressed('test')
    controls._pressed('test')  # bounce
    controls._last_press -= 2
    controls._pressed('test')
    assert len(presses) == 2


def test_config_new_sections_roundtrip(tmp_path):
    c = NotetakerConfig()
    c.email.to_emails = ["x@example.com"]
    c.device.button_gpio = 17
    c.web.pin = "1234"
    path = tmp_path / "c.yaml"
    c.save(str(path))
    loaded = NotetakerConfig.load(str(path))
    assert loaded.email.to_emails == ["x@example.com"]
    assert loaded.device.button_gpio == 17
    assert loaded.web.pin == "1234"


# --- web page ----------------------------------------------------------------

@pytest.fixture
def web(config, tmp_path):
    config.voxtral.api_key = ""
    svc = make_service(config, tmp_path)
    server = start_web_server(svc, host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield svc, base
    server.shutdown()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode()


def post(url, data):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(url, urllib.parse.urlencode(data).encode(), timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_home_shows_setup_banner_and_start_button(web):
    svc, base = web
    status, html = get(base + "/")
    assert status == 200
    assert "Setup needed" in html and "Start meeting" in html


def test_start_and_stop_from_phone(web):
    svc, base = web
    assert post(base + "/toggle", {"action": "start"})[0] == 303
    assert svc.is_recording
    assert "Stop meeting" in get(base + "/")[1]
    post(base + "/toggle", {"action": "stop"})
    assert not svc.is_recording


def test_first_visit_sets_pin_then_pin_required(web, tmp_path):
    svc, base = web
    status, html = post(base + "/settings", {"api_key": "sk-1", "new_pin": "12"})
    assert "at least 4 digits" in html and not svc.config.voxtral.api_key

    status, html = post(base + "/settings", {"api_key": "sk-1", "new_pin": "2468",
                                            "language": "de-CH", "max_minutes": "90"})
    assert "Saved." in html
    assert svc.config.voxtral.api_key == "sk-1"
    assert svc.config.service.language == "de-CH"
    assert svc.config.max_recording_minutes == 90
    saved = NotetakerConfig.load(str(tmp_path / "config.yaml"))
    assert saved.web.pin == "2468" and saved.voxtral.api_key == "sk-1"
    assert "sk-1" not in get(base + "/settings")[1]  # never shown again

    status, html = post(base + "/settings", {"pin": "0000", "api_key": "evil"})
    assert "Wrong PIN" in html and svc.config.voxtral.api_key == "sk-1"

    post(base + "/settings", {"pin": "2468", "email_enabled": "1",
                              "to_emails": "a@example.com\nb@example.com",
                              "smtp_host": "smtp.example.com", "smtp_port": "465"})
    assert svc.config.email.ready
    assert svc.config.email.to_emails == ["a@example.com", "b@example.com"]
    assert svc.config.voxtral.api_key == "sk-1"  # empty field keeps the key


def test_meeting_page_and_downloads(web):
    svc, base = web
    svc.config.voxtral.api_key = "key"
    svc.toggle()
    svc.toggle()
    svc.process_due()
    job = svc.store.all()[0]
    assert "Protokoll: Test" in get(f"{base}/meeting/{job.id}")[1]
    status, body = get(f"{base}/file/{job.id}/transcript")
    assert status == 200 and body == "[Anna] Hallo"
    with urllib.request.urlopen(f"{base}/file/{job.id}/audio", timeout=5) as r:
        assert r.headers["Content-Type"] == "audio/wav" and r.read(4) == b"RIFF"


@pytest.mark.parametrize("path", [
    "/file/../../etc/passwd/memo", "/file/nope/memo", "/file/x/../../config.yaml",
    "/meeting/../config", "/file/%2e%2e/audio",
])
def test_no_access_outside_meetings(web, path):
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(web[1] + path, timeout=5)
    assert e.value.code == 404


def test_error_text_is_escaped(web):
    svc, base = web
    store = svc.store
    path = store.new_recording_path()
    write_wav(path)
    job = store.create(path, status=FAILED)
    job.last_error = "<script>alert(1)</script>"
    store.save(job)
    html = get(base + "/")[1]
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_status_api(web):
    status = json.loads(get(web[1] + "/api/status")[1])
    assert status["recording"] is False and status["api_key_set"] is False


def test_concurrent_toggles_never_double_record(config, tmp_path):
    svc = make_service(config, tmp_path)
    threads = [threading.Thread(target=svc.start_meeting) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len([j for j in svc.store.all() if j.status == RECORDING]) == 1
    svc.stop_meeting()


def test_example_config_lists_exactly_the_real_settings():
    import yaml
    from pathlib import Path
    from dataclasses import fields
    from voxtral_notetaker.config import SECTIONS

    path = Path(__file__).parent.parent / "config.example.yaml"
    data = yaml.safe_load(path.read_text())
    assert set(data) == set(SECTIONS) | {"max_recording_minutes"}
    for name, cls in SECTIONS.items():
        assert set(data[name]) == {f.name for f in fields(cls)}, name
    # And the documented values are the defaults
    assert NotetakerConfig.from_dict(data).to_dict() == NotetakerConfig().to_dict()


def test_noise_reduction_runs_in_background_once(config, tmp_path, monkeypatch):
    seen_configs = []

    class Recorder(FakeNotetaker):
        def __init__(self, cfg):
            super().__init__(cfg)
            seen_configs.append(cfg.audio.noise_reduction)

    calls = []
    monkeypatch.setattr("voxtral_notetaker.audio.reduce_noise_file", lambda p: calls.append(p))
    config.audio.noise_reduction = True
    svc = make_service(config, tmp_path)
    svc.notetaker_factory = Recorder
    svc.toggle()
    svc.toggle()
    assert seen_configs[0] is False      # stopping does not wait for noise reduction
    assert config.audio.noise_reduction  # the real setting is untouched
    FakeNotetaker.fail_with = httpx.ConnectError("offline")
    svc.process_due()
    FakeNotetaker.fail_with = None
    svc.retry()
    svc.process_due()
    assert len(calls) == 1               # not repeated on retry
    assert svc.store.all()[0].status == DONE


def test_error_messages_in_german(config):
    from voxtral_notetaker.i18n import TEXTS
    config.service.ui_language = "de"
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path()
    write_wav(path)
    FakeNotetaker.fail_with = http_error(401)
    job = JobProcessor(config, store, FakeNotetaker).process(store.create(path, status=PENDING))
    assert job.last_error == "Mistral-API-Schlüssel abgelehnt (401). Bitte in den Einstellungen prüfen."
    assert describe_error(httpx.ConnectError("x"), "de").startswith("Keine Verbindung")
    # Every text exists in both languages
    assert set(TEXTS["de"]) == set(TEXTS["en"])
