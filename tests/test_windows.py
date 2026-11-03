# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Tests for running on Windows: locked files, built-in voice, console start/stop
"""

import io
import os
import sys
import shutil
import subprocess

import pytest

from voxtral_notetaker import fsutil
from voxtral_notetaker import device
from voxtral_notetaker.device import Voice

from test_service import FakeNotetaker, make_service, NotetakerConfig


def test_atomic_replace_retries_while_locked(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a"
    src.write_text("new")
    dst.write_text("old")
    real_replace = os.replace
    attempts = []

    def flaky(a, b):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("[WinError 5] Access is denied")  # reader has the file open
        real_replace(a, b)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(fsutil, "REPLACE_WAIT_SECONDS", 0)
    fsutil.atomic_replace(str(src), str(dst))
    assert dst.read_text() == "new" and len(attempts) == 3


def test_atomic_replace_gives_up_eventually(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(fsutil, "REPLACE_WAIT_SECONDS", 0)
    with pytest.raises(PermissionError):
        fsutil.atomic_replace("x", "y")


def test_windows_uses_builtin_voice_safely(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which",
                        lambda name: r"C:\Windows\powershell.exe" if name == "powershell" else None)
    monkeypatch.setattr(os.path, "exists",
                        lambda p, _exists=os.path.exists: False if "eSpeak" in p else _exists(p))
    voice = Voice("de", cache_dir=str(tmp_path))
    assert voice.engine == "sapi"

    calls = []

    def fake_run(cmd, env=None, **kwargs):
        calls.append((cmd, env))
        with open(env["NOTETAKER_TTS_OUT"], "wb") as f:
            f.write(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    text = 'Notiz notiert"; Remove-Item C:\\ -Recurse; "'
    assert voice.wav_for(text)
    cmd, env = calls[0]
    # The text travels in an environment variable, never inside the command
    assert env["NOTETAKER_TTS_TEXT"] == text and env["NOTETAKER_TTS_LANG"] == "de"
    assert all(text not in part for part in cmd)
    assert cmd[0] == "powershell" and "-NonInteractive" in cmd
    # Cached: no second synthesis
    voice.wav_for(text)
    assert len(calls) == 1


def test_windows_prefers_installed_espeak(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    path = device.WINDOWS_ESPEAK_PATHS[0]
    monkeypatch.setattr(os.path, "exists", lambda p: p == path)
    assert device.find_espeak() == path


def test_enter_starts_and_stops(tmp_path):
    config = NotetakerConfig()
    config.voxtral.api_key = "key"
    config.service.recordings_dir = str(tmp_path / "rec")
    svc = make_service(config, tmp_path)
    svc._read_console(io.StringIO("\n"))
    assert svc.is_recording  # Enter started it; closed input does not stop it
    svc._read_console(io.StringIO("\n"))
    assert not svc.is_recording  # the next Enter stops it
    # Two lines: start, then stop
    svc2 = make_service(config, tmp_path / "b")
    states = []
    svc2.toggle = lambda: (states.append("toggle"))
    svc2._read_console(io.StringIO("\n\n"))
    assert states == ["toggle", "toggle"]


def test_started_event_names_the_microphone(tmp_path):
    class WithMic(FakeNotetaker):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.audio = type("A", (), {"device_name": "Jabra SPEAK 510 USB"})()

    config = NotetakerConfig()
    config.service.recordings_dir = str(tmp_path / "rec")
    config.service.ui_language = "de"
    svc = make_service(config, tmp_path)
    svc.notetaker_factory = WithMic
    svc.start_meeting()
    assert svc.last_event == "Aufnahme gestartet (Mikrofon: Jabra SPEAK 510 USB)"
    svc.stop_meeting()


def _silent_service(tmp_path, monkeypatch, platform):
    from voxtral_notetaker.audio import RecordingInfo

    class SilentMic(FakeNotetaker):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.audio = type("A", (), {"is_silent": True, "device_name": "Mikrofon"})()

        def stop_recording(self):
            return RecordingInfo(file_path=self.path, duration=20, sample_rate=16000, peak=0)

    monkeypatch.setattr(sys, "platform", platform)
    config = NotetakerConfig()
    config.service.recordings_dir = str(tmp_path / "rec")
    config.service.ui_language = "de"
    svc = make_service(config, tmp_path)
    svc.notetaker_factory = SilentMic
    return svc


def test_silent_microphone_warned_early_with_windows_hint(tmp_path, monkeypatch):
    import time
    svc = _silent_service(tmp_path, monkeypatch, "win32")
    svc.start_meeting()
    svc._recording_since = time.time() - 16
    svc.tick()
    assert "Desktop-Apps den Zugriff" in svc.last_event
    assert svc.feedback.events.count("error") == 1
    svc.tick()  # warned only once
    assert svc.feedback.events.count("error") == 1
    svc.stop_meeting()


def test_silent_recording_reported_at_stop(tmp_path, monkeypatch):
    svc = _silent_service(tmp_path, monkeypatch, "linux")
    svc.start_meeting()
    job = svc.stop_meeting()
    assert "angeschlossen" in svc.last_event or "Ton" in svc.last_event
    assert "error" in svc.feedback.events
    assert job.status == "pending"  # still processed: it may really have been quiet


def test_peak_tracks_real_sound(tmp_path):
    import numpy as np
    from voxtral_notetaker.audio import AudioRecorder
    from voxtral_notetaker.config import AudioConfig
    rec = AudioRecorder(AudioConfig(noise_reduction=False))
    rec._open_file(str(tmp_path / "x.wav"))
    rec._output_file = str(tmp_path / "x.wav")
    rec._is_recording = True
    rec._write(np.zeros(1600, dtype=np.int16).tobytes(), 1600)
    assert rec.is_silent
    rec._write((np.ones(1600) * 5000).astype(np.int16).tobytes(), 1600)
    assert not rec.is_silent
    assert rec.stop_recording().peak == 5000
    rec.close()


# --- only the API key to enter ---------------------------------------------------

import urllib.error
import urllib.parse
import urllib.request

from voxtral_notetaker.web import start_web_server


@pytest.fixture
def local_web(tmp_path, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    config = NotetakerConfig()
    config.service.recordings_dir = str(tmp_path / "rec")
    config.service.ui_language = "de"
    svc = make_service(config, tmp_path)
    server = start_web_server(svc, host="127.0.0.1", port=0)
    port = server.server_address[1]
    yield svc, port
    server.shutdown()


def _request(port, path, data=None, host=None, origin=None):
    headers = {}
    if host:
        headers["Host"] = host
    if origin:
        headers["Origin"] = origin
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_first_start_asks_only_for_the_key(local_web, monkeypatch):
    svc, port = local_web
    status, html = _request(port, "/", host=f"localhost:{port}")
    assert "Nur noch ein Schritt" in html and 'name="api_key"' in html
    assert "PIN" not in html

    monkeypatch.setattr("voxtral_notetaker.transcription.check_api_key", lambda cfg: "ok")
    status, html = _request(port, "/api-key", {"api_key": " sk-good "}, host=f"localhost:{port}",
                            origin=f"http://localhost:{port}")
    assert "Schlüssel funktioniert" in html and "Besprechung starten" in html
    assert svc.config.voxtral.api_key == "sk-good"
    assert NotetakerConfig.load(svc.config_path).voxtral.api_key == "sk-good"  # saved


def test_rejected_key_is_not_saved(local_web, monkeypatch):
    svc, port = local_web
    monkeypatch.setattr("voxtral_notetaker.transcription.check_api_key", lambda cfg: "invalid")
    status, html = _request(port, "/api-key", {"api_key": "sk-typo"}, host=f"localhost:{port}")
    assert "abgelehnt" in html and svc.config.voxtral.api_key == ""


def test_key_saved_when_offline(local_web, monkeypatch):
    svc, port = local_web
    monkeypatch.setattr("voxtral_notetaker.transcription.check_api_key", lambda cfg: "offline")
    status, html = _request(port, "/api-key", {"api_key": "sk-x"}, host=f"localhost:{port}")
    assert "nicht geprüft" in html and svc.config.voxtral.api_key == "sk-x"


def test_settings_on_the_pc_need_no_pin(local_web):
    svc, port = local_web
    status, html = _request(port, "/settings", host=f"localhost:{port}")
    assert "Am PC selbst ist keine PIN nötig" in html
    _request(port, "/settings", {"language": "de-CH", "max_minutes": "60"}, host=f"localhost:{port}")
    assert svc.config.service.language == "de-CH" and svc.config.max_recording_minutes == 60


def test_other_websites_cannot_post(local_web):
    svc, port = local_web
    status, _ = _request(port, "/api-key", {"api_key": "sk-evil"}, host=f"localhost:{port}",
                         origin="https://evil.example")
    assert status == 403 and svc.config.voxtral.api_key == ""
    status, _ = _request(port, "/toggle", {"action": "start"}, host=f"localhost:{port}",
                         origin="null")
    assert status == 403 and not svc.is_recording


def test_dns_rebinding_gets_no_pin_free_access(local_web):
    svc, port = local_web
    # A website whose name resolves to 127.0.0.1: same "origin" as itself, but not localhost
    host = f"evil.example:{port}"
    status, html = _request(port, "/", host=host)
    assert 'name="api_key"' not in html  # no inline key form
    status, html = _request(port, "/settings", {"api_key": "sk-evil", "new_pin": "1"},
                            host=host, origin=f"http://{host}")
    assert svc.config.voxtral.api_key == ""


def test_check_api_key(monkeypatch):
    import httpx
    from voxtral_notetaker.config import VoxtralConfig
    from voxtral_notetaker.transcription import check_api_key
    replies = {"good": 200, "bad": 401}

    def fake_get(url, headers, timeout):
        assert url == "https://api.mistral.ai/v1/models"
        code = replies[headers["Authorization"].split()[-1]]
        return httpx.Response(code, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    assert check_api_key(VoxtralConfig(api_key="good")) == "ok"
    assert check_api_key(VoxtralConfig(api_key="bad")) == "invalid"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("x")))
    assert check_api_key(VoxtralConfig(api_key="good")) == "offline"
