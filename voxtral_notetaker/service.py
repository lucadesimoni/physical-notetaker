# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
The always-on notetaker: one button to start and stop, everything else automatic.

- Recovers recordings interrupted by a crash or power cut at startup
- Start/stop from a GPIO button, the speakerphone button or the web page;
  hold the button to hear the device's address
- Announces the recording, confirms voice commands during the meeting
- Stops automatically at max_recording_minutes (warning 5 minutes before)
  or when storage runs out
- Processes recordings in the background and retries when offline
- Deletes old audio of finished meetings so the SD card never fills up
"""

import os
import sys
import time
import signal
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from .config import NotetakerConfig, find_config_path, load_config
from .jobs import (JobStore, JobProcessor, Job, PENDING, PROCESSING, RECORDING, FAILED,
                   summarize_jobs)
from .device import Feedback, Controls
from .disk import (cleanup, free_bytes, format_size, MB, HARD_MIN_FREE_BYTES,
                   STOP_RECORDING_FREE_BYTES)
from .i18n import t

log = logging.getLogger(__name__)

WARN_BEFORE_LIMIT_SECONDS = 5 * 60
DISK_CHECK_SECONDS = 30


class NotetakerService:

    def __init__(self, config: Optional[NotetakerConfig] = None,
                 config_path: Optional[str] = None,
                 notetaker_factory: Optional[Callable] = None,
                 feedback: Optional[Feedback] = None,
                 poll_seconds: float = 5.0):
        self.config_path = find_config_path(config_path)
        self.config = config or load_config(self.config_path)
        if notetaker_factory is None:
            from .core import Notetaker
            notetaker_factory = Notetaker
        self.notetaker_factory = notetaker_factory
        self.feedback = feedback or Feedback(self.config.device, self.config.audio,
                                             lang=self.lang)
        self.poll_seconds = poll_seconds

        self.store = JobStore(self.config.service.recordings_dir)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._recorder = None
        self._live = None
        self._current: Optional[Job] = None
        self._recording_since: Optional[float] = None
        self._warned = False
        self._last_disk_check = 0.0
        self._worker: Optional[threading.Thread] = None
        self._controls: Optional[Controls] = None
        self._web = None
        self.last_event: str = ""
        self.live_items = []  # (kind, text) heard during the current meeting

    @property
    def lang(self) -> str:
        return self.config.service.ui_language

    def _event(self, key: str, **kwargs):
        self.last_event = t(key, self.lang, **kwargs)
        log.info(self.last_event)

    # --- lifecycle ---------------------------------------------------------

    def start(self, web: bool = True, controls: bool = True):
        recovered = self.store.recover()
        if recovered:
            self._event('ev_recovered', n=len(recovered))

        self._worker = threading.Thread(target=self._work_loop, daemon=True, name="worker")
        self._worker.start()

        if controls:
            self._controls = Controls(self.config.device, self.toggle,
                                      on_long_press=self.announce_address)
            self._controls.start()

        if web and self.config.web.enabled:
            from .web import start_web_server
            self._web = start_web_server(self)
            if self.config.web.setup_hotspot:
                threading.Thread(target=self._hotspot_if_offline, daemon=True).start()

        self.feedback.ready()
        log.info("Notetaker ready")

    def run_forever(self, web: bool = True, console: bool = True):
        """Run until stopped (Ctrl+C or systemd stop)"""
        # systemd stops services with SIGTERM: shut down cleanly so the
        # current recording is saved and queued
        signal.signal(signal.SIGTERM, lambda *_: self._stop.set())
        self.start(web=web)
        if console and sys.stdin is not None and sys.stdin.isatty():
            # In a terminal (Windows test, SSH): Enter starts and stops
            print(t('console_hint', self.lang))
            threading.Thread(target=self._read_console, daemon=True, name="console").start()
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _read_console(self, stream=None):
        stream = stream or sys.stdin
        while not self._stop.is_set():
            line = stream.readline()
            if not line:  # input closed
                return
            self.toggle()

    def shutdown(self):
        self._stop.set()
        self._wake.set()
        if self.is_recording:
            self.stop_meeting()  # saves the recording; processing resumes after restart
        if self._controls:
            self._controls.stop()
        if self._web:
            self._web.shutdown()
        if self._worker:
            self._worker.join(timeout=5)
        self.feedback.close()

    def _hotspot_if_offline(self, wait_seconds: int = 60):
        """First boot without Wi-Fi: open a setup hotspot for the phone"""
        from .network import connectivity, start_hotspot
        self._stop.wait(wait_seconds)
        if self._stop.is_set() or connectivity() != 'none':
            return
        web = self.config.web
        if start_hotspot(web.hotspot_ssid, web.hotspot_password):
            suffix = '' if web.port == 80 else f':{web.port}'
            self._event('ev_hotspot', ssid=web.hotspot_ssid, url=f"http://10.42.0.1{suffix}")

    def announce_address(self):
        """Long press: say where the web page is"""
        from .network import local_ip, speakable_address
        ip = local_ip()
        port = self.config.web.port
        self.feedback.say_address(speakable_address(ip, port, self.lang) if ip else None)

    # --- recording ---------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._current is not None

    @property
    def recording_seconds(self) -> float:
        return time.time() - self._recording_since if self._recording_since else 0.0

    def toggle(self):
        with self._lock:
            if self.is_recording:
                self.stop_meeting()
            else:
                self.start_meeting()

    def start_meeting(self) -> bool:
        with self._lock:
            if self.is_recording:
                return False

            # Make room first; refuse only when the card is really full
            cleanup(self.store, self.config)
            free = free_bytes(self.store.directory)
            if free < HARD_MIN_FREE_BYTES:
                self.feedback.error('say_disk_low')
                self._event('ev_no_space')
                return False

            path = self.store.new_recording_path()
            # Noise reduction runs later in the background, so stopping is instant
            config = NotetakerConfig.from_dict(self.config.to_dict())
            config.audio.noise_reduction = False
            recorder = self.notetaker_factory(config)
            if not recorder.start_recording(path):
                recorder.close()
                self.feedback.error('say_no_mic')
                self._event('ev_no_mic')
                return False
            self._recorder = recorder
            self._current = self.store.create(path, status=RECORDING)
            self._recording_since = time.time()
            self._warned = False
            self.live_items = []
            self.feedback.recording()
            if free < self.config.service.min_free_mb * MB:
                self.feedback.disk_low()
            self._start_live(path)
            mic = getattr(getattr(recorder, 'audio', None), 'device_name', None)
            if mic:
                self._event('ev_started_mic', mic=mic)
            else:
                self._event('ev_started')
            return True

    def _start_live(self, path: str):
        if not self.config.service.live_commands or not self.config.voxtral.resolved_api_key():
            return
        from .live import LiveListener
        self._live = LiveListener(self.config, path, self.notetaker_factory,
                                  on_item=self._live_item, on_stop=self._voice_stop)
        self._live.start()

    def _live_item(self, kind: str, text: str):
        self.live_items.append((kind, text))
        self.feedback.confirm(kind)
        self._event('ev_live_item', item=text)

    def _voice_stop(self):
        # Called from the live thread: stop in another thread, which joins the live one
        def stop():
            if self.stop_meeting():
                self._event('ev_voice_stop')
        threading.Thread(target=stop, daemon=True).start()

    def stop_meeting(self) -> Optional[Job]:
        with self._lock:
            if not self.is_recording:
                return None
            job, recorder, live = self._current, self._recorder, self._live
            self._current = self._recorder = self._live = None
            self._recording_since = None
            if live:
                live.stop()
            try:
                info = recorder.stop_recording()
            finally:
                recorder.close()

            if not info:
                job.status = FAILED
                job.last_error = t('ev_no_audio', self.lang)
                self.store.save(job)
                self.feedback.error('say_no_mic')
                self.last_event = job.last_error
                return job

            job.duration = info.duration
            job.status = PENDING
            job.next_attempt_at = 0.0
            self.store.save(job)
            self.feedback.stopped(email=self.config.email.ready)
            self._event('ev_saved')
            self._wake.set()
            return job

    def tick(self):
        """Enforce the recording time limit and watch the free space"""
        if not self.is_recording:
            return
        limit = self.config.max_recording_minutes * 60
        elapsed = self.recording_seconds
        if not self._warned and limit > WARN_BEFORE_LIMIT_SECONDS \
                and elapsed >= limit - WARN_BEFORE_LIMIT_SECONDS:
            self._warned = True
            self.feedback.warning()
        if elapsed >= limit:
            self.stop_meeting()
            self._event('ev_time_limit')
            return

        now = time.time()
        if now - self._last_disk_check >= DISK_CHECK_SECONDS:
            self._last_disk_check = now
            if free_bytes(self.store.directory) < STOP_RECORDING_FREE_BYTES:
                cleanup(self.store, self.config)
                if free_bytes(self.store.directory) < STOP_RECORDING_FREE_BYTES:
                    self.stop_meeting()
                    self._event('ev_disk_full')

    # --- processing --------------------------------------------------------

    def _work_loop(self):
        while not self._stop.is_set():
            self.process_due()
            try:
                cleanup(self.store, self.config)
            except Exception:
                log.exception("Cleanup failed")
            self._wake.wait(self.poll_seconds)
            self._wake.clear()

    def process_due(self) -> int:
        """Process all jobs that are due; returns how many ran"""
        processor = JobProcessor(self.config, self.store, self.notetaker_factory)
        ran = 0
        for job in self.store.due():
            if self._stop.is_set():
                break
            log.info("Processing %s (attempt %d)", job.id, job.attempts + 1)
            job = processor.process(job)
            ran += 1
            if job.status == FAILED:
                if not self.is_recording:
                    self.feedback.error()
                self._event('ev_problem', name=job.title or job.id, error=job.last_error)
            elif job.status == PENDING:
                log.warning("%s will be retried: %s", job.id, job.last_error)
            else:
                if not self.is_recording:
                    self.feedback.idle()
                self._event('ev_memo_ready', title=job.title or job.id)
        return ran

    def retry(self, job_id: Optional[str] = None) -> int:
        count = self.store.retry(job_id)
        # Pending jobs waiting for their next attempt run now as well
        for job in self.store.all():
            if job.status == PENDING and (job_id is None or job.id == job_id):
                job.next_attempt_at = 0.0
                self.store.save(job)
        self._wake.set()
        return count

    def remake_memo(self, job_id: str, names: Dict[str, str], resend_email: bool = True) -> bool:
        """
        Create the memo again with corrected speaker names. Uses the cached
        transcription, so nothing is transcribed again.
        """
        job = self.store.get(job_id)
        if not job or job.status in (RECORDING, PROCESSING):
            return False  # still recording, or a memo is being made right now
        job.speaker_overrides = {sid: name.strip() for sid, name in names.items()
                                 if name and name.strip()}
        if job.memo_file and os.path.exists(job.memo_file):
            os.remove(job.memo_file)
        job.memo_file = None
        job.uploaded = False
        if resend_email:
            job.emailed = False
        job.status = PENDING
        job.attempts = 0
        job.last_error = None
        job.next_attempt_at = 0.0
        self.store.save(job)
        self._wake.set()
        return True

    # --- settings ----------------------------------------------------------

    def update_config(self, config: NotetakerConfig):
        """Save new settings and retry everything that failed before"""
        with self._lock:
            config.save(self.config_path)
            try:
                os.chmod(self.config_path, 0o600)  # holds API key and passwords
            except OSError:
                pass
            self.config = config
            self.store = JobStore(config.service.recordings_dir)
            self.feedback.lang = config.service.ui_language
            if getattr(self.feedback, 'voice', None):
                self.feedback.voice.lang = config.service.ui_language
        self.retry()
        self._event('ev_settings_saved')

    def status(self) -> Dict[str, Any]:
        jobs = self.store.all()
        free = free_bytes(self.store.directory)
        return {
            'recording': self.is_recording,
            'recording_seconds': self.recording_seconds,
            'max_recording_minutes': self.config.max_recording_minutes,
            'api_key_set': bool(self.config.voxtral.resolved_api_key()),
            'email_ready': self.config.email.ready,
            'counts': summarize_jobs(jobs),
            'jobs': jobs,
            'last_event': self.last_event,
            'live_items': list(self.live_items),
            'free_bytes': free,
            'free_text': format_size(free),
            'storage_low': free < self.config.service.min_free_mb * MB,
            'time': datetime.now().isoformat(timespec='seconds'),
        }
