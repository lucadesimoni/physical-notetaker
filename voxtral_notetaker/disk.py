"""
Keep the SD card from filling up: delete audio of finished meetings.

Only audio is deleted; memos and transcripts are kept. Audio of meetings that
are not finished (no memo yet, upload or email still pending) is never touched.
"""

import os
import time
import shutil
import logging
from typing import List

from .config import NotetakerConfig
from .jobs import DONE, Job, JobStore

log = logging.getLogger(__name__)

MB = 1024 * 1024
# Below this, a new recording is refused / a running one is stopped and saved
HARD_MIN_FREE_BYTES = 100 * MB
STOP_RECORDING_FREE_BYTES = 50 * MB


def free_bytes(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def format_size(n: int) -> str:
    if n >= 1024 * MB:
        return f"{n / (1024 * MB):.1f} GB"
    return f"{n // MB} MB"


def is_finished(job: Job, config: NotetakerConfig) -> bool:
    """Everything that needs the audio is done"""
    if job.status != DONE or not job.memo_file:
        return False
    if config.email.ready and config.email.attach_audio and not job.emailed:
        return False
    if config.storage.auto_upload and not job.uploaded:
        return False
    return True


def _job_time(job: Job) -> float:
    try:
        return os.path.getmtime(job.audio_file)
    except OSError:
        return 0.0


def cleanup(store: JobStore, config: NotetakerConfig, now: float = None) -> List[Job]:
    """
    Delete audio older than keep_audio_days, then more of the oldest finished
    audio while free space is below min_free_mb. Returns the jobs changed.
    """
    now = time.time() if now is None else now
    candidates = sorted(
        (j for j in store.all()
         if not j.audio_deleted and os.path.exists(j.audio_file) and is_finished(j, config)),
        key=_job_time,
    )
    deleted: List[Job] = []

    def delete(job: Job, reason: str):
        try:
            os.remove(job.audio_file)
        except OSError as e:
            log.warning("Could not delete %s: %s", job.audio_file, e)
            return
        job.audio_deleted = True
        store.save(job)
        deleted.append(job)
        log.info("Deleted audio of %s (%s)", job.id, reason)

    days = config.service.keep_audio_days
    if days and days > 0:
        for job in list(candidates):
            if now - _job_time(job) > days * 86400:
                delete(job, f"older than {days} days")
                candidates.remove(job)

    min_free = config.service.min_free_mb * MB
    while candidates and free_bytes(store.directory) < min_free:
        delete(candidates.pop(0), "storage low")

    return deleted
