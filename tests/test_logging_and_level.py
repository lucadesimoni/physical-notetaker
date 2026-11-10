# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Tests for logging (file, console, secrets) and the microphone level handling
"""

import io
import os
import time
import wave
import logging

import numpy as np
import pytest

from voxtral_notetaker import NotetakerConfig
from voxtral_notetaker import logsetup
from voxtral_notetaker.audio import (AudioRecorder, QUIET_PEAK, dbfs, measure_level,
                                     normalize_file)
from voxtral_notetaker.config import AudioConfig

from test_service import FakeNotetaker, make_service, write_wav


@pytest.fixture
def logged(tmp_path):
    config = NotetakerConfig()
    config.voxtral.api_key = "sk-secret-key-123"
    config.email.smtp_password = "mail-pass-456"
    config.web.pin = "2468"
    path = logsetup.setup_logging(config, log_dir=str(tmp_path / "logs"), console=False)
    yield config, path
    for handler in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(handler)
        handler.close()


def _read(path):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return open(path, encoding="utf-8").read()


def test_log_file_with_details_and_no_secrets(logged):
    config, path = logged
    logsetup.log_startup(config, "config.yaml", "9.9.9")
    logging.getLogger("voxtral_notetaker.x").info("calling with sk-secret-key-123 and pin 2468")
    logging.getLogger("voxtral_notetaker.x").warning("smtp login mail-pass-456 failed")
    text = _read(path)
    assert "Notetaker 9.9.9 starting" in text and "Mistral API key: set" in text
    assert "sk-secret-key-123" not in text and "mail-pass-456" not in text and "2468" not in text
    assert text.count("***") >= 3
    assert "[MainThread]" in text  # thread names help with background work


def test_crash_in_thread_is_logged_with_traceback(logged):
    import threading
    _, path = logged

    def boom():
        raise ValueError("thread exploded")

    thread = threading.Thread(target=boom, name="worker-test")
    thread.start()
    thread.join()
    text = _read(path)
    assert "Unhandled error in thread worker-test" in text
    assert "Traceback" in text and "ValueError: thread exploded" in text


def test_console_shows_status_and_problems_only():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(logsetup.ConsoleFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        logsetup.status("Aufnahme gestartet")
        logging.getLogger("voxtral_notetaker.jobs").info("stage details")
        logging.getLogger("voxtral_notetaker.jobs").warning("retry later")
        logging.getLogger("httpx").info("HTTP Request: GET ...")
        logging.getLogger("httpx").error("connection broke")
    finally:
        root.removeHandler(handler)
    out = stream.getvalue()
    assert "Aufnahme gestartet" in out and "retry later" in out and "connection broke" in out
    assert "stage details" not in out and "HTTP Request" not in out


def test_live_command_content_not_in_log(tmp_path, logged):
    config, path = logged
    config.service.recordings_dir = str(tmp_path / "rec")
    svc = make_service(config, tmp_path)
    svc._live_item("note", "Budget ist streng vertraulich")
    assert "Budget ist streng vertraulich" in svc.last_event  # shown on the web page
    assert "streng vertraulich" not in _read(path)


# --- microphone level ---------------------------------------------------------

def _speech(path, peak, seconds=2.0, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    signal = np.sin(2 * np.pi * 220 * t) * np.sin(2 * np.pi * 3 * t) * peak
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(signal.astype(np.int16).tobytes())


def test_quiet_recording_is_raised(tmp_path):
    path = tmp_path / "quiet.wav"
    _speech(path, 514)  # the level of a real recording that was recognised badly
    gain = normalize_file(str(path))
    assert gain == pytest.approx(30.0)  # capped
    peak, loud, rms = measure_level(str(path))
    assert dbfs(loud) > -10 and peak <= 32767


def test_normal_recording_is_left_alone(tmp_path):
    path = tmp_path / "ok.wav"
    _speech(path, 20000)
    before = path.read_bytes()
    assert normalize_file(str(path)) == 0.0
    assert path.read_bytes() == before


def test_silent_recording_is_not_amplified(tmp_path):
    path = tmp_path / "silent.wav"
    write_wav(path, 1.0)
    assert normalize_file(str(path)) == 0.0


def test_recorder_tracks_quiet_level(tmp_path):
    rec = AudioRecorder(AudioConfig())
    rec._open_file(str(tmp_path / "x.wav"))
    rec._output_file = str(tmp_path / "x.wav")
    rec._is_recording = True
    rec._write((np.ones(1600) * 900).astype(np.int16).tobytes(), 1600)
    assert rec.is_quiet and not rec.is_silent
    rec._write((np.ones(1600) * (QUIET_PEAK + 5000)).astype(np.int16).tobytes(), 1600)
    assert not rec.is_quiet
    rec.close()


def test_quiet_microphone_warned_after_30_seconds(tmp_path):
    class QuietMic(FakeNotetaker):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.audio = type("A", (), {"is_silent": False, "is_quiet": True, "device_name": "Mic"})()

    config = NotetakerConfig()
    config.service.recordings_dir = str(tmp_path / "rec")
    svc = make_service(config, tmp_path)
    svc.notetaker_factory = QuietMic
    svc.start_meeting()
    svc._recording_since = time.time() - 31
    svc.tick()
    assert "sehr leise" in svc.last_event and "warning" in svc.feedback.events
    svc.stop_meeting()


def test_level_checked_once_before_transcription(tmp_path, monkeypatch):
    from voxtral_notetaker.jobs import JobProcessor, JobStore, PENDING, DONE
    calls = []
    monkeypatch.setattr("voxtral_notetaker.audio.normalize_file", lambda p: calls.append(p) or 12.0)
    config = NotetakerConfig()
    config.voxtral.api_key = "k"
    config.service.recordings_dir = str(tmp_path / "rec")
    config.storage.auto_upload = False
    store = JobStore(config.service.recordings_dir)
    path = store.new_recording_path()
    write_wav(path)
    job = JobProcessor(config, store, FakeNotetaker).process(store.create(path, status=PENDING))
    assert job.status == DONE and job.level_checked and calls == [path]


def test_retranscribe_drops_cached_transcription(tmp_path):
    from voxtral_notetaker.core import transcription_cache_path
    from voxtral_notetaker.jobs import DONE
    config = NotetakerConfig()
    config.service.recordings_dir = str(tmp_path / "rec")
    svc = make_service(config, tmp_path)
    path = svc.store.new_recording_path()
    write_wav(path)
    job = svc.store.create(path, status=DONE)
    cache = transcription_cache_path(path)
    open(cache, "w").write("{}")
    assert svc.retranscribe(job.id)
    assert not os.path.exists(cache) and svc.store.get(job.id).status == "pending"
