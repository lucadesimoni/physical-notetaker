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
