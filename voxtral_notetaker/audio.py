# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Lean audio recording for conference microphones (Jabra, etc.)

Audio is written to disk while recording, so a crash or power cut loses
seconds, not the meeting.
"""

import os
import wave
import time
import struct
import threading
from typing import Optional, List
from dataclasses import dataclass

import numpy as np

try:
    import noisereduce as nr
    HAS_NOISEREDUCE = True
except ImportError:
    HAS_NOISEREDUCE = False

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

from .config import AudioConfig
from .fsutil import atomic_replace


# Force buffered audio onto the SD card at least this often (seconds)
FSYNC_INTERVAL = 2.0
# Noise reduction works on chunks of this length (seconds) to bound memory use
NOISE_CHUNK_SECONDS = 60


@dataclass
class RecordingInfo:
    file_path: str
    duration: float
    sample_rate: int


def repair_wav(path: str) -> bool:
    """
    Fix the size fields of a WAV file that was cut off (crash, power loss).
    
    Returns True when the file is readable afterwards.
    """
    try:
        size = os.path.getsize(path)
        if size < 44:
            return False
        with open(path, 'r+b') as f:
            header = f.read(44)
            if header[:4] != b'RIFF' or header[8:12] != b'WAVE' or header[36:40] != b'data':
                return False
            block_align = struct.unpack('<H', header[32:34])[0] or 1
            data_size = size - 44
            data_size -= data_size % block_align  # drop a partial last frame
            f.seek(4)
            f.write(struct.pack('<I', 36 + data_size))
            f.seek(40)
            f.write(struct.pack('<I', data_size))
            f.truncate(44 + data_size)
        with wave.open(path, 'rb'):
            return True
    except (OSError, wave.Error, struct.error):
        return False


def wav_duration(path: str) -> float:
    try:
        with wave.open(path, 'rb') as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except (OSError, wave.Error, EOFError):
        return 0.0


def reduce_noise(audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
    """Apply noise reduction to 16-bit samples (unchanged if noisereduce is missing)"""
    if not HAS_NOISEREDUCE:
        return audio_data
    try:
        reduced = nr.reduce_noise(y=audio_data.astype(np.float32), sr=sample_rate,
                                  stationary=True, prop_decrease=0.8)
        # noisereduce returns floats; convert back to 16-bit PCM for the WAV file
        return np.clip(reduced, -32768, 32767).astype(np.int16)
    except Exception:
        return audio_data


def reduce_noise_file(path: str) -> bool:
    """
    Apply noise reduction to a WAV file in place, chunk by chunk.
    
    Slow for long meetings, so the service runs it in the background.
    """
    if not HAS_NOISEREDUCE:
        return False
    tmp = f"{path}.nr.tmp"
    try:
        with wave.open(path, 'rb') as src, wave.open(tmp, 'wb') as dst:
            dst.setparams(src.getparams())
            rate = src.getframerate()
            chunk = rate * NOISE_CHUNK_SECONDS
            while True:
                data = src.readframes(chunk)
                if not data:
                    break
                samples = np.frombuffer(data, dtype=np.int16)
                dst.writeframes(reduce_noise(samples, rate).astype(np.int16).tobytes())
        atomic_replace(tmp, path)  # the original stays untouched until this point
        return True
    except Exception as e:
        print(f"Noise reduction skipped: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


class AudioRecorder:
    """Audio recorder optimized for conference microphones"""
    
    def __init__(self, config: AudioConfig):
        self.config = config
        self.audio = pyaudio.PyAudio() if HAS_PYAUDIO else None
        self._is_recording = False
        self._stream = None
        self._output_file: Optional[str] = None
        self._file = None
        self._wav = None
        self._lock = threading.Lock()
        self._frames_written = 0
        self._last_sync = 0.0
        self._start_time: Optional[float] = None
        self.device_name: Optional[str] = None
        
        if not HAS_PYAUDIO:
            print("⚠️  Audio recording disabled: PyAudio not available")
    
    def _list_devices(self):
        """List available audio input devices"""
        if not HAS_PYAUDIO or not self.audio:
            return []
        
        devices = []
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev.get('maxInputChannels', 0) > 0:
                name = dev.get('name', '').lower()
                if 'jabra' in name or 'spider' in name or 'conference' in name:
                    print(f"Found conference mic: {dev.get('name')} (index {i})")
                devices.append(dev)
        return devices
    
    def _get_device_index(self) -> int:
        """Get Jabra or first available input device"""
        if self.config.device_index is not None:
            return self.config.device_index
        
        if not HAS_PYAUDIO or not self.audio:
            return 0
        
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev.get('maxInputChannels', 0) > 0:
                name = dev.get('name', '').lower()
                if 'jabra' in name or 'spider' in name:
                    return i
        
        return self.audio.get_default_input_device_info()['index']
    
    def _audio_callback(self, in_data: bytes, frame_count: int, time_info, status):
        self._write(in_data, frame_count)
        return (in_data, pyaudio.paContinue)
    
    def _open_file(self, output_file: str):
        os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
        self._file = open(output_file, 'wb')
        self._wav = wave.open(self._file, 'wb')
        self._wav.setnchannels(self.config.channels)
        self._wav.setsampwidth(2)
        self._wav.setframerate(self.config.sample_rate)
        self._frames_written = 0
        self._last_sync = time.time()
    
    def _write(self, data: bytes, frame_count: int):
        """Append audio to the WAV file (called from the audio thread)"""
        with self._lock:
            if not self._is_recording or self._wav is None:
                return
            try:
                # wave rewrites the header sizes on every write, so the file is
                # valid on disk at all times
                self._wav.writeframes(data)
                self._frames_written += frame_count
                now = time.time()
                if now - self._last_sync >= FSYNC_INTERVAL:
                    self._file.flush()
                    os.fsync(self._file.fileno())
                    self._last_sync = now
            except (OSError, ValueError) as e:
                print(f"Writing audio failed: {e}")
    
    def _close_file(self):
        with self._lock:
            if self._wav is not None:
                try:
                    self._wav.close()
                except (OSError, wave.Error):
                    pass
                self._wav = None
            if self._file is not None:
                try:
                    self._file.flush()
                    os.fsync(self._file.fileno())
                except (OSError, ValueError):
                    pass
                self._file.close()
                self._file = None
    
    @property
    def recorded_seconds(self) -> float:
        return self._frames_written / float(self.config.sample_rate)
    
    def start_recording(self, output_file: str) -> bool:
        """Start recording from conference microphone"""
        if self._is_recording:
            return False
        
        if not HAS_PYAUDIO or not self.audio:
            print("⚠️  Cannot start recording: PyAudio not available")
            return False
        
        try:
            device_index = self._get_device_index()
            self.device_name = self.audio.get_device_info_by_index(device_index).get('name')
            print(f"Recording from: {self.device_name}")
            self._open_file(output_file)
            self._output_file = output_file
            self._start_time = time.time()
            self._is_recording = True
            
            self._stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=1024,
                input_device_index=device_index,
                stream_callback=self._audio_callback
            )
            return True
        except Exception as e:
            print(f"Failed to start: {e}")
            self._is_recording = False
            self._close_file()
            return False
    
    def stop_recording(self) -> Optional[RecordingInfo]:
        """Stop recording and save to file"""
        if not self._is_recording:
            return None
        
        self._close_stream()
        self._is_recording = False
        self._close_file()
        
        if not self._frames_written:
            return None
        
        if self.config.noise_reduction:
            reduce_noise_file(self._output_file)
        
        return RecordingInfo(file_path=self._output_file, duration=self.recorded_seconds,
                             sample_rate=self.config.sample_rate)
    
    def _reduce_noise(self, audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
        return reduce_noise(audio_data, sample_rate)
    
    def _save_wav(self, audio_data: np.ndarray, sample_rate: int, file_path: str):
        """Save audio as WAV file"""
        os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
        with wave.open(file_path, 'wb') as wf:
            wf.setnchannels(self.config.channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.astype(np.int16).tobytes())
    
    def is_recording(self) -> bool:
        return self._is_recording
    
    def get_available_devices(self) -> List[dict]:
        """Get list of available audio input devices"""
        if not HAS_PYAUDIO or not self.audio:
            return []
        
        devices = []
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev.get('maxInputChannels', 0) > 0:
                devices.append({
                    'index': i,
                    'name': dev.get('name', 'Unknown'),
                    'channels': dev.get('maxInputChannels')
                })
        return devices
    
    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
    
    def close(self):
        """Close the audio recorder"""
        self._close_stream()
        self._is_recording = False
        self._close_file()
        if self.audio:
            self.audio.terminate()
            self.audio = None
        self._is_recording = False
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
