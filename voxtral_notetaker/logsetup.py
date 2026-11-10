# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Logging for the always-on notetaker.

- Log file (logs/notetaker.log): detailed, timestamped, with thread names and
  full tracebacks; rotates at 5 MB, keeps 5 old files. Made for debugging.
- Console: only short status lines ("14:03  Aufnahme gestartet") and real
  problems, so the window stays readable.
- Secrets (API key, email password, PIN) are blanked out wherever they appear.
  What was said in meetings is never logged, only sizes and counts.
"""

import os
import sys
import logging
import platform
import threading
from logging.handlers import RotatingFileHandler
from typing import Iterable, Optional

LOG_FILE_NAME = "notetaker.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
FILE_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"

# Our own status messages for the console window
STATUS_LOGGER = "voxtral_notetaker.status"
# Chatty libraries: keep their detail out of the log unless it matters
QUIET_LIBRARIES = {"httpcore": logging.WARNING, "urllib3": logging.WARNING,
                   "asyncio": logging.WARNING, "PIL": logging.WARNING,
                   "httpx": logging.INFO}


class SecretFilter(logging.Filter):
    """Replace known secrets in every log line with ***"""

    def __init__(self):
        super().__init__()
        self.secrets = []

    def set_secrets(self, secrets: Iterable[Optional[str]]):
        # Short values (e.g. an empty or 1-char string) would blank random text
        self.secrets = sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            message = record.getMessage()
            redacted = message
            for secret in self.secrets:
                redacted = redacted.replace(secret, "***")
            if redacted != message:
                record.msg, record.args = redacted, ()
        return True


class ConsoleFilter(logging.Filter):
    """Status lines, plus warnings and errors of our own code, plus any error"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == STATUS_LOGGER:
            return True
        if record.name.startswith("voxtral_notetaker"):
            return record.levelno >= logging.WARNING
        return record.levelno >= logging.ERROR


SECRETS = SecretFilter()
_log_file: Optional[str] = None


def status(message: str):
    """A line for the console window (and the log file)"""
    logging.getLogger(STATUS_LOGGER).info(message)


def secrets_from_config(config) -> list:
    return [config.voxtral.api_key, config.voxtral.resolved_api_key(),
            config.summary.api_key, config.email.smtp_password,
            config.email.resolved_password(), config.web.pin]


def log_file_path() -> Optional[str]:
    return _log_file


def setup_logging(config, log_dir: Optional[str] = None, verbose: bool = False,
                  console: bool = True) -> str:
    """Configure file and console logging; returns the log file path"""
    global _log_file
    log_dir = os.path.abspath(log_dir or config.service.log_dir or "logs")
    os.makedirs(log_dir, exist_ok=True)
    _log_file = os.path.join(log_dir, LOG_FILE_NAME)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.DEBUG)

    SECRETS.set_secrets(secrets_from_config(config))

    file_handler = RotatingFileHandler(_log_file, maxBytes=MAX_BYTES,
                                       backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    file_handler.addFilter(SECRETS)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        if verbose:
            console_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        else:
            console_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M"))
            console_handler.addFilter(ConsoleFilter())
        console_handler.addFilter(SECRETS)
        root.addHandler(console_handler)

    for name, level in QUIET_LIBRARIES.items():
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else level)

    _install_excepthooks()
    return _log_file


def _install_excepthooks():
    """Crashes, also in background threads, end up in the log with a traceback"""
    crash_log = logging.getLogger("voxtral_notetaker.crash")

    def main_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        crash_log.critical("Unhandled error", exc_info=(exc_type, exc, tb))

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        crash_log.critical("Unhandled error in thread %s",
                           args.thread.name if args.thread else "?",
                           exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def log_startup(config, config_path: str, version: str):
    """What is needed to debug a report: environment and settings, never secrets"""
    log = logging.getLogger("voxtral_notetaker.startup")
    log.info("=" * 60)
    log.info("Notetaker %s starting", version)
    log.info("System: %s %s (%s), Python %s", platform.system(), platform.release(),
             platform.machine(), platform.python_version())
    log.info("Config: %s (%s)", os.path.abspath(config_path),
             "found" if os.path.exists(config_path) else "not found, using defaults")
    log.info("Recordings: %s", os.path.abspath(config.service.recordings_dir))
    log.info("Meeting language: %s, device language: %s, dialect clean-up: %s",
             config.service.language, config.service.ui_language,
             config.voxtral.dialect_cleanup)
    log.info("Models: transcription %s, fast %s, summary %s",
             config.voxtral.model, config.voxtral.fast_model, config.summary.model)
    log.info("Mistral API key: %s, vocabulary: %d term(s)",
             "set" if config.voxtral.resolved_api_key() else "MISSING",
             len(config.voxtral.vocabulary))
    log.info("Email: %s, upload: %s (%s)",
             f"to {len(config.email.to_emails)} recipient(s)" if config.email.ready else "off",
             config.storage.auto_upload, config.storage.provider.value)
    log.info("Web page: %s:%s, PIN %s", config.web.host, config.web.port,
             "set" if config.web.pin else "not set")
    log.info("Device: voice %s, live commands %s, button GPIO %s, input device '%s'",
             config.device.voice, config.service.live_commands,
             config.device.button_gpio, config.device.input_device)
