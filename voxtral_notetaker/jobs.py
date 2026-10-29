# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Processing queue for recordings: survives reboots and retries when offline.

Each recording has a status file next to it (meeting_….wav -> meeting_….job.json).
Processing runs in stages (memo, upload, email); a retry only repeats the
stages that are not done yet.
"""

import os
import json
import time
import glob
import socket
import smtplib
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field, asdict

import httpx

from .audio import repair_wav, wav_duration
from .config import NotetakerConfig, Language
from .notify import build_memo_email, send_email, memo_subject
from .i18n import t
from .fsutil import atomic_replace

RECORDING = 'recording'
PENDING = 'pending'
PROCESSING = 'processing'
DONE = 'done'
FAILED = 'failed'  # needs the user: wrong API key, bad settings, broken file

MAX_RETRY_SECONDS = 3600


class PermanentError(Exception):
    """An error retrying will not fix, e.g. a rejected API key"""


@dataclass
class Job:
    id: str
    audio_file: str
    status: str = PENDING
    started_at: Optional[str] = None     # meeting start, ISO format
    duration: Optional[float] = None
    title: Optional[str] = None
    language: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None
    next_attempt_at: float = 0.0
    memo_file: Optional[str] = None
    transcript_file: Optional[str] = None
    uploaded: bool = False
    upload_urls: List[str] = field(default_factory=list)
    emailed: bool = False
    noise_reduced: bool = False
    audio_deleted: bool = False
    speakers: Dict[str, str] = field(default_factory=dict)           # id -> name in the memo
    speaker_overrides: Dict[str, str] = field(default_factory=dict)  # names set by the user
    updated_at: Optional[str] = None

    @property
    def job_file(self) -> str:
        return job_path(self.audio_file)

    @property
    def start_datetime(self) -> Optional[datetime]:
        return datetime.fromisoformat(self.started_at) if self.started_at else None


def job_path(audio_file: str) -> str:
    return os.path.splitext(audio_file)[0] + '.job.json'


def classify_error(error: Exception) -> bool:
    """True when retrying later may help (network, rate limit, server error)"""
    if isinstance(error, PermanentError):
        return False
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        return code in (408, 409, 425, 429) or code >= 500
    # SMTP errors are OSErrors too, so check them before the network errors
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return False
    if isinstance(error, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return True
    if isinstance(error, smtplib.SMTPResponseException):
        return 400 <= error.smtp_code < 500  # 4xx = temporary in SMTP
    if isinstance(error, smtplib.SMTPException):
        return False
    if isinstance(error, (httpx.TransportError, socket.error, TimeoutError)):
        return True
    return False


def describe_error(error: Exception, lang: str = 'de') -> str:
    """A message the user can act on"""
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code in (401, 403):
            return t('err_api_key_rejected', lang, code=code)
        if code == 404:
            return t('err_model_not_found', lang, code=code)
        return t('err_api', lang, code=code, detail=error.response.text[:200])
    if isinstance(error, httpx.TransportError):
        return t('err_offline', lang)
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return t('err_email_login', lang)
    if isinstance(error, PermanentError):
        return str(error)
    return f"{type(error).__name__}: {error}"


class JobStore:
    """Job files in the recordings directory"""

    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    def new_recording_path(self, now: Optional[datetime] = None) -> str:
        now = now or datetime.now()
        return os.path.join(self.directory, f"meeting_{now.strftime('%Y%m%d_%H%M%S')}.wav")

    def save(self, job: Job):
        job.updated_at = datetime.now().isoformat(timespec='seconds')
        tmp = job.job_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(asdict(job), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        atomic_replace(tmp, job.job_file)

    def load(self, path: str) -> Optional[Job]:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            known = Job.__dataclass_fields__
            return Job(**{k: v for k, v in data.items() if k in known})
        except (OSError, ValueError, TypeError):
            return None

    def get(self, job_id: str) -> Optional[Job]:
        return next((j for j in self.all() if j.id == job_id), None)

    def create(self, audio_file: str, status: str = RECORDING,
               started_at: Optional[datetime] = None) -> Job:
        job = Job(
            id=os.path.splitext(os.path.basename(audio_file))[0],
            audio_file=audio_file,
            status=status,
            started_at=(started_at or datetime.now()).isoformat(timespec='seconds'),
        )
        self.save(job)
        return job

    def all(self) -> List[Job]:
        """All jobs, newest first"""
        jobs = [self.load(p) for p in glob.glob(os.path.join(self.directory, '*.job.json'))]
        jobs = [j for j in jobs if j]
        return sorted(jobs, key=lambda j: j.started_at or '', reverse=True)

    def recover(self) -> List[Job]:
        """
        After a crash or reboot: repair interrupted recordings and queue them.
        Recordings without a job file (copied in by hand) are queued too.
        """
        recovered = []
        for job in self.all():
            if job.status in (RECORDING, PROCESSING):
                if job.status == RECORDING:
                    repair_wav(job.audio_file)
                    job.duration = wav_duration(job.audio_file)
                job.status = PENDING
                job.next_attempt_at = 0.0
                self.save(job)
                recovered.append(job)
        for wav in glob.glob(os.path.join(self.directory, '*.wav')):
            if not os.path.exists(job_path(wav)):
                job = self.create(wav, status=PENDING,
                                  started_at=datetime.fromtimestamp(os.path.getmtime(wav)))
                job.duration = wav_duration(wav)
                self.save(job)
                recovered.append(job)
        return recovered

    def due(self, now: Optional[float] = None) -> List[Job]:
        """Pending jobs ready to be (re)tried, oldest first"""
        now = time.time() if now is None else now
        jobs = [j for j in self.all() if j.status == PENDING and j.next_attempt_at <= now]
        return list(reversed(jobs))

    def retry(self, job_id: Optional[str] = None) -> int:
        """Queue failed jobs again (all, or one); returns how many"""
        count = 0
        for job in self.all():
            if job.status == FAILED and (job_id is None or job.id == job_id):
                job.status = PENDING
                job.next_attempt_at = 0.0
                job.attempts = 0
                job.last_error = None
                self.save(job)
                count += 1
        return count


class JobProcessor:
    """Runs the memo, upload and email stages for a job"""

    def __init__(self, config: NotetakerConfig, store: JobStore,
                 notetaker_factory: Optional[Callable] = None):
        self.config = config
        self.store = store
        if notetaker_factory is None:
            from .core import Notetaker
            notetaker_factory = Notetaker
        self.notetaker_factory = notetaker_factory

    @property
    def lang(self) -> str:
        return self.config.service.ui_language

    def process(self, job: Job) -> Job:
        job.status = PROCESSING
        job.attempts += 1
        self.store.save(job)
        try:
            self._run_stages(job)
            job.status = DONE
            job.last_error = None
        except Exception as e:
            job.last_error = describe_error(e, self.lang)
            limit = self.config.service.max_attempts
            if classify_error(e) and not (limit and job.attempts >= limit):
                job.status = PENDING
                delay = self.config.service.retry_interval_seconds * 2 ** (job.attempts - 1)
                job.next_attempt_at = time.time() + min(delay, MAX_RETRY_SECONDS)
            else:
                job.status = FAILED
        self.store.save(job)
        return job

    def _run_stages(self, job: Job):
        from .core import transcription_cache_path
        has_audio = os.path.exists(job.audio_file)
        if not has_audio and not os.path.exists(transcription_cache_path(job.audio_file)):
            raise PermanentError(t('err_recording_missing', self.lang, path=job.audio_file))

        if has_audio and self.config.audio.noise_reduction and not job.noise_reduced:
            from .audio import reduce_noise_file
            reduce_noise_file(job.audio_file)
            job.noise_reduced = True  # once only, even if noisereduce is missing
            self.store.save(job)
        
        if not job.memo_file or not os.path.exists(job.memo_file):
            self._make_memo(job)
            self.store.save(job)  # memo is safe even if upload/email fail later

        if self.config.storage.auto_upload and not job.uploaded:
            self._upload(job)
            self.store.save(job)

        if self.config.email.ready and not job.emailed:
            self._email(job)

    def _make_memo(self, job: Job):
        if not self.config.voxtral.resolved_api_key():
            raise PermanentError(t('err_no_api_key', self.lang))
        language = self.config.service.language or 'auto'
        try:
            lang = Language(language)
        except ValueError:
            lang = Language.AUTO
        notetaker = self.notetaker_factory(self.config)
        for speaker_id, name in job.speaker_overrides.items():
            notetaker.set_speaker_name(speaker_id, name)
        try:
            result = notetaker.process_recording(
                job.audio_file, language=lang, start_time=job.start_datetime,
                duration=job.duration or wav_duration(job.audio_file) or None,
                upload=False,
            )
        finally:
            notetaker.close()
        job.memo_file = result.memo_file
        job.transcript_file = result.transcript_file
        job.title = result.memo.title if result.memo else job.id
        job.language = result.language
        job.duration = result.duration
        job.speakers = {seg['speaker_id']: seg['speaker_name']
                        for seg in (getattr(result, 'speaker_segments', None) or [])}

    def _upload(self, job: Job):
        from .storage import CloudStorage
        storage = CloudStorage(self.config.storage)
        urls, errors = [], []
        for path in (job.audio_file, job.transcript_file, job.memo_file):
            if not path or not os.path.exists(path):
                continue
            for result in storage.upload(path):
                if result.success:
                    if result.url:
                        urls.append(result.url)
                else:
                    errors.append(f"{result.provider}: {result.error}")
        job.upload_urls = urls
        if errors:
            # Treated as temporary: cloud services are often just unreachable
            raise ConnectionError(t('err_upload', self.lang, detail="; ".join(errors)))
        job.uploaded = True

    def _email(self, job: Job):
        with open(job.memo_file, encoding='utf-8') as f:
            body = f.read()
        if job.upload_urls:
            body += "\n\n---\n" + "\n".join(job.upload_urls)
        attachments = [job.memo_file]
        if self.config.email.attach_transcript:
            attachments.append(job.transcript_file)
        if self.config.email.attach_audio:
            attachments.append(job.audio_file)
        msg = build_memo_email(self.config.email, memo_subject(job.title or job.id, job.language),
                               body, attachments)
        send_email(self.config.email, msg)
        job.emailed = True


def summarize_jobs(jobs: List[Job]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for job in jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    return counts
