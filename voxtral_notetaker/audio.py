"""
Lean audio recording for conference microphones (Jabra, etc.)
"""

import os
import wave
import time
import queue
import threading
from typing import Optional, List
from dataclasses import dataclass

import numpy as np
import noisereduce as nr

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    print("⚠️  PyAudio not installed. Audio recording will be limited.")

from .config import AudioConfig


@dataclass
class RecordingInfo:
    file_path: str
    duration: float
    sample_rate: int


class AudioRecorder:
    """Audio recorder optimized for conference microphones"""
    
    def __init__(self, config: AudioConfig):
        self.config = config
        self.audio = pyaudio.PyAudio() if HAS_PYAUDIO else None
        self._is_recording = False
        self._audio_queue = queue.Queue()
        self._audio_data = []
        self._start_time: Optional[float] = None
        
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
        if self._is_recording:
            self._audio_queue.put(in_data)
            self._audio_data.append(in_data)
        return (in_data, pyaudio.paContinue)
    
    def start_recording(self, output_file: str) -> bool:
        """Start recording from conference microphone"""
        if self._is_recording:
            return False
        
        if not HAS_PYAUDIO or not self.audio:
            print("⚠️  Cannot start recording: PyAudio not available")
            return False
        
        try:
            device_index = self._get_device_index()
            
            self._stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=1024,
                input_device_index=device_index,
                stream_callback=self._audio_callback
            )
            
            self._is_recording = True
            self._audio_data = []
            self._start_time = time.time()
            return True
        except Exception as e:
            print(f"Failed to start: {e}")
            return False
    
    def stop_recording(self) -> Optional[RecordingInfo]:
        """Stop recording and save to file"""
        if not self._is_recording:
            return None
        
        self._is_recording = False
        
        if hasattr(self, '_stream'):
            self._stream.stop_stream()
            self._stream.close()
        
        if self._audio_data:
            audio_np = np.frombuffer(b''.join(self._audio_data), dtype=np.int16)
            
            # Apply noise reduction
            if self.config.noise_reduction:
                audio_np = self._reduce_noise(audio_np, self.config.sample_rate)
            
            # Save to WAV
            self._save_wav(audio_np, self.config.sample_rate, output_file)
            
            duration = time.time() - self._start_time
            return RecordingInfo(file_path=output_file, duration=duration, 
                                sample_rate=self.config.sample_rate)
        
        return None
    
    def _reduce_noise(self, audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
        """Apply noise reduction"""
        try:
            return nr.reduce_noise(y=audio_data, sr=sample_rate, stationary=True, prop_decrease=0.8)
        except:
            return audio_data
    
    def _save_wav(self, audio_data: np.ndarray, sample_rate: int, file_path: str):
        """Save audio as WAV file"""
        os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
        with wave.open(file_path, 'wb') as wf:
            wf.setnchannels(self.config.channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())
    
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
    
    def close(self):
        """Close the audio recorder"""
        if hasattr(self, '_stream'):
            self._stream.stop_stream()
            self._stream.close()
        if self.audio:
            self.audio.terminate()
        self._is_recording = False
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
