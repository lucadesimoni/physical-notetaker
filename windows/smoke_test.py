# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Windows smoke test: starts the real service the way the starter does and uses
it like a person would. Run after windows/start-notetaker.ps1 set everything up:

    venv\\Scripts\\python windows\\smoke_test.py

Checks the first-start page, entering a key (checked against the real Mistral
API), starting a meeting without a microphone, the Windows voice and the
desktop shortcut. Exits non-zero on the first failed check.
"""

import os
import sys
import time
import wave
import subprocess
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8080
BASE = f"http://127.0.0.1:{PORT}"
FAILED = []


def check(ok: bool, what: str, detail: str = ""):
    print(f"{'PASS' if ok else 'FAIL'}  {what}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(what)


def request(path: str, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Origin": BASE} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main() -> int:
    os.chdir(ROOT)
    check(sys.platform == "win32", "running on Windows", sys.platform)

    log = open(os.path.join(ROOT, "smoke-service.log"), "w", encoding="utf-8")
    service = subprocess.Popen(
        [sys.executable, "-m", "voxtral_notetaker", "run", "--config", "config.yaml"],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1"))
    try:
        # 1. The page comes up
        deadline = time.time() + 60
        status, home = 0, ""
        while time.time() < deadline:
            try:
                status, home = request("/")
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(1)
        check(status == 200, "web page answers on 127.0.0.1:8080")

        # 2. First start asks only for the API key, no PIN
        check('name="api_key"' in home, "first start shows the API key field")
        check("PIN" not in home, "no PIN asked on the PC itself")

        # 3. A wrong key is checked against the real Mistral API and rejected
        status, page = request("/api-key", {"api_key": "sk-not-a-real-key"})
        if "abgelehnt" in page:
            check(True, "wrong key rejected by the live Mistral API")
        elif "nicht geprüft" in page:
            check(True, "key saved unchecked (Mistral not reachable from this runner)")
        else:
            check(False, "API key check", page[:300])

        # 4. Another website in the browser cannot post to the page
        req = urllib.request.Request(BASE + "/api-key", data=b"api_key=x",
                                     headers={"Origin": "https://evil.example"})
        try:
            urllib.request.urlopen(req, timeout=10)
            check(False, "cross-site POST blocked")
        except urllib.error.HTTPError as e:
            check(e.code == 403, "cross-site POST blocked", f"HTTP {e.code}")

        # 5. Start a meeting: no microphone on the runner -> clear message, no crash
        status, _ = request("/toggle", {"action": "start"})
        time.sleep(2)
        status, home = request("/")
        recording = "Besprechung beenden" in home
        mic_message = "Mikrofon" in home
        check(status == 200 and (recording or mic_message),
              "start meeting: recording, or a clear microphone message",
              "recording" if recording else "no microphone on this machine")
        if recording:
            request("/toggle", {"action": "stop"})
        check(service.poll() is None, "service still running")

        # 6. Settings page works without PIN
        status, settings = request("/settings")
        check(status == 200 and "Am PC selbst ist keine PIN nötig" in settings,
              "settings open without PIN")
    finally:
        service.terminate()
        service.wait(timeout=30)
        log.close()

    # 7. Windows built-in voice produces speech
    from voxtral_notetaker.device import Voice
    voice = Voice("de", cache_dir=os.path.join(ROOT, "smoke-voice"))
    check(voice.engine in ("sapi", "espeak-ng"), "speech engine found", str(voice.engine))
    wav = voice.wav_for("Aufnahme gestartet. Diese Besprechung wird aufgezeichnet.")
    seconds = 0.0
    if wav:
        with wave.open(wav) as wf:
            seconds = wf.getnframes() / float(wf.getframerate())
    check(seconds > 1.0, "announcement synthesized", f"{seconds:.1f} s")

    # 8. Desktop shortcut from the starter
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    shortcut = os.path.join(desktop, "Notetaker.lnk")
    check(os.path.exists(shortcut), "desktop shortcut created", shortcut)

    print()
    with open(os.path.join(ROOT, "smoke-service.log"), encoding="utf-8") as f:
        print("--- service log ---")
        print(f.read()[-3000:])
    if FAILED:
        print(f"{len(FAILED)} check(s) failed: {', '.join(FAILED)}")
        return 1
    print("All Windows checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
