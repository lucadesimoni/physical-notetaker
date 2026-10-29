# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Physical feedback and controls: beeps, status LED, start/stop buttons.

Everything here is optional. Missing hardware or libraries (gpiozero, evdev,
PyAudio) only disable that piece; recording keeps working.
"""

import os
import sys
import time
import wave
import shutil
import select
import hashlib
import logging
import threading
import subprocess
from typing import Callable, List, Optional

import numpy as np

from .config import DeviceConfig, AudioConfig
from .i18n import t, normalize
from .fsutil import atomic_replace

log = logging.getLogger(__name__)

# (frequency Hz, duration s) sequences
TONES = {
    'ready': [(880, 0.08)],
    'start': [(660, 0.12), (880, 0.18)],          # rising: recording
    'stop': [(880, 0.12), (660, 0.18)],           # falling: stopped and saved
    'error': [(300, 0.2), (0, 0.08), (300, 0.2), (0, 0.08), (300, 0.3)],
    'warning': [(660, 0.1), (0, 0.1), (660, 0.1)],  # e.g. recording time almost up
}


# Windows' built-in voices (System.Speech, as used by Narrator). The text comes in
# through environment variables, so it is never parsed as PowerShell code.
SAPI_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object {
    $_.Enabled -and $_.VoiceInfo.Culture.Name -like ($env:NOTETAKER_TTS_LANG + '*') } |
    Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($env:NOTETAKER_TTS_OUT, $fmt)
$s.Speak($env:NOTETAKER_TTS_TEXT)
$s.Dispose()
"""

WINDOWS_ESPEAK_PATHS = [
    r"C:\Program Files\eSpeak NG\espeak-ng.exe",
    r"C:\Program Files (x86)\eSpeak NG\espeak-ng.exe",
]


def find_espeak() -> Optional[str]:
    found = shutil.which('espeak-ng')
    if found:
        return found
    if sys.platform == 'win32':
        return next((p for p in WINDOWS_ESPEAK_PATHS if os.path.exists(p)), None)
    return None


class Voice:
    """
    Spoken announcements: Piper (natural voice, optional), espeak-ng, or on
    Windows the built-in system voice (no install needed).

    Each phrase is synthesized once and cached as a WAV file.
    """

    def __init__(self, lang: str = 'de', piper_model: str = '', cache_dir: Optional[str] = None):
        self.lang = normalize(lang)
        self.piper_model = piper_model
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser('~'), '.cache', 'notetaker')
        self.espeak = find_espeak()
        if piper_model and shutil.which('piper') and os.path.exists(piper_model):
            self.engine = 'piper'
        elif self.espeak:
            self.engine = 'espeak-ng'
        elif sys.platform == 'win32' and shutil.which('powershell'):
            self.engine = 'sapi'
        else:
            self.engine = None

    @property
    def available(self) -> bool:
        return self.engine is not None

    def wav_for(self, text: str) -> Optional[str]:
        """Path of a WAV file speaking `text`, or None"""
        if not self.engine or not text:
            return None
        key = hashlib.sha1(f"{self.engine}|{self.piper_model}|{self.lang}|{text}".encode()).hexdigest()
        path = os.path.join(self.cache_dir, f"{key}.wav")
        if os.path.exists(path):
            return path
        os.makedirs(self.cache_dir, exist_ok=True)
        tmp = f"{path}.tmp.wav"
        try:
            if self.engine == 'piper':
                subprocess.run(['piper', '--model', self.piper_model, '--output_file', tmp],
                               input=text, text=True, capture_output=True, timeout=30, check=True)
            elif self.engine == 'sapi':
                env = dict(os.environ, NOTETAKER_TTS_TEXT=text, NOTETAKER_TTS_OUT=tmp,
                           NOTETAKER_TTS_LANG=self.lang)
                subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                SAPI_SCRIPT], env=env, capture_output=True, timeout=60,
                               check=True)
            else:
                subprocess.run([self.espeak, '-v', self.lang, '-s', '150', '-w', tmp, text],
                               capture_output=True, timeout=30, check=True)
            atomic_replace(tmp, path)
            return path
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Speech synthesis failed: %s", e)
            if os.path.exists(tmp):
                os.remove(tmp)
            return None


