"""
Physical feedback and controls: beeps, status LED, start/stop buttons.

Everything here is optional. Missing hardware or libraries (gpiozero, evdev,
PyAudio) only disable that piece; recording keeps working.
"""

import time
import select
import logging
import threading
from typing import Callable, List, Optional

import numpy as np

from .config import DeviceConfig, AudioConfig

log = logging.getLogger(__name__)

# (frequency Hz, duration s) sequences
TONES = {
    'ready': [(880, 0.08)],
    'start': [(660, 0.12), (880, 0.18)],          # rising: recording
    'stop': [(880, 0.12), (660, 0.18)],           # falling: stopped and saved
    'error': [(300, 0.2), (0, 0.08), (300, 0.2), (0, 0.08), (300, 0.3)],
    'warning': [(660, 0.1), (0, 0.1), (660, 0.1)],  # e.g. recording time almost up
}


class Feedback:
    """Tells people in the room what the device is doing"""

    def __init__(self, config: DeviceConfig, audio: Optional[AudioConfig] = None):
        self.config = config
        self.sample_rate = 16000
        self._led = None
        self._pyaudio = None
        self._output_index = None
        self._lock = threading.Lock()

        if config.led_gpio is not None:
            try:
                from gpiozero import LED
                self._led = LED(config.led_gpio)
            except Exception as e:
                log.warning("Status LED disabled: %s", e)

        if config.beeps:
            try:
                import pyaudio
                self._pyaudio = pyaudio.PyAudio()
                self._output_index = self._find_output()
            except Exception as e:
                log.warning("Beeps disabled: %s", e)
                self._pyaudio = None

    def _find_output(self) -> Optional[int]:
        # Prefer the speakerphone, so the beep comes from the table
        for i in range(self._pyaudio.get_device_count()):
            dev = self._pyaudio.get_device_info_by_index(i)
            name = dev.get('name', '').lower()
            if dev.get('maxOutputChannels', 0) > 0 and ('jabra' in name or 'spider' in name):
                return i
        return None

    # --- tones -------------------------------------------------------------

    def tone_samples(self, name: str) -> np.ndarray:
        parts = []
        for freq, duration in TONES[name]:
            t = np.arange(int(self.sample_rate * duration)) / self.sample_rate
            wave = np.sin(2 * np.pi * freq * t) if freq else np.zeros_like(t)
            # Short fade in/out so the tone does not click
            fade = min(len(t) // 5, int(self.sample_rate * 0.01))
            if fade:
                envelope = np.ones_like(t)
                envelope[:fade] = np.linspace(0, 1, fade)
                envelope[-fade:] = np.linspace(1, 0, fade)
                wave = wave * envelope
            parts.append(wave)
        samples = np.concatenate(parts) if parts else np.zeros(0)
        return (samples * self.config.beep_volume * 32767).astype(np.int16)

    def beep(self, name: str):
        """Play a tone in the background"""
        if not self._pyaudio:
            return
        threading.Thread(target=self._play, args=(name,), daemon=True).start()

    def _play(self, name: str):
        import pyaudio
        with self._lock:
            try:
                stream = self._pyaudio.open(format=pyaudio.paInt16, channels=1,
                                            rate=self.sample_rate, output=True,
                                            output_device_index=self._output_index)
                stream.write(self.tone_samples(name).tobytes())
                stream.stop_stream()
                stream.close()
            except Exception as e:
                log.warning("Beep failed: %s", e)

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
        self.beep('ready')

    def recording(self):
        self._led_set('on')
        self.beep('start')

    def stopped(self):
        self._led_set('slow')  # blinking: processing the meeting
        self.beep('stop')

    def idle(self):
        self._led_set('off')

    def warning(self):
        self.beep('warning')

    def error(self):
        self._led_set('fast')
        self.beep('error')

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
    """Start/stop buttons: a GPIO push button and/or keys of a USB device"""

    DEBOUNCE_SECONDS = 1.0

    def __init__(self, config: DeviceConfig, on_press: Callable[[], None]):
        self.config = config
        self.on_press = on_press
        self._button = None
        self._devices: List = []
        self._stop = threading.Event()
        self._last_press = 0.0
        self._thread: Optional[threading.Thread] = None

    def _pressed(self, source: str = ''):
        now = time.time()
        if now - self._last_press < self.DEBOUNCE_SECONDS:
            return
        self._last_press = now
        log.info("Button pressed (%s)", source)
        try:
            self.on_press()
        except Exception:
            log.exception("Button action failed")

    def start(self):
        if self.config.button_gpio is not None:
            try:
                from gpiozero import Button
                self._button = Button(self.config.button_gpio, bounce_time=0.05)
                self._button.when_pressed = lambda: self._pressed('gpio')
                log.info("Start/stop button on GPIO %s", self.config.button_gpio)
            except Exception as e:
                log.warning("GPIO button disabled: %s", e)

        if self.config.input_device and self.config.input_keys:
            self._devices = self._open_input_devices()
            if self._devices:
                self._thread = threading.Thread(target=self._read_keys, daemon=True)
                self._thread.start()

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

    def _read_keys(self):
        import evdev
        wanted = set(self.config.input_keys)
        while not self._stop.is_set() and self._devices:
            try:
                ready, _, _ = select.select(self._devices, [], [], 0.5)
            except (OSError, ValueError):
                break
            for dev in ready:
                try:
                    for event in dev.read():
                        if event.type != evdev.ecodes.EV_KEY or event.value != 1:
                            continue  # only key-down
                        names = evdev.ecodes.KEY.get(event.code, [])
                        names = names if isinstance(names, list) else [names]
                        if wanted.intersection(names):
                            self._pressed(dev.name)
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
