"""
The always-on notetaker: one button to start and stop, everything else automatic.

- Recovers recordings interrupted by a crash or power cut at startup
- Start/stop from a GPIO button, the speakerphone button or the web page
- Stops automatically at max_recording_minutes (warning beep 5 minutes before)
- Processes recordings in the background and retries when offline
"""

import os
import time
import signal
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from .config import NotetakerConfig, find_config_path, load_config
from .jobs import JobStore, JobProcessor, Job, PENDING, RECORDING, FAILED, summarize_jobs
from .device import Feedback, Controls

log = logging.getLogger(__name__)

WARN_BEFORE_LIMIT_SECONDS = 5 * 60


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
        self.feedback = feedback or Feedback(self.config.device, self.config.audio)
        self.poll_seconds = poll_seconds

        self.store = JobStore(self.config.service.recordings_dir)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._recorder = None
        self._current: Optional[Job] = None
        self._recording_since: Optional[float] = None
        self._warned = False
        self._worker: Optional[threading.Thread] = None
        self._controls: Optional[Controls] = None
        self._web = None
        self.last_event: str = ""

    # --- lifecycle ---------------------------------------------------------

    def start(self, web: bool = True, controls: bool = True):
        recovered = self.store.recover()
        if recovered:
            log.info("Recovered %d recording(s) after restart", len(recovered))
            self.last_event = f"{len(recovered)} recording(s) recovered after restart"

        self._worker = threading.Thread(target=self._work_loop, daemon=True, name="worker")
        self._worker.start()

        if controls:
            self._controls = Controls(self.config.device, self.toggle)
            self._controls.start()

        if web and self.config.web.enabled:
            from .web import start_web_server
            self._web = start_web_server(self)
            if self.config.web.setup_hotspot:
                threading.Thread(target=self._hotspot_if_offline, daemon=True).start()

        self.feedback.ready()
        log.info("Notetaker ready")

    def run_forever(self, web: bool = True):
        """Run until stopped (Ctrl+C or systemd stop)"""
        # systemd stops services with SIGTERM: shut down cleanly so the
        # current recording is saved and queued
        signal.signal(signal.SIGTERM, lambda *_: self._stop.set())
        self.start(web=web)
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

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
            self.last_event = (f"No network: connect to Wi-Fi '{web.hotspot_ssid}' "
                               f"and open http://10.42.0.1:{web.port}")
            log.info(self.last_event)
    
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
            path = self.store.new_recording_path()
            # Noise reduction runs later in the background, so stopping is instant
            config = NotetakerConfig.from_dict(self.config.to_dict())
            config.audio.noise_reduction = False
            recorder = self.notetaker_factory(config)
            if not recorder.start_recording(path):
                recorder.close()
                self.feedback.error()
                self.last_event = "Could not start recording: is the microphone connected?"
                log.error(self.last_event)
                return False
            self._recorder = recorder
            self._current = self.store.create(path, status=RECORDING)
            self._recording_since = time.time()
            self._warned = False
            self.feedback.recording()
            self.last_event = "Recording started"
            log.info("Recording started: %s", path)
            return True

    def stop_meeting(self) -> Optional[Job]:
        with self._lock:
            if not self.is_recording:
                return None
            job, recorder = self._current, self._recorder
            self._current = self._recorder = None
            self._recording_since = None
            try:
                info = recorder.stop_recording()
            finally:
                recorder.close()

            if not info:
                job.status = FAILED
                job.last_error = "No audio was recorded. Is the microphone connected?"
                self.store.save(job)
                self.feedback.error()
                self.last_event = job.last_error
                return job

            job.duration = info.duration
            job.status = PENDING
            job.next_attempt_at = 0.0
            self.store.save(job)
            self.feedback.stopped()
            self.last_event = "Recording saved, creating memo"
            log.info("Recording stopped (%.0f s): %s", info.duration, job.audio_file)
            self._wake.set()
            return job

    def tick(self):
        """Enforce the recording time limit"""
        if not self.is_recording:
            return
        limit = self.config.max_recording_minutes * 60
        elapsed = self.recording_seconds
        if not self._warned and limit > WARN_BEFORE_LIMIT_SECONDS \
                and elapsed >= limit - WARN_BEFORE_LIMIT_SECONDS:
            self._warned = True
            self.feedback.warning()
        if elapsed >= limit:
            log.info("Maximum recording time reached, stopping")
            self.stop_meeting()
            self.last_event = "Stopped at the maximum recording time"

    # --- processing --------------------------------------------------------

    def _work_loop(self):
        while not self._stop.is_set():
            self.process_due()
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
                log.error("%s failed: %s", job.id, job.last_error)
                if not self.is_recording:
                    self.feedback.error()
                self.last_event = f"Problem with {job.id}: {job.last_error}"
            elif job.status == PENDING:
                log.warning("%s will be retried: %s", job.id, job.last_error)
            else:
                log.info("%s done: %s", job.id, job.memo_file)
                if not self.is_recording:
                    self.feedback.idle()
                self.last_event = f"Memo ready: {job.title or job.id}"
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
        self.retry()
        self.last_event = "Settings saved"

    def status(self) -> Dict[str, Any]:
        jobs = self.store.all()
        return {
            'recording': self.is_recording,
            'recording_seconds': self.recording_seconds,
            'max_recording_minutes': self.config.max_recording_minutes,
            'api_key_set': bool(self.config.voxtral.resolved_api_key()),
            'email_ready': self.config.email.ready,
            'counts': summarize_jobs(jobs),
            'jobs': jobs,
            'last_event': self.last_event,
            'time': datetime.now().isoformat(timespec='seconds'),
        }