class Feedback:
    """Tells people in the room what the device is doing: tones, speech, LED"""

    def __init__(self, config: DeviceConfig, audio: Optional[AudioConfig] = None,
                 lang: str = 'de', cache_dir: Optional[str] = None):
        self.config = config
        self.lang = normalize(lang)
        self.sample_rate = 16000
        self._led = None
        self._pyaudio = None
        self._output_index = None
        self._lock = threading.Lock()
        self.voice = Voice(lang, config.piper_model, cache_dir) if config.voice else None
        if self.voice and not self.voice.available:
            log.info("No speech engine (install espeak-ng): using tones only")
            self.voice = None

        if config.led_gpio is not None:
            try:
                from gpiozero import LED
                self._led = LED(config.led_gpio)
            except Exception as e:
                log.warning("Status LED disabled: %s", e)

        if config.beeps or self.voice:
            try:
                import pyaudio
                self._pyaudio = pyaudio.PyAudio()
                self._output_index = self._find_output()
            except Exception as e:
                log.warning("Sound output disabled: %s", e)
                self._pyaudio = None

    def _find_output(self) -> Optional[int]:
        # Prefer the speakerphone, so the sound comes from the table
        for i in range(self._pyaudio.get_device_count()):
            dev = self._pyaudio.get_device_info_by_index(i)
            name = dev.get('name', '').lower()
            if dev.get('maxOutputChannels', 0) > 0 and ('jabra' in name or 'spider' in name):
                return i
        return None

    # --- sound -------------------------------------------------------------

    def tone_samples(self, name: str) -> np.ndarray:
        parts = []
        for freq, duration in TONES[name]:
            t_ = np.arange(int(self.sample_rate * duration)) / self.sample_rate
            wave_ = np.sin(2 * np.pi * freq * t_) if freq else np.zeros_like(t_)
            # Short fade in/out so the tone does not click
            fade = min(len(t_) // 5, int(self.sample_rate * 0.01))
            if fade:
                envelope = np.ones_like(t_)
                envelope[:fade] = np.linspace(0, 1, fade)
                envelope[-fade:] = np.linspace(1, 0, fade)
                wave_ = wave_ * envelope
            parts.append(wave_)
        samples = np.concatenate(parts) if parts else np.zeros(0)
        return (samples * self.config.beep_volume * 32767).astype(np.int16)

    def announce(self, tone: Optional[str] = None, key: Optional[str] = None, **kwargs):
        """Play a tone, then speak a message (in the background, one at a time)"""
        text = t(key, self.lang, **kwargs) if key else None
        if not self._pyaudio:
            if text:
                log.info("Announcement: %s", text)
            return
        threading.Thread(target=self._play_sequence, args=(tone, text), daemon=True).start()

    def beep(self, name: str):
        self.announce(tone=name)

    def _play_sequence(self, tone: Optional[str], text: Optional[str]):
        with self._lock:
            if tone and self.config.beeps:
                self._play_samples(self.tone_samples(tone), self.sample_rate, 1)
            wav = self.voice.wav_for(text) if (self.voice and text) else None
            if wav:
                self._play_wav(wav)

    def _play_samples(self, samples: np.ndarray, rate: int, channels: int):
        import pyaudio
        try:
            stream = self._pyaudio.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                                        output=True, output_device_index=self._output_index)
            stream.write(samples.astype(np.int16).tobytes())
            stream.stop_stream()
            stream.close()
        except Exception as e:
            log.warning("Sound output failed: %s", e)

    def _play_wav(self, path: str):
        try:
            with wave.open(path, 'rb') as wf:
                if wf.getsampwidth() != 2:
                    return
                data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                self._play_samples(data, wf.getframerate(), wf.getnchannels())
        except (OSError, wave.Error) as e:
            log.warning("Playing announcement failed: %s", e)

    # --- LED ---------------------------------------------------------------

    def _led_set(self, mode: str):
        if not self._led:
            return
        try:
            if mode == 'on':
                self._led.on()
            elif mode == 'off':
                self._led.off()
            elif mode == 'slow':
                self._led.blink(on_time=0.5, off_time=0.5)
            elif mode == 'fast':
                self._led.blink(on_time=0.1, off_time=0.1)
        except Exception as e:
            log.warning("LED failed: %s", e)

    # --- states ------------------------------------------------------------

    def ready(self):
        self._led_set('off')
        self.announce('ready', 'say_ready')

    def recording(self):
        self._led_set('on')
        # Also tells everyone in the room that the meeting is recorded
        self.announce('start', 'say_start')

    def stopped(self, email: bool = False):
        self._led_set('slow')  # blinking: processing the meeting
        self.announce('stop', 'say_stop_email' if email else 'say_stop')

    def idle(self):
        self._led_set('off')

    def warning(self):
        self.announce('warning', 'say_warning')

    def error(self, key: str = 'say_error'):
        self._led_set('fast')
        self.announce('error', key)

    def disk_low(self):
        self.announce('warning', 'say_disk_low')

    def confirm(self, kind: str):
        """A voice command was understood: note, task or research"""
        self.announce('ready', f'say_{kind}')

    def say_address(self, address: Optional[str]):
        if address:
            self.announce('ready', 'say_address', address=address)
        else:
            self.announce('error', 'say_no_address')

    def close(self):
        if self._led:
            try:
                self._led.close()
            except Exception:
                pass
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass


