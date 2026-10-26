"""
Voice commands during the meeting, confirmed out loud.

While recording, the newest audio is transcribed with the fast Mini model every
live_interval_seconds. "Mach eine Notiz: …" is answered with "Notiz notiert",
"Beende die Aufnahme" stops the recording. This is feedback only: the memo is
still made from the whole recording with the accurate model at the end.
"""

import os
import wave
import logging
import tempfile
import threading
from typing import Callable, Optional

from .config import NotetakerConfig, Language
from .commands import CommandType, split_transcript

log = logging.getLogger(__name__)

# Audio repeated from the previous chunk, so a command cut at the edge is still heard
OVERLAP_SECONDS = 2.0
KIND = {CommandType.NOTE: 'note', CommandType.TASK: 'task', CommandType.RESEARCH: 'research'}


def read_new_audio(path: str, start_frame: int, out_path: str) -> int:
    """
    Copy frames from start_frame to the current end of a WAV that is still being
    written into out_path. Returns the end frame (0 if nothing new).
    """
    with wave.open(path, 'rb') as src:
        end = src.getnframes()
        if end <= start_frame:
            return 0
        src.setpos(start_frame)
        data = src.readframes(end - start_frame)
        params = src.getparams()
    with wave.open(out_path, 'wb') as dst:
        dst.setparams(params)
        dst.writeframes(data)
    return end


class LiveListener:
    """Checks the running recording for voice commands in a background thread"""

    def __init__(self, config: NotetakerConfig, audio_file: str,
                 notetaker_factory: Callable,
                 on_item: Callable[[str, str], None],
                 on_stop: Callable[[], None]):
        self.config = config
        self.audio_file = audio_file
        self.notetaker_factory = notetaker_factory
        self.on_item = on_item      # (kind, text) for notes, tasks, research
        self.on_stop = on_stop      # "Beende die Aufnahme"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._position = 0          # frames already checked
        self._notetaker = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="live")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        if self._notetaker:
            self._notetaker.close()

    def _run(self):
        interval = max(5, self.config.service.live_interval_seconds)
        while not self._stop.wait(interval):
            try:
                self.check_once()
            except Exception as e:
                # Never disturb the meeting: the memo is made from the full recording anyway
                log.info("Live check skipped: %s", e)

    def _language(self) -> Language:
        try:
            return Language(self.config.service.language or 'auto')
        except ValueError:
            return Language.AUTO

    def check_once(self) -> int:
        """Transcribe the audio since the last check; returns commands handled"""
        if not self.config.voxtral.resolved_api_key() or not os.path.exists(self.audio_file):
            return 0
        with wave.open(self.audio_file, 'rb') as wf:
            rate = wf.getframerate()
        start = max(0, self._position - int(OVERLAP_SECONDS * rate))
        fd, chunk = tempfile.mkstemp(suffix='.wav', prefix='live_')
        os.close(fd)
        try:
            end = read_new_audio(self.audio_file, start, chunk)
            if not end:
                return 0
            self._position = end
            if self._notetaker is None:
                self._notetaker = self.notetaker_factory(self.config)
            result = self._notetaker.transcribe(chunk, self._language(), fast=True)
        finally:
            os.remove(chunk)
        return self.handle_text(result.text, result.language)

    def handle_text(self, text: str, language: str) -> int:
        handled = 0
        executor = self._notetaker._command_executor
        parser = executor._parser
        for _speaker, sentence in split_transcript(text):
            command = parser.parse(sentence, language, strict=True)
            if not command:
                continue
            if command.command_type == CommandType.RECORDING:
                if command.parameters.get('action') == 'stop':
                    log.info("Voice command: stop recording")
                    self.on_stop()
                    return handled + 1
                continue
            if command.command_type in KIND and not executor._is_duplicate(command):
                executor._dispatch(command)  # remembered, so the overlap is not repeated
                content = command.parameters.get('content') or command.parameters.get('query')
                self.on_item(KIND[command.command_type], content or '')
                handled += 1
        return handled
