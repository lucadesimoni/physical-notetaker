# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Language flips: in a German or Swiss German meeting, speech recognition with
speaker labels (language detected automatically) sometimes writes a short or
unclear passage in English ("If I'm in the eating"). Such segments are found
here by their function words and transcribed again with German fixed.
"""

import logging
import re

log = logging.getLogger(__name__)

ENGLISH = frozenset("""
    the and is are was were i i'm i've you you're we they it it's this that these those
    of to for with be have has had a an my me if will would what not do does don't so
    on at but there here can could should just like know think
""".split())
GERMAN = frozenset("""
    der die das den dem des und ist sind ich wir ihr nicht ein eine einen einem zu mit
    auf für es sie er im auch noch aber wenn dann so ja nein hat haben wird werden von
    dass wie was oder mir mich dir uns isch händ mer nöd au
""".split()) - {"so"}

_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


def looks_english(text: str) -> bool:
    """Does this text read as English (and not German)?"""
    words = [w.lower() for w in _WORD.findall(text or "")]
    if len(words) < 3:
        return False
    english = sum(w in ENGLISH for w in words)
    german = sum(w in GERMAN for w in words)
    return german == 0 and english >= 2 and english >= 0.3 * len(words)


def looks_german(text: str) -> bool:
    words = [w.lower() for w in _WORD.findall(text or "")]
    return bool(words) and sum(w in GERMAN for w in words) >= 1 and not looks_english(text)


MAX_REDOS = 20      # bounds the extra cost of one meeting
PAD_SECONDS = 0.3   # a little audio around the segment


def cut_wav(source: str, start: float, end: float, target: str) -> bool:
    """Write the part start..end of a WAV file to target"""
    import wave
    try:
        with wave.open(source, 'rb') as wf:
            rate = wf.getframerate()
            first = max(0, int((start - PAD_SECONDS) * rate))
            last = min(wf.getnframes(), int((end + PAD_SECONDS) * rate))
            if last <= first:
                return False
            wf.setpos(first)
            frames = wf.readframes(last - first)
            params = wf.getparams()
        with wave.open(target, 'wb') as out:
            out.setparams(params)
            out.writeframes(frames)
        return True
    except (OSError, EOFError, wave.Error):
        return False


def fix_language_flips(audio_file: str, transcription, transcribe) -> int:
    """
    Transcribe segments that came out in English again with German fixed, and
    keep the new text where it is German. transcribe(path) -> text.
    Returns how many segments were replaced.
    """
    import os
    import tempfile
    flipped = [seg for seg in transcription.segments if looks_english(seg.text)]
    if not flipped or not os.path.exists(audio_file):
        return 0
    fixed = 0
    for seg in flipped[:MAX_REDOS]:
        handle, path = tempfile.mkstemp(suffix='.wav')
        os.close(handle)
        try:
            if not cut_wav(audio_file, seg.start, seg.end, path):
                continue
            text = (transcribe(path) or '').strip()
            if looks_german(text):
                seg.text = text
                fixed += 1
        except Exception as e:  # a failed redo keeps the segment as it was
            log.warning("Language check: redo failed: %s", e)
        finally:
            os.remove(path)
    if fixed:
        transcription.text = ' '.join(seg.text for seg in transcription.segments if seg.text)
    log.info("Language check: %d of %d English segment(s) redone in German", fixed, len(flipped))
    return fixed