class Controls:
    """
    Start/stop buttons: a GPIO push button and/or keys of a USB device.

    A short press toggles the recording; holding the button for
    long_press_seconds calls on_long_press (the device says its address).
    """

    DEBOUNCE_SECONDS = 1.0

    def __init__(self, config: DeviceConfig, on_press: Callable[[], None],
                 on_long_press: Optional[Callable[[], None]] = None):
        self.config = config
        self.on_press = on_press
        self.on_long_press = on_long_press
        self._button = None
        self._held = False
        self._devices: List = []
        self._down_at: dict = {}
        self._stop = threading.Event()
        self._last_press = 0.0
        self._thread: Optional[threading.Thread] = None

    def _call(self, action: Optional[Callable[[], None]], what: str):
        if not action:
            return
        log.info("Button: %s", what)
        try:
            action()
        except Exception:
            log.exception("Button action failed")

    def _pressed(self, source: str = ''):
        now = time.time()
        if now - self._last_press < self.DEBOUNCE_SECONDS:
            return
        self._last_press = now
        self._call(self.on_press, f"press ({source})")

    def _long_pressed(self, source: str = ''):
        self._last_press = time.time()
        self._call(self.on_long_press, f"long press ({source})")

    def released(self, source: str, held_seconds: float):
        """A button went up after being held for held_seconds"""
        if self.on_long_press and held_seconds >= self.config.long_press_seconds:
            self._long_pressed(source)
        else:
            self._pressed(source)

    def start(self):
        if self.config.button_gpio is not None:
            try:
                from gpiozero import Button
                self._button = Button(self.config.button_gpio, bounce_time=0.05,
                                      hold_time=self.config.long_press_seconds)
                self._button.when_held = self._gpio_held
                self._button.when_released = self._gpio_released
                log.info("Start/stop button on GPIO %s", self.config.button_gpio)
            except Exception as e:
                log.warning("GPIO button disabled: %s", e)

        if self.config.input_device and self.config.input_keys:
            self._devices = self._open_input_devices()
            if self._devices:
                self._thread = threading.Thread(target=self._read_keys, daemon=True)
                self._thread.start()

    def _gpio_held(self):
        self._held = True
        self._long_pressed('gpio')

    def _gpio_released(self):
        if not self._held:
            self._pressed('gpio')
        self._held = False

    def _open_input_devices(self) -> List:
        try:
            import evdev
        except ImportError:
            log.info("evdev not installed: USB device buttons disabled")
            return []
        wanted = self.config.input_device.lower()
        devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            if wanted in dev.name.lower():
                log.info("Listening for buttons on %s (%s)", dev.name, path)
                devices.append(dev)
            else:
                dev.close()
        return devices

    def key_event(self, source: str, key: str, value: int, now: Optional[float] = None):
        """value 1 = down, 0 = up, 2 = auto-repeat (ignored)"""
        now = time.time() if now is None else now
        if key not in self.config.input_keys:
            return
        if value == 1:
            self._down_at[(source, key)] = now
        elif value == 0:
            down = self._down_at.pop((source, key), None)
            self.released(source, now - down if down is not None else 0.0)

    def _read_keys(self):
        import evdev
        while not self._stop.is_set() and self._devices:
            try:
                ready, _, _ = select.select(self._devices, [], [], 0.5)
            except (OSError, ValueError):
                break
            for dev in ready:
                try:
                    for event in dev.read():
                        if event.type != evdev.ecodes.EV_KEY:
                            continue
                        names = evdev.ecodes.KEY.get(event.code, [])
                        for name in (names if isinstance(names, list) else [names]):
                            self.key_event(dev.name, name, event.value)
                except OSError:
                    # Device unplugged
                    self._devices.remove(dev)

    def stop(self):
        self._stop.set()
        if self._button:
            try:
                self._button.close()
            except Exception:
                pass
        for dev in self._devices:
            try:
                dev.close()
            except Exception:
                pass
